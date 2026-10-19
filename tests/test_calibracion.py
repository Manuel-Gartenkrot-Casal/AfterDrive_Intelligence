"""Tests de la calibración: calificaciones, etiquetas, ediciones y umbral del evaluador."""

import datetime

import mongomock
import pytest
from bson import ObjectId

from afterdrive import calibracion, historial
from afterdrive.ia import llm


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def _nota(base, puntaje=None, etiquetas=(), comentario="", auto=None, persona="comercial", proveedor="openrouter",
          contenido="# Una nota\n\nCuerpo de la nota.\n\n## Fuentes\n\n- [x](https://x)\n\n*Meta.*"):
    doc = {"contenido": contenido, "persona": persona, "proveedor": proveedor, "estado": "borrador"}
    if auto is not None:
        doc["calidad"] = {"puntaje": auto}
    _id = base.notas_fase2.insert_one(doc).inserted_id
    if puntaje is not None:
        calibracion.calificar("notas_fase2", str(_id), puntaje, list(etiquetas), comentario, base=base)
    return str(_id)


def test_calificar_guarda_y_valida(base):
    nid = _nota(base)
    cal = calibracion.calificar("notas_fase2", nid, 4, ["buen_angulo"], "  Muy  clara ", base=base)
    assert cal["puntaje"] == 4 and cal["etiquetas"] == ["buen_angulo"] and cal["comentario"] == "Muy clara"
    assert base.notas_fase2.find_one({"_id": ObjectId(nid)})["calificacion"]["puntaje"] == 4
    for malo in (0, 6, "5", True, None):
        with pytest.raises(calibracion.ErrorCalibracion):
            calibracion.calificar("notas_fase2", nid, malo, base=base)
    with pytest.raises(calibracion.ErrorCalibracion):
        calibracion.calificar("notas_fase2", nid, 3, ["inventada"], base=base)
    with pytest.raises(calibracion.ErrorCalibracion):
        calibracion.calificar("articulos", nid, 3, base=base)
    assert calibracion.calificar("notas_fase2", str(ObjectId()), 3, base=base) is None


def test_una_etiqueta_que_se_repite_activa_su_regla(base):
    _nota(base, 2, ["suena_ia"])
    cal = calibracion.contexto(base=base)
    assert not any("periodista" in r for r in cal.reglas)          # una vez: todavía no
    _nota(base, 3, ["suena_ia", "buen_angulo"])
    cal = calibracion.contexto(base=base)
    assert calibracion.ETIQUETAS["suena_ia"][2] in cal.reglas
    assert not any("ángulo" in r and "Buen" in r for r in cal.reglas)   # las positivas no activan reglas


def test_comentarios_bajos_son_correcciones_y_altos_aciertos(base):
    _nota(base, 1, comentario="El cierre repite la introducción")
    _nota(base, 5, comentario="El dato de márgenes estuvo perfecto")
    cal = calibracion.contexto(base=base)
    assert "El cierre repite la introducción" in cal.reglas
    assert cal.aciertos == ["El dato de márgenes estuvo perfecto"]


def test_los_rechazos_siguen_contando(base):
    nid = _nota(base)
    historial.cambiar_estado("notas_fase2", nid, "rechazada", base=base, motivo="Inventa cifras")
    assert "Inventa cifras" in calibracion.contexto(base=base).reglas


def test_notas_bien_calificadas_son_referencias_primero_la_misma_persona(base):
    _nota(base, 5, persona="ejecutivo", contenido="# Ejecutiva\n\nCuerpo E.\n\n## Fuentes\n\n- [x](https://x)")
    _nota(base, 4, persona="comercial", contenido="# Comercial\n\nCuerpo C.")
    _nota(base, 2, persona="comercial", contenido="# Floja\n\nCuerpo F.")
    propios = calibracion.contexto("comercial", base=base).ejemplos_propios
    assert [p["titulo"] for p in propios] == ["Comercial", "Ejecutiva"]
    assert propios[1]["cuerpo"] == "Cuerpo E."        # sin título ni fuentes


def test_umbral_del_evaluador():
    # Por debajo de 6 lineamientos el equipo las califica mal: el umbral es 6.
    pares = [(4, 1), (5, 2), (5, 1), (6, 3), (7, 4), (8, 5), (9, 4), (6, 4)]
    assert calibracion.umbral_evaluador(pares) == (6, 1.0)
    assert calibracion.umbral_evaluador(pares[:5]) == (None, None)             # pocas
    assert calibracion.umbral_evaluador([(5, 4)] * 8) == (None, None)           # todas buenas: nada que separar


def test_el_umbral_se_calcula_con_las_calificaciones(base):
    for auto, humano in [(4, 1), (5, 2), (5, 1), (6, 3), (7, 4), (8, 5), (9, 4), (6, 4)]:
        _nota(base, humano, auto=auto)
    assert calibracion.contexto(base=base).umbral == 6


