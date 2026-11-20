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
        Con pedido: la IA reescribe según lo pedido, sin mezclar mejoras del diagnóstico automático.
        Los cambios se aplican solo después de una comparación sin regresiones; cada uno guarda el texto anterior.
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
                        _id "validada": textos, huella, base, modelo, evaluación y retiro por regresión
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import unicodedata
from collections import Counter

from bson import ObjectId
from bson.errors import InvalidId

from afterdrive import prompts_editables as pe
from afterdrive import prompts_evaluacion as prueba
from afterdrive.ia import llm

JUEGOS = ("actuales", "ia")
NOTAS_ANALISIS = 40
AUTO_CADA = 5           # notas nuevas entre una mejora automática y la siguiente
PEDIDO_MAX = 1500
EJEMPLOS_POR_TIPO = 4
CAMBIOS_MAX = len(pe.CLAVES)  # piezas que puede reescribir una mejora (todas)
MEJORAS_A_LA_VISTA = 8
# Solo frena el inflado descontrolado (Formato llegó a 11 veces su largo): si un cambio empeora las notas
# lo frena la comparación (prompts_evaluacion). Con 1,5x / +400 el modelo se pasaba siempre por poco.
CRECIMIENTO_MAX = 2.0   # una pieza de la copia puede llegar al doble de su largo aprobado...
CRECIMIENTO_MIN = 800   # ...o 800 caracteres más, lo que sea más (las piezas cortas necesitan margen)

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


def juego(base=None) -> str:
    return "ia" if _config().get("usar") == "ia" and _validada(base) else "actuales"


def auto() -> bool:
    return bool(_config().get("auto", True))


def usar(cual: str, base=None) -> dict:
    if cual not in JUEGOS:
        raise ErrorPromptIA("Elegí 'actuales' o 'ia'.")
    if cual == "ia" and not _validada(base):
        raise ErrorPromptIA("La copia todavía no tiene una validación vigente. Analizá y mejorá antes de usarla.")
    _guardar_config(usar=cual)
    pe.invalidar_cache()
    return estado(base)


def set_auto(si: bool, base=None) -> dict:
    _guardar_config(auto=bool(si))
    return estado(base)


# ── La copia ──────────────────────────────────────────────────────────────────

def _copia_docs(base=None) -> dict:
    return {d["clave"]: d for d in _base(base)["prompts_ia"].find({}) if d.get("clave") in pe.CLAVES}


def _validada(base=None) -> dict | None:
    """Nunca activar cambios antiguos, parciales, retirados o evaluados con otra base/modelo."""
    d = _base(base)["prompts_ia_estado"].find_one({"_id": "validada"})
    if not d or d.get("retirada") or d.get("base") != prueba.huella(textos("actuales", base)):
        return None
    if d.get("huella") != prueba.huella(textos("ia", base)):
        return None
    if d.get("modelo") != prueba.modelo():
        return None
    return d


def en_uso(base=None) -> dict:
    if _config().get("usar") != "ia":
        return {}
    d = _validada(base)
    if not d:
        return {}
    actuales = textos("actuales", base)
    return {c: t for c, t in d["textos"].items() if t != actuales[c]}


def instantanea(base=None) -> dict:
    actuales = textos("actuales", base)
    d = _validada(base) if _config().get("usar") == "ia" else None
    piezas = d["textos"] if d else actuales
    return {"juego": "ia" if d else "actuales", "huella": prueba.huella(piezas),
            "piezas": piezas, "referencia": actuales}


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
        "cambiada": bool(d) and d.get("contenido") != activo["contenido"], "cambios": _cambios_publicos((d or {}).get("cambios")),
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
    actuales = textos("actuales", base)
    copia = []
    for item in pe.catalogo():
        d = docs.get(item["clave"])
        copia.append({
            "clave": item["clave"], "titulo": item["titulo"], "grupo": item["grupo"],
            "cambiada": bool(d) and d.get("contenido") != actuales[item["clave"]],
            "cambios": len((d or {}).get("cambios", [])),
            "actualizado": (d or {}).get("actualizado"),
            "desactualizada": bool(d) and d.get("base_version") != activos.get(item["clave"], 0),
        })
    analisis = b["prompts_ia_analisis"].find_one(sort=[("fecha", -1)])
    mejoras = list(b["prompts_ia_mejoras"].find().sort("fecha", -1).limit(MEJORAS_A_LA_VISTA))
    return {
        "usar": juego(base), "auto": auto(),
        "validada": bool(_validada(base)),
        "aviso": ("La copia no tiene una prueba vigente. La redacción usa los prompts actuales hasta validarla."
                  if docs and not _validada(base) else ""), "auto_cada": AUTO_CADA,
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
                ejemplos[tipo].append({"problema": e["problema"], "fragmento": e.get("fragmento", ""),
                                       "sugerencia": e.get("sugerencia", "")})
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
              "motivo_rechazo": 1, "prompts_juego": 1, "prompts_huella": 1, "generado_en": 1}
    col = _base(base)["notas_fase2"]
    firma = instantanea(base)["huella"]
    filtro = {"prompts_huella": firma}
    if not col.count_documents(filtro):
        # Las notas históricas no identifican su versión: no atribuirles una mejora causal.
        filtro = {"prompts_huella": {"$exists": False}}
    return list(col.find(filtro, campos).sort("_id", -1).limit(limite))


