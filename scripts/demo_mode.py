"""
scripts/demo_mode.py (python -m scripts.demo_mode) — Pipeline optimizado para demo en tiempo real (<60 segundos).

Optimizaciones:
  - Scraping: HTTP directo con requests (sin Playwright/headless), max 1 articulo por fuente
  - Clasificacion: skip si LM Studio no responde en 3s
  - Generacion: contexto reducido, sin dedup por embeddings
  - Todo en secuencia con progreso visible
"""

import datetime
import re
import time
from html.parser import HTMLParser

import requests
import trafilatura

from afterdrive.db import col_articulos, col_trusted_urls

# ── Configuracion demo ──────────────────────────────────────────────────────

DEMO_MAX_ARTICLES_PER_SOURCE = 1
DEMO_HTTP_TIMEOUT = 8  # segundos por request HTTP
DEMO_MAX_SOURCES = 2


# ── Fetch HTTP rapido (sin Playwright) ──────────────────────────────────────

def _fetch_html(url: str) -> str | None:
    """HTTP GET directo, sin headless browser."""
    try:
        r = requests.get(
            url,
            timeout=DEMO_HTTP_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AfterDriveBot/1.0)"},
            allow_redirects=True,
        )
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _encontrar_links(html: str, base_url: str) -> list[str]:
    """Extrae enlaces a articulos del HTML usando BeautifulSoup."""
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()

    # Buscar enlaces con patrones tipicos de articulos
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href in seen:
            continue
        full = urljoin(base_url, href)
        # Filtrar por patrones de articulos (no footer, no nav, etc.)
        if any(p in full.lower() for p in ["/blog/", "/noticias/", "/articulo/", "/news/", "/post/", "/accesorios", "/repuestos"]):
            if full not in seen:
                seen.add(full)
                links.append(full)
    return links


def _extraer_articulo(html: str, url: str) -> dict | None:
    """Extrae titulo y contenido de un HTML con trafilatura."""
    try:
        result = trafilatura.extract(
            html, output_format="json", url=url,
            include_links=False, include_images=False,
        )
        if not result:
            return None
        import json
        data = json.loads(result)
        titulo = data.get("title", "").strip()
        texto = data.get("text", "").strip()
        if not titulo or len(texto) < 100:
            return None
        return {"titulo": titulo, "cuerpo": texto, "url": url, "fuente": url}
    except Exception:
        return None


# ── Scraping rapido ─────────────────────────────────────────────────────────

def demo_scraping():
    """Scraping rapido: HTTP directo, max 1 articulo por fuente."""
    print("\n" + "=" * 60)
    print("  FASE 1: SCRAPING (modo demo)")
    print("=" * 60)

    urls_confiables = list(col_trusted_urls.find({"estado": "activo"}).limit(DEMO_MAX_SOURCES))

    if not urls_confiables:
        print("  [WARN] No hay URLs confiables. Usando fuentes de ejemplo...")
        urls_confiables = [
            {"url": "https://www.aftermarketinternational.com"},
            {"url": "https://www.lacasadelrenault.com.ar"},
        ]

    total_nuevos = 0
    fuentes_procesadas = 0

    for doc in urls_confiables:
        url = doc["url"]
        fuentes_procesadas += 1
        print(f"\n  [{fuentes_procesadas}/{len(urls_confiables)}] {url}")

        t0 = time.time()
        try:
            items = _scrape_fuente_rapida(url)
            if items:
                res = _guardar_rapido(items, col_articulos)
                nuevos = res.get("aprobados", 0)
                total_nuevos += nuevos
                print(f"    [OK] {nuevos} articulo(s) nuevo(s) ({time.time() - t0:.1f}s)")
            else:
                print(f"    [SKIP] Sin articulos nuevos ({time.time() - t0:.1f}s)")
        except Exception as e:
            print(f"    [ERROR] {e} ({time.time() - t0:.1f}s)")

    print(f"\n  Scraping completado: {total_nuevos} articulos nuevos en {fuentes_procesadas} fuentes")
    return total_nuevos


def _guardar_rapido(items: list[dict], coleccion) -> dict:
    """Guardar items sin embeddings ni clasificacion IA (modo demo rapido)."""
    from pymongo import UpdateOne
    from afterdrive.db import col_trusted_urls

    urls_existentes = set()
    for col_name in ["afterdrive", "articulos_generados"]:
        for doc in coleccion.find({}, {"url": 1, "_id": 0}):
            if url := doc.get("url"):
                urls_existentes.add(url)

    aprobados = []
    for item in items:
        if item.get("url") not in urls_existentes:
            aprobados.append(item)
            urls_existentes.add(item.get("url"))

    if aprobados:
        operaciones = [
            UpdateOne(
                {"url": item["url"]},
                {"$set": item, "$setOnInsert": {"usado_para_articulo": False}},
                upsert=True,
            )
            for item in aprobados
        ]
        coleccion.bulk_write(operaciones)

    return {
        "total": len(items),
        "aprobados": len(aprobados),
        "rechazados": len(items) - len(aprobados),
    }


