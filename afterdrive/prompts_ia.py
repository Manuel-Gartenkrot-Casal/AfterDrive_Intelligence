"""
prompts_ia.py — Prompts con IA: entender por qué las notas no sacan mejor nota y pedirle a la IA
que cambie los prompts, sobre una copia.

Interfaz:
    juego() -> "actuales" | "ia"                con qué prompts escribe la redacción
    usar(juego, base=None) -> dict              elegir el juego
    en_uso(base=None) -> {clave: contenido}     lo que la copia pisa de los actuales (vacío con "actuales")
    estado(base=None) -> dict                   juego, la copia pieza por pieza, el último análisis y las propuestas
    pieza(clave, base=None) -> dict             el texto actual y el de la copia de una pieza
    estadisticas(notas) -> dict                 promedios y lo que más falla (sin IA)
    analizar(limite=NOTAS_ANALISIS, base=None) -> dict
                                                estadísticas + el diagnóstico de la IA (qué falla y en qué pieza)
    proponer(pedido, claves=None, base=None) -> dict
                                                la IA reescribe piezas de la copia según el pedido (no se aplica sola)
    aplicar(propuesta_id, claves=None, base=None) -> dict
    descartar(propuesta_id, base=None) -> None
    restablecer(clave=None, base=None) -> int   la copia (o una pieza) vuelve a ser igual a los actuales

Los prompts actuales (prompts_editables: lo aprobado o el texto original) no se
tocan nunca desde acá. La copia de la IA es un duplicado de esos Markdown: una
pieza que la IA no cambió es igual a la actual; una que cambió queda en la
colección `prompts_ia` con su historial. En Prompts se elige con cuál escribe la
redacción ("actuales" o "ia") y se puede volver a los actuales cuando se quiera.
Cada nota guarda con cuál se escribió (`prompts_juego`), así el análisis compara.

Colecciones:
    prompts_ia            clave, contenido, base_version, base_contenido, cambios [{fecha, pedido, explicacion}]
    prompts_ia_analisis   fecha, estadisticas, diagnostico {resumen, problemas [...]} o error
    prompts_ia_propuestas fecha, pedido, estado (pendiente | aplicada | descartada),
                          cambios [{clave, titulo, antes, despues, explicacion, errores, avisos}], comentario
"""

from __future__ import annotations

import datetime
import json
from collections import Counter

from bson import ObjectId
from bson.errors import InvalidId

from afterdrive import prompts_editables as pe

JUEGOS = ("actuales", "ia")
NOTAS_ANALISIS = 40
PEDIDO_MAX = 1500
EJEMPLOS_POR_TIPO = 4
PROPUESTA_MAX_PIEZAS = 4

ASPECTOS = {"gramatica": "Gramática", "ortografia": "Ortografía", "redaccion": "Redacción", "tono": "Tono",
            "estructura": "Estructura"}


class ErrorPromptIA(Exception):
    """Un pedido que no se puede hacer (sin IA, propuesta inexistente, pedido vacío...)."""


def _base(base):
    if base is None:
        from afterdrive.db import db
        return db
    return base


def _ahora() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _oid(texto) -> ObjectId:
    try:
        return ObjectId(str(texto))
    except (InvalidId, TypeError) as e:
        raise ErrorPromptIA("Propuesta inexistente.") from e


# ── Qué juego se usa ──────────────────────────────────────────────────────────

def juego() -> str:
    try:
        from afterdrive import config_store
        return config_store.get_prompts_juego()
    except Exception:
        return "actuales"


def usar(cual: str, base=None) -> dict:
    if cual not in JUEGOS:
        raise ErrorPromptIA("Elegí 'actuales' o 'ia'.")
    _guardar_juego(cual)
    pe.invalidar_cache()
    return estado(base)


def _guardar_juego(cual: str) -> None:
    from afterdrive import config_store
    config_store.set_prompts_juego(cual)


