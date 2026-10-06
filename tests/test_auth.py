"""Tests del login: guardia de sesión, bloqueo por intentos y token de cron."""

import pytest

OK = {"usuario": "admin", "password": "secreta123"}
MALA = {"usuario": "admin", "password": "mala"}


def test_sin_sesion_es_401(api):
    c = api[0].app.test_client()
    r = c.get("/api/scraping-config")
    assert r.status_code == 401 and r.json == {"success": False, "error": "No autenticado"}
    assert c.post("/api/fase2/clientes", json={"nombre": "x"}).status_code == 401
    assert c.get("/ruta-que-no-existe").status_code == 401


def test_health_abierto(api):
    assert api[0].app.test_client().get("/health").status_code == 200


def test_login_abre_sesion_y_logout_la_cierra(api):
    c = api[0].app.test_client()
    r = c.post("/api/login", json=OK)
    assert r.status_code == 200 and r.json == {"success": True}
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert c.get("/api/scraping-config").status_code == 200
    assert c.post("/api/logout").status_code == 200
    assert c.get("/api/scraping-config").status_code == 401


@pytest.mark.parametrize("body", [
    MALA,
    {"usuario": "otro", "password": "secreta123"},
    {},
    {"usuario": None, "password": 5},
    {"usuario": {"$ne": ""}, "password": ["x"]},
    ["admin", "secreta123"],
])
def test_credenciales_malas_son_401(api, body):
    assert api[0].app.test_client().post("/api/login", json=body).status_code == 401


def test_body_no_json_es_401(api):
    assert api[0].app.test_client().post("/api/login", data="hola").status_code == 401


def test_bloqueo_al_quinto_fallo_y_vence(api, monkeypatch):
    from afterdrive import auth
    reloj = [1000.0]
    monkeypatch.setattr(auth, "_ahora", lambda: reloj[0])
    c = api[0].app.test_client()
    for _ in range(5):
        assert c.post("/api/login", json=MALA).status_code == 401
    assert c.post("/api/login", json=OK).status_code == 429
    reloj[0] += 901
    assert c.post("/api/login", json=OK).status_code == 200


def test_login_correcto_limpia_fallos(api):
    c = api[0].app.test_client()
    for _ in range(4):
        c.post("/api/login", json=MALA)
    assert c.post("/api/login", json=OK).status_code == 200
    c.post("/api/logout")
    for _ in range(4):
        assert c.post("/api/login", json=MALA).status_code == 401


@pytest.mark.parametrize("falta", ["ADMIN_USER", "ADMIN_PASSWORD_HASH", "SECRET_KEY"])
def test_sin_configuracion_es_503_y_sigue_cerrado(api, monkeypatch, falta):
    fa = api[0]
    c = fa.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    # SECRET_KEY vive en app.config; las otras dos en el entorno.
    if falta == "SECRET_KEY":
        monkeypatch.setitem(fa.app.config, "SECRET_KEY", None)
    else:
        monkeypatch.delenv(falta)
    assert c.post("/api/login", json=OK).status_code == 503
    assert c.get("/api/scraping-config").status_code == 401


def test_hash_mal_formado_es_401(api, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "secreta123")
    assert api[0].app.test_client().post("/api/login", json=OK).status_code == 401


def test_cron_token_solo_en_sus_dos_endpoints(api, monkeypatch):
    fa = api[0]
    monkeypatch.setattr(fa.corridas, "en_segundo_plano", lambda *a: None)
    c, h = fa.app.test_client(), {"Authorization": "Bearer cron-test"}
    assert c.post("/api/run-automation", headers=h).status_code == 200
    assert c.post("/api/run-generacion", headers=h).status_code == 200
    assert c.get("/api/scraping-config", headers=h).status_code == 401
    assert c.post("/api/run-automation", headers={"Authorization": "Bearer otro"}).status_code == 401


def test_sin_cron_token_ningun_bearer_vale(api, monkeypatch):
    monkeypatch.delenv("CRON_TOKEN")
    r = api[0].app.test_client().post("/api/run-automation", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_hash_entre_comillas_simples_sobrevive_a_dotenv(tmp_path):
    from dotenv import dotenv_values
    from werkzeug.security import generate_password_hash
    h = generate_password_hash("x")
    (tmp_path / ".env").write_text(f"ADMIN_PASSWORD_HASH='{h}'\n")
    assert dotenv_values(tmp_path / ".env")["ADMIN_PASSWORD_HASH"] == h
