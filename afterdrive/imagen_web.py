"""
imagen_web.py — Descarga una imagen pública de internet.

Interfaz:
    descargar(url, max_bytes=None) -> (bytes, mime)    max_bytes None = MAX_BYTES
    url_valida(url) -> bool
    ErrorDescarga

La usan la copia de la imagen destacada a HubSpot y la elección de la foto
con IA (el modelo recibe los bytes, no el link). Como la URL sale de páginas
de terceros, cada salto de redirección se valida contra la red interna del
servidor (scraper.url_publica) y nunca se sigue una redirección sin revisar.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests

MAX_BYTES = 10 * 1024 * 1024
_transporte = {"get": requests.get}   # seam para los tests


class ErrorDescarga(RuntimeError):
    """La imagen no se pudo descargar, con un motivo apto para el usuario."""


def url_valida(url: str) -> bool:
    """https con un nombre de dominio (no una IP)."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = p.hostname or ""
    return p.scheme == "https" and "." in host and not re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host)


def descargar(url: str, max_bytes: int | None = None) -> tuple[bytes, str]:
    """(bytes, mime) de una imagen https pública. ErrorDescarga si no se puede."""
    max_bytes = max_bytes or MAX_BYTES
    from afterdrive.ingesta.scraper import url_publica

    for _ in range(4):
        if not url_valida(url) or not url_publica(url):
            raise ErrorDescarga("la imagen no está en una URL https pública")
        try:
            resp = _transporte["get"](url, timeout=(5, 20), stream=True, allow_redirects=False,
                                      headers={"User-Agent": "Mozilla/5.0 (AfterDrive)", "Accept": "image/*"})
        except requests.RequestException as e:
            raise ErrorDescarga(f"no se pudo descargar: {e}") from e
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
            url = urljoin(url, resp.headers["Location"])
            continue
        break
    else:
        raise ErrorDescarga("demasiadas redirecciones")
    if resp.status_code >= 400:
        raise ErrorDescarga(f"el sitio respondió {resp.status_code}")
    mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if not mime.startswith("image/") or mime == "image/svg+xml":
        raise ErrorDescarga(f"no es una imagen ({mime or 'sin tipo'})")
    contenido = b""
    for parte in resp.iter_content(64 * 1024):
        contenido += parte
        if len(contenido) > max_bytes:
            raise ErrorDescarga(f"la imagen pesa más de {max_bytes / 1024 / 1024:g} MB")
    if not contenido:
        raise ErrorDescarga("la imagen vino vacía")
    return contenido, mime
