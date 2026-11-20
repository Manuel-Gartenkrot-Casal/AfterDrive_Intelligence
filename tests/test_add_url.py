"""Tests del alta de una URL con clasificador (python -m afterdrive.ingesta.add_url)."""

import importlib
from types import SimpleNamespace

import mongomock
import pytest

URL = "https://sitio.com/noticias"


@pytest.fixture
def add_url(monkeypatch):
    """El módulo con scraper, clasificador y Mongo reemplazados por fakes."""
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017/afterdrive")
    modulo = importlib.import_module("afterdrive.ingesta.add_url")
    col = mongomock.MongoClient().db.trusted_urls
    estado = {"items": [{"fuente": "Sitio", "url": URL + "/nota-1"}],
              "res": {"aprobados": 1, "rechazados": 0}}
    monkeypatch.setattr(modulo, "col_trusted_urls", col)
    monkeypatch.setattr(modulo.config_store, "get_scraping_config", lambda: {"max_articulos": 5})
    monkeypatch.setattr(modulo, "start", lambda urls, **k: SimpleNamespace(items=estado["items"]))
    monkeypatch.setattr(modulo, "ingerir", lambda items: estado["res"])
    return modulo, col, estado


def test_url_con_articulos_aprobados_queda_confiable(add_url):
    modulo, col, _ = add_url
    modulo.add_custom_url(URL)
    doc = col.find_one({"url": URL})
    assert doc["estado"] == "activo" and doc["nombre_fuente"] == "Sitio"
    assert doc["fecha_agregado"] == doc["ultima_ejecucion"]


def test_volver_a_agregarla_no_pisa_la_fecha_de_alta(add_url):
    modulo, col, _ = add_url
    col.insert_one({"url": URL, "estado": "inactivo", "fecha_agregado": "2026-01-01T00:00:00+00:00"})
    modulo.add_custom_url(URL)
    doc = col.find_one({"url": URL})
    assert doc["estado"] == "activo"
    assert doc["fecha_agregado"] == "2026-01-01T00:00:00+00:00"
    assert doc["ultima_ejecucion"] > "2026-01-01"
    assert col.count_documents({}) == 1


@pytest.mark.parametrize("items, res, aviso", [
    ([], None, "No se encontraron articulos"),
    ([{"fuente": "Sitio"}], {"aprobados": 0, "rechazados": 3}, "Ningun articulo fue aprobado"),
    ([{"fuente": "Sitio"}], {"aprobados": 0, "rechazados": 0, "pendientes": 2}, "La IA no respondio"),
])
def test_sin_aprobados_no_se_agrega(add_url, capsys, items, res, aviso):
    modulo, col, estado = add_url
    estado["items"], estado["res"] = items, res
    modulo.add_custom_url(URL)
    assert col.count_documents({}) == 0
    assert aviso in capsys.readouterr().out