def test_las_ediciones_dejan_lecciones_que_se_guardan(base, monkeypatch):
    nid = _nota(base, contenido="# T\n\nEn el dinámico mundo del aftermarket todo cambia muy rápido. Frasle amplía su planta.")
    historial.editar("notas_fase2", nid, "# T\n\n" + "Frasle amplía su planta en Caxias do Sul y acorta plazos. " * 5,
                     base=base)
    doc = base.notas_fase2.find_one({"_id": ObjectId(nid)})
    assert doc["contenido_original"].startswith("# T\n\nEn el dinámico mundo")
    llamadas = []
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: llamadas.append(user) or
                        '{"reglas": ["Empezá por el hecho, sin introducciones genéricas."]}')
    assert calibracion.lecciones_de_ediciones(base=base) == ["Empezá por el hecho, sin introducciones genéricas."]
    assert "En el dinámico mundo" in llamadas[0]
    # Ya calculada: la segunda vez no se llama al modelo.
    monkeypatch.setattr(llm, "completar", lambda *a, **k: pytest.fail("ya estaba calculada"))
    assert calibracion.lecciones_de_ediciones(base=base) == ["Empezá por el hecho, sin introducciones genéricas."]
    # El panel nunca llama al modelo.
    assert calibracion.resumen(base=base)["reglas"] == ["Empezá por el hecho, sin introducciones genéricas."]


def test_editar_dos_veces_conserva_la_version_generada(base):
    nid = _nota(base, contenido="# T\n\nOriginal del modelo. " + "x" * 300)
    historial.editar("notas_fase2", nid, "# T\n\nPrimera edición. " + "y" * 300, base=base)
    historial.editar("notas_fase2", nid, "# T\n\nSegunda edición. " + "z" * 300, base=base)
    assert base.notas_fase2.find_one({"_id": ObjectId(nid)})["contenido_original"].startswith("# T\n\nOriginal")


def test_diferencias_por_oraciones():
    sacado, agregado = calibracion.diferencias("Uno es igual. Dos se va del todo. Tres es igual.",
                                               "Uno es igual. Dos cambia por completo. Tres es igual.")
    assert sacado == "Dos se va del todo." and agregado == "Dos cambia por completo."


def test_calificaciones_viejas_no_cuentan(base):
    nid = _nota(base, 1, ["suena_ia"])
    _nota(base, 1, ["suena_ia"])
    viejo = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)).isoformat()
    base.notas_fase2.update_one({"_id": ObjectId(nid)}, {"$set": {"calificacion.calificado_en": viejo}})
    assert calibracion.ETIQUETAS["suena_ia"][2] not in calibracion.contexto(base=base).reglas


def test_resumen_para_el_panel(base):
    _nota(base, 5, persona="comercial", proveedor="paga")
    _nota(base, 3, ["muy_larga"], persona="ejecutivo")
    _nota(base, 2, ["muy_larga"], persona="comercial")
    _nota(base)
    r = calibracion.resumen(base=base)
    assert r["calificadas"] == 3 and r["sin_calificar"] == 1 and r["promedio"] == 3.33
    assert r["distribucion"] == {"1": 0, "2": 1, "3": 1, "4": 0, "5": 1}
    assert {"nombre": "comercial", "notas": 2, "promedio": 3.5} in r["por_persona"]
    assert r["etiquetas"] == [{"clave": "muy_larga", "nombre": "Muy larga o repetitiva", "veces": 2, "activa": True}]
    assert r["evaluador"]["umbral"] is None and r["evaluador"]["minimo"] == calibracion.MIN_PARES


def test_sin_mongo_la_calibracion_queda_vacia(monkeypatch):
    class Rota:
        def __getitem__(self, k):
            raise RuntimeError("Mongo caído")
    cal = calibracion.contexto(base=Rota())
    assert cal.reglas == [] and cal.umbral is None


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(api, base, monkeypatch):
    from afterdrive import db as db_module
    monkeypatch.setattr(db_module, "db", base)
    flask_api, _ = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c


def test_endpoints_de_calificacion_y_calibracion(client, base):
    nid = _nota(base)
    r = client.post("/api/historial/calificacion", json={"coleccion": "notas_fase2", "id": nid, "puntaje": 2,
                                                          "etiquetas": ["generica"], "comentario": "Sin ángulo"})
    assert r.status_code == 200 and r.json["calificacion"]["puntaje"] == 2
    assert client.post("/api/historial/calificacion", json={"coleccion": "notas_fase2", "id": nid,
                                                             "puntaje": 9}).status_code == 400
    assert client.post("/api/historial/calificacion", json={"coleccion": "notas_fase2", "id": str(ObjectId()),
                                                             "puntaje": 3}).status_code == 404
    d = client.get("/api/calibracion").json
    assert d["success"] and d["calificadas"] == 1 and "Sin ángulo" in d["reglas"]
    item = client.get(f"/api/historial/generados_aprobados/notas_fase2/{nid}").json["item"]
    assert item["calificacion"]["etiquetas"] == ["generica"]
