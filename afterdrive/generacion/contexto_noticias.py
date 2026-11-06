"""
contexto_noticias.py — Qué noticias scrapeadas alimentan una nota.

Interfaz:
    seleccionar(consulta, limite=5) -> list[Noticia]
    seleccionar_archivo(consulta, limite=2, dias_min=90) -> list[Noticia]
                                       noticias viejas parecidas al tema, para dar perspectiva
    formatear(noticias, max_chars=7000) -> str
    formatear_archivo(noticias, max_chars=2500) -> str
    marcar_usadas(noticias) -> None
    urls_liberadas() -> set[str]       noticias de notas rechazadas, que vuelven a estar disponibles
    con_foto(noticias, max_busquedas=3, limite=4) -> list[Noticia]   las que tienen foto
    todas_las_fotos(noticias) -> list[Noticia]       una por foto (cada noticia guarda varias)
    mas_fotos(noticias, max_busquedas=5) -> list[Noticia]   relee las páginas que no tienen la lista
    imagen_de(noticia) -> {"url", "alt", "origen"}
    tendencias(noticias, ahora) -> None   puntúa cuántos medios cubren el mismo tema esta semana
    fuentes_recientes() -> {medio: proporción}   en qué parte de las últimas notas se usó cada medio

Antes la generación de notas no leía las noticias scrapeadas: el modelo
escribía solo con las categorías y los ejemplos de estilo, y los prompts le
pedían "usar datos del contexto" que nunca recibía. Acá se eligen las
noticias más útiles para el pedido: parecidas al tema (embeddings), recientes
y todavía no usadas en otra nota.

Además, 1 o 2 noticias del archivo (de más de ARCHIVO_DIAS_MIN días) parecidas
al tema dan perspectiva ("hace un año…", "pasó de X a Y"). rankear() no sirve
para eso: con una vida media de 10 días una noticia de hace 3 meses casi no
pesa, y solo mira las CANDIDATOS más recientes. seleccionar_archivo() busca
entre las viejas y las ordena solo por parecido.

Tendencia antes que recencia: una noticia que cubren varios medios distintos
en la última semana (el mismo tema, por embeddings o, sin ellos, por las
palabras del título) pesa más que una recién publicada que nadie más levantó.

Medios variados: un medio que alimentó muchas de las últimas notas pierde
puntos, y una nota lleva como mucho MAX_POR_FUENTE noticias del mismo medio
(cada una que se suma de un medio ya elegido resta PENALIDAD_MISMA_FUENTE).

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
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse

CANDIDATOS = 200          # noticias recientes que se consideran
CANDIDATOS_VECTOR = 100   # con Atlas Vector Search: las más parecidas de toda la base
VIDA_MEDIA_DIAS = 10      # a los 10 días una noticia pesa la mitad por recencia
PESO_SIMILITUD = 0.50
PESO_TENDENCIA = 0.20     # varios medios cubren el mismo tema esta semana
PESO_RECENCIA = 0.15
PESO_NO_USADA = 0.10
PESO_FUENTE_FRECUENTE = 0.15   # se resta: el medio alimentó muchas de las últimas notas
TENDENCIA_DIAS = 7             # la ventana en la que se cuenta quién más cubrió el tema
TENDENCIA_SIMILITUD = 0.80     # coseno desde el que dos noticias son el mismo tema
TENDENCIA_PALABRAS = 0.35      # sin embeddings: parte de palabras del título en común
TENDENCIA_SATURA = 3           # con 3 medios más cubriéndolo, la tendencia es máxima
MAX_POR_FUENTE = 2             # noticias del mismo medio en una nota
PENALIDAD_MISMA_FUENTE = 0.10  # por cada noticia ya elegida de ese medio
NOTAS_PARA_FUENTES = 15        # últimas notas que se miran para saber qué medios se repiten
DIAS_SIN_REPETIR = 30
ARCHIVO_DIAS_MIN = 90          # desde cuándo una noticia es "de archivo"
ARCHIVO_CANDIDATOS = 400       # viejas que se miran (por fecha de guardado y por fecha de publicación)
ARCHIVO_SIMILITUD_MIN = 0.5    # menos parecida que esto no aporta perspectiva: mejor ninguna


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
    imagen: dict | None = None     # {"url", "alt"}: la foto del artículo (imagen_articulo.extraer)
    imagen_buscada: bool = False   # ya se intentó sacarla (aunque no tuviera): no se vuelve a descargar
    imagenes: list[dict] | None = None   # todas las fotos del artículo; None = scrapeado antes de guardarlas
    refrescable: bool = True       # su `imagen` es la principal de la página: si deja de responder se relee
    liberada: bool = False         # solo alimentó notas rechazadas: vuelve a contar como no usada
    antiguedad_dias: int | None = None   # solo las del archivo: días desde su fecha
    tendencia: float = 0.0         # 0 a 1: cuántos otros medios cubren el tema esta semana


def _coseno(a, b) -> float:
    if not a or not b or len(a) != len(b):  # largos distintos = modelos distintos
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def fuente_de(n: Noticia) -> str:
    """El medio de la noticia: el dominio de su URL (sin www.), o el nombre de la fuente."""
    dom = urlparse(n.url or "").netloc.lower().removeprefix("www.")
    return dom or (n.fuente or "").strip().lower() or f"id:{n.id}"


def _palabras(titulo: str) -> set[str]:
    plano = unicodedata.normalize("NFKD", (titulo or "").lower()).encode("ascii", "ignore").decode()
    return {p for p in re.findall(r"[a-z0-9]+", plano) if len(p) >= 4}


def _normalizado(v):
    if not v:
        return None
    norma = math.sqrt(sum(x * x for x in v))
    return [x / norma for x in v] if norma else None


def tendencias(noticias: list[Noticia], ahora: datetime.datetime) -> None:
    """Le pone a cada noticia su `tendencia` (0 a 1): cuántos OTROS medios publicaron el mismo
    tema en los últimos TENDENCIA_DIAS días. Satura en TENDENCIA_SATURA medios.

    El mismo tema: coseno de embeddings >= TENDENCIA_SIMILITUD, o, si alguna de las dos no
    tiene vector, títulos con TENDENCIA_PALABRAS de palabras en común. Solo pueden ser
    tendencia las de los últimos 2 × TENDENCIA_DIAS días.
    """
    for n in noticias:
        n.tendencia = 0.0
    corte = ahora - datetime.timedelta(days=TENDENCIA_DIAS)
    limite = ahora - datetime.timedelta(days=2 * TENDENCIA_DIAS)
    evaluar = [n for n in noticias if n.fecha and n.fecha >= limite]
    en_ventana = [i for i, n in enumerate(evaluar) if n.fecha >= corte]
    if not en_ventana:
        return
    vec = [_normalizado(n.embedding) for n in evaluar]
    pal = [_palabras(n.titulo) for n in evaluar]
    medio = [fuente_de(n) for n in evaluar]
    iguales = _mismo_tema(vec, pal, en_ventana)
    for i, n in enumerate(evaluar):
        otros = {medio[j] for j in en_ventana if medio[j] != medio[i] and iguales(i, j)}
        n.tendencia = min(1.0, len(otros) / TENDENCIA_SATURA)


def _mismo_tema(vec: list, pal: list[set[str]], columnas: list[int]):
    """f(i, j) -> bool: si las noticias i y j hablan del mismo tema."""
    def una(i: int, j: int) -> bool:
        a, b = vec[i], vec[j]
        if a and b and len(a) == len(b):
            return sum(x * y for x, y in zip(a, b, strict=True)) >= TENDENCIA_SIMILITUD
        pa, pb = pal[i], pal[j]
        return bool(pa and pb) and len(pa & pb) / len(pa | pb) >= TENDENCIA_PALABRAS

    if not (all(vec) and len({len(v) for v in vec}) == 1):
        return una
    try:   # con numpy (si está instalado) se comparan todas de una vez
        import numpy as np
    except ImportError:
        return una
    m = np.array(vec, dtype=float)
    parecido = m @ m[columnas].T >= TENDENCIA_SIMILITUD
    columna = {j: k for k, j in enumerate(columnas)}
    return lambda i, j: bool(parecido[i, columna[j]])


def rankear(noticias: list[Noticia], consulta_vec: list[float] | None, ahora: datetime.datetime,
            uso_fuentes: dict[str, float] | None = None) -> list[Noticia]:
    """Ordena por utilidad para la nota: similitud, tendencia, recencia, no usada y medio poco repetido.

    Sin vector de consulta (embeddings caídos) mandan la tendencia y la recencia.
    uso_fuentes: {medio: parte de las últimas notas que lo usaron} (ver fuentes_recientes).
    """
    tendencias(noticias, ahora)
    uso_fuentes = uso_fuentes or {}
    for n in noticias:
        dias = max(0.0, (ahora - n.fecha).total_seconds() / 86400) if n.fecha else 60.0
        recencia = 0.5 ** (dias / VIDA_MEDIA_DIAS)
        similitud = _coseno(consulta_vec, n.embedding) if consulta_vec else 0.0
        peso_sim = PESO_SIMILITUD if consulta_vec else 0.0
        n.puntaje = (peso_sim * similitud + PESO_TENDENCIA * n.tendencia + PESO_RECENCIA * recencia
                     + PESO_NO_USADA * (0 if n.usada else 1)
                     - PESO_FUENTE_FRECUENTE * uso_fuentes.get(fuente_de(n), 0.0))
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
        origen = " | ".join(x for x in (n.fuente, n.url) if x)
        bloques.append(f"[{i}] {n.titulo}\n{('Fuente: ' + origen) if origen else ''}\n{_cuerpo(n, por_noticia)}".strip())
    return "\n\n".join(bloques)


def _cuerpo(n: Noticia, limite: int) -> str:
    if n.ficha:
        ficha = _texto_ficha(n.ficha)
        extracto = _recortar(n.cuerpo or "", max(300, limite - len(ficha)))
        return ficha + (f"\nExtracto: {extracto}" if extracto else "")
    return _recortar(n.cuerpo or "", limite)


def antiguedad(dias: int | None) -> str:
    """"hace 4 meses", "hace 1 año y 2 meses": cómo se le cuenta al modelo de cuándo es el dato."""
    if dias is None:
        return "fecha desconocida"
    if dias < 60:
        return f"hace {dias} días"
    meses = round(dias / 30.4)
    if meses < 12:
        return f"hace {meses} meses"
    anios, meses = divmod(meses, 12)
    texto = "hace 1 año" if anios == 1 else f"hace {anios} años"
    return texto + ("" if not meses else " y 1 mes" if meses == 1 else f" y {meses} meses")


def formatear_archivo(noticias: list[Noticia], max_chars: int = 2500) -> str:
    """Las noticias del archivo, con la fecha y la antigüedad de cada una ([A1], [A2])."""
    if not noticias:
        return ""
    por_noticia = max(400, max_chars // len(noticias))
    bloques = []
    for i, n in enumerate(noticias, 1):
        fecha = n.fecha.date().isoformat() if n.fecha else "sin fecha"
        origen = " | ".join(x for x in (n.fuente, n.url) if x)
        bloques.append(f"[A{i}] {n.titulo}\nFecha: {fecha} ({antiguedad(n.antiguedad_dias)})"
                       f"{(' | Fuente: ' + origen) if origen else ''}\n{_cuerpo(n, por_noticia)}".strip())
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
        imagen=d.get("imagen") if isinstance(d.get("imagen"), dict) and d["imagen"].get("url") else None,
        imagen_buscada="imagen" in d,
        imagenes=[i for i in d["imagenes"] if isinstance(i, dict) and i.get("url")]
        if isinstance(d.get("imagenes"), list) else None,
    )


_CAMPOS = {"titulo": 1, "cuerpo": 1, "bajada": 1, "url": 1, "fuente": 1, "fecha": 1, "embedding": 1,
           "embedding_modelo": 1, "usado_para_articulo": 1, "usado_en": 1, "ficha": 1, "imagen": 1,
           "imagenes": 1}


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
    from afterdrive.ingesta.embeddings import vector_de

    vec, modelo = _vector_consulta(consulta)
    if vec is None:
        print("  [AVISO] Sin embeddings para elegir noticias; se usan las más recientes.", flush=True)

    recientes = list(col_articulos.find({"cuerpo": {"$exists": True, "$ne": ""}}, _CAMPOS)
                     .sort("_id", -1).limit(CANDIDATOS))
    docs = {d["_id"]: d for d in recientes + _parecidas_en_atlas(col_articulos, vec, modelo)}
    if not docs:
        return []
    liberadas = urls_liberadas()
    noticias = []
    for d in docs.values():
        n = _desde_doc(d)
        n.embedding = vector_de(d, modelo)  # vectores de otro modelo no se comparan
        if (n.usada or n.usada_reciente) and _url_clave(n.url) in liberadas:
            n.usada = n.usada_reciente = False
            n.liberada = True
        noticias.append(n)
    ahora = datetime.datetime.now(datetime.UTC)
    elegidas = elegir(rankear(noticias, vec, ahora, fuentes_recientes()), limite)
    medios = Counter(fuente_de(n) for n in elegidas)
    en_tendencia = sum(n.tendencia > 0 for n in elegidas)
    print(f"  Noticias elegidas: {len(elegidas)} de {len(medios)} medio(s)"
          f"{f', {en_tendencia} en tendencia' if en_tendencia else ''}.", flush=True)
    _completar_fichas(elegidas, col_articulos)
    return elegidas


def _vector_consulta(consulta: str) -> tuple[list[float] | None, str]:
    """(vector de la consulta o None si los embeddings fallan, modelo con el que se calculó)."""
    from afterdrive.ia import llm

    modelo = llm.modelo_embeddings()  # antes de vectorizar: la etiqueta es del modelo que lo calculó
    try:
        return llm.embeber([consulta], tipo="query")[0], modelo
    except Exception as e:
        print(f"  [AVISO] Embeddings no disponibles: {e}", flush=True)
        return None, modelo


def seleccionar_archivo(consulta: str, limite: int = 2, dias_min: int = ARCHIVO_DIAS_MIN,
                        excluir=()) -> list[Noticia]:
    """Hasta `limite` noticias de hace más de `dias_min` días parecidas a `consulta`, para dar perspectiva.

    Ordenadas solo por parecido (no por recencia ni por si ya se usaron: una
    noticia vieja que alimentó otra nota sigue sirviendo de referencia). Sin
    embeddings no hay orden posible y devuelve []; por debajo de
    ARCHIVO_SIMILITUD_MIN tampoco: mejor ninguna que una que no viene al caso.
    `excluir`: _id de noticias que ya están en la nota.
    """
    if limite <= 0:
        return []
    from bson import ObjectId

    from afterdrive.db import col_articulos
    from afterdrive.ingesta.embeddings import vector_de

    vec, modelo = _vector_consulta(consulta)
    if vec is None:
        return []
    ahora = datetime.datetime.now(datetime.UTC)
    corte = ahora - datetime.timedelta(days=dias_min)
    con_cuerpo = {"cuerpo": {"$exists": True, "$ne": ""}}
    try:
        # Guardadas hace más de dias_min días, y publicadas antes aunque se hayan scrapeado hace poco.
        viejas = list(col_articulos.find({**con_cuerpo, "_id": {"$lt": ObjectId.from_datetime(corte)}}, _CAMPOS)
                      .sort("_id", -1).limit(ARCHIVO_CANDIDATOS))
        por_fecha = list(col_articulos.find({**con_cuerpo, "fecha": {"$lt": corte.date().isoformat(), "$gte": "1990"}},
                                            _CAMPOS).sort("fecha", -1).limit(ARCHIVO_CANDIDATOS))
    except Exception as e:
        print(f"  [AVISO] No se pudo leer el archivo de noticias: {e}", flush=True)
        return []
    excluir = set(excluir)
    docs = {d["_id"]: d for d in viejas + por_fecha + _parecidas_en_atlas(col_articulos, vec, modelo)}
    candidatas, titulos = [], set()
    for d in docs.values():
        if d["_id"] in excluir:
            continue
        n = _desde_doc(d)
        if not n.fecha or n.fecha > corte:
            continue
        n.puntaje = _coseno(vec, vector_de(d, modelo))
        if n.puntaje < ARCHIVO_SIMILITUD_MIN:
            continue
        n.antiguedad_dias = (ahora - n.fecha).days
        candidatas.append(n)
    elegidas = []
    for n in sorted(candidatas, key=lambda n: n.puntaje, reverse=True):
        clave = " ".join(n.titulo.lower().split())
        if clave in titulos:   # la misma noticia publicada por dos sitios
            continue
        titulos.add(clave)
        elegidas.append(n)
        if len(elegidas) == limite:
            break
    _completar_fichas(elegidas, col_articulos)
    return elegidas


NOTAS_PARA_LIBERAR = 300   # notas recientes que se miran para saber qué noticias liberar


def _url_clave(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def urls_liberadas(col=None) -> set[str]:
    """URLs de noticias que solo alimentaron notas rechazadas: se pueden volver a usar.

    marcar_usadas() las marca al guardar la nota, y si el equipo la rechaza
    quedaban postergadas DIAS_SIN_REPETIR días sin haber llegado al blog. Si
    también están en otra nota que no se rechazó (borrador, aprobada,
    publicada), siguen contando como usadas. Se calcula cada vez desde las
    notas, así que si una nota vuelve de rechazada a borrador sus noticias
    vuelven a estar usadas. Si Mongo falla, ninguna.
    """
    from afterdrive.db import ESTADO_RECHAZADA

    if col is None:
        from afterdrive.db import db
        col = db["notas_fase2"]
    rechazadas, en_uso = set(), set()
    try:
        for d in col.find({}, {"estado": 1, "fuentes.url": 1}).sort("generado_en", -1).limit(NOTAS_PARA_LIBERAR):
            urls = {_url_clave(f.get("url")) for f in d.get("fuentes") or [] if isinstance(f, dict) and f.get("url")}
            (rechazadas if d.get("estado") == ESTADO_RECHAZADA else en_uso).update(urls)
    except Exception as e:
        print(f"  [AVISO] No se pudieron leer las notas rechazadas para reutilizar sus noticias: {e}", flush=True)
        return set()
    return rechazadas - en_uso


def fuentes_recientes(col=None, notas: int = NOTAS_PARA_FUENTES) -> dict[str, float]:
    """{medio: parte (0 a 1) de las últimas `notas` notas que usaron alguna noticia suya}. {} si Mongo falla."""
    if col is None:
        from afterdrive.db import db
        col = db["notas_fase2"]
    try:
        docs = list(col.find({"fuentes.url": {"$exists": True}}, {"fuentes.url": 1}).sort("_id", -1).limit(notas))
    except Exception as e:
        print(f"  [AVISO] No se pudieron leer los medios de las últimas notas: {e}", flush=True)
        return {}
    if not docs:
        return {}
    conteo = Counter()
    for d in docs:
        conteo.update({fuente_de(Noticia(None, "", "", url=f.get("url", "")))
                       for f in d.get("fuentes") or [] if isinstance(f, dict) and f.get("url")})
    return {medio: veces / len(docs) for medio, veces in conteo.items()}


def elegir(ranking: list[Noticia], limite: int) -> list[Noticia]:
    """Las mejores del ranking, dejando para el final las usadas hace poco y variando los medios.

    De un mismo medio entran como mucho MAX_POR_FUENTE, y cada una que ya entró le resta
    PENALIDAD_MISMA_FUENTE a las siguientes de ese medio. Si así no se llega a `limite`,
    se completa sin el tope (mejor repetir medio que escribir con menos noticias).
    """
    elegidas: list[Noticia] = []
    por_medio: Counter = Counter()
    frescas = [n for n in ranking if not n.usada_reciente]
    grupos = (frescas, [n for n in ranking if n.usada_reciente])
    for con_tope in (True, False):
        for grupo in grupos:
            quedan = [n for n in grupo if n not in elegidas]
            while quedan and len(elegidas) < limite:
                validas = [n for n in quedan if not con_tope or por_medio[fuente_de(n)] < MAX_POR_FUENTE]
                if not validas:
                    break
                mejor = max(validas, key=lambda n: n.puntaje - PENALIDAD_MISMA_FUENTE * por_medio[fuente_de(n)])
                elegidas.append(mejor)
                por_medio[fuente_de(mejor)] += 1
                quedan.remove(mejor)
        if len(elegidas) >= limite:
            break
    return elegidas


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


def con_foto(noticias: list[Noticia], max_busquedas: int = 3, limite: int = 4) -> list[Noticia]:
    """Las noticias que tienen foto, en el orden recibido (hasta `limite`).

    Los artículos scrapeados antes de que se guardara la imagen no la tienen:
    a esos se les descarga la página una vez (hasta `max_busquedas` por nota)
    y lo encontrado queda guardado, aunque sea "no tiene".
    """
    busquedas, resultado = 0, []
    for n in noticias:
        if len(resultado) >= limite:
            break
        if not n.imagen and not n.imagen_buscada and n.url and busquedas < max_busquedas:
            busquedas += 1
            n.imagen = _buscar_imagen(n)
        if n.imagen:
            resultado.append(n)
    return resultado


def todas_las_fotos(noticias: list[Noticia]) -> list[Noticia]:
    """Una Noticia por foto: primero la principal de cada una y después las otras de sus páginas.

    Las copias llevan otra `imagen` y no se releen si la foto deja de responder
    (releer la página trae la principal, no esa).
    """
    principales = [n for n in noticias if n.imagen]
    otras = []
    for n in principales:
        for im in n.imagenes or []:
            if im["url"] != n.imagen["url"]:
                otras.append(replace(n, imagen={"url": im["url"], "alt": im.get("alt", "")}, refrescable=False))
    return principales + otras


def mas_fotos(noticias: list[Noticia], max_busquedas: int = 5) -> list[Noticia]:
    """Relee las páginas de las noticias scrapeadas antes de que se guardaran todas sus fotos
    (hasta `max_busquedas`) y devuelve una Noticia por foto encontrada. Lo encontrado queda guardado."""
    leidas = 0
    for n in noticias:
        if leidas >= max_busquedas:
            break
        if n.imagenes is None and n.url and n.id is not None:
            leidas += 1
            principal = _buscar_imagen(n)
            if principal and not n.imagen:
                n.imagen = principal
    return todas_las_fotos([n for n in noticias if n.imagenes])


def imagen_de(n: Noticia) -> dict:
    """El campo `imagen` de una nota con la foto de esta noticia (o del banco de imágenes)."""
    im = {"url": n.imagen["url"], "alt": n.imagen.get("alt", ""), "origen": {"titulo": n.titulo, "url": n.url}}
    for extra in ("credito", "atribucion", "banco"):
        if n.imagen.get(extra):
            im[extra] = n.imagen[extra]
    return im


def refrescar_imagen(n: Noticia) -> dict | None:
    """Vuelve a leer la página de la noticia para sacar su foto actual: la guardada dejó de responder
    (los sitios cambian o borran las fotos). Devuelve la nueva si cambió de URL, o None. Queda guardada."""
    anterior = (n.imagen or {}).get("url")
    if not n.url or not n.refrescable:
        return None
    nueva = _buscar_imagen(n)
    if nueva and nueva.get("url") != anterior:
        n.imagen = nueva
        return nueva
    return None


def _buscar_imagen(n: Noticia) -> dict | None:
    from afterdrive.db import col_articulos
    from afterdrive.ingesta import imagen_articulo, scraper

    print(f"  Buscando la imagen de '{n.titulo[:60]}'...", flush=True)
    try:
        html = scraper.descargar(n.url)
    except Exception as e:
        html = None
        print(f"  [AVISO] No se pudo leer la página de la noticia: {e}", flush=True)
    if not html:
        return None   # sin marcar como buscada: la próxima nota lo reintenta
    imagenes = imagen_articulo.extraer_todas(html, n.url)
    imagen = imagenes[0] if imagenes else None
    n.imagen_buscada, n.imagenes = True, imagenes
    try:
        col_articulos.update_one({"_id": n.id}, {"$set": {"imagen": imagen, "imagenes": imagenes}})
    except Exception as e:
        print(f"  [AVISO] No se pudo guardar la imagen de la noticia: {e}", flush=True)
    return imagen
