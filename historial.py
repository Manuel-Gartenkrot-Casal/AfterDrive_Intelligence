"""
historial.py — Consulta del historial de Artículos y Notas guardados.

Interfaz:
    resumen(base=None) -> conteos por sección, publicadas y borradores
    listar(seccion, pagina=1, por_pagina=20, q="", estado="todos", base=None) -> página
    detalle(seccion, coleccion, item_id, base=None) -> ítem con el contenido completo
    cambiar_estado(coleccion, item_id, estado, base=None) -> ítem actualizado

Secciones:
    generados_aprobados     Notas Fase 1 (articulos_generados) y Fase 2 (notas_fase2)
    generados_descartados   Notas que el modelo escribió pero se descartaron
    scrapeados_aprobados    Artículos que pasaron la clasificación
    scrapeados_descartados  Artículos que la clasificación rechazó

Cada sección declara qué colecciones la componen y el resto del módulo solo
acepta esas: el nombre de colección llega desde el navegador y sin esta lista
blanca un request armado a mano podría leer cualquier colección de la base.

La fecha y el orden salen del _id de Mongo, que lleva la hora de inserción.
Así los documentos anteriores a este módulo, que no tienen un campo de fecha
uniforme, también quedan ordenados y fechados.

La búsqueda usa regex y no $text: $text exige un índice de texto que la base
no siempre tiene (ver /api/articulos-stats).
"""

import datetime
import re

from bson import ObjectId
from bson.errors import InvalidId

import db as _db

# Campos que nunca viajan al navegador: los vectores pesan miles de floats.
_SIN_EMBEDDING = {"embedding": 0}

SECCIONES = {
    "generados_aprobados": {
        "colecciones": ["articulos_generados", "notas_fase2"],
        "campo_texto": "contenido",
    },
    "generados_descartados": {
        "colecciones": ["notas_descartadas"],
        "campo_texto": "contenido",
    },
    "scrapeados_aprobados": {
        # 'afterdrive' es una colección heredada: hoy nadie escribe ahí, pero
        # generar_articulo.py todavía la lee y puede tener artículos viejos.
        "colecciones": ["articulos", "afterdrive"],
        "campo_texto": "cuerpo",
    },
    "scrapeados_descartados": {
        "colecciones": ["articulos_descartados"],
        "campo_texto": "cuerpo",
    },
}

# Colecciones de Notas guardadas, las únicas con estado editorial.
COLECCIONES_CON_ESTADO = {"articulos_generados", "notas_fase2"}
ESTADOS = {_db.ESTADO_BORRADOR, _db.ESTADO_PUBLICADO}

_ORIGEN = {
    "articulos_generados": "Artículo por tema",
    "notas_fase2": "Nota AfterDrive",
    "fase1": "Artículo por tema",
    "fase2": "Nota AfterDrive",
    "articulos": "Scraping",
    "afterdrive": "Scraping (colección anterior)",
    "articulos_descartados": "Scraping",
}

POR_PAGINA_MAX = 50
_LARGO_RESUMEN = 240


class ErrorHistorial(ValueError):
    """Parámetro inválido; el mensaje es apto para mostrarle al usuario."""


def _base(base):
    return base if base is not None else _db.db


def _validar_seccion(seccion: str) -> dict:
    if seccion not in SECCIONES:
        raise ErrorHistorial(f"Sección inválida: {seccion!r}.")
    return SECCIONES[seccion]


def _oid(item_id: str) -> ObjectId:
    try:
        return ObjectId(item_id)
    except (InvalidId, TypeError) as e:
        raise ErrorHistorial("Identificador inválido.") from e


def _filtro_estado(estado: str) -> dict:
    """Filtro Mongo por estado editorial.

    'borrador' incluye las Notas sin el campo: son anteriores a que existiera
    y nunca se marcaron como publicadas.
    """
    if estado == _db.ESTADO_PUBLICADO:
        return {"estado": _db.ESTADO_PUBLICADO}
    if estado == _db.ESTADO_BORRADOR:
        return {"estado": {"$ne": _db.ESTADO_PUBLICADO}}
    return {}


def _filtro_busqueda(q: str, campo_texto: str) -> dict:
    q = (q or "").strip()
    if not q:
        return {}
    patron = {"$regex": re.escape(q), "$options": "i"}
    campos = ["titulo", campo_texto, "tema", "url", "motivo", "razon"]
    return {"$or": [{c: patron} for c in dict.fromkeys(campos)]}


