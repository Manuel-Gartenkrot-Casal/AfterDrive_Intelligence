"""Tests del módulo Corrida: una sola corrida a la vez, por cualquier camino."""


import pytest

from afterdrive import corridas


@pytest.fixture
def script_lento(tmp_path):
    p = tmp_path / "lento.py"
    p.write_text("import sys, time\nprint('uno', flush=True)\ntime.sleep(30)\nprint('dos', flush=True)\n")
    return str(p)


@pytest.fixture
def script_rapido(tmp_path):
    p = tmp_path / "rapido.py"
    p.write_text("print('hola')\nprint('chau')\n")
    return str(p)


def test_subproceso_emite_la_salida(script_rapido):
    assert list(corridas._subproceso(script_rapido)) == ["hola\n", "chau\n"]


def test_con_otra_corrida_en_curso_se_rechaza():
    with corridas._reservar("otra"):
        assert corridas.en_curso() == "otra"
        assert not corridas.generacion({"categorias": ["x"]})["success"]
        assert not corridas.scraping()["success"]
    assert corridas.en_curso() is None


def test_cortar_la_lectura_mata_el_proceso(script_lento, monkeypatch):
    procesos = []
    popen = corridas.subprocess.Popen

    def espiar(*a, **k):
        procesos.append(popen(*a, **k))
        return procesos[-1]

    monkeypatch.setattr(corridas.subprocess, "Popen", espiar)
    gen = corridas._subproceso(script_lento)
    assert next(gen) == "uno\n"
    gen.close()
    assert procesos[0].wait(timeout=5) is not None


def test_generacion_sin_params_usa_la_config_guardada(monkeypatch):
    from afterdrive import config_store
    from afterdrive.generacion import generar_nota_fase2
    monkeypatch.setattr(config_store, "get_fase2_config", lambda: {
        "categorias": ["autopartes"], "regiones": ["brasil"], "clientes": ["acme"],
        "puntapie_activo": True, "puntapie_url": "",
    })
    monkeypatch.setattr(config_store, "get_generacion_config", lambda: {
        "persona": "ejecutivo", "tema": "", "puntapie_url": "https://alephee.com",
    })
    recibido = {}
    monkeypatch.setattr(generar_nota_fase2, "generar_nota", lambda **kw: recibido.update(kw) or {"success": True})

    assert corridas.generacion()["success"]
    assert recibido == {
        "categorias": ["autopartes"], "clientes_ids": ["acme"], "puntapie_url": "https://alephee.com",
        "persona": "ejecutivo", "tema": None, "regiones": ["brasil"], "largo": "medio",
    }


def test_generacion_sin_categorias_no_genera(monkeypatch):
    from afterdrive import config_store
    monkeypatch.setattr(config_store, "get_fase2_config", lambda: {"categorias": []})
    monkeypatch.setattr(config_store, "get_generacion_config", lambda: {})
    r = corridas.generacion()
    assert not r["success"] and "categorías" in r["error"]


def test_generacion_que_explota_libera_el_lock(monkeypatch):
    from afterdrive.generacion import generar_nota_fase2
    def boom(**kw):
        raise ValueError("boom")

    monkeypatch.setattr(generar_nota_fase2, "generar_nota", boom)
    r = corridas.generacion({"categorias": ["x"]})
    assert not r["success"] and "boom" in r["error"]
    assert corridas.en_curso() is None


def test_el_scraping_dice_cuanto_gasto_de_la_api_paga(monkeypatch, capsys):
    from afterdrive.ia import consumo

    gastos = []

    def scrapear(max_articulos):
        gastos.append(consumo.registrar("clasificacion", "m", 1_000_000, 0, proveedor="paga"))
        gastos.append(consumo.registrar("embeddings", "m", 1000, 0, proveedor="paga"))
        consumo.registrar("clasificacion", "m", 1_000_000, 0, proveedor="local")   # gratis: no suma
        return {"success": True, "aprobados": 1}
    monkeypatch.setattr(corridas, "_scrapear", scrapear)
    assert corridas._scrapear_fuentes(None) == {"success": True, "aprobados": 1}
    assert f"[COSTO] Esta corrida: USD {sum(gastos):.4f} en 2 llamadas" in capsys.readouterr().out
    assert sum(gastos) > 0


def test_el_scraping_sin_api_paga_dice_que_no_gasto(monkeypatch, capsys):
    monkeypatch.setattr(corridas, "_scrapear", lambda m: {"success": True})
    corridas._scrapear_fuentes(None)
    assert "[COSTO] Esta corrida: USD 0 (no usó la API paga)" in capsys.readouterr().out
