"""Fixtures compartidos: la API de Flask con config en memoria y login configurado."""

import os

import mongomock
import pytest
from werkzeug.security import generate_password_hash

from afterdrive import config_store
from afterdrive.ia import consumo

# scrypt es lento a propósito: se calcula una vez para toda la sesión de tests.
HASH = generate_password_hash("secreta123")


@pytest.fixture(autouse=True)
def consumo_en_memoria(monkeypatch):
    """El registro de consumo de la API paga va a un Mongo en memoria, nunca al real."""
    col = mongomock.MongoClient().db.consumo_ia
    monkeypatch.setattr(consumo, "_coleccion", lambda: col)
    monkeypatch.setattr(consumo, "_cache", {})
    return col


@pytest.fixture(autouse=True)
def sin_buscar_imagenes(monkeypatch):
    """Los tests no descargan páginas de noticias para buscarles la imagen."""
    from afterdrive.generacion import contexto_noticias
    monkeypatch.setattr(contexto_noticias, "_buscar_imagen", lambda n: None)


@pytest.fixture(autouse=True)
def sin_notas_del_blog(monkeypatch):
    """La generación no lee la base real para buscar notas del blog que citar."""
    from afterdrive.generacion import notas_blog
    monkeypatch.setattr(notas_blog, "relacionadas", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def sin_modo_pago(monkeypatch):
    """El modo pago se prende escribiendo os.environ directo: no debe pasar de un test a otro."""
    monkeypatch.delenv("MODO_PAGO_HASTA", raising=False)
    yield
    os.environ.pop("MODO_PAGO_HASTA", None)


@pytest.fixture(autouse=True)
def blog_pruebas_prendido(monkeypatch):
    """El switch del blog de pruebas no se lee de la base real: prendido, como el default."""
    monkeypatch.setattr(config_store, "get_blog_pruebas_config", lambda: True)


@pytest.fixture(autouse=True)
def aprobacion_auto_apagada(monkeypatch):
    """La aprobación automática no se lee de la base real: apagada, como el default."""
    monkeypatch.setattr(config_store, "get_aprobacion_auto_config", lambda: False)


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
