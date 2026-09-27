"""Tests del fetch del scraper: origen caído -> copia de Wayback."""

import pytest
import requests

import scraper

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
