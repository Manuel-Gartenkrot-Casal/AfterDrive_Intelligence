"""
generar_nota_fase2.py — Generador de Notas Fase 2

Genera notas estilo AfterDrive by Alephee usando:
  - Few-shot con notas reales scrapeadas del blog (afterdrive_ejemplos)
  - Categorías seleccionadas via toggles
  - Mención opcional de clientes (de la colección 'clientes')
  - Modo "puntapié a link": nota pensada para redirigir a una URL externa

Uso:
    python generar_nota_fase2.py \
        --categorias autopartes marketplaces \
        --clientes cliente_a cliente_b \
        --puntapie https://alephee.com/landing \
        --persona comercial
"""

import argparse
import datetime
import os
import re
import sys

# Validación temprana de variables de entorno críticas
_provider = os.getenv("AI_PROVIDER", "local")
if _provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
    print("[ERROR] AI_PROVIDER=openrouter pero OPENROUTER_API_KEY no está configurado.", flush=True)
    sys.exit(1)
if _provider == "nvidia" and not os.getenv("NVIDIA_API_KEY"):
    print("[ERROR] AI_PROVIDER=nvidia pero NVIDIA_API_KEY no está configurado.", flush=True)
    sys.exit(1)
if not os.getenv("MONGO_URI"):
    print("[ERROR] MONGO_URI no está configurado.", flush=True)
    sys.exit(1)

from db import db
from lm_studio import _post, _extraer_primer_json, _post_procesar_articulo
from lm_studio import get_system_prompt_redactar, calcular_embedding
from scraper_afterdrive import get_ejemplos_por_tags, CATEGORIAS
from regiones import REGIONES, REGION_SLUGS
import json
import time

col_notas_fase2 = db["notas_fase2"]
col_clientes = db["clientes"]

EJEMPLOS_POR_CATEGORIA = 2
MAX_CHARS_EJEMPLO = 1200
MAX_EJEMPLOS_TOTAL = 6


def _formatear_ejemplos(ejemplos: list[dict]) -> str:
    if not ejemplos:
        return ""
    bloques = []
    for i, ej in enumerate(ejemplos, 1):
        cuerpo = ej.get("cuerpo", "")[:MAX_CHARS_EJEMPLO]
        bloques.append(
            f"--- EJEMPLO {i} [{ej.get('categoria', '')}] ---\n"
            f"TÍTULO: {ej.get('titulo', '')}\n"
            f"CONTENIDO:\n{cuerpo}\n"
        )
    return "\n".join(bloques)


def _formatear_clientes(clientes: list[dict]) -> str:
    if not clientes:
        return ""
    lines = []
    for c in clientes:
        nombre = c.get("nombre", "")
        descripcion = c.get("descripcion", "")
        productos = c.get("productos", [])
        linea = f"- {nombre}"
        if descripcion:
            linea += f": {descripcion}"
        if productos:
            linea += f" | Productos/servicios: {', '.join(productos)}"
        lines.append(linea)
    return "\n".join(lines)


_IDIOMAS_REGION = {
    "argentina": "español rioplatense",
    "brasil": "portugués brasileño",
    "mexico": "español mexicano",
    "latinoamerica": "español latinoamericano",
    "europa": "español (mercado europeo; escribí en español)",
    "china": "chino mandarín simplificado",
    "asia": "inglés (mercado asiático internacional)",
}

# Notas sobre el idioma de cada región para el user prompt
_NOTAS_IDIOMA = {
    "china": "Escribí toda la nota en chino mandarín simplificado. "
             "Usa terminología automotriz china: 零部件 (autopartes), 后市场 (aftermarket), 电子商务 (e-commerce). "
             "Menciona marcas chinas: BYD, NIO, Geely, Chery, Great Wall.",
    "asia": "Escribí toda la nota en inglés. "
            "Enfocate en el mercado asiático de autopartes: Japón, Corea, India, Tailandia. "
            "Menciona marcas: Toyota, Hyundai, Tata Motors, Denso, AISIN.",
    "brasil": "Escribí toda la nota en portugués brasileño.",
    "argentina": "Escribí toda la nota en español rioplatense.",
    "mexico": "Escribí toda la nota en español mexicano.",
    "latinoamerica": "Escribí toda la nota en español latinoamericano.",
    "europa": "Escribí toda la nota en español. El mercado objetivo es Europa.",
}


