"""
juez.py — Un editor crítico con IA que decide si una Nota pasa sola y le sugiere una calificación.

Interfaz:
    juzgar(nota, noticias_texto, reglas=()) -> dict    una llamada al modelo de evaluación
    filtro_duro(doc, umbral=None) -> [motivo]          sin IA: lo que la frena sí o sí
    decidir(doc, confianza_min=CONFIANZA_MIN) -> dict  {"pasa", "motivos", ...}

La sugerencia (estrellas, etiquetas, comentario) se muestra precargada al
revisar la nota, pero no cuenta para el aprendizaje hasta que una persona la
guarda: si contara sola, la IA se enseñaría a sí misma.

Ante la duda no pasa: si el modelo no responde o el JSON viene roto, el juicio
queda con error y la nota espera a una persona.

Checklist de Alephee: el juez también revisa cómo aparece Alephee, con el bloque
"Enfoque Alephee" activo (redaccion.py) como la única verdad sobre la empresa.
Cada punto es sí, no o no aplica (por ejemplo, si la nota no nombra a Alephee);
un "no" frena la aprobación automática y queda como motivo.
"""

from __future__ import annotations

import math

from afterdrive.calibracion import ETIQUETAS
from afterdrive.ia import llm
from afterdrive.ia.lm_studio import _extraer_json

# Checklist específica de Alephee: código -> qué se pregunta (lo que el juez responde).
CHECKLIST_ALEPHEE = {
    "mencion_con_motivo": "Si nombra a Alephee, lo hace donde resuelve un problema que la nota planteó, no de relleno.",
    "nada_inventado": "No le atribuye a Alephee funciones, precios, cifras, clientes ni casos que no estén en el "
                      "enfoque Alephee, las noticias o el pedido.",
    "beneficio_concreto": "Lo que aporta Alephee se dice en concreto (catálogo, marketplaces, stock, fitment), "
                          "no con frases generales.",
    "informa_primero": "El cuerpo informa: Alephee no es el tema salvo que el pedido lo diga, y no hay tono "
                       "publicitario (superlativos, \"la mejor solución\").",
    "cta_unico": "Hay una sola llamada a la acción, al final, con un link a Alephee o al puntapié.",
}

CONFIANZA_MIN = 0.8
UMBRAL_DEFAULT = 7          # puntaje del evaluador (0 a 9) si todavía no hay umbral calibrado
NOTICIAS_MAX = 12000        # chars de noticias que entran al prompt

_SYSTEM = """\
Sos el editor jefe del blog B2B de AfterDrive by Alephee (autopartes y postventa automotriz).
Sos exigente: preferís frenar una nota dudosa antes que publicar algo flojo. Juzgás una nota
que escribió otra IA, con las noticias que la alimentaron.

## Qué mirás
- Datos: cada cifra, empresa o caso tiene que estar en las noticias. Uno inventado = no pasa.
- Ángulo: un hecho concreto y qué implica para un distribuidor o repuestero, no un panorama genérico.
- Utilidad: deja algo accionable (precios, stock, canales, catálogo).
- Escritura: suena a periodista del sector, no a IA; sin muletillas ni relleno; sin repetir.
- Terminología técnica correcta.

## Respuesta
Solo un JSON, sin texto alrededor:
{"pasa": bool, "confianza": número 0 a 1 (qué tan seguro estás de tu decisión),
 "calificacion": entero 1 a 5 (la que le pondría el equipo),
 "etiquetas": [códigos de la lista de abajo que apliquen],
 "comentario": "una o dos oraciones concretas: lo mejor y lo que hay que arreglar",
 "motivos": ["por qué no pasa", ...] (vacío si pasa),
 "alephee": {"código de la checklist": true, false o null si no aplica}}
"""


def _checklist_alephee() -> str:
    from afterdrive.ia import redaccion

    puntos = "\n".join(f"- {k}: {v}" for k, v in CHECKLIST_ALEPHEE.items())
    return ("## Checklist de Alephee (respondé cada punto en \"alephee\": true, false o null si no aplica)\n"
            f"{puntos}\n\nLo único que se puede afirmar de Alephee es lo que dice este bloque:\n"
            f"{redaccion.texto('enfoque_alephee')}")


def _alephee(valor) -> dict:
    """{código: True | False | None} con los puntos de la checklist; lo que no vino, None (no se sabe)."""
    valor = valor if isinstance(valor, dict) else {}
    return {k: valor[k] if isinstance(valor.get(k), bool) else None for k in CHECKLIST_ALEPHEE}


def _lista_etiquetas() -> str:
    return "\n".join(f"- {k}: {v[0]}" for k, v in ETIQUETAS.items())


def _numero(valor, minimo, maximo, default):
    """El valor acotado a [minimo, maximo]; default si no es un número usable.

    Un bool o un NaN no cuentan como número: antes `true` o `NaN` en la
    confianza daban 1.0 y la nota podía aprobarse sola con un JSON roto.
    """
    if isinstance(valor, bool):
        return default
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numero):
        return default
    if isinstance(default, int):
        numero = round(numero)
    return type(default)(max(minimo, min(maximo, numero)))


