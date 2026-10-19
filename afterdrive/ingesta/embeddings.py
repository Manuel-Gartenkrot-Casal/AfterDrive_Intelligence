"""
embeddings.py — Vectores de significado para los artículos.

Cada artículo lleva un campo 'embedding' (lista de 2048 floats) calculado UNA sola
vez a partir de su título + cuerpo. Sirve para agrupar artículos por tópico y para
detectar duplicados, comparando vectores con similitud coseno (pura matemática, sin
volver a llamar al modelo).

Uso:
    python -m afterdrive.ingesta.embeddings          # backfill: vectoriza los que aún no tienen embedding
"""

import math

from afterdrive.db import col_afterdrive, col_articulos
from afterdrive.ia import llm

# Colecciones de contenido (excluye 'articulos_descartados').
COLECCIONES_CONTENIDO = [col_articulos, col_afterdrive]


def coseno(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores (1.0 = idénticos, ~0 = sin relación).

    Largos distintos = modelos distintos: 0.0 en vez de un número sin sentido.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def vector_de(doc: dict, modelo: str) -> list[float] | None:
    """El embedding del doc si se puede comparar con vectores de `modelo`.

    Sin etiqueta = vector anterior al cambio de modelo: se acepta y coseno()
    descarta los de otro largo.
    """
    # ponytail: un vector viejo sin etiqueta y del mismo largo que el modelo
    # nuevo se compararía mal; correr el backfill tras cambiar de modelo lo evita.
    etiqueta = doc.get("embedding_modelo")
    return doc.get("embedding") if etiqueta in (None, modelo) else None


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
    modelo = llm.modelo_embeddings()
    if doc.get("embedding") and doc.get("embedding_modelo") == modelo:
        return False
    vec = llm.embeber([texto_para_embedding(doc)])[0]
    if not vec:
        return False
    coleccion.update_one({"_id": doc["_id"]}, {"$set": {"embedding": vec, "embedding_modelo": modelo}})
    return True


def backfill(colecciones=None) -> dict:
    """Deja todos los artículos con un vector del modelo actual. Idempotente.

    Después de cambiar de modelo (p. ej. a la API paga) re-vectoriza lo
    guardado, para que el RAG compare vectores del mismo modelo. Los vectores
    viejos sin etiqueta y del largo del modelo actual solo se etiquetan.

    Returns:
        {coleccion: {"vectorizados": n, "etiquetados": n}}
    """
    colecciones = colecciones or COLECCIONES_CONTENIDO
    modelo = llm.modelo_embeddings()
    sonda = llm.embeber(["autopartes"])[0]
    if not sonda:
        # Sin el largo del modelo actual no se sabe qué vectores viejos sirven:
        # seguir re-vectorizaría toda la base (plata o rate limit) o la recorrería fallando.
        print(f"[ERROR] El proveedor de embeddings ({modelo}) no respondió. Backfill cancelado.", flush=True)
        return {}
    dim = len(sonda)
    stats = {}
    for col in colecciones:
        vectorizados = etiquetados = 0
        for doc in col.find({"embedding_modelo": {"$ne": modelo}}):
            vec = doc.get("embedding")
            # ponytail: mismo largo se asume mismo modelo. Falla solo si el modelo
            # nuevo tiene el largo del viejo; ahí hay que borrar los vectores antes.
            if vec and "embedding_modelo" not in doc and len(vec) == dim:
                col.update_one({"_id": doc["_id"]}, {"$set": {"embedding_modelo": modelo}})
                etiquetados += 1
            elif asegurar_embedding(doc, col):
                vectorizados += 1
        stats[col.name] = {"vectorizados": vectorizados, "etiquetados": etiquetados}
    return stats


if __name__ == "__main__":
    print(f"Backfill de embeddings con {llm.modelo_embeddings()} (artículos sin vector de este modelo)...\n")
    stats = backfill()
    for nombre, n in stats.items():
        print(f"  {nombre:<12} +{n['vectorizados']} vectorizados, {n['etiquetados']} etiquetados")
