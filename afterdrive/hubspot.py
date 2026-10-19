"""
hubspot.py — Publica Notas aprobadas en el blog de HubSpot.

Interfaz:
    configurado() -> bool
    enviar(nota, publicar=False) -> dict   {"id", "url", "estado"}
    vista_previa(nota) -> dict              lo que se mandaría, sin llamar a HubSpot
    preparar(contenido) -> dict             título, cuerpo HTML y meta description
    ErrorHubSpot

Usa la API de CMS v3 (POST/PATCH /cms/v3/blogs/posts) con el token de una app
privada de HubSpot con el scope "content". Configuración:
    HUBSPOT_TOKEN      token de la app privada (Configuración > Integraciones > Apps privadas)
    HUBSPOT_BLOG_ID    id del blog (contentGroupId)
    HUBSPOT_AUTOR_ID   opcional: blogAuthorId
    HUBSPOT_IMAGEN_DEFAULT  opcional: imagen destacada para las notas que no tienen una propia
    HUBSPOT_IDIOMA     opcional: idioma de las etiquetas nuevas (es por defecto)

Las etiquetas del post salen de las categorías de la Nota: se buscan en el blog
y se crean las que falten. Si eso falla, la nota se publica igual, sin etiquetas.

Si la Nota ya se envió antes (tiene hubspot.id), se actualiza esa misma entrada
en lugar de crear otra: reenviar después de editar no duplica posts.
"""

from __future__ import annotations

import os
import re
import unicodedata

import markdown
import requests

API = "https://api.hubapi.com/cms/v3/blogs/posts"
API_TAGS = "https://api.hubapi.com/cms/v3/blogs/tags"
TIMEOUT_S = 30

_transporte = {"post": requests.post, "patch": requests.patch, "get": requests.get}   # seam para los tests
_tags_cache: dict[str, str] = {}   # nombre en minúsculas -> id de la etiqueta en HubSpot


class ErrorHubSpot(RuntimeError):
    """Fallo al publicar, con un mensaje apto para el usuario."""


def configurado() -> bool:
    return bool(os.getenv("HUBSPOT_TOKEN") and os.getenv("HUBSPOT_BLOG_ID"))


def _slug(texto: str, sufijo: str = "") -> str:
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-")[:80].rstrip("-")
    return f"{slug}-{sufijo}" if sufijo else slug


def preparar(contenido: str) -> dict:
    """Separa el título (# ...) y la meta description (*...* al final) del cuerpo.

    HubSpot muestra el título aparte: si quedara también en el cuerpo, saldría
    dos veces. La meta description de la Nota es la última línea en cursiva.
    """
    from afterdrive.ia.saneo import normalizar_formato

    # Las notas anteriores al arreglo de formato también salen bien.
    lineas = normalizar_formato((contenido or "").strip()).splitlines()
    titulo = ""
    for i, ln in enumerate(lineas):
        if ln.startswith("# "):
            titulo = ln[2:].strip().strip("*_ ")
            del lineas[i]
            break
    meta = ""
    while lineas and not lineas[-1].strip():
        lineas.pop()
    if lineas:
        ultima = lineas[-1].strip()
        m = re.fullmatch(r"[*_]{1,2}([^*_].*?)[*_]{1,2}", ultima)
        if m and len(m.group(1)) <= 300:
            meta = m.group(1).strip()
            lineas.pop()
    # Sin HTML crudo: si el modelo escribió un <script> o un <iframe>, llegaría
    # tal cual al blog. Las notas son Markdown; un "<" literal se ve igual.
    cuerpo = "\n".join(lineas).strip().replace("<", "&lt;")
    if not titulo:
        raise ErrorHubSpot("La nota no tiene título (una línea que empiece con '# ').")
    return {
        "titulo": titulo,
        "html": markdown.markdown(cuerpo, extensions=["extra", "sane_lists"]),
        "meta": meta[:300],
    }


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('HUBSPOT_TOKEN', '')}", "Content-Type": "application/json"}


def _error(resp) -> ErrorHubSpot:
    try:
        detalle = resp.json().get("message", "")
    except Exception:
        detalle = (resp.text or "")[:200]
    if resp.status_code in (401, 403):
        return ErrorHubSpot("HubSpot rechazó el token: revisá HUBSPOT_TOKEN y que la app privada tenga el scope 'content'.")
    if resp.status_code == 404:
        return ErrorHubSpot("HubSpot no encontró el blog o el post: revisá HUBSPOT_BLOG_ID.")
    if resp.status_code == 429:
        return ErrorHubSpot("HubSpot está limitando las llamadas (429): probá de nuevo en un minuto.")
    return ErrorHubSpot(f"HubSpot respondió {resp.status_code}: {detalle}")


