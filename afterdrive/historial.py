"""
historial.py — Consulta del historial de Artículos y Notas guardados.

Interfaz:
    resumen(base=None) -> conteos por sección, publicadas y borradores
    listar(seccion, pagina=1, por_pagina=20, q="", estado="todos", base=None) -> página
    detalle(seccion, coleccion, item_id, base=None) -> ítem con el contenido completo
    cambiar_estado(coleccion, item_id, estado, base=None) -> ítem actualizado
    generar_imagen(coleccion, item_id, descripcion="", base=None) -> ítem con la imagen nueva (NVIDIA)
    editar(coleccion, item_id, contenido, base=None) -> ítem actualizado
                            (la primera edición guarda la versión generada en contenido_original)

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

Portado de la rama Front-Testing, con los estados de revisión (aprobada,
rechazada) y la edición del texto de una Nota.
"""

import datetime
import re

from bson import ObjectId
from bson.errors import InvalidId

from afterdrive import db as _db

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
        # puede tener artículos viejos.
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
ESTADOS = set(_db.ESTADOS_NOTA)
LARGO_MINIMO_NOTA = 200   # una edición que deja la nota casi vacía es un error

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

    'borrador' incluye las Notas sin el campo: son anteriores a que existiera.
    """
    if estado == _db.ESTADO_BORRADOR:
        return {"estado": {"$nin": [e for e in ESTADOS if e != _db.ESTADO_BORRADOR]}}
    if estado in ESTADOS:
        return {"estado": estado}
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
        item["editado_en"] = doc.get("editado_en")
        item["calidad"] = doc.get("calidad")
        item["hubspot"] = doc.get("hubspot")
        item["calificacion"] = doc.get("calificacion")
        if item["estado"] == _db.ESTADO_RECHAZADA:
            item["motivo"] = doc.get("motivo_rechazo") or None
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
    colecciones = SECCIONES["generados_aprobados"]["colecciones"]
    por_estado = {
        e: sum(b[c].count_documents(_filtro_estado(e)) for c in colecciones) for e in _db.ESTADOS_NOTA
    }
    publicados = por_estado[_db.ESTADO_PUBLICADO]
    total_generados = sum(generados.values())
    descartados_scraping = b["articulos_descartados"].count_documents({})
    descartados_con_motivo = b["articulos_descartados"].count_documents(
        {"razon": {"$exists": True, "$nin": ["", None]}}
    )
    return {
        "generados_aprobados": {
            "total": total_generados,
            "publicados": publicados,
            "borradores": por_estado[_db.ESTADO_BORRADOR],
            "por_estado": por_estado,
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


MOTIVO_MAX = 300


def cambiar_estado(coleccion: str, item_id: str, estado: str, base=None, motivo: str | None = None) -> dict | None:
    """Cambia el estado editorial de una Nota (borrador, aprobada, rechazada, publicado).

    Rechazar pide un motivo: se muestra en el historial y las notas siguientes
    lo reciben como un error a evitar (ver motivos_recientes).
    """
    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen estado editorial.")
    if estado not in ESTADOS:
        raise ErrorHistorial(f"Estado inválido: {estado!r}.")
    motivo = " ".join(motivo.split())[:MOTIVO_MAX] if isinstance(motivo, str) else ""
    if estado == _db.ESTADO_RECHAZADA and len(motivo) < 3:
        raise ErrorHistorial("Contá en pocas palabras por qué la rechazás: las próximas notas lo van a tener en cuenta.")

    col = _base(base)[coleccion]
    actual = col.find_one({"_id": _oid(item_id)}, {"estado": 1, "hubspot": 1})
    if actual and actual.get("estado") == _db.ESTADO_PUBLICADO and (actual.get("hubspot") or {}).get("id") \
            and estado != _db.ESTADO_PUBLICADO:
        # Si no, la nota quedaría como borrador acá y seguiría publicada en el blog.
        from afterdrive import hubspot
        hubspot.despublicar(actual["hubspot"]["id"])
        col.update_one({"_id": actual["_id"]}, {"$set": {"hubspot.estado": "DRAFT"}})

    cambios = {"$set": {"estado": estado}}
    if estado == _db.ESTADO_RECHAZADA:
        cambios["$set"].update(motivo_rechazo=motivo, rechazado_en=datetime.datetime.now(datetime.UTC).isoformat())
    if estado == _db.ESTADO_PUBLICADO:
        cambios["$set"]["publicado_en"] = datetime.datetime.now(datetime.UTC).isoformat()
    else:
        cambios["$unset"] = {"publicado_en": ""}

    resultado = col.update_one({"_id": _oid(item_id)}, cambios)
    if not resultado.matched_count:
        return None
    return _normalizar(col.find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING), coleccion, "generados_aprobados")


def editar(coleccion: str, item_id: str, contenido: str, base=None) -> dict | None:
    """Reemplaza el texto de una Nota. Una nota ya publicada no se edita acá."""
    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo se pueden editar las notas generadas.")
    contenido = (contenido or "").strip() if isinstance(contenido, str) else ""
    if len(contenido) < LARGO_MINIMO_NOTA:
        raise ErrorHistorial(f"La nota quedó demasiado corta (mínimo {LARGO_MINIMO_NOTA} caracteres).")
    col = _base(base)[coleccion]
    doc = col.find_one({"_id": _oid(item_id)}, {"estado": 1, "contenido": 1, "contenido_original": 1})
    if not doc:
        return None
    if doc.get("estado") == _db.ESTADO_PUBLICADO:
        raise ErrorHistorial("La nota ya está publicada: volvela a borrador para editarla.")
    cambios = {"contenido": contenido, "editado_en": datetime.datetime.now(datetime.UTC).isoformat()}
    if not doc.get("contenido_original") and doc.get("contenido") and doc["contenido"].strip() != contenido:
        # La versión que escribió el modelo, una sola vez: de la diferencia con la
        # editada salen las lecciones de calibracion.lecciones_de_ediciones.
        cambios["contenido_original"] = doc["contenido"]
    col.update_one({"_id": doc["_id"]}, {"$set": cambios})
    return _normalizar(col.find_one({"_id": doc["_id"]}, _SIN_EMBEDDING), coleccion, "generados_aprobados", completo=True)


def enviar_a_hubspot(coleccion: str, item_id: str, publicar: bool, base=None) -> dict | None:
    """Manda una Nota aprobada a HubSpot (borrador o publicada) y guarda el resultado.

    Solo las notas aprobadas (o ya publicadas, para actualizarlas): así nada
    llega al blog sin que una persona lo haya revisado.
    """
    from afterdrive import hubspot

    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas se pueden enviar a HubSpot.")
    col = _base(base)[coleccion]
    doc = col.find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING)
    if not doc:
        return None
    if doc.get("estado") not in (_db.ESTADO_APROBADA, _db.ESTADO_PUBLICADO):
        raise ErrorHistorial("Aprobá la nota antes de enviarla a HubSpot.")

    aviso = _subir_imagen_generada(col, doc, base)
    r = hubspot.enviar(doc, publicar=publicar)   # ErrorHubSpot sube tal cual
    ahora = datetime.datetime.now(datetime.UTC).isoformat()
    cambios = {"hubspot": {**r, "enviado_en": ahora}}
    if publicar:
        cambios.update(estado=_db.ESTADO_PUBLICADO, publicado_en=ahora)
    col.update_one({"_id": doc["_id"]}, {"$set": cambios})
    item = _normalizar(col.find_one({"_id": doc["_id"]}, _SIN_EMBEDDING), coleccion, "generados_aprobados", completo=True)
    if aviso:
        item["aviso"] = aviso
    return item


def _subir_imagen_generada(col, doc: dict, base=None) -> str:
    """Sube a HubSpot la imagen generada que todavía no tiene URL pública. Devuelve un aviso si no pudo.

    Si falla, la nota se publica igual (con la imagen por defecto, si hay): una
    imagen no debería frenar una publicación.
    """
    from afterdrive import hubspot, imagenes

    imagen = doc.get("imagen") or {}
    generada = imagen.get("generada") or {}
    if imagen.get("url") or not generada.get("id"):
        return ""
    datos = imagenes.leer(generada["id"], base=base)
    if not datos:
        return "La imagen generada ya no está guardada: se publica sin ella."
    contenido, mime = datos
    extension = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
    try:
        url = hubspot.subir_imagen(contenido, mime, f"nota-{doc['_id']}.{extension}")
    except hubspot.ErrorHubSpot as e:
        return f"No se pudo subir la imagen ({e}). Se publicó sin ella."
    col.update_one({"_id": doc["_id"]}, {"$set": {"imagen.url": url}})
    doc["imagen"] = {**imagen, "url": url}
    return ""


def generar_imagen(coleccion: str, item_id: str, descripcion: str = "", base=None) -> dict | None:
    """Genera (o regenera) la imagen destacada con NVIDIA. `descripcion` manda sobre la del plan."""
    from afterdrive import imagenes

    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen imagen destacada.")
    descripcion = " ".join(descripcion.split())[:600] if isinstance(descripcion, str) else ""
    col = _base(base)[coleccion]
    doc = col.find_one({"_id": _oid(item_id)}, {"contenido": 1, "plan": 1, "categorias": 1, "imagen": 1})
    if not doc:
        return None
    try:
        nueva = imagenes.para_nota(doc.get("plan"), doc.get("categorias"), _titulo_de_nota(doc.get("contenido", "")),
                                   pedido=descripcion, base=base)
    except imagenes.ErrorImagen as e:
        raise ErrorHistorial(str(e)) from e
    col.update_one({"_id": doc["_id"]}, {"$set": {"imagen": nueva}})
    imagenes.borrar(((doc.get("imagen") or {}).get("generada") or {}).get("id"), base=base)
    return _normalizar(col.find_one({"_id": doc["_id"]}, _SIN_EMBEDDING), coleccion, "generados_aprobados")


def motivos_recientes(limite: int = 5, dias: int = 60, base=None) -> list[str]:
    """Los motivos de las últimas notas rechazadas, sin repetir, el más nuevo primero.

    Es lo que una persona corrigió: la generación los pasa al modelo como
    errores a evitar. Solo los de los últimos `dias`, para que una queja vieja
    (ya resuelta en los prompts) no siga pesando para siempre.
    """
    desde = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=dias)).isoformat()
    motivos: list[str] = []
    for coleccion in COLECCIONES_CON_ESTADO:
        cursor = _base(base)[coleccion].find(
            {"estado": _db.ESTADO_RECHAZADA, "motivo_rechazo": {"$nin": ["", None]}, "rechazado_en": {"$gte": desde}},
            {"motivo_rechazo": 1, "rechazado_en": 1},
        ).sort("rechazado_en", -1).limit(limite)
        motivos += [(d["rechazado_en"], d["motivo_rechazo"]) for d in cursor]
    vistos, resultado = set(), []
    for _, m in sorted(motivos, reverse=True):
        if m.lower() not in vistos:
            vistos.add(m.lower())
            resultado.append(m)
    return resultado[:limite]


def _url_imagen_valida(url: str) -> bool:
    """https con un nombre de dominio (no una IP).

    No hace falta el chequeo anti-SSRF del scraper: este servidor nunca
    descarga la imagen, la piden HubSpot y el navegador.
    """
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = p.hostname or ""
    return p.scheme == "https" and "." in host and not re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host)


def cambiar_imagen(coleccion: str, item_id: str, url: str, alt: str = "", base=None) -> dict | None:
    """Imagen destacada de una Nota para HubSpot. url vacía la saca."""
    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen imagen destacada.")
    url = url.strip() if isinstance(url, str) else ""
    alt = " ".join(alt.split())[:200] if isinstance(alt, str) else ""
    if url and not _url_imagen_valida(url):
        raise ErrorHistorial("La imagen tiene que ser una URL https pública.")
    col = _base(base)[coleccion]
    previa = (col.find_one({"_id": _oid(item_id)}, {"imagen": 1}) or {}).get("imagen") or {}
    cambio = {"$set": {"imagen": {"url": url, "alt": alt}}} if url else {"$unset": {"imagen": ""}}
    if not col.update_one({"_id": _oid(item_id)}, cambio).matched_count:
        return None
    from afterdrive import imagenes
    imagenes.borrar((previa.get("generada") or {}).get("id"), base=base)   # la generada que se reemplaza
    return _normalizar(col.find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING), coleccion, "generados_aprobados")


def vista_previa(coleccion: str, item_id: str, base=None) -> dict | None:
    """Cómo quedaría la Nota en HubSpot. No necesita HubSpot configurado."""
    from afterdrive import hubspot

    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen vista previa.")
    doc = _base(base)[coleccion].find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING)
    if not doc:
        return None
    from afterdrive import imagenes
    try:
        return {**hubspot.vista_previa(doc), "imagen_propia": doc.get("imagen") or None,
                "imagenes_disponibles": imagenes.configurado()}
    except hubspot.ErrorHubSpot as e:
        raise ErrorHistorial(str(e)) from e
