import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from db import clasificar_y_guardar, col_articulos, col_trusted_urls
from lm_studio import clasificar_articulo
from scraper import start

# Configuración por defecto
DEFAULT_INTERVAL_DAYS = 1
DEFAULT_MAX_ARTICULOS = 10

scheduler = BackgroundScheduler()
_max_articulos = DEFAULT_MAX_ARTICULOS


def get_max_articulos() -> int:
    """Devuelve el máximo de artículos por fuente."""
    return _max_articulos


def set_max_articulos(cantidad: int):
    """Actualiza el máximo de artículos por fuente."""
    global _max_articulos
    _max_articulos = max(1, cantidad)


def run_trusted_scraping():
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


def start_scheduler(interval_days=DEFAULT_INTERVAL_DAYS):
    """Inicia el scheduler con el intervalo especificado."""
    # Eliminar trabajos previos si existen para evitar duplicados al reiniciar
    if scheduler.get_job("trusted_scraping"):
        scheduler.remove_job("trusted_scraping")

    scheduler.add_job(
        run_trusted_scraping,
        "interval",
        days=interval_days,
        id="trusted_scraping",
        next_run_time=datetime.datetime.now(),  # Ejecutar inmediatamente al iniciar
    )
    scheduler.start()
    print(f"Scheduler iniciado. Ejecución cada {interval_days} día(s).")


def update_scheduler_interval(days: int):
    """Actualiza el intervalo de ejecución dinámicamente."""
    if scheduler.get_job("trusted_scraping"):
        scheduler.reschedule_job("trusted_scraping", trigger="interval", days=days)
        print(f"Intervalo actualizado a {days} día(s).")
    else:
        start_scheduler(days)


def get_next_execution():
    """Devuelve la próxima fecha de ejecución programada."""
    job = scheduler.get_job("trusted_scraping")
    if job:
        return job.next_run_time.isoformat()
    return None
