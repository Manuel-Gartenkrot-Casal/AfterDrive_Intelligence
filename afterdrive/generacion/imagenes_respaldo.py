"""
imagenes_respaldo.py — Fotos de bancos de imágenes para cuando las noticias no alcanzan.

Interfaz:
    buscador(titulo, angulo="") -> función(ronda) -> list[Noticia]
    buscar(consulta, por_banco=PIDE_POR_BANCO, pagina=1) -> list[Noticia]
    consultas(titulo, angulo="") -> list[str]

Una nota lleva imagen_destacada.CANTIDAD fotos y no repite las de otras notas:
cuando las fotos de las noticias se agotan, imagen_destacada.elegir pide más
acá, una búsqueda por ronda, hasta completar. Cada foto vuelve como una
Noticia (sin cuerpo) para que la IA la juzgue igual que a las de las noticias.

Bancos, en orden:
- Pexels (si está PEXELS_API_KEY): fotos de stock de uso libre, sin atribución.
- Wikimedia Commons (siempre, sin clave): solo licencias que permiten uso
  comercial (dominio público, CC0, CC BY y CC BY-SA). Las CC BY/BY-SA piden
  atribución: llevan `credito` y `atribucion: True`, van con su crédito dentro
  del texto y nunca de portada (HubSpot no muestra crédito en la destacada).

Las búsquedas son en inglés (los bancos tienen mucho más material así): la IA
las arma con el título de la nota y, si falla, se usan búsquedas del sector.
Nunca lanza: un banco caído devuelve [].
"""

from __future__ import annotations

import html
import os
import re

import requests

from afterdrive.generacion.contexto_noticias import Noticia

PIDE_POR_BANCO = 12
ANCHO = 1600
TIMEOUT = (5, 20)
USER_AGENT = "AfterDrive/1.0 (https://afterdrive.alephee.com; blog B2B del aftermarket automotor)"
# Si la IA no arma las búsquedas: temas del sector que siempre tienen fotos.
CONSULTAS_SECTOR = [
    "auto parts", "car repair workshop", "auto parts warehouse", "car mechanic engine",
    "automotive factory assembly line", "brake disc", "car tires stack", "truck logistics",
]
_LICENCIAS_LIBRES = re.compile(r"^(public domain|pd\b|cc0|no restrictions)", re.I)
_LICENCIAS_ATRIBUCION = re.compile(r"^cc[ -]by(-sa)?[ -]\d", re.I)
_MIMES = {"image/jpeg", "image/png", "image/webp"}
_transporte = {"get": requests.get}   # seam para los tests

_SYSTEM = """\
Sos el editor de fotografía del blog B2B AfterDrive (aftermarket automotor en Latinoamérica). Te paso el \
título de una nota y armás búsquedas para un banco de fotos de stock (Pexels, Wikimedia Commons).

- En inglés, de 2 a 4 palabras cada una, con cosas que se pueden fotografiar (objetos, lugares, actividades): \
"brake pads", "auto parts store shelves", "car assembly line". Nada de conceptos abstractos ni nombres de empresas.
- La primera, lo más cerca posible del tema concreto de la nota; las siguientes, cada vez más generales \
dentro del sector (repuestos, talleres, depósitos, logística, fábricas de autos).
- Sin personas como protagonistas.

Respondé solo con este JSON: {"consultas": ["...", "...", "...", "...", "..."]}"""


def consultas(titulo: str, angulo: str = "") -> list[str]:
    """Búsquedas en inglés para la nota: las de la IA y después las del sector, sin repetir."""
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    propias = []
    try:
        pedido = f"Título de la nota: {titulo}" + (f"\nÁngulo: {angulo}" if angulo else "")
        data = _extraer_json(llm.completar(_SYSTEM, pedido, temperature=0.3, max_tokens=300, tarea="clasificacion"))
        propias = [" ".join(str(c).split())[:60] for c in data.get("consultas") or [] if isinstance(c, str)]
    except llm.Cancelada:
        raise
    except Exception as e:
        print(f"  [AVISO] La IA no armó las búsquedas del banco de imágenes ({e}): van las del sector.", flush=True)
    vistas, resultado = set(), []
    for c in [c for c in propias if c] + CONSULTAS_SECTOR:
        if c.lower() not in vistas:
            vistas.add(c.lower())
            resultado.append(c)
    return resultado


