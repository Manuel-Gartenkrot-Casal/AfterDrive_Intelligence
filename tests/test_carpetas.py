"""Tests de la carpeta de cada cliente: datos y eventos (carpetas.py y su API)."""

import mongomock
import pytest

from afterdrive import carpetas
from afterdrive import db as db_module

# ── Entradas ─────────────────────────────────────────────────────────────────


def test_nueva_entrada_valida():
    doc, error = carpetas.nueva_entrada("dato", {"titulo": " Contacto comercial ", "contenido": "Ana, ana@acme.com"})
    assert error is None and doc["titulo"] == "Contacto comercial" and doc["contenido"] == "Ana, ana@acme.com"
    assert carpetas.nueva_entrada("dato", {"titulo": "", "contenido": "x"})[1]
    assert carpetas.nueva_entrada("dato", {"titulo": "t", "contenido": "x" * 5001})[1]
    assert carpetas.nueva_entrada("dato", {"titulo": ["t"], "contenido": "x"})[1]
    assert carpetas.nueva_entrada("evento", {"nombre": "Feria", "fecha": "15/03/2026"})[1]
    assert carpetas.nueva_entrada("otro", {})[1]
    ev, error = carpetas.nueva_entrada("evento", {"nombre": "Lanzamiento", "fecha": "2026-03-15",
                                                  "lugar": "Rosario", "descripcion": "Llamar al 341 456-7890"})
    assert error is None and ev["fecha"] == "2026-03-15" and ev["lugar"] == "Rosario"


# ── API ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def carpeta_api(api, monkeypatch):
    flask_api, _ = api
    base = mongomock.MongoClient().db
    monkeypatch.setattr(db_module, "col_clientes", base.clientes)
    monkeypatch.setattr(db_module, "col_carpetas", base.carpetas_clientes)
    base.clientes.insert_one({"slug": "acme", "nombre": "ACME"})
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c, base


def test_subir_un_dato_lo_guarda_en_la_carpeta(carpeta_api):
    c, base = carpeta_api
    r = c.post("/api/carpetas/acme/datos", json={"titulo": "Productos", "contenido": "Filtros y pastillas"})
    assert r.status_code == 200 and r.json["entrada"]["contenido"] == "Filtros y pastillas"
    guardado = base.carpetas_clientes.find_one()
    assert guardado["cliente_slug"] == "acme" and guardado["tipo"] == "dato" and guardado["titulo"] == "Productos"


def test_subir_un_evento_y_listar_la_carpeta(carpeta_api):
    c, _ = carpeta_api
    c.post("/api/carpetas/acme/eventos", json={"nombre": "Feria vieja", "fecha": "2025-05-01"})
    c.post("/api/carpetas/acme/eventos", json={"nombre": "Lanzamiento", "fecha": "2026-03-15", "lugar": "Rosario"})
    c.post("/api/carpetas/acme/datos", json={"titulo": "Productos", "contenido": "Filtros y pastillas"})
    d = c.get("/api/carpetas/acme").json
    assert [e["nombre"] for e in d["eventos"]] == ["Lanzamiento", "Feria vieja"]
    assert [x["titulo"] for x in d["datos"]] == ["Productos"]
    assert all(isinstance(e["id"], str) for e in d["eventos"])
    # La función de lectura para el backend devuelve lo mismo.
    assert [e["nombre"] for e in carpetas.listar("acme", "evento")] == ["Lanzamiento", "Feria vieja"]


def test_cliente_inexistente_y_datos_invalidos(carpeta_api):
    c, base = carpeta_api
    assert c.get("/api/carpetas/nadie").status_code == 404
    assert c.post("/api/carpetas/nadie/datos", json={"titulo": "t", "contenido": "c"}).status_code == 404
    assert c.post("/api/carpetas/acme/datos", json={"titulo": "t"}).status_code == 400
    assert c.post("/api/carpetas/acme/eventos", json={"nombre": "x", "fecha": "mañana"}).status_code == 400
    assert c.post("/api/carpetas/acme/datos", json=["no", "es", "un", "objeto"]).status_code == 400
    assert c.post("/api/carpetas/acme/datos", json="texto").status_code == 400
    assert base.carpetas_clientes.count_documents({}) == 0


def test_borrar_una_entrada(carpeta_api):
    c, base = carpeta_api
    entrada = c.post("/api/carpetas/acme/datos", json={"titulo": "t", "contenido": "c"}).json["entrada"]
    assert c.delete("/api/carpetas/otro/" + entrada["id"]).status_code == 404   # de otra carpeta, no
    assert c.delete("/api/carpetas/acme/no-es-un-id").status_code == 404
    assert c.delete("/api/carpetas/acme/" + entrada["id"]).status_code == 200
    assert base.carpetas_clientes.count_documents({}) == 0


def test_borrar_el_cliente_borra_su_carpeta(carpeta_api):
    c, base = carpeta_api
    c.post("/api/carpetas/acme/datos", json={"titulo": "t", "contenido": "c"})
    c.delete("/api/fase2/clientes/acme")
    assert base.carpetas_clientes.count_documents({}) == 0


def test_la_api_pide_sesion(api):
    flask_api, _ = api
    assert flask_api.app.test_client().get("/api/carpetas/acme").status_code in (401, 302)
