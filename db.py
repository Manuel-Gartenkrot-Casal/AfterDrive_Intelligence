import datetime
import os

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne, UpdateOne

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/afterdrive")

if not MONGO_URI or MONGO_URI == "mongodb://localhost:27017/afterdrive":
    print("[DB] ADVERTENCIA: MONGO_URI no configurado o usando fallback local.", flush=True)
else:
    _uri_log = MONGO_URI[:40] + "..." if len(MONGO_URI) > 40 else MONGO_URI
    print(f"[DB] Conectando a MongoDB: {_uri_log}", flush=True)

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


def clasificar_y_guardar(items, coleccion, clasificador_fn):
    """
    Clasifica cada item usando clasificador_fn y guarda solo los aprobados.
    Los rechazados se persisten en la colección 'articulos_descartados' para auditoría.

    clasificador_fn(titulo, cuerpo) -> {"aprobado": bool, "razon": str}
    Returns:
        {"total": int, "aprobados": int, "rechazados": int, "detalles": list[dict]}
    """
    if not items:
        return {"total": 0, "aprobados": 0, "rechazados": 0, "detalles": []}

    aprobados = []
    detalles = []
    total = len(items)

    for i, item in enumerate(items, 1):
        titulo = item.get("titulo", "(sin título)")
        cuerpo = item.get("cuerpo", item.get("bajada", ""))
        print(f"  Clasificando [{i}/{total}]: {titulo[:70]}")

        resultado = clasificador_fn(titulo, cuerpo)

        if resultado["aprobado"]:
            print("    -> Aprobado")
            aprobados.append(item)
            detalles.append({"titulo": titulo, "estado": "aprobado"})
        else:
            print(f"    -> Rechazado: {resultado.get('razon', '')[:80]}")
            col_descartados.replace_one(
                {"url": item.get("url", "")},
                {
                    "url": item.get("url", ""),
                    "fecha_descarte": datetime.datetime.now(datetime.UTC).isoformat(),
                },
                upsert=True,
            )
            detalles.append(
                {
                    "titulo": titulo,
                    "estado": "rechazado",
                    "razon": resultado.get("razon", ""),
                }
            )

    if aprobados:
        print(f"  Generando embeddings para {len(aprobados)} artículo(s) aprobado(s)...")
        from embeddings import texto_para_embedding
        from lm_studio import calcular_embeddings_batch

        textos = [texto_para_embedding(item) for item in aprobados]
        embeddings = calcular_embeddings_batch(textos)

        for item, vec in zip(aprobados, embeddings):
            if vec:
                item["embedding"] = vec

        operaciones = [
            UpdateOne({"url": item["url"]}, {"$set": item, "$setOnInsert": {"usado_para_articulo": False}}, upsert=True)
            for item in aprobados
        ]
        coleccion.bulk_write(operaciones)

    return {
        "total": len(items),
        "aprobados": len(aprobados),
        "rechazados": len(items) - len(aprobados),
        "detalles": detalles,
    }


def obtener_urls_procesados() -> set[str]:
    urls = set()
    for col in COLECCIONES_URLS:
        for doc in col.find({}, {"url": 1, "_id": 0}):
            if url := doc.get("url"):
                urls.add(url)
    return urls
