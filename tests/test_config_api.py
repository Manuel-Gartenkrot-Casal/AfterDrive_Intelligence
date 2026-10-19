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
    """Nada se encola: estos tests solo miran la validación."""
    from afterdrive import cola
    monkeypatch.setattr(cola, "encolar", lambda *a, **k: pytest.fail("no debe encolarse"))


@pytest.mark.parametrize("categorias", ["autopartes", ["autopartes", "--puntapie", "http://x"], [1], [{}]])
def test_listas_invalidas_son_400(client, monkeypatch, categorias):
    _sin_corridas(monkeypatch)
    assert client[0].post("/api/corridas/generacion", json={"categorias": categorias}).status_code == 400


@pytest.mark.parametrize("clave", ["clientes", "regiones"])
def test_las_otras_listas_tambien_se_validan(client, monkeypatch, clave):
    _sin_corridas(monkeypatch)
    body = {"categorias": ["autopartes"], clave: ["--tema", "x"]}
    assert client[0].post("/api/corridas/generacion", json=body).status_code == 400


@pytest.mark.parametrize("body", [{"tags": ["--max", "9"]}, {"max": "5; rm"}, {"max": 0}, {"tags": "x"}])
def test_sincronizar_ejemplos_valida_parametros(client, monkeypatch, body):
    _sin_corridas(monkeypatch)
    assert client[0].post("/api/corridas/ejemplos", json=body).status_code == 400


def test_escalares_viajan_como_opcion_igual_valor(client, monkeypatch):
    """Un valor que empieza con '-' no puede convertirse en otra opción del argv."""
    from afterdrive import cola
    visto = {}

    def encolar(tipo, params=None, origen="manual", etiqueta=None):
        visto[params["modulo"]] = params["argv"]
        return {"id": "x", "posicion": 1, "duplicada": False}

    monkeypatch.setattr(cola, "encolar", encolar)
    c = client[0]
    c.post("/api/corridas/generacion",
           json={"categorias": ["autopartes"], "tema": "--persona", "puntapie_url": "-x", "persona": "comercial"})
    argv = visto["afterdrive.generacion.generar_nota_fase2"]
    assert "--tema=--persona" in argv and "--puntapie=-x" in argv and "--persona=comercial" in argv
    assert argv[:2] == ["--categorias", "autopartes"]
    c.post("/api/corridas/ejemplos", json={"tags": ["autopartes"], "max": 5})
    assert visto["afterdrive.generacion.scraper_afterdrive"] == ["--tags", "autopartes", "--max=5"]


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
    for ruta in ("/api/articulos-stats", "/api/db-check"):
        r = c.get(ruta)
        assert r.status_code == 500 and "host-interno" not in r.get_data(as_text=True), ruta
        assert r.json["error"] == "Error interno del servidor"


# ── Alta de fuentes: solo URLs http(s) públicas ───────────────────────────────


@pytest.mark.parametrize("ruta", ["/api/trusted-urls", "/api/corridas/probar-fuente"])
@pytest.mark.parametrize("url", ["http://127.0.0.1/", {"$ne": ""}, 7])
def test_alta_de_url_interna_o_rara_es_400(client, monkeypatch, ruta, url):
    from afterdrive import db
    from afterdrive.ingesta import scraper
    _sin_corridas(monkeypatch)
    monkeypatch.setattr(scraper, "url_publica", lambda u: False)
    monkeypatch.setattr(db, "col_trusted_urls", None)  # tocar Mongo acá sería un error
    assert client[0].post(ruta, json={"url": url}).status_code == 400


def test_alta_de_url_publica_sigue_andando(client, monkeypatch):
    from afterdrive import cola, db
    from afterdrive.ingesta import scraper
    guardadas = []

    class Col:
        def update_one(self, filtro, *_a, **_k):
            guardadas.append(filtro["url"])

    monkeypatch.setattr(scraper, "url_publica", lambda u: True)
    monkeypatch.setattr(db, "col_trusted_urls", Col())
    monkeypatch.setattr(cola, "encolar", lambda tipo, params=None, **k: {"id": params["argv"][0], "posicion": 1, "duplicada": False})
    c = client[0]
    assert c.post("/api/trusted-urls", json={"url": " https://sitio.com/noticias "}).status_code == 200
    assert guardadas == ["https://sitio.com/noticias"]
    assert c.post("/api/corridas/probar-fuente", json={"url": "https://sitio.com/noticias"}).json["id"] == "https://sitio.com/noticias"



@pytest.fixture
def fuentes(client, monkeypatch):
    """Colección trusted_urls en memoria con una fuente activa."""
    import mongomock

    from afterdrive import db
    col = mongomock.MongoClient().db.trusted_urls
    col.insert_one({"url": "https://sitio.com/noticias", "estado": "activo", "nombre_fuente": "Sitio"})
    monkeypatch.setattr(db, "col_trusted_urls", col)
    return client[0], col


