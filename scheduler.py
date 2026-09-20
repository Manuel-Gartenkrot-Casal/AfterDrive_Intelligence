import datetime
import threading

from apscheduler.schedulers.background import BackgroundScheduler

import config_store
from db import clasificar_y_guardar, col_articulos, col_trusted_urls
from lm_studio import clasificar_articulo
from resource_detector import get_startup_delay_minutes
from scraper import start

DEFAULT_INTERVAL_DAYS = 1
DEFAULT_MAX_ARTICULOS = 10
DEFAULT_GENERACION_INTERVAL_DAYS = 3

scheduler = BackgroundScheduler()
_exec_lock = threading.Lock()


def _load_persisted() -> dict:
    """Lee la config persistida de Mongo y la aplica a los defaults."""
    cfg = config_store.get_scraping_config()
    gen = config_store.get_generacion_config()
    return {
        "interval_days": cfg.get("interval_days", DEFAULT_INTERVAL_DAYS),
        "max_articulos": cfg.get("max_articulos", DEFAULT_MAX_ARTICULOS),
        "scraping_enabled": cfg.get("enabled", True),
        "gen_enabled": gen.get("enabled", True),
        "gen_interval_days": gen.get("interval_days", DEFAULT_GENERACION_INTERVAL_DAYS),
    }


_persisted = {}
try:
    _persisted = _load_persisted()
except Exception as e:
    print(f"[Scheduler] No se pudo cargar config persistida, usando defaults: {e}", flush=True)
for _k, _v in {
    "interval_days": DEFAULT_INTERVAL_DAYS,
    "max_articulos": DEFAULT_MAX_ARTICULOS,
    "scraping_enabled": True,
    "gen_enabled": True,
    "gen_interval_days": DEFAULT_GENERACION_INTERVAL_DAYS,
}.items():
    _persisted.setdefault(_k, _v)
_max_articulos = _persisted["max_articulos"]


def get_max_articulos() -> int:
    return _max_articulos


def set_max_articulos(cantidad: int):
    global _max_articulos
    _max_articulos = max(1, cantidad)
    config_store.set_scraping_config(max_articulos=_max_articulos)


def is_scraping_enabled() -> bool:
    return _persisted.get("scraping_enabled", True)


def set_scraping_enabled(enabled: bool):
    _persisted["scraping_enabled"] = bool(enabled)
    config_store.set_scraping_config(enabled=_persisted["scraping_enabled"])
    _sync_jobs()


def get_generacion_enabled() -> bool:
    return _persisted.get("gen_enabled", True)


def set_generacion_enabled(enabled: bool):
    _persisted["gen_enabled"] = bool(enabled)
    config_store.set_generacion_config(enabled=_persisted["gen_enabled"])
    _sync_jobs()


def get_generacion_interval() -> int:
    return _persisted.get("gen_interval_days", DEFAULT_GENERACION_INTERVAL_DAYS)


def update_generacion_interval(days: int):
    _persisted["gen_interval_days"] = max(1, int(days))
    config_store.set_generacion_config(interval_days=_persisted["gen_interval_days"])
    _sync_jobs()


def run_trusted_scraping():
    if not is_scraping_enabled():
        print(f"[{datetime.datetime.now()}] Scraping automático DESHABILITADO. Skipping.", flush=True)
        return

    if not _exec_lock.acquire(blocking=False):
        print(f"[{datetime.datetime.now()}] Otra tarea en ejecución. Skipping scraping.", flush=True)
        return

    try:
        print(f"[{datetime.datetime.now()}] Iniciando scraping automatizado de URLs confiables...", flush=True)

        try:
            total_en_db = col_trusted_urls.count_documents({})
            urls_confiables = list(col_trusted_urls.find({"estado": "activo"}))
            print(f"[DB] Total en trusted_urls: {total_en_db} | Activas: {len(urls_confiables)}", flush=True)
        except Exception as e:
            print(f"[ERROR] No se pudo consultar la base de datos: {e}", flush=True)
            return

        if not urls_confiables:
            if total_en_db == 0:
                print("No hay URLs confiables en la base de datos. Agregá una desde el panel.", flush=True)
            else:
                print(f"Hay {total_en_db} URL(s) en la DB pero ninguna con estado='activo'.", flush=True)
            return

        print(f"Procesando {len(urls_confiables)} fuentes (max {_max_articulos} artículos/fuente)...", flush=True)

        for doc in urls_confiables:
            url = doc["url"]
            print(f"Scrapeando: {url}", flush=True)

            try:
                result = start([url], modo="list", max_articulos=_max_articulos)
                items = result.items

                if items:
                    res = clasificar_y_guardar(items, col_articulos, clasificar_articulo)
                    print(f"  [OK] {res['aprobados']} nuevos artículos aprobados.", flush=True)
                else:
                    print(f"  [WARN] No se encontraron artículos nuevos en {url}", flush=True)

                col_trusted_urls.update_one(
                    {"url": url}, {"$set": {"ultima_ejecucion": datetime.datetime.now(datetime.UTC).isoformat()}}
                )
            except Exception as e:
                print(f"  [ERROR] Fallo al procesar {url}: {e}", flush=True)

        print(f"[{datetime.datetime.now()}] Scraping automatizado finalizado.", flush=True)
    finally:
        _exec_lock.release()


