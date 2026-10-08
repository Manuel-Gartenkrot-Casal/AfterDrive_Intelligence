"""Contrato de sesión compartido con Render_Testing, sin Mongo ni proveedores."""
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

import auth


@pytest.fixture
def api(monkeypatch):
    import config_store
    import scheduler
    monkeypatch.setattr(config_store, "get_provider_config", lambda: None)
    monkeypatch.setattr(scheduler, "iniciar", lambda: None)
    monkeypatch.setenv("ADMIN_USER", "editor")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", generate_password_hash("test-only-password"))
    monkeypatch.setenv("CRON_TOKEN", "test-only-cron")
    import flask_api
    monkeypatch.setitem(flask_api.app.config, "SECRET_KEY", "test-only-signing-key")
    monkeypatch.setitem(flask_api.app.config, "SESSION_COOKIE_SECURE", False)
    assets = str(Path("express/src/public").resolve())
    monkeypatch.setattr(flask_api, "_STATIC_DIR", assets)
    monkeypatch.setattr(flask_api.app, "static_folder", assets)
    auth._fallos.clear()
    return flask_api.app.test_client()


def login(client):
    return client.post("/api/login", json={"usuario": "editor", "password": "test-only-password"})


def test_login_logout_y_recursos_protegidos(api):
    assert b"login-form" in api.get("/").data
    for path in ["/api/health", "/api/historial/resumen", "/ultimo-articulo", "/static/index.html", "/static/workspace.js"]:
        assert api.get(path).status_code == 401
    for path in ["/static/login.css", "/static/login.js", "/health"]:
        assert api.get(path).status_code == 200
    response = login(api)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Strict" in response.headers["Set-Cookie"]
    assert b"workspace-main" in api.get("/").data
    assert api.get("/static/session.js").status_code == 200
    assert "Set-Cookie" not in api.get("/api/health").headers
    assert api.post("/api/logout").status_code == 200
    assert api.get("/api/health").status_code == 401
    assert b"login-form" in api.get("/").data


@pytest.mark.parametrize("body", [{}, [], {"usuario": None, "password": 3}, {"usuario": "otro", "password": "bad"}, {"usuario": "editor", "password": "x" * 1025}])
def test_credenciales_invalidas(api, body):
    assert api.post("/api/login", json=body).status_code == 401


def test_bloqueo_y_vencimiento(api, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(auth, "_ahora", lambda: clock[0])
    for _ in range(5):
        assert api.post("/api/login", json={}).status_code == 401
    assert login(api).status_code == 429
    clock[0] += 901
    assert login(api).status_code == 200


@pytest.mark.parametrize("key", ["ADMIN_USER", "ADMIN_PASSWORD_HASH", "SECRET_KEY"])
def test_sin_configuracion_no_hay_acceso(api, monkeypatch, key):
    if key == "SECRET_KEY":
        import flask_api
        monkeypatch.setitem(flask_api.app.config, "SECRET_KEY", None)
    else:
        monkeypatch.delenv(key)
    assert login(api).status_code == 503
    assert api.get("/api/health").status_code == 401
    assert api.get("/health").status_code == 200


def test_sesion_alterada_no_da_acceso(api):
    login(api)
    api.set_cookie("session", "forged.session.value")
    assert api.get("/api/health").status_code == 401


def test_cron_limitado_a_dos_endpoints(api, monkeypatch):
    import flask_api
    monkeypatch.setattr(flask_api.corridas, "en_segundo_plano", lambda *args: None)
    headers = {"Authorization": "Bearer test-only-cron"}
    assert api.post("/api/run-automation", headers=headers).status_code == 200
    assert api.post("/api/run-generacion", headers=headers).status_code == 200
    assert api.get("/api/historial/resumen", headers=headers).status_code == 401
    assert api.post("/api/run-automation", headers={"Authorization": "Bearer incorrecto"}).status_code == 401


def test_no_cache_y_sin_cors_abierto(api):
    for path in ["/", "/api/health", "/health"]:
        headers = api.get(path).headers
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Frame-Options"] == "DENY"
        assert "Access-Control-Allow-Origin" not in headers


def test_cookie_secure_en_render(monkeypatch):
    from flask import Flask
    monkeypatch.setenv("RENDER", "true")
    app = Flask("production-cookie-test")
    auth.init_app(app)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Strict"
