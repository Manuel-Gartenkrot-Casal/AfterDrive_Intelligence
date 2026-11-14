"""Sin Chromium, los e2e se saltean en una PC pero fallan en el CI (no quedan en verde sin probar nada)."""

import pytest

from tests.e2e import conftest as e2e


@pytest.fixture(autouse=True)
def sin_variables(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("E2E_OBLIGATORIO", raising=False)


def test_en_una_pc_sin_chromium_se_saltean():
    assert not e2e.e2e_obligatorio()
    with pytest.raises(pytest.skip.Exception):
        e2e.sin_navegador("Sin Chromium.")


@pytest.mark.parametrize("variable, valor", [("CI", "true"), ("CI", "1"), ("E2E_OBLIGATORIO", "1"),
                                             ("E2E_OBLIGATORIO", " TRUE ")])
def test_en_el_ci_sin_chromium_fallan(monkeypatch, variable, valor):
    monkeypatch.setenv(variable, valor)
    assert e2e.e2e_obligatorio()
    with pytest.raises(pytest.fail.Exception, match="no se saltean"):
        e2e.sin_navegador("Sin Chromium.")


@pytest.mark.parametrize("valor", ["", "0", "false", "no"])
def test_valores_apagados_no_obligan(monkeypatch, valor):
    monkeypatch.setenv("CI", valor)
    assert not e2e.e2e_obligatorio()