def _lista(valor) -> list:
    """Una lista aunque el modelo mande un solo texto (si no, se partiría letra por letra)."""
    if isinstance(valor, str):
        return [valor] if valor.strip() else []
    return list(valor) if isinstance(valor, list) else []


def juzgar(nota: str, noticias_texto: str, reglas=()) -> dict:
    """Juicio del editor crítico. Siempre devuelve un dict; con "error" si no se pudo juzgar."""
    if not llm.disponible():
        return {"error": "Proveedor de IA no disponible para juzgar."}
    user = f"## Etiquetas posibles\n{_lista_etiquetas()}\n\n"
    if reglas:
        user += "## Lo que el equipo viene corrigiendo (respetalo al juzgar)\n" + \
                "\n".join(f"- {r}" for r in reglas) + "\n\n"
    user += _checklist_alephee() + "\n\n"
    user += f"## Noticias de contexto\n{(noticias_texto or '')[:NOTICIAS_MAX]}\n\n## Nota a juzgar\n{nota}"
    try:
        data = _extraer_json(llm.completar(_SYSTEM, user, temperature=0.1, max_tokens=1000, tarea="evaluacion"))
    except Exception as e:
        return {"error": f"No se pudo juzgar la nota: {e}"}
    if not isinstance(data.get("pasa"), bool):
        return {"error": "El juez no dijo si la nota pasa."}
    return {
        "pasa": data["pasa"],
        "confianza": _numero(data.get("confianza"), 0.0, 1.0, 0.0),
        "calificacion": _numero(data.get("calificacion"), 1, 5, 3),
        "etiquetas": [e for e in _lista(data.get("etiquetas")) if isinstance(e, str) and e in ETIQUETAS],
        "comentario": str(data.get("comentario") or "")[:300],
        "motivos": [str(m)[:200] for m in _lista(data.get("motivos")) if str(m).strip()][:5],
        "alephee": _alephee(data.get("alephee")),
        "modelo": "evaluacion",
    }


def filtro_duro(doc: dict, umbral: int | None = None) -> list[str]:
    """Motivos objetivos por los que la nota no puede aprobarse sola. Vacío = sigue al juez."""
    motivos = []
    sin_respaldo = (doc.get("verificacion") or {}).get("sin_respaldo") or []
    if sin_respaldo:
        motivos.append(f"datos sin respaldo en las noticias: {', '.join(sin_respaldo[:3])}")
    calidad = doc.get("calidad") or {}
    if calidad.get("fallas_criticas"):
        motivos.append(f"el evaluador marcó fallas críticas: {', '.join(calidad['fallas_criticas'])}")
    graves = [h.get("detalle", h.get("codigo", "")) for h in doc.get("estilo") or [] if h.get("grave")]
    if graves:
        motivos.append(f"problemas graves de estilo o SEO: {graves[0]}")
    if doc.get("parecida_a"):
        motivos.append("se parece a una nota reciente")
    if doc.get("empresas_prohibidas"):
        motivos.append(f"nombra empresas que no se pueden mencionar: {', '.join(doc['empresas_prohibidas'][:3])}")
    if not doc.get("imagen"):
        motivos.append("no tiene imagen destacada")
    minimo = umbral if umbral is not None else UMBRAL_DEFAULT
    if calidad.get("puntaje") is None or calidad["puntaje"] < minimo:
        motivos.append(f"puntaje del evaluador {calidad.get('puntaje')}/9, por debajo de {minimo}")
    return motivos


def fallas_alephee(juicio: dict | None) -> list[str]:
    """Los puntos de la checklist de Alephee que el juez marcó en falso, como motivos."""
    checklist = (juicio or {}).get("alephee") or {}
    return [f"checklist de Alephee: {CHECKLIST_ALEPHEE[k]}" for k in CHECKLIST_ALEPHEE if checklist.get(k) is False]


def decidir(doc: dict, confianza_min: float = CONFIANZA_MIN) -> dict:
    """Junta el filtro duro y el juicio guardado en la nota. Solo pasa si los dos dicen que sí."""
    umbral = (doc.get("calibracion_usada") or {}).get("umbral")
    motivos = filtro_duro(doc, umbral)
    juicio = doc.get("juicio") or {}
    if juicio.get("error"):
        motivos.append(juicio["error"])
    elif not juicio:
        motivos.append("la nota no tiene juicio de la IA")
    elif not juicio.get("pasa"):
        motivos += juicio.get("motivos") or ["el juez dijo que no pasa"]
    elif juicio.get("confianza", 0) < confianza_min:
        motivos.append(f"el juez no está seguro (confianza {juicio['confianza']:.2f} < {confianza_min})")
    motivos += fallas_alephee(juicio)
    return {"pasa": not motivos, "motivos": motivos, "umbral": umbral if umbral is not None else UMBRAL_DEFAULT,
            "confianza_min": confianza_min}
