"""Tests del fetch del scraper: origen caído -> copia de Wayback."""

import socket

import pytest
import requests

from afterdrive.ingesta import scraper
HTML = "<html><body>" + ("<p>contenido real del sitio</p>" * 40) + "</body></html>"


class Resp:
    def __init__(self, url, status=200, text=HTML):
        self.url = url
        self.status_code = status
        self.text = text
        self.ok = status < 400

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def red(monkeypatch):
    """Origen que cuelga (como aftermarketinternational.com) y Wayback que responde."""
    llamadas = []

    def fake_get(url, timeout=None, headers=None, **kw):
        llamadas.append(url)
        if url.startswith("https://web.archive.org/"):
            original = url.split("id_/", 1)[1]
            return Resp(f"https://web.archive.org/web/20260917200101id_/{original}")
        raise requests.exceptions.ReadTimeout("origen colgado")

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    monkeypatch.setattr(scraper, "_PERFIL", scraper.PERFIL_BAJO)
    monkeypatch.setattr(scraper, "_ORIGEN_CAIDO", set())
    # Estos tests no prueban la validación de URLs: sin esto harían DNS real.
    monkeypatch.setattr(scraper, "_direcciones", lambda url: ["93.184.216.34"])
    return llamadas


def test_home_del_sitio_se_obtiene_de_wayback(red):
    # Antes fallaba: el slug de "/" es vacío y la copia se descartaba.
    assert scraper._fetch("https://www.aftermarketinternational.com/") == HTML
    assert any("id_/https://www.aftermarketinternational.com/" in u for u in red)


def test_con_origen_caido_los_articulos_van_directo_a_wayback(red):
    scraper._fetch("https://www.aftermarketinternational.com/")
    red.clear()
    scraper._fetch("https://www.aftermarketinternational.com/novedades/9757-nota.html")
    assert all(u.startswith("https://web.archive.org/") for u in red)


def test_wayback_que_redirige_a_otra_pagina_se_descarta(monkeypatch):
    def fake_get(url, timeout=None, headers=None, **kw):
        if url.startswith("https://web.archive.org/"):
            return Resp("https://web.archive.org/web/20250101000000id_/https://otro.com/")
        raise requests.exceptions.ReadTimeout("x")

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    monkeypatch.setattr(scraper, "_PERFIL", scraper.PERFIL_BAJO)
    monkeypatch.setattr(scraper, "_ORIGEN_CAIDO", set())
    assert scraper._fetch("https://www.aftermarketinternational.com/nota.html") is None


def test_articulo_no_archivado_devuelve_none(monkeypatch):
    def fake_get(url, timeout=None, headers=None, **kw):
        if url.startswith("https://web.archive.org/"):
            return Resp(url, status=404, text="")
        raise requests.exceptions.ReadTimeout("x")

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    monkeypatch.setattr(scraper, "_PERFIL", scraper.PERFIL_BAJO)
    monkeypatch.setattr(scraper, "_ORIGEN_CAIDO", set())
    assert scraper._fetch("https://www.aftermarketinternational.com/nota.html") is None


# ── url_publica: el scraper no visita la red interna ──────────────────────────

_DNS = {
    "sitio.com": ["93.184.216.34"],
    "localhost": ["127.0.0.1"],
    "127.0.0.1": ["127.0.0.1"],
    "::1": ["::1"],
    "10.0.0.1": ["10.0.0.1"],
    "169.254.169.254": ["169.254.169.254"],
    "interno.corp": ["192.168.1.20"],
    "mixto.com": ["93.184.216.34", "10.0.0.5"],
}


@pytest.fixture
def dns(monkeypatch):
    def fake(host, *_a, **_k):
        if host not in _DNS:
            raise socket.gaierror("no resuelve")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, 0, 0, "", (ip, 0)) for ip in _DNS[host]]

    monkeypatch.setattr(scraper.socket, "getaddrinfo", fake)


