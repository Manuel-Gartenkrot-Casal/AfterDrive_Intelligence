import datetime
import ipaddress
import json
import re
import socket
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from urllib3.util import parse_url

from afterdrive.ingesta import feeds, imagen_articulo
from afterdrive.ingesta.resource_detector import (
    PERFIL_ALTO,
    PERFIL_MEDIO,
    get_max_workers,
    get_perfil,
    usar_browser,
)

_PERFIL = get_perfil()
_MAX_WORKERS = get_max_workers()

print(f"[scraper] perfil='{_PERFIL}' workers={_MAX_WORKERS} browser={'si' if usar_browser() else 'no'}", flush=True)

FETCH_OPTS = {
    "headless": True,
    "disable_resources": True,
    "timeout": 10000,
    "extra_flags": [
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
    def __init__(self, items, descartes=None):
        self.items = items
        self.descartes = dict(descartes or {})   # motivo -> cuántos links no dieron un artículo


MIN_CUERPO = 100   # caracteres de texto: menos que eso no es una nota

# Por qué un link no terminó en artículo, para ver en el log dónde se pierden.
MOTIVOS = {
    "sin_html": "no se pudo bajar la página",
    "sin_texto": "la página no tiene texto de nota (portada de sección, video, galería)",
    "sin_titulo": "sin título",
    "cuerpo_corto": f"{MIN_CUERPO} caracteres de texto o menos",
    "error": "error al leer la página",
    "sin_probar": "no se probaron (tope de candidatos por fuente)",
}
_DESCARTES: Counter = Counter()
_LOCK_DESCARTES = threading.Lock()


def _descartar(motivo: str, cuantos: int = 1, url: str = "", detalle: str = "") -> None:
    with _LOCK_DESCARTES:
        _DESCARTES[motivo] += cuantos
    if detalle:
        print(f"    [DESCARTE {motivo}] {url[:60]}: {detalle[:120]}", flush=True)


def resumen_descartes(descartes: dict) -> str:
    """'cuerpo_corto 4 (...), sin_html 2 (...)', de mayor a menor."""
    return ", ".join(f"{m} {n} ({MOTIVOS.get(m, m)})" for m, n in sorted(descartes.items(), key=lambda t: -t[1]))


def _esta_bloqueado(html: str | None) -> bool:
    if not html or len(html) < 500:
        return True
    return any(s in html for s in _BLOQUEOS_CF)


# Dominios cuyo origen no respondió en esta corrida (timeout / conexión
# rechazada). Sus artículos van directo a Wayback en vez de esperar el mismo
# timeout por cada link. Se vacía al empezar cada start(): el scraping corre
# dentro del proceso del servidor, que vive días, y un timeout de ayer no
# tiene que mandar hoy la fuente entera a Wayback.
_ORIGEN_CAIDO: set[str] = set()


def _direcciones(url) -> list[str] | None:
    """IPs a las que resuelve el host de una URL http(s).

    None si la URL no es válida; [] si es válida pero el dominio no resuelve.
    """
    try:
        if not isinstance(url, str) or "\\" in url or any(c.isspace() or not c.isprintable() for c in url):
            return None
        # El host se saca con el parser de requests (urllib3), no con urlparse:
        # en "http://127.0.0.1\\@sitio.com/" urlparse ve sitio.com y requests
        # se conecta a 127.0.0.1. Hay que validar el host que se va a visitar.
        partes = parse_url(url)
        if partes.scheme not in ("http", "https") or not partes.host:
            return None
        infos = socket.getaddrinfo(partes.host.strip("[]"), None)
    except socket.gaierror:
        return []
    except Exception:
        return None
    return [info[4][0] for info in infos]


def _todas_publicas(ips: list[str]) -> bool:
    try:
        return all(ipaddress.ip_address(ip).is_global for ip in ips)
    except ValueError:
        return False


def url_publica(url) -> bool:
    """True si la URL es http(s) y su host resuelve solo a direcciones públicas.

    El scraper visita lo que le pasen por la API y los links que encuentra en
    las páginas: sin este filtro se lo podría apuntar a la red interna del
    servidor (localhost, IPs privadas, metadata del proveedor cloud).
    """
    # ponytail: se valida al resolver, no al conectar. No cubre redirecciones
    # hacia hosts internos ni DNS rebinding; para eso hay que fijar la IP
    # resuelta en la conexión (adapter de requests) y validar cada salto.
    ips = _direcciones(url)
    return bool(ips) and _todas_publicas(ips)


def _http_get(url: str, timeout: int = 10) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers=_HEADERS)
        r.raise_for_status()
        return r.text
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        _ORIGEN_CAIDO.add(urlparse(url).netloc)
        return None
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


def _sin_esquema(url: str) -> str:
    return url.split("://", 1)[-1].removeprefix("www.").rstrip("/")


def _wayback_get(url: str) -> str | None:
    """Última copia de la URL en Wayback Machine, con el HTML original.

    El modo `id_` devuelve la página tal como se archivó (links sin reescribir
    a /web/...), así que el listado sirve para encontrar artículos igual que
    el sitio real. Se pide la copia más cercana a hoy y se verifica que
    Wayback no haya redirigido a otra página.
    """
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")
    try:
        r = requests.get(f"https://web.archive.org/web/{ts}id_/{url}", timeout=15, headers=_HEADERS)
    except Exception:
        return None
    if not r.ok:
        return None
    archivada = r.url.split("id_/", 1)[-1]
    if _sin_esquema(archivada) != _sin_esquema(url):
        return None
    return None if _esta_bloqueado(r.text) else r.text


def _fetch(url: str) -> str | None:
    """
    Estrategia adaptativa según perfil de recursos:

    ALTO:  Chromium → requests → Wayback
    MEDIO: requests → (si bloqueado) Chromium → Wayback
    BAJO:  requests → Wayback (sin Chromium nunca)

    Si el origen del dominio ya no respondió en esta corrida, va directo a Wayback.
    """
    ips = _direcciones(url)
    if ips is None or not _todas_publicas(ips):
        print(f"  [URL BLOQUEADA] no es http(s) pública: {str(url)[:60]}", flush=True)
        return None
    if not ips:
        # El dominio no resuelve: no hay origen que visitar, pero sí puede
        # haber copia archivada (Wayback no toca el host).
        _ORIGEN_CAIDO.add(urlparse(url).netloc)

    if urlparse(url).netloc in _ORIGEN_CAIDO:
        return _wayback_get(url)

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

    if urlparse(url).netloc in _ORIGEN_CAIDO:
        print(f"  [ORIGEN SIN RESPUESTA] {urlparse(url).netloc}: se usa la copia de Wayback Machine", flush=True)
    else:
        print(f"  [WAYBACK] {url[:60]}", flush=True)
    return _wayback_get(url)


def descargar(url: str) -> str | None:
    """HTML de una página con la misma estrategia que el scraping (origen, navegador o Wayback)."""
    return _fetch(url)


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
    """El artículo de la página, o None (el motivo queda contado en _DESCARTES)."""
    try:
        result = trafilatura.extract(
            html, output_format="json", url=url,
            include_links=False, include_images=False,
        )
        if not result:
            _descartar("sin_texto")
            return None
        data = json.loads(result)
        titulo = (data.get("title") or "").strip() or _extraer_titulo(html)
        cuerpo = data.get("text") or ""
        fecha = data.get("date") or ""
        if not titulo:
            _descartar("sin_titulo")
            return None
        if len(cuerpo) <= MIN_CUERPO:
            _descartar("cuerpo_corto")
            return None
        # Las fotos del artículo, para la nota que salga de esta noticia: `imagen` es la principal
        # (None si no tiene) e `imagenes` todas las usables de la página, la principal primero.
        imagenes = imagen_articulo.extraer_todas(html, url)
        return {"titulo": titulo, "cuerpo": cuerpo, "fecha": fecha, "url": url, "fuente": "custom",
                "imagen": imagenes[0] if imagenes else None, "imagenes": imagenes}
    except Exception as e:
        # Antes se tragaba sin aviso: ahora se cuenta y se muestra, para ver qué páginas fallan.
        _descartar("error", url=url, detalle=f"{type(e).__name__}: {e}")
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
    return len(texto) >= 25


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


FEEDS_POR_FUENTE = 2        # feeds anunciados por la portada que se prueban
SITEMAPS_POR_INDICE = 3     # sitemaps de un índice que se leen (los de notas primero)


def _xml_get(url: str) -> str | None:
    """Un feed o sitemap: una descarga liviana, solo si la dirección es pública."""
    return _http_get(url) if url_publica(url) else None


def _es_nota_de_feed(url: str) -> bool:
    path = urlparse(url).path.lower()
    if not url.startswith(("http://", "https://")) or not path or path == "/":
        return False
    if any(s in path for s in _PAGINAS_SALTAR):
        return False
    return not any(path.endswith(ext) for ext in (".pdf", ".jpg", ".png", ".mp4", ".zip", ".xml", ".json"))


def _notas_del_feed(url: str, contenido: str | None) -> list[str]:
    """Las notas desde el RSS, Atom o sitemap: la fuente misma, o el feed que anuncia su portada.

    [] si no hay feed o no trae notas: entonces se buscan los links en el HTML como siempre.
    """
    if contenido and feeds.tipo(contenido):
        candidatos = [(url, contenido)]
    else:
        candidatos = [(f, None) for f in feeds.descubrir(contenido or "", url)[:FEEDS_POR_FUENTE]]
    for feed_url, xml in candidatos:
        feed = feeds.leer(xml or _xml_get(feed_url) or "")
        if feed is None:
            continue
        entradas = feed.entradas
        if feed.tipo == "indice":
            for hijo_url in feeds.sitemaps_de_notas(feed.sitemaps, SITEMAPS_POR_INDICE):
                hijo = feeds.leer(_xml_get(hijo_url) or "")
                entradas += hijo.entradas if hijo else []
            entradas = feeds.ordenar(entradas)
        links = list(dict.fromkeys(e.url for e in entradas if _es_nota_de_feed(e.url)))
        if links:
            nombre = {"rss": "RSS", "atom": "Atom", "sitemap": "Sitemap", "indice": "Sitemap"}[feed.tipo]
            print(f"  -> {nombre} {feed_url[:70]}: {len(links)} notas", flush=True)
            return links
    return []


def _fetch_and_extract(link: str) -> dict | None:
    html = _fetch(link)
    if not html:
        _descartar("sin_html")
        return None
    return _extraer_articulo(html, link)


def _procesar_individual(url: str, items: list):
    print(f"\n>>> URL (individual): {url}", flush=True)
    html = _fetch(url)
    if not html:
        _descartar("sin_html")
        print("  [ERROR] No se pudo obtener HTML", flush=True)
        return
    art = _extraer_articulo(html, url)
    if art:
        print(f"  [OK] {art['titulo'][:90]}", flush=True)
        items.append(art)
    else:
        print("  [FAIL] No se pudo extraer contenido", flush=True)


def _procesar_listado(url: str, max_articulos: int, items: list, omitir=None):
    print(f"\n>>> URL (listado): {url}", flush=True)

    # Una fuente que es un feed o un sitemap se baja como XML, sin navegador.
    html = (_xml_get(url) if feeds.parece_feed(url) else None) or _fetch(url)
    if not html:
        print("  [ERROR] No se pudo obtener HTML del listado", flush=True)
        return

    enlaces = _notas_del_feed(url, html) or _encontrar_links(html, url)
    if not enlaces:
        print("  [ERROR] No se encontraron enlaces a artículos", flush=True)
        return

    if omitir:
        conocidas = omitir(enlaces)
        if conocidas:
            enlaces = [e for e in enlaces if e not in conocidas]
            print(f"  -> {len(conocidas)} enlace(s) ya procesado(s) antes: se omiten", flush=True)
        if not enlaces:
            print("  [OK] Sin artículos nuevos en esta fuente.", flush=True)
            return

    candidatos = enlaces[: max_articulos * 3]
    if len(enlaces) > len(candidatos):
        _descartar("sin_probar", len(enlaces) - len(candidatos))
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


def start(urls: list[str], max_articulos: int = 5, modo: str = "list", omitir=None) -> _Result:
    """Scrapea las URLs (como listado o como artículo individual).

    omitir(links) -> set: los links que ya se procesaron en otra corrida. No se
    descargan ni se vuelven a clasificar.
    """
    _ORIGEN_CAIDO.clear()
    with _LOCK_DESCARTES:
        _DESCARTES.clear()
    items = []
    for url in urls:
        if modo == "single":
            _procesar_individual(url, items)
        else:
            _procesar_listado(url, max_articulos, items, omitir)
    print(f"\n>>> Total artículos extraídos: {len(items)}", flush=True)
    with _LOCK_DESCARTES:
        descartes = dict(_DESCARTES)
    if descartes:
        print(f">>> Links que no dieron artículo: {resumen_descartes(descartes)}", flush=True)
    return _Result(items, descartes)