def _copia_docs(base=None) -> dict:
    return {d["clave"]: d for d in _base(base)["prompts_ia"].find({}) if d.get("clave") in pe.CLAVES}


def en_uso(base=None) -> dict:
    """Las piezas de la copia que pisan a las actuales. Vacío si la redacción usa los actuales."""
    if juego() != "ia":
        return {}
    return {c: d["contenido"] for c, d in _copia_docs(base).items()
            if d.get("contenido") and not pe.validar(c, d["contenido"])["errores"]}


def _texto_copia(clave: str, docs: dict, base=None) -> str:
    d = docs.get(clave)
    return d["contenido"] if d else pe._activo(clave, base)["contenido"]


def pieza(clave: str, base=None) -> dict:
    pe._clave(clave)
    docs = _copia_docs(base)
    activo = pe._activo(clave, base)
    d = docs.get(clave)
    return {
        "clave": clave, "titulo": pe._titulo(clave),
        "actual": activo["contenido"], "version_actual": activo["version"],
        "ia": d["contenido"] if d else activo["contenido"],
        "cambiada": bool(d), "cambios": (d or {}).get("cambios", []),
        "desactualizada": bool(d) and d.get("base_version") != activo["version"],
    }


def estado(base=None) -> dict:
    b = _base(base)
    docs = _copia_docs(base)
    activos = {d["clave"]: d["version"] for d in pe._col(base).find({"estado": pe.ACTIVO}, {"clave": 1, "version": 1})}
    copia = []
    for item in pe.catalogo():
        d = docs.get(item["clave"])
        copia.append({
            "clave": item["clave"], "titulo": item["titulo"], "grupo": item["grupo"],
            "cambiada": bool(d), "cambios": len((d or {}).get("cambios", [])),
            "actualizado": (d or {}).get("actualizado"),
            "desactualizada": bool(d) and d.get("base_version") != activos.get(item["clave"], 0),
        })
    analisis = b["prompts_ia_analisis"].find_one(sort=[("fecha", -1)])
    propuestas = list(b["prompts_ia_propuestas"].find({"estado": "pendiente"}).sort("fecha", -1).limit(5))
    return {
        "usar": juego(), "copia": copia, "cambiadas": sum(c["cambiada"] for c in copia),
        "analisis": _publico(analisis), "propuestas": [_publico(p) for p in propuestas],
    }


