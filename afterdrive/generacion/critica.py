"""
critica.py — Una IA corrige cómo está escrita una Nota: gramática, ortografía, redacción, tono y estructura.

Interfaz:
    criticar(nota, persona="comercial", regiones=None, idioma=None) -> dict   una llamada al modelo de evaluación
    criticar_guardada(coleccion, item_id, base=None) -> dict | None
                                                    critica una nota guardada y deja el resultado en ella
    traducir_guardada(coleccion, item_id, idioma, base=None) -> dict | None
                                                    el resumen y los problemas en el idioma del dashboard

La crítica se escribe en español aunque la nota esté en otro idioma (las notas
nuevas salen en portugués): el fragmento citado y su corrección quedan en el
idioma de la nota, y lo que explica la IA se traduce al idioma elegido en el
dashboard la primera vez que se pide (queda guardado en "traducciones").

A diferencia del juez (generacion/juez.py), que decide si la nota pasa, acá se
mira solo la escritura y se señala cada error con el fragmento, qué está mal y
cómo arreglarlo. Es informativa: no toca la calificación de las personas ni
cuenta para el aprendizaje.
"""

from __future__ import annotations

import datetime
import json
import re

from afterdrive.ia import llm, redaccion
from afterdrive.ia.lm_studio import _extraer_json

TIPOS = ("gramatica", "ortografia", "redaccion", "tono", "estructura")
ASPECTOS = ("gramatica", "redaccion", "tono", "estructura")
ERRORES_MAX = 8
NOTA_MAX = 16000            # chars de la nota que entran al prompt
MAX_TOKENS = 3000           # la lista de errores es larga y los modelos gratis además razonan
INTENTOS = 2
IDIOMA_CRITICA = "es"
IDIOMAS_UI = {"es": "español rioplatense", "pt": "portugués de Brasil", "en": "inglés"}

_SYSTEM = """\
Sos corrector de estilo del blog B2B de AfterDrive by Alephee (autopartes y postventa automotriz).
Otra IA escribió la nota y vos revisás solo CÓMO está escrita, no si los datos son ciertos.

## Qué revisás
- gramatica: concordancia, tiempos verbales, preposiciones, puntuación que cambia el sentido.
- ortografia: tildes, mayúsculas, palabras mal escritas, nombres propios.
- redaccion: frases largas o confusas, repeticiones, muletillas de IA ("en un mundo cada vez más",
  "es importante destacar", "en conclusión"), relleno, oraciones que no dicen nada.
- tono: si respeta el rol, el estilo, el idioma y el trato pedidos (abajo). Mezclar voseo y tuteo,
  exagerar o sonar a folleto cuenta como error de tono.
- estructura: títulos, orden de las ideas, párrafos que no siguen la estructura pedida, cierre flojo.

## Idioma de tu respuesta
Escribí el resumen y cada problema en español rioplatense, aunque la nota esté en otro idioma.
El fragmento va TAL CUAL aparece en la nota (corto, hasta una oración) y la sugerencia es ese
mismo fragmento corregido, en el idioma de la nota. Si el arreglo no entra en un fragmento,
dejá la sugerencia vacía y explicá en el problema qué hacer.

## Cómo respondés
Sé concreto y exigente, pero no inventes errores: si algo está bien, no lo marques.
Sé breve: el problema en una oración.
Solo un JSON, sin texto alrededor:
{"puntaje": entero 1 a 10 (qué tan bien escrita está),
 "resumen": "dos o tres oraciones, en español: qué logró y en qué se equivocó la IA al redactarla",
 "aspectos": {"gramatica": 1 a 10, "redaccion": 1 a 10, "tono": 1 a 10, "estructura": 1 a 10},
 "errores": [{"tipo": "gramatica|ortografia|redaccion|tono|estructura",
              "fragmento": "texto exacto de la nota", "problema": "qué está mal, en español",
              "sugerencia": "el fragmento corregido, en el idioma de la nota"}] (los más importantes primero, hasta 8)}
"""


