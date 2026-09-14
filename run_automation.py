import os
import sys

print("[run_automation] Iniciando...", flush=True)

mongo_uri = os.getenv("MONGO_URI", "")
if not mongo_uri:
    print("[run_automation] ERROR: MONGO_URI no está configurado en el entorno.", flush=True)
    sys.exit(1)

# Se enmascaran las credenciales en vez de truncar la URI: truncar a 40 chars
# dejaba el usuario y el inicio de la contraseña en los logs de Render.
# La redacción va inline (y no importada de db.py) para no disparar la conexión
# a Mongo antes del import de abajo, que es lo que este log busca diagnosticar.
_host = mongo_uri.split("://", 1)[-1].split("@", 1)[-1].split("/", 1)[0].split("?", 1)[0]
print(f"[run_automation] MONGO_URI detectado (host): {_host or '***'}", flush=True)

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
