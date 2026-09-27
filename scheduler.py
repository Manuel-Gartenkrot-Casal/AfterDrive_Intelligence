"""
scheduler.py — Agenda las Corridas automáticas según la config guardada.

Interfaz:
    iniciar()   arranca APScheduler y agenda según config_store
    aplicar()   reagenda después de un cambio de config
    proximas()  {"scraping": iso | None, "generacion": iso | None}

La config (habilitado, intervalo, max artículos) es de config_store; este
módulo no guarda copia propia, así que no hay dos fuentes de verdad.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config_store
import corridas

# Horarios fijos (UTC). Con el keep-alive externo la instancia queda despierta
# 24/7, así que APScheduler puede ejecutar a hora de reloj y no relativo al boot.
SCRAPING_HORA = (8, 30)
GENERACION_HORA = (14, 0)

_JOBS = {
    # id: (lector de config, hora, qué correr)
    "scraping": (lambda: config_store.get_scraping_config(), SCRAPING_HORA, corridas.scraping),
    "generacion": (lambda: config_store.get_generacion_config(), GENERACION_HORA, corridas.generacion),
}

_scheduler = BackgroundScheduler()


def aplicar() -> None:
    """Deja los jobs exactamente como dice la config guardada."""
    for job_id, (leer_config, (hora, minuto), correr) in _JOBS.items():
        cfg = leer_config()
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
        if not cfg.get("enabled", True):
            print(f"[Scheduler] {job_id}: deshabilitado por configuración.", flush=True)
            continue
        dias = max(1, int(cfg.get("interval_days", 1)))
        _scheduler.add_job(correr, CronTrigger(hour=hora, minute=minuto, day=f"*/{dias}"), id=job_id)
        print(f"[Scheduler] {job_id}: {hora:02d}:{minuto:02d} UTC cada {dias} día(s).", flush=True)


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
