"""
modo_pago.py — Modo API paga: todo el pipeline usa la API paga por un día como máximo.

Interfaz:
    vigente() -> bool              True mientras no venció
    hasta() -> datetime | None     cuándo vence (UTC), o None si no está vigente
    activar() -> dict              lo prende por DURACION; valida que se pueda pagar
    desactivar() -> dict           lo apaga ya
    restaurar() -> None            al arrancar: retoma el que estaba prendido en Mongo
    estado() -> dict               para el dashboard

Se prende desde la vista Cliente. Un día alcanza para una Corrida programada
completa (scraping + generación) más las notas y scrapings que pida el usuario
en ese tiempo. Al vencer, el pipeline vuelve solo al proveedor elegido en la
vista Desarrollador: no hace falta que nadie lo apague.

El vencimiento vive en la variable de entorno MODO_PAGO_HASTA y llm.py la mira
en cada llamada, sin ir a Mongo: así lo ven también los subprocesos (heredan
os.environ) y el corte es exacto aunque una Corrida esté a mitad. Mongo lo
guarda para que sobreviva reinicios y para que lo lean las Corridas de GitHub
Actions (ver ejecutor_externo.py).

El tope mensual de consumo sigue mandando: si se alcanza con el modo prendido,
el chat pasa a NVIDIA igual que con la API paga elegida a mano.
"""

from __future__ import annotations

import datetime
import os

VARIABLE = "MODO_PAGO_HASTA"
DURACION = datetime.timedelta(days=1)


def _ahora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _leer(crudo: str) -> datetime.datetime | None:
    try:
        valor = datetime.datetime.fromisoformat(crudo.strip())
    except ValueError:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=datetime.UTC)


def hasta() -> datetime.datetime | None:
    """Vencimiento del modo pago, o None si está apagado o ya venció."""
    valor = _leer(os.getenv(VARIABLE, ""))
    if valor is None or valor <= _ahora():
        return None
    return valor


def vigente() -> bool:
    return hasta() is not None


def _aplicar(valor: datetime.datetime | None) -> None:
    if valor is None:
        os.environ.pop(VARIABLE, None)
    else:
        os.environ[VARIABLE] = valor.isoformat()


def _guardar(valor: datetime.datetime | None) -> None:
    from afterdrive import config_store
    config_store.set_modo_pago_config(valor.isoformat() if valor else "")


def activar() -> dict:
    """Prende el modo pago por DURACION, si la API paga está configurada y bajo el tope.

    Prenderlo de nuevo con el modo vigente no lo extiende: el máximo es un día
    desde que se prendió.
    """
    from afterdrive.ia import consumo, llm

    if vigente():
        return {"success": True, **estado()}
    if not llm.paga_configurada("PAGA_MODEL"):
        return {"success": False, "error": "La API paga no está configurada en el servidor "
                                           "(faltan PAGA_API_KEY, PAGA_BASE_URL o PAGA_MODEL)."}
    if motivo := consumo.motivo_tope():
        return {"success": False, "error": f"No se puede usar la API paga: {motivo}."}
    valor = _ahora() + DURACION
    try:
        _guardar(valor)
    except Exception as e:
        # Sin guardarlo, un reinicio lo apagaría en silencio y GitHub Actions no lo vería.
        return {"success": False, "error": f"No se pudo guardar el modo pago: {e}"}
    _aplicar(valor)
    print(f"[MODO PAGO] Activado hasta {valor.isoformat()}.", flush=True)
    return {"success": True, **estado()}


def desactivar() -> dict:
    _aplicar(None)
    try:
        _guardar(None)
    except Exception as e:
        print(f"[MODO PAGO] Apagado en este proceso, pero no se pudo guardar: {e}", flush=True)
        return {"success": False, "error": f"Se apagó, pero no se pudo guardar el cambio: {e}", **estado()}
    print("[MODO PAGO] Desactivado.", flush=True)
    return {"success": True, **estado()}


def restaurar() -> None:
    """Toma el modo pago guardado en Mongo (si sigue vigente). Nunca lanza."""
    from afterdrive import config_store
    try:
        valor = _leer(config_store.get_modo_pago_config().get("hasta") or "")
    except Exception as e:
        print(f"[MODO PAGO] No se pudo leer el modo pago guardado: {e}", flush=True)
        return
    _aplicar(valor if valor and valor > _ahora() else None)


def estado() -> dict:
    fin = hasta()
    return {
        "modo_pago_activo": fin is not None,
        "modo_pago_hasta": fin.isoformat() if fin else "",
        "modo_pago_restante_s": int((fin - _ahora()).total_seconds()) if fin else 0,
    }
