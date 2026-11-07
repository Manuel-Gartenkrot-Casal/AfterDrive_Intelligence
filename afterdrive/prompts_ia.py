"""
prompts_ia.py — Prompts con IA: la IA analiza las calificaciones de las notas y mejora sola una COPIA
de los prompts. Los prompts actuales no se tocan nunca desde acá.

Interfaz:
    juego() -> "actuales" | "ia"                con qué prompts escribe la redacción
    usar(juego, base=None) -> dict              elegir el juego
    auto() -> bool / set_auto(si, base=None)    si la IA mejora la copia sola (cada AUTO_CADA notas nuevas)
    en_uso(base=None) -> {clave: contenido}     lo que la copia pisa de los actuales (vacío con "actuales")
    estado(base=None) -> dict                   juego, auto, la copia, el último análisis y las últimas mejoras
    pieza(clave, base=None) -> dict             el texto actual y el de la copia de una pieza
    textos(juego, base=None) -> {clave: contenido}  todas las piezas de "actuales" o de "ia" (para mostrarlas)
    estadisticas(notas) -> dict                 promedios y lo que más falla (sin IA)
    analizar(limite=NOTAS_ANALISIS, base=None) -> dict
    mejorar(pedido=None, claves=None, origen="manual", base=None) -> dict
        Sin pedido: analiza las notas y con ese diagnóstico la IA reescribe las piezas que hagan falta.
        Con pedido: la IA reescribe según lo pedido (usa el último diagnóstico de contexto).
        Los cambios válidos se aplican directo a la copia; cada uno guarda el texto anterior.
    mejora_automatica(base=None) -> dict | None corre mejorar() si está prendida y hay AUTO_CADA notas nuevas
    deshacer(clave, base=None) -> dict          la copia de esa pieza vuelve a como estaba antes del último cambio
    restablecer(clave=None, base=None) -> int   la copia (o una pieza) vuelve a ser igual a los actuales

    python -m afterdrive.prompts_ia [--pedido "..."] [--claves seo formato] [--auto]
        (lo encola el dashboard: corre en la cola y el registro se ve en la terminal)

La copia de la IA es un duplicado de los Markdown de prompts_editables: una pieza
que la IA no cambió es igual a la actual; una que cambió queda en `prompts_ia` con
su historial. En Prompts se elige con cuál escribe la redacción ("actuales" o "ia").
Cada nota guarda con cuál se escribió (`prompts_juego`), así el análisis compara.

Colecciones:
    prompts_ia          clave, contenido, base_version, base_contenido,
                        cambios [{fecha, origen, pedido, explicacion, antes}], actualizado
    prompts_ia_analisis fecha, estadisticas, diagnostico {resumen, problemas [...]} o error
    prompts_ia_mejoras  fecha, origen (automatica | manual | pedido), pedido, resumen, comentario, error,
                        cambios [{clave, titulo, antes, despues, explicacion, errores, avisos, aplicado}]
    prompts_ia_estado   _id "auto": ultima_nota (id), fecha — hasta dónde miró la mejora automática
"""

from __future__ import annotations

import argparse
import datetime
import json
from collections import Counter

from bson import ObjectId
from bson.errors import InvalidId

from afterdrive import prompts_editables as pe

JUEGOS = ("actuales", "ia")
NOTAS_ANALISIS = 40
AUTO_CADA = 5           # notas nuevas entre una mejora automática y la siguiente
PEDIDO_MAX = 1500
EJEMPLOS_POR_TIPO = 4
CAMBIOS_MAX = 13        # piezas que puede reescribir una mejora (todas)
MEJORAS_A_LA_VISTA = 8

ASPECTOS = {"gramatica": "Gramática", "ortografia": "Ortografía", "redaccion": "Redacción", "tono": "Tono",
            "estructura": "Estructura"}


class ErrorPromptIA(Exception):
    """Un pedido que no se puede hacer (sin IA, pedido vacío, nada que deshacer...)."""


def _base(base):
    if base is None:
        from afterdrive.db import db
        return db
    return base