def _build_system_prompt(
    categorias: list[str],
    clientes: list[dict],
    puntapie_url: str | None,
    persona: str,
    regiones: list[str] | None = None,
) -> str:
    base = get_system_prompt_redactar(persona)

    instrucciones_extra = []

    if regiones:
        nombres_regiones = [REGIONES.get(s, s) for s in regiones]
        instrucciones_extra.append(
            f"REGIÓN(ES) OBJETIVO: {', '.join(nombres_regiones)}. "
            "La nota debe estar contextualizada en esta(s) región(es): "
            "usá datos, casos, marcas y referencias de mercado de esa región. "
            "NO mezcles datos de otras regiones salvo como comparación puntual."
        )

        # Forzar idioma según región con notas detalladas
        idiomas = []
        for s in regiones:
            lang = _IDIOMAS_REGION.get(s, "español latinoamericano")
            nota = _NOTAS_IDIOMA.get(s, f"Escribí en {lang}.")
            idiomas.append(nota)

        idioma_texto = " ".join(idiomas)
        instrucciones_extra.append(f"IDIOMA Y CONTENIDO:\n{idioma_texto}")
    else:
        instrucciones_extra.append(
            "IDIOMA: Español latinoamericano (default)."
        )

    if categorias:
        nombres = [CATEGORIAS.get(s, s) for s in categorias]
        instrucciones_extra.append(
            f"CATEGORÍAS OBJETIVO: {', '.join(nombres)}. "
            "La nota debe enmarcarse en estas categorías. "
            "El contenido debe ser relevante para estos temas específicos."
        )

    if clientes:
        info_clientes = _formatear_clientes(clientes)
        instrucciones_extra.append(
            f"MENCIONAR CLIENTES: Sí. Integra naturalmente la mención a estos clientes "
            f"como casos de éxito o como ejemplo del sector. "
            f"NO hagas publicidad explícita: mencionalos con contexto real.\n{info_clientes}"
        )
    else:
        instrucciones_extra.append(
            "CLIENTES: No mencionar clientes específicos en esta nota."
        )

    if puntapie_url:
        instrucciones_extra.append(
            f"MODO PUNTAPIÉ A LINK: Esta nota tiene como objetivo principal redirigir "
            f"al lector a la siguiente URL: {puntapie_url}\n"
            "Estructura la nota para generar curiosidad y llevar al lector a hacer clic. "
            "El CTA final DEBE incluir un link explícito a esa URL. "
            "La nota debe ser más concisa (600-900 palabras) y con gancho fuerte desde el inicio."
        )
    else:
        instrucciones_extra.append(
            "EXTENSIÓN: Nota completa estilo blog AfterDrive (900-1400 palabras). "
            "El CTA final es hacia Alephee como plataforma general."
        )

    if instrucciones_extra:
        return base + "\n\n## Instrucciones adicionales para esta generación\n" + "\n\n".join(instrucciones_extra)
    return base


def _build_few_shot_prompt(
    ejemplos: list[dict],
    categorias: list[str],
    clientes: list[dict],
    puntapie_url: str | None,
    tema: str | None,
    regiones: list[str] | None = None,
) -> str:
    partes = []

    if ejemplos:
        partes.append(
            "A continuación hay notas REALES publicadas en AfterDrive by Alephee. "
            "Úsalas como referencia de tono, estructura y nivel de profundidad. "
            "NO copies su contenido, solo imita el estilo.\n\n"
            + _formatear_ejemplos(ejemplos)
        )
    else:
        partes.append(
            "No hay notas de referencia disponibles en la base de datos. "
            "Generá la nota directamente siguiendo las instrucciones del system prompt. "
            "Estilo blog B2B AfterDrive by Alephee: título descriptivo, introducción con gancho, "
            "secciones con ##, datos específicos del sector, cierre con CTA."
        )

    instrucciones = ["Redactá una nota B2B estilo AfterDrive by Alephee."]

    if tema:
        instrucciones.append(f"TEMA: {tema}")

    if categorias:
        nombres = [CATEGORIAS.get(s, s) for s in categorias]
        instrucciones.append(f"CATEGORÍAS: {', '.join(nombres)}")

    if regiones:
        nombres_regiones = [REGIONES.get(s, s) for s in regiones]
        instrucciones.append(f"REGIÓN(ES): {', '.join(nombres_regiones)}")

        idiomas = [_IDIOMAS_REGION.get(s, "español") for s in regiones]
        idioma_unico = list(dict.fromkeys(idiomas))
        instrucciones.append(f"IDIOMA: {', '.join(idioma_unico)}")

    if puntapie_url:
        instrucciones.append(
            f"OBJETIVO: generar curiosidad y redirigir al lector a {puntapie_url}. "
            "El CTA final debe ser un link directo a esa URL."
        )

    partes.append(" | ".join(instrucciones))
    return "\n\n".join(partes)


