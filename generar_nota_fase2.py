"""
generar_nota_fase2.py — Generador de notas estilo AfterDrive by Alephee.

Recorrido de una nota:
  1. Noticias de contexto: las noticias scrapeadas más útiles para el pedido
     (contexto_noticias). Son la única fuente de cifras, empresas y casos.
  2. Referencias de estilo: notas reales del blog (afterdrive_ejemplos).
  3. Prompt: system de redaccion.py (persona + región) ajustado al proveedor
     activo (llm.ajustes_redaccion) + pedido con noticias y referencias.
  4. Generación, saneo (saneo.py) y evaluación de calidad, que se guarda con
     la nota para no re-evaluarla cada vez que se abre.

Uso:
    python generar_nota_fase2.py \\
        --categorias autopartes marketplaces \\
        --clientes cliente_a cliente_b \\
        --puntapie https://alephee.com/landing \\
        --persona comercial
"""

import argparse
import datetime
import os
import sys

import contexto_noticias
import llm
import redaccion
from db import db
from regiones import REGION_SLUGS, REGIONES
from saneo import sanear
from scraper_afterdrive import CATEGORIAS, get_ejemplos_por_tags

col_notas_fase2 = db["notas_fase2"]
col_clientes = db["clientes"]

EJEMPLOS_POR_CATEGORIA = 2
NOTICIAS_POR_NOTA = 5


def _recortar_parrafos(texto: str, limite: int) -> str:
    """Corta en el último párrafo completo que entra, para no imitar notas truncadas."""
    texto = (texto or "").strip()
    if len(texto) <= limite:
        return texto
    corte = texto.rfind("\n", 0, limite)
    return texto[:corte].rstrip() if corte > limite * 0.5 else texto[:limite].rstrip() + "..."


def _formatear_ejemplos(ejemplos: list[dict], chars: int) -> str:
    bloques = []
    for i, ej in enumerate(ejemplos, 1):
        bloques.append(
            f"--- Referencia {i} ---\n"
            f"# {ej.get('titulo', '')}\n"
            f"{_recortar_parrafos(ej.get('cuerpo', ''), chars)}"
        )
    return "\n\n".join(bloques)


def _formatear_clientes(clientes: list[dict]) -> str:
    lines = []
    for c in clientes:
        linea = f"- {c.get('nombre', '')}"
        if c.get("descripcion"):
            linea += f": {c['descripcion']}"
        if c.get("productos"):
            linea += f" | Productos/servicios: {', '.join(c['productos'])}"
        lines.append(linea)
    return "\n".join(lines)


def _build_system_prompt(
    categorias: list[str],
    clientes: list[dict],
    puntapie_url: str | None,
    persona: str,
    regiones: list[str] | None = None,
    ajustes: "llm.Redaccion | None" = None,
) -> str:
    ajustes = ajustes or llm.Redaccion()
    base = redaccion.system_prompt(
        persona,
        region=regiones,
        compacto=ajustes.compacto,
        extension="entre 600 y 900 palabras" if puntapie_url else None,
        puntapie_url=puntapie_url,
    )
    extra = []
    if regiones:
        nombres = [REGIONES.get(s, s) for s in regiones]
        extra.append(
            f"- Región: {', '.join(nombres)}. Contextualizá la nota en ese mercado; datos de otras "
            "regiones solo como comparación puntual."
        )
    if categorias:
        nombres = [CATEGORIAS.get(s, s) for s in categorias]
        extra.append(
            f"- Categorías: {', '.join(nombres)}. La nota tiene que encuadrarse en ellas, respetando la "
            "estructura de secciones de arriba."
        )
    if clientes:
        extra.append(
            "- Clientes a mencionar como casos o ejemplos del sector, con contexto real y sin tono "
            f"publicitario:\n{_formatear_clientes(clientes)}"
        )
    else:
        extra.append("- No menciones clientes específicos de Alephee.")
    prompt = base + "\n\n## Para esta nota\n" + "\n".join(extra)
    # La indicación propia del modelo va al final: es lo último que lee.
    return prompt + ("\n\n" + ajustes.directiva if ajustes.directiva else "")


def _build_user_prompt(
    noticias: list,
    ejemplos: list[dict],
    categorias: list[str],
    tema: str | None,
    ajustes: "llm.Redaccion | None" = None,
) -> str:
    ajustes = ajustes or llm.Redaccion()
    partes = []
    if noticias:
        partes.append(
            "## Noticias de contexto\n"
            "Son la única fuente de hechos concretos para esta nota (cifras, empresas, casos, citas).\n\n"
            + contexto_noticias.formatear(noticias, max_chars=3500 if ajustes.compacto else 7000)
        )
    else:
        partes.append(
            "## Noticias de contexto\n"
            "No hay noticias recientes para este tema. Escribí un análisis sin cifras, empresas ni "
            "casos concretos: explicá el tema con criterio de negocio."
        )
    if ejemplos:
        partes.append(
            "## Notas publicadas de referencia\n"
            "Imitá su tono, estructura y profundidad. No copies su contenido ni sus datos.\n\n"
            + _formatear_ejemplos(ejemplos, ajustes.chars_ejemplo)
        )
    pedido = "Escribí la nota."
    if tema:
        pedido = f"Escribí la nota sobre este tema: {tema}."
    elif categorias:
        pedido = f"Escribí la nota sobre {', '.join(CATEGORIAS.get(s, s) for s in categorias).lower()}."
    partes.append("## Pedido\n" + pedido)
    return "\n\n".join(partes)


