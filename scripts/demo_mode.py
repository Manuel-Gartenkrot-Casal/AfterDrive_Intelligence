"""
scripts/demo_mode.py — La demo de noviembre de punta a punta: noticia → nota → revisión → HubSpot de pruebas.

    python -m scripts.demo_mode --solo-preparar   # el día antes: deja todo prendido y revisa lo que falta
    python -m scripts.demo_mode                   # trae noticias y escribe una nota enfocada en Alephee
    python -m scripts.demo_mode --hubspot         # además la aprueba y la sube como borrador al blog de pruebas
    python -m scripts.demo_mode --datos-ejemplo   # plan B: sin internet, con las noticias de demo_datos.json
    python -m scripts.demo_mode --limpiar         # borra las noticias de ejemplo que cargó --datos-ejemplo

Usa el mismo camino que la app (scraper con RSS y sitemaps, clasificación,
generar_nota con verificación, juez con la checklist de Alephee). Al preparar:
prende el blog de pruebas, prende la API paga (si está configurada y bajo el
tope) y suma las fuentes recomendadas para Alephee a Fuentes > Recomendadas.

Nunca publica: a HubSpot sube un borrador y solo si el blog de pruebas está
cargado y prendido. El guion de la demo está en docs/demo-noviembre.md.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import time

DATOS_EJEMPLO = pathlib.Path(__file__).with_name("demo_datos.json")
FUENTES_DEMO = 2          # fuentes activas que se scrapean en vivo
NOTAS_POR_FUENTE = 2

NOTA_DEMO = {
    "categorias": ["marketplaces", "catalogacion", "autopartes"],
    "persona": "comercial",
    "tema": "vender autopartes en marketplaces con el catálogo al día",
    "regiones": ["argentina"],
    "largo": "corto",
}


def _titulo(texto: str) -> None:
    print("\n" + "=" * 64 + f"\n  {texto}\n" + "=" * 64, flush=True)


def _ok(texto: str) -> None:
    print(f"  [OK] {texto}", flush=True)


def _falta(texto: str) -> None:
    print(f"  [FALTA] {texto}", flush=True)


# ── 1. Preparar ──────────────────────────────────────────────────────────────


def preparar() -> list[str]:
    """Prende el blog de pruebas y la API paga, y suma las fuentes recomendadas. Devuelve lo que falta."""
    from afterdrive import config_store, hubspot
    from afterdrive.ia import modo_pago
    from afterdrive.ingesta import fuentes_recomendadas

    _titulo("1. Preparar: blog de pruebas, API paga y fuentes")
    faltan = []

    config_store.set_blog_pruebas_config(True)
    if not hubspot.configurado():
        faltan.append("HUBSPOT_TOKEN no está cargado: no se puede subir a HubSpot.")
    elif not hubspot.blog_pruebas():
        faltan.append("HUBSPOT_BLOG_PRUEBAS no está cargado: sin él la demo no sube nada a HubSpot.")
    else:
        _ok(f"Blog de pruebas prendido (id {hubspot.blog_pruebas()}).")

    pago = modo_pago.activar()
    if pago.get("success"):
        _ok(f"API paga prendida hasta {pago.get('modo_pago_hasta') or '(sin fecha)'}.")
    else:
        faltan.append(f"API paga: {pago.get('error', 'no se pudo prender')}")

    try:
        n = fuentes_recomendadas.sembrar()
        _ok(f"{n} fuente(s) sumadas a Recomendadas." if n else "Las fuentes recomendadas ya estaban.")
    except Exception as e:
        faltan.append(f"No se pudieron sumar las fuentes recomendadas: {e}")

    for f in faltan:
        _falta(f)
    return faltan


# ── 2. Noticias ──────────────────────────────────────────────────────────────


def traer_noticias(fuentes: int = FUENTES_DEMO, por_fuente: int = NOTAS_POR_FUENTE) -> int:
    """Scrapea unas pocas fuentes activas como lo hace la corrida programada. Devuelve cuántas guardó."""
    from afterdrive.corridas import ya_procesadas
    from afterdrive.db import col_trusted_urls
    from afterdrive.ingesta.ingesta import ingerir
    from afterdrive.ingesta.scraper import start

    _titulo("2. Noticias: scraping de fuentes activas (RSS, sitemap o HTML)")
    docs = list(col_trusted_urls.find({"estado": "activo"}, {"url": 1}).limit(fuentes))
    if not docs:
        _falta("No hay fuentes activas. Agregá una en Fuentes o usá --datos-ejemplo.")
        return 0
    guardadas = 0
    for d in docs:
        t0 = time.time()
        print(f"  {d['url']}", flush=True)
        try:
            items = start([d["url"]], max_articulos=por_fuente, omitir=ya_procesadas).items
            n = ingerir(items)["aprobados"] if items else 0
        except Exception as e:
            print(f"    [ERROR] {e}", flush=True)
            continue
        guardadas += n
        print(f"    {n} noticia(s) nueva(s) en {time.time() - t0:.0f}s", flush=True)
    return guardadas


def cargar_ejemplos(base=None, ruta: pathlib.Path = DATOS_EJEMPLO, embeber: bool = True) -> int:
    """Plan B sin internet: guarda las noticias de demo_datos.json marcadas con demo=True."""
    from pymongo import UpdateOne

    if base is None:
        from afterdrive.db import db as base
    items = json.loads(ruta.read_text(encoding="utf-8"))
    ahora = datetime.datetime.now(datetime.UTC).isoformat()
    for item in items:
        item.update(demo=True, fecha=ahora)
    if embeber:
        try:
            from afterdrive.ia import llm
            from afterdrive.ingesta.embeddings import texto_para_embedding
            modelo = llm.modelo_embeddings()
            for item, vec in zip(items, llm.embeber([texto_para_embedding(i) for i in items]), strict=True):
                if vec:
                    item.update(embedding=vec, embedding_modelo=modelo)
        except Exception as e:
            print(f"  [AVISO] Sin embeddings para los ejemplos ({e}): se eligen por fecha.", flush=True)
    base["articulos"].bulk_write([
        UpdateOne({"url": i["url"]}, {"$set": i, "$setOnInsert": {"usado_para_articulo": False}}, upsert=True)
        for i in items
    ])
    return len(items)


def limpiar_ejemplos(base=None) -> int:
    """Borra las noticias de ejemplo. Las notas que se escribieron con ellas quedan."""
    if base is None:
        from afterdrive.db import db as base
    return base["articulos"].delete_many({"demo": True}).deleted_count


# ── 3. Nota y revisión ───────────────────────────────────────────────────────


def escribir_nota() -> dict:
    """Escribe una nota enfocada en Alephee y muestra lo que se ve en Revisión."""
    from afterdrive.generacion import juez
    from afterdrive.generacion.generar_nota_fase2 import generar_nota

    _titulo("3. Nota: escribir, verificar y juzgar")
    t0 = time.time()
    r = generar_nota(NOTA_DEMO["categorias"], persona=NOTA_DEMO["persona"], tema=NOTA_DEMO["tema"],
                     regiones=NOTA_DEMO["regiones"], largo=NOTA_DEMO["largo"])
    if not r.get("success"):
        _falta(f"No se escribió la nota: {r.get('error')}")
        return r
    meta = r.get("meta") or {}
    _ok(f"Nota guardada en {time.time() - t0:.0f}s (id {r.get('id')}).")
    print("\n" + (r.get("contenido") or "")[:600] + "\n  [...]\n", flush=True)

    _titulo("4. Revisión: lo que ve el equipo antes de aprobar")
    v = meta.get("verificacion") or {}
    print(f"  Datos verificados: {len(v.get('respaldados') or [])} de {v.get('total', 0)}"
          + (f" | sin respaldo: {', '.join(v['sin_respaldo'][:3])}" if v.get("sin_respaldo") else ""), flush=True)
    j = meta.get("juicio") or {}
    if j.get("error"):
        print(f"  Juez: {j['error']}", flush=True)
    else:
        print(f"  Calificación de la IA: {j.get('calificacion')}/5 — {'pasa' if j.get('pasa') else 'no pasa'}"
              + (f" ({j['comentario']})" if j.get("comentario") else ""), flush=True)
        for clave, desc in juez.CHECKLIST_ALEPHEE.items():
            valor = (j.get("alephee") or {}).get(clave)
            marca = {True: "sí", False: "NO", None: "—"}[valor]
            print(f"    [{marca:>2}] {desc}", flush=True)
    fallas = juez.fallas_alephee(j)
    if fallas:
        print("  Para corregir antes de aprobar: " + "; ".join(fallas), flush=True)
    return r


# ── 4. HubSpot de pruebas ────────────────────────────────────────────────────


def subir_a_pruebas(nota_id: str) -> dict | None:
    """Aprueba la nota y la sube como borrador al blog de pruebas. Nunca publica."""
    from afterdrive import historial, hubspot

    _titulo("5. HubSpot: borrador en el blog de pruebas")
    if not hubspot.configurado() or not hubspot.blog_pruebas():
        _falta("Sin HUBSPOT_TOKEN y HUBSPOT_BLOG_PRUEBAS (prendido) no se sube: la demo nunca usa el blog real.")
        return None
    historial.cambiar_estado("notas_fase2", nota_id, "aprobada")
    item = historial.enviar_a_hubspot("notas_fase2", nota_id, publicar=False)
    hs = (item or {}).get("hubspot") or {}
    _ok(f"Borrador subido: {hs.get('url') or hs.get('id') or '(sin link)'}")
    if item and item.get("aviso"):
        print(f"  [AVISO] {item['aviso']}", flush=True)
    return item


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Demo de noviembre: noticia → nota → revisión → HubSpot de pruebas.")
    p.add_argument("--solo-preparar", action="store_true", help="solo prender blog de pruebas, API paga y fuentes")
    p.add_argument("--sin-scraping", action="store_true", help="no traer noticias: usar las que ya hay")
    p.add_argument("--datos-ejemplo", action="store_true", help="cargar las noticias de demo_datos.json")
    p.add_argument("--limpiar", action="store_true", help="borrar las noticias de ejemplo y salir")
    p.add_argument("--hubspot", action="store_true", help="aprobar la nota y subirla como borrador de prueba")
    args = p.parse_args(argv)

    if args.limpiar:
        print(f"[OK] {limpiar_ejemplos()} noticia(s) de ejemplo borradas.", flush=True)
        return 0

    t0 = time.time()
    faltan = preparar()
    if args.solo_preparar:
        print("\nListo para la demo." if not faltan else f"\nFaltan {len(faltan)} cosa(s), ver arriba.", flush=True)
        return 1 if faltan else 0

    if args.datos_ejemplo:
        _titulo("2. Noticias: datos de ejemplo")
        _ok(f"{cargar_ejemplos()} noticia(s) de ejemplo cargadas (se borran con --limpiar).")
    elif not args.sin_scraping:
        traer_noticias()

    r = escribir_nota()
    if r.get("success") and args.hubspot and r.get("id"):
        subir_a_pruebas(r["id"])

    print(f"\nDemo terminada en {time.time() - t0:.0f}s.", flush=True)
    return 0 if r.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
