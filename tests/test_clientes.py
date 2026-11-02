"""Tests de las empresas que las notas pueden nombrar y las que no (clientes.py y su API)."""

import mongomock
import pytest

from afterdrive import clientes
from afterdrive import db as db_module


def test_parsear_lista_con_descripcion_alias_y_vinetas():
    texto = """
    - Repuestos del Sur | Distribuidor mayorista en Córdoba
    2. Competidor SA | | CSA, Competidor
    repuestos del sur | repetida
    Solo Nombre
    """
    lista = clientes.parsear_lista(texto)
    assert [c["nombre"] for c in lista] == ["Repuestos del Sur", "Competidor SA", "Solo Nombre"]
    assert lista[0]["descripcion"] == "Distribuidor mayorista en Córdoba" and lista[0]["alias"] == []
    assert lista[1]["descripcion"] == "" and lista[1]["alias"] == ["CSA", "Competidor"]


def test_parsear_lista_acepta_tabulaciones_de_una_planilla():
    assert clientes.parsear_lista("ACME\tFabricante de frenos")[0]["descripcion"] == "Fabricante de frenos"


@pytest.mark.parametrize("texto, esperado", [
    ("Según Frasle, la demanda crece.", ["Frasle"]),
    ("según FRASLE la demanda", ["Frasle"]),
    ("La autopeças São Paulo Peças creció", ["Sao Paulo Pecas"]),   # sin tildes ni mayúsculas
    ("Stanford publicó un estudio", []),                            # palabra entera: Ford no está
    ("El grupo CSA amplió su planta", ["Competidor SA"]),           # por alias
    ("Mercado   Libre suma vendedores", ["Mercado Libre"]),          # espacios flexibles
])
def test_nombrados(texto, esperado):
    lista = [{"nombre": "Frasle"}, {"nombre": "Ford"}, {"nombre": "Sao Paulo Pecas"},
             {"nombre": "Competidor SA", "alias": ["CSA"]}, {"nombre": "Mercado Libre"}]
    assert clientes.nombrados(texto, lista) == esperado


def test_no_mencionar_solo_trae_las_prohibidas():
    col = mongomock.MongoClient().db.clientes
    col.insert_many([{"slug": "a", "nombre": "A"}, {"slug": "b", "nombre": "B", "modo": "no_mencionar"},
                     {"slug": "c", "nombre": "C", "modo": "mencionar"}])
    assert [c["nombre"] for c in clientes.no_mencionar(col)] == ["B"]


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def cliente_api(api, monkeypatch):
    flask_api, store = api
    base = mongomock.MongoClient().db
    monkeypatch.setattr(db_module, "col_clientes", base.clientes)
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c, base.clientes, store


def test_crear_cliente_con_modo(cliente_api):
    c, col, _ = cliente_api
    assert c.post("/api/fase2/clientes", json={"nombre": "Repuestos Núñez"}).json["cliente"]["modo"] == "mencionar"
    r = c.post("/api/fase2/clientes", json={"nombre": "Competidor", "modo": "no_mencionar"})
    assert r.status_code == 200 and col.find_one({"slug": "competidor"})["modo"] == "no_mencionar"
    assert col.find_one({"slug": "repuestos-nunez"})   # slug sin tildes
    assert c.post("/api/fase2/clientes", json={"nombre": "X", "modo": "otro"}).status_code == 400


def test_importar_lista_crea_y_actualiza(cliente_api):
    c, col, _ = cliente_api
    col.insert_one({"slug": "acme", "nombre": "ACME", "descripcion": "vieja", "modo": "mencionar"})
    r = c.post("/api/fase2/clientes/importar",
               json={"texto": "ACME\nCompetidor SA | Rival directo | CSA", "modo": "no_mencionar"})
    assert r.status_code == 200 and r.json["nuevos"] == 1 and r.json["actualizados"] == 1
    acme = col.find_one({"slug": "acme"})
    assert acme["modo"] == "no_mencionar" and acme["descripcion"] == "vieja"   # sin descripción nueva, no se pisa
    assert col.find_one({"slug": "competidor-sa"})["alias"] == ["CSA"]
    assert c.post("/api/fase2/clientes/importar", json={"texto": "  "}).status_code == 400


def test_pasar_a_no_mencionar_lo_saca_de_la_nota_automatica(cliente_api):
    c, col, store = cliente_api
    col.insert_one({"slug": "acme", "nombre": "ACME"})
    store["fase2"] = {"categorias": ["autopartes"], "clientes": ["acme", "otro"]}
    r = c.patch("/api/fase2/clientes/acme", json={"modo": "no_mencionar"})
    assert r.status_code == 200 and col.find_one({"slug": "acme"})["modo"] == "no_mencionar"
    assert store["fase2"]["clientes"] == ["otro"]
    assert c.patch("/api/fase2/clientes/nadie", json={"modo": "mencionar"}).status_code == 404
    assert c.patch("/api/fase2/clientes/acme", json={"modo": "x"}).status_code == 400


def test_las_indicaciones_viajan_al_generador(api):
    flask_api, _ = api
    with flask_api.app.app_context():
        _indicaciones(flask_api)


def _indicaciones(flask_api):
    argv, error = flask_api._argv_generar({"categorias": ["autopartes"], "indicaciones": "  Tono cercano --tema=x  "})
    assert error is None and argv[-1] == "--indicaciones=Tono cercano --tema=x"
    _, error = flask_api._argv_generar({"categorias": ["autopartes"], "indicaciones": "x" * 2001})
    assert error is not None
    _, error = flask_api._argv_generar({"categorias": ["autopartes"], "indicaciones": ["no", "texto"]})
    assert error is not None


def test_editar_una_nota_recalcula_las_empresas_prohibidas():
    from afterdrive import historial
    base = mongomock.MongoClient().db
    base.clientes.insert_one({"slug": "frasle", "nombre": "Frasle", "modo": "no_mencionar"})
    oid = base.notas_fase2.insert_one({"contenido": "# T\n\nTexto.", "estado": "borrador",
                                       "empresas_prohibidas": []}).inserted_id
    cuerpo = "# Título\n\n" + "Frasle amplía su planta y crece la demanda. " * 10
    historial.editar("notas_fase2", str(oid), cuerpo + "\n\n## Fuentes\n\n- [ZF y Frasle](https://n/1)", base=base)
    assert base.notas_fase2.find_one({"_id": oid})["empresas_prohibidas"] == ["Frasle"]
    sin = "# Título\n\n" + "La fabricante amplía su planta y crece la demanda. " * 10
    historial.editar("notas_fase2", str(oid), sin + "\n\n## Fuentes\n\n- [Frasle amplía](https://n/1)", base=base)
    assert base.notas_fase2.find_one({"_id": oid})["empresas_prohibidas"] == []   # en las fuentes no cuenta
