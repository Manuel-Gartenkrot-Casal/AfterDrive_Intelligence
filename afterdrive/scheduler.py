"""
scheduler.py — Agenda las Corridas automáticas según la config guardada.

Interfaz:
    iniciar()   arranca APScheduler y agenda según config_store
    aplicar()   reagenda después de un cambio de config
    proximas()  {"scraping": iso | None, "generacion": iso | None}

La config (habilitado, hora, intervalo, max artículos) es de config_store;
este módulo no guarda copia propia, así que no hay dos fuentes de verdad.

Las horas se interpretan en ZONA (hora de Argentina por defecto), que es la
que ve y edita el usuario en el dashboard.
"""

import datetime
import os
import zoneinfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from afterdrive import cola, config_store

ZONA = os.getenv("SCHEDULER_TZ", "America/Argentina/Buenos_Aires")

# Con el keep-alive externo la instancia queda despierta 24/7, así que
# APScheduler puede ejecutar a hora de reloj y no relativo al boot.
# Las programadas se encolan: si a esa hora hay otra Corrida, esperan su turno
# en vez de perderse.
_JOBS = {
    # id: (lector de config, hora por defecto, qué correr)
    "scraping": (
        lambda: config_store.get_scraping_config(), config_store.DEFAULT_SCRAPING["hora"],
        lambda: cola.encolar("scraping", origen="cron"),
    ),
    "generacion": (
        lambda: config_store.get_generacion_config(), config_store.DEFAULT_GENERACION["hora"],
        lambda: cola.encolar("generacion", origen="cron"),
    ),
}

_scheduler = BackgroundScheduler()

# "Cada N días" se cuenta desde esta fecha fija, así el ritmo no cambia con
# cada reinicio del servidor. Antes era CronTrigger(day="*/N"), que cuenta días
# del mes: con N=2 corría el 31 y el 1, dos días seguidos.
ANCLA = datetime.date(2026, 1, 1)


def trigger(hora: int, minuto: int, dias: int):
    """Todos los días a esa hora, o cada `dias` días contados desde ANCLA."""
    tz = zoneinfo.ZoneInfo(ZONA)
    if dias <= 1:
        return CronTrigger(hour=hora, minute=minuto, timezone=tz)
    inicio = datetime.datetime.combine(ANCLA, datetime.time(hora, minuto), tzinfo=tz)
    return IntervalTrigger(days=dias, start_date=inicio, timezone=tz)


def externas() -> bool:
    """True si las Corridas programadas las ejecuta GitHub Actions y no este servidor."""
    return os.getenv("CORRIDAS_EXTERNAS", "").strip().lower() == "github"


def programacion(job_id: str) -> tuple[bool, int, int, int]:
    """(habilitado, hora, minuto, cada_dias) de un job, según la config guardada."""
    leer_config, hora_default, _ = _JOBS[job_id]
    cfg = leer_config()
    hora, minuto = (int(x) for x in (cfg.get("hora") or hora_default).split(":"))
    return bool(cfg.get("enabled", True)), hora, minuto, max(1, int(cfg.get("interval_days", 1)))


def aplicar() -> None:
    """Deja los jobs exactamente como dice la config guardada."""
    for job_id, (_, _, correr) in _JOBS.items():
        habilitado, hora, minuto, dias = programacion(job_id)
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
        if not habilitado:
            print(f"[Scheduler] {job_id}: deshabilitado por configuración.", flush=True)
            continue
        if externas():
            # La misma programación la lee afterdrive/ejecutor_externo.py en GitHub Actions.
            print(f"[Scheduler] {job_id}: a cargo de GitHub Actions (CORRIDAS_EXTERNAS=github).", flush=True)
            continue
        _scheduler.add_job(correr, trigger(hora, minuto, dias), id=job_id)
        print(f"[Scheduler] {job_id}: {hora:02d}:{minuto:02d} ({ZONA}) cada {dias} día(s).", flush=True)


def iniciar() -> None:
    from afterdrive.db import crear_indices
    crear_indices()
    cola.iniciar()
    aplicar()
    if not _scheduler.running:
        _scheduler.start()
    print("[Scheduler] iniciado.", flush=True)


def proximas() -> dict:
    def _iso(job_id):
        if externas():
            habilitado, hora, minuto, dias = programacion(job_id)
            if not habilitado:
                return None
            ahora = datetime.datetime.now(zoneinfo.ZoneInfo(ZONA))
            return trigger(hora, minuto, dias).get_next_fire_time(None, ahora).isoformat()
        job = _scheduler.get_job(job_id)
        nxt = getattr(job, "next_run_time", None)  # los jobs pendientes (scheduler sin arrancar) no lo tienen
        return nxt.isoformat() if nxt else None

    return {job_id: _iso(job_id) for job_id in _JOBS}
