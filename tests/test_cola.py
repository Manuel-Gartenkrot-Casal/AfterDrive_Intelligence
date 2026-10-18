"""Tests de la Cola de Corridas: esperan su turno en orden, sin duplicarse ni perderse."""

import threading
import time

import mongomock
import pytest

from afterdrive import cola, corridas


@pytest.fixture
def col(monkeypatch):
    c = mongomock.MongoClient().db.corridas
    monkeypatch.setattr(cola, "_col", lambda: c)
    return c


@pytest.fixture
def ejecutadas(monkeypatch):
    """Reemplaza los ejecutores in-process por uno que anota el orden."""
    orden = []

    def scrapear(max_articulos):
        print(f"scrapeando {max_articulos}")
        orden.append(("scraping", max_articulos))
        return {"success": True, "aprobados": 2}

    def generar(params):
        print("generando")
        orden.append(("generacion", params))
        return {"success": False, "error": "sin categorías"}

    monkeypatch.setattr(corridas, "_scrapear_fuentes", scrapear)
    monkeypatch.setattr(corridas, "_generar", generar)
    return orden


def test_corren_en_orden_de_llegada(col, ejecutadas):
    cola.encolar("scraping", {"max_articulos": 3})
    cola.encolar("generacion")
    assert cola.procesar_pendientes() == 2
    assert ejecutadas == [("scraping", 3), ("generacion", None)]
    estados = [d["estado"] for d in col.find().sort("creada", 1)]
    assert estados == ["ok", "error"]


def test_el_log_queda_guardado_y_se_lee_por_offset(col, ejecutadas):
    id_ = cola.encolar("scraping", {"max_articulos": 1})["id"]
    cola.procesar_pendientes()
    todo = cola.log(id_)
    assert todo["estado"] == "ok" and "scrapeando 1" in todo["lineas"]
    resto = cola.log(id_, desde=todo["siguiente"])
    assert resto["lineas"] == [] and resto["siguiente"] == todo["siguiente"]


def test_una_identica_pendiente_no_se_duplica(col, ejecutadas):
    a = cola.encolar("generacion", origen="cron")
    b = cola.encolar("generacion")
    assert b["duplicada"] and b["id"] == a["id"]
    assert col.count_documents({}) == 1
    c = cola.encolar("scraping")
    assert not c["duplicada"] and c["posicion"] == 2


def test_cola_llena(col, ejecutadas):
    for i in range(cola.MAX_PENDIENTES):
        cola.encolar("scraping", {"max_articulos": i + 1})
    with pytest.raises(cola.ColaLlena):
        cola.encolar("scraping", {"max_articulos": 99})


def test_cancelar_una_pendiente_hace_que_no_corra(col, ejecutadas):
    id_ = cola.encolar("scraping")["id"]
    assert cola.cancelar(id_) == {"estado": "cancelada"}
    assert cola.procesar_pendientes() == 0 and ejecutadas == []


def test_al_arrancar_la_que_estaba_en_curso_queda_interrumpida(col):
    col.insert_one({"tipo": "scraping", "estado": "en_curso", "creada": "2026-01-01"})
    col.insert_one({"tipo": "scraping", "estado": "pendiente", "creada": "2026-01-02", "clave": "x"})
    cola.recuperar_al_arrancar()
    assert sorted(d["estado"] for d in col.find()) == ["interrumpida", "pendiente"]


def test_espera_a_que_termine_la_corrida_que_tiene_el_lock(col, ejecutadas):
    """Una Corrida que tomó el lock por fuera de la cola (botón viejo) no la rechaza: la demora."""
    cola.encolar("scraping")
    with corridas._reservar("otra"):
        t = threading.Thread(target=cola.procesar_pendientes)
        t.start()
        time.sleep(0.2)
        assert ejecutadas == []
    t.join(timeout=5)
    assert ejecutadas == [("scraping", None)]


@pytest.fixture
def script_lento(tmp_path):
    p = tmp_path / "lento.py"
    p.write_text("import time\nprint('uno', flush=True)\ntime.sleep(30)\n")
    return str(p)


