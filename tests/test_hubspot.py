"""Tests de la publicación en HubSpot: qué se manda, cuándo se permite y qué se guarda."""

import mongomock
import pytest
from bson import ObjectId

from afterdrive import db as db_module
from afterdrive import historial, hubspot

NOTA = """# Frenos: la demanda sube en Argentina

## Qué pasó
El mercado de **pastillas de freno** creció un 12 % en el último trimestre.

- Más reposición
- Menos importación

*La demanda de frenos crece y el distribuidor necesita stock de alta rotación.*"""


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture
def hs(monkeypatch):
    """HubSpot falso: anota cada llamada y responde lo que se le cargue."""
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat-test")
    monkeypatch.setenv("HUBSPOT_BLOG_ID", "123")
    llamadas = []
    respuesta = {"status": 200, "body": {"id": "999", "url": "https://blog/frenos", "state": "DRAFT"}}

    def fake(metodo):
        def f(url, json, headers, timeout):
            llamadas.append({"metodo": metodo, "url": url, "json": json, "headers": headers})
            return Resp(respuesta["status"], respuesta["body"])
        return f

    monkeypatch.setattr(hubspot, "_transporte", {"post": fake("post"), "patch": fake("patch")})
    return llamadas, respuesta


def test_preparar_separa_titulo_meta_y_pasa_a_html():
    p = hubspot.preparar(NOTA)
    assert p["titulo"] == "Frenos: la demanda sube en Argentina"
    assert p["meta"].startswith("La demanda de frenos crece")
    assert "<h1>" not in p["html"] and "<h2>Qué pasó</h2>" in p["html"]
    assert "<strong>pastillas de freno</strong>" in p["html"] and "<li>Más reposición</li>" in p["html"]
    assert "La demanda de frenos crece" not in p["html"]


def test_preparar_sin_titulo_falla_con_mensaje():
    with pytest.raises(hubspot.ErrorHubSpot):
        hubspot.preparar("Texto sin encabezado")


def test_slug_sin_acentos_ni_simbolos():
    assert hubspot._slug("Frenos: la demanda ¡sube! en Córdoba", "a1b2c3") == "frenos-la-demanda-sube-en-cordoba-a1b2c3"


def test_enviar_crea_borrador_con_el_token(hs):
    llamadas, _ = hs
    r = hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})
    assert r == {"id": "999", "url": "https://blog/frenos", "estado": "DRAFT"}
    c = llamadas[0]
    assert c["metodo"] == "post" and c["url"] == hubspot.API
    assert c["headers"]["Authorization"] == "Bearer pat-test"
    assert c["json"]["contentGroupId"] == "123" and c["json"]["state"] == "DRAFT"
    assert c["json"]["name"] == "Frenos: la demanda sube en Argentina" and c["json"]["slug"].startswith("frenos-la-demanda")


def test_reenviar_actualiza_el_mismo_post_sin_cambiar_el_slug(hs):
    llamadas, _ = hs
    hubspot.enviar({"_id": ObjectId(), "contenido": NOTA, "hubspot": {"id": "999"}}, publicar=True)
    c = llamadas[0]
    assert c["metodo"] == "patch" and c["url"].endswith("/999")
    assert c["json"]["state"] == "PUBLISHED" and "slug" not in c["json"]


@pytest.mark.parametrize("status, texto", [(401, "token"), (404, "HUBSPOT_BLOG_ID"), (429, "limitando"), (500, "500")])
def test_errores_de_hubspot_se_explican(hs, status, texto):
    _, respuesta = hs
    respuesta.update(status=status, body={"message": "x"})
    with pytest.raises(hubspot.ErrorHubSpot, match=texto):
        hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})


def test_sin_configurar_no_llama(monkeypatch):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.setattr(hubspot, "_transporte", {"post": None, "patch": None})
    assert not hubspot.configurado()
    with pytest.raises(hubspot.ErrorHubSpot, match="no está configurado"):
        hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})


# ── Flujo completo desde el historial ─────────────────────────────────────────


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def test_solo_las_notas_aprobadas_van_a_hubspot(hs, base):
    llamadas, _ = hs
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "borrador"}).inserted_id
    with pytest.raises(historial.ErrorHistorial, match="Aprobá"):
        historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=True, base=base)
    assert llamadas == []


def test_publicar_marca_la_nota_y_guarda_el_post(hs, base):
    _, respuesta = hs
    respuesta["body"] = {"id": "777", "url": "https://blog/x", "state": "PUBLISHED"}
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    item = historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=True, base=base)
    assert item["estado"] == "publicado" and item["publicado_en"]
    assert item["hubspot"]["id"] == "777" and item["hubspot"]["url"] == "https://blog/x"


def test_borrador_en_hubspot_no_cambia_el_estado(hs, base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    item = historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert item["estado"] == "aprobada" and item["hubspot"]["estado"] == "DRAFT"


def test_endpoint_enviar(hs, api, monkeypatch, base):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    assert c.get("/api/hubspot/estado").json["configurado"] is True
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    r = c.post("/api/hubspot/enviar", json={"coleccion": "notas_fase2", "id": str(oid), "publicar": True})
    assert r.status_code == 200 and r.json["item"]["estado"] == "publicado"
    hs[1].update(status=401)
    r = c.post("/api/hubspot/enviar", json={"coleccion": "notas_fase2", "id": str(oid), "publicar": True})
    assert r.status_code == 502 and "token" in r.json["error"]


def test_despublicar_tambien_la_saca_del_blog(hs, base):
    llamadas, _ = hs
    oid = base.notas_fase2.insert_one(
        {"contenido": NOTA, "estado": "publicado", "hubspot": {"id": "777", "estado": "PUBLISHED"}}).inserted_id
    item = historial.cambiar_estado("notas_fase2", str(oid), "aprobada", base=base)
    assert item["estado"] == "aprobada" and item["hubspot"]["estado"] == "DRAFT"
    assert llamadas[-1]["metodo"] == "patch" and llamadas[-1]["url"].endswith("/777")
    assert llamadas[-1]["json"] == {"state": "DRAFT"}


def test_si_hubspot_falla_al_despublicar_no_cambia_nada(hs, base):
    _, respuesta = hs
    respuesta.update(status=500)
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "publicado", "hubspot": {"id": "777"}}).inserted_id
    with pytest.raises(hubspot.ErrorHubSpot):
        historial.cambiar_estado("notas_fase2", str(oid), "aprobada", base=base)
    assert base.notas_fase2.find_one({"_id": oid})["estado"] == "publicado"