@pytest.mark.parametrize("url,ok", [
    ("https://sitio.com/noticias", True),
    ("http://sitio.com", True),
    ("https://usuario:clave@sitio.com:8443/x?y=1", True),
    ("HTTP://SITIO.COM/", True),
    # requests corta el host en la barra invertida y visitaría 127.0.0.1.
    ("http://127.0.0.1:5000\\@sitio.com/", False),
    ("http://sitio.com/a b", False),
    ("http://sitio.com/\n", False),
    ("http://sitio.com/\x00", False),
    ("file:///etc/passwd", False),
    ("ftp://sitio.com", False),
    ("javascript:alert(1)", False),
    ("sitio.com", False),
    ("", False),
    (None, False),
    ("http://", False),
    ("http://localhost:5000/", False),
    ("http://127.0.0.1/", False),
    ("http://[::1]/", False),
    ("http://10.0.0.1/", False),
    ("http://169.254.169.254/latest/meta-data/", False),
    ("http://interno.corp/", False),
    ("http://no-resuelve.invalid/", False),
    ("http://mixto.com/", False),
])
def test_url_publica(dns, url, ok):
    assert scraper.url_publica(url) is ok


@pytest.mark.parametrize("url", [
    "http://10.0.0.1/", "http://interno.corp/", "http://mixto.com/", "file:///etc/passwd",
    "http://127.0.0.1:5000\\@sitio.com/",
])
def test_fetch_no_descarga_urls_internas(dns, monkeypatch, url):
    for nombre in ("_http_get", "_browser_get", "_wayback_get"):
        monkeypatch.setattr(scraper, nombre, lambda *a, **k: pytest.fail("no debe descargar"))
    assert scraper._fetch(url) is None


def test_dominio_que_no_resuelve_va_a_wayback(dns, monkeypatch):
    # Un dominio caído no es una URL interna: Wayback no lo visita, así que la
    # copia archivada se sigue pudiendo usar.
    monkeypatch.setattr(scraper, "_ORIGEN_CAIDO", set())
    for nombre in ("_http_get", "_browser_get"):
        monkeypatch.setattr(scraper, nombre, lambda *a, **k: pytest.fail("el origen no existe"))
    monkeypatch.setattr(scraper, "_wayback_get", lambda url: "COPIA:" + url)
    assert scraper._fetch("http://no-resuelve.invalid/nota") == "COPIA:http://no-resuelve.invalid/nota"
    assert "no-resuelve.invalid" in scraper._ORIGEN_CAIDO


# ── Entre corridas ────────────────────────────────────────────────────────────


@pytest.fixture
def listado(monkeypatch):
    """Un listado con tres artículos; cada descarga de artículo queda anotada."""
    links = ["https://sitio.com/2026/10/01/a", "https://sitio.com/2026/10/02/b", "https://sitio.com/2026/10/03/c"]
    bajados = []
    monkeypatch.setattr(scraper, "_fetch", lambda url: HTML)
    monkeypatch.setattr(scraper, "_encontrar_links", lambda html, base: list(links))

    def extraer(link):
        bajados.append(link)
        return {"titulo": link[-1], "cuerpo": "x" * 200, "url": link}

    monkeypatch.setattr(scraper, "_fetch_and_extract", extraer)
    return links, bajados


def test_un_origen_caido_no_se_arrastra_a_la_corrida_siguiente(listado):
    scraper._ORIGEN_CAIDO.add("sitio.com")
    scraper.start(["https://sitio.com/noticias"], max_articulos=3)
    assert "sitio.com" not in scraper._ORIGEN_CAIDO


def test_los_articulos_ya_procesados_no_se_vuelven_a_bajar(listado):
    links, bajados = listado
    r = scraper.start(["https://sitio.com/noticias"], max_articulos=3, omitir=lambda urls: {links[0], links[2]})
    assert bajados == [links[1]] and [i["url"] for i in r.items] == [links[1]]


def test_si_todo_es_conocido_no_baja_nada(listado):
    links, bajados = listado
    assert scraper.start(["https://sitio.com/noticias"], max_articulos=3, omitir=lambda urls: set(urls)).items == []
    assert bajados == []


def test_ya_procesadas_mira_guardadas_y_descartadas(monkeypatch):
    import mongomock

    from afterdrive import corridas, db
    base = mongomock.MongoClient().db
    base.articulos.insert_one({"url": "https://s.com/a"})
    base.articulos_descartados.insert_one({"url": "https://s.com/b"})
    monkeypatch.setattr(db, "col_articulos", base.articulos)
    monkeypatch.setattr(db, "col_descartados", base.articulos_descartados)
    assert corridas.ya_procesadas(["https://s.com/a", "https://s.com/b", "https://s.com/c"]) == {
        "https://s.com/a", "https://s.com/b"}
