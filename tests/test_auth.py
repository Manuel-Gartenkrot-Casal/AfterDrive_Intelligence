"""Tests del login: guardia de sesión, bloqueo por intentos y token de cron."""

from pathlib import Path

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


def test_raiz_sirve_login_o_dashboard_segun_sesion(api, monkeypatch, tmp_path):
    (tmp_path / "login.html").write_text("PANTALLA-LOGIN")
    (tmp_path / "index.html").write_text("PANTALLA-DASHBOARD")
    monkeypatch.setattr(api[0], "_STATIC_DIR", str(tmp_path))
    c = api[0].app.test_client()
    r = c.get("/")
    assert b"PANTALLA-LOGIN" in r.data and r.headers["Cache-Control"] == "no-store"
    c.post("/api/login", json=OK)
    r = c.get("/")
    assert b"PANTALLA-DASHBOARD" in r.data and r.headers["Cache-Control"] == "no-store"


def test_la_pantalla_de_login_existe_y_usa_el_endpoint():
    html = Path("express/src/public/login.html").read_text(encoding="utf-8")
    assert "/api/login" in html and 'type="password"' in html


def test_sin_build_el_dashboard_sale_de_la_fuente(api):
    # En local no hay carpeta static/ (la genera el Dockerfile): se sirve la fuente.
    assert api[0]._STATIC_DIR.replace("\\", "/").endswith(("/static", "express/src/public"))
    c = api[0].app.test_client()
    assert b"<form" in c.get("/").data


def test_cabeceras_de_seguridad(api, monkeypatch):
    c = api[0].app.test_client()
    h = c.get("/health").headers
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "same-origin" and "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in h and "Access-Control-Allow-Origin" not in h
    monkeypatch.setenv("RENDER", "true")
    assert c.get("/health").headers["Strict-Transport-Security"] == "max-age=31536000"


def test_cabeceras_tambien_en_el_401(api):
    h = api[0].app.test_client().get("/api/scraping-config").headers
    assert h["X-Frame-Options"] == "DENY" and "Content-Security-Policy" in h
