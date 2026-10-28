"""El juez de IA (calificación sugerida + si pasa) y la aprobación automática."""

import json

import mongomock
import pytest

from afterdrive import aprobacion_auto, calibracion, config_store, historial, traducciones
from afterdrive.generacion import juez
from afterdrive.ia import llm

NOTA = "# Frenos en alza\n\nTexto.\n\n## Qué hacer\n\nMás texto."

BUENA = {
    "contenido": NOTA, "estado": "borrador", "regiones": ["argentina"],
    "verificacion": {"sin_respaldo": []},
    "calidad": {"puntaje": 9, "fallas_criticas": []},
    "estilo": [], "parecida_a": None, "imagen": {"url": "https://x/i.jpg"},
    "calibracion_usada": {"umbral": None},
    "juicio": {"pasa": True, "confianza": 0.9, "calificacion": 4, "etiquetas": [], "comentario": "", "motivos": []},
}


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def _responde(monkeypatch, texto):
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "completar", lambda *a, **k: texto)


def test_juzgar_usa_el_modelo_de_evaluacion_y_limpia_la_respuesta(monkeypatch):
    tareas = []
    monkeypatch.setattr(llm, "disponible", lambda: True)

    def completar(system, user, **k):
        tareas.append(k["tarea"])
        return json.dumps({"pasa": True, "confianza": 3, "calificacion": 9,
                           "etiquetas": ["buen_angulo", "inventada"], "comentario": "ok", "motivos": []})
    monkeypatch.setattr(llm, "completar", completar)
    j = juez.juzgar(NOTA, "noticias", ["no uses muletillas"])
    assert tareas == ["evaluacion"]
    assert j["confianza"] == 1.0 and j["calificacion"] == 5 and j["etiquetas"] == ["buen_angulo"]


@pytest.mark.parametrize("texto", ["no es json", '{"confianza": 0.9}'])
def test_juicio_roto_queda_con_error(monkeypatch, texto):
    _responde(monkeypatch, texto)
    assert "error" in juez.juzgar(NOTA, "")


def test_sin_proveedor_no_juzga(monkeypatch):
    monkeypatch.setattr(llm, "disponible", lambda: False)
    assert "error" in juez.juzgar(NOTA, "")


@pytest.mark.parametrize("cambio, texto", [
    ({"verificacion": {"sin_respaldo": ["15%"]}}, "sin respaldo"),
    ({"calidad": {"puntaje": 9, "fallas_criticas": ["sin_alucinaciones"]}}, "fallas críticas"),
    ({"estilo": [{"codigo": "titulo", "detalle": "título largo", "grave": True}]}, "graves"),
    ({"parecida_a": {"id": "1"}}, "parece"),
    ({"imagen": None}, "imagen"),
    ({"calidad": {"puntaje": 6, "fallas_criticas": []}}, "puntaje"),
    ({"juicio": {**BUENA["juicio"], "pasa": False, "motivos": ["genérica"]}}, "genérica"),
    ({"juicio": {**BUENA["juicio"], "confianza": 0.5}}, "no está seguro"),
    ({"juicio": {"error": "se cayó"}}, "se cayó"),
    ({"juicio": None}, "no tiene juicio"),
])
def test_cada_motivo_la_frena(cambio, texto):
    d = juez.decidir({**BUENA, **cambio})
    assert not d["pasa"] and any(texto in m for m in d["motivos"])


def test_una_nota_buena_pasa_y_respeta_el_umbral_calibrado():
    assert juez.decidir(BUENA)["pasa"]
    assert not juez.decidir({**BUENA, "calibracion_usada": {"umbral": 10}})["pasa"]


def test_con_el_switch_apagado_no_hace_nada(base):
    oid = str(base.notas_fase2.insert_one(dict(BUENA)).inserted_id)
    assert aprobacion_auto.procesar("notas_fase2", oid, base=base) is None
    assert base.notas_fase2.find_one()["estado"] == "borrador"


def test_si_pasa_se_aprueba_y_sube_como_borrador(base, monkeypatch):
    monkeypatch.setattr(config_store, "get_aprobacion_auto_config", lambda: True)
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    enviados = []
    monkeypatch.setattr(historial, "enviar_a_hubspot",
                        lambda c, i, publicar, base=None: enviados.append(publicar) or {"hubspot": {"url": "https://b/x"}})
    monkeypatch.setattr(traducciones, "encolar", lambda c, i: {"id": "t", "idiomas": ["pt", "en"]})
    oid = str(base.notas_fase2.insert_one(dict(BUENA)).inserted_id)
    d = aprobacion_auto.procesar("notas_fase2", oid, base=base)
    doc = base.notas_fase2.find_one()
    assert d["pasa"] and enviados == [False]
    assert doc["estado"] == "aprobada" and doc["aprobada_por"] == "ia"
    assert doc["aprobacion_auto"]["hubspot"] == "https://b/x"


def test_si_no_pasa_queda_en_borrador_con_los_motivos(base, monkeypatch):
    monkeypatch.setattr(config_store, "get_aprobacion_auto_config", lambda: True)
    oid = str(base.notas_fase2.insert_one({**BUENA, "imagen": None}).inserted_id)
    d = aprobacion_auto.procesar("notas_fase2", oid, base=base)
    doc = base.notas_fase2.find_one()
    assert not d["pasa"] and doc["estado"] == "borrador" and "aprobada_por" not in doc
    assert doc["aprobacion_auto"]["motivos"]


def test_sin_hubspot_queda_aprobada_sin_subir(base, monkeypatch):
    monkeypatch.setattr(config_store, "get_aprobacion_auto_config", lambda: True)
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    oid = str(base.notas_fase2.insert_one(dict(BUENA)).inserted_id)
    d = aprobacion_auto.procesar("notas_fase2", oid, base=base)
    assert "no está configurado" in d["hubspot"] and base.notas_fase2.find_one()["estado"] == "aprobada"


def test_la_calificacion_guarda_lo_que_sugirio_la_ia_y_se_mide(base):
    oid = str(base.notas_fase2.insert_one(dict(BUENA)).inserted_id)
    cal = calibracion.calificar("notas_fase2", oid, 2, base=base)
    assert cal["sugerida_ia"] == 4
    jz = calibracion._juez(list(base.notas_fase2.find()))
    assert jz == {"pares": 1, "diferencia_media": 2.0, "acierto": 0.0, "aprobadas_ia": 0, "aprobadas_ia_mal": 0}


def test_switch_de_aprobacion_automatica(api, monkeypatch):
    flask_api, store = api
    monkeypatch.setattr(config_store, "get_aprobacion_auto_config",
                        lambda: store.get("aprobacion_auto", {"activo": False})["activo"])
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    assert c.get("/api/aprobacion-auto").get_json()["activo"] is False
    assert c.post("/api/aprobacion-auto", json={"activo": True}).get_json()["activo"] is True
    assert c.post("/api/aprobacion-auto", json={}).status_code == 400
