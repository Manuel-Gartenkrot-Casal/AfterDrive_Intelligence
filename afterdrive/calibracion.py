"""
calibracion.py — Lo que la generación aprende de las personas que revisan las notas.

Interfaz:
    calificar(coleccion, item_id, puntaje, etiquetas=(), comentario="", base=None) -> dict | None
    contexto(persona="", base=None) -> Calibracion     lo que entra en el prompt de la próxima nota
    lecciones_de_ediciones(limite=3, base=None) -> list[str]
    umbral_evaluador(pares) -> (umbral, coincidencia)
    resumen(base=None) -> dict                          para el panel del dashboard
    ETIQUETAS

Cuatro señales humanas, de más fuerte a más débil:

1. Calificación (1 a 5 estrellas) con etiquetas y un comentario opcional.
   - Una etiqueta negativa que se repite (UMBRAL_ETIQUETA veces en las últimas
     CALIFICACIONES_RECIENTES notas calificadas) activa su regla correctiva
     fija en el prompt. Así una queja puntual no cambia nada y una que se
     repite sí.
   - Los comentarios de las notas mal calificadas (1 o 2) entran como
     correcciones; los de las bien calificadas (4 o 5), como aciertos.
   - Las notas propias con 4 o 5 pasan a ser referencias de estilo, junto a
     las del blog (primero las de la misma persona).
   - El evaluador automático se calibra: con MIN_PARES notas calificadas se
     busca el puntaje automático mínimo que mejor separa lo que el equipo
     aprobaría (3 o más) de lo que no. Una nota que no llega a ese umbral se
     reescribe una vez.
2. Motivo de rechazo (ya existía: historial.motivos_recientes).
3. Ediciones: la primera edición guarda el texto generado (historial.editar); en la
   próxima generación, el modelo de evaluación resume qué corrigió la persona
   en una o dos reglas generales, que quedan guardadas en la nota.
4. Las calificaciones por persona, proveedor y modelo se muestran en el
   panel, para decidir con datos (no se cambian solas).

Todo se lee de Mongo en cada generación: no hay estado en memoria.
"""

from __future__ import annotations

import datetime
import difflib
import re
from dataclasses import asdict, dataclass, field

from afterdrive import db as _db

COLECCION = "notas_fase2"
COLECCIONES = ("notas_fase2", "articulos_generados")
CALIFICACIONES_RECIENTES = 20
UMBRAL_ETIQUETA = 2
MIN_PARES = 8
DIAS = 90
COMENTARIO_MAX = 300
MAX_REGLAS = 8

# clave -> (texto para el usuario, es_negativa, regla que activa)
ETIQUETAS = {
    "datos_dudosos": ("Datos dudosos o inventados", True,
                      "Cada cifra, empresa y caso tiene que estar en las noticias de contexto. Ante la duda, "
                      "escribí la idea sin el dato."),
    "generica": ("Muy genérica, sin ángulo", True,
                 "Elegí un ángulo concreto y sostenelo: un hecho puntual de las noticias y qué implica, "
                 "no un panorama general del sector."),
    "suena_ia": ("Suena a IA", True,
                 "Escribí como un periodista del sector: sin muletillas (\"en el dinámico mundo\", \"cabe "
                 "destacar\"), sin enumeraciones de tres adjetivos, con oraciones concretas."),
    "muy_larga": ("Muy larga o repetitiva", True,
                  "Sé más breve: cada párrafo dice algo nuevo. Cortá las introducciones y los cierres que "
                  "repiten lo ya dicho."),
    "tono": ("Tono equivocado", True,
             "Tono B2B profesional: ni publicitario ni académico. Hablale a un dueño de distribuidora."),
    "poco_util": ("Poco útil para el negocio", True,
                  "Cada sección tiene que dejar algo accionable para un distribuidor o repuestero: precios, "
                  "stock, canales o catálogo."),
    "errores_tecnicos": ("Errores técnicos del sector", True,
                         "Revisá la terminología técnica: neumático no es llanta, pastillas no son balatas, "
                         "motor no es transmisión."),
    "buen_angulo": ("Buen ángulo", False, ""),
    "bien_escrita": ("Bien escrita", False, ""),
    "datos_utiles": ("Datos útiles", False, ""),
    "lista": ("Lista para publicar", False, ""),
}


