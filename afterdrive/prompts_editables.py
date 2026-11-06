"""
prompts_editables.py — Las piezas del prompt de redacción, editadas desde el dashboard con aprobación.

Interfaz:
    catalogo() -> list[dict]                       las piezas editables, en el orden del prompt
    listar(base=None) -> list[dict]                cada pieza con su versión activa y si tiene algo pendiente
    detalle(clave, base=None) -> dict              activa, pendiente, original e historial de una pieza
    validar(clave, contenido) -> dict              {"errores": [...], "avisos": [...]}
    guardar_borrador(clave, contenido, motivo="", base=None) -> dict
    descartar_borrador(clave, base=None)
    enviar(clave, base=None) -> dict               borrador -> en revisión
    aprobar(clave, version, base=None) -> dict     en revisión -> activa; la activa anterior se archiva
    rechazar(clave, motivo="", base=None) -> dict  en revisión -> vuelve a borrador, con el motivo
    restaurar(clave, version, motivo="", base=None) -> dict
                                                   una versión archivada (0 = el texto original) vuelve
                                                   a revisión: hay que aprobarla de nuevo
    activos() -> {clave: contenido}                lo que usa redaccion.py (caché de CACHE_S segundos)

Recorrido de una pieza: Borrador → Validar → Enviar a revisión → Aprobar y
activar → Activa. El login es de un solo admin: las aprobaciones son pasos de
confirmación, no personas distintas. Por clave hay como mucho una versión
pendiente (borrador o en revisión) y una activa; el resto queda archivado.

Colección `prompts`, un documento por versión:
    clave, contenido, version (1, 2, ...; la 0 es el texto original del código),
    estado: borrador | en_revision | activo | archivado,
    motivo (por qué se cambió), restaurado_de (versión), rechazo {motivo, fecha},
    y la fecha de cada paso: creado, editado, enviado, aprobado, archivado.
"""

from __future__ import annotations

import datetime
import re
import time

from afterdrive.ia import redaccion

BORRADOR, EN_REVISION, ACTIVO, ARCHIVADO = "borrador", "en_revision", "activo", "archivado"
PENDIENTES = (BORRADOR, EN_REVISION)
CACHE_S = 60
LARGO_MAX = 4000            # caracteres por pieza
LARGO_MAX_IDENTIDAD = 600   # va en la misma línea que el rol de la persona
MOTIVO_MAX = 300
SECCIONES_ALEPHEE = ("Qué resuelve", "Productos", "Casos")

_NOMBRES_PERSONAS = {
    "analitico": "Analítico-técnico",
    "periodistico": "Periodístico",
    "comercial": "Comercial",
    "divulgativo": "Divulgativo",
    "ejecutivo": "Ejecutivo",
}

_CATALOGO = [
    ("identidad", "Identidad", "base", "Quién escribe y para qué medio. Va en la misma línea que el rol de la persona."),
    ("audiencia", "Audiencia", "base", "Para quién se escribe y qué le importa."),
    ("reglas_datos", "Reglas de datos", "base", "De dónde salen los hechos, cómo se citan y qué no se inventa."),
    ("oficio", "Oficio del sector", "base", "Terminología y criterios del aftermarket automotor."),
    ("enfoque_alephee", "Enfoque Alephee", "base",
     "Qué resuelve, productos y casos de Alephee (lo único que la nota puede afirmar) y cómo nombrarla."),
    ("formato", "Formato", "base", "Markdown, títulos y extensión. {extension} se reemplaza por el largo elegido."),
    ("seo", "SEO", "base", "Título, palabra clave y enlaces."),
    ("salida", "Respuesta", "base", "Qué devuelve el modelo: solo la nota, sin comentarios."),
    *[(f"persona_{slug}", nombre, "persona",
       "El rol, y después ## Tu tarea, ## Estructura (lista numerada) y ## Estilo.")
      for slug, nombre in _NOMBRES_PERSONAS.items()],
]
CLAVES = [c[0] for c in _CATALOGO]


class ErrorPrompt(Exception):
    """Un pedido que no se puede hacer: clave desconocida, estado equivocado o texto inválido."""