def _pedido(persona: str, regiones, idioma: str | None = None) -> str:
    p = redaccion.PERSONAS.get(persona) or redaccion.PERSONAS["comercial"]
    # La voz en que se escribió: el idioma guardado (portugués en las nuevas) o, en las viejas, sus regiones.
    voz = redaccion.voz_de_idioma(idioma) if idioma else redaccion.voz(regiones)
    return (f"## Lo que se le pidió a la IA\n- Rol: {p['rol']}\n- Tarea: {p['tarea']}\n"
            f"- Estructura: " + " / ".join(p["estructura"]) + f"\n- Estilo: {p['estilo']}\n"
            f"- Idioma: {voz.idioma}, con {voz.trato}\n")


def _numero(valor, default: int | None) -> int | None:
    try:
        return max(1, min(10, int(valor)))
    except (TypeError, ValueError):
        return default


def _texto(valor, largo: int) -> str:
    return " ".join(str(valor or "").split())[:largo]


def _leer(texto: str) -> dict:
    """JSON de la respuesta. Si vino cortado por el límite de tokens, se queda con
    lo completo: el puntaje, el resumen y los errores que alcanzaron a cerrarse."""
    try:
        return _extraer_json(texto)
    except ValueError:
        pass
    cuerpo = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    cuerpo = cuerpo[cuerpo.find("{"):] if "{" in cuerpo else ""
    corte = cuerpo.rfind("}")
    while corte > 0:
        for cierre in ("]}", "}"):
            try:
                return json.loads(cuerpo[:corte + 1] + cierre)
            except ValueError:
                pass
        corte = cuerpo.rfind("}", 0, corte)
    raise ValueError("la respuesta no trae un JSON")


def _pedir(user: str) -> tuple[dict | None, str]:
    """Hasta INTENTOS llamadas: (datos con puntaje, "") o (None, motivo del último fallo)."""
    motivo = ""
    for _ in range(INTENTOS):
        try:
            data = _leer(llm.completar(_SYSTEM, user, temperature=0.1, max_tokens=MAX_TOKENS, tarea="evaluacion"))
        except Exception as e:
            motivo = f"No se pudo criticar la nota: {e}"
            continue
        if isinstance(data, dict) and _numero(data.get("puntaje"), None) is not None:
            return data, ""
        motivo = "La IA no dio un puntaje para la redacción."
    return None, motivo


