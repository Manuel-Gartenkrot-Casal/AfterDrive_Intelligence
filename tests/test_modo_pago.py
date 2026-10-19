"""Tests del modo API paga: un día como máximo, con vencimiento solo y tope mensual."""

import datetime

import pytest

from afterdrive import config_store
from afterdrive.ia import consumo, llm, modo_pago


@pytest.fixture
def paga_configurada(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("PAGA_API_KEY", "pg-key")
    monkeypatch.setenv("PAGA_BASE_URL", "https://api.paga.test/v1")
    monkeypatch.setenv("PAGA_MODEL", "modelo-pago")
    monkeypatch.setenv("PAGA_TOPE_MENSUAL_USD", "40")


@pytest.fixture
def store(monkeypatch):
    """La config de Mongo en un dict."""
    datos = {}
    monkeypatch.setattr(config_store, "_get_section", lambda key, defaults: {**defaults, **datos.get(key, {})})
    monkeypatch.setattr(config_store, "_set_section", lambda key, value: datos.__setitem__(key, value))
    return datos


@pytest.fixture
def reloj(monkeypatch):
    """Hora controlable del modo pago."""
    ahora = {"t": datetime.datetime(2026, 10, 19, 12, 0, tzinfo=datetime.UTC)}
    monkeypatch.setattr(modo_pago, "_ahora", lambda: ahora["t"])
    return ahora


def test_activar_usa_la_api_paga_en_todo_el_pipeline(paga_configurada, store, reloj):
    assert llm.proveedor_activo() == "openrouter"
    r = modo_pago.activar()
    assert r["success"] and r["modo_pago_activo"]
    assert llm.proveedor_activo() == "paga"
    assert llm.usa_api_paga()
    assert llm.proveedor_base() == "openrouter"  # la elección de Desarrollador no se pisa
    assert store["modo_pago"]["hasta"] == "2026-10-20T12:00:00+00:00"


def test_vence_solo_al_dia_y_vuelve_al_proveedor_base(paga_configurada, store, reloj):
    modo_pago.activar()
    reloj["t"] += datetime.timedelta(hours=23, minutes=59)
    assert llm.proveedor_activo() == "paga"
    reloj["t"] += datetime.timedelta(minutes=1)
    assert llm.proveedor_activo() == "openrouter"
    assert modo_pago.estado() == {"modo_pago_activo": False, "modo_pago_hasta": "", "modo_pago_restante_s": 0}


def test_prenderlo_de_nuevo_no_extiende_el_dia(paga_configurada, store, reloj):
    modo_pago.activar()
    reloj["t"] += datetime.timedelta(hours=10)
    modo_pago.activar()
    assert modo_pago.hasta() == datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)


def test_desactivar_vuelve_al_proveedor_base(paga_configurada, store, reloj):
    modo_pago.activar()
    assert modo_pago.desactivar()["success"]
    assert llm.proveedor_activo() == "openrouter"
    assert store["modo_pago"]["hasta"] == ""


def test_sin_api_paga_configurada_no_se_prende(paga_configurada, store, monkeypatch):
    monkeypatch.delenv("PAGA_MODEL")
    r = modo_pago.activar()
    assert not r["success"] and "PAGA_MODEL" in r["error"]
    assert llm.proveedor_activo() == "openrouter"


def test_con_el_tope_mensual_alcanzado_no_se_prende(paga_configurada, store, consumo_en_memoria):
    consumo.registrar("redaccion", "modelo-pago", 0, 10_000_000)  # muy por encima de USD 40
    r = modo_pago.activar()
    assert not r["success"] and "tope" in r["error"]
    assert not modo_pago.vigente()


def test_si_falta_la_config_de_la_api_paga_no_cae_a_local(paga_configurada, store, monkeypatch):
    modo_pago.activar()
    monkeypatch.delenv("PAGA_API_KEY")  # p. ej. se borró la key con el modo prendido
    assert llm.proveedor_activo() == "openrouter"


def test_restaurar_retoma_el_modo_vigente_y_descarta_el_vencido(paga_configurada, store, reloj):
    store["modo_pago"] = {"hasta": "2026-10-19T20:00:00+00:00"}
    modo_pago.restaurar()
    assert llm.proveedor_activo() == "paga"
    store["modo_pago"] = {"hasta": "2026-10-19T11:00:00+00:00"}
    modo_pago.restaurar()
    assert llm.proveedor_activo() == "openrouter"


def test_el_ejecutor_de_github_toma_el_modo_pago(paga_configurada, store, reloj, monkeypatch):
    from afterdrive import ejecutor_externo
    monkeypatch.delenv("AI_PROVIDER_OVERRIDE", raising=False)
    store["provider"] = {"provider": "openrouter"}
    store["modo_pago"] = {"hasta": "2026-10-19T20:00:00+00:00"}
    ejecutor_externo._proveedor_guardado()
    assert llm.proveedor_activo() == "paga"


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(api, paga_configurada, monkeypatch):
    flask_api, store = api
    # estado() pregunta si LM Studio responde: en tests, que no.
    monkeypatch.setattr(llm, "_transporte", {**llm._transporte, "get": _sin_red})
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c, store


def _sin_red(*a, **k):
    raise ConnectionError("sin red en tests")


def test_api_prende_y_apaga_el_modo_pago(client):
    c, store = client
    r = c.post("/api/modo-pago", json={"activo": True})
    assert r.status_code == 200 and r.json["modo_pago_activo"] and r.json["provider"] == "paga"
    assert r.json["provider_base"] == "openrouter"
    assert 0 < r.json["modo_pago_restante_s"] <= 86400
    assert c.get("/api/providers").json["modo_pago_activo"]
    r = c.post("/api/modo-pago", json={"activo": False})
    assert r.status_code == 200 and not r.json["modo_pago_activo"] and r.json["provider"] == "openrouter"


@pytest.mark.parametrize("body", [{}, {"activo": "si"}, {"activo": 1}])
def test_api_modo_pago_exige_un_booleano(client, body):
    c, store = client
    assert c.post("/api/modo-pago", json=body).status_code == 400
    assert "modo_pago" not in store


def test_api_modo_pago_exige_sesion(api, paga_configurada):
    flask_api, store = api
    assert flask_api.app.test_client().post("/api/modo-pago", json={"activo": True}).status_code == 401
    assert "modo_pago" not in store


def test_elegir_otro_proveedor_a_mano_apaga_el_modo_pago(client, monkeypatch):
    c, store = client
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-key")
    c.post("/api/modo-pago", json={"activo": True})
    r = c.post("/api/providers", json={"provider": "nvidia"})
    assert r.status_code == 200 and r.json["provider"] == "nvidia" and not r.json["modo_pago_activo"]
    assert store["modo_pago"]["hasta"] == ""
