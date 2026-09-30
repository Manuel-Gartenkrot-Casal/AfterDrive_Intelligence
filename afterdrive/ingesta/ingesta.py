"""
ingesta.py — Artículos scrapeados -> Artículos guardados (o descartados).

Interfaz:
    ingerir(items) -> {"total", "aprobados", "rechazados", "detalles"}
    clasificar(titulo, cuerpo) -> {"aprobado": bool, "razon": str}

Acá vive el orden completo de la ingesta (clasificar, vectorizar, guardar) y
la cadena de clasificadores: Jev primero; si no está configurado o falla, el
clasificador LLM. La política de modo degradado del clasificador LLM está
documentada en lm_studio.clasificar_articulo.
"""

import datetime

from pymongo import UpdateOne

from afterdrive.ingesta import jev_clasificador
from afterdrive.ia import llm
from afterdrive.ia import lm_studio
from afterdrive.db import col_articulos, col_descartados
from afterdrive.ingesta.embeddings import texto_para_embedding


def clasificar(titulo: str, cuerpo: str) -> dict:
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
        col_descartados.replace_one(
            {"url": item.get("url", "")},
            {"url": item.get("url", ""), "fecha_descarte": datetime.datetime.now(datetime.UTC).isoformat()},
            upsert=True,
        )
        detalles.append({"titulo": titulo, "estado": "rechazado", "razon": razon})

    if aprobados:
        print(f"  Generando embeddings para {len(aprobados)} artículo(s) aprobado(s)...", flush=True)
        vectores = llm.embeber([texto_para_embedding(item) for item in aprobados])
        for item, vec in zip(aprobados, vectores, strict=True):
            if vec:
                item["embedding"] = vec
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
