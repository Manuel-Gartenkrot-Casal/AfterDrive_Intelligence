"""
rotacion.py — Rotación automática de categorías: cada nota toca otra parte de lo elegido.

Interfaz:
    elegir(seleccionadas, recientes, cantidad=None, azar=random) -> list[str]
    categorias_recientes(base=None, notas=NOTAS_RECIENTES) -> list[list[str]]
    rotar(seleccionadas, base=None) -> list[str]

Con la rotación prendida (Crear nota → "Rotar categorías"), una nota no lleva
todas las categorías marcadas sino 1 o 2 de ellas. Se sortean con más chances
para las que menos aparecieron en las últimas notas (las de hace poco pesan
más que las viejas), y nunca sale exactamente la misma combinación que la nota
anterior. Así, con varias notas por día, no salen notas parecidas seguidas.

Sin rotación (o con una sola categoría marcada) la nota usa todas, como antes.
"""

from __future__ import annotations

import random

NOTAS_RECIENTES = 20     # notas que se miran para saber qué categorías se usaron
DECAIMIENTO = 0.8        # cada nota más vieja pesa un 20 % menos que la siguiente


def cantidad_por_nota(total: int) -> int:
    """Cuántas categorías lleva cada nota: 1 si hay pocas marcadas, 2 si hay más."""
    return 1 if total <= 3 else 2


def _uso(seleccionadas: list[str], recientes: list[list[str]]) -> dict[str, float]:
    """Cuánto se usó cada categoría en las notas recientes (la más reciente primero)."""
    uso = dict.fromkeys(seleccionadas, 0.0)
    for i, cats in enumerate(recientes):
        for c in cats or []:
            if c in uso:
                uso[c] += DECAIMIENTO ** i
    return uso


def elegir(seleccionadas: list[str], recientes: list[list[str]], cantidad: int | None = None,
           azar: random.Random | None = None) -> list[str]:
    """Las categorías de la próxima nota, sorteadas entre `seleccionadas`.

    recientes: categorías de las últimas notas, de la más nueva a la más vieja.
    Pesa más la que menos se usó: peso = 1 / (1 + uso)².
    """
    azar = azar or random
    seleccionadas = list(dict.fromkeys(seleccionadas))
    if len(seleccionadas) <= 1:
        return seleccionadas
    cantidad = max(1, min(cantidad or cantidad_por_nota(len(seleccionadas)), len(seleccionadas)))
    uso = _uso(seleccionadas, recientes)
    ultima = set(recientes[0]) if recientes else set()

    def sortear() -> list[str]:
        quedan, elegidas = list(seleccionadas), []
        while quedan and len(elegidas) < cantidad:
            pesos = [1.0 / (1.0 + uso[c]) ** 2 for c in quedan]
            c = azar.choices(quedan, weights=pesos, k=1)[0]
            quedan.remove(c)
            elegidas.append(c)
        return elegidas

    elegidas = sortear()
    for _ in range(10):   # misma combinación que la nota anterior: se vuelve a sortear
        if set(elegidas) != ultima:
            break
        elegidas = sortear()
    if set(elegidas) == ultima:   # el azar insistió: se cambia la más usada por la menos usada que quede
        resto = sorted((c for c in seleccionadas if c not in elegidas), key=lambda c: uso[c])
        if resto:
            elegidas[max(range(len(elegidas)), key=lambda i: uso[elegidas[i]])] = resto[0]
    return sorted(elegidas, key=seleccionadas.index)


def categorias_recientes(base=None, notas: int = NOTAS_RECIENTES) -> list[list[str]]:
    """Las categorías de las últimas notas, de la más nueva a la más vieja. [] si Mongo falla."""
    try:
        if base is None:
            from afterdrive.db import db as base
        docs = base["notas_fase2"].find({"categorias": {"$exists": True}}, {"categorias": 1}).sort("_id", -1).limit(notas)
        return [list(d.get("categorias") or []) for d in docs]
    except Exception as e:
        print(f"  [AVISO] No se pudieron leer las notas recientes para rotar categorías: {e}", flush=True)
        return []


def rotar(seleccionadas: list[str], base=None) -> list[str]:
    """Las categorías de la próxima nota con la rotación prendida (lo imprime en el log)."""
    elegidas = elegir(seleccionadas, categorias_recientes(base))
    if len(elegidas) < len(set(seleccionadas)):
        print(f"[Rotación] Esta nota usa: {', '.join(elegidas)} (de {len(set(seleccionadas))} marcadas).", flush=True)
    return elegidas