def test_pausar_y_reactivar_una_fuente(fuentes):
    c, col = fuentes
    r = c.patch("/api/trusted-urls/https://sitio.com/noticias", json={"estado": "inactivo"})
    assert r.status_code == 200
    doc = col.find_one({"url": "https://sitio.com/noticias"})
    assert doc["estado"] == "inactivo" and doc["nombre_fuente"] == "Sitio"
    assert c.patch("/api/trusted-urls/https://sitio.com/noticias", json={"estado": "activo"}).status_code == 200
    assert col.find_one({"url": "https://sitio.com/noticias"})["estado"] == "activo"


@pytest.mark.parametrize("body", [{}, {"estado": "borrado"}, {"estado": True}])
def test_estado_invalido_es_400(fuentes, body):
    c, col = fuentes
    assert c.patch("/api/trusted-urls/https://sitio.com/noticias", json=body).status_code == 400
    assert col.find_one({"url": "https://sitio.com/noticias"})["estado"] == "activo"


def test_pausar_una_fuente_inexistente_es_404(fuentes):
    c, _ = fuentes
    assert c.patch("/api/trusted-urls/https://otro.com", json={"estado": "inactivo"}).status_code == 404


# ── Config de la Nota automática (Fase 2) ─────────────────────────────────────


def test_config_fase2_cambia_solo_lo_que_viene(client, monkeypatch):
    from afterdrive.ingesta import scraper
    monkeypatch.setattr(scraper, "url_publica", lambda u: True)
    c, store = client
    assert c.post("/api/fase2/config", json={"categorias": ["autopartes"], "clientes": ["acme"]}).status_code == 200
    assert c.post("/api/fase2/config", json={"puntapie_activo": True, "puntapie_url": " https://alephee.com "}).status_code == 200
    cfg = store["fase2"]
    assert cfg["categorias"] == ["autopartes"] and cfg["clientes"] == ["acme"]
    assert cfg["puntapie_activo"] is True and cfg["puntapie_url"] == "https://alephee.com"


@pytest.mark.parametrize("body", [
    {"categorias": "autopartes"},
    {"regiones": ["--tema", "x"]},
    {"clientes": [1]},
    {"puntapie_activo": "si"},
    {"puntapie_url": 5},
    {"puntapie_url": "javascript:alert(1)"},
    {"puntapie_url": "http://127.0.0.1/admin"},
])
def test_config_fase2_invalida_es_400(client, body):
    c, store = client
    assert c.post("/api/fase2/config", json=body).status_code == 400
    assert "fase2" not in store


def test_config_fase2_permite_vaciar_el_puntapie(client):
    c, store = client
    assert c.post("/api/fase2/config", json={"puntapie_url": ""}).status_code == 200
    assert store["fase2"]["puntapie_url"] == ""


def test_largo_de_la_nota(client):
    c, store = client
    assert c.post("/api/generacion-config", json={"largo": "corto"}).status_code == 200
    assert store["generacion"]["largo"] == "corto"
    assert c.post("/api/generacion-config", json={"largo": "enorme"}).status_code == 400


def test_el_largo_llega_al_argv_de_la_generacion(client, monkeypatch):
    from afterdrive import cola
    c, _ = client
    encolado = {}
    monkeypatch.setattr(cola, "encolar", lambda tipo, params=None, **k: encolado.update(params) or
                        {"id": "1", "posicion": 0, "duplicada": False})
    assert c.post("/api/corridas/generacion", json={"categorias": ["autopartes"], "largo": "largo"}).status_code == 202
    assert "--largo=largo" in encolado["argv"]
    assert c.post("/api/corridas/generacion", json={"categorias": ["autopartes"], "largo": "x"}).status_code == 400


def test_documentacion_en_ayuda(client, api):
    c, _ = client
    docs = c.get("/api/docs").json["documentos"]
    assert docs[0] == {"slug": "guia-de-uso", "titulo": "Guía de uso", "grupo": "Usar la aplicación"}
    assert any(d["slug"] == "glosario" for d in docs)
    d = c.get("/api/docs/guia-de-uso").json
    assert d["success"] and d["markdown"].startswith("# Guía de uso")
    assert c.get("/api/docs/..%2F..%2Fetc%2Fpasswd").status_code == 404     # solo la lista blanca
    assert c.get("/api/docs/no-existe").status_code == 404
    flask_api, _ = api
    anonimo = flask_api.app.test_client()
    assert anonimo.get("/api/docs").status_code == 401
    r = anonimo.get("/ayuda")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert c.get("/ayuda").status_code == 200
