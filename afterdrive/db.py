import os

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/afterdrive")


def uri_segura(uri: str) -> str:
    """Enmascara las credenciales de una URI de Mongo para poder loguearla.

    Truncar la URI a N caracteres NO alcanza: el usuario y el arranque de la
    contraseña caen dentro de los primeros 40 y quedan en los logs del servicio,
    que son visibles para cualquiera con acceso al panel de deploy.

        mongodb+srv://user:pass@cluster.mongodb.net/db
        -> mongodb+srv://***@cluster.mongodb.net

    Se conserva el host, que es lo único con valor diagnóstico.
    """
    partes = uri.split("://", 1)
    if len(partes) != 2:
        return "***"
    esquema, resto = partes
    host = resto.split("@", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return f"{esquema}://***@{host}"


if not MONGO_URI or MONGO_URI == "mongodb://localhost:27017/afterdrive":
    print("[DB] ADVERTENCIA: MONGO_URI no configurado o usando fallback local.", flush=True)
else:
    print(f"[DB] Conectando a MongoDB: {uri_segura(MONGO_URI)}", flush=True)

# ── Base de Datos ─────────────────────────────────────────────────────────────

client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=15000,
    connectTimeoutMS=15000,
    socketTimeoutMS=30000,
    retryWrites=True,
    retryReads=True,
)
db = client["afterdrive"]

col_articulos = db["articulos"]  # Todos los artículos scrapeados
col_trusted_urls = db["trusted_urls"]  # Lista blanca de URLs confiables
col_descartados = db["articulos_descartados"]
col_afterdrive = db["afterdrive"]

# ── Fase 2 ────────────────────────────────────────────────────────────────────
col_afterdrive_ejemplos = db["afterdrive_ejemplos"]  # Notas reales scrapeadas del blog
col_notas_fase2 = db["notas_fase2"]                  # Notas generadas por Fase 2
col_clientes = db["clientes"]                        # Clientes para mencionar en notas

COLECCIONES_URLS = [col_articulos, col_afterdrive]

COLECCIONES_TEXTO = {
    col_articulos: [("titulo", "text"), ("cuerpo", "text")],
    col_afterdrive: [("titulo", "text"), ("cuerpo", "text")],
    col_afterdrive_ejemplos: [("titulo", "text"), ("cuerpo", "text")],
}


def crear_indices_texto():
    for col, campos in COLECCIONES_TEXTO.items():
        try:
            col.create_index(campos, default_language="spanish", name="text_search", background=True)
        except Exception:
            pass
    try:
        col_generados = db["articulos_generados"]
        col_generados.create_index(
            [("contenido", "text")], default_language="spanish", name="text_search", background=True
        )
    except Exception:
        pass


def guardar_items(items, coleccion):
    """
    Inserta una lista de dicts en la colección indicada.
    Usa ReplaceOne con upsert=True sobre 'url' para evitar duplicados.
    """
    if not items:
        return 0

    operaciones = [ReplaceOne({"url": item["url"]}, item, upsert=True) for item in items]
    resultado = coleccion.bulk_write(operaciones)
    return resultado.upserted_count + resultado.modified_count


def obtener_urls_procesados() -> set[str]:
    urls = set()
    for col in COLECCIONES_URLS:
        for doc in col.find({}, {"url": 1, "_id": 0}):
            if url := doc.get("url"):
                urls.add(url)
    return urls