def _piezas_texto(docs: dict, base=None) -> str:
    return "\n\n".join(f"<pieza clave=\"{c['clave']}\" titulo=\"{c['titulo']}\">\n"
                       f"Uso: {c['descripcion']}\n{_texto_copia(c['clave'], docs, base)}\n</pieza>"
                       for c in pe.catalogo())


_SYSTEM_ANALISIS = """Sos editor jefe y especialista en prompts de un blog del aftermarket automotor.
Un sistema escribe notas con un prompt armado por piezas en Markdown. Te paso las calificaciones de las
últimas notas (crítica de redacción /10, juez /5, calificaciones del equipo /5, errores que se repiten,
checklist de Alephee, motivos de rechazo) y las piezas del prompt.

No inventes una causa a partir de un promedio. Conservá las reglas que ya producen buenas notas.
Buscá errores repetidos con fragmentos y sugerencias concretas; como máximo dos cambios focalizados.
Las fotos no afectan la calificación de redacción: no cambies imágenes a partir de estas métricas.
Explicá, solo donde haya evidencia, qué impide mejorar: qué se repite, qué regla del prompt no se
está cumpliendo o falta, y en qué pieza habría que tocar. Basate solo en los datos que te paso; si algo no
tiene datos, no lo afirmes.

Respondé SOLO un JSON válido. Dentro de los textos no uses comillas dobles: usá «» o comillas simples.
{"resumen": "2 o 3 oraciones",
 "problemas": [{"titulo": "corto", "detalle": "qué pasa y por qué", "evidencia": "qué dato lo muestra",
                "pieza": "clave de la pieza a cambiar", "pedido": "el cambio concreto que le harías al prompt"}]}
Como mucho 2 problemas, del más importante al menos importante."""


def analizar(limite: int = NOTAS_ANALISIS, base=None) -> dict:
    """Estadísticas de las últimas notas y el diagnóstico de la IA. Se guarda: el último se ve en Prompts."""
    from afterdrive.ia import llm

    notas = _notas(limite, base)
    if not notas:
        raise ErrorPromptIA("Todavía no hay notas para analizar.")
    est = estadisticas(notas)
    doc = {"fecha": _ahora(), "estadisticas": est,
           "prompts_huella": instantanea(base)["huella"],
           "historicas_sin_version": any(not n.get("prompts_huella") for n in notas)}
    if not llm.disponible():
        doc["error"] = "La IA no está disponible: se muestran solo los números."
    else:
        user = (f"## Calificaciones de las últimas {est['notas']} notas\n{json.dumps(est, ensure_ascii=False)}\n\n"
                f"## Piezas vigentes\n{_piezas_texto({k: {'contenido': v} for k, v in instantanea(base)['piezas'].items()}, base)}")
        try:
            data = _pedir_json(_SYSTEM_ANALISIS, user, 4000, "evaluacion")   # con 2500 la API paga lo cortaba
            doc["diagnostico"] = _diagnostico(data)
        except llm.Cancelada:
            raise
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