def buscador(titulo: str, angulo: str = ""):
    """Función ronda -> fotos: la ronda N usa la búsqueda N (las búsquedas se arman una sola vez).
    Pasadas todas las búsquedas, vuelve a empezar con la página siguiente de resultados."""
    lista: list[str] = []

    def buscar_ronda(ronda: int) -> list[Noticia]:
        if not lista:
            lista.extend(consultas(titulo, angulo))
        consulta = lista[ronda % len(lista)]
        pagina = ronda // len(lista) + 1
        print(f"  Buscando fotos en bancos de imágenes: \"{consulta}\""
              f"{f' (página {pagina})' if pagina > 1 else ''}...", flush=True)
        return buscar(consulta, pagina=pagina)
    return buscar_ronda


def buscar(consulta: str, por_banco: int = PIDE_POR_BANCO, pagina: int = 1) -> list[Noticia]:
    """Fotos de los bancos para la búsqueda: primero las de Pexels (si hay clave), después las de Commons."""
    fotos = []
    for banco in (_pexels, _commons):
        try:
            fotos += banco(consulta, por_banco, pagina)
        except Exception as e:
            print(f"  [AVISO] El banco de imágenes {banco.__name__.strip('_')} no respondió: {e}", flush=True)
    return fotos


def _foto(consulta: str, url: str, alt: str, pagina_url: str, banco: str, credito: str,
          atribucion: bool) -> Noticia:
    imagen = {"url": url, "alt": alt, "credito": credito, "banco": banco}
    if atribucion:
        imagen["atribucion"] = True
    return Noticia(id=None, titulo=f"Foto de banco de imágenes ({banco}) para \"{consulta}\": {alt or consulta}",
                   cuerpo="", url=pagina_url, fuente=banco, imagen=imagen, imagen_buscada=True,
                   imagenes=[], refrescable=False)


def _pexels(consulta: str, cantidad: int, pagina: int) -> list[Noticia]:
    clave = os.getenv("PEXELS_API_KEY", "").strip()
    if not clave:
        return []
    resp = _transporte["get"]("https://api.pexels.com/v1/search", timeout=TIMEOUT,
                              params={"query": consulta, "per_page": cantidad, "page": pagina,
                                      "orientation": "landscape"},
                              headers={"Authorization": clave, "User-Agent": USER_AGENT})
    resp.raise_for_status()
    fotos = []
    for p in resp.json().get("photos") or []:
        url = (p.get("src") or {}).get("large2x") or (p.get("src") or {}).get("large")
        if url and url.startswith("https://"):
            autor = p.get("photographer") or "Pexels"
            fotos.append(_foto(consulta, url, " ".join(str(p.get("alt") or "").split())[:200],
                               p.get("url") or "https://www.pexels.com", "Pexels",
                               f"Foto: {autor} / Pexels", atribucion=False))
    return fotos


def _texto(valor) -> str:
    """Texto plano de un campo de extmetadata de Commons (viene con HTML)."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(valor or ""))).split())


def _commons(consulta: str, cantidad: int, pagina: int) -> list[Noticia]:
    resp = _transporte["get"]("https://commons.wikimedia.org/w/api.php", timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                              params={"action": "query", "format": "json", "generator": "search",
                                      "gsrnamespace": 6, "gsrsearch": f"{consulta} filetype:bitmap",
                                      "gsrlimit": cantidad * 2, "gsroffset": (pagina - 1) * cantidad * 2,
                                      "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
                                      "iiurlwidth": ANCHO, "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription"})
    resp.raise_for_status()
    paginas = sorted(((resp.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 0))
    fotos = []
    for p in paginas:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licencia = _texto((meta.get("LicenseShortName") or {}).get("value"))
        libre = bool(_LICENCIAS_LIBRES.match(licencia))
        if info.get("mime") not in _MIMES or (info.get("width") or 0) < 800 \
                or not (libre or _LICENCIAS_ATRIBUCION.match(licencia)):
            continue
        url = info.get("thumburl") or info.get("url") or ""
        if not url.startswith("https://"):
            continue
        autor = _texto((meta.get("Artist") or {}).get("value"))[:80] or "Wikimedia Commons"
        alt = _texto((meta.get("ImageDescription") or {}).get("value"))[:200] \
            or re.sub(r"^File:|\.\w+$", "", p.get("title", "")).replace("_", " ")
        fotos.append(_foto(consulta, url, alt, info.get("descriptionurl") or "https://commons.wikimedia.org",
                           "Wikimedia Commons", f"Foto: {autor} / Wikimedia Commons ({licencia})",
                           atribucion=not libre))
        if len(fotos) >= cantidad:
            break
    return fotos
