"""
historial.py — Consulta del historial de Artículos y Notas guardados.

Interfaz:
    resumen(base=None) -> conteos por sección, publicadas y borradores
    listar(seccion, pagina=1, por_pagina=20, q="", estado="todos", base=None) -> página
    detalle(seccion, coleccion, item_id, base=None) -> ítem con el contenido completo
    cambiar_estado(coleccion, item_id, estado, base=None) -> ítem actualizado
    editar_traduccion(coleccion, item_id, idioma, contenido) -> traducción guardada
    cambiar_imagen(coleccion, item_id, url, alt="", base=None) -> ítem con la imagen destacada elegida
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
        item["aprobada_por"] = doc.get("aprobada_por")
        item["aprobacion_auto"] = doc.get("aprobacion_auto")
        item["juicio"] = doc.get("juicio")
        item["critica_puntaje"] = (doc.get("critica") or {}).get("puntaje")   # 1 a 10, de critica.py
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


def editar_traduccion(coleccion: str, item_id: str, idioma: str, contenido: str, base=None) -> dict | None:
    """Reemplaza el texto de la versión de una Nota en otro idioma. Devuelve la traducción guardada.

    Queda al día con el original actual: si después se edita el original, se
    marca como desactualizada (y al subir a HubSpot se vuelve a traducir).
    """
    from afterdrive import hubspot, traducciones

    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen traducciones.")
    contenido = (contenido or "").strip() if isinstance(contenido, str) else ""
    if len(contenido) < LARGO_MINIMO_NOTA:
        raise ErrorHistorial(f"La traducción quedó demasiado corta (mínimo {LARGO_MINIMO_NOTA} caracteres).")
    if not contenido.startswith("# "):
        raise ErrorHistorial("La traducción tiene que empezar con el título (una línea con '# ').")
    col = _base(base)[coleccion]
    doc = col.find_one({"_id": _oid(item_id)}, {"contenido": 1, "regiones": 1, "idioma": 1})
    if not doc:
        return None
    if idioma not in traducciones.IDIOMAS or idioma == hubspot.idioma(doc):
        raise ErrorHistorial("Idioma inválido para una traducción de esta nota.")
    nueva = traducciones.entrada(contenido, doc.get("contenido", ""), editada=True)
    col.update_one({"_id": doc["_id"]}, {"$set": {f"traducciones.{idioma}": nueva}})
    return nueva


def destino_hubspot(coleccion: str, item_id: str, base=None) -> dict | None:
    """A qué blog va la nota, con qué etiquetas y autor, y los autores que se pueden elegir."""
    from afterdrive import hubspot

    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas se envían a HubSpot.")
    doc = _base(base)[coleccion].find_one({"_id": _oid(item_id)}, {"regiones": 1, "categorias": 1, "hubspot_autor_id": 1})
    if not doc:
        return None
    lugar = hubspot.destino(doc)
    lugar.pop("tag_ids")
    try:
        lugar["autores"] = hubspot.autores(lugar["idioma"])
    except hubspot.ErrorHubSpot:
        lugar["autores"] = []   # se sube igual con el autor por defecto
    return lugar


def enviar_a_hubspot(coleccion: str, item_id: str, publicar: bool, base=None, autor_id: str | None = None) -> dict | None:
    """Manda una Nota aprobada a HubSpot (borrador o publicada) y guarda el resultado.

    Solo las notas aprobadas (o ya publicadas, para actualizarlas): así nada
    llega al blog sin que una persona lo haya revisado. `autor_id` es el autor
    elegido al revisarla; queda guardado para los reenvíos.
    """
    from afterdrive import hubspot

    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas se pueden enviar a HubSpot.")
    if autor_id is not None and not re.fullmatch(r"\d{1,20}", str(autor_id)):
        raise ErrorHistorial("Autor inválido.")
    col = _base(base)[coleccion]
    doc = col.find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING)
    if not doc:
        return None
    if doc.get("estado") not in (_db.ESTADO_APROBADA, _db.ESTADO_PUBLICADO):
        raise ErrorHistorial("Aprobá la nota antes de enviarla a HubSpot.")
    if autor_id is not None:
        col.update_one({"_id": doc["_id"]}, {"$set": {"hubspot_autor_id": str(autor_id)}})
        doc["hubspot_autor_id"] = str(autor_id)

    hubspot.destino(doc)   # sin blog para su idioma: falla antes de subir la imagen
    aviso = _copiar_imagen_a_hubspot(col, doc)
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


def _copiar_imagen_a_hubspot(col, doc: dict) -> str:
    """Copia las imágenes de la nota (destacada y del cuerpo) a los archivos de HubSpot.

    Así el blog no depende de que el sitio de la noticia la siga sirviendo ni
    de que acepte que otro sitio la muestre. Si una copia falla, la nota se
    sube igual con el link original: una imagen no debería frenar una
    publicación. Devuelve un aviso si alguna no se pudo copiar.
    """
    from afterdrive import hubspot, imagen_web

    def copiar(url: str, nombre: str) -> tuple[str, str]:
        try:
            if url.startswith(PREFIJO_IMAGEN_SUBIDA):   # subida desde la computadora: está en la base
                local = imagen_subida(url[len(PREFIJO_IMAGEN_SUBIDA):], base=col.database)
                if not local:
                    return "", "la imagen subida ya no está"
                contenido, mime = local
            else:
                contenido, mime = imagen_web.descargar(url)
            extension = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
            return hubspot.subir_imagen(contenido, mime, f"{nombre}.{extension}"), ""
        except (imagen_web.ErrorDescarga, hubspot.ErrorHubSpot) as e:
            return "", str(e)

    errores = []
    imagen = doc.get("imagen") or {}
    if imagen.get("url") and not imagen.get("hubspot_url"):
        copia, error = copiar(imagen["url"], f"nota-{doc['_id']}")
        if copia:
            col.update_one({"_id": doc["_id"]}, {"$set": {"imagen.hubspot_url": copia}})
            doc["imagen"] = {**imagen, "hubspot_url": copia}
        else:
            errores.append(f"la destacada ({error})")
    for i, im in enumerate(doc.get("imagenes_cuerpo") or []):
        if im.get("url") and not im.get("hubspot_url"):
            copia, error = copiar(im["url"], f"nota-{doc['_id']}-{i + 2}")
            if copia:
                col.update_one({"_id": doc["_id"]}, {"$set": {f"imagenes_cuerpo.{i}.hubspot_url": copia}})
                im["hubspot_url"] = copia
            else:
                errores.append(f"la {i + 2}ª ({error})")
    if not errores:
        return ""
    return f"No se pudo copiar a HubSpot {', '.join(errores)}. Se usa el link original."


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


def cambiar_imagen(coleccion: str, item_id: str, url: str, alt: str = "", base=None) -> dict | None:
    """Imagen destacada de una Nota para HubSpot. url vacía la saca."""
    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen imagen destacada.")
    url = url.strip() if isinstance(url, str) else ""
    alt = " ".join(alt.split())[:200] if isinstance(alt, str) else ""
    from afterdrive.imagen_web import url_valida
    if url and not url_valida(url):
        raise ErrorHistorial("La imagen tiene que ser una URL https pública.")
    col = _base(base)[coleccion]
    doc = col.find_one({"_id": _oid(item_id)}, {"fuentes": 1})
    if not doc:
        return None
    nueva = {"url": url, "alt": alt}
    # Si es la foto de una de sus noticias, se recuerda de cuál (se muestra al revisarla).
    origen = next(({"titulo": f.get("titulo", ""), "url": f.get("url", "")}
                   for f in doc.get("fuentes") or [] if url and f.get("imagen") == url), None)
    if origen:
        nueva["origen"] = origen
    col.update_one({"_id": doc["_id"]}, {"$set": {"imagen": nueva}} if url else {"$unset": {"imagen": ""}})
    return _normalizar(col.find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING), coleccion, "generados_aprobados")


# ── Imagen subida desde la computadora ────────────────────────────────────────
# Se guarda en la base (imagenes_subidas) y se sirve en /api/imagenes/<id> con
# sesión; al subir la nota a HubSpot se copia desde ahí (ver _copiar_imagen_a_hubspot).

PREFIJO_IMAGEN_SUBIDA = "/api/imagenes/"
IMAGEN_SUBIDA_MAX = 5 * 1024 * 1024


def _tipo_imagen(contenido: bytes) -> str | None:
    """mime por los primeros bytes: no alcanza con la extensión ni con lo que diga el navegador."""
    if contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    if contenido.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def subir_imagen(coleccion: str, item_id: str, contenido: bytes, nombre: str = "", alt: str = "", base=None) -> dict | None:
    """Imagen destacada elegida desde la computadora. Devuelve {"imagen"} o None si la nota no existe."""
    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen imagen destacada.")
    if not contenido:
        raise ErrorHistorial("El archivo está vacío.")
    if len(contenido) > IMAGEN_SUBIDA_MAX:
        raise ErrorHistorial("La imagen pesa más de 5 MB.")
    mime = _tipo_imagen(contenido)
    if not mime:
        raise ErrorHistorial("El archivo no es una imagen JPG, PNG, WebP o GIF.")
    b = _base(base)
    col = b[coleccion]
    doc = col.find_one({"_id": _oid(item_id)}, {"_id": 1})
    if not doc:
        return None
    nombre = " ".join(str(nombre or "").split())[:120]
    guardada = b.imagenes_subidas.insert_one({
        "contenido": contenido, "mime": mime, "nombre": nombre, "coleccion": coleccion, "nota_id": doc["_id"],
        "fecha": datetime.datetime.now(datetime.UTC).isoformat(),
    })
    alt = " ".join(alt.split())[:200] if isinstance(alt, str) else ""
    nueva = {"url": PREFIJO_IMAGEN_SUBIDA + str(guardada.inserted_id), "alt": alt, "subida": {"nombre": nombre}}
    col.update_one({"_id": doc["_id"]}, {"$set": {"imagen": nueva}})
    return {"imagen": nueva}


def imagen_subida(imagen_id: str, base=None) -> tuple[bytes, str] | None:
    """(bytes, mime) de una imagen subida, o None si no existe."""
    try:
        oid = ObjectId(imagen_id)
    except (InvalidId, TypeError):
        return None
    doc = _base(base).imagenes_subidas.find_one({"_id": oid})
    return (bytes(doc["contenido"]), doc["mime"]) if doc else None


def vista_previa(coleccion: str, item_id: str, base=None) -> dict | None:
    """Cómo quedaría la Nota en HubSpot. No necesita HubSpot configurado."""
    from afterdrive import hubspot

    if coleccion not in COLECCIONES_CON_ESTADO:
        raise ErrorHistorial("Solo las notas generadas tienen vista previa.")
    doc = _base(base)[coleccion].find_one({"_id": _oid(item_id)}, _SIN_EMBEDDING)
    if not doc:
        return None
    # Fotos de las noticias de la nota, para elegir otra destacada (con lo que opinó la IA, si las miró).
    de_noticias = [{"url": f["imagen"], "titulo": f.get("titulo", ""), "noticia": f.get("url", ""),
                    **({"apta": f["imagen_apta"], "motivo": f.get("imagen_motivo", "")} if "imagen_apta" in f else {})}
                   for f in doc.get("fuentes") or [] if f.get("imagen")]
    try:
        previa = hubspot.vista_previa(doc)
    except hubspot.ErrorHubSpot as e:
        raise ErrorHistorial(str(e)) from e
    propia = doc.get("imagen") or {}
    if str(propia.get("url") or "").startswith(PREFIJO_IMAGEN_SUBIDA) and not propia.get("hubspot_url"):
        # Subida desde la computadora y todavía sin copia en HubSpot: se ve la de este servidor.
        previa["imagen"] = {"url": propia["url"], "alt": propia.get("alt") or (previa.get("imagen") or {}).get("alt", "")}
    return {**previa, "imagen_propia": propia or None, "imagenes_noticias": de_noticias}
