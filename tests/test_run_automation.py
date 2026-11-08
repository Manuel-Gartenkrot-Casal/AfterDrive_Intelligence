"""Tests del scraping por línea de comandos (python -m afterdrive.ingesta.run_automation [N])."""

import importlib

import pytest


@pytest.fixture
def run_automation(monkeypatch):
    """El módulo con corridas.scraping reemplazado: anota con qué máximo se llamó."""
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017/afterdrive")
    modulo = importlib.import_module("afterdrive.ingesta.run_automation")
    llamadas = []
    monkeypatch.setattr(modulo.corridas, "scraping", lambda m=None: llamadas.append(m) or {"success": True})
    return modulo, llamadas


@pytest.mark.parametrize("argv, esperado", [(["x"], None), (["x", "10"], 10), (["x", " 3 "], 3), (["x", "1"], 1)])
def test_maximo_valido_o_el_de_la_config(run_automation, argv, esperado):
    modulo, llamadas = run_automation
    assert modulo.main(argv) == 0
    assert llamadas == [esperado]


@pytest.mark.parametrize("valor", ["0", "-5", "diez", "", "2.5"])
def test_maximo_invalido_no_scrapea(run_automation, capsys, valor):
    modulo, llamadas = run_automation
    assert modulo.main(["x", valor]) == 2
    assert llamadas == []
    assert "No se scrapeó nada" in capsys.readouterr().out


def test_si_el_scraping_falla_sale_con_1(run_automation, monkeypatch):
    modulo, _ = run_automation
    monkeypatch.setattr(modulo.corridas, "scraping", lambda m=None: {"success": False})
    assert modulo.main(["x"]) == 1
