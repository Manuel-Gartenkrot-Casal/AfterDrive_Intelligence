"""config_store.py — Persistencia de configuración del sistema en MongoDB.

Todo lo que el usuario toca en el dashboard (toggles, intervalos, proveedor)
se guarda en la colección `config` para que sobreviva reinicios y redeploys
de Render. Sin esto, cualquier cambio se perdía al arrancar de nuevo.

Formato: un documento por sección, clave `key`, valor en `value`.
"""

import datetime

from afterdrive.db import db

_col = db["config"]

# ── Valores por defecto ───────────────────────────────────────────────────────

# Horas en la zona del scheduler (Argentina). 05:30 y 11:00 = 08:30 y 14:00
# UTC, los horarios fijos que había antes de hacerlos configurables.
DEFAULT_SCRAPING = {
    "enabled": True,
    "hora": "05:30",
    "interval_days": 1,
    "max_articulos": 10,
}

DEFAULT_GENERACION = {
    "enabled": True,
    "hora": "11:00",
    "interval_days": 1,
    "persona": "comercial",
    "largo": "medio",
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
    try:
        doc = _col.find_one({"key": key})
    except Exception as e:
        # Sin Mongo el sistema sigue con los defaults en vez de no arrancar.
        print(f"[config_store] No se pudo leer '{key}', usando defaults: {e}", flush=True)
        doc = None
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


# ── Ejecutor externo (GitHub Actions) ─────────────────────────────────────────


def get_ejecutor_externo() -> dict:
    """{tipo: iso} de la última vez que GitHub Actions revisó qué tocaba correr."""
    return _get_section("ejecutor_externo", {})


def set_ejecutor_externo(revisado: dict) -> None:
    _set_section("ejecutor_externo", revisado)


# ── Scraping ──────────────────────────────────────────────────────────────────


def get_scraping_config() -> dict:
    return _get_section("scraping", DEFAULT_SCRAPING)


def set_scraping_config(
    enabled: bool | None = None,
    interval_days: int | None = None,
    max_articulos: int | None = None,
    hora: str | None = None,
):
    cfg = get_scraping_config()
    if hora is not None:
        cfg["hora"] = hora
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
    hora: str | None = None,
    largo: str | None = None,
):
    cfg = get_generacion_config()
    if largo is not None:
        cfg["largo"] = largo
    if hora is not None:
        cfg["hora"] = hora
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


# ── Modo API paga (vista Cliente) ─────────────────────────────────────────────

DEFAULT_MODO_PAGO = {"hasta": ""}  # ISO UTC; vacío = apagado. Ver afterdrive/ia/modo_pago.py


def get_modo_pago_config() -> dict:
    return _get_section("modo_pago", DEFAULT_MODO_PAGO)


def set_modo_pago_config(hasta: str):
    _set_section("modo_pago", {"hasta": hasta})


# ── Blog de pruebas de HubSpot (vista Desarrollador) ──────────────────────────

# Prendido = los borradores van al blog de HUBSPOT_BLOG_PRUEBAS (si está cargado).
DEFAULT_BLOG_PRUEBAS = {"activo": True}


def get_blog_pruebas_config() -> bool:
    return bool(_get_section("blog_pruebas", DEFAULT_BLOG_PRUEBAS)["activo"])


def set_blog_pruebas_config(activo: bool):
    _set_section("blog_pruebas", {"activo": bool(activo)})


# ── Aprobación automática (vista Desarrollador) ───────────────────────────────

# Prendido = las notas de la generación programada que pasan el filtro y el
# juez se aprueban solas y suben a HubSpot como borrador. Ver aprobacion_auto.py
DEFAULT_APROBACION_AUTO = {"activo": False}


def get_aprobacion_auto_config() -> bool:
    return bool(_get_section("aprobacion_auto", DEFAULT_APROBACION_AUTO)["activo"])


def set_aprobacion_auto_config(activo: bool):
    _set_section("aprobacion_auto", {"activo": bool(activo)})
