"""
feeds.py — Leer las notas de una fuente desde su RSS, Atom o sitemap.

Interfaz:
    tipo(texto) -> "rss" | "atom" | "sitemap" | "indice" | None
    leer(texto) -> Feed(tipo, entradas=[Entrada(url, titulo, fecha)], sitemaps=[url])
    ordenar(entradas) -> [Entrada]       de la más nueva a la más vieja
    sitemaps_de_notas(sitemaps) -> [url] de un índice, los que listan notas
    descubrir(html, base_url) -> [url]   los feeds que anuncia una página (<link rel="alternate">)
    parece_feed(url) -> bool             por la dirección: .xml, /feed, /rss, /atom, sitemap

Antes el scraper solo leía el HTML de la portada y adivinaba qué links eran
notas: con un feed o un sitemap la lista de notas viene dada, con su fecha, y
alcanza una sola descarga liviana (sin navegador ni bloqueos de Cloudflare).

El XML viene de sitios de afuera: se lee sin resolver entidades ni ir a la red.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from lxml import etree

TIPOS_FEED = ("application/rss+xml", "application/atom+xml", "application/rdf+xml", "application/feed+json")
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)


@dataclass
class Entrada:
    url: str
    titulo: str = ""
    fecha: datetime.datetime | None = None


@dataclass
class Feed:
    tipo: str
    entradas: list[Entrada] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)   # solo en un índice de sitemaps


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _raiz(texto: str):
    if not texto or "<" not in texto[:2000]:
        return None
    try:
        return etree.fromstring(texto.lstrip().encode("utf-8"), _PARSER)
    except (etree.XMLSyntaxError, ValueError):
        return None


def tipo(texto: str) -> str | None:
    """Qué es el texto, mirando su elemento raíz. None si no es un feed ni un sitemap."""
    raiz = _raiz(texto)
    if raiz is None:
        return None
    return {"rss": "rss", "rdf": "rss", "feed": "atom", "urlset": "sitemap", "sitemapindex": "indice"}.get(_local(raiz.tag))


def parece_feed(url: str) -> bool:
    """Por la dirección: se baja como XML liviano, sin navegador."""
    path = urlparse(url).path.lower().rstrip("/")
    return path.endswith((".xml", ".rss", ".atom", "/feed", "/rss", "/atom")) or "sitemap" in path


def _fecha(texto: str | None) -> datetime.datetime | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        d = parsedate_to_datetime(texto)            # RSS: "Tue, 04 Nov 2026 10:00:00 GMT"
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.datetime.fromisoformat(texto.replace("Z", "+00:00"))   # Atom y sitemaps
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.UTC)


def _hijo(el, *nombres) -> str:
    """El texto del primer hijo (a cualquier profundidad) con alguno de esos nombres."""
    for e in el.iter():
        if e is not el and _local(e.tag) in nombres and (e.text or "").strip():
            return e.text.strip()
    return ""


def _link_atom(entry) -> str:
    for e in entry:
        if _local(e.tag) == "link" and e.get("rel", "alternate") == "alternate" and e.get("href"):
            return e.get("href").strip()
    return ""


def leer(texto: str) -> Feed | None:
    """Las notas del feed o sitemap, de la más nueva a la más vieja (las sin fecha, al final)."""
    raiz = _raiz(texto)
    t = tipo(texto)
    if raiz is None or t is None:
        return None
    feed = Feed(t)
    if t == "indice":
        feed.sitemaps = [loc for s in raiz if (loc := _hijo(s, "loc"))]
        return feed
    for el in raiz.iter():
        nombre = _local(el.tag)
        if t == "rss" and nombre == "item":
            url = _hijo(el, "link") or (el.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or "")
            feed.entradas.append(Entrada(url, _hijo(el, "title"), _fecha(_hijo(el, "pubdate", "date"))))
        elif t == "atom" and nombre == "entry":
            feed.entradas.append(Entrada(_link_atom(el), _hijo(el, "title"), _fecha(_hijo(el, "published", "updated"))))
        elif t == "sitemap" and nombre == "url":
            # Un sitemap de noticias (news:) trae título y fecha de publicación.
            feed.entradas.append(Entrada(_hijo(el, "loc"), _hijo(el, "title"),
                                         _fecha(_hijo(el, "publication_date", "lastmod"))))
    feed.entradas = ordenar([e for e in feed.entradas if e.url.startswith(("http://", "https://"))])
    return feed


def ordenar(entradas: list[Entrada]) -> list[Entrada]:
    """De la más nueva a la más vieja; las que no tienen fecha, al final y en su orden."""
    minimo = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    return sorted(entradas, key=lambda e: (e.fecha is not None, e.fecha or minimo), reverse=True)


def descubrir(html: str, base_url: str) -> list[str]:
    """Los feeds que anuncia una página con <link rel="alternate" type="application/rss+xml">."""
    if not html or tipo(html):
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []
    urls = []
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        if "alternate" in rel and (link.get("type") or "").lower() in TIPOS_FEED:
            url = urljoin(base_url, link["href"].strip())
            # Los feeds de comentarios no traen notas.
            if url not in urls and not re.search(r"comments?/feed|/comments", url):
                urls.append(url)
    return urls


def sitemaps_de_notas(sitemaps: list[str], limite: int = 3) -> list[str]:
    """De un índice, los sitemaps que más probablemente listan notas (news, post, noticia), primero."""
    def prioridad(url: str) -> int:
        u = url.lower()
        if "news" in u or "noticia" in u:
            return 0
        if "post" in u or "article" in u or "blog" in u:
            return 1
        if any(x in u for x in ("page", "categor", "tag", "author", "product", "image", "video")):
            return 3
        return 2
    return sorted(sitemaps, key=prioridad)[:limite]
