"""Fixtures compartidos: la API de Flask con config en memoria y login configurado."""

import pytest
from werkzeug.security import generate_password_hash

from afterdrive import config_store

# scrypt es lento a propósito: se calcula una vez para toda la sesión de tests.
HASH = generate_password_hash("secreta123")


@pytest.fixture
def api(monkeypatch):
    """(flask_api, store): la app sin Mongo ni scheduler, con usuario admin / secreta123."""
    store = {}

    def get_section(key, defaults):
        return {**defaults, **store.get(key, {})}

    monkeypatch.setattr(config_store, "_get_section", get_section)
    monkeypatch.setattr(config_store, "_set_section", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setenv("AI_PROVIDER_OVERRIDE", "1")
    from afterdrive import scheduler
    # Importar flask_api arranca el scheduler (modo gunicorn): en tests no.
    monkeypatch.setattr(scheduler, "iniciar", lambda: None)
    monkeypatch.setattr(scheduler, "aplicar", lambda: None)
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", HASH)
    monkeypatch.setenv("CRON_TOKEN", "cron-test")
    monkeypatch.delenv("RENDER", raising=False)
    from afterdrive import auth, flask_api
    monkeypatch.setitem(flask_api.app.config, "SECRET_KEY", "clave-de-test")
    auth._fallos.clear()
    return flask_api, store
