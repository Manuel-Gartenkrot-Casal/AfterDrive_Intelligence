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


# ── Parámetros que terminan en el argv de un subproceso ───────────────────────


def _sin_corridas(monkeypatch):
    from afterdrive import corridas
    for nombre in ("stream", "script", "generacion"):
        monkeypatch.setattr(corridas, nombre, lambda *a, **k: pytest.fail("no debe ejecutarse"))


@pytest.mark.parametrize("ruta", ["/api/fase2/stream/generar", "/api/fase2/generar"])
@pytest.mark.parametrize("categorias", ["autopartes", ["autopartes", "--puntapie", "http://x"], [1], [{}]])
def test_listas_invalidas_son_400(client, monkeypatch, ruta, categorias):
    _sin_corridas(monkeypatch)
    assert client[0].post(ruta, json={"categorias": categorias}).status_code == 400


@pytest.mark.parametrize("ruta", ["/api/fase2/stream/generar", "/api/fase2/generar"])
@pytest.mark.parametrize("clave", ["clientes", "regiones"])
def test_las_otras_listas_tambien_se_validan(client, monkeypatch, ruta, clave):
    _sin_corridas(monkeypatch)
    assert client[0].post(ruta, json={"categorias": ["autopartes"], clave: ["--tema", "x"]}).status_code == 400


@pytest.mark.parametrize("ruta", ["/api/fase2/scrape", "/api/fase2/stream/scrape"])
@pytest.mark.parametrize("body", [{"tags": ["--max", "9"]}, {"max": "5; rm"}, {"max": 0}, {"tags": "x"}])
def test_scrape_fase2_valida_parametros(client, monkeypatch, ruta, body):
    _sin_corridas(monkeypatch)
    assert client[0].post(ruta, json=body).status_code == 400


def test_escalares_viajan_como_opcion_igual_valor(client, monkeypatch):
    from afterdrive import corridas
    visto = {}
    monkeypatch.setattr(corridas, "stream", lambda nombre, argv=None: visto.update({nombre: argv}) or iter(()))
    c = client[0]
    c.post("/api/fase2/stream/generar",
           json={"categorias": ["autopartes"], "tema": "--persona", "puntapie_url": "-x", "persona": "comercial"})
    argv = visto["afterdrive.generacion.generar_nota_fase2"]
    assert "--tema=--persona" in argv and "--puntapie=-x" in argv and "--persona=comercial" in argv
    assert argv[:2] == ["--categorias", "autopartes"]
    c.post("/api/fase2/stream/scrape", json={"tags": ["autopartes"], "max": 5})
    assert visto["afterdrive.generacion.scraper_afterdrive"] == ["--tags", "autopartes", "--max=5"]
    c.post("/api/stream/generar", json={"tema": "--fuente", "persona": "ejecutivo"})
    assert visto["afterdrive.generacion.generar_articulo"] == ["--tema=--fuente", "--persona=ejecutivo"]


# ── Fugas de información ──────────────────────────────────────────────────────


def test_db_check_no_expone_credenciales(client, monkeypatch):
    from afterdrive import db

    class Col:
        def count_documents(self, *_):
            return 0

        def find(self, *_a, **_k):
            return self

        def limit(self, _n):
            return []

    monkeypatch.setattr(db, "MONGO_URI", "mongodb+srv://usuario:clave-secreta@cluster.mongodb.net/x")
    monkeypatch.setattr(db, "col_trusted_urls", Col())
    r = client[0].get("/api/db-check")
    cuerpo = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "usuario" not in cuerpo and "clave" not in cuerpo and "cluster.mongodb.net" in cuerpo


def test_errores_no_filtran_la_excepcion(client, monkeypatch):
    from afterdrive import db, flask_api

    class Rota:
        def count_documents(self, *_):
            raise RuntimeError("host-interno-10.0.0.7")

    monkeypatch.setattr(flask_api, "col_articulos", Rota())
    monkeypatch.setattr(db, "col_trusted_urls", Rota())
    c = client[0]
    for ruta in ("/api/articulos-stats", "/api/check-volume?keyword=x", "/api/db-check"):
        r = c.get(ruta)
        assert r.status_code == 500 and "host-interno" not in r.get_data(as_text=True), ruta
        assert r.json["error"] == "Error interno del servidor"
