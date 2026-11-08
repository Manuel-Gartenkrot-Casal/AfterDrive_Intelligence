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
    from afterdrive import corridas
except Exception as e:
    print(f"[run_automation] ERROR al importar módulos (posible fallo de DB): {e}", flush=True)
    sys.exit(1)

def max_articulos_de(argv: list[str]) -> int | None:
    """El máximo de artículos por fuente pedido en la línea de comandos; None = el de la config.

    Lanza ValueError si no es un entero de al menos 1. Antes un texto se ignoraba
    en silencio (se usaba la config) y un 0 o un negativo llegaba al scraper.
    """
    if len(argv) < 2:
        return None
    valor = int(argv[1].strip())
    if valor < 1:
        raise ValueError(valor)
    return valor


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    try:
        max_articulos = max_articulos_de(argv)
    except ValueError:
        print(f"[run_automation] ERROR: el máximo de artículos por fuente tiene que ser un entero mayor o igual "
              f"a 1 (llegó {argv[1]!r}). No se scrapeó nada.", flush=True)
        return 2
    # Corre bajo el lock del proceso padre (flask); acá solo se ejecuta.
    resultado = corridas.scraping(max_articulos)
    return 0 if resultado.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
