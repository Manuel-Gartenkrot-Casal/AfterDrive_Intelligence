"""
embeddings.py — Vectores de significado para los artículos.

Cada artículo lleva un campo 'embedding' (lista de 2048 floats) calculado UNA sola
vez a partir de su título + cuerpo. Sirve para agrupar artículos por tópico y para
detectar duplicados, comparando vectores con similitud coseno (pura matemática, sin
volver a llamar al modelo).

Uso:
    python embeddings.py          # backfill: vectoriza los que aún no tienen embedding
"""

import math

from db import col_afterdrive, col_articulos
from lm_studio import calcular_embedding

# Colecciones de contenido (excluye 'articulos_descartados').
COLECCIONES_CONTENIDO = [col_articulos, col_afterdrive]


def coseno(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores (1.0 = idénticos, ~0 = sin relación)."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def texto_para_embedding(doc: dict) -> str:
    """El texto que representa al artículo: título + cuerpo (o bajada)."""
    titulo = doc.get("titulo", "")
    cuerpo = doc.get("cuerpo", doc.get("bajada", ""))
    return f"{titulo}. {cuerpo}".strip()


def asegurar_embedding(doc: dict, coleccion) -> bool:
    """
    Calcula y guarda el embedding del doc si todavía no lo tiene.
    Devuelve True si lo agregó, False si ya existía o si falló el cálculo.
    """
    if doc.get("embedding"):
        return False
    vec = calcular_embedding(texto_para_embedding(doc))
    if not vec:
        return False
    coleccion.update_one({"_id": doc["_id"]}, {"$set": {"embedding": vec}})
    return True


def backfill(colecciones=None) -> dict:
    """Vectoriza todos los artículos que aún no tienen embedding. Idempotente."""
    colecciones = colecciones or COLECCIONES_CONTENIDO
    stats = {}
    for col in colecciones:
        agregados = 0
        for doc in col.find({"embedding": {"$exists": False}}):
            if asegurar_embedding(doc, col):
                agregados += 1
        stats[col.name] = agregados
    return stats


if __name__ == "__main__":
    print("Backfill de embeddings (solo artículos sin vector)...\n")
    stats = backfill()
    total = 0
    for nombre, n in stats.items():
        print(f"  {nombre:<12} +{n}")
        total += n
    print(f"\nTotal embeddings agregados: {total}")