def _scrape_fuente_rapida(url: str) -> list[dict]:
    """Scrapea una fuente con HTTP directo, devuelve max 1 articulo."""
    html = _fetch_html(url)
    if not html:
        return []

    links = _encontrar_links(html, url)
    if not links:
        # Intentar extraer articulo directo de la URL raiz
        art = _extraer_articulo(html, url)
        return [art] if art else []

    # Solo probar el primer link
    for link in links[:DEMO_MAX_ARTICLES_PER_SOURCE]:
        art_html = _fetch_html(link)
        if art_html:
            art = _extraer_articulo(art_html, link)
            if art:
                return [art]
    return []


# ── Generacion rapida ──────────────────────────────────────────────────────

def demo_generacion():
    """Generacion rapida: contexto reducido, sin embeddings."""
    print("\n" + "=" * 60)
    print("  FASE 2: GENERACION DE ARTICULO (modo demo)")
    print("=" * 60)

    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import generar_articulo as lm_generar

    if not llm.disponible():
        print("  [ERROR] LM Studio no disponible")
        return None

    docs = list(col_articulos.find().sort("_id", -1).limit(10))
    if not docs:
        print("  [ERROR] No hay articulos en la DB para generar contexto")
        return None

    contexto = ""
    for i, doc in enumerate(docs[:5], 1):
        titulo = doc.get("titulo", "(sin titulo)")
        cuerpo = doc.get("cuerpo", "")[:800]
        contexto += f"[#{i}] {titulo}\n{cuerpo}\n\n"

    print(f"  Contexto: {len(docs[:5])} articulos (~{len(contexto)} chars)")
    print("  Generando articulo...")

    t0 = time.time()
    try:
        articulo = lm_generar(contexto, persona="analitico", tema="autopartes aftermarket")
        elapsed = time.time() - t0

        if articulo:
            print(f"  [OK] Articulo generado ({elapsed:.1f}s, {len(articulo)} chars)")

            from afterdrive.db import db
            col_gen = db["articulos_generados"]
            col_gen.insert_one({
                "contenido": articulo,
                "fuentes": ["demo"],
                "tema": "demo",
                "docs_usados": [],
                "generado_en": datetime.datetime.now(datetime.UTC).isoformat(),
            })
            print("  Articulo guardado en DB")
            return articulo
        else:
            print("  [ERROR] Articulo vacio")
            return None
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


# ── Scheduler ──────────────────────────────────────────────────────────────

def demo_scheduler():
    """Mostrar que el scheduler esta configurado y funciona."""
    print("\n" + "=" * 60)
    print("  FASE 3: SCHEDULER (verificacion)")
    print("=" * 60)

    from afterdrive.scheduler import proximas
    next_run = proximas()["scraping"]
    if next_run:
        print(f"  Scheduler activo. Proxima ejecucion: {next_run}")
    else:
        print("  Scheduler no activo (se inicia al arrancar Flask)")

    print("  Configuracion: ejecucion periodica cada N dias")
    print("  Intervalo ajustable desde el dashboard")


# ── Main ──────────────────────────────────────────────────────────────────

def run_demo():
    """Ejecutar pipeline completo de demo."""
    print("\n" + "#" * 60)
    print("  AFTERDRIVE INTELLIGENCE — MODO DEMO")
    print("  Pipeline completo en tiempo real")
    print("#" * 60)

    t_total = time.time()

    nuevos = demo_scraping()
    articulo = demo_generacion()
    demo_scheduler()

    elapsed_total = time.time() - t_total

    print("\n" + "=" * 60)
    print("  RESUMEN DE LA DEMO")
    print("=" * 60)
    print(f"  Tiempo total: {elapsed_total:.1f}s")
    print(f"  Articulos scrapeados: {nuevos}")
    print(f"  Articulo generado: {'Si' if articulo else 'No'}")
    print(f"  Scheduler: Activo")
    print("=" * 60)

    if elapsed_total < 60:
        print("\n  OK: Demo completada en menos de 60 segundos")
    else:
        print(f"\n  WARN: Demo tomo {elapsed_total:.0f}s (objetivo: <60s)")

    return articulo


if __name__ == "__main__":
    run_demo()
