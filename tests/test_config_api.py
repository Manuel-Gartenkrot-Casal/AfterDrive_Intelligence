"""Tests de los endpoints de programación (hora de scraping y generación)."""

import pytest


@pytest.fixture
def client(api):
    """(test_client, store) con la sesión del admin ya iniciada."""
    flask_api, store = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c, store


def test_guardar_y_leer_hora_de_scraping(client):
    c, store = client
    r = c.post("/api/scraping-config", json={"hora": "07:15"})
    assert r.status_code == 200
    assert store["scraping"]["hora"] == "07:15"
    assert c.get("/api/scraping-config").json["hora"] == "07:15"


def test_guardar_hora_de_generacion(client):
    c, store = client
    assert c.post("/api/generacion-config", json={"hora": "23:59"}).status_code == 200
    assert store["generacion"]["hora"] == "23:59"


@pytest.mark.parametrize("hora", ["24:00", "7:15", "07:60", "ayer", 715])
def test_hora_invalida_se_rechaza(client, hora):
    c, store = client
    assert c.post("/api/scraping-config", json={"hora": hora}).status_code == 400
    assert c.post("/api/generacion-config", json={"hora": hora}).status_code == 400
    assert "scraping" not in store and "generacion" not in store


def test_la_config_informa_la_zona_horaria(client):
    c, _ = client
    assert c.get("/api/scraping-config").json["zona"] == "America/Argentina/Buenos_Aires"