class ErrorCalibracion(ValueError):
    """Parámetro inválido; el mensaje es apto para mostrarle al usuario."""


@dataclass
class Calibracion:
    reglas: list[str] = field(default_factory=list)            # correcciones a respetar
    aciertos: list[str] = field(default_factory=list)          # lo que el equipo valoró
    ejemplos_propios: list[dict] = field(default_factory=list)  # {"id", "titulo", "cuerpo", "puntaje"}
    umbral: int | None = None                                  # puntaje automático mínimo (0 a 9)

    def como_dict(self) -> dict:
        d = asdict(self)
        d["ejemplos_propios"] = [{"id": e["id"], "titulo": e["titulo"], "puntaje": e["puntaje"]}
                                 for e in self.ejemplos_propios]
        return d


def _base(base):
    return base if base is not None else _db.db


def _ahora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _oid(item_id: str):
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        return ObjectId(item_id)
    except (InvalidId, TypeError) as e:
        raise ErrorCalibracion("Identificador inválido.") from e


def _titulo(contenido: str) -> str:
    for ln in (contenido or "").splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


# ── Escritura ─────────────────────────────────────────────────────────────────


def calificar(coleccion: str, item_id: str, puntaje, etiquetas=(), comentario: str = "", base=None) -> dict | None:
    """Guarda la calificación de una Nota. Devuelve la calificación guardada, o None si la nota no existe."""
    if coleccion not in COLECCIONES:
        raise ErrorCalibracion("Solo se califican las notas generadas.")
    if isinstance(puntaje, bool) or not isinstance(puntaje, int) or not 1 <= puntaje <= 5:
        raise ErrorCalibracion("La calificación va de 1 a 5 estrellas.")
    if not isinstance(etiquetas, list | tuple) or any(e not in ETIQUETAS for e in etiquetas):
        raise ErrorCalibracion("Etiqueta desconocida.")
    comentario = " ".join(comentario.split())[:COMENTARIO_MAX] if isinstance(comentario, str) else ""
    calificacion = {
        "puntaje": puntaje,
        "etiquetas": list(dict.fromkeys(etiquetas)),
        "comentario": comentario,
        "calificado_en": _ahora().isoformat(),
    }
    r = _base(base)[coleccion].update_one({"_id": _oid(item_id)}, {"$set": {"calificacion": calificacion}})
    return calificacion if r.matched_count else None


# ── Lectura ───────────────────────────────────────────────────────────────────


def _calificadas(base, limite: int = CALIFICACIONES_RECIENTES, dias: int = DIAS) -> list[dict]:
    desde = (_ahora() - datetime.timedelta(days=dias)).isoformat()
    return list(_base(base)[COLECCION].find(
        {"calificacion.puntaje": {"$exists": True}, "calificacion.calificado_en": {"$gte": desde}},
        {"embedding": 0},
    ).sort("calificacion.calificado_en", -1).limit(limite))


def _reglas_por_etiquetas(calificadas: list[dict]) -> list[tuple[str, int]]:
    cuenta: dict[str, int] = {}
    for d in calificadas:
        for e in d["calificacion"].get("etiquetas") or []:
            cuenta[e] = cuenta.get(e, 0) + 1
    activas = [(e, n) for e, n in cuenta.items() if ETIQUETAS.get(e, ("", False))[1] and n >= UMBRAL_ETIQUETA]
    return sorted(activas, key=lambda t: -t[1])


def umbral_evaluador(pares: list[tuple[int, int]]) -> tuple[int | None, float | None]:
    """(umbral, coincidencia) a partir de pares (puntaje automático 0-9, calificación 1-5).

    El umbral es el puntaje automático mínimo que mejor predice que el equipo
    calificaría la nota con 3 o más. La coincidencia es la proporción de notas
    en las que el umbral y la persona están de acuerdo. Con menos de MIN_PARES
    pares, o si todas las notas tienen la misma opinión humana, no hay umbral.
    """
    if len(pares) < MIN_PARES:
        return None, None
    buenas = [h >= 3 for _, h in pares]
    if all(buenas) or not any(buenas):
        return None, None
    mejor, mejor_acierto = None, -1.0
    for s in range(0, 10):
        acierto = sum((a >= s) == b for (a, _), b in zip(pares, buenas, strict=True)) / len(pares)
        if acierto > mejor_acierto:
            mejor, mejor_acierto = s, acierto
    # Umbral 0 = aceptar todo: no aporta nada.
    return (mejor if mejor else None), round(mejor_acierto, 2)


