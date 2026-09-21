"""config_store.py — Persistencia de configuración del sistema en MongoDB.

Todo lo que el usuario toca en el dashboard (toggles, intervalos, proveedor)
se guarda en la colección `config` para que sobreviva reinicios y redeploys
de Render. Sin esto, cualquier cambio se perdía al arrancar de nuevo.

Formato: un documento por sección, clave `key`, valor en `value`.
"""

import datetime

from db import db

_col = db["config"]

# ── Valores por defecto ───────────────────────────────────────────────────────

DEFAULT_SCRAPING = {
    "enabled": True,
    "interval_days": 1,
    "max_articulos": 10,
}

DEFAULT_GENERACION = {
    "enabled": True,
    "interval_days": 1,
    "persona": "comercial",
    "tema": "",
    "puntapie_url": "",
}

DEFAULT_FASE2 = {
    "categorias": [],
    "regiones": [],
    "clientes": [],
    "puntapie_activo": False,
    "puntapie_url": "",
}

DEFAULT_PROVIDER = {
    "provider": "openrouter",
}


def _get_section(key: str, defaults: dict) -> dict:
    doc = _col.find_one({"key": key})
    value = doc.get("value") if doc else None
    merged = dict(defaults)
    if isinstance(value, dict):
        merged.update({k: v for k, v in value.items() if v is not None})
    return merged


def _set_section(key: str, value: dict):
    _col.replace_one(
        {"key": key},
        {"key": key, "value": value, "updated_at": datetime.datetime.now(datetime.UTC).isoformat()},
        upsert=True,
    )


# ── Scraping ──────────────────────────────────────────────────────────────────


def get_scraping_config() -> dict:
    return _get_section("scraping", DEFAULT_SCRAPING)


def set_scraping_config(enabled: bool | None = None, interval_days: int | None = None, max_articulos: int | None = None):
    cfg = get_scraping_config()
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if interval_days is not None:
        cfg["interval_days"] = max(1, int(interval_days))
    if max_articulos is not None:
        cfg["max_articulos"] = max(1, int(max_articulos))
    _set_section("scraping", cfg)
    return cfg


# ── Generación automática ─────────────────────────────────────────────────────


def get_generacion_config() -> dict:
    return _get_section("generacion", DEFAULT_GENERACION)


def set_generacion_config(
    enabled: bool | None = None,
    interval_days: int | None = None,
    persona: str | None = None,
    tema: str | None = None,
    puntapie_url: str | None = None,
):
    cfg = get_generacion_config()
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if interval_days is not None:
        cfg["interval_days"] = max(1, int(interval_days))
    if persona is not None:
        cfg["persona"] = persona
    if tema is not None:
        cfg["tema"] = tema
    if puntapie_url is not None:
        cfg["puntapie_url"] = puntapie_url
    _set_section("generacion", cfg)
    return cfg


# ── Toggles de Fase 2 ─────────────────────────────────────────────────────────


def get_fase2_config() -> dict:
    return _get_section("fase2", DEFAULT_FASE2)


def set_fase2_config(
    categorias: list[str] | None = None,
    regiones: list[str] | None = None,
    clientes: list[str] | None = None,
    puntapie_activo: bool | None = None,
    puntapie_url: str | None = None,
):
    cfg = get_fase2_config()
    if categorias is not None:
        cfg["categorias"] = categorias
    if regiones is not None:
        cfg["regiones"] = regiones
    if clientes is not None:
        cfg["clientes"] = clientes
    if puntapie_activo is not None:
        cfg["puntapie_activo"] = bool(puntapie_activo)
    if puntapie_url is not None:
        cfg["puntapie_url"] = puntapie_url
    _set_section("fase2", cfg)
    return cfg


# ── Proveedor de IA ───────────────────────────────────────────────────────────


def get_provider_config() -> str:
    return _get_section("provider", DEFAULT_PROVIDER)["provider"]


def set_provider_config(provider: str):
    _set_section("provider", {"provider": provider})