def _col(base=None):
    if base is None:
        from afterdrive import db
        return db.col_prompts
    return base["prompts"]


def _ahora() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _clave(clave: str) -> str:
    if clave not in CLAVES:
        raise ErrorPrompt("Pieza del prompt desconocida.")
    return clave


def catalogo() -> list[dict]:
    return [{"clave": c, "titulo": t, "grupo": g, "descripcion": d} for c, t, g, d in _CATALOGO]


def _titulo(clave: str) -> str:
    return next(t for c, t, _, _ in _CATALOGO if c == clave)


# ── Validación ────────────────────────────────────────────────────────────────

def validar(clave: str, contenido: str) -> dict:
    """Lo que impide aprobar (errores) y lo que conviene mirar (avisos)."""
    _clave(clave)
    texto = (contenido or "").strip()
    errores, avisos = [], []
    if not texto:
        return {"errores": ["El texto está vacío."], "avisos": []}
    maximo = LARGO_MAX_IDENTIDAD if clave == "identidad" else LARGO_MAX
    if len(texto) > maximo:
        errores.append(f"Supera el largo máximo: {len(texto)} de {maximo} caracteres.")

    titulos = re.findall(r"^##\s+(.+?)\s*$", texto, flags=re.M)
    if clave == "identidad":
        if titulos or re.search(r"^#", texto, flags=re.M):
            errores.append("La identidad va sin títulos: es una o dos oraciones que siguen al rol de la persona.")
    elif clave.startswith("persona_"):
        p = redaccion.parsear_persona(texto)
        if not p["rol"]:
            errores.append("Falta el rol: la primera línea, antes de \"## Tu tarea\" (por ejemplo, \"Sos un analista...\").")
        for nombre, campo in (("## Tu tarea", "tarea"), ("## Estilo", "estilo")):
            if not p[campo]:
                errores.append(f"Falta la sección \"{nombre}\" o está vacía.")
        if not p["estructura"]:
            errores.append("Falta la sección \"## Estructura\" con una lista numerada (1. ..., 2. ...).")
        elif len(p["estructura"]) < 2:
            errores.append("La estructura necesita al menos 2 puntos: cada uno es una sección de la nota.")
        elif len(p["estructura"]) > 8:
            avisos.append(f"La estructura tiene {len(p['estructura'])} puntos: más de 8 secciones suele dar notas repetitivas.")
    else:
        if not re.match(r"^##\s+\S", texto):
            errores.append("Tiene que empezar con un título \"## \" (por ejemplo, \"## Formato\").")
        cuerpo = re.sub(r"^##\s+.*$", "", texto, flags=re.M).strip()
        if not cuerpo:
            errores.append("Tiene título pero no tiene reglas debajo.")

    if clave == "enfoque_alephee":
        faltan = [s for s in SECCIONES_ALEPHEE if not re.search(rf"^###\s+{s}", texto, flags=re.M | re.I)]
        if faltan:
            avisos.append("Conviene que tenga las secciones " + ", ".join(f"\"### {s}\"" for s in faltan)
                          + ": la nota y el juez solo pueden afirmar de Alephee lo que está acá.")
    if clave == "formato" and "{extension}" not in texto:
        errores.append("Falta {extension} en Formato: ahí va el largo elegido en Crear nota.")
    if clave != "formato" and "{extension}" in texto:
        avisos.append("{extension} solo se reemplaza en Formato: acá va a quedar escrito tal cual.")
    return {"errores": errores, "avisos": avisos}


# ── Lectura ───────────────────────────────────────────────────────────────────

def _publico(doc: dict | None) -> dict | None:
    if not doc:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _original(clave: str) -> dict:
    return {"clave": clave, "version": 0, "estado": ACTIVO, "contenido": redaccion.PIEZAS[clave],
            "motivo": "Texto original del sistema.", "original": True}


def _activo(clave: str, base=None) -> dict:
    doc = _col(base).find_one({"clave": clave, "estado": ACTIVO})
    return _publico(doc) or _original(clave)


