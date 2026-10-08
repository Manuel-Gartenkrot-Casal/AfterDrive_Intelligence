"""Tests del historial: secciones, paginación entre colecciones, estado editorial."""

import datetime

import mongomock
import pytest
from bson import ObjectId

import db as db_module
import historial


def _oid(minutos: int) -> ObjectId:
    """ObjectId con fecha controlada: el historial ordena por la fecha del _id."""
    base = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
    return ObjectId.from_datetime(base + datetime.timedelta(minutes=minutos))


@pytest.fixture
def base():
    b = mongomock.MongoClient().db
    # Notas aprobadas: Fase 1 con y sin estado (las viejas no tienen el campo).
    b.articulos_generados.insert_many([
        {"_id": _oid(1), "contenido": "# Frenos 2026\n\nTexto sobre frenos.", "tema": "frenos",
         "embedding": [0.1] * 2048},
        {"_id": _oid(5), "contenido": "# Filtros\n\nTexto.", "estado": "publicado"},
    ])
    b.notas_fase2.insert_many([
        {"_id": _oid(3), "contenido": "Primera línea sin encabezado\nResto.", "estado": "borrador",
         "persona": "comercial"},
        {"_id": _oid(7), "contenido": "# Neumáticos (+ datos)\n\nUno.", "embedding": [0.2] * 10},
    ])
    b.notas_descartadas.insert_one(
        {"_id": _oid(2), "origen": "fase2", "contenido": "<think>planeo</think>", "motivo": "razonamiento en vez de nota"}
    )
    b.articulos.insert_many([
        {"_id": _oid(10), "titulo": "Autopartes crecen", "cuerpo": "Cuerpo A", "url": "https://a"},
        {"_id": _oid(12), "titulo": "Repuestos", "cuerpo": "Cuerpo B", "url": "https://b"},
    ])
    b.afterdrive.insert_one({"_id": _oid(11), "titulo": "Heredado", "cuerpo": "Viejo", "url": "https://c"})
    b.articulos_descartados.insert_many([
        {"_id": _oid(20), "url": "https://viejo-sin-motivo"},
        {"_id": _oid(21), "url": "https://nuevo", "titulo": "Nissan 65 años", "razon": "No es repuesto"},
    ])
    return b


def test_resumen_cuenta_secciones_publicadas_y_borradores(base):
    r = historial.resumen(base)
    assert r["generados_aprobados"] == {
        "total": 4, "publicados": 1, "borradores": 3,
        "por_origen": {"Artículo por tema": 2, "Nota AfterDrive": 2},
    }
    assert r["generados_descartados"]["total"] == 1
    assert r["scrapeados_aprobados"]["total"] == 3  # incluye la colección heredada
    assert r["scrapeados_descartados"] == {"total": 2, "sin_motivo": 1}


def test_listar_mezcla_colecciones_por_fecha_y_pagina_sin_huecos(base):
    vistos = []
    for pagina in (1, 2):
        r = historial.listar("generados_aprobados", pagina=pagina, por_pagina=3, base=base)
        assert r["total"] == 4 and r["paginas"] == 2
        vistos += [i["id"] for i in r["items"]]
    # Orden descendente por fecha, alternando colecciones, sin duplicar ni perder.
    assert vistos == [str(_oid(m)) for m in (7, 5, 3, 1)]


def test_listar_nunca_devuelve_embeddings(base):
    r = historial.listar("generados_aprobados", base=base)
    assert all("embedding" not in i and "contenido" not in i for i in r["items"])


def test_borrador_incluye_notas_sin_campo_estado(base):
    borradores = historial.listar("generados_aprobados", estado="borrador", base=base)
    publicadas = historial.listar("generados_aprobados", estado="publicado", base=base)
    assert borradores["total"] == 3 and publicadas["total"] == 1
    assert {i["estado"] for i in borradores["items"]} == {"borrador"}
    assert publicadas["items"][0]["titulo"] == "Filtros"


def test_titulo_sale_del_encabezado_o_de_la_primera_linea(base):
    titulos = {i["id"]: i["titulo"] for i in historial.listar("generados_aprobados", base=base)["items"]}
    assert titulos[str(_oid(1))] == "Frenos 2026"
    assert titulos[str(_oid(3))] == "Primera línea sin encabezado"


def test_busqueda_escapa_caracteres_especiales_y_ignora_mayusculas(base):
    r = historial.listar("generados_aprobados", q="NEUMÁTICOS (+", base=base)
    assert [i["titulo"] for i in r["items"]] == ["Neumáticos (+ datos)"]


def test_descartados_muestran_motivo_y_los_viejos_quedan_sin_motivo(base):
    items = historial.listar("scrapeados_descartados", base=base)["items"]
    motivos = {i["url"]: i["motivo"] for i in items}
    assert motivos == {"https://nuevo": "No es repuesto", "https://viejo-sin-motivo": None}
    # Sin título guardado, se muestra la URL.
    assert items[1]["titulo"] == "https://viejo-sin-motivo"


