"""La crítica de la redacción hecha por la IA (gramática, tono, estructura) que se ve al calificar."""

import json

import mongomock
import pytest
from bson import ObjectId

from afterdrive import calibracion
from afterdrive.generacion import critica
from afterdrive.ia import llm

NOTA = "# Frenos en alza\n\nLos repuesteros vendieron mas pastillas. Descubre cómo sumar stock.\n"

RESPUESTA = {
    "puntaje": 14,
    "resumen": "Buen gancho,   pero mezcla voseo y tuteo.",
    "aspectos": {"gramatica": 8, "redaccion": "6", "tono": 0, "estructura": "x"},
    "errores": [
        {"tipo": "ortografia", "fragmento": "vendieron mas pastillas", "problema": "Falta la tilde en 'más'.",
         "sugerencia": "vendieron más pastillas"},
        {"tipo": "Tono", "fragmento": "Descubre cómo", "problema": "Tutea en una nota con voseo.",
         "sugerencia": "Descubrí cómo"},
        {"tipo": "inventado", "fragmento": "Frenos", "problema": "Título genérico.", "sugerencia": ""},
        {"tipo": "gramatica", "fragmento": "x", "problema": ""},
        "no es un error",
    ],
}


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def _responde(monkeypatch, texto, pedidos=None):
    monkeypatch.setattr(llm, "disponible", lambda: True)

    def completar(system, user, **k):
        if pedidos is not None:
            pedidos.append((user, k["tarea"]))
        return texto
    monkeypatch.setattr(llm, "completar", completar)


def test_criticar_usa_el_modelo_de_evaluacion_con_el_tono_pedido(monkeypatch):
    pedidos = []
    _responde(monkeypatch, json.dumps(RESPUESTA), pedidos)
    c = critica.criticar(NOTA, "comercial", ["argentina"])
    (user, tarea), = pedidos
    assert tarea == "evaluacion"
    assert "redactor comercial" in user and "voseo" in user and NOTA.strip() in user
    assert c["puntaje"] == 10 and c["resumen"] == "Buen gancho, pero mezcla voseo y tuteo."
    assert c["aspectos"] == {"gramatica": 8, "redaccion": 6, "tono": 1}
    assert [e["tipo"] for e in c["errores"]] == ["ortografia", "tono", "redaccion"]
    assert c["errores"][1]["sugerencia"] == "Descubrí cómo" and c["fecha"]


@pytest.mark.parametrize("texto", ["no es json", '{"resumen": "sin puntaje"}'])
def test_critica_rota_queda_con_error(monkeypatch, texto):
    _responde(monkeypatch, texto)
    assert "error" in critica.criticar(NOTA)


def test_sin_proveedor_no_critica(monkeypatch):
    monkeypatch.setattr(llm, "disponible", lambda: False)
    assert "error" in critica.criticar(NOTA)


def test_criticar_guardada_deja_la_critica_en_la_nota(monkeypatch, base):
    _responde(monkeypatch, json.dumps(RESPUESTA))
    nid = base.notas_fase2.insert_one({"contenido": NOTA, "persona": "analitico", "regiones": ["mexico"]}).inserted_id
    c = critica.criticar_guardada("notas_fase2", str(nid), base=base)
    assert base.notas_fase2.find_one({"_id": nid})["critica"] == c
    assert critica.criticar_guardada("notas_fase2", str(ObjectId()), base=base) is None
    with pytest.raises(calibracion.ErrorCalibracion):
        critica.criticar_guardada("articulos", str(nid), base=base)


def test_una_critica_fallida_no_pisa_la_anterior(monkeypatch, base):
    _responde(monkeypatch, "no es json")
    nid = base.notas_fase2.insert_one({"contenido": NOTA, "critica": {"puntaje": 7}}).inserted_id
    assert "error" in critica.criticar_guardada("notas_fase2", str(nid), base=base)
    assert base.notas_fase2.find_one({"_id": nid})["critica"] == {"puntaje": 7}


@pytest.fixture
def client(api, base, monkeypatch):
    from afterdrive import db as db_module
    monkeypatch.setattr(db_module, "db", base)
    flask_api, _ = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c


def test_endpoint_de_critica(client, base, monkeypatch):
    nid = str(base.notas_fase2.insert_one({"contenido": NOTA}).inserted_id)
    _responde(monkeypatch, json.dumps(RESPUESTA))
    r = client.post("/api/historial/critica", json={"coleccion": "notas_fase2", "id": nid})
    assert r.status_code == 200 and r.json["critica"]["puntaje"] == 10
    assert base.notas_fase2.find_one({"_id": ObjectId(nid)})["critica"]["puntaje"] == 10
    assert client.post("/api/historial/critica", json={"coleccion": "notas_fase2", "id": "x"}).status_code == 400
    assert client.post("/api/historial/critica",
                       json={"coleccion": "notas_fase2", "id": str(ObjectId())}).status_code == 404
    _responde(monkeypatch, "no es json")
    r = client.post("/api/historial/critica", json={"coleccion": "notas_fase2", "id": nid})
    assert r.status_code == 503 and not r.json["success"]