def _pendiente(clave: str, base=None) -> dict | None:
    return _publico(_col(base).find_one({"clave": clave, "estado": {"$in": list(PENDIENTES)}}))


def listar(base=None) -> list[dict]:
    col = _col(base)
    activos = {d["clave"]: d for d in col.find({"estado": ACTIVO}, {"contenido": 0})}
    pendientes = {d["clave"]: d for d in col.find({"estado": {"$in": list(PENDIENTES)}}, {"contenido": 0})}
    piezas = []
    for item in catalogo():
        a, p = activos.get(item["clave"]), pendientes.get(item["clave"])
        piezas.append({
            **item,
            "version_activa": a["version"] if a else 0,
            "aprobado": a.get("aprobado") if a else None,
            "pendiente": {"estado": p["estado"], "version": p["version"]} if p else None,
        })
    return piezas


def detalle(clave: str, base=None) -> dict:
    _clave(clave)
    historial = [_publico(d) for d in _col(base).find({"clave": clave, "estado": ARCHIVADO}).sort("version", -1)]
    activo = _activo(clave, base)
    if not activo.get("original"):
        historial.append(_original(clave) | {"estado": ARCHIVADO})
    return {
        "clave": clave, "titulo": _titulo(clave),
        "activo": activo, "pendiente": _pendiente(clave, base),
        "original": redaccion.PIEZAS[clave], "historial": historial,
    }


# ── Recorrido ─────────────────────────────────────────────────────────────────

def _siguiente_version(clave: str, base=None) -> int:
    ultimo = _col(base).find_one({"clave": clave}, sort=[("version", -1)])
    return (ultimo["version"] if ultimo else 0) + 1


def _motivo(motivo) -> str:
    return " ".join(str(motivo or "").split())[:MOTIVO_MAX]


def guardar_borrador(clave: str, contenido: str, motivo: str = "", base=None) -> dict:
    """Guarda el texto como borrador. Si ya estaba en revisión, vuelve a borrador."""
    _clave(clave)
    contenido = (contenido or "").replace("\r\n", "\n").strip()
    if not contenido:
        raise ErrorPrompt("El texto está vacío.")
    if len(contenido) > LARGO_MAX * 2:
        raise ErrorPrompt("El texto es demasiado largo.")
    col, ahora = _col(base), _ahora()
    pendiente = col.find_one({"clave": clave, "estado": {"$in": list(PENDIENTES)}})
    if pendiente:
        col.update_one({"_id": pendiente["_id"]}, {
            "$set": {"contenido": contenido, "motivo": _motivo(motivo), "estado": BORRADOR, "editado": ahora},
            "$unset": {"enviado": ""},
        })
    else:
        col.insert_one({"clave": clave, "contenido": contenido, "motivo": _motivo(motivo), "estado": BORRADOR,
                        "version": _siguiente_version(clave, base), "creado": ahora, "editado": ahora})
    return _pendiente(clave, base)


def descartar_borrador(clave: str, base=None) -> None:
    _clave(clave)
    if not _col(base).delete_one({"clave": clave, "estado": {"$in": list(PENDIENTES)}}).deleted_count:
        raise ErrorPrompt("No hay ningún borrador para descartar.")


def _revisable(clave: str, base=None) -> dict:
    """El pendiente, validado y distinto de lo activo. Si no, ErrorPrompt con el motivo."""
    pendiente = _pendiente(clave, base)
    if not pendiente:
        raise ErrorPrompt("No hay ningún borrador de esta pieza.")
    v = validar(clave, pendiente["contenido"])
    if v["errores"]:
        raise ErrorPrompt("Antes hay que corregir: " + " ".join(v["errores"]))
    if pendiente["contenido"].strip() == _activo(clave, base)["contenido"].strip():
        raise ErrorPrompt("El texto es igual al de la versión activa: no hay nada que aprobar.")
    return pendiente


def enviar(clave: str, base=None) -> dict:
    """Borrador -> en revisión."""
    _clave(clave)
    pendiente = _revisable(clave, base)
    if pendiente["estado"] != BORRADOR:
        raise ErrorPrompt("Ya está en revisión.")
    _col(base).update_one({"clave": clave, "version": pendiente["version"]},
                          {"$set": {"estado": EN_REVISION, "enviado": _ahora()}, "$unset": {"rechazo": ""}})
    return _pendiente(clave, base)