def run_auto_generacion():
    """Genera una nota Fase 2 automáticamente con la config guardada."""
    if not get_generacion_enabled():
        print(f"[{datetime.datetime.now()}] Generación automática DESHABILITADA. Skipping.", flush=True)
        return

    if not _exec_lock.acquire(blocking=False):
        print(f"[{datetime.datetime.now()}] Otra tarea en ejecución. Skipping generación.", flush=True)
        return

    try:
        from generar_nota_fase2 import generar_nota

        fase2 = config_store.get_fase2_config()
        gen = config_store.get_generacion_config()
        categorias = fase2.get("categorias") or []
        if not categorias:
            print("[Generación] Sin categorías activas guardadas. Skipping.", flush=True)
            return

        puntapie_url = None
        if fase2.get("puntapie_activo"):
            puntapie_url = fase2.get("puntapie_url") or gen.get("puntapie_url") or None

        print(f"[Generación] Categorías: {categorias} | Persona: {gen.get('persona')}", flush=True)
        resultado = generar_nota(
            categorias=categorias,
            clientes_ids=(fase2.get("clientes") or []),
            puntapie_url=puntapie_url,
            persona=gen.get("persona", "comercial"),
            tema=(gen.get("tema") or None),
            regiones=(fase2.get("regiones") or []),
        )
        if resultado.get("success"):
            print(f"[Generación] [OK] Nota generada y guardada en 'notas_fase2'.", flush=True)
        else:
            print(f"[Generación] [ERROR] {resultado.get('error')}", flush=True)
    except Exception as e:
        print(f"[Generación] [ERROR] Fallo en generación automática: {e}", flush=True)
    finally:
        _exec_lock.release()


def _sync_jobs():
    """Sincroniza los jobs del scheduler con la config persistida."""
    if not scheduler.running:
        return

    # Job de scraping
    job = scheduler.get_job("trusted_scraping")
    if job:
        scheduler.remove_job("trusted_scraping")
    if _persisted["scraping_enabled"]:
        delay = get_startup_delay_minutes()
        primera_ejecucion = datetime.datetime.now() + datetime.timedelta(minutes=delay)
        scheduler.add_job(
            run_trusted_scraping,
            "interval",
            days=_persisted["interval_days"],
            id="trusted_scraping",
            next_run_time=primera_ejecucion,
        )

    # Job de generación de artículos
    job = scheduler.get_job("auto_generacion")
    if job:
        scheduler.remove_job("auto_generacion")
    if _persisted["gen_enabled"]:
        primera = datetime.datetime.now() + datetime.timedelta(hours=1)
        scheduler.add_job(
            run_auto_generacion,
            "interval",
            days=_persisted["gen_interval_days"],
            id="auto_generacion",
            next_run_time=primera,
        )


def start_scheduler(interval_days=None):
    if interval_days is not None:
        _persisted["interval_days"] = max(1, int(interval_days))
        config_store.set_scraping_config(interval_days=_persisted["interval_days"])

    if scheduler.get_job("trusted_scraping"):
        scheduler.remove_job("trusted_scraping")
    if scheduler.get_job("auto_generacion"):
        scheduler.remove_job("auto_generacion")

    delay = get_startup_delay_minutes()
    primera_ejecucion = datetime.datetime.now() + datetime.timedelta(minutes=delay)

    if _persisted["scraping_enabled"]:
        scheduler.add_job(
            run_trusted_scraping,
            "interval",
            days=_persisted["interval_days"],
            id="trusted_scraping",
            next_run_time=primera_ejecucion,
        )
        print(f"[Scheduler] Scraping cada {_persisted['interval_days']} día(s). Primera ejecución en {delay} min.", flush=True)
    else:
        print("[Scheduler] Scraping automático deshabilitado por configuración.", flush=True)

    if _persisted["gen_enabled"]:
        primera_gen = datetime.datetime.now() + datetime.timedelta(hours=1)
        scheduler.add_job(
            run_auto_generacion,
            "interval",
            days=_persisted["gen_interval_days"],
            id="auto_generacion",
            next_run_time=primera_gen,
        )
        print(f"[Scheduler] Generación automática cada {_persisted['gen_interval_days']} día(s).", flush=True)
    else:
        print("[Scheduler] Generación automática deshabilitada por configuración.", flush=True)

    scheduler.start()
    print("Scheduler iniciado.")


def update_scheduler_interval(days: int):
    _persisted["interval_days"] = max(1, int(days))
    config_store.set_scraping_config(interval_days=_persisted["interval_days"])
    if scheduler.get_job("trusted_scraping"):
        scheduler.reschedule_job("trusted_scraping", trigger="interval", days=_persisted["interval_days"])
        print(f"Intervalo actualizado a {_persisted['interval_days']} día(s).")
    else:
        start_scheduler(_persisted["interval_days"])


def get_next_execution():
    job = scheduler.get_job("trusted_scraping")
    if job:
        return job.next_run_time.isoformat()
    return None


def get_next_generacion_execution():
    job = scheduler.get_job("auto_generacion")
    if job:
        return job.next_run_time.isoformat()
    return None