"""Ingesta por RSS, Atom y sitemaps (feeds.py) y las fuentes recomendadas para notas de Alephee."""

import datetime

import mongomock

from afterdrive.ingesta import feeds, fuentes_recomendadas, scraper

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Sitio</title>
  <item><title>Vieja</title><link>https://sitio.com/2026/10/01/vieja</link><pubDate>Wed, 01 Oct 2026 10:00:00 GMT</pubDate></item>
  <item><title>Nueva</title><link>https://sitio.com/2026/11/04/nueva</link><pubDate>Wed, 04 Nov 2026 10:00:00 GMT</pubDate></item>
  <item><title>Sin fecha</title><link>https://sitio.com/sin-fecha</link></item>
</channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
  <entry><title>Una</title><link rel="alternate" href="https://blog.com/una"/><link rel="edit" href="https://blog.com/x"/>
    <updated>2026-11-02T08:00:00Z</updated></entry>
</feed>"""

SITEMAP_NOTICIAS = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
    xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url><loc>https://diario.com/nota-1</loc>
    <news:news><news:publication_date>2026-11-05</news:publication_date><news:title>Nota 1</news:title></news:news></url>
  <url><loc>https://diario.com/</loc><lastmod>2026-11-06</lastmod></url>
</urlset>"""

INDICE = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://diario.com/page-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://diario.com/post-sitemap.xml</loc></sitemap>
</sitemapindex>"""


def test_rss_de_la_mas_nueva_a_la_mas_vieja():
    f = feeds.leer(RSS)
    assert f.tipo == "rss" and [e.titulo for e in f.entradas] == ["Nueva", "Vieja", "Sin fecha"]
    assert f.entradas[0].fecha == datetime.datetime(2026, 11, 4, 10, tzinfo=datetime.UTC)


def test_atom_toma_el_link_de_la_nota_y_no_el_de_edicion():
    f = feeds.leer(ATOM)
    assert f.tipo == "atom" and [(e.url, e.titulo) for e in f.entradas] == [("https://blog.com/una", "Una")]


def test_sitemap_de_noticias_e_indice():
    f = feeds.leer(SITEMAP_NOTICIAS)
    assert f.tipo == "sitemap" and f.entradas[0].url == "https://diario.com/" and f.entradas[1].titulo == "Nota 1"
    i = feeds.leer(INDICE)
    assert i.tipo == "indice" and feeds.sitemaps_de_notas(i.sitemaps) == [
        "https://diario.com/post-sitemap.xml", "https://diario.com/page-sitemap.xml"]


def test_lo_que_no_es_feed():
    for texto in ("", "<html><body>hola</body></html>", "no es xml", None):
        assert feeds.tipo(texto) is None and feeds.leer(texto) is None


def test_el_xml_no_resuelve_entidades_externas():
    malicioso = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                 '<rss><channel><item><title>&x;</title><link>https://a.com/n</link></item></channel></rss>')
    f = feeds.leer(malicioso)
    assert f is not None and "root:" not in (f.entradas[0].titulo if f.entradas else "")


def test_descubrir_el_feed_que_anuncia_la_portada():
    html = """<html><head>
      <link rel="alternate" type="application/rss+xml" href="/feed/">
      <link rel="alternate" type="application/rss+xml" href="/comments/feed/">
      <link rel="alternate" type="application/atom+xml" href="https://otro.com/atom.xml">
      <link rel="stylesheet" href="/x.css"></head></html>"""
    assert feeds.descubrir(html, "https://sitio.com/noticias") == ["https://sitio.com/feed/", "https://otro.com/atom.xml"]
    assert feeds.parece_feed("https://sitio.com/feed/") and feeds.parece_feed("https://s.com/sitemap_index.xml")
    assert not feeds.parece_feed("https://sitio.com/noticias")


# ── Scraper ──────────────────────────────────────────────────────────────────


def _scraper_con(monkeypatch, paginas):
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    monkeypatch.setattr(scraper, "_http_get", lambda url, timeout=10: paginas.get(url))
    monkeypatch.setattr(scraper, "_fetch", lambda url: paginas.get(url))
    bajadas = []

    def extraer(link):
        bajadas.append(link)
        return {"titulo": link, "cuerpo": "x" * 200, "url": link}
    monkeypatch.setattr(scraper, "_fetch_and_extract", extraer)
    return bajadas


def test_una_portada_con_feed_usa_las_notas_del_feed(monkeypatch):
    portada = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed"></head>' \
              '<body><a href="https://sitio.com/nota-del-html-sin-fecha">Un título de nota bastante largo</a></body></html>'
    bajadas = _scraper_con(monkeypatch, {"https://sitio.com/": portada, "https://sitio.com/feed": RSS})
    items = []
    scraper._procesar_listado("https://sitio.com/", 2, items)
    assert set(bajadas) <= {"https://sitio.com/2026/11/04/nueva", "https://sitio.com/2026/10/01/vieja",
                            "https://sitio.com/sin-fecha"}
    assert len(items) == 2


def test_una_fuente_que_es_un_indice_de_sitemaps_lee_los_de_notas(monkeypatch):
    bajadas = _scraper_con(monkeypatch, {
        "https://diario.com/sitemap_index.xml": INDICE, "https://diario.com/post-sitemap.xml": SITEMAP_NOTICIAS,
        "https://diario.com/page-sitemap.xml": "<urlset><url><loc>https://diario.com/contacto</loc></url></urlset>",
    })
    items = []
    scraper._procesar_listado("https://diario.com/sitemap_index.xml", 5, items)
    assert "https://diario.com/nota-1" in bajadas and "https://diario.com/" not in bajadas   # la portada no es nota


def test_sin_feed_se_buscan_los_links_en_el_html(monkeypatch):
    portada = '<html><body><a href="https://sitio.com/2026/11/04/una-nota">Un título de nota bastante largo</a></body></html>'
    bajadas = _scraper_con(monkeypatch, {"https://sitio.com/": portada})
    scraper._procesar_listado("https://sitio.com/", 3, [])
    assert bajadas == ["https://sitio.com/2026/11/04/una-nota"]


def test_un_feed_con_direccion_interna_no_se_baja(monkeypatch):
    monkeypatch.setattr(scraper, "url_publica", lambda url: "interno" not in url)
    monkeypatch.setattr(scraper, "_http_get", lambda url, timeout=10: RSS)
    assert scraper._xml_get("http://interno.local/feed") is None and scraper._xml_get("https://s.com/feed") == RSS


# ── Fuentes recomendadas ─────────────────────────────────────────────────────


def test_las_recomendadas_se_suman_una_vez_y_sin_las_que_ya_son_fuentes():
    base = mongomock.MongoClient().db
    base.trusted_urls.insert_one({"url": "https://www.aftermarketnews.com/"})
    n = fuentes_recomendadas.sembrar(base)
    assert n == len(fuentes_recomendadas.RECOMENDADAS) - 1
    doc = base.suggested_urls.find_one({"dominio": "alephee.com"})
    assert doc["origen"] == "alephee" and "material propio" in doc["snippet"]
    assert fuentes_recomendadas.sembrar(base) == 0