def _texto_plano(markdown: str) -> str:
    texto = re.sub(r"```.*?```", " ", markdown or "", flags=re.DOTALL)
    texto = re.sub(r"[#>*_`\[\]]", "", texto)
    texto = re.sub(r"\(https?://[^)]*\)", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _titulo_de_nota(contenido: str) -> str:
    """Primer encabezado '# ' de la Nota o, si no hay, su primera línea."""
    lineas = [ln.strip() for ln in (contenido or "").splitlines() if ln.strip()]
    for linea in lineas:
        if linea.startswith("# "):
            return linea[2:].strip()
    for linea in lineas:
        limpia = linea.lstrip("#").strip()
        if limpia:
            return limpia[:140]
    return ""


def _fecha(doc: dict) -> str | None:
    oid = doc.get("_id")
    return oid.generation_time.isoformat() if isinstance(oid, ObjectId) else None


def _normalizar(doc: dict, coleccion: str, seccion: str, completo: bool = False) -> dict:
    campo_texto = SECCIONES[seccion]["campo_texto"]
    texto = doc.get(campo_texto) or ""
    es_nota = seccion.startswith("generados")

    titulo = doc.get("titulo") or (_titulo_de_nota(texto) if es_nota else "")
    if not titulo:
        titulo = doc.get("tema") or doc.get("url") or "(sin título)"

    item = {
        "id": str(doc["_id"]),
        "coleccion": coleccion,
        "seccion": seccion,
        "titulo": titulo,
        "resumen": _texto_plano(texto)[:_LARGO_RESUMEN],
        "fecha": _fecha(doc),
        "url": doc.get("url") or None,
        "origen": _ORIGEN.get(doc.get("origen", coleccion), _ORIGEN.get(coleccion, coleccion)),
    }

    if seccion == "generados_aprobados":
        item["estado"] = doc.get("estado") or _db.ESTADO_BORRADOR
        item["publicado_en"] = doc.get("publicado_en")
    if seccion.endswith("descartados"):
        # Los descartes anteriores a este cambio no guardaban el motivo.
        item["motivo"] = doc.get("motivo") or doc.get("razon") or None

    meta = {k: doc[k] for k in ("tema", "persona", "categorias", "regiones", "fuente", "fuentes") if doc.get(k)}
    if meta:
        item["meta"] = meta

    if completo:
        item["contenido"] = texto
    return item


def resumen(base=None) -> dict:
    b = _base(base)
    generados = {c: b[c].count_documents({}) for c in SECCIONES["generados_aprobados"]["colecciones"]}
    publicados = sum(
        b[c].count_documents({"estado": _db.ESTADO_PUBLICADO})
        for c in SECCIONES["generados_aprobados"]["colecciones"]
    )
    total_generados = sum(generados.values())
    descartados_scraping = b["articulos_descartados"].count_documents({})
    descartados_con_motivo = b["articulos_descartados"].count_documents(
        {"razon": {"$exists": True, "$nin": ["", None]}}
    )
    return {
        "generados_aprobados": {
            "total": total_generados,
            "publicados": publicados,
            "borradores": total_generados - publicados,
            "por_origen": {_ORIGEN[c]: n for c, n in generados.items()},
        },
        "generados_descartados": {"total": b["notas_descartadas"].count_documents({})},
        "scrapeados_aprobados": {
            "total": sum(b[c].count_documents({}) for c in SECCIONES["scrapeados_aprobados"]["colecciones"]),
        },
        "scrapeados_descartados": {
            "total": descartados_scraping,
            "sin_motivo": descartados_scraping - descartados_con_motivo,
        },
    }


def listar(seccion: str, pagina: int = 1, por_pagina: int = 20, q: str = "", estado: str = "todos", base=None) -> dict:
    cfg = _validar_seccion(seccion)
    b = _base(base)
    pagina = max(1, int(pagina))
    por_pagina = min(max(1, int(por_pagina)), POR_PAGINA_MAX)
    if estado not in ESTADOS | {"todos"}:
        raise ErrorHistorial(f"Estado inválido: {estado!r}.")

    filtro = _filtro_busqueda(q, cfg["campo_texto"])
    if seccion == "generados_aprobados":
        filtro = {**filtro, **_filtro_estado(estado)}

    # Una sección puede juntar dos colecciones. Para paginar el conjunto
    # ordenado sin traer todo: se piden los primeros (salto + por_pagina) de
    # cada una, se mezclan por fecha y se corta la página. Es exacto porque
    # ninguna página puede necesitar más que eso de una sola colección.
    salto = (pagina - 1) * por_pagina
    candidatos, total = [], 0
    for coleccion in cfg["colecciones"]:
        total += b[coleccion].count_documents(filtro)
        cursor = b[coleccion].find(filtro, _SIN_EMBEDDING).sort("_id", -1).limit(salto + por_pagina)
        candidatos += [(doc["_id"], coleccion, doc) for doc in cursor]

    candidatos.sort(key=lambda t: t[0].generation_time, reverse=True)
    pagina_docs = candidatos[salto:salto + por_pagina]
    return {
        "seccion": seccion,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total": total,
        "paginas": max(1, -(-total // por_pagina)),
        "items": [_normalizar(doc, col, seccion) for _, col, doc in pagina_docs],
    }


def detalle(seccion: str, coleccion: str, item_id: str, base=None) -> dict | None:
    cfg = _validar_seccion(seccion)
    if coleccion not in cfg["colecciones"]:
        raise ErrorHistorial("Colección inválida para esta sección.")
    doc = _base(base)[coleccion].find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING)
    return _normalizar(doc, coleccion, seccion, completo=True) if doc else None


def cambiar_estado(coleccion: str, item_id: str, estado: str, base=None) -> dict | None:
    """Marca una Nota como publicada o la devuelve a borrador."""
    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen estado de publicación.")
    if estado not in ESTADOS:
        raise ErrorHistorial(f"Estado inválido: {estado!r}.")

    cambios = {"$set": {"estado": estado}}
    if estado == _db.ESTADO_PUBLICADO:
        cambios["$set"]["publicado_en"] = datetime.datetime.now(datetime.UTC).isoformat()
    else:
        cambios["$unset"] = {"publicado_en": ""}

    col = _base(base)[coleccion]
    resultado = col.update_one({"_id": _oid(item_id)}, cambios)
    if not resultado.matched_count:
        return None
    return _normalizar(col.find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING), coleccion, "generados_aprobados")