def generar_nota(
    categorias: list[str],
    clientes_ids: list[str] | None = None,
    puntapie_url: str | None = None,
    persona: str = "comercial",
    tema: str | None = None,
    regiones: list[str] | None = None,
) -> dict:
    clientes_ids = clientes_ids or []
    regiones = regiones or []

    clientes_docs = []
    if clientes_ids:
        from bson import ObjectId
        for cid in clientes_ids:
            doc = col_clientes.find_one({"slug": cid}) or col_clientes.find_one({"nombre": {"$regex": cid, "$options": "i"}})
            if doc:
                clientes_docs.append(doc)

    ejemplos = get_ejemplos_por_tags(categorias, regiones=regiones or None, limit=EJEMPLOS_POR_CATEGORIA)
    ejemplos = ejemplos[:MAX_EJEMPLOS_TOTAL]
    print(f"  Few-shot: {len(ejemplos)} ejemplo(s) cargado(s) para {categorias}" +
          (f" — regiones {regiones}" if regiones else ""))
    if not ejemplos:
        print("  [WARN] Sin ejemplos en DB — ejecuta scraper_afterdrive.py primero.")

    system = _build_system_prompt(categorias, clientes_docs, puntapie_url, persona, regiones)
    user_msg = _build_few_shot_prompt(ejemplos, categorias, clientes_docs, puntapie_url, tema, regiones)

    from lm_studio import AI_PROVIDER, _get_model, _get_headers, _get_base_url

    payload = {
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.72,
        "max_tokens": 4000,
        "stream": True,
        "include_reasoning": False,
    }

    print("  Generando nota...")
    partes = []
    t0 = time.time()

    try:
        response = _post("/chat/completions", payload, timeout=1800, stream=True, retries=5)
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not response.ok:
        return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:500]}"}

    last_progress = t0
    for line in response.iter_lines():
        if not line:
            continue
        text = line.decode("utf-8")
        if text.startswith("data: "):
            text = text[6:]
        if text == "[DONE]":
            break
        try:
            chunk = json.loads(text)
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content") or ""
                partes.append(content)
        except Exception:
            continue
        now = time.time()
        if now - last_progress >= 60:
            print(f"  [{int(now-t0)}s] {len(''.join(partes))} chars...", flush=True)
            last_progress = now

    t_total = int(time.time() - t0)
    print(f"  Generación completa en {t_total}s")

    articulo_raw = "".join(partes)
    if not articulo_raw:
        return {"success": False, "error": "Respuesta vacía del modelo"}

    articulo = _limpiar_y_extraer(articulo_raw)
    if not articulo:
        return {"success": False, "error": "No se pudo extraer el texto del artículo"}

    articulo = _post_procesar_articulo(articulo)

    doc = {
        "contenido": articulo,
        "categorias": categorias,
        "regiones": regiones,
        "clientes_mencionados": [c.get("nombre") for c in clientes_docs],
        "puntapie_url": puntapie_url,
        "persona": persona,
        "tema": tema,
        "ejemplos_usados": [e.get("url") for e in ejemplos],
        "generado_en": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    emb = calcular_embedding(articulo)
    if emb:
        doc["embedding"] = emb

    col_notas_fase2.insert_one(doc)
    print(f"[OK] Nota guardada en 'notas_fase2'.")

    return {"success": True, "contenido": articulo, "meta": doc}


def _limpiar_y_extraer(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r"^```(?:markdown)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)
    texto = re.sub(r"</?ARTICULO>", "", texto)
    texto = re.sub(r"(?i)(?:^|\n)\s*Meta Description:\s*", "\n", texto)

    lineas = texto.split("\n")
    for i, line in enumerate(lineas):
        if line.strip().startswith("# ") or line.strip().startswith("## "):
            posible = "\n".join(lineas[i:]).strip()
            if len(posible) > 200:
                return posible
    return texto if len(texto) > 200 else ""


def get_ultima_nota() -> dict | None:
    return col_notas_fase2.find_one({}, sort=[("generado_en", -1)])


if __name__ == "__main__":
    import io, sys, os
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Generador de notas Fase 2 — AfterDrive")
    parser.add_argument("--categorias", nargs="+", choices=list(CATEGORIAS.keys()), default=["autopartes"])
    parser.add_argument("--clientes", nargs="+", default=[])
    parser.add_argument("--puntapie", type=str, default=None)
    parser.add_argument("--persona", default="comercial",
                        choices=["analitico", "periodistico", "comercial", "divulgativo", "ejecutivo"])
    parser.add_argument("--tema", type=str, default=None)
    parser.add_argument("--regiones", nargs="+", choices=REGION_SLUGS, default=[],
                        help="Regiones objetivo (argentina, brasil, mexico, latinoamerica, europa, china, asia)")
    args = parser.parse_args()

    resultado = generar_nota(
        categorias=args.categorias,
        clientes_ids=args.clientes,
        puntapie_url=args.puntapie,
        persona=args.persona,
        tema=args.tema,
        regiones=args.regiones,
    )

    if resultado["success"]:
        print("\n" + "=" * 60)
        print(resultado["contenido"][:1500])
        print("=" * 60)
    else:
        print(f"[ERROR] {resultado['error']}")
