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

Una noticia que ya alimentó una nota en los últimos DIAS_SIN_REPETIR días
solo se usa si no alcanzan las demás: así dos notas seguidas no salen de la
misma noticia. Al prompt va su ficha (resumen, hechos, cifras, empresas, ver
lm_studio.fichar_articulo) más un extracto del cuerpo; a las elegidas que no
tienen ficha se les arma en el momento y queda guardada.
"""

from __future__ import annotations

import datetime
import math
import os
from dataclasses import dataclass, field

CANDIDATOS = 200          # noticias recientes que se consideran
CANDIDATOS_VECTOR = 100   # con Atlas Vector Search: las más parecidas de toda la base
VIDA_MEDIA_DIAS = 10      # a los 10 días una noticia pesa la mitad por recencia
PESO_SIMILITUD = 0.65
PESO_RECENCIA = 0.25
PESO_NO_USADA = 0.10
DIAS_SIN_REPETIR = 30


@dataclass
class Noticia:
    id: object
    titulo: str
    cuerpo: str
    url: str = ""
    fuente: str = ""
    fecha: datetime.datetime | None = None
    usada: bool = False
    usada_reciente: bool = False   # alimentó una nota en los últimos DIAS_SIN_REPETIR días
    ficha: dict | None = field(default=None, repr=False)
    embedding: list[float] | None = field(default=None, repr=False)
    puntaje: float = 0.0


def _coseno(a, b) -> float:
    if not a or not b or len(a) != len(b):  # largos distintos = modelos distintos
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


def _texto_ficha(f: dict) -> str:
    partes = [f"Resumen: {f.get('resumen', '')}"]
    for clave, nombre in (("hechos", "Hechos"), ("cifras", "Cifras"), ("empresas", "Empresas")):
        if f.get(clave):
            partes.append(f"{nombre}:\n" + "\n".join(f"- {x}" for x in f[clave]))
    if f.get("fecha"):
        partes.append(f"Fecha: {f['fecha']}")
    return "\n".join(partes)


def formatear(noticias: list[Noticia], max_chars: int = 7000) -> str:
    """Bloque de contexto para el prompt, repartiendo el presupuesto entre las noticias.

    Con ficha va la ficha y un extracto corto del cuerpo (para matices y citas);
    sin ficha, el cuerpo recortado como antes.
    """
    if not noticias:
        return ""
    por_noticia = max(400, max_chars // len(noticias))
    bloques = []
    for i, n in enumerate(noticias, 1):
        if n.ficha:
            ficha = _texto_ficha(n.ficha)
            extracto = _recortar(n.cuerpo or "", max(300, por_noticia - len(ficha)))
            cuerpo = ficha + (f"\nExtracto: {extracto}" if extracto else "")
        else:
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


def _fecha(d: dict) -> datetime.datetime | None:
    """Fecha de publicación del artículo; si falta o no se entiende, la de guardado.

    Antes se usaba siempre la de guardado (el _id): un artículo viejo
    scrapeado hoy pesaba como recién publicado.
    """
    guardado = d["_id"].generation_time if hasattr(d.get("_id"), "generation_time") else None
    texto = str(d.get("fecha") or "").strip()
    try:
        publicado = datetime.datetime.fromisoformat(texto[:10]).replace(tzinfo=datetime.UTC)
    except ValueError:
        return guardado
    # Una fecha futura es un error de extracción: no puede ganarle a todas.
    if guardado and publicado > guardado + datetime.timedelta(days=1):
        return guardado
    return publicado


def _usada_reciente(d: dict, ahora: datetime.datetime | None = None) -> bool:
    usado_en = str(d.get("usado_en") or "")
    if not usado_en:
        return False   # las marcadas antes de guardar la fecha cuentan como usadas hace mucho
    try:
        cuando = datetime.datetime.fromisoformat(usado_en)
    except ValueError:
        return False
    ahora = ahora or datetime.datetime.now(datetime.UTC)
    return ahora - cuando < datetime.timedelta(days=DIAS_SIN_REPETIR)


def _desde_doc(d: dict) -> Noticia:
    return Noticia(
        id=d["_id"],
        titulo=d.get("titulo") or "(sin título)",
        cuerpo=d.get("cuerpo") or d.get("bajada") or "",
        url=d.get("url", ""),
        fuente=d.get("fuente", "") if d.get("fuente") not in ("custom", None) else "",
        fecha=_fecha(d),
        usada=bool(d.get("usado_para_articulo")),
        usada_reciente=_usada_reciente(d),
        ficha=d.get("ficha") if isinstance(d.get("ficha"), dict) else None,
        embedding=d.get("embedding"),
    )


_CAMPOS = {"titulo": 1, "cuerpo": 1, "bajada": 1, "url": 1, "fuente": 1, "fecha": 1, "embedding": 1,
           "embedding_modelo": 1, "usado_para_articulo": 1, "usado_en": 1, "ficha": 1}


def _parecidas_en_atlas(col, vec: list[float] | None, modelo: str) -> list[dict]:
    """Las noticias más parecidas de TODA la base, con Atlas Vector Search.

    Solo si ATLAS_VECTOR_INDEX tiene el nombre del índice. Sin él (o si Atlas
    falla) devuelve [] y alcanza con las recientes: es una mejora, no un
    requisito. El índice se crea en Atlas (ver docs/08-despliegue.md).

    Filtra por embedding_modelo: vectores de otro modelo no se comparan. Para
    eso el índice declara ese campo como "filter"; con un índice que no lo
    tiene, Atlas rechaza la búsqueda y se reintenta sin filtro (vector_de()
    descarta después los de otro modelo).
    """
    indice = os.getenv("ATLAS_VECTOR_INDEX", "").strip()
    if not indice or not vec:
        return []
    busqueda = {
        "index": indice, "path": "embedding", "queryVector": vec,
        "numCandidates": CANDIDATOS_VECTOR * 10, "limit": CANDIDATOS_VECTOR,
        "filter": {"embedding_modelo": {"$eq": modelo}},
    }

    def _buscar(etapa: dict) -> list[dict]:
        return list(col.aggregate([
            {"$vectorSearch": etapa},
            {"$match": {"cuerpo": {"$exists": True, "$ne": ""}}},
            {"$project": _CAMPOS},
        ]))

    from pymongo.errors import OperationFailure

    try:
        try:
            return _buscar(busqueda)
        except OperationFailure as e:
            # Atlas rechazó la consulta (índice sin el filter); no es un timeout ni la red.
            print(f"  [AVISO] Atlas Vector Search rechazó el filtro por modelo ({e}); se reintenta sin filtro. "
                  "Agregá embedding_modelo como filter al índice (docs/08-despliegue.md).", flush=True)
        return _buscar({k: v for k, v in busqueda.items() if k != "filter"})
    except Exception as e:
        print(f"  [AVISO] Atlas Vector Search no respondió ({e}); se usan las noticias recientes.", flush=True)
        return []


def seleccionar(consulta: str, limite: int = 5) -> list[Noticia]:
    """Las `limite` noticias más útiles para una nota sobre `consulta`.

    Candidatas: las CANDIDATOS más recientes y, si hay índice vectorial en
    Atlas, también las más parecidas de toda la base. El orden final lo decide
    rankear() (parecido, recencia y si ya se usó) igual en los dos casos.
    """
    from afterdrive.db import col_articulos
    from afterdrive.ia import llm
    from afterdrive.ingesta.embeddings import vector_de

    vec = None
    modelo = llm.modelo_embeddings()  # antes de vectorizar: la etiqueta es del modelo que lo calculó
    try:
        vec = llm.embeber([consulta], tipo="query")[0]
    except Exception as e:
        print(f"  [AVISO] Sin embeddings para elegir noticias ({e}); se usan las más recientes.", flush=True)

    recientes = list(col_articulos.find({"cuerpo": {"$exists": True, "$ne": ""}}, _CAMPOS)
                     .sort("_id", -1).limit(CANDIDATOS))
    docs = {d["_id"]: d for d in recientes + _parecidas_en_atlas(col_articulos, vec, modelo)}
    if not docs:
        return []
    noticias = []
    for d in docs.values():
        n = _desde_doc(d)
        n.embedding = vector_de(d, modelo)  # vectores de otro modelo no se comparan
        noticias.append(n)
    ahora = datetime.datetime.now(datetime.UTC)
    elegidas = elegir(rankear(noticias, vec, ahora), limite)
    _completar_fichas(elegidas, col_articulos)
    return elegidas


def elegir(ranking: list[Noticia], limite: int) -> list[Noticia]:
    """Las mejores del ranking, dejando para el final las usadas hace poco."""
    frescas = [n for n in ranking if not n.usada_reciente]
    return (frescas + [n for n in ranking if n.usada_reciente])[:limite]


def _completar_fichas(noticias: list[Noticia], col) -> None:
    """Arma la ficha de las elegidas que no la tienen (artículos guardados antes de las fichas)."""
    from afterdrive.ingesta.ingesta import fichas_activas

    if not fichas_activas():
        return
    from afterdrive.ia import lm_studio

    for n in noticias:
        if n.ficha or not (n.cuerpo or "").strip():
            continue
        n.ficha = lm_studio.fichar_articulo(n.titulo, n.cuerpo)
        if n.ficha:
            try:
                col.update_one({"_id": n.id}, {"$set": {"ficha": n.ficha}})
            except Exception as e:
                print(f"  [AVISO] No se pudo guardar la ficha de '{n.titulo[:60]}': {e}", flush=True)


def marcar_usadas(noticias: list[Noticia]) -> None:
    from afterdrive.db import col_articulos

    if noticias:
        col_articulos.update_many(
            {"_id": {"$in": [n.id for n in noticias]}},
            {"$set": {"usado_para_articulo": True, "usado_en": datetime.datetime.now(datetime.UTC).isoformat()}},
        )