def test_scrapeados_incluye_la_coleccion_heredada(base):
    origenes = {i["titulo"]: i["origen"] for i in historial.listar("scrapeados_aprobados", base=base)["items"]}
    assert origenes["Heredado"] == "Scraping (colección anterior)"


def test_detalle_devuelve_el_contenido_completo(base):
    item = historial.detalle("generados_aprobados", "articulos_generados", str(_oid(1)), base=base)
    assert item["contenido"].startswith("# Frenos 2026") and "embedding" not in item


@pytest.mark.parametrize("seccion,coleccion", [
    ("generados_aprobados", "config"),          # colección fuera de la lista blanca
    ("generados_aprobados", "articulos"),       # existe, pero no es de esta sección
    ("inexistente", "articulos_generados"),
])
def test_detalle_rechaza_colecciones_fuera_de_la_seccion(base, seccion, coleccion):
    with pytest.raises(historial.ErrorHistorial):
        historial.detalle(seccion, coleccion, str(_oid(1)), base=base)


def test_detalle_rechaza_ids_invalidos(base):
    with pytest.raises(historial.ErrorHistorial):
        historial.detalle("generados_aprobados", "notas_fase2", "no-es-un-id", base=base)


def test_cambiar_estado_publica_y_vuelve_a_borrador(base):
    item = historial.cambiar_estado("articulos_generados", str(_oid(1)), "publicado", base=base)
    assert item["estado"] == "publicado" and item["publicado_en"]
    item = historial.cambiar_estado("articulos_generados", str(_oid(1)), "borrador", base=base)
    assert item["estado"] == "borrador" and item["publicado_en"] is None
    assert "publicado_en" not in base.articulos_generados.find_one({"_id": _oid(1)})


@pytest.mark.parametrize("coleccion,estado", [
    ("articulos", "publicado"),            # un artículo scrapeado no se publica
    ("notas_descartadas", "publicado"),
    ("notas_fase2", "archivado"),
])
def test_cambiar_estado_valida_coleccion_y_estado(base, coleccion, estado):
    with pytest.raises(historial.ErrorHistorial):
        historial.cambiar_estado(coleccion, str(_oid(3)), estado, base=base)


def test_cambiar_estado_de_nota_inexistente_devuelve_none(base):
    assert historial.cambiar_estado("notas_fase2", str(_oid(999)), "publicado", base=base) is None


def test_registrar_nota_descartada_guarda_y_nunca_corta_la_generacion(monkeypatch):
    col = mongomock.MongoClient().db.notas_descartadas
    monkeypatch.setattr(db_module, "col_notas_descartadas", col)
    db_module.registrar_nota_descartada("fase1", "x" * 30000, "muy corto", tema="frenos")
    doc = col.find_one()
    assert doc["motivo"] == "muy corto" and doc["tema"] == "frenos" and len(doc["contenido"]) == 20000

    class Rota:
        def insert_one(self, _):
            raise RuntimeError("mongo caído")

    monkeypatch.setattr(db_module, "col_notas_descartadas", Rota())
    db_module.registrar_nota_descartada("fase2", "texto", "motivo")  # no debe lanzar


@pytest.fixture
def client(monkeypatch, base):
    import scheduler

    monkeypatch.setattr(scheduler, "iniciar", lambda: None)
    monkeypatch.setattr(scheduler, "aplicar", lambda: None)
    monkeypatch.setattr(db_module, "db", base)
    import flask_api
    monkeypatch.setenv("ADMIN_USER", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "configured-in-test")
    monkeypatch.setitem(flask_api.app.config, "SECRET_KEY", "test-only-session-key")
    c = flask_api.app.test_client()
    with c.session_transaction() as session:
        session["usuario"] = "test-admin"

    return c


def test_endpoints_de_historial(client):
    assert client.get("/api/historial/resumen").json["generados_aprobados"]["publicados"] == 1

    r = client.get("/api/historial/generados_aprobados?por_pagina=2&estado=borrador")
    assert r.status_code == 200 and len(r.json["items"]) == 2 and r.json["total"] == 3

    item = r.json["items"][0]
    det = client.get(f"/api/historial/generados_aprobados/{item['coleccion']}/{item['id']}")
    assert det.status_code == 200 and det.json["item"]["contenido"]

    pub = client.post("/api/historial/estado", json={"coleccion": item["coleccion"], "id": item["id"], "estado": "publicado"})
    assert pub.status_code == 200 and pub.json["item"]["estado"] == "publicado"


def test_endpoints_responden_400_y_404_con_json(client):
    assert client.get("/api/historial/inventada").status_code == 400
    assert client.get("/api/historial/generados_aprobados/config/" + str(_oid(1))).status_code == 400
    assert client.get("/api/historial/generados_aprobados/notas_fase2/" + str(_oid(999))).status_code == 404
    r = client.post("/api/historial/estado", json={"coleccion": "articulos", "id": str(_oid(10)), "estado": "publicado"})
    assert r.status_code == 400 and r.json["success"] is False
