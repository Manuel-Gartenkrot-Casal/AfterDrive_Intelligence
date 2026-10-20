"""
consumo.py — Tokens de cada llamada a la IA y lo que gasta la API paga (tope mensual).

Interfaz:
    registrar(tarea, modelo, tokens_entrada, tokens_salida, estimado=False,
              proveedor="paga", truncado=False, max_tokens=None) -> float (USD)
    medir() -> Medicion        context manager: suma lo que se gasta adentro (el costo de una nota)
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

import contextlib
import datetime
import os
import threading
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
    "planificacion": "PAGA_MODEL_PLANIFICACION",
    "correccion": "PAGA_MODEL_CORRECCION",
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


class Medicion:
    """Lo que se gastó dentro de un `with medir()`: total, por tarea y cantidad de llamadas."""

    def __init__(self):
        self.por_tarea: dict[str, float] = {}
        self.llamadas = 0
        self.estimado = False

    def sumar(self, tarea: str, costo: float, estimado: bool) -> None:
        self.por_tarea[tarea] = self.por_tarea.get(tarea, 0.0) + costo
        self.llamadas += 1
        self.estimado |= estimado

    @property
    def total(self) -> float:
        return sum(self.por_tarea.values())

    def como_dict(self) -> dict:
        return {"total_usd": round(self.total, 4), "por_tarea": {k: round(v, 4) for k, v in self.por_tarea.items()},
                "llamadas": self.llamadas, "estimado": self.estimado}


# Por thread: cada Corrida corre en el suyo y no suma lo de otra.
_medidores = threading.local()


@contextlib.contextmanager
def medir():
    """Mide lo que gastan las llamadas pagas hechas en este thread dentro del bloque."""
    m = Medicion()
    activos = getattr(_medidores, "activos", None)
    if activos is None:
        activos = _medidores.activos = []
    activos.append(m)
    try:
        yield m
    finally:
        activos.remove(m)


def registrar(tarea: str, modelo: str, tokens_entrada: int, tokens_salida: int, estimado: bool = False, *,
              proveedor: str = "paga", truncado: bool = False, max_tokens: int | None = None) -> float:
    """Guarda una llamada a la IA y devuelve su costo en USD. Nunca lanza.

    Se registran las llamadas de todos los proveedores para ver cuántos tokens
    consume cada una; solo las de la API paga tienen costo y cuentan para el tope.

    estimado=True: el proveedor no informó tokens (timeout, stream cortado) y
    se cuenta una estimación por lo alto.
    truncado=True: la respuesta se cortó al llegar a max_tokens (el límite de
    salida de esa llamada).
    """
    pago = proveedor == "paga"
    if pago:
        entrada, salida = precio_de_modelo(modelo)
        costo = (tokens_entrada * entrada + tokens_salida * salida) / 1_000_000
    else:
        costo = 0.0
    ahora = datetime.datetime.now(datetime.UTC)
    _imprimir(tarea, proveedor, tokens_entrada, tokens_salida, max_tokens, truncado, estimado, costo if pago else None)
    try:
        _coleccion().insert_one({
            "fecha": ahora.isoformat(), "mes": ahora.strftime("%Y-%m"), "tarea": tarea or "general",
            "proveedor": proveedor, "modelo": modelo, "tokens_entrada": tokens_entrada, "tokens_salida": tokens_salida,
            "max_tokens": max_tokens, "truncado": truncado, "costo_usd": costo, "estimado": estimado,
        })
        if pago and _cache.get("mes") == _mes() and _cache.get("total") is not None:
            _cache["total"] += costo
    except Exception as e:
        if not pago:
            print(f"[CONSUMO] No se pudo registrar el consumo de tokens ({e}).", flush=True)
            return costo
        # La llamada ya se pagó: si no se puede guardar, se sigue sumando en
        # memoria para que el tope la vea mientras viva este proceso.
        # ponytail: se pierde si el proceso se reinicia antes de que Mongo vuelva.
        _sin_registrar[_mes()] = _sin_registrar.get(_mes(), 0.0) + costo
        print(f"[CONSUMO] No se pudo registrar el consumo ({e}); se suma en memoria.", flush=True)
    if pago:
        for m in getattr(_medidores, "activos", []):
            m.sumar(tarea or "general", costo, estimado)
    return costo


def _imprimir(tarea, proveedor, entrada, salida, max_tokens, truncado, estimado, costo) -> None:
    """Una línea por llamada en la consola (y en el log de la Corrida)."""
    aprox = "≈" if estimado else ""
    linea = (f"  [TOKENS] {tarea or 'general'} · {proveedor} · entrada {aprox}{entrada} · salida {aprox}{salida}"
             f" · total {aprox}{entrada + salida}")
    if max_tokens:
        linea += f" (límite de salida {max_tokens})"
    if truncado:
        linea += " · CORTADA POR EL LÍMITE"
    if costo is not None:
        linea += f" · USD {costo:.4f}"
    print(linea, flush=True)


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
