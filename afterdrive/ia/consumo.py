"""
consumo.py — Lo que gasta la API paga: un registro por llamada y el tope mensual.

Interfaz:
    registrar(tarea, modelo, tokens_entrada, tokens_salida, estimado=False) -> float (USD)
    precio_de_modelo(modelo) -> (entrada, salida)
    gastado_mes() -> float
    tope() -> float
    motivo_tope() -> str | None      None = se puede usar la API paga

El proveedor no devuelve dólares, solo tokens: el costo sale del precio por 1M
de tokens del modelo que contestó. Los modelos son ids opacos (ARNs), así que
el precio se busca por la variable que lo nombra: el modelo de
PAGA_MODEL_<TAREA> cobra PAGA_PRECIO_<TAREA>, el de PAGA_FALLBACK_MODEL cobra
PAGA_PRECIO_FALLBACK, etc. Un modelo que no aparece en ninguna variable se
cobra al precio más alto: ante la duda, se sobreestima.

El razonamiento viene incluido en los tokens de salida y se cobra como tal.
El registro vive en Mongo (colección consumo_ia): lo comparten Render y las
corridas de GitHub Actions.
"""

from __future__ import annotations

import datetime
import os
import time

# USD por 1M de tokens (entrada, salida), ruta US de Bedrock, medidos el
# 2026-10-18, para el reparto recomendado: clasificación GPT-6 Luna,
# evaluación GPT-5.6 Luna, redacción Kimi K3. Otro reparto => cargar
# PAGA_PRECIO_<TAREA>.
PRECIOS_DEFAULT = {
    "clasificacion": (0.11, 0.55),
    "evaluacion": (0.22, 1.32),
    "redaccion": (3.30, 16.50),
}
_PRECIO_MAXIMO = max(PRECIOS_DEFAULT.values())

# clave de precio -> variable de entorno que nombra el modelo
_VARIABLES = {
    "clasificacion": "PAGA_MODEL_CLASIFICACION",
    "evaluacion": "PAGA_MODEL_EVALUACION",
    "redaccion": "PAGA_MODEL_REDACCION",
    "general": "PAGA_MODEL",
    "fallback": "PAGA_FALLBACK_MODEL",
    "embeddings": "PAGA_EMB_MODEL",
}

_VIGENCIA_S = 60  # el total del mes se relee de Mongo como mucho una vez por minuto
_cache: dict = {}  # {"mes": "YYYY-MM", "total": float | None (None = no se pudo leer), "t": monotonic}
_sin_registrar: dict = {}  # mes -> USD gastados que no se pudieron guardar en Mongo (este proceso)
_reloj = time.monotonic  # seam para los tests


def _coleccion():
    from afterdrive.db import db
    return db["consumo_ia"]


def _mes() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m")


def tope() -> float:
    try:
        return float(os.getenv("PAGA_TOPE_MENSUAL_USD", "40"))
    except ValueError:
        return 40.0


def _precio(clave: str) -> tuple[float, float]:
    crudo = os.getenv(f"PAGA_PRECIO_{clave.upper()}", "")
    try:
        entrada, salida = (float(x) for x in crudo.split("/"))
        return entrada, salida
    except ValueError:
        return PRECIOS_DEFAULT.get(clave, _PRECIO_MAXIMO)


def precio_de_modelo(modelo: str) -> tuple[float, float]:
    """(entrada, salida) en USD por 1M de tokens del modelo que contestó."""
    for clave, variable in _VARIABLES.items():
        if modelo and os.getenv(variable, "").strip() == modelo:
            return _precio(clave)
    return _PRECIO_MAXIMO


def registrar(tarea: str, modelo: str, tokens_entrada: int, tokens_salida: int, estimado: bool = False) -> float:
    """Guarda una llamada paga y devuelve su costo en USD. Nunca lanza.

    estimado=True: el proveedor no informó tokens (timeout, stream cortado) y
    se cuenta una estimación por lo alto.
    """
    entrada, salida = precio_de_modelo(modelo)
    costo = (tokens_entrada * entrada + tokens_salida * salida) / 1_000_000
    ahora = datetime.datetime.now(datetime.UTC)
    try:
        _coleccion().insert_one({
            "fecha": ahora.isoformat(), "mes": ahora.strftime("%Y-%m"), "tarea": tarea or "general",
            "modelo": modelo, "tokens_entrada": tokens_entrada, "tokens_salida": tokens_salida,
            "costo_usd": costo, "estimado": estimado,
        })
        if _cache.get("mes") == _mes() and _cache.get("total") is not None:
            _cache["total"] += costo
    except Exception as e:
        # La llamada ya se pagó: si no se puede guardar, se sigue sumando en
        # memoria para que el tope la vea mientras viva este proceso.
        # ponytail: se pierde si el proceso se reinicia antes de que Mongo vuelva.
        _sin_registrar[_mes()] = _sin_registrar.get(_mes(), 0.0) + costo
        print(f"[CONSUMO] No se pudo registrar el consumo ({e}); se suma en memoria.", flush=True)
    marca = " (estimado)" if estimado else ""
    print(f"  [CONSUMO] {tarea or 'general'}: {tokens_entrada} + {tokens_salida} tokens = USD {costo:.4f}{marca}",
          flush=True)
    return costo


def _total_mongo(mes: str) -> float | None:
    """Total del mes según Mongo, cacheado; None si no se pudo leer."""
    if _cache.get("mes") == mes and _reloj() - _cache["t"] < _VIGENCIA_S:
        return _cache["total"]
    try:
        filas = list(_coleccion().aggregate([
            {"$match": {"mes": mes}},
            {"$group": {"_id": None, "total": {"$sum": "$costo_usd"}}},
        ]))
        total = filas[0]["total"] if filas else 0.0
    except Exception as e:
        print(f"[CONSUMO] No se pudo leer el consumo del mes ({e}).", flush=True)
        total = None  # el fallo también se cachea: no reintentar Mongo en cada llamada
    _cache.update(mes=mes, total=total, t=_reloj())
    return total


def gastado_mes() -> float:
    """USD gastados en el mes en curso (UTC). Sin registro legible, devuelve el tope."""
    mes = _mes()
    total = _total_mongo(mes)
    if total is None:
        return tope()
    return total + _sin_registrar.get(mes, 0.0)


def motivo_tope() -> str | None:
    """Por qué no usar la API paga ahora, o None si se puede."""
    mes = _mes()
    if _total_mongo(mes) is None:
        return "no se pudo leer el registro de consumo (se asume el tope alcanzado)"
    gastado = gastado_mes()
    if gastado >= tope():
        return f"tope mensual alcanzado (USD {gastado:.2f} de {tope():.2f})"
    return None
