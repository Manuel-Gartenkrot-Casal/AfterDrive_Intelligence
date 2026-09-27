"""Tests del módulo Corrida: una sola corrida a la vez, por cualquier camino."""


import pytest

import corridas


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


def test_stream_emite_la_salida_y_libera(script_rapido):
    assert list(corridas.stream(script_rapido)) == ["hola\n", "chau\n"]
    assert corridas.en_curso() is None


def test_script_captura_la_salida(script_rapido):
    r = corridas.script(script_rapido)
    assert r["success"] and r["output"] == "hola\nchau\n"


def test_segunda_corrida_mientras_hay_otra_se_rechaza(script_lento, script_rapido):
    gen = corridas.stream(script_lento)
    assert next(gen) == "uno\n"
    assert corridas.en_curso() == script_lento

    ocupado = list(corridas.stream(script_rapido))
    assert len(ocupado) == 1 and ocupado[0].startswith("[OCUPADO]")
    assert not corridas.script(script_rapido)["success"]
    assert not corridas.generacion({"categorias": ["x"]})["success"]
    assert not corridas.scraping()["success"]

    gen.close()  # el cliente cortó la conexión
    assert corridas.en_curso() is None


def test_cortar_el_stream_mata_el_proceso(script_lento, monkeypatch):
    procesos = []
    popen = corridas.subprocess.Popen

    def espiar(*a, **k):
        procesos.append(popen(*a, **k))
        return procesos[-1]

    monkeypatch.setattr(corridas.subprocess, "Popen", espiar)
    gen = corridas.stream(script_lento)
    next(gen)
    gen.close()
    assert procesos[0].wait(timeout=5) is not None


def test_generacion_sin_params_usa_la_config_guardada(monkeypatch):
    import config_store
    import generar_nota_fase2

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
        "persona": "ejecutivo", "tema": None, "regiones": ["brasil"],
    }


def test_generacion_sin_categorias_no_genera(monkeypatch):
    import config_store

    monkeypatch.setattr(config_store, "get_fase2_config", lambda: {"categorias": []})
    monkeypatch.setattr(config_store, "get_generacion_config", lambda: {})
    r = corridas.generacion()
    assert not r["success"] and "categorías" in r["error"]


def test_generacion_que_explota_libera_el_lock(monkeypatch):
    import generar_nota_fase2

    def boom(**kw):
        raise ValueError("boom")

    monkeypatch.setattr(generar_nota_fase2, "generar_nota", boom)
    r = corridas.generacion({"categorias": ["x"]})
    assert not r["success"] and "boom" in r["error"]
    assert corridas.en_curso() is None
