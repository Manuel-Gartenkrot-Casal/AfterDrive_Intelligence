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

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from afterdrive import config_store
from afterdrive import corridas
ZONA = os.getenv("SCHEDULER_TZ", "America/Argentina/Buenos_Aires")

# Con el keep-alive externo la instancia queda despierta 24/7, así que
# APScheduler puede ejecutar a hora de reloj y no relativo al boot.
_JOBS = {
    # id: (lector de config, hora por defecto, qué correr)
    "scraping": (lambda: config_store.get_scraping_config(), config_store.DEFAULT_SCRAPING["hora"], corridas.scraping),
    "generacion": (
        lambda: config_store.get_generacion_config(), config_store.DEFAULT_GENERACION["hora"], corridas.generacion,
    ),
}

_scheduler = BackgroundScheduler()


def aplicar() -> None:
    """Deja los jobs exactamente como dice la config guardada."""
    for job_id, (leer_config, hora_default, correr) in _JOBS.items():
        cfg = leer_config()
        hora, minuto = (int(x) for x in (cfg.get("hora") or hora_default).split(":"))
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
        if not cfg.get("enabled", True):
            print(f"[Scheduler] {job_id}: deshabilitado por configuración.", flush=True)
            continue
        dias = max(1, int(cfg.get("interval_days", 1)))
        trigger = CronTrigger(hour=hora, minute=minuto, day=f"*/{dias}", timezone=ZONA)
        _scheduler.add_job(correr, trigger, id=job_id)
        print(f"[Scheduler] {job_id}: {hora:02d}:{minuto:02d} ({ZONA}) cada {dias} día(s).", flush=True)


def iniciar() -> None:
    aplicar()
    if not _scheduler.running:
        _scheduler.start()
    print("[Scheduler] iniciado.", flush=True)


def proximas() -> dict:
    def _iso(job_id):
        job = _scheduler.get_job(job_id)
        nxt = getattr(job, "next_run_time", None)  # los jobs pendientes (scheduler sin arrancar) no lo tienen
        return nxt.isoformat() if nxt else None

    return {job_id: _iso(job_id) for job_id in _JOBS}
