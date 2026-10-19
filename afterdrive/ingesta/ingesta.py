"""
ingesta.py — Artículos scrapeados -> Artículos guardados (o descartados).

Interfaz:
    ingerir(items) -> {"total", "aprobados", "rechazados", "detalles"}
    clasificar(titulo, cuerpo) -> {"aprobado": bool, "razon": str}

Acá vive el orden completo de la ingesta (clasificar, fichar, vectorizar,
guardar) y la cadena de clasificadores: Jev primero; si no está configurado o
falla, el clasificador LLM. Con la API paga en uso se saltea Jev y clasifica
ella. La política de modo degradado del clasificador LLM está documentada en
lm_studio.clasificar_articulo.

La ficha (lm_studio.fichar_articulo) es el resumen estructurado que después
usa la generación en lugar del cuerpo crudo. FICHAS_NOTICIAS=0 la apaga.
"""

import datetime
import os

from pymongo import UpdateOne

from afterdrive.db import col_articulos, col_descartados
from afterdrive.ia import llm, lm_studio
from afterdrive.ingesta import jev_clasificador
from afterdrive.ingesta.embeddings import texto_para_embedding


def fichas_activas() -> bool:
    """Las fichas cuestan una llamada barata por artículo aprobado; FICHAS_NOTICIAS=0 las apaga."""
    return os.getenv("FICHAS_NOTICIAS", "1").strip() != "0"


def clasificar(titulo: str, cuerpo: str) -> dict:
    # Con la API paga en uso (configurada y bajo el tope) clasifica ella: Jev no se consulta.
    if llm.usa_api_paga():
        return lm_studio.clasificar_articulo(titulo, cuerpo)
    veredicto = jev_clasificador.clasificar(titulo, cuerpo)
    if veredicto is not None:
        return veredicto
    return lm_studio.clasificar_articulo(titulo, cuerpo)


def ingerir(items: list[dict]) -> dict:
    """Clasifica cada artículo; guarda los aprobados con embedding y registra los rechazados.

    Los rechazados van a 'articulos_descartados' para que el scraper no los
    vuelva a procesar.
    """
    if not items:
        return {"total": 0, "aprobados": 0, "rechazados": 0, "detalles": []}

    aprobados, detalles = [], []
    total = len(items)
    for i, item in enumerate(items, 1):
        titulo = item.get("titulo", "(sin título)")
        cuerpo = item.get("cuerpo", item.get("bajada", ""))
        print(f"  Clasificando [{i}/{total}]: {titulo[:70]}", flush=True)

        veredicto = clasificar(titulo, cuerpo)
        if veredicto["aprobado"]:
            print("    -> Aprobado", flush=True)
            aprobados.append(item)
            detalles.append({"titulo": titulo, "estado": "aprobado"})
            continue

        razon = veredicto.get("razon", "")
        print(f"    -> Rechazado: {razon[:80]}", flush=True)
        # Además de la URL (que evita reprocesarlo) se guarda qué era y por qué
        # se rechazó, para el historial. El cuerpo se acota para no inflar la base.
        col_descartados.replace_one(
            {"url": item.get("url", "")},
            {
                "url": item.get("url", ""),
                "titulo": titulo,
                "cuerpo": (cuerpo or "")[:5000],
                "fuente": item.get("fuente", ""),
                "fecha": item.get("fecha", ""),
                "razon": razon,
                "fecha_descarte": datetime.datetime.now(datetime.UTC).isoformat(),
            },
            upsert=True,
        )
        detalles.append({"titulo": titulo, "estado": "rechazado", "razon": razon})

    if aprobados and fichas_activas():
        print(f"  Armando la ficha de {len(aprobados)} artículo(s) aprobado(s)...", flush=True)
        for item in aprobados:
            ficha = lm_studio.fichar_articulo(item.get("titulo", ""), item.get("cuerpo", item.get("bajada", "")))
            if ficha:
                item["ficha"] = ficha

    if aprobados:
        print(f"  Generando embeddings para {len(aprobados)} artículo(s) aprobado(s)...", flush=True)
        modelo = llm.modelo_embeddings()
        vectores = llm.embeber([texto_para_embedding(item) for item in aprobados])
        for item, vec in zip(aprobados, vectores, strict=True):
            if vec:
                item["embedding"] = vec
                item["embedding_modelo"] = modelo
        col_articulos.bulk_write([
            UpdateOne({"url": item["url"]}, {"$set": item, "$setOnInsert": {"usado_para_articulo": False}}, upsert=True)
            for item in aprobados
        ])

    return {
        "total": total,
        "aprobados": len(aprobados),
        "rechazados": total - len(aprobados),
        "detalles": detalles,
    }