def _pares(calificadas: list[dict]) -> list[tuple[int, int]]:
    return [((d.get("calidad") or {}).get("puntaje"), d["calificacion"]["puntaje"]) for d in calificadas
            if isinstance((d.get("calidad") or {}).get("puntaje"), int)]


def _cuerpo_ejemplo(contenido: str) -> str:
    """Sin título, sin fuentes y sin meta: la referencia es el cuerpo."""
    lineas = [ln for ln in (contenido or "").splitlines() if not ln.startswith("# ")]
    texto = "\n".join(lineas)
    texto = re.split(r"^## (Fuentes|Fontes|Sources)\s*$", texto, flags=re.MULTILINE)[0]
    return texto.strip()


def contexto(persona: str = "", base=None, calcular_lecciones: bool = True) -> Calibracion:
    """Lo que la próxima nota tiene que tener en cuenta. Nunca lanza: sin Mongo, calibración vacía.

    calcular_lecciones=False solo lee las lecciones de ediciones ya guardadas
    (el panel del dashboard no debe llamar al modelo).
    """
    try:
        return _contexto(persona, base, calcular_lecciones)
    except Exception as e:
        print(f"  [AVISO] No se pudo leer la calibración: {e}", flush=True)
        return Calibracion()


def _contexto(persona: str, base, calcular_lecciones: bool) -> Calibracion:
    from afterdrive.historial import motivos_recientes

    cal = Calibracion()
    calificadas = _calificadas(base)
    reglas = [ETIQUETAS[e][2] for e, _ in _reglas_por_etiquetas(calificadas)]
    reglas += [d["calificacion"]["comentario"] for d in calificadas
               if d["calificacion"]["puntaje"] <= 2 and d["calificacion"].get("comentario")][:3]
    reglas += motivos_recientes(base=base)
    reglas += lecciones_de_ediciones(base=base, limite=3 if calcular_lecciones else 0)
    vistas = set()
    for r in reglas:
        if r and r.lower() not in vistas:
            vistas.add(r.lower())
            cal.reglas.append(r)
    cal.reglas = cal.reglas[:MAX_REGLAS]
    cal.aciertos = [d["calificacion"]["comentario"] for d in calificadas
                    if d["calificacion"]["puntaje"] >= 4 and d["calificacion"].get("comentario")][:3]

    buenas = [d for d in calificadas if d["calificacion"]["puntaje"] >= 4 and d.get("contenido")]
    buenas.sort(key=lambda d: (d.get("persona") != persona, -d["calificacion"]["puntaje"]))
    cal.ejemplos_propios = [{"id": str(d["_id"]), "titulo": _titulo(d["contenido"]),
                             "cuerpo": _cuerpo_ejemplo(d["contenido"]), "puntaje": d["calificacion"]["puntaje"]}
                            for d in buenas[:2]]
    cal.umbral, _ = umbral_evaluador(_pares(_calificadas(base, limite=200)))
    return cal


# ── Ediciones ─────────────────────────────────────────────────────────────────

_SYSTEM_EDICION = """\
Un editor corrigió una nota B2B escrita por una IA. Te paso lo que sacó y lo que agregó o reescribió.
Deducí hasta 2 reglas generales de redacción que expliquen esas correcciones y sirvan para notas
futuras sobre otros temas. No menciones el tema puntual de esta nota.
Si los cambios son mínimos o solo de datos puntuales, no hay regla.
Respondé solo con este JSON: {"reglas": ["..."]}"""


def _oraciones(texto: str) -> list[str]:
    return [o.strip() for o in re.split(r"(?<=[.!?])\s+|\n+", texto or "") if len(o.strip()) > 15]


def diferencias(original: str, editado: str, max_chars: int = 1500) -> tuple[str, str]:
    """(lo que se sacó, lo que se agregó), por oraciones."""
    a, b = _oraciones(original), _oraciones(editado)
    sacado, agregado = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            sacado += a[i1:i2]
        if op in ("insert", "replace"):
            agregado += b[j1:j2]
    return "\n".join(sacado)[:max_chars], "\n".join(agregado)[:max_chars]


