"""
plan.py — El plan de una Nota, antes de escribirla.

Interfaz:
    planificar(noticias, pedido, estructura, publicadas=(), reglas=()) -> dict | None
    formatear(plan, noticias) -> str      bloque para el prompt de redacción
    noticias_del_plan(plan, noticias) -> list

Redactar sin plan da notas que resumen noticias una tras otra. Con un plan
(ángulo, título, palabra clave, secciones con qué noticia alimenta cada una)
la nota sale mejor armada y se puede ver qué pensaba escribir el modelo.

Al plan se le pasan los títulos de las últimas notas para que elija otro
ángulo. Si el modelo no devuelve un plan válido, la nota se escribe igual,
sin plan: es una mejora, no un requisito.
"""

from __future__ import annotations

from afterdrive.ia import llm

TITULO_MAX = 60
# El plan es un JSON corto: con la API paga va al modelo de evaluación (ver
# llm.RESPALDO_TAREA) y con este presupuesto. Antes usaba el de redacción con
# 16000 tokens, y un modelo que razona podía gastar varios centavos solo acá.
MAX_TOKENS = 4000

_SYSTEM = """\
Sos el editor del blog B2B de AfterDrive by Alephee (aftermarket automotor en Latinoamérica). \
Antes de que un redactor escriba, armás el plan de la nota.

## Reglas
- Un solo ángulo concreto, apoyado en un hecho de las noticias. Nada de panoramas generales.
- Distinto de las notas ya publicadas que te paso: otro ángulo, otro hecho central.
- Cada sección indica qué noticias usa, por número. Una sección sin noticias es de análisis y no lleva cifras.
- La palabra clave es lo que un repuestero o un distribuidor buscaría en Google: de 2 a 4 palabras, en minúscula.
- Título de 60 caracteres como máximo, que incluya la palabra clave.
- Las implicancias son acciones concretas para un distribuidor, repuestero o taller (precios, stock, canales, catálogo).

## Formato de salida
Respondé solo con este JSON:
{"angulo": "una oración", "titulo": "...", "palabra_clave": "...",
 "secciones": [{"titulo": "...", "idea": "una oración", "noticias": [1, 2]}],
 "implicancias": ["...", "..."]}"""


def _normalizar(data: dict, n_noticias: int) -> dict | None:
    if not isinstance(data, dict):
        return None
    titulo = " ".join(str(data.get("titulo") or "").split())
    secciones = []
    for s in data.get("secciones") or []:
        if not isinstance(s, dict) or not str(s.get("titulo") or "").strip():
            continue
        idx = [int(i) for i in (s.get("noticias") or []) if isinstance(i, int | float) and 1 <= int(i) <= n_noticias]
        secciones.append({"titulo": " ".join(str(s["titulo"]).split())[:120],
                          "idea": " ".join(str(s.get("idea") or "").split())[:300],
                          "noticias": sorted(set(idx))})
    if not titulo or len(secciones) < 2:
        return None
    return {
        "angulo": " ".join(str(data.get("angulo") or "").split())[:300],
        "titulo": titulo[:120],
        "palabra_clave": " ".join(str(data.get("palabra_clave") or "").split()).lower()[:60],
        "secciones": secciones[:7],
        "implicancias": [" ".join(str(x).split())[:200] for x in (data.get("implicancias") or []) if str(x).strip()][:5],
    }


def planificar(noticias: list, pedido: str, estructura: list[str], publicadas: list[str] = (),
               reglas: list[str] = (), contexto: str = "", idioma: str = "") -> dict | None:
    """Plan de la nota, o None si el modelo no devolvió uno válido. Nunca lanza."""
    from afterdrive.ia.lm_studio import _extraer_json

    partes = ["## Noticias\n" + (contexto or "No hay noticias: el plan es de análisis, sin cifras.")]
    if estructura:
        partes.append("## Estructura que pide el estilo de la nota\n" + "\n".join(f"- {e}" for e in estructura))
    if publicadas:
        partes.append("## Notas ya publicadas (no repitas su ángulo)\n" + "\n".join(f"- {t}" for t in publicadas))
    if reglas:
        partes.append("## Correcciones del equipo\n" + "\n".join(f"- {r}" for r in reglas))
    if idioma:
        # Sin esto el plan salía en español aunque la nota fuera en portugués, y
        # el título y la palabra clave mezclaban idiomas.
        partes.append(f"## Idioma\nLa nota se escribe en {idioma}: título, palabra clave, secciones e "
                      "implicancias van en ese idioma, con la palabra clave que se busca en ese mercado.")
    partes.append("## Pedido\n" + pedido)
    try:
        crudo = llm.completar(_SYSTEM, "\n\n".join(partes), temperature=0.4, max_tokens=MAX_TOKENS,
                              tarea="planificacion")
        plan = _normalizar(_extraer_json(crudo), len(noticias))
    except llm.Cancelada:
        raise
    except Exception as e:
        print(f"  [AVISO] No se pudo armar el plan ({e}); se escribe sin plan.", flush=True)
        return None
    if plan is None:
        print("  [AVISO] El plan no vino completo; se escribe sin plan.", flush=True)
    return plan


def formatear(plan: dict) -> str:
    lineas = ["## Plan de la nota (seguilo)"]
    if plan.get("angulo"):
        lineas.append(f"Ángulo: {plan['angulo']}")
    lineas.append(f"Título propuesto: {plan['titulo']}")
    if plan.get("palabra_clave"):
        lineas.append(f"Palabra clave: {plan['palabra_clave']}")
    lineas.append("Secciones:")
    for i, s in enumerate(plan["secciones"], 1):
        fuentes = f" (noticias {', '.join(f'[{n}]' for n in s['noticias'])})" if s["noticias"] else " (análisis, sin cifras)"
        lineas.append(f"{i}. {s['titulo']}: {s['idea']}{fuentes}")
    if plan.get("implicancias"):
        lineas.append("Implicancias para la sección del negocio:")
        lineas += [f"- {x}" for x in plan["implicancias"]]
    return "\n".join(lineas)


def noticias_del_plan(plan: dict | None, noticias: list) -> list:
    if not plan:
        return []
    usados = {i for s in plan["secciones"] for i in s["noticias"]}
    return [n for i, n in enumerate(noticias, 1) if i in usados]
