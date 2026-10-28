"""
ejecutor_externo.py — Corre las Corridas programadas fuera de Render (GitHub Actions).

Uso (lo llama .github/workflows/corridas.yml una vez por hora):
    python -m afterdrive.ejecutor_externo --pendientes          imprime los tipos que tocan ahora
    python -m afterdrive.ejecutor_externo --correr scraping generacion   (corre ya, sin mirar la hora)

Lee la MISMA programación que el dashboard (hora, cada cuántos días, activada)
y corre lo que tocaba desde la última vez que se revisó. Así los horarios se
siguen cambiando desde Programación aunque el que ejecuta sea GitHub.

En Render hay que poner CORRIDAS_EXTERNAS=github para que el servidor deje de
programarlas (si no, corren dos veces). Las Corridas quedan registradas en la
colección `corridas`: el panel del dashboard las muestra con su log en vivo.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import zoneinfo

TIPOS = ("scraping", "generacion")
VENTANA_INICIAL = datetime.timedelta(hours=2)   # primera vez: qué tan atrás se mira


def _ahora() -> datetime.datetime:
    from afterdrive import scheduler
    return datetime.datetime.now(zoneinfo.ZoneInfo(scheduler.ZONA))


def pendientes(ahora: datetime.datetime | None = None) -> list[str]:
    """Los tipos cuya hora programada pasó desde la última revisión, y la marca como revisada.

    Se marca ANTES de correr: si el runner muere a mitad, la siguiente hora no
    repite la misma Corrida (queda 'interrumpida' en el panel y se ve).
    """
    from afterdrive import config_store, scheduler

    ahora = ahora or _ahora()
    revisado = config_store.get_ejecutor_externo()
    tocan = []
    for tipo in TIPOS:
        habilitado, hora, minuto, dias = scheduler.programacion(tipo)
        desde_txt = revisado.get(tipo)
        desde = datetime.datetime.fromisoformat(desde_txt) if desde_txt else ahora - VENTANA_INICIAL
        if habilitado:
            proxima = scheduler.trigger(hora, minuto, dias).get_next_fire_time(None, desde)
            if proxima is not None and proxima <= ahora:
                tocan.append(tipo)
        revisado[tipo] = ahora.isoformat()
    config_store.set_ejecutor_externo(revisado)
    return tocan


def _proveedor_guardado() -> None:
    """Usa el proveedor de IA elegido en el dashboard (y el modo pago), como hace el servidor."""
    from afterdrive import config_store
    from afterdrive.ia import modo_pago
    if os.getenv("AI_PROVIDER_OVERRIDE"):
        return
    try:
        p = config_store.get_provider_config()
        if p:
            os.environ["AI_PROVIDER"] = p
    except Exception as e:
        print(f"[ejecutor] No se pudo leer el proveedor guardado ({e}); se usa AI_PROVIDER.", flush=True)
    modo_pago.restaurar()


def correr(tipos: list[str]) -> int:
    """Corre los tipos pedidos en orden. Devuelve 1 si alguna terminó con error."""
    from afterdrive import cola
    from afterdrive.db import crear_indices

    _proveedor_guardado()
    crear_indices()
    fallo = False
    for tipo in tipos:
        print(f"[ejecutor] Corriendo '{tipo}' en GitHub Actions...", flush=True)
        estado = cola.ejecutar_aca(tipo, origen="cron", ejecutor="github")
        print(f"[ejecutor] '{tipo}' terminó: {estado}.", flush=True)
        fallo |= estado != "ok"
    return 1 if fallo else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--pendientes", action="store_true", help="imprime los tipos que tocan ahora")
    grupo.add_argument("--correr", nargs="*", choices=TIPOS, help="corre estos tipos ya")
    args = ap.parse_args(argv)
    if not os.getenv("MONGO_URI"):
        print("[ejecutor] Falta MONGO_URI: configurá los secretos del repositorio.", flush=True)
        return 1
    if args.pendientes:
        print(" ".join(pendientes()))
        return 0
    return correr(args.correr or [])


if __name__ == "__main__":
    sys.exit(main())
