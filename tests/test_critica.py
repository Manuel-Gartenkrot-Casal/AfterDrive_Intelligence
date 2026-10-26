"""La crítica de la redacción hecha por la IA (gramática, tono, estructura) que se ve al calificar."""

import json

import mongomock
import pytest
from bson import ObjectId

from afterdrive import calibracion, historial
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


def test_respuesta_cortada_se_queda_con_lo_completo(monkeypatch):
    # El modelo se quedó sin tokens a mitad del segundo error.
    completa = json.dumps(RESPUESTA, ensure_ascii=False)
    cortada = completa[:completa.index("Descubre cómo") + 5]
    _responde(monkeypatch, "<think>pienso</think>" + cortada)
    c = critica.criticar(NOTA)
    assert c["puntaje"] == 10 and [e["tipo"] for e in c["errores"]] == ["ortografia"]


def test_reintenta_una_vez_si_la_respuesta_viene_rota(monkeypatch):
    respuestas = iter(["no es json", json.dumps(RESPUESTA)])
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "completar", lambda *a, **k: next(respuestas))
    assert critica.criticar(NOTA)["puntaje"] == 10


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


def test_la_lista_del_historial_trae_el_puntaje_de_la_ia(base):
    base.notas_fase2.insert_many([{"contenido": NOTA, "critica": {"puntaje": 7, "errores": [{"tipo": "tono"}]}},
                                  {"contenido": NOTA}])
    puntajes = [it["critica_puntaje"] for it in historial.listar("generados_aprobados", base=base)["items"]]
    assert sorted(puntajes, key=str) == [7, None]


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


# ── Idioma de la calificación ────────────────────────────────────────────────


def test_la_critica_se_escribe_en_espanol_aunque_la_nota_este_en_otro_idioma(monkeypatch):
    pedidos = []
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "completar", lambda system, user, **k: pedidos.append(system) or json.dumps(RESPUESTA))
    c = critica.criticar("# Freios em alta\n\nTexto.", "comercial", idioma="pt")
    assert "en español rioplatense, aunque la nota esté en otro idioma" in pedidos[0]
    assert c["idioma"] == "es"


def _guardada(base, **extra):
    return base.notas_fase2.insert_one({"contenido": NOTA, "critica": {
        "puntaje": 7, "resumen": "Buen gancho.", "idioma": "es",
        "errores": [{"tipo": "tono", "fragmento": "Descubre", "problema": "Tutea.", "sugerencia": "Descubrí"}], **extra}}).inserted_id


def test_traducir_guardada_traduce_una_vez_y_la_deja_en_la_nota(monkeypatch, base):
    pedidos = []
    monkeypatch.setattr(llm, "disponible", lambda: True)

    def completar(system, user, **k):
        pedidos.append((system, json.loads(user), k["tarea"]))
        return json.dumps({"resumen": "Good hook.", "problemas": ["Uses tú."]})
    monkeypatch.setattr(llm, "completar", completar)
    nid = _guardada(base)
    t = critica.traducir_guardada("notas_fase2", str(nid), "en", base=base)
    assert t == {"resumen": "Good hook.", "problemas": ["Uses tú."]}
    (system, enviado, tarea), = pedidos
    assert "inglés" in system and tarea == "traduccion" and enviado == {"resumen": "Buen gancho.", "problemas": ["Tutea."]}
    assert base.notas_fase2.find_one({"_id": nid})["critica"]["traducciones"]["en"] == t
    # La segunda vez sale de lo guardado, sin llamar a la IA.
    assert critica.traducir_guardada("notas_fase2", str(nid), "en", base=base) == t and len(pedidos) == 1


def test_en_su_propio_idioma_no_se_traduce(monkeypatch, base):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: pytest.fail("no tenía que llamar a la IA"))
    nid = _guardada(base)
    assert critica.traducir_guardada("notas_fase2", str(nid), "es", base=base) == {"resumen": "Buen gancho.", "problemas": ["Tutea."]}


def test_una_traduccion_incompleta_no_se_guarda(monkeypatch, base):
    _responde(monkeypatch, json.dumps({"resumen": "Bom gancho.", "problemas": []}))
    nid = _guardada(base)
    assert "error" in critica.traducir_guardada("notas_fase2", str(nid), "pt", base=base)
    assert "traducciones" not in base.notas_fase2.find_one({"_id": nid})["critica"]


def test_traducir_guardada_valida_el_pedido(base):
    nid = _guardada(base)
    with pytest.raises(calibracion.ErrorCalibracion):
        critica.traducir_guardada("notas_fase2", str(nid), "fr", base=base)
    sin = base.notas_fase2.insert_one({"contenido": NOTA}).inserted_id
    with pytest.raises(calibracion.ErrorCalibracion):
        critica.traducir_guardada("notas_fase2", str(sin), "en", base=base)
    assert critica.traducir_guardada("notas_fase2", str(ObjectId()), "en", base=base) is None


def test_endpoint_de_traduccion_de_la_critica(client, base, monkeypatch):
    _responde(monkeypatch, json.dumps({"resumen": "Bom gancho.", "problemas": ["Usa tú."]}))
    nid = str(_guardada(base))
    r = client.post("/api/historial/critica/traduccion", json={"coleccion": "notas_fase2", "id": nid, "idioma": "pt"})
    assert r.status_code == 200 and r.json["traduccion"]["resumen"] == "Bom gancho."
    assert client.post("/api/historial/critica/traduccion",
                       json={"coleccion": "notas_fase2", "id": nid, "idioma": "xx"}).status_code == 400
    assert client.post("/api/historial/critica/traduccion",
                       json={"coleccion": "notas_fase2", "id": str(ObjectId()), "idioma": "pt"}).status_code == 404