def _leccion(original: str, editado: str) -> list[str]:
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    sacado, agregado = diferencias(original, editado)
    if len(sacado) + len(agregado) < 40:
        return []
    user = f"## Lo que sacó\n{sacado or '(nada)'}\n\n## Lo que agregó o reescribió\n{agregado or '(nada)'}"
    data = _extraer_json(llm.completar(_SYSTEM_EDICION, user, temperature=0.1, max_tokens=500, tarea="evaluacion"))
    return [" ".join(str(r).split())[:240] for r in (data.get("reglas") or []) if str(r).strip()][:2]


def lecciones_de_ediciones(limite: int = 3, dias: int = 60, base=None) -> list[str]:
    """Reglas aprendidas de las últimas notas editadas. Calcula (y guarda) las que falten.

    Como mucho `limite` llamadas al modelo por generación; si el modelo falla,
    esa edición se reintenta la próxima vez.
    """
    col = _base(base)[COLECCION]
    desde = (_ahora() - datetime.timedelta(days=dias)).isoformat()
    docs = list(col.find(
        {"contenido_original": {"$exists": True}, "editado_en": {"$gte": desde}},
        {"contenido": 1, "contenido_original": 1, "editado_en": 1, "leccion_edicion": 1},
    ).sort("editado_en", -1).limit(5))
    reglas, llamadas = [], 0
    for d in docs:
        leccion = d.get("leccion_edicion") or {}
        if leccion.get("calculada_en", "") < d["editado_en"]:
            if llamadas >= limite:
                continue
            llamadas += 1
            try:
                leccion = {"reglas": _leccion(d["contenido_original"], d["contenido"]),
                           "calculada_en": _ahora().isoformat()}
            except Exception as e:
                print(f"  [AVISO] No se pudo resumir una edición: {e}", flush=True)
                continue
            col.update_one({"_id": d["_id"]}, {"$set": {"leccion_edicion": leccion}})
        reglas += leccion.get("reglas") or []
    return reglas


# ── Panel ─────────────────────────────────────────────────────────────────────


def _promedios(docs: list[dict], clave) -> list[dict]:
    grupos: dict[str, list[int]] = {}
    for d in docs:
        grupos.setdefault(clave(d) or "—", []).append(d["calificacion"]["puntaje"])
    return sorted(({"nombre": k, "notas": len(v), "promedio": round(sum(v) / len(v), 2)} for k, v in grupos.items()),
                  key=lambda g: -g["notas"])


def resumen(base=None) -> dict:
    """Estado de la calibración para el dashboard."""
    todas = _calificadas(base, limite=500, dias=3650)
    recientes = todas[:CALIFICACIONES_RECIENTES]
    pares = _pares(todas[:200])
    umbral, coincidencia = umbral_evaluador(pares)
    sin_calificar = _base(base)[COLECCION].count_documents({"calificacion": {"$exists": False}})
    cal = contexto(base=base, calcular_lecciones=False)
    return {
        "calificadas": len(todas),
        "sin_calificar": sin_calificar,
        "promedio": round(sum(d["calificacion"]["puntaje"] for d in todas) / len(todas), 2) if todas else None,
        "distribucion": {str(i): sum(1 for d in todas if d["calificacion"]["puntaje"] == i) for i in range(1, 6)},
        "por_persona": _promedios(todas, lambda d: d.get("persona")),
        "por_proveedor": _promedios(todas, lambda d: d.get("proveedor")),
        "etiquetas": [{"clave": e, "nombre": ETIQUETAS[e][0], "veces": n, "activa": True}
                      for e, n in _reglas_por_etiquetas(recientes)],
        "evaluador": {"pares": len(pares), "minimo": MIN_PARES, "umbral": umbral, "coincidencia": coincidencia},
        "reglas": cal.reglas,
        "aciertos": cal.aciertos,
        "ejemplos_propios": [{"id": e["id"], "titulo": e["titulo"], "puntaje": e["puntaje"]} for e in cal.ejemplos_propios],
        "catalogo_etiquetas": [{"clave": k, "nombre": v[0], "negativa": v[1]} for k, v in ETIQUETAS.items()],
    }
