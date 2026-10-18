import contextlib
import datetime
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

# Notas que el modelo llegó a escribir pero se descartaron (el saneo las
# rechazó). Antes solo se imprimían en la consola y se perdían.
col_notas_descartadas = db["notas_descartadas"]

# Estado editorial de una Nota guardada. Las notas anteriores a este campo no
# lo tienen y cuentan como borrador. "publicado" (y no "publicada") por
# compatibilidad con lo que ya guardó la rama Front-Testing.
ESTADO_BORRADOR = "borrador"
ESTADO_APROBADA = "aprobada"
ESTADO_RECHAZADA = "rechazada"
ESTADO_PUBLICADO = "publicado"
ESTADOS_NOTA = (ESTADO_BORRADOR, ESTADO_APROBADA, ESTADO_RECHAZADA, ESTADO_PUBLICADO)

COLECCIONES_URLS = [col_articulos, col_afterdrive]

COLECCIONES_TEXTO = {
    col_articulos: [("titulo", "text"), ("cuerpo", "text")],
    col_afterdrive: [("titulo", "text"), ("cuerpo", "text")],
    col_afterdrive_ejemplos: [("titulo", "text"), ("cuerpo", "text")],
}


# Índices para lo que se consulta en cada corrida. Sin ellos, cada upsert por
# url y cada búsqueda de la cola recorren la colección entera. create_index es
# idempotente: correrlo en cada arranque no cuesta nada si ya existen.
INDICES = {
    "articulos": [[("url", 1)], [("usado_para_articulo", 1)]],
    "articulos_descartados": [[("url", 1)]],
    "trusted_urls": [[("url", 1)], [("estado", 1)]],
    "suggested_urls": [[("dominio", 1)]],
    "notas_fase2": [[("generado_en", -1)], [("estado", 1)]],
    "notas_descartadas": [[("descartado_en", -1)]],
    "afterdrive_ejemplos": [[("tag_slug", 1)]],
    "corridas": [[("estado", 1), ("creada", 1)], [("fin", -1)]],
}


def crear_indices() -> None:
    """Crea los índices que faltan. Nunca frena el arranque: si Mongo falla, avisa."""
    for coleccion, indices in INDICES.items():
        for campos in indices:
            try:
                db[coleccion].create_index(campos, background=True)
            except Exception as e:
                print(f"[DB] No se pudo crear el índice {coleccion}.{campos}: {e}", flush=True)
    crear_indices_texto()


def registrar_nota_descartada(origen: str, contenido: str, motivo: str, **meta) -> None:
    """Guarda una Nota descartada para que el historial pueda mostrarla.

    Nunca corta la generación: si Mongo falla, avisa y sigue. El contenido se
    acota a 20000 caracteres: el texto crudo puede traer razonamiento largo.
    """
    try:
        col_notas_descartadas.insert_one({
            "origen": origen,
            "contenido": (contenido or "")[:20000],
            "motivo": motivo,
            "descartado_en": datetime.datetime.now(datetime.UTC).isoformat(),
            **meta,
        })
    except Exception as e:
        print(f"[AVISO] No se pudo registrar la nota descartada: {e}", flush=True)


def crear_indices_texto():
    for col, campos in COLECCIONES_TEXTO.items():
        with contextlib.suppress(Exception):
            col.create_index(campos, default_language="spanish", name="text_search", background=True)
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