def _consulta(categorias: list[str], tema: str | None, regiones: list[str]) -> str:
    """Texto con el que se buscan las noticias de contexto."""
    base = tema or ", ".join(CATEGORIAS.get(s, s) for s in categorias)
    region = " ".join(REGIONES.get(s, s) for s in regiones)
    return f"{base} {region} autopartes aftermarket".strip()


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
    ajustes = llm.ajustes_redaccion()

    clientes_docs = []
    for cid in clientes_ids:
        doc = col_clientes.find_one({"slug": cid}) or col_clientes.find_one({"nombre": {"$regex": cid, "$options": "i"}})
        if doc:
            clientes_docs.append(doc)

    noticias = contexto_noticias.seleccionar(_consulta(categorias, tema, regiones), limite=NOTICIAS_POR_NOTA)
    print(f"  Noticias de contexto: {len(noticias)}", flush=True)
    for n in noticias:
        print(f"    - {n.titulo[:80]}", flush=True)
    if not noticias:
        print("  [WARN] No hay noticias scrapeadas: la nota se escribe sin datos concretos.", flush=True)

    ejemplos = get_ejemplos_por_tags(categorias, regiones=regiones or None, limit=EJEMPLOS_POR_CATEGORIA)
    ejemplos = ejemplos[: ajustes.max_ejemplos]
    print(f"  Few-shot: {len(ejemplos)} ejemplo(s) cargado(s) para {categorias}", flush=True)

    system = _build_system_prompt(categorias, clientes_docs, puntapie_url, persona, regiones, ajustes)
    user_msg = _build_user_prompt(noticias, ejemplos, categorias, tema, ajustes)

    print("  Generando nota...", flush=True)
    try:
        crudo = llm.completar(system, user_msg, temperature=ajustes.temperatura, max_tokens=ajustes.max_tokens, stream=True)
    except llm.ErrorLLM as e:
        return {"success": False, "error": str(e)}

    saneo = sanear(crudo)
    if not saneo.ok:
        print(f"  [WARN] {saneo.motivo}. Se descarta.", flush=True)
        return {"success": False, "error": f"No se obtuvo una nota publicable: {saneo.motivo}"}
    articulo = saneo.texto

    print("  Evaluando calidad...", flush=True)
    from lm_studio import evaluar_lineamientos
    evaluacion = evaluar_lineamientos(articulo)

    doc = {
        "contenido": articulo,
        "categorias": categorias,
        "regiones": regiones,
        "clientes_mencionados": [c.get("nombre") for c in clientes_docs],
        "puntapie_url": puntapie_url,
        "persona": persona,
        "tema": tema,
        "fuentes": [{"titulo": n.titulo, "url": n.url} for n in noticias],
        "ejemplos_usados": [e.get("url") for e in ejemplos],
        "evaluacion": evaluacion if not evaluacion.get("error") else None,
        "proveedor": llm.proveedor_activo(),
        "generado_en": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    emb = llm.embeber([articulo])[0]
    if emb:
        doc["embedding"] = emb

    col_notas_fase2.insert_one(dict(doc))  # copia: insert_one agrega un _id no serializable
    contexto_noticias.marcar_usadas(noticias)
    print("[OK] Nota guardada en 'notas_fase2'.", flush=True)

    meta = {k: v for k, v in doc.items() if k != "embedding"}
    return {"success": True, "contenido": articulo, "meta": meta}


def get_ultima_nota() -> dict | None:
    return col_notas_fase2.find_one({}, sort=[("generado_en", -1)])


def _validar_entorno() -> None:
    """Falla temprano y con mensaje claro si falta configuración crítica."""
    provider = os.getenv("AI_PROVIDER", "local")
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        sys.exit("[ERROR] AI_PROVIDER=openrouter pero OPENROUTER_API_KEY no está configurado.")
    if provider == "nvidia" and not os.getenv("NVIDIA_API_KEY"):
        sys.exit("[ERROR] AI_PROVIDER=nvidia pero NVIDIA_API_KEY no está configurado.")
    if not os.getenv("MONGO_URI"):
        sys.exit("[ERROR] MONGO_URI no está configurado.")


if __name__ == "__main__":
    import io
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
    _validar_entorno()

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
