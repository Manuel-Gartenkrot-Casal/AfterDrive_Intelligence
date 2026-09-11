import os
import sys

print("[run_automation] Iniciando...", flush=True)

mongo_uri = os.getenv("MONGO_URI", "")
if not mongo_uri:
    print("[run_automation] ERROR: MONGO_URI no está configurado en el entorno.", flush=True)
    sys.exit(1)

_uri_log = mongo_uri[:40] + "..." if len(mongo_uri) > 40 else mongo_uri
print(f"[run_automation] MONGO_URI detectado: {_uri_log}", flush=True)

try:
    from scheduler import run_trusted_scraping, set_max_articulos
except Exception as e:
    print(f"[run_automation] ERROR al importar módulos (posible fallo de DB): {e}", flush=True)
    sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            set_max_articulos(int(sys.argv[1]))
        except ValueError:
            pass
    run_trusted_scraping()
