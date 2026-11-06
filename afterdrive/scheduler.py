"""
scheduler.py — Agenda las Corridas automáticas según la config guardada.

Interfaz:
    iniciar()   arranca APScheduler y agenda según config_store
    aplicar()   reagenda después de un cambio de config
    proximas()  {"scraping": iso | None, "generacion": iso | None}
    horarios(job_id) -> (habilitado, [(hora, minuto)], cada_dias)

La generación puede correr varias veces por día: `hora` y las `horas_extra`
de la config. Cada hora es un job propio ("generacion", "generacion_2", ...).

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
        lambda: cola.encolar("scraping", origen="cron", turno=_turno("scraping")),
    ),
    "generacion": (
        lambda: config_store.get_generacion_config(), config_store.DEFAULT_GENERACION["hora"],
        lambda: cola.encolar("generacion", origen="cron", turno=_turno("generacion")),
    ),
}

_scheduler = BackgroundScheduler()


def _turno(tipo: str) -> str:
    """Identifica la programada que se dispara ahora (al minuto): si otro servidor
    contra la misma base la dispara a la vez, la Cola la encola una sola vez."""
    return f"{tipo}:{datetime.datetime.now(zoneinfo.ZoneInfo(ZONA)):%Y-%m-%dT%H:%M}"

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


def _hhmm(texto: str) -> tuple[int, int] | None:
    try:
        hora, minuto = (int(x) for x in str(texto).split(":"))
    except ValueError:
        return None
    return (hora, minuto) if 0 <= hora < 24 and 0 <= minuto < 60 else None


def horarios(job_id: str) -> tuple[bool, list[tuple[int, int]], int]:
    """(habilitado, [(hora, minuto)] en orden, cada_dias) de un job, según la config guardada.

    La primera es `hora`; después las `horas_extra` (solo la generación las tiene).
    """
    leer_config, hora_default, _ = _JOBS[job_id]
    cfg = leer_config()
    principal = _hhmm(cfg.get("hora") or hora_default) or _hhmm(hora_default)
    extra = [h for h in (_hhmm(x) for x in cfg.get("horas_extra") or []) if h and h != principal]
    return (bool(cfg.get("enabled", True)), [principal] + sorted(set(extra)),
            max(1, int(cfg.get("interval_days", 1))))


def programacion(job_id: str) -> tuple[bool, int, int, int]:
    """(habilitado, hora, minuto, cada_dias) de la hora principal de un job."""
    habilitado, horas, dias = horarios(job_id)
    return habilitado, horas[0][0], horas[0][1], dias


def _ids(job_id: str, cantidad: int) -> list[str]:
    """"generacion", "generacion_2", "generacion_3"...: un job por hora."""
    return [job_id] + [f"{job_id}_{i}" for i in range(2, cantidad + 1)]


def aplicar() -> None:
    """Deja los jobs exactamente como dice la config guardada."""
    for job_id, (_, _, correr) in _JOBS.items():
        for job in _scheduler.get_jobs():
            if job.id == job_id or job.id.startswith(job_id + "_"):
                job.remove()
        habilitado, horas, dias = horarios(job_id)
        if not habilitado:
            print(f"[Scheduler] {job_id}: deshabilitado por configuración.", flush=True)
            continue
        if externas():
            # La misma programación la lee afterdrive/ejecutor_externo.py en GitHub Actions.
            print(f"[Scheduler] {job_id}: a cargo de GitHub Actions (CORRIDAS_EXTERNAS=github).", flush=True)
            continue
        for id_, (hora, minuto) in zip(_ids(job_id, len(horas)), horas, strict=True):
            _scheduler.add_job(correr, trigger(hora, minuto, dias), id=id_)
        lista = ", ".join(f"{h:02d}:{m:02d}" for h, m in horas)
        print(f"[Scheduler] {job_id}: {lista} ({ZONA}) cada {dias} día(s).", flush=True)


def iniciar() -> None:
    from afterdrive.db import crear_indices
    crear_indices()
    cola.iniciar()
    aplicar()
    if not _scheduler.running:
        _scheduler.start()
    print("[Scheduler] iniciado.", flush=True)


def proximas() -> dict:
    """La próxima ejecución de cada tipo (la más cercana de sus horas)."""
    def _iso(job_id):
        if externas():
            habilitado, horas, dias = horarios(job_id)
            if not habilitado:
                return None
            ahora = datetime.datetime.now(zoneinfo.ZoneInfo(ZONA))
            return min(trigger(h, m, dias).get_next_fire_time(None, ahora) for h, m in horas).isoformat()
        # Los jobs pendientes (scheduler sin arrancar) no tienen next_run_time.
        siguientes = [nxt for job in _scheduler.get_jobs()
                      if (job.id == job_id or job.id.startswith(job_id + "_"))
                      and (nxt := getattr(job, "next_run_time", None))]
        return min(siguientes).isoformat() if siguientes else None

    return {job_id: _iso(job_id) for job_id in _JOBS}