def aprobar(clave: str, version, base=None) -> dict:
    """En revisión -> activa. `version` es la que se vio en la confirmación: si cambió, no se aprueba."""
    _clave(clave)
    pendiente = _revisable(clave, base)
    if pendiente["estado"] != EN_REVISION:
        raise ErrorPrompt("Primero hay que enviarla a revisión.")
    try:
        version = int(version)
    except (TypeError, ValueError) as e:
        raise ErrorPrompt("Falta la versión que se aprueba.") from e
    if version != pendiente["version"]:
        raise ErrorPrompt("La versión cambió mientras la revisabas: volvé a mirarla antes de aprobar.")
    col, ahora = _col(base), _ahora()
    col.update_many({"clave": clave, "estado": ACTIVO}, {"$set": {"estado": ARCHIVADO, "archivado": ahora}})
    col.update_one({"clave": clave, "version": version}, {"$set": {"estado": ACTIVO, "aprobado": ahora}})
    invalidar_cache()
    return _activo(clave, base)


def rechazar(clave: str, motivo: str = "", base=None) -> dict:
    """En revisión -> borrador, con el motivo a la vista para corregirlo."""
    _clave(clave)
    pendiente = _pendiente(clave, base)
    if not pendiente or pendiente["estado"] != EN_REVISION:
        raise ErrorPrompt("No hay ninguna versión en revisión.")
    _col(base).update_one({"clave": clave, "version": pendiente["version"]}, {
        "$set": {"estado": BORRADOR, "rechazo": {"motivo": _motivo(motivo), "fecha": _ahora()}},
        "$unset": {"enviado": ""},
    })
    return _pendiente(clave, base)


def restaurar(clave: str, version, motivo: str = "", base=None) -> dict:
    """Una versión archivada (0 = el original) pasa a revisión. Pisa el borrador que hubiera."""
    _clave(clave)
    try:
        version = int(version)
    except (TypeError, ValueError) as e:
        raise ErrorPrompt("Versión inválida.") from e
    if version == 0:
        contenido = redaccion.PIEZAS[clave]
    else:
        doc = _col(base).find_one({"clave": clave, "version": version, "estado": ARCHIVADO})
        if not doc:
            raise ErrorPrompt("Esa versión no está archivada.")
        contenido = doc["contenido"]
    if contenido.strip() == _activo(clave, base)["contenido"].strip():
        raise ErrorPrompt("Esa versión es igual a la activa.")
    col, ahora = _col(base), _ahora()
    col.delete_many({"clave": clave, "estado": {"$in": list(PENDIENTES)}})
    col.insert_one({
        "clave": clave, "contenido": contenido, "estado": EN_REVISION,
        "version": _siguiente_version(clave, base), "restaurado_de": version,
        "motivo": _motivo(motivo) or (f"Restaurar la versión {version}." if version else "Volver al texto original."),
        "creado": ahora, "editado": ahora, "enviado": ahora,
    })
    return _pendiente(clave, base)


# ── Lo que usa la redacción ───────────────────────────────────────────────────

_cache: dict = {"hasta": 0.0, "datos": {}}


def invalidar_cache() -> None:
    _cache["hasta"] = 0.0


def activos(base=None) -> dict:
    """{clave: contenido} de las piezas aprobadas. Si Mongo falla, {} (y se reintenta en CACHE_S)."""
    if base is None and time.monotonic() < _cache["hasta"]:
        return _cache["datos"]
    try:
        datos = {d["clave"]: d["contenido"] for d in _col(base).find({"estado": ACTIVO}, {"clave": 1, "contenido": 1})
                 if d.get("clave") in CLAVES and d.get("contenido")}
    except Exception as e:
        print(f"[AVISO] Prompts editados no disponibles, se usan los originales: {e}", flush=True)
        datos = {}
    if base is None:
        _cache.update(hasta=time.monotonic() + CACHE_S, datos=datos)
    return datos
