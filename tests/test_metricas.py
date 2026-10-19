"""Tests de las métricas del tablero de Desarrollador, con Mongo en memoria."""

import datetime

import mongomock
import pytest
from bson import ObjectId

from afterdrive import metricas

AHORA = datetime.datetime.now(datetime.UTC)


def _hace(dias: float) -> datetime.datetime:
    return AHORA - datetime.timedelta(days=dias)


def _oid(dias: float) -> ObjectId:
    return ObjectId.from_datetime(_hace(dias))


@pytest.fixture
def base():
    b = mongomock.MongoClient().db
    b.articulos.insert_many([
        {"_id": _oid(0), "url": "https://www.sitio-a.com/n1"},
        {"_id": _oid(0.01), "url": "https://sitio-a.com/n2"},
        {"_id": _oid(1), "url": "https://sitio-b.com/n3"},
        {"_id": _oid(20), "url": "https://sitio-c.com/viejo"},   # fuera de los 14 días, dentro de 30
        {"_id": _oid(90), "url": "https://sitio-d.com/muy-viejo"},
    ])
    b.articulos_descartados.insert_many([
        # Creado hace mucho, pero descartado de nuevo hoy: cuenta hoy.
        {"_id": _oid(80), "url": "https://sitio-b.com/x", "fecha_descarte": _hace(0).isoformat()},
        {"_id": _oid(2), "url": "https://sitio-a.com/y", "fecha_descarte": _hace(2).isoformat()},
    ])
    b.notas_fase2.insert_many([
        {"generado_en": _hace(0).isoformat(), "estado": "borrador",
         "calidad": {"puntaje": 8, "intentos": 1}, "calificacion": {"puntaje": 4}},
        {"generado_en": _hace(1).isoformat(), "estado": "publicado", "calidad": {"puntaje": 6, "intentos": 2}},
        {"generado_en": _hace(40).isoformat(), "estado": "rechazada"},
    ])
    b.notas_descartadas.insert_one({"_id": _oid(0)})
    b.corridas.insert_many([
        {"tipo": "scraping", "estado": "ok", "creada": _hace(0).isoformat(),
         "inicio": _hace(0).isoformat(), "fin": (_hace(0) + datetime.timedelta(seconds=90)).isoformat()},
        {"tipo": "scraping", "estado": "error", "creada": _hace(1).isoformat()},
        {"tipo": "generacion", "estado": "cancelada", "creada": _hace(3).isoformat()},
        {"tipo": "script", "estado": "ok", "creada": _hace(0).isoformat()},   # no es scraping ni nota
    ])
    b.consumo_ia.insert_many([
        {"fecha": _hace(0).isoformat(), "mes": AHORA.strftime("%Y-%m"), "tarea": "redaccion", "costo_usd": 0.25},
        {"fecha": _hace(0).isoformat(), "mes": AHORA.strftime("%Y-%m"), "tarea": "clasificacion", "costo_usd": 0.05},
    ])
    return b


def test_series_diarias_terminan_hoy_y_cuentan_por_dia(base):
    r = metricas.resumen(14, base=base)
    assert len(r["dias"]) == 14 and r["dias"][-1] == datetime.datetime.now(metricas.ZONA).date().isoformat()
    a = r["articulos"]
    assert sum(a["guardados"]) == 3            # el de hace 20 días queda afuera de la serie
    assert sum(a["descartados"]) == 2          # el reescrito hoy cuenta por fecha_descarte
    assert r["notas"]["escritas"][-1] + r["notas"]["escritas"][-2] == 2
    assert sum(r["notas"]["descartadas"]) == 1


def test_fuentes_agrupan_por_sitio_en_30_dias(base):
    fuentes = {f["sitio"]: f for f in metricas.resumen(14, base=base)["articulos"]["fuentes"]}
    assert fuentes["sitio-a.com"] == {"sitio": "sitio-a.com", "guardados": 2, "descartados": 1}
    assert "sitio-c.com" in fuentes and "sitio-d.com" not in fuentes


def test_calidad_y_estados_de_las_notas(base):
    n = metricas.resumen(14, base=base)["notas"]
    assert n["puntaje_promedio"] == 7.0 and n["intentos_promedio"] == 1.5
    assert n["calificacion_promedio"] == 4.0 and n["calificadas"] == 1
    assert n["estados"]["publicado"] == 1 and n["estados"]["rechazada"] == 0  # la rechazada es de hace 40 días


def test_corridas_por_tipo_con_exito_y_duracion(base):
    c = {x["tipo"]: x for x in metricas.resumen(14, base=base)["corridas"]}
    assert set(c) == {"scraping", "generacion"}
    assert c["scraping"]["ok"] == 1 and c["scraping"]["error"] == 1 and c["scraping"]["exito"] == 0.5
    assert c["scraping"]["duracion_mediana_s"] == 90
    assert c["generacion"]["cancelada"] == 1 and c["generacion"]["exito"] == 0.0


def test_gasto_del_mes_por_tarea(base, monkeypatch):
    monkeypatch.setenv("PAGA_TOPE_MENSUAL_USD", "40")
    g = metricas.resumen(14, base=base)["gasto"]
    assert g["mes_usd"] == 0.3 and g["tope_usd"] == 40.0
    assert list(g["por_tarea"]) == ["redaccion", "clasificacion"]
    assert g["por_dia"][-1] == 0.3


def test_base_vacia_no_falla():
    r = metricas.resumen(7, base=mongomock.MongoClient().db)
    assert r["articulos"]["guardados"] == [0] * 7 and r["articulos"]["fuentes"] == []
    assert r["notas"]["puntaje_promedio"] is None
    assert all(c["exito"] is None for c in r["corridas"])


def test_endpoint_metricas(api, monkeypatch):
    import afterdrive.db as dbm

    monkeypatch.setattr(dbm, "db", mongomock.MongoClient().db)
    c = api[0].app.test_client()
    assert c.post("/api/login", json={"usuario": "admin", "password": "secreta123"}).status_code == 200
    r = c.get("/api/metricas?dias=7")
    assert r.status_code == 200 and r.json["success"] and len(r.json["dias"]) == 7
