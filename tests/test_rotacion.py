"""Rotación automática de categorías (generacion/rotacion.py) y cómo la usan las notas automáticas."""

import random

import mongomock

from afterdrive import config_store, corridas
from afterdrive.generacion import rotacion


def test_con_una_sola_categoria_no_hay_nada_que_rotar():
    assert rotacion.elegir(["autopartes"], [["autopartes"]]) == ["autopartes"]


def test_cuantas_por_nota_segun_las_marcadas():
    assert rotacion.cantidad_por_nota(2) == 1 and rotacion.cantidad_por_nota(3) == 1
    assert rotacion.cantidad_por_nota(4) == 2 and rotacion.cantidad_por_nota(9) == 2


def test_prefiere_las_que_menos_salieron():
    marcadas = ["autopartes", "neumaticos", "logistica"]
    recientes = [["autopartes"], ["neumaticos"], ["autopartes"], ["neumaticos"]]
    veces = {c: 0 for c in marcadas}
    azar = random.Random(1)
    for _ in range(300):
        veces[rotacion.elegir(marcadas, recientes, azar=azar)[0]] += 1
    assert veces["logistica"] > veces["autopartes"] and veces["logistica"] > veces["neumaticos"]
    assert veces["logistica"] > 200


def test_nunca_repite_la_combinacion_de_la_nota_anterior():
    marcadas = ["a", "b", "c", "d"]
    for semilla in range(50):
        elegidas = rotacion.elegir(marcadas, [["a", "b"]], azar=random.Random(semilla))
        assert len(elegidas) == 2 and set(elegidas) != {"a", "b"}


def test_respeta_el_orden_de_las_marcadas_y_no_repite():
    elegidas = rotacion.elegir(["d", "c", "b", "a"], [], cantidad=3, azar=random.Random(3))
    assert len(set(elegidas)) == 3
    assert elegidas == sorted(elegidas, key=["d", "c", "b", "a"].index)


def test_categorias_recientes_de_la_mas_nueva_a_la_mas_vieja():
    base = mongomock.MongoClient().db
    base.notas_fase2.insert_many([{"categorias": ["viejo"]}, {"categorias": ["nuevo"]}, {"titulo": "sin categorías"}])
    assert rotacion.categorias_recientes(base) == [["nuevo"], ["viejo"]]


def test_si_mongo_falla_rota_igual_sin_historial():
    class Rota:
        def __getitem__(self, k):
            raise RuntimeError("sin mongo")
    assert rotacion.categorias_recientes(Rota()) == []


def test_la_nota_automatica_rota_si_esta_prendida(monkeypatch):
    from afterdrive.generacion import generar_nota_fase2
    monkeypatch.setattr(config_store, "get_fase2_config", lambda: {
        "categorias": ["autopartes", "neumaticos", "logistica"], "rotar_categorias": True})
    monkeypatch.setattr(config_store, "get_generacion_config", lambda: {"persona": "comercial"})
    monkeypatch.setattr(rotacion, "categorias_recientes", lambda base=None: [["autopartes"], ["neumaticos"]])
    monkeypatch.setattr(rotacion.random, "choices", lambda pob, weights, k: [pob[weights.index(max(weights))]])
    recibido = {}
    monkeypatch.setattr(generar_nota_fase2, "generar_nota", lambda **kw: recibido.update(kw) or {"success": True})
    assert corridas.generacion()["success"]
    assert recibido["categorias"] == ["logistica"]


def test_sin_rotacion_la_nota_automatica_usa_todas(monkeypatch):
    monkeypatch.setattr(config_store, "get_fase2_config", lambda: {"categorias": ["autopartes", "neumaticos"]})
    monkeypatch.setattr(config_store, "get_generacion_config", lambda: {})
    monkeypatch.setattr(rotacion, "rotar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe rotar")))
    assert corridas.parametros_guardados()["categorias"] == ["autopartes", "neumaticos"]


def test_el_generador_rota_con_la_opcion_rotar(monkeypatch):
    from afterdrive.generacion import generar_nota_fase2 as g
    monkeypatch.setattr(g, "_validar_entorno", lambda: None)
    monkeypatch.setattr(rotacion, "rotar", lambda cats, base=None: cats[:1])
    recibido = {}
    monkeypatch.setattr(g, "generar_nota", lambda **kw: recibido.update(kw) or {"success": True, "contenido": "x"})
    assert g.main(["--categorias", "autopartes", "neumaticos", "--rotar"]) == 0
    assert recibido["categorias"] == ["autopartes"]
