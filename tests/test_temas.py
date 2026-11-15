"""Lista de temas para las próximas notas: se pega o importa, se usa y se descarta."""

import pytest

from afterdrive import config_store
from afterdrive.generacion import generar_nota_fase2 as g


@pytest.fixture
def client(api):
    flask_api, store = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c, store


def test_pegar_texto_limpia_vinetas_vacios_y_repetidos(client):
    c, store = client
    texto = "- Neumáticos en verano\r\n\n  2) Autopartes en Mercado Libre \n• Neumáticos en verano\n1.6 turbo vs 2.0\n-5 °C y baterías\n"
    r = c.post("/api/fase2/temas", json={"texto": texto})
    assert r.status_code == 200
    esperado = ["Neumáticos en verano", "Autopartes en Mercado Libre", "1.6 turbo vs 2.0", "-5 °C y baterías"]
    assert r.json["temas"] == esperado
    assert store["temas"]["lista"] == esperado
    assert c.get("/api/fase2/temas").json["temas"] == esperado


@pytest.mark.parametrize("body", [{}, {"texto": 5}, {"texto": "x" * 301}, {"texto": "\n".join(f"t{i}" for i in range(201))},
                                  {"texto": "\n".join(f"t{i}" for i in range(50_000))}])
def test_texto_invalido_da_400_y_no_guarda(client, body):
    c, store = client
    assert c.post("/api/fase2/temas", json=body).status_code == 400
    assert "temas" not in store


@pytest.fixture
def nota(api, monkeypatch):
    """Lo que recibió _generar_nota como tema; el resultado se controla con `nota['ok']`."""
    estado = {"ok": True, "tema": "sin llamar"}

    def falso(categorias, clientes_ids, puntapie_url, persona, tema, *a, **k):
        estado["tema"] = tema
        return {"success": estado["ok"]}

    monkeypatch.setattr(g, "_generar_nota", falso)
    config_store.set_temas(["Primero", "Segundo"])
    return estado


def test_sin_tema_usa_el_primero_y_lo_descarta(nota):
    g.generar_nota(["autopartes"])
    assert nota["tema"] == "Primero"
    assert config_store.get_temas() == ["Segundo"]


def test_si_la_nota_falla_el_tema_queda(nota):
    nota["ok"] = False
    g.generar_nota(["autopartes"])
    assert nota["tema"] == "Primero"
    assert config_store.get_temas() == ["Primero", "Segundo"]


def test_si_falla_el_descarte_la_nota_sigue_bien(nota, monkeypatch):
    def roto(_):
        raise RuntimeError("Mongo caído")
    monkeypatch.setattr(config_store, "descartar_tema", roto)
    assert g.generar_nota(["autopartes"])["success"] is True


def test_con_tema_puntual_no_toca_la_lista(nota):
    g.generar_nota(["autopartes"], tema="Otro")
    assert nota["tema"] == "Otro"
    assert config_store.get_temas() == ["Primero", "Segundo"]