El pedido explícito del usuario tiene prioridad sobre las reglas editoriales actuales y sobre el diagnóstico.
Implementá cada parte del pedido modificando el contenido de las piezas: no alcanza con explicar el cambio
en el comentario. Si pide quitar, permitir o cambiar una restricción, reemplazá o eliminá las reglas que
la contradicen en todas las piezas afectadas. No conserves la prohibición vieja junto con la regla nueva.
La pieza "imagenes" controla la selección de fotos y las restricciones editoriales de portada (por ejemplo,
permitir personas); esos pedidos se resuelven allí, no en "formato" ni "seo". El selector de fotos lee esa pieza.
Las piezas describen reglas editoriales: no cambian código, credenciales ni servicios. La descarga de fotos,
su cantidad, la búsqueda sin repetir y los créditos requeridos por su licencia se controlan por código;
si un pedido requiere cambiar eso, explicá el límite concreto sin afirmar que lo implementaste.
Si se indican claves, cambiá solo esas piezas. Si ninguna puede resolver el pedido, explicá qué pieza hace falta.

Reescribí todas las piezas que hagan falta para resolverlo, y solo esas. Cambios mínimos y concretos: conservá lo que
funciona, el formato de cada pieza (títulos ##, listas) y las llaves como {extension}. En las piezas de
persona mantené el rol arriba y las secciones ## Tu tarea, ## Estructura (lista numerada) y ## Estilo. No
inventes datos de Alephee: lo que se puede afirmar está en el enfoque Alephee.
Cada pieza admite hasta 4000 caracteres (identidad: 600). No copies "Uso:" ni las etiquetas <pieza> al contenido.
No apiles reglas: un prompt con demasiadas reglas escribe peor. Si una regla nueva se superpone con otra,
fusionalas o reemplazala. Una pieza puede llegar como mucho al doble del largo de la aprobada (o 800
caracteres más); achicarla siempre está bien.

Respondé SOLO un JSON válido: en "contenido", escapá las comillas dobles (\\") y los saltos de línea (\\n).
{"comentario": "una oración sobre qué cambiaste",
 "cambios": [{"clave": "clave de la pieza", "explicacion": "qué cambiaste y por qué", "contenido": "la pieza completa nueva"}]}"""


def _limpiar(texto: str) -> str:
    """El contenido de una pieza tal como lo devolvió la IA, sin lo que copia del pedido aunque se le diga
    que no: la línea «Uso: ...» de arriba y las etiquetas <pieza>. El 20/11 la «Uso:» delante de «## Formato»
    hizo fallar la validación y se rechazó la propuesta entera."""
    texto = re.sub(r"</?pieza\b[^>]*>", "", str(texto or "").replace("\r\n", "\n")).strip()
    return re.sub(r"\AUso:[^\n]*\n+", "", texto).strip()


def _tope(antes: str, aprobada: str) -> int:
    """Largo máximo de una pieza de la copia. Se mide contra la aprobada (no contra la versión anterior de la
    copia): así no se infla mejora tras mejora, pero una pieza corta igual se puede cambiar. Achicar siempre
    vale: una pieza que ya se pasó puede bajar de a poco."""
    return max(int(len(aprobada) * CRECIMIENTO_MAX), len(aprobada) + CRECIMIENTO_MIN, len(antes))


def _validar(clave: str, despues: str, tope: int) -> dict:
    """La validación de la pieza y, además, que no se infle: apilar reglas mejora tras mejora bajaba las notas
    de 8 a 6 (las piezas pasaron de ~400-1000 a ~3900 caracteres)."""
    v = pe.validar(clave, despues)
    if len(despues) > tope:
        v["errores"].append(f"{_INFLADA}{len(despues)} caracteres y el máximo es {tope}. "
                            "Fusioná o reemplazá reglas en vez de agregarlas.")
    return v


_INFLADA = "Quedó de "   # comienzo del error de largo (mejorar() distingue ese error de los de formato)


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
    for intento in range(2):
        try:
            data = _pedir_json(_SYSTEM_MEJORA, user, 12000, "correccion")
        except llm.Cancelada:
            raise
        except Exception as e:
            raise ErrorPromptIA(f"La IA no pudo reescribir los prompts: {e}") from e
        cambios, comentario = _leer_propuesta(data, claves, docs, base)
        if cambios or intento:
            return cambios, comentario
        print("[PROMPTS IA] La IA no devolvió cambios en las piezas: reintentando el pedido...", flush=True)
        user += ("\n\n## Corregí tu respuesta anterior\nNo recibimos contenido diferente para ninguna pieza permitida. "
                 "Devolvé las piezas completas modificadas para implementar el pedido. Si ya se cumple o excede "
                 "estas piezas, explicá el motivo concreto.\nRespuesta anterior:\n"
                 + json.dumps(data, ensure_ascii=False)[:8000])


def _leer_propuesta(data, claves: list[str], docs: dict, base=None) -> tuple[list, str]:
    data = data if isinstance(data, dict) else {}
    cambios = []
    propuestas = data.get("cambios")
    for c in propuestas if isinstance(propuestas, list) else []:
        clave = c.get("clave") if isinstance(c, dict) else None
        if (not isinstance(clave, str) or clave not in pe.CLAVES or (claves and clave not in claves)
                or any(x["clave"] == clave for x in cambios) or not isinstance(c.get("contenido"), str)):
            continue
        despues = _limpiar(c.get("contenido"))
        antes = _texto_copia(clave, docs, base)
        if not despues or despues == antes.strip():
            continue
        tope = _tope(antes, pe._activo(clave, base)["contenido"])
        v = _validar(clave, despues, tope)
        cambios.append({"clave": clave, "titulo": pe._titulo(clave), "antes": antes, "despues": despues,
                        "explicacion": str(c.get("explicacion") or "").strip()[:600],
                        "errores": v["errores"], "avisos": v["avisos"], "tope": tope})
        if len(cambios) >= CAMBIOS_MAX:
            break
    return cambios, str(data.get("comentario") or "").strip()[:400]


_SYSTEM_REPARAR = """Sos especialista en prompts. Estas piezas en Markdown de un prompt no pasaron la validación.
Corregí cada una para que cumpla lo que dicen los errores, sin perder el cambio que se quiso hacer. En las
piezas de persona: el rol arriba y las secciones ## Tu tarea, ## Estructura (lista numerada) y ## Estilo.

Respondé SOLO un JSON: {"cambios": [{"clave": "...", "contenido": "la pieza completa corregida"}]}"""


def _reparar(cambios: list[dict], pedido: str) -> None:
    """A los cambios que no pasaron la validación, se los devuelve a la IA con los errores (una vez)."""
    rotos = [c for c in cambios if c["errores"]]
    if not rotos:
        return
    print(f"[PROMPTS IA] Corrigiendo {len(rotos)} pieza(s) que no pasaron la validación...", flush=True)
    user = f"## Pedido que hay que conservar\n{pedido}\n\n" + "\n\n".join(
                       f"<pieza clave=\"{c['clave']}\">\n## Errores\n" + "\n".join(f"- {e}" for e in c["errores"])
                       + f"\n## Texto\n{c['despues']}\n</pieza>" for c in rotos)
    try:
        data = _pedir_json(_SYSTEM_REPARAR, user, 6000, "correccion")
    except llm.Cancelada:
        raise
    except Exception as e:
        print(f"[PROMPTS IA] [AVISO] No se pudieron corregir: {e}", flush=True)
        return
    propuestas = data.get("cambios") if isinstance(data, dict) else None
    nuevos = {c["clave"]: _limpiar(c["contenido"])
              for c in (propuestas if isinstance(propuestas, list) else [])
              if isinstance(c, dict) and isinstance(c.get("clave"), str) and isinstance(c.get("contenido"), str)}
    for c in rotos:
        texto = nuevos.get(c["clave"])
        if texto:
            v = _validar(c["clave"], texto, c["tope"])
            if not v["errores"]:
                c.update(despues=texto, errores=[], avisos=v["avisos"])


def _aplicar(cambios: list[dict], origen: str, pedido: str, base=None) -> list[str]:
    """Pasa a la copia los cambios sin errores. Cada uno guarda el texto anterior (para deshacer)."""
    b, ahora, aplicadas = _base(base), _ahora(), []
    for c in cambios:
        if c["despues"].strip() == c["antes"].strip() and not c["errores"]:
            c["errores"].append("La reparación devolvió el texto anterior: no implementó el cambio.")
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


def validar_pedido(pedido=None, claves=None) -> tuple[str, list[str]]:
    """No recorta pedidos ni convierte una selección inválida en permiso para editar todo."""
    if pedido is not None and not isinstance(pedido, str):
        raise ErrorPromptIA("El pedido debe ser un texto.")
    pedido = (pedido or "").strip()
    if pedido and len(pedido) < 8:
        raise ErrorPromptIA("Contá qué querés cambiar en los prompts.")
    if len(pedido) > PEDIDO_MAX:
        raise ErrorPromptIA(f"El pedido supera los {PEDIDO_MAX} caracteres: dividilo en pedidos más cortos.")
    claves = [] if claves is None else claves
    if not isinstance(claves, list) or any(not isinstance(c, str) or c not in pe.CLAVES for c in claves):
        raise ErrorPromptIA("Elegí piezas válidas del prompt.")
    return pedido, list(dict.fromkeys(claves))


def _solo_imagenes(pedido: str) -> bool:
    t = "".join(c for c in unicodedata.normalize("NFD", pedido.lower()) if not unicodedata.combining(c))
    imagen = re.search(r"\b(imagen\w*|imgen\w*|foto\w*|cara\w*|rostro\w*)\b", t)
    redaccion = re.search(r"\b(seo|voseo|titulos?|subtitulos?|parrafos?|ortografia|redaccion|cta|tono|escritura|redactar|escribir)\b", t)
    return bool(imagen and not redaccion)


def mejorar(pedido: str | None = None, claves=None, origen: str = "manual", base=None) -> dict:
    """Proponer, comparar y recién entonces guardar una copia completa validada."""
    b = _base(base)
    pedido, claves = validar_pedido(pedido, claves)
    if not llm.disponible():
        raise ErrorPromptIA("La IA no está disponible para mejorar los prompts.")
    if pedido and _solo_imagenes(pedido):
        if claves and claves != ["imagenes"]:
            raise ErrorPromptIA("Ese pedido corresponde a Imágenes. Elegí esa pieza o dejá que la IA la elija.")
        claves = ["imagenes"]
    referencia = textos("actuales", base)
    validada = _validada(base)
    # Una copia antigua sin pruebas no debe contaminar nuevas propuestas.
    inicial = validada["textos"] if validada and (pedido or juego(base) == "ia") else referencia
    copia_inicial = prueba.huella(textos("ia", base))
    perfil = prueba.modelo()
    docs = {k: {"contenido": v} for k, v in inicial.items()}
    mejora = {"fecha": _ahora(), "origen": "pedido" if pedido else origen, "pedido": pedido, "cambios": []}
    diagnostico = None
    if not pedido:
        print("[PROMPTS IA] Analizando errores de las notas de la versión vigente...", flush=True)
        analisis = analizar(base=base)
        diagnostico = analisis.get("diagnostico")
        mejora["analisis_id"] = analisis["id"]
        problemas = (diagnostico or {}).get("problemas", [])
        permitidas = [p["pieza"] for p in problemas if p.get("evidencia") and p.get("pieza")
                      and p["pieza"] != "imagenes"][:2]
        claves = [c for c in permitidas if not claves or c in claves]
        if not claves:
            mejora["error"] = analisis.get("error") or "No hay errores con evidencia suficiente para cambiar los prompts."
        else:
            mejora["resumen"] = diagnostico["resumen"]
    if not mejora.get("error"):
        pedido_efectivo = pedido or _pedido_del_diagnostico(diagnostico)
        print("[PROMPTS IA] Preparando una propuesta; todavía no se activa...", flush=True)
        try:
            cambios, comentario = _proponer(pedido_efectivo, claves, docs, diagnostico, base)
            _reparar(cambios, pedido_efectivo)
        except ErrorPromptIA as e:
            cambios, comentario, mejora["error"] = [], "", str(e)
        mejora.update(cambios=cambios, comentario=comentario)
        for c in cambios:
            c["aplicado"] = False
            if c["despues"].strip() == c["antes"].strip():
                c["errores"].append("La reparación devolvió el texto anterior.")
        # Sin pedido, una pieza que solo se pasó de largo queda afuera y las demás siguen: el 20/11 la IA
        # inflaba «Formato» aunque se le pidiera achicarla, y eso tumbaba la propuesta entera una y otra vez.
        # Con pedido no: el usuario pidió todo junto (no se aplica un subconjunto).
        infladas = [] if pedido else [c for c in cambios
                                      if c["errores"] and all(e.startswith(_INFLADA) for e in c["errores"])]
        evaluables = [c for c in cambios if c not in infladas]
        if infladas:
            mejora["avisos"] = [f"{c['titulo']} quedó afuera: {c['errores'][0]}" for c in infladas]
            print(f"[PROMPTS IA] [AVISO] {' '.join(mejora['avisos'])}", flush=True)
        if not cambios:
            mejora["error"] = mejora.get("error") or "La IA no propuso cambios. " + comentario
        elif not evaluables or any(c["errores"] for c in evaluables):
            detalle = " ".join(f"{c['titulo']}: {c['errores'][0]}" for c in cambios if c["errores"])
            mejora["error"] = f"La propuesta está incompleta o es inválida. No se aplicó ninguna pieza. {detalle}"
        else:
            candidata = inicial | {c["clave"]: c["despues"] for c in evaluables}
            evaluacion = prueba.comparar(inicial, candidata, referencia, b, automatico=not bool(pedido))
            mejora["evaluacion"] = evaluacion
            llm.verificar_cancelacion()
            if evaluacion["estado"] != "aprobada":
                mejora["error"] = evaluacion["motivo"] + " Se conservan los prompts anteriores."
            elif (prueba.huella(textos("ia", base)) != copia_inicial or textos("actuales", base) != referencia
                  or prueba.modelo() != perfil):
                mejora["error"] = "Los prompts o el modelo cambiaron durante la prueba. Repetí el pedido."
            else:
                # Restaurar piezas heredadas sin validar, sin perder su historial.
                for clave, anterior in textos("ia", base).items():
                    if clave not in {c["clave"] for c in evaluables} and anterior != candidata[clave]:
                        cambios.append({"clave": clave, "titulo": pe._titulo(clave), "antes": anterior,
                                        "despues": candidata[clave], "errores": [], "avisos": [],
                                        "explicacion": "Se recupera la base aprobada: esta pieza no tenía una prueba vigente."})
                _aplicar(cambios, mejora["origen"], pedido_efectivo, base)
                # Publicar el conjunto completo en un documento. El lector verifica su huella.
                b.prompts_ia_estado.replace_one({"_id": "validada"}, {
                    "_id": "validada", "textos": candidata, "huella": prueba.huella(candidata),
                    "base": prueba.huella(referencia), "modelo": perfil, "fecha": _ahora(),
                    "evaluacion": evaluacion,
                    "evaluacion_redaccion": (evaluacion if evaluacion.get("tipo") == "redaccion"
                                             else (validada or {}).get("evaluacion_redaccion")),
                }, upsert=True)
                pe.invalidar_cache()
    if mejora.get("error"):
        print(f"[PROMPTS IA] [AVISO] {mejora['error']}", flush=True)
    r = b["prompts_ia_mejoras"].insert_one(dict(mejora))
    return _publico(mejora | {"_id": r.inserted_id})


def vigilar_calidad(base=None) -> dict | None:
    """Retirar una versión si sus primeras notas reales muestran una caída sostenida."""
    if _config().get("usar") != "ia":
        return None
    b = _base(base)
    d = _validada(base)
    if not d or not d.get("evaluacion_redaccion"):
        return None
    notas = list(b.notas_fase2.find({"prompts_huella": d["huella"]}).sort("_id", -1).limit(5))
    valores = [(n.get("critica") or {}).get("puntaje") for n in notas]
    valores = [v for v in valores if prueba._puntaje(v, 10)]
    if len(valores) < 3:
        return None
    media = sum(valores) / len(valores)
    if media >= max(8, d["evaluacion_redaccion"].get("antes", 8) - 0.5):
        return None
    motivo = f"Se volvió a los prompts actuales: las últimas {len(valores)} notas promedian {media:.1f}/10."
    b.prompts_ia_estado.update_one({"_id": "validada", "huella": d["huella"]},
                                  {"$set": {"retirada": True, "motivo": motivo}})
    _guardar_config(usar="actuales")
    pe.invalidar_cache()
    doc = {"fecha": _ahora(), "origen": "proteccion", "error": motivo, "cambios": [],
           "evaluacion": {"estado": "retirada", "motivo": motivo, "despues": round(media, 2)}}
    r = b.prompts_ia_mejoras.insert_one(dict(doc))
    return _publico(doc | {"_id": r.inserted_id})


def mejora_automatica(base=None) -> dict | None:
    """Si la mejora automática está prendida y hay AUTO_CADA notas nuevas desde la última, mejora la copia."""
    from afterdrive.ia import llm

    retirada = vigilar_calidad(base)
    if retirada:
        return retirada
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
    print(f"[PROMPTS IA RESULTADO] {r['id']}", flush=True)
    aplicadas = [c["titulo"] for c in r.get("cambios", []) if c.get("aplicado")]
    if aplicadas:
        print(f"[OK] Copia de la IA mejorada: {', '.join(aplicadas)}.", flush=True)
        return 1 if r.get("error") else 0
    print(f"[ERROR] {r.get('error') or 'No se aplicó ningún cambio.'}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