def despublicar(post_id: str) -> None:
    """Vuelve un post de HubSpot a borrador: deja de verse en el blog."""
    if not configurado():
        raise ErrorHubSpot("HubSpot no está configurado: faltan HUBSPOT_TOKEN y HUBSPOT_BLOG_ID.")
    try:
        resp = _transporte["patch"](f"{API}/{post_id}", json={"state": "DRAFT"}, headers=_headers(), timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErrorHubSpot(f"No se pudo conectar con HubSpot: {e}") from e
    if resp.status_code >= 400:
        raise _error(resp)


def _nombres_etiquetas(nota: dict) -> list[str]:
    from afterdrive.generacion.scraper_afterdrive import CATEGORIAS
    return [CATEGORIAS.get(c, c) for c in nota.get("categorias") or []]


def _imagen(nota: dict, titulo: str) -> dict:
    """{url, alt} de la imagen destacada: la de la nota o la de por defecto."""
    propia = nota.get("imagen") or {}
    url = propia.get("url") or os.getenv("HUBSPOT_IMAGEN_DEFAULT", "").strip()
    return {"url": url, "alt": propia.get("alt") or titulo} if url else {}


def vista_previa(nota: dict) -> dict:
    """Lo que se mandaría a HubSpot (título, meta, imagen, etiquetas y cuerpo), sin llamarlo."""
    partes = preparar(nota.get("contenido", ""))
    previo = nota.get("hubspot") or {}
    return {
        **partes,
        "imagen": _imagen(nota, partes["titulo"]),
        "etiquetas": _nombres_etiquetas(nota),
        "slug": previo.get("slug") or _slug(partes["titulo"], str(nota.get("_id", ""))[-6:]),
    }


def _ids_etiquetas(nombres: list[str]) -> list[str]:
    """Ids de HubSpot de estas etiquetas, creando las que falten.

    Nunca frena la publicación: si la API de etiquetas falla, se publica sin ellas.
    """
    if not nombres:
        return []
    try:
        if not _tags_cache:
            despues = None
            while True:
                params = {"limit": 100, **({"after": despues} if despues else {})}
                resp = _transporte["get"](API_TAGS, params=params, headers=_headers(), timeout=TIMEOUT_S)
                if resp.status_code >= 400:
                    raise _error(resp)
                data = resp.json()
                _tags_cache.update({t["name"].strip().lower(): str(t["id"]) for t in data.get("results", [])})
                despues = ((data.get("paging") or {}).get("next") or {}).get("after")
                if not despues:
                    break
        ids = []
        for nombre in nombres:
            clave = nombre.strip().lower()
            if clave not in _tags_cache:
                resp = _transporte["post"](API_TAGS, json={"name": nombre, "language": os.getenv("HUBSPOT_IDIOMA", "es")},
                                           headers=_headers(), timeout=TIMEOUT_S)
                if resp.status_code >= 400:
                    raise _error(resp)
                _tags_cache[clave] = str(resp.json()["id"])
            ids.append(_tags_cache[clave])
        return ids
    except Exception as e:
        print(f"[HubSpot] No se pudieron preparar las etiquetas ({e}); se publica sin ellas.", flush=True)
        return []


def enviar(nota: dict, publicar: bool = False) -> dict:
    """Crea (o actualiza) el post de la Nota en HubSpot, como borrador o publicado.

    nota: documento de Mongo con "_id", "contenido" y opcionalmente "hubspot",
    "imagen" y "categorias".
    """
    if not configurado():
        raise ErrorHubSpot("HubSpot no está configurado: faltan HUBSPOT_TOKEN y HUBSPOT_BLOG_ID.")
    partes = preparar(nota.get("contenido", ""))
    cuerpo = {
        "contentGroupId": os.getenv("HUBSPOT_BLOG_ID"),
        "name": partes["titulo"],
        "htmlTitle": partes["titulo"],
        "postBody": partes["html"],
        "metaDescription": partes["meta"],
        "state": "PUBLISHED" if publicar else "DRAFT",
    }
    if os.getenv("HUBSPOT_AUTOR_ID"):
        cuerpo["blogAuthorId"] = os.getenv("HUBSPOT_AUTOR_ID")
    imagen = _imagen(nota, partes["titulo"])
    if imagen:
        cuerpo.update(useFeaturedImage=True, featuredImage=imagen["url"], featuredImageAltText=imagen["alt"])
    etiquetas = _ids_etiquetas(_nombres_etiquetas(nota))
    if etiquetas:
        cuerpo["tagIds"] = etiquetas

    previo = (nota.get("hubspot") or {}).get("id")
    try:
        if previo:
            resp = _transporte["patch"](f"{API}/{previo}", json=cuerpo, headers=_headers(), timeout=TIMEOUT_S)
        else:
            # El slug va solo al crear: cambiarlo después rompería links ya compartidos.
            cuerpo["slug"] = _slug(partes["titulo"], str(nota.get("_id", ""))[-6:])
            resp = _transporte["post"](API, json=cuerpo, headers=_headers(), timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErrorHubSpot(f"No se pudo conectar con HubSpot: {e}") from e
    if resp.status_code >= 400:
        raise _error(resp)
    data = resp.json()
    return {
        "id": str(data.get("id") or previo),
        "url": data.get("url") or "",
        "estado": data.get("state") or cuerpo["state"],
        "slug": data.get("slug") or cuerpo.get("slug") or (nota.get("hubspot") or {}).get("slug") or "",
    }
