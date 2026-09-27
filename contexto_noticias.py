"""
contexto_noticias.py — Qué noticias scrapeadas alimentan una nota.

Interfaz:
    seleccionar(consulta, limite=5) -> list[Noticia]
    formatear(noticias, max_chars=7000) -> str
    marcar_usadas(noticias) -> None

Antes la generación de notas no leía las noticias scrapeadas: el modelo
escribía solo con las categorías y los ejemplos de estilo, y los prompts le
pedían "usar datos del contexto" que nunca recibía. Acá se eligen las
noticias más útiles para el pedido: parecidas al tema (embeddings), recientes
y todavía no usadas en otra nota.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field

CANDIDATOS = 200          # noticias recientes que se consideran
VIDA_MEDIA_DIAS = 10      # a los 10 días una noticia pesa la mitad por recencia
PESO_SIMILITUD = 0.65
PESO_RECENCIA = 0.25
PESO_NO_USADA = 0.10


@dataclass
class Noticia:
    id: object
    titulo: str
    cuerpo: str
    url: str = ""
    fuente: str = ""
    fecha: datetime.datetime | None = None
    usada: bool = False
    embedding: list[float] | None = field(default=None, repr=False)
    puntaje: float = 0.0


def _coseno(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def rankear(noticias: list[Noticia], consulta_vec: list[float] | None, ahora: datetime.datetime) -> list[Noticia]:
    """Ordena por utilidad para la nota: similitud, recencia y no usada.

    Sin vector de consulta (embeddings caídos) manda la recencia.
    """
    for n in noticias:
        dias = max(0.0, (ahora - n.fecha).total_seconds() / 86400) if n.fecha else 60.0
        recencia = 0.5 ** (dias / VIDA_MEDIA_DIAS)
        similitud = _coseno(consulta_vec, n.embedding) if consulta_vec else 0.0
        peso_sim = PESO_SIMILITUD if consulta_vec else 0.0
        n.puntaje = peso_sim * similitud + PESO_RECENCIA * recencia + PESO_NO_USADA * (0 if n.usada else 1)
    return sorted(noticias, key=lambda n: n.puntaje, reverse=True)


def formatear(noticias: list[Noticia], max_chars: int = 7000) -> str:
    """Bloque de contexto para el prompt, repartiendo el presupuesto entre las noticias."""
    if not noticias:
        return ""
    por_noticia = max(400, max_chars // len(noticias))
    bloques = []
    for i, n in enumerate(noticias, 1):
        cuerpo = _recortar(n.cuerpo or "", por_noticia)
        origen = " | ".join(x for x in (n.fuente, n.url) if x)
        bloques.append(f"[{i}] {n.titulo}\n{('Fuente: ' + origen) if origen else ''}\n{cuerpo}".strip())
    return "\n\n".join(bloques)


def _recortar(texto: str, limite: int) -> str:
    """Corta en el último punto antes del límite, para no dejar frases a medias."""
    texto = " ".join(texto.split())
    if len(texto) <= limite:
        return texto
    corte = texto.rfind(". ", 0, limite)
    return texto[: corte + 1] if corte > limite * 0.5 else texto[:limite].rstrip() + "..."


# ── IO (Mongo + embeddings) ───────────────────────────────────────────────────


def _desde_doc(d: dict) -> Noticia:
    return Noticia(
        id=d["_id"],
        titulo=d.get("titulo") or "(sin título)",
        cuerpo=d.get("cuerpo") or d.get("bajada") or "",
        url=d.get("url", ""),
        fuente=d.get("fuente", "") if d.get("fuente") not in ("custom", None) else "",
        fecha=d["_id"].generation_time if hasattr(d["_id"], "generation_time") else None,
        usada=bool(d.get("usado_para_articulo")),
        embedding=d.get("embedding"),
    )


def seleccionar(consulta: str, limite: int = 5) -> list[Noticia]:
    """Las `limite` noticias más útiles para una nota sobre `consulta`."""
    import llm
    from db import col_articulos

    docs = list(
        col_articulos.find(
            {"cuerpo": {"$exists": True, "$ne": ""}},
            {"titulo": 1, "cuerpo": 1, "bajada": 1, "url": 1, "fuente": 1, "embedding": 1, "usado_para_articulo": 1},
        ).sort("_id", -1).limit(CANDIDATOS)
    )
    if not docs:
        return []
    vec = None
    try:
        vec = llm.embeber([consulta], tipo="query")[0]
    except Exception as e:
        print(f"  [AVISO] Sin embeddings para elegir noticias ({e}); se usan las más recientes.", flush=True)
    ahora = datetime.datetime.now(datetime.UTC)
    return rankear([_desde_doc(d) for d in docs], vec, ahora)[:limite]


def marcar_usadas(noticias: list[Noticia]) -> None:
    from db import col_articulos

    if noticias:
        col_articulos.update_many({"_id": {"$in": [n.id for n in noticias]}}, {"$set": {"usado_para_articulo": True}})
