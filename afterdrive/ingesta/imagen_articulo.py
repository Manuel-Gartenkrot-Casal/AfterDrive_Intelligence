"""
imagen_articulo.py — La imagen principal de un Artículo, sacada de su HTML.

Interfaz:
    extraer(html, url) -> {"url", "alt"} | None
    extraer_todas(html, url, limite=MAX_IMAGENES) -> [{"url", "alt"}, ...]   la principal primero
    valida(url) -> bool

Es la foto que el sitio eligió para compartir la noticia, en este orden:
og:image, twitter:image, la "image" del JSON-LD (schema.org) y, si no hay
ninguna, la primera <img> dentro de <article> o <main>.

extraer_todas suma las otras fotos del cuerpo de la nota (las <img> de
<article> o <main>): una nota lleva varias imágenes y con una por noticia
el pozo de fotos sin repetir se agotaba.

Solo https: el dashboard la muestra directo (la CSP no deja cargar http) y al
subir la nota se copia a los archivos de HubSpot. Se descartan logos, íconos,
avatares y placeholders: muchos sitios ponen su logo en og:image cuando la
nota no tiene foto propia.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Un tramo del nombre de archivo o de la ruta que delata que no es una foto de la noticia.
_NO_ES_FOTO = re.compile(
    r"(?:^|[/_.\-])(?:logos?|favicons?|icons?|avatars?|placeholders?|sprites?|gravatar|blank|"
    r"default|no-?image|spacer|pixel)(?:[/_.\-]|$)",
    re.IGNORECASE,
)
_EXTENSIONES_NO = (".svg", ".gif", ".ico")
MAX_IMAGENES = 8
ANCHO_MINIMO = 300   # una <img> que declara menos de esto es una miniatura o un ícono
# El mismo archivo en otro tamaño (WordPress: foto-300x200.jpg): cuenta como la misma foto.
_TAMANIO = re.compile(r"-\d{2,4}x\d{2,4}(?=\.\w+$)")
_META = (
    {"property": "og:image:secure_url"}, {"property": "og:image"}, {"property": "og:image:url"},
    {"name": "twitter:image"}, {"name": "twitter:image:src"}, {"property": "twitter:image"},
    {"itemprop": "image"},
)


def valida(url: str) -> bool:
    """https, con un host con dominio, y que no parezca un logo o un ícono."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    ruta = p.path.lower()
    return (p.scheme == "https" and "." in (p.hostname or "")
            and not ruta.endswith(_EXTENSIONES_NO) and not _NO_ES_FOTO.search(ruta))


def _de_ld(data) -> list[str]:
    """URLs de imagen en un bloque JSON-LD (str, lista, {"url"} o dentro de @graph)."""
    if isinstance(data, list):
        return [u for d in data for u in _de_ld(d)]
    if not isinstance(data, dict):
        return []
    urls = _de_ld(data["@graph"]) if "@graph" in data else []
    imagen = data.get("image") or data.get("thumbnailUrl")
    for i in imagen if isinstance(imagen, list) else [imagen]:
        if isinstance(i, str):
            urls.append(i)
        elif isinstance(i, dict) and isinstance(i.get("url") or i.get("contentUrl"), str):
            urls.append(i.get("url") or i.get("contentUrl"))
    return urls


def _ancho_chico(img) -> bool:
    for attr in ("width", "height"):
        valor = str(img.get(attr) or "").strip().removesuffix("px")
        if valor.isdigit() and int(valor) < ANCHO_MINIMO:
            return True
    return False


def _candidatas(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """(url, alt) de las imágenes de la página: primero las que el sitio eligió para compartir."""
    alt_meta = _alt(soup)
    urls = []
    for attrs in _META:
        for tag in soup.find_all("meta", attrs=attrs):
            if tag.get("content"):
                urls.append((tag["content"], alt_meta))
    for link in soup.find_all("link", rel="image_src"):
        if link.get("href"):
            urls.append((link["href"], alt_meta))
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            urls += [(u, alt_meta) for u in _de_ld(json.loads(script.string or ""))]
        except (ValueError, TypeError):
            continue
    cuerpo = soup.find("article") or soup.find("main")
    for img in (cuerpo.find_all("img") if cuerpo else []):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        if src and not src.startswith("data:") and not _ancho_chico(img):
            urls.append((src, " ".join(str(img.get("alt") or "").split())[:200]))
    return urls


def _alt(soup: BeautifulSoup) -> str:
    tag = soup.find("meta", property="og:image:alt") or soup.find("meta", attrs={"name": "twitter:image:alt"})
    return " ".join((tag.get("content") if tag else "").split())[:200]


def extraer(html: str | None, url: str) -> dict | None:
    """{"url", "alt"} de la imagen principal, o None si la página no tiene una usable."""
    todas = extraer_todas(html, url, limite=1)
    return todas[0] if todas else None


def extraer_todas(html: str | None, url: str, limite: int = MAX_IMAGENES) -> list[dict]:
    """[{"url", "alt"}] de las fotos de la página, sin repetir, la principal primero."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []
    alt_meta = _alt(soup)
    # Las completas primero: una relativa sin "/" (p. ej. "images/x.jpg" en sitios Joomla sin <base>)
    # se pega a la ruta de la nota y da 404, y el mismo sitio suele repetir la foto completa más abajo.
    candidatas = sorted(_candidatas(soup), key=lambda c: not re.match(r"\s*(https?:)?//", c[0], re.I))
    vistas, resultado = set(), []
    for candidata, alt in candidatas:
        absoluta = urljoin(url, candidata.strip())
        if absoluta.startswith("//"):
            absoluta = "https:" + absoluta
        clave = _TAMANIO.sub("", urlparse(absoluta).path.lower())
        if not valida(absoluta) or clave in vistas:
            continue
        vistas.add(clave)
        # La principal lleva el alt del og:image (la de la nota), aunque venga de una <img>.
        resultado.append({"url": absoluta, "alt": alt_meta if not resultado else alt})
        if len(resultado) >= limite:
            break
    return resultado
