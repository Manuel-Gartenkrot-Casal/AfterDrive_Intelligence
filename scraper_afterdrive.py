"""
scraper_afterdrive.py — Fase 2

Scrapea las notas reales del blog AfterDrive by Alephee (afterdrive.alephee.com/es)
organizadas por tag/categoría y las guarda en MongoDB como ejemplos few-shot.

Uso:
    python scraper_afterdrive.py               # scrapea todas las categorías
    python scraper_afterdrive.py --tags autopartes marketplaces
    python scraper_afterdrive.py --max 3       # máximo por categoría

Resultado en MongoDB:
    DB: afterdrive  |  Colección: afterdrive_ejemplos
    Campos: url, titulo, cuerpo, categoria, tag_slug, fecha, scrapeado_en
"""

import argparse
import datetime
import time

import requests
import trafilatura
from bs4 import BeautifulSoup
from pymongo import UpdateOne

from db import db
from regiones import clasificar_region, REGIONES
from resource_detector import get_scrape_sleep, usar_browser

col_ejemplos = db["afterdrive_ejemplos"]

BASE_URL = "https://afterdrive.alephee.com/es/blog/tag"

CATEGORIAS = {
    # Novedades
    "casos-de-exito":      "Casos de éxito",
    "columna-de-opinion":  "Columna de opinión",
    # Innovación
    "productos":           "Productos",
    "soluciones":          "Soluciones",
    "servicios":           "Servicios",
    # Industria
    "neumaticos":          "Neumáticos",
    "autopartes":          "Autopartes",
    "motopartes":          "Motopartes",
    "vehiculos-pesados":   "Vehículos pesados",
    "estadisticas":        "Estadísticas",
    # E-commerce
    "marketplaces":        "Marketplaces",
    "catalogacion":        "Catalogación",
    "gestion-de-ventas":   "Gestión de Ventas",
    "logistica":           "Logística",
    "rentabilidad":        "Rentabilidad",
    # Comunidad
    "eventos":             "Eventos",
}