def _publico(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


# ── Análisis de las notas ─────────────────────────────────────────────────────

def _promedio(valores) -> float | None:
    v = [float(x) for x in valores if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return round(sum(v) / len(v), 1) if v else None


def estadisticas(notas: list[dict]) -> dict:
    """Lo que dicen las calificaciones de estas notas, sin IA: promedios y lo que más se repite."""
    from afterdrive.generacion import juez

    criticas = [n["critica"] for n in notas if isinstance(n.get("critica"), dict) and not n["critica"].get("error")]
    juicios = [n["juicio"] for n in notas if isinstance(n.get("juicio"), dict) and not n["juicio"].get("error")]
    humanas = [n["calificacion"] for n in notas if isinstance(n.get("calificacion"), dict)]

    errores = Counter()
    ejemplos: dict[str, list[str]] = {}
    for c in criticas:
        for e in c.get("errores") or []:
            tipo = e.get("tipo") or "redaccion"
            errores[tipo] += 1
            if e.get("problema") and len(ejemplos.setdefault(tipo, [])) < EJEMPLOS_POR_TIPO:
                ejemplos[tipo].append(e["problema"])
    alephee = Counter(k for j in juicios for k, v in (j.get("alephee") or {}).items() if v is False)
    etiquetas = Counter(e for x in juicios + humanas for e in x.get("etiquetas") or [])
    estilo = Counter(h.get("codigo") or h.get("detalle", "")[:40] for n in notas for h in n.get("estilo") or []
                     if isinstance(h, dict))
    por_juego: dict[str, dict] = {}
    for n in notas:
        g = n.get("prompts_juego") or "actuales"
        c = n.get("critica") if isinstance(n.get("critica"), dict) else {}
        j = n.get("juicio") if isinstance(n.get("juicio"), dict) else {}
        r = por_juego.setdefault(g, {"notas": 0, "_c": [], "_j": []})
        r["notas"] += 1
        r["_c"].append(c.get("puntaje"))
        r["_j"].append(j.get("calificacion"))
    for r in por_juego.values():
        r["redaccion"], r["juez"] = _promedio(r.pop("_c")), _promedio(r.pop("_j"))

    return {
        "notas": len(notas),
        "redaccion": _promedio(c.get("puntaje") for c in criticas),           # /10, la crítica
        "aspectos": {k: p for k, nombre in ASPECTOS.items()
                     if (p := _promedio((c.get("aspectos") or {}).get(k) for c in criticas)) is not None},
        "juez": _promedio(j.get("calificacion") for j in juicios),            # /5
        "pasa_juez": round(sum(bool(j.get("pasa")) for j in juicios) / len(juicios), 2) if juicios else None,
        "humana": _promedio(h.get("puntaje") for h in humanas),               # /5
        "errores": [{"tipo": t, "nombre": ASPECTOS.get(t, t), "veces": n, "ejemplos": ejemplos.get(t, [])}
                    for t, n in errores.most_common()],
        "alephee": [{"punto": k, "texto": juez.CHECKLIST_ALEPHEE.get(k, k), "veces": n} for k, n in alephee.most_common()],
        "etiquetas": [{"etiqueta": e, "veces": n} for e, n in etiquetas.most_common(8)],
        "estilo": [{"codigo": c, "veces": n} for c, n in estilo.most_common(6) if c],
        "sin_respaldo": sum(bool((n.get("verificacion") or {}).get("sin_respaldo")) for n in notas),
        "rechazos": [n["motivo_rechazo"] for n in notas if n.get("motivo_rechazo")][:6],
        "comentarios": [h["comentario"] for h in humanas if h.get("comentario")][:6],
        "por_juego": por_juego,
    }


def _notas(limite: int, base=None) -> list[dict]:
    campos = {"critica": 1, "juicio": 1, "calificacion": 1, "estilo": 1, "verificacion.sin_respaldo": 1,
              "motivo_rechazo": 1, "prompts_juego": 1, "generado_en": 1}
    return list(_base(base)["notas_fase2"].find({}, campos).sort("_id", -1).limit(limite))


def _piezas_texto(base=None, docs: dict | None = None) -> str:
    docs = _copia_docs(base) if docs is None else docs
    return "\n\n".join(f"<pieza clave=\"{c['clave']}\" titulo=\"{c['titulo']}\">\n{_texto_copia(c['clave'], docs, base)}\n</pieza>"
                       for c in pe.catalogo())


_SYSTEM_ANALISIS = """Sos editor jefe y especialista en prompts de un blog del aftermarket automotor.
Un sistema escribe notas con un prompt armado por piezas en Markdown. Te paso las calificaciones de las
últimas notas (crítica de redacción /10, juez /5, calificaciones del equipo /5, errores que se repiten,
checklist de Alephee) y las piezas del prompt.

Explicá por qué las notas se quedan en 7 u 8 en vez de 9 o 10: qué se repite, qué regla del prompt no se
está cumpliendo o falta, y en qué pieza habría que tocar. Basate solo en los datos que te paso; si algo no
tiene datos, no lo afirmes.

Respondé SOLO un JSON:
{"resumen": "2 o 3 oraciones",
 "problemas": [{"titulo": "corto", "detalle": "qué pasa y por qué", "evidencia": "qué dato lo muestra",
                "pieza": "clave de la pieza a cambiar", "pedido": "el cambio concreto que le pedirías al prompt"}]}
Como mucho 6 problemas, del más importante al menos importante."""


def analizar(limite: int = NOTAS_ANALISIS, base=None) -> dict:
    """Estadísticas de las últimas notas y el diagnóstico de la IA. Se guarda: el último se ve en Prompts."""
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    notas = _notas(limite, base)
    if not notas:
        raise ErrorPromptIA("Todavía no hay notas para analizar.")
    est = estadisticas(notas)
    doc = {"fecha": _ahora(), "estadisticas": est}
    if not llm.disponible():
        doc["error"] = "La IA no está disponible: se muestran solo los números."
    else:
        user = (f"## Calificaciones de las últimas {est['notas']} notas\n{json.dumps(est, ensure_ascii=False)}\n\n"
                f"## Piezas del prompt\n{_piezas_texto(base)}")
        try:
            data = _extraer_json(llm.completar(_SYSTEM_ANALISIS, user, temperature=0.2, max_tokens=1600,
                                               tarea="evaluacion"))
            doc["diagnostico"] = _diagnostico(data)
        except Exception as e:
            doc["error"] = f"La IA no pudo analizar las notas: {e}"
    r = _base(base)["prompts_ia_analisis"].insert_one(dict(doc))
    doc["id"] = str(r.inserted_id)
    doc.pop("_id", None)
    return doc


def _diagnostico(data) -> dict:
    if not isinstance(data, dict):
        raise ErrorPromptIA("La IA no devolvió un análisis legible.")
    problemas = []
    for p in data.get("problemas") or []:
        if not isinstance(p, dict) or not str(p.get("titulo") or "").strip():
            continue
        pieza = p.get("pieza") if p.get("pieza") in pe.CLAVES else ""
        problemas.append({k: str(p.get(k) or "").strip()[:400] for k in ("titulo", "detalle", "evidencia", "pedido")}
                         | {"pieza": pieza, "titulo_pieza": pe._titulo(pieza) if pieza else ""})
    return {"resumen": str(data.get("resumen") or "").strip()[:800], "problemas": problemas[:6]}


# ── Propuestas ────────────────────────────────────────────────────────────────

_SYSTEM_PROPUESTA = """Sos especialista en prompts. Te paso las piezas en Markdown del prompt con el que una IA
escribe notas para un blog del aftermarket automotor, el último diagnóstico de por qué las notas no sacan
mejor calificación y un pedido del equipo.

Reescribí SOLO las piezas que hagan falta para cumplir el pedido (como mucho 4). Cambios mínimos y
concretos: conservá lo que funciona, el formato de cada pieza (títulos ##, listas) y las llaves como
{extension}. En las piezas de persona mantené el rol arriba y las secciones ## Tu tarea, ## Estructura
(lista numerada) y ## Estilo. No inventes datos de Alephee: lo que se puede afirmar está en el enfoque Alephee.

Respondé SOLO un JSON:
{"comentario": "una oración sobre qué cambiaste",
 "cambios": [{"clave": "clave de la pieza", "explicacion": "qué cambiaste y por qué", "contenido": "la pieza completa nueva"}]}"""


def proponer(pedido: str, claves=None, base=None) -> dict:
    """La IA reescribe piezas de la copia según el pedido. Queda pendiente: se aplica a mano (aplicar)."""
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    pedido = " ".join(str(pedido or "").split())[:PEDIDO_MAX]
    if len(pedido) < 8:
        raise ErrorPromptIA("Contá qué querés cambiar en los prompts.")
    claves = [c for c in (claves or []) if c in pe.CLAVES]
    if not llm.disponible():
        raise ErrorPromptIA("La IA no está disponible para proponer cambios.")
    b = _base(base)
    docs = _copia_docs(base)
    analisis = b["prompts_ia_analisis"].find_one({"diagnostico": {"$exists": True}}, sort=[("fecha", -1)])
    user = f"## Pedido del equipo\n{pedido}\n\n"
    if claves:
        user += "## Piezas que se pueden cambiar\n" + ", ".join(claves) + "\n\n"
    if analisis:
        user += "## Último diagnóstico\n" + json.dumps(analisis["diagnostico"], ensure_ascii=False)[:4000] + "\n\n"
    user += f"## Piezas del prompt (la copia de la IA)\n{_piezas_texto(base, docs)}"
    try:
        data = _extraer_json(llm.completar(_SYSTEM_PROPUESTA, user, temperature=0.3, max_tokens=4000,
                                           tarea="correccion"))
    except Exception as e:
        raise ErrorPromptIA(f"La IA no pudo proponer cambios: {e}") from e
    data = data if isinstance(data, dict) else {}
    cambios = []
    for c in data.get("cambios") or []:
        clave = c.get("clave") if isinstance(c, dict) else None
        if clave not in pe.CLAVES or (claves and clave not in claves) or any(x["clave"] == clave for x in cambios):
            continue
        despues = str(c.get("contenido") or "").replace("\r\n", "\n").strip()
        antes = _texto_copia(clave, docs, base)
        if not despues or despues == antes.strip():
            continue
        v = pe.validar(clave, despues)
        cambios.append({"clave": clave, "titulo": pe._titulo(clave), "antes": antes, "despues": despues,
                        "explicacion": str(c.get("explicacion") or "").strip()[:600],
                        "errores": v["errores"], "avisos": v["avisos"]})
        if len(cambios) >= PROPUESTA_MAX_PIEZAS:
            break
    if not cambios:
        raise ErrorPromptIA("La IA no propuso ningún cambio para ese pedido. Probá contarlo de otra manera.")
    doc = {"fecha": _ahora(), "pedido": pedido, "estado": "pendiente", "cambios": cambios,
           "comentario": str(data.get("comentario") or "").strip()[:400]}
    r = b["prompts_ia_propuestas"].insert_one(dict(doc))
    return _publico(doc | {"_id": r.inserted_id})


def _propuesta(propuesta_id, base=None) -> dict:
    doc = _base(base)["prompts_ia_propuestas"].find_one({"_id": _oid(propuesta_id)})
    if not doc:
        raise ErrorPromptIA("Propuesta inexistente.")
    if doc.get("estado") != "pendiente":
        raise ErrorPromptIA("Esa propuesta ya se aplicó o se descartó.")
    return doc


def aplicar(propuesta_id, claves=None, base=None) -> dict:
    """Pasa los cambios de la propuesta a la copia de la IA. Los actuales no se tocan."""
    doc = _propuesta(propuesta_id, base)
    b, ahora = _base(base), _ahora()
    elegidos = [c for c in doc["cambios"] if not c.get("errores") and (not claves or c["clave"] in claves)]
    if not elegidos:
        raise ErrorPromptIA("No hay cambios aplicables: corregí los errores o elegí otra pieza.")
    for c in elegidos:
        activo = pe._activo(c["clave"], base)
        b["prompts_ia"].update_one({"clave": c["clave"]}, {
            "$set": {"contenido": c["despues"], "base_version": activo["version"],
                     "base_contenido": activo["contenido"], "actualizado": ahora},
            "$push": {"cambios": {"fecha": ahora, "pedido": doc["pedido"], "explicacion": c["explicacion"]}},
        }, upsert=True)
    b["prompts_ia_propuestas"].update_one({"_id": doc["_id"]}, {"$set": {
        "estado": "aplicada", "aplicada": ahora, "aplicadas": [c["clave"] for c in elegidos]}})
    pe.invalidar_cache()
    return estado(base)


def descartar(propuesta_id, base=None) -> None:
    doc = _propuesta(propuesta_id, base)
    _base(base)["prompts_ia_propuestas"].update_one({"_id": doc["_id"]},
                                                    {"$set": {"estado": "descartada", "descartada": _ahora()}})


def restablecer(clave: str | None = None, base=None) -> int:
    """La copia de una pieza (o toda) vuelve a ser igual a los prompts actuales."""
    filtro = {}
    if clave:
        pe._clave(clave)
        filtro = {"clave": clave}
    n = _base(base)["prompts_ia"].delete_many(filtro).deleted_count
    pe.invalidar_cache()
    return n
