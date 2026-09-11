import datetime
import os
import sys

if not os.getenv("MONGO_URI"):
    print("[add_url] ERROR: MONGO_URI no está configurado en el entorno.", flush=True)
    sys.exit(1)

from db import clasificar_y_guardar, col_articulos, col_trusted_urls
from lm_studio import clasificar_articulo
from scheduler import get_max_articulos
from scraper import start


def add_custom_url(url: str):
    print(f"Procesando URL: {url}", flush=True)

    max_art = get_max_articulos()
    result = start([url], modo="list", max_articulos=max_art)
    items = result.items

    if not items:
        print("[FAIL] No se encontraron articulos en la URL. No se agregara a URLs Confiables.", flush=True)
        return

    res = clasificar_y_guardar(items, col_articulos, clasificar_articulo)

    print(f"\nResultado: {res['aprobados']} aprobados, {res['rechazados']} rechazados.", flush=True)

    if res["aprobados"] > 0:
        col_trusted_urls.update_one(
            {"url": url},
            {
                "$set": {
                    "nombre_fuente": items[0].get("fuente", "Custom Source"),
                    "fecha_agregado": datetime.datetime.now(datetime.UTC).isoformat(),
                    "ultima_ejecucion": datetime.datetime.now(datetime.UTC).isoformat(),
                    "estado": "activo",
                }
            },
            upsert=True,
        )
        print("[OK] URL agregada exitosamente a la lista de URLs Confiables.", flush=True)
    else:
        print("[WARN] Ningun articulo fue aprobado por el clasificador. La URL no se agrego a Confiables.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python add_url.py <URL>")
        sys.exit(1)

    target_url = sys.argv[1]
    add_custom_url(target_url)