TAG_URL_MAP = {
    "casos-de-exito":      "casos-de-%C3%A9xito",
    "columna-de-opinion":  "columna-de-opini%C3%B3n",
    "productos":           "productos",
    "soluciones":          "soluciones",
    "servicios":           "servicios",
    "neumaticos":          "neum%C3%A1ticos",
    "autopartes":          "autopartes",
    "motopartes":          "motopartes",
    "vehiculos-pesados":   "veh%C3%ADculos-pesados",
    "estadisticas":        "estad%C3%ADsticas",
    "marketplaces":        "marketplaces",
    "catalogacion":        "catalogaci%C3%B3n",
    "gestion-de-ventas":   "gesti%C3%B3n-de-ventas",
    "logistica":           "log%C3%ADstica",
    "rentabilidad":        "rentabilidad",
    "eventos":             "eventos",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_FETCH_OPTS = {
    "headless": True,
    "disable_resources": True,
    "timeout": 20000,
    "extra_args": [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
    ],
}


def _get(url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"    [HTTP ERROR] {url}: {e}")
        return None


def _get_browser(url: str) -> str | None:
    """Fetch con headless browser para sitios que requieren JS (HubSpot).
    Solo se ejecuta si el perfil de recursos lo permite."""
    if not usar_browser():
        print(f"    [BROWSER SKIP] perfil bajo, omitiendo browser para {url[:60]}", flush=True)
        return None
    try:
        from scrapling.fetchers import StealthyFetcher
        pag = StealthyFetcher.fetch(url, **_FETCH_OPTS)
        if hasattr(pag, "body") and pag.body:
            raw = pag.body
            return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if hasattr(pag, "text") and pag.text:
            return pag.text
    except Exception as e:
        print(f"    [BROWSER ERROR] {url}: {e}", flush=True)
    return None


def _extraer_links_listado(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/es/blog/" in href and "/tag/" not in href and "/author/" not in href:
            if href.startswith("/"):
                href = "https://afterdrive.alephee.com" + href
            if href not in seen and href.startswith("https://afterdrive.alephee.com/es/blog/"):
                seen.add(href)
                links.append(href)
    return links


def _extraer_articulo_bs4(html: str, url: str, tag_slug: str) -> dict | None:
    """Extrae artículo de HubSpot/AfterDrive usando BeautifulSoup."""
    try:
        soup = BeautifulSoup(html, "lxml")
        titulo = ""
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            titulo = og["content"].strip()
        if not titulo:
            h1 = soup.find("h1")
            if h1:
                titulo = h1.get_text(strip=True)
        if not titulo:
            return None

        cuerpo = ""
        for sel in ["div.hs-blog-post", "div.post-body", "div.blog-post__content", "article"]:
            el = soup.select_one(sel)
            if el:
                # Quitar nav, header, footer, scripts, styles
                for tag in el.find_all(["nav", "header", "footer", "script", "style", "aside"]):
                    tag.decompose()
                cuerpo = el.get_text(separator="\n", strip=True)
                break

        if not cuerpo or len(cuerpo) < 200:
            return None

        # Limpiar cuerpo de texto de navegación
        lineas = [l.strip() for l in cuerpo.split("\n") if len(l.strip()) > 40]
        cuerpo = "\n".join(lineas)
        if len(cuerpo) < 200:
            return None

        regiones = clasificar_region(titulo, cuerpo)

        return {
            "url": url,
            "titulo": titulo,
            "cuerpo": cuerpo[:5000],
            "fecha": "",
            "categoria": CATEGORIAS.get(tag_slug, tag_slug),
            "tag_slug": tag_slug,
            "regiones": regiones,
            "region_principal": regiones[0] if regiones else "",
            "scrapeado_en": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    except Exception as e:
        print(f"    [BS4 ERROR] {e}")
        return None


def _extraer_articulo(url: str, html: str, tag_slug: str) -> dict | None:
    try:
        result = trafilatura.extract(
            html,
            output_format="json",
            url=url,
            include_links=False,
            include_images=False,
            favor_precision=True,
        )
        if not result:
            return _extraer_articulo_bs4(html, url, tag_slug)
        import json
        data = json.loads(result)
        titulo = (data.get("title") or "").strip()
        cuerpo = (data.get("text") or "").strip()
        fecha = data.get("date") or ""

        if not titulo or not cuerpo or len(cuerpo) < 200:
            return _extraer_articulo_bs4(html, url, tag_slug)

        regiones = clasificar_region(titulo, cuerpo)

        return {
            "url": url,
            "titulo": titulo,
            "cuerpo": cuerpo[:5000],
            "fecha": fecha,
            "categoria": CATEGORIAS.get(tag_slug, tag_slug),
            "tag_slug": tag_slug,
            "regiones": regiones,
            "region_principal": regiones[0] if regiones else "",
            "scrapeado_en": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    except Exception as e:
        print(f"    [PARSE ERROR] {e}")
        return _extraer_articulo_bs4(html, url, tag_slug)


def _scrapearticulo_con_fallback(url: str, html_initial: str | None, tag_slug: str) -> dict | None:
    """Intenta extraer artículo: primero con HTML normal, luego con browser."""
    html = html_initial
    art = _extraer_articulo(url, html, tag_slug) if html else None
    if not art:
        print(f"    [RETRY] Usando browser para {url}")
        html_browser = _get_browser(url)
        if html_browser:
            art = _extraer_articulo(url, html_browser, tag_slug)
    return art


def scrape_tag(tag_slug: str, max_por_tag: int = 5) -> int:
    url_encoded = TAG_URL_MAP.get(tag_slug, tag_slug)
    listado_url = f"https://afterdrive.alephee.com/es/blog/tag/{url_encoded}"
    nombre = CATEGORIAS.get(tag_slug, tag_slug)
    print(f"\n[TAG] {nombre} → {listado_url}")

    html_listado = _get(listado_url)
    if not html_listado:
        print("  [SKIP] No se pudo descargar el listado.")
        return 0

    links = _extraer_links_listado(html_listado, listado_url)
    print(f"  → {len(links)} links encontrados, procesando hasta {max_por_tag}...")

    guardados = 0
    operaciones = []

    for link in links[:max_por_tag * 2]:
        if guardados >= max_por_tag:
            break

        ya_existe = col_ejemplos.find_one({"url": link}, {"_id": 1})
        if ya_existe:
            print(f"  [SKIP] Ya existe: {link}")
            guardados += 1
            continue

        time.sleep(get_scrape_sleep())
        html_art = _get(link)
        art = _scrapearticulo_con_fallback(link, html_art, tag_slug)
        if not art:
            print(f"  [FAIL] No se pudo parsear: {link}")
            continue

        operaciones.append(
            UpdateOne({"url": art["url"]}, {"$set": art}, upsert=True)
        )
        print(f"  [OK] {art['titulo'][:80]}")
        guardados += 1

    if operaciones:
        col_ejemplos.bulk_write(operaciones)
        print(f"  → {len(operaciones)} nota(s) guardada(s) en 'afterdrive_ejemplos'.")

    return guardados


def scrape_all(tags: list[str] | None = None, max_por_tag: int = 5) -> dict:
    tags_a_procesar = tags or list(CATEGORIAS.keys())
    total = 0
    resultado = {}
    for slug in tags_a_procesar:
        if slug not in CATEGORIAS:
            print(f"[WARN] Tag desconocido: {slug}")
            continue
        n = scrape_tag(slug, max_por_tag)
        resultado[slug] = n
        total += n

    print(f"\n[OK] Scraping AfterDrive finalizado — {total} nota(s) procesadas.")
    return resultado


def get_categorias_disponibles() -> list[dict]:
    pipeline = [
        {"$group": {"_id": "$tag_slug", "nombre": {"$first": "$categoria"}, "total": {"$sum": 1}}},
        {"$sort": {"nombre": 1}},
    ]
    return list(col_ejemplos.aggregate(pipeline))


def get_regiones_disponibles() -> list[dict]:
    pipeline = [
        {"$unwind": "$regiones"},
        {"$group": {"_id": "$regiones", "total": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    return list(col_ejemplos.aggregate(pipeline))


def get_ejemplos_por_tags(tag_slugs: list[str], regiones: list[str] | None = None, limit: int = 2) -> list[dict]:
    docs = []
    for slug in tag_slugs:
        query: dict = {"tag_slug": slug}
        if regiones:
            query["regiones"] = {"$in": regiones}
        cursor = col_ejemplos.find(query).sort("scrapeado_en", -1).limit(limit)
        docs.extend(list(cursor))
    return docs


if __name__ == "__main__":
    import io, sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Scraper de notas AfterDrive by Alephee")
    parser.add_argument("--tags", nargs="+", choices=list(CATEGORIAS.keys()), metavar="TAG")
    parser.add_argument("--max", type=int, default=5, help="Máximo de notas por categoría")
    args = parser.parse_args()

    scrape_all(tags=args.tags, max_por_tag=args.max)