def test_cancelar_un_script_en_curso_lo_mata(col, script_lento):
    id_ = cola.encolar("script", {"modulo": script_lento})["id"]
    t = threading.Thread(target=cola.procesar_pendientes)
    t.start()
    for _ in range(50):
        if "uno" in (cola.log(id_) or {}).get("lineas", []):
            break
        time.sleep(0.1)
    assert cola.cancelar(id_) == {"estado": "cancelando"}
    t.join(timeout=5)
    assert not t.is_alive()
    assert cola.log(id_)["estado"] == "cancelada"
    assert corridas.en_curso() is None


def test_la_generacion_en_curso_no_se_corta(col, monkeypatch):
    listo, seguir = threading.Event(), threading.Event()

    def generar(params):
        listo.set()
        seguir.wait(5)
        return {"success": True}

    monkeypatch.setattr(corridas, "_generar", generar)
    id_ = cola.encolar("generacion")["id"]
    t = threading.Thread(target=cola.procesar_pendientes)
    t.start()
    assert listo.wait(5)
    with pytest.raises(cola.NoCancelable):
        cola.cancelar(id_)
    seguir.set()
    t.join(timeout=5)
    assert cola.log(id_)["estado"] == "ok"


def test_el_cron_encola_en_vez_de_perderse(col, monkeypatch):
    from afterdrive import scheduler
    for _, _, correr in scheduler._JOBS.values():
        correr()
    assert sorted(d["tipo"] for d in col.find()) == ["generacion", "scraping"]
    assert {d["origen"] for d in col.find()} == {"cron"}


@pytest.fixture
def client(api, col):
    flask_api, _ = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c


def test_api_encola_lista_y_cancela(client, ejecutadas):
    r = client.post("/api/corridas/scraping")
    assert r.status_code == 202 and r.json["posicion"] == 1
    id_ = r.json["id"]
    lista = client.get("/api/corridas").json
    assert [p["id"] for p in lista["pendientes"]] == [id_] and lista["en_curso"] is None
    assert client.get(f"/api/corridas/{id_}/log").json["posicion"] == 1
    assert client.post(f"/api/corridas/{id_}/cancelar").json["estado"] == "cancelada"
    assert client.get("/api/corridas").json["recientes"][0]["estado"] == "cancelada"


def test_api_generacion_arma_el_argv_del_formulario(client, col):
    r = client.post("/api/corridas/generacion", json={"categorias": ["autopartes"], "persona": "ejecutivo"})
    assert r.status_code == 202
    doc = col.find_one()
    assert doc["tipo"] == "script" and doc["etiqueta"] == "Generar nota"
    assert doc["params"] == {"modulo": "afterdrive.generacion.generar_nota_fase2",
                             "argv": ["--categorias", "autopartes", "--persona=ejecutivo"]}


def test_api_generacion_sin_categorias_es_400(client, col):
    assert client.post("/api/corridas/generacion", json={"categorias": []}).status_code == 400
    assert col.count_documents({}) == 0


def test_api_cola_llena_es_429(client, col):
    for i in range(cola.MAX_PENDIENTES):
        client.post("/api/corridas/ejemplos", json={"max": i + 1})
    assert client.post("/api/corridas/ejemplos", json={"max": 99}).status_code == 429


def test_api_log_de_id_invalido_es_404(client):
    assert client.get("/api/corridas/no-es-un-id/log").status_code == 404
    assert client.post("/api/corridas/no-es-un-id/cancelar").status_code == 404


def test_limpiar_viejas_borra_solo_terminadas_de_hace_mas_de_30_dias(col):
    import datetime
    hace = lambda d: (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=d)).isoformat()  # noqa: E731
    col.insert_many([
        {"estado": "ok", "fin": hace(40)},
        {"estado": "error", "fin": hace(31)},
        {"estado": "ok", "fin": hace(5)},
        {"estado": "pendiente", "creada": hace(40)},
    ])
    assert cola.limpiar_viejas() == 2
    assert sorted(d["estado"] for d in col.find()) == ["ok", "pendiente"]