def criticar(nota: str, persona: str = "comercial", regiones=None, idioma: str | None = None) -> dict:
    """Crítica de la redacción. Siempre devuelve un dict; con "error" si no se pudo hacer."""
    if not llm.disponible():
        return {"error": "Proveedor de IA no disponible para criticar la nota."}
    user = _pedido(persona, regiones, idioma) + f"\n## Nota a revisar\n{(nota or '')[:NOTA_MAX]}"
    data, motivo = _pedir(user)
    if data is None:
        print(f"[CRITICA] {motivo}", flush=True)
        return {"error": motivo}
    puntaje = _numero(data.get("puntaje"), None)
    aspectos = data.get("aspectos") if isinstance(data.get("aspectos"), dict) else {}
    errores = []
    for e in data.get("errores") or []:
        if not isinstance(e, dict) or not _texto(e.get("problema"), 1):
            continue
        tipo = str(e.get("tipo") or "").lower().replace("á", "a")
        errores.append({
            "tipo": tipo if tipo in TIPOS else "redaccion",
            "fragmento": _texto(e.get("fragmento"), 220),
            "problema": _texto(e.get("problema"), 240),
            "sugerencia": _texto(e.get("sugerencia"), 240),
        })
    return {
        "puntaje": puntaje,
        "resumen": _texto(data.get("resumen"), 500),
        "aspectos": {k: v for k in ASPECTOS if (v := _numero(aspectos.get(k), None)) is not None},
        "errores": errores[:ERRORES_MAX],
        "idioma": IDIOMA_CRITICA,
        "fecha": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def criticar_guardada(coleccion: str, item_id: str, base=None) -> dict | None:
    """Critica una nota ya guardada y deja la crítica en ella. None si la nota no existe."""
    from afterdrive import calibracion

    if coleccion not in calibracion.COLECCIONES:
        raise calibracion.ErrorCalibracion("Solo se critican las notas generadas.")
    col = calibracion._base(base)[coleccion]
    doc = col.find_one({"_id": calibracion._oid(item_id)}, {"contenido": 1, "persona": 1, "regiones": 1, "idioma": 1})
    if not doc:
        return None
    resultado = criticar(doc.get("contenido") or "", doc.get("persona") or "comercial", doc.get("regiones"),
                         doc.get("idioma"))
    if not resultado.get("error"):
        col.update_one({"_id": doc["_id"]}, {"$set": {"critica": resultado}})
    return resultado


# ── Traducción al idioma del dashboard ────────────────────────────────────────

_SYSTEM_TRADUCCION = """\
Traducís al {idioma} los textos de una revisión de estilo de una nota de blog B2B.
Recibís un JSON y devolvés solo un JSON con las mismas claves y la misma cantidad de
elementos en "problemas", en el mismo orden. Lo que esté entre comillas es una cita
de la nota: dejalo como está. Sin texto alrededor del JSON.
"""


def _textos(critica: dict) -> dict:
    return {"resumen": critica.get("resumen") or "",
            "problemas": [e.get("problema") or "" for e in critica.get("errores") or []]}


def traducir(critica: dict, idioma: str) -> dict:
    """{"resumen", "problemas": [...]} en `idioma`. Con "error" si no se pudo."""
    if critica.get("idioma") == idioma:
        return _textos(critica)
    if not llm.disponible():
        return {"error": "Proveedor de IA no disponible para traducir la calificación."}
    original = _textos(critica)
    try:
        data = _extraer_json(llm.completar(_SYSTEM_TRADUCCION.format(idioma=IDIOMAS_UI[idioma]),
                                           json.dumps(original, ensure_ascii=False),
                                           temperature=0.1, max_tokens=MAX_TOKENS, tarea="traduccion"))
    except Exception as e:
        return {"error": f"No se pudo traducir la calificación: {e}"}
    problemas = data.get("problemas") if isinstance(data.get("problemas"), list) else []
    if len(problemas) != len(original["problemas"]):
        return {"error": "La traducción de la calificación vino incompleta."}
    return {"resumen": _texto(data.get("resumen"), 600), "problemas": [_texto(x, 300) for x in problemas]}


def traducir_guardada(coleccion: str, item_id: str, idioma: str, base=None) -> dict | None:
    """Traduce la crítica guardada y deja la traducción en la nota. None si la nota no existe."""
    from afterdrive import calibracion

    if coleccion not in calibracion.COLECCIONES:
        raise calibracion.ErrorCalibracion("Solo se critican las notas generadas.")
    if idioma not in IDIOMAS_UI:
        raise calibracion.ErrorCalibracion("Idioma desconocido.")
    col = calibracion._base(base)[coleccion]
    doc = col.find_one({"_id": calibracion._oid(item_id)}, {"critica": 1})
    if not doc:
        return None
    critica = doc.get("critica") or {}
    if not critica.get("puntaje") or critica.get("error"):
        raise calibracion.ErrorCalibracion("La nota todavía no tiene la calificación de la IA.")
    guardada = (critica.get("traducciones") or {}).get(idioma)
    if guardada:
        return guardada
    resultado = traducir(critica, idioma)
    if not resultado.get("error") and critica.get("idioma") != idioma:
        col.update_one({"_id": doc["_id"]}, {"$set": {f"critica.traducciones.{idioma}": resultado}})
    return resultado
