import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

from resource_detector import get_max_workers, get_perfil, usar_browser
from resource_detector import PERFIL_ALTO, PERFIL_MEDIO, PERFIL_BAJO

_PERFIL = get_perfil()
_MAX_WORKERS = get_max_workers()

print(f"[scraper] perfil='{_PERFIL}' workers={_MAX_WORKERS} browser={'si' if usar_browser() else 'no'}", flush=True)

FETCH_OPTS = {
    "headless": True,
    "disable_resources": True,
    "timeout": 10000,
    "extra_args": [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
    ],
}

_PAGINAS_SALTAR = [
    "login", "register", "search", "tag", "author",
    "category", "contact", "about", "privacy", "terms", "moneda",
]

_BLOQUEOS_CF = [
    "Just a moment",
    "Enable JavaScript",
    "cf-browser-verification",
    "Checking your browser",
    "DDoS protection by",
    "Please enable cookies",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}


class _Result:
    def __init__(self, items):
        self.items = items


def _esta_bloqueado(html: str | None) -> bool:
    if not html or len(html) < 500:
        return True
    return any(s in html for s in _BLOQUEOS_CF)


def _http_get(url: str, timeout: int = 10) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers=_HEADERS)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _browser_get(url: str) -> str | None:
    try:
        from scrapling.fetchers import StealthyFetcher
        pag = StealthyFetcher.fetch(url, **FETCH_OPTS)
        if hasattr(pag, "body") and pag.body:
            raw = pag.body
            return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if hasattr(pag, "text") and pag.text:
            return pag.text
    except Exception:
        pass
    return None


def _wayback_get(url: str) -> str | None:
    anos = ["2026", "2025"]
    slug = urlparse(url).path.rstrip("/").split("/")[-1]

    def _try(ano):
        html = _http_get(f"https://web.archive.org/web/{ano}/{url}", timeout=12)
        if html and slug and slug in html:
            return html
        return None

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_try, a) for a in anos]
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                return result
    return None


def _fetch(url: str) -> str | None:
    """
    Estrategia adaptativa según perfil de recursos:

    ALTO:  Chromium → requests → Wayback
    MEDIO: requests → (si bloqueado) Chromium → Wayback
    BAJO:  requests → Wayback (sin Chromium nunca)
    """
    if _PERFIL == PERFIL_ALTO:
        html = _browser_get(url)
        if not _esta_bloqueado(html):
            return html
        print(f"  [BROWSER FAIL] intentando requests: {url[:60]}", flush=True)
        html = _http_get(url)
        if not _esta_bloqueado(html):
            return html

    elif _PERFIL == PERFIL_MEDIO:
        html = _http_get(url)
        if not _esta_bloqueado(html):
            return html
        print(f"  [CF BLOQUEADO] intentando browser: {url[:60]}", flush=True)
        html = _browser_get(url)
        if not _esta_bloqueado(html):
            return html

    else:
        html = _http_get(url)
        if not _esta_bloqueado(html):
            return html

    print(f"  [WAYBACK] {url[:60]}", flush=True)
    return _wayback_get(url)


def _extraer_titulo(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og and (c := og.get("content", "").strip()):
        return c
    h1 = soup.find("h1")
    if h1 and (t := h1.get_text(strip=True)):
        return t
    title = soup.find("title")
    if title and (t := title.get_text(strip=True)):
        return t
    return ""


def _extraer_articulo(html: str, url: str) -> dict | None:
    try:
        result = trafilatura.extract(
            html, output_format="json", url=url,
            include_links=False, include_images=False,
        )
        if result:
            data = json.loads(result)
            titulo = (data.get("title") or "").strip() or _extraer_titulo(html)
            cuerpo = data.get("text") or ""
            fecha = data.get("date") or ""
            if titulo and cuerpo and len(cuerpo) > 100:
                return {"titulo": titulo, "cuerpo": cuerpo, "fecha": fecha, "url": url, "fuente": "custom"}
    except Exception:
        pass
    return None


_PATRON_FECHA = re.compile(r"/\d{4}/\d{2}/\d{2}/")


def _es_link_articulo(url: str, texto: str, dominio: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != dominio:
        return False
    path = parsed.path.lower()
    if not path or path == "/":
        return False
    if any(s in path for s in _PAGINAS_SALTAR):
        return False
    if any(url.endswith(ext) for ext in [".pdf", ".jpg", ".png", ".mp4", ".zip", ".xml", ".json"]):
        return False
    if len(texto) < 25:
        return False
    return True


def _encontrar_links(html: str, base_url: str) -> list[str]:
    dominio = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "lxml")
    vistos = set()
    con_fecha = []
    sin_fecha = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        texto = a.get_text(strip=True)
        url_completa = urljoin(base_url, href)

        if not href or not texto or url_completa in vistos:
            continue
        vistos.add(url_completa)
        if not _es_link_articulo(url_completa, texto, dominio):
            continue

        if _PATRON_FECHA.search(url_completa):
            con_fecha.append(url_completa)
        else:
            sin_fecha.append(url_completa)

    return con_fecha + sin_fecha


def _fetch_and_extract(link: str) -> dict | None:
    html = _fetch(link)
    if not html:
        return None
    return _extraer_articulo(html, link)


def _procesar_individual(url: str, items: list):
    print(f"\n>>> URL (individual): {url}", flush=True)
    html = _fetch(url)
    if not html:
        print("  [ERROR] No se pudo obtener HTML", flush=True)
        return
    art = _extraer_articulo(html, url)
    if art:
        print(f"  [OK] {art['titulo'][:90]}", flush=True)
        items.append(art)
    else:
        print("  [FAIL] No se pudo extraer contenido", flush=True)


def _procesar_listado(url: str, max_articulos: int, items: list):
    print(f"\n>>> URL (listado): {url}", flush=True)

    html = _fetch(url)
    if not html:
        print("  [ERROR] No se pudo obtener HTML del listado", flush=True)
        return

    enlaces = _encontrar_links(html, url)
    if not enlaces:
        print("  [ERROR] No se encontraron enlaces a artículos", flush=True)
        return

    candidatos = enlaces[: max_articulos * 3]
    print(f"  -> {len(enlaces)} enlaces encontrados, procesando {len(candidatos)} candidatos con {_MAX_WORKERS} workers...", flush=True)

    lock_items = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_and_extract, link): link for link in candidatos}
        for fut in as_completed(futures):
            if len(lock_items) >= max_articulos:
                for f in futures:
                    f.cancel()
                break
            try:
                art = fut.result()
            except Exception as e:
                print(f"    [ERROR] {e}", flush=True)
                continue
            if art:
                print(f"    [OK] {art['titulo'][:90]}", flush=True)
                lock_items.append(art)
            else:
                print(f"    [FAIL] {futures[fut][:60]}", flush=True)

    items.extend(lock_items[:max_articulos])


def start(urls: list[str], max_articulos: int = 5, modo: str = "list") -> _Result:
    items = []
    for url in urls:
        if modo == "single":
            _procesar_individual(url, items)
        else:
            _procesar_listado(url, max_articulos, items)
    print(f"\n>>> Total artículos extraídos: {len(items)}", flush=True)
    return _Result(items)