def _ahora() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _publico(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


# ── Configuración: qué juego se usa y si la mejora es automática ──────────────

def _config() -> dict:
    try:
        from afterdrive import config_store
        return config_store.get_prompts_ia_config()
    except Exception:
        return {"usar": "actuales", "auto": True}


def _guardar_config(**cambios) -> None:
    from afterdrive import config_store
    config_store.set_prompts_ia_config({**_config(), **cambios})


def juego() -> str:
    usar = _config().get("usar")
    return usar if usar in JUEGOS else "actuales"


def auto() -> bool:
    return bool(_config().get("auto", True))


def usar(cual: str, base=None) -> dict:
    if cual not in JUEGOS:
        raise ErrorPromptIA("Elegí 'actuales' o 'ia'.")
    _guardar_config(usar=cual)
    pe.invalidar_cache()
    return estado(base)


def set_auto(si: bool, base=None) -> dict:
    _guardar_config(auto=bool(si))
    return estado(base)


# ── La copia ──────────────────────────────────────────────────────────────────

def _copia_docs(base=None) -> dict:
    return {d["clave"]: d for d in _base(base)["prompts_ia"].find({}) if d.get("clave") in pe.CLAVES}


def en_uso(base=None) -> dict:
    """Las piezas de la copia que pisan a las actuales. Vacío si la redacción usa los actuales."""
    if juego() != "ia":
        return {}
    return {c: d["contenido"] for c, d in _copia_docs(base).items()
            if d.get("contenido") and not pe.validar(c, d["contenido"])["errores"]}


def textos(cual: str, base=None) -> dict:
    """{clave: contenido} de todas las piezas de un juego: "actuales" (lo aprobado o el original) o "ia"
    (la copia: lo que cambió la IA y, en lo demás, lo actual). Para mostrar cada juego por separado."""
    datos = _originales()
    datos.update(pe.aprobados(base))
    if cual == "ia":
        datos.update({c: d["contenido"] for c, d in _copia_docs(base).items() if d.get("contenido")})
    return datos


def _originales() -> dict:
    from afterdrive.ia import redaccion
    return {c: redaccion.PIEZAS[c] for c in pe.CLAVES}


def _texto_copia(clave: str, docs: dict, base=None) -> str:
    d = docs.get(clave)
    return d["contenido"] if d else pe._activo(clave, base)["contenido"]


def _cambios_publicos(cambios) -> list[dict]:
    return [{k: v for k, v in c.items() if k != "antes"} for c in cambios or []]


def pieza(clave: str, base=None) -> dict:
    pe._clave(clave)
    d = _copia_docs(base).get(clave)
    activo = pe._activo(clave, base)
    return {
        "clave": clave, "titulo": pe._titulo(clave),
        "actual": activo["contenido"], "version_actual": activo["version"],
        "ia": d["contenido"] if d else activo["contenido"],
        "cambiada": bool(d), "cambios": _cambios_publicos((d or {}).get("cambios")),
        "desactualizada": bool(d) and d.get("base_version") != activo["version"],
    }


def _nuevas_desde_auto(base=None) -> int:
    b = _base(base)
    marca = b["prompts_ia_estado"].find_one({"_id": "auto"}) or {}
    filtro = {}
    if marca.get("ultima_nota"):
        try:
            filtro = {"_id": {"$gt": ObjectId(marca["ultima_nota"])}}
        except (InvalidId, TypeError):
            filtro = {}
    return b["notas_fase2"].count_documents(filtro)


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
    mejoras = list(b["prompts_ia_mejoras"].find().sort("fecha", -1).limit(MEJORAS_A_LA_VISTA))
    return {
        "usar": juego(), "auto": auto(), "auto_cada": AUTO_CADA,
        "faltan": max(0, AUTO_CADA - _nuevas_desde_auto(base)),
        "copia": copia, "cambiadas": sum(c["cambiada"] for c in copia),
        "analisis": _publico(analisis), "mejoras": [_publico(m) for m in mejoras],
    }


# ── JSON de la IA: tolerante ──────────────────────────────────────────────────

def _escapar_comillas(texto: str) -> str:
    """Escapa las comillas dobles que quedaron sueltas dentro de un valor ("la tecnología" adentro de un
    texto rompe el JSON): una comilla dentro de un string que no va seguida de , } ] o : no lo cierra."""
    salida, en_texto, i = [], False, 0
    while i < len(texto):
        c = texto[i]
        if c == "\\" and en_texto:
            salida.append(texto[i:i + 2])
            i += 2
            continue
        if c == '"':
            if not en_texto:
                en_texto = True
            else:
                resto = texto[i + 1:].lstrip()
                if not resto or resto[0] in ",}]:":
                    en_texto = False
                else:
                    salida.append('\\"')
                    i += 1
                    continue
        salida.append(c)
        i += 1
    return "".join(salida)


def _leer_json(texto: str):
    from afterdrive.ia.lm_studio import _extraer_json

    try:
        return _extraer_json(texto)
    except (json.JSONDecodeError, ValueError):
        pass
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin < inicio:
        raise json.JSONDecodeError("sin objeto JSON en la respuesta", texto, 0)
    crudo = texto[inicio:fin + 1]
    for candidato in (crudo, _escapar_comillas(crudo), _sumar_comas(_escapar_comillas(crudo))):
        try:
            return json.loads(candidato, strict=False)   # strict=False: acepta saltos de línea dentro de los textos
        except json.JSONDecodeError:
            continue
    return json.loads(_sumar_comas(_escapar_comillas(crudo)), strict=False)


def _sumar_comas(texto: str) -> str:
    """Agrega la coma que la IA a veces olvida entre dos elementos que terminan y empiezan en renglones
    distintos ("}\n  {" o "\"\n  \"") — el error de producción era «Expecting ',' delimiter» al principio
    de un renglón."""
    import re
    return re.sub(r'(["}\]0-9]|true|false|null)(\s*\n\s*)(["{\[])', r"\1,\2\3", texto)


_SYSTEM_JSON = """Te paso una respuesta que debía ser un JSON y no se puede leer. Devolvé exactamente el mismo
contenido como JSON válido: escapá las comillas dobles dentro de los textos y los saltos de línea como \\n.
No cambies, agregues ni saques nada. Respondé SOLO el JSON."""


def _pedir_json(system: str, user: str, max_tokens: int, tarea: str):
    """Le pide un JSON a la IA. Si no se puede leer, lo repara; si tampoco, le pide que lo corrija (una vez)."""
    from afterdrive.ia import llm

    texto = llm.completar(system, user, temperature=0.2, max_tokens=max_tokens, tarea=tarea)
    try:
        return _leer_json(texto)
    except (json.JSONDecodeError, ValueError):
        print("[PROMPTS IA] La respuesta de la IA no era un JSON válido: se le pide que la corrija...", flush=True)
    return _leer_json(llm.completar(_SYSTEM_JSON, texto, temperature=0.0, max_tokens=max_tokens, tarea=tarea))


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
        "aspectos": {k: p for k in ASPECTOS
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


def _piezas_texto(docs: dict, base=None) -> str:
    return "\n\n".join(f"<pieza clave=\"{c['clave']}\" titulo=\"{c['titulo']}\">\n{_texto_copia(c['clave'], docs, base)}\n</pieza>"
                       for c in pe.catalogo())


_SYSTEM_ANALISIS = """Sos editor jefe y especialista en prompts de un blog del aftermarket automotor.
Un sistema escribe notas con un prompt armado por piezas en Markdown. Te paso las calificaciones de las
últimas notas (crítica de redacción /10, juez /5, calificaciones del equipo /5, errores que se repiten,
checklist de Alephee, motivos de rechazo) y las piezas del prompt.

Explicá por qué las notas se quedan en 7 u 8 en vez de 9 o 10: qué se repite, qué regla del prompt no se
está cumpliendo o falta, y en qué pieza habría que tocar. Basate solo en los datos que te paso; si algo no
tiene datos, no lo afirmes.

Respondé SOLO un JSON válido. Dentro de los textos no uses comillas dobles: usá «» o comillas simples.
{"resumen": "2 o 3 oraciones",
 "problemas": [{"titulo": "corto", "detalle": "qué pasa y por qué", "evidencia": "qué dato lo muestra",
                "pieza": "clave de la pieza a cambiar", "pedido": "el cambio concreto que le harías al prompt"}]}
Como mucho 6 problemas, del más importante al menos importante."""


def analizar(limite: int = NOTAS_ANALISIS, base=None) -> dict:
    """Estadísticas de las últimas notas y el diagnóstico de la IA. Se guarda: el último se ve en Prompts."""
    from afterdrive.ia import llm

    notas = _notas(limite, base)
    if not notas:
        raise ErrorPromptIA("Todavía no hay notas para analizar.")
    est = estadisticas(notas)
    doc = {"fecha": _ahora(), "estadisticas": est}
    if not llm.disponible():
        doc["error"] = "La IA no está disponible: se muestran solo los números."
    else:
        user = (f"## Calificaciones de las últimas {est['notas']} notas\n{json.dumps(est, ensure_ascii=False)}\n\n"
                f"## Piezas del prompt (la copia de la IA)\n{_piezas_texto(_copia_docs(base), base)}")
        try:
            data = _pedir_json(_SYSTEM_ANALISIS, user, 2500, "evaluacion")
            doc["diagnostico"] = _diagnostico(data)
        except Exception as e:
            doc["error"] = f"La IA no pudo analizar las notas: {e}"
    r = _base(base)["prompts_ia_analisis"].insert_one(dict(doc))
    return _publico(doc | {"_id": r.inserted_id})


def _diagnostico(data) -> dict:
    if not isinstance(data, dict):
        raise ErrorPromptIA("La IA no devolvió un análisis legible.")
    problemas = []
    for p in data.get("problemas") or []:
        if not isinstance(p, dict) or not str(p.get("titulo") or "").strip():
            continue
        pieza_ = p.get("pieza") if p.get("pieza") in pe.CLAVES else ""
        problemas.append({k: str(p.get(k) or "").strip()[:400] for k in ("titulo", "detalle", "evidencia", "pedido")}
                         | {"pieza": pieza_, "titulo_pieza": pe._titulo(pieza_) if pieza_ else ""})
    return {"resumen": str(data.get("resumen") or "").strip()[:800], "problemas": problemas[:6]}


# ── Mejorar la copia ──────────────────────────────────────────────────────────

_SYSTEM_MEJORA = """Sos especialista en prompts. Te paso las piezas en Markdown del prompt con el que una IA
escribe notas para un blog del aftermarket automotor, el diagnóstico de por qué las notas no sacan mejor
calificación y lo que hay que resolver.

Reescribí todas las piezas que hagan falta para resolverlo, y solo esas. Cambios mínimos y concretos: conservá lo que
funciona, el formato de cada pieza (títulos ##, listas) y las llaves como {extension}. En las piezas de
persona mantené el rol arriba y las secciones ## Tu tarea, ## Estructura (lista numerada) y ## Estilo. No
inventes datos de Alephee: lo que se puede afirmar está en el enfoque Alephee.

Respondé SOLO un JSON válido: en "contenido", escapá las comillas dobles (\\") y los saltos de línea (\\n).
{"comentario": "una oración sobre qué cambiaste",
 "cambios": [{"clave": "clave de la pieza", "explicacion": "qué cambiaste y por qué", "contenido": "la pieza completa nueva"}]}"""


def _pedido_del_diagnostico(diagnostico: dict) -> str:
    lineas = [f"- {p['titulo']}: {p.get('pedido') or p.get('detalle')}" + (f" (pieza: {p['pieza']})" if p.get("pieza") else "")
              for p in diagnostico.get("problemas") or []]
    return "Resolvé los problemas del diagnóstico:\n" + "\n".join(lineas)


def _proponer(pedido: str, claves: list[str], docs: dict, diagnostico: dict | None, base=None) -> tuple[list, str]:
    """Lo que la IA reescribiría: [{clave, titulo, antes, despues, explicacion, errores, avisos}], comentario."""
    user = f"## Qué hay que resolver\n{pedido}\n\n"
    if claves:
        user += "## Piezas que se pueden cambiar\n" + ", ".join(claves) + "\n\n"
    if diagnostico:
        user += "## Diagnóstico de las notas\n" + json.dumps(diagnostico, ensure_ascii=False)[:4000] + "\n\n"
    user += f"## Piezas del prompt (la copia de la IA)\n{_piezas_texto(docs, base)}"
    try:
        data = _pedir_json(_SYSTEM_MEJORA, user, 6000, "correccion")
    except Exception as e:
        raise ErrorPromptIA(f"La IA no pudo reescribir los prompts: {e}") from e
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
        if len(cambios) >= CAMBIOS_MAX:
            break
    return cambios, str(data.get("comentario") or "").strip()[:400]


_SYSTEM_REPARAR = """Sos especialista en prompts. Estas piezas en Markdown de un prompt no pasaron la validación.
Corregí cada una para que cumpla lo que dicen los errores, sin perder el cambio que se quiso hacer. En las
piezas de persona: el rol arriba y las secciones ## Tu tarea, ## Estructura (lista numerada) y ## Estilo.

Respondé SOLO un JSON: {"cambios": [{"clave": "...", "contenido": "la pieza completa corregida"}]}"""


def _reparar(cambios: list[dict]) -> None:
    """A los cambios que no pasaron la validación, se los devuelve a la IA con los errores (una vez)."""
    rotos = [c for c in cambios if c["errores"]]
    if not rotos:
        return
    print(f"[PROMPTS IA] Corrigiendo {len(rotos)} pieza(s) que no pasaron la validación...", flush=True)
    user = "\n\n".join(f"<pieza clave=\"{c['clave']}\">\n## Errores\n" + "\n".join(f"- {e}" for e in c["errores"])
                       + f"\n## Texto\n{c['despues']}\n</pieza>" for c in rotos)
    try:
        data = _pedir_json(_SYSTEM_REPARAR, user, 6000, "correccion")
    except Exception as e:
        print(f"[PROMPTS IA] [AVISO] No se pudieron corregir: {e}", flush=True)
        return
    nuevos = {c.get("clave"): str(c.get("contenido") or "").replace("\r\n", "\n").strip()
              for c in (data.get("cambios") or [] if isinstance(data, dict) else []) if isinstance(c, dict)}
    for c in rotos:
        texto = nuevos.get(c["clave"])
        if texto:
            v = pe.validar(c["clave"], texto)
            if not v["errores"]:
                c.update(despues=texto, errores=[], avisos=v["avisos"])


def _aplicar(cambios: list[dict], origen: str, pedido: str, base=None) -> list[str]:
    """Pasa a la copia los cambios sin errores. Cada uno guarda el texto anterior (para deshacer)."""
    b, ahora, aplicadas = _base(base), _ahora(), []
    for c in cambios:
        c["aplicado"] = not c["errores"]
        if not c["aplicado"]:
            continue
        activo = pe._activo(c["clave"], base)
        b["prompts_ia"].update_one({"clave": c["clave"]}, {
            "$set": {"contenido": c["despues"], "base_version": activo["version"],
                     "base_contenido": activo["contenido"], "actualizado": ahora},
            "$push": {"cambios": {"fecha": ahora, "origen": origen, "pedido": pedido[:PEDIDO_MAX],
                                  "explicacion": c["explicacion"], "antes": c["antes"]}},
        }, upsert=True)
        aplicadas.append(c["clave"])
    if aplicadas:
        pe.invalidar_cache()
    return aplicadas


def mejorar(pedido: str | None = None, claves=None, origen: str = "manual", base=None) -> dict:
    """Analiza (sin pedido) o toma el pedido, y la IA mejora la copia. Los cambios válidos se aplican solos."""
    from afterdrive.ia import llm

    b = _base(base)
    pedido = " ".join(str(pedido or "").split())[:PEDIDO_MAX]
    claves = [c for c in (claves or []) if c in pe.CLAVES]
    if pedido and len(pedido) < 8:
        raise ErrorPromptIA("Contá qué querés cambiar en los prompts.")
    if not llm.disponible():
        raise ErrorPromptIA("La IA no está disponible para mejorar los prompts.")
    mejora = {"fecha": _ahora(), "origen": "pedido" if pedido else origen, "pedido": pedido, "cambios": []}
    if pedido:
        ultimo = b["prompts_ia_analisis"].find_one({"diagnostico": {"$exists": True}}, sort=[("fecha", -1)])
        diagnostico = (ultimo or {}).get("diagnostico")
    else:
        print("[PROMPTS IA] Analizando las calificaciones de las últimas notas...", flush=True)
        analisis = analizar(base=base)
        diagnostico = analisis.get("diagnostico")
        mejora["analisis_id"] = analisis["id"]
        if not diagnostico:
            mejora["error"] = analisis.get("error") or "Sin diagnóstico."
        elif not diagnostico["problemas"]:
            mejora["error"] = "La IA no encontró nada para mejorar en los prompts."
        else:
            mejora["resumen"] = diagnostico["resumen"]
    if not mejora.get("error"):
        print("[PROMPTS IA] La IA está reescribiendo la copia de los prompts...", flush=True)
        try:
            cambios, comentario = _proponer(pedido or _pedido_del_diagnostico(diagnostico), claves,
                                            _copia_docs(base), diagnostico, base)
        except ErrorPromptIA as e:
            cambios, comentario, mejora["error"] = [], "", str(e)
        _reparar(cambios)
        mejora["comentario"] = comentario
        aplicadas = _aplicar(cambios, mejora["origen"], pedido or mejora.get("resumen", ""), base)
        mejora["cambios"] = cambios
        if not cambios and not mejora.get("error"):
            mejora["error"] = "La IA no propuso cambios."
        elif cambios and not aplicadas:
            mejora["error"] = "Los cambios propuestos no pasaron la validación: no se aplicó ninguno."
        for c in cambios:
            print(f"[PROMPTS IA] {'[OK] Cambiada' if c['aplicado'] else '[AVISO] Sin aplicar'}: {c['titulo']}"
                  + (f" ({'; '.join(c['errores'])})" if c["errores"] else ""), flush=True)
    if mejora.get("error"):
        print(f"[PROMPTS IA] [AVISO] {mejora['error']}", flush=True)
    r = b["prompts_ia_mejoras"].insert_one(dict(mejora))
    return _publico(mejora | {"_id": r.inserted_id})


def mejora_automatica(base=None) -> dict | None:
    """Si la mejora automática está prendida y hay AUTO_CADA notas nuevas desde la última, mejora la copia."""
    from afterdrive.ia import llm

    if not auto():
        return None
    nuevas = _nuevas_desde_auto(base)
    if nuevas < AUTO_CADA or not llm.disponible():
        return None
    b = _base(base)
    ultima = b["notas_fase2"].find_one(sort=[("_id", -1)], projection={"_id": 1})
    b["prompts_ia_estado"].replace_one({"_id": "auto"}, {"_id": "auto", "ultima_nota": str(ultima["_id"]),
                                                         "fecha": _ahora()}, upsert=True)
    print(f"[PROMPTS IA] Mejora automática: {nuevas} notas nuevas desde la última.", flush=True)
    try:
        return mejorar(origen="automatica", base=base)
    except ErrorPromptIA as e:
        print(f"[PROMPTS IA] [AVISO] {e}", flush=True)
        return None


def deshacer(clave: str, base=None) -> dict:
    """La copia de la pieza vuelve a como estaba antes de su último cambio."""
    pe._clave(clave)
    col = _base(base)["prompts_ia"]
    d = col.find_one({"clave": clave})
    if not d or not d.get("cambios"):
        raise ErrorPromptIA("Esa pieza no tiene cambios de la IA para deshacer.")
    ultimo, resto = d["cambios"][-1], d["cambios"][:-1]
    activo = pe._activo(clave, base)
    if not resto or (ultimo.get("antes") or "").strip() == activo["contenido"].strip():
        col.delete_one({"_id": d["_id"]})
    else:
        col.update_one({"_id": d["_id"]}, {"$set": {"contenido": ultimo["antes"], "cambios": resto, "actualizado": _ahora()}})
    pe.invalidar_cache()
    return pieza(clave, base)


def restablecer(clave: str | None = None, base=None) -> int:
    """La copia de una pieza (o toda) vuelve a ser igual a los prompts actuales."""
    filtro = {}
    if clave:
        pe._clave(clave)
        filtro = {"clave": clave}
    n = _base(base)["prompts_ia"].delete_many(filtro).deleted_count
    pe.invalidar_cache()
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mejorar la copia de la IA de los prompts")
    p.add_argument("--pedido", default="", help="lo que hay que cambiar; sin pedido, analiza las notas")
    p.add_argument("--claves", nargs="*", default=[], help="piezas que se pueden cambiar")
    p.add_argument("--auto", action="store_true", help="solo si toca la mejora automática")
    args = p.parse_args(argv)
    try:
        if args.auto:
            r = mejora_automatica()
            if r is None:
                print("[PROMPTS IA] No toca la mejora automática todavía.", flush=True)
                return 0
        else:
            r = mejorar(pedido=args.pedido or None, claves=args.claves)
    except ErrorPromptIA as e:
        print(f"[ERROR] {e}", flush=True)
        return 1
    aplicadas = [c["titulo"] for c in r.get("cambios", []) if c.get("aplicado")]
    if aplicadas:
        print(f"[OK] Copia de la IA mejorada: {', '.join(aplicadas)}.", flush=True)
        return 0
    print(f"[ERROR] {r.get('error') or 'No se aplicó ningún cambio.'}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
