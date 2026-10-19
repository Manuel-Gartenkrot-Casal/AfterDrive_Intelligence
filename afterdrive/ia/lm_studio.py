"""
lm_studio.py — Prompts y tareas de IA del pipeline.

Tareas (todas hablan con el proveedor a través del módulo LLM, llm.py):
  clasificar_articulo   ¿vale la pena guardar este artículo scrapeado?
  fichar_articulo       resumen, hechos, cifras y empresas de un artículo guardado
  evaluar_lineamientos  checklist de calidad de una nota generada
  generar_articulo      nota a partir de un contexto (lo usa scripts/demo_mode.py)

El nombre del archivo es histórico (empezó como cliente de LM Studio); el
proveedor, el transporte, los fallbacks y los embeddings viven en llm.py.
"""

import json
import re

from afterdrive.ia import llm, redaccion
from afterdrive.ia.saneo import sanear

# ── System prompts optimizados con patrones de prompt engineering ──────────────

_SYSTEM_EVALUAR = """\
Eres un clasificador de contenido especializado en la industria de autopartes y aftermarket.

## Tu tarea
Evaluar si un articulo es relevante para la industria de autopartes.

## Reglas de clasificacion
APROBAR solo si el contenido trata sobre:
- Piezas mecanicas (frenos, filtros, amortiguadores, etc.)
- Repuestos y catalogos de autopartes
- Normas tecnicas OEM y equivalencias
- Logistica inversa y gestion de devoluciones
- Digitalizacion del sector aftermarket
- E-commerce B2B de repuestos
- Indexacion y fitment de componentes
- PAGINAS DE PRODUCTOS de repuestos (kits de distribucion, homocineticas, electroventiladores, espejos, botadores, pastillas, etc.)
- CATALOGOS de autopartes con precios y especificaciones tecnicas

RECHAZAR si trata sobre:
- Ventas de vehiculos 0km (concesionarias, agencias, listados de autos nuevos)
- Seguros automotrices
- Anecdotas personales de consumidores
- Concesionarias o dealers de VEHICULOS (no de repuestos)
- Contenido generico de B2C (explicar al consumidor basico)
- Contenido con alucinaciones tecnicas (conceptos inventados que no existen)

## IMPORTANTE: Diferenciar REPUSTOS de VEHICULOS
- "Kit Correa Distribucion Renault" = REPOSTO → APROBAR
- "Kit Homocinetica Chevrolet Corsa" = REPOSTO → APROBAR
- "Electroventilador VW Gol" = REPOSTO → APROBAR
- "Espejos Retrovisores" = REPOSTO → APROBAR
- "Botadores VW Amarok" = REPOSTO → APROBAR
- "Concesionaria Renault venta 0km" = VEHICULO → RECHAZAR
- "Review Toyota Corolla 2026" = VEHICULO → RECHAZAR

## Formato de salida
Responde UNICAMENTE con este JSON (sin texto adicional):
{"aprobado": true/false, "razon": "maximo 15 palabras"}

## Ejemplos

Ejemplo 1 - APROBAR:
Entrada: "Las pastillas de freno ceramicas ganan mercado en el aftermarket argentino"
Salida: {"aprobado": true, "razon": "Mercado de repuestos aftermarket"}

Ejemplo 2 - RECHAZAR:
Entrada: "Los seguros auto suben un 15% y afectan el bolsillo de los conductores"
Salida: {"aprobado": false, "razon": "Tema de seguros, no autopartes"}

Ejemplo 3 - RECHAZAR:
Entrada: "Las ruedas de traccion en dos ruedas son importantes para la seguridad"
Salida: {"aprobado": false, "razon": "Alucinacion tecnica: concepto inventado"}

Ejemplo 4 - APROBAR:
Entrada: "Kit Correa Distribucion Renault Master 2 2.5 G9u"
Salida: {"aprobado": true, "razon": "Repuesto Renault: kit distribucion"}

Ejemplo 5 - APROBAR:
Entrada: "Electroventilador P/ Gol Trend Voyage Fox Suran Todos C/aire"
Salida: {"aprobado": true, "razon": "Repuesto Volkswagen: electroventilador"}"""


# ── Redacción ─────────────────────────────────────────────────────────────────
# Los system prompts de redacción viven en redaccion.py (persona + región +
# ajustes del proveedor). Esto queda por compatibilidad con generar_articulo.

PERSONAS_DISPONIBLES = list(redaccion.PERSONAS)


def get_system_prompt_redactar(persona: str = "analitico") -> str:
    """System prompt de redacción para la persona, ajustado al proveedor activo."""
    if persona not in redaccion.PERSONAS:
        print(f"[AVISO] Personalidad '{persona}' no encontrada, usando 'analitico'.")
    ajustes = llm.ajustes_redaccion()
    return redaccion.system_prompt(persona, compacto=ajustes.compacto, directiva=ajustes.directiva)


_SYSTEM_EVALUAR_CONTENIDO = """\
Eres un auditor de calidad editorial especializado en contenido B2B de autopartes y aftermarket.

## Tu tarea
Analizar el articulo y validar el cumplimiento de lineamientos de estilo y formato.

## Lineamientos a evaluar
1. **estructura_correcta** - Contiene secciones (##) bien definidas con titulos coherentes?
2. **formato_negritas** - Cifras, porcentajes, empresas y fechas en **negrita**?
3. **vocabulario_negocio** - Usa terminos del sector ("parque automotor", "demanda cautiva", "cadena de valor")?
4. **tono_b2b** - Lenguaje directo, profesional, enfocado al negocio?
5. **sin_paywall** - Sin frases de suscripcion o paywalls?
6. **no_repetitivo** - Cada seccion aporta informacion nueva? Las secciones finales de implicancias para el negocio ("Qué significa para tu negocio") y de preguntas frecuentes retoman ideas de la nota a proposito: no cuentan como repeticion.
7. **sin_alucinaciones** - No inventa conceptos tecnicos que no existen?
8. **sin_obviedades** - No explica cosas basicas que el lector B2B ya sabe?
9. **terminologia_correcta** - Usa los terminos correctos (neumaticos vs llantas, pastillas vs balatas)?

## Formato de salida
Responde UNICAMENTE con este JSON:
{
  "lineamientos": {
    "estructura_correcta": boolean,
    "formato_negritas": boolean,
    "vocabulario_negocio": boolean,
    "tono_b2b": boolean,
    "sin_paywall": boolean,
    "no_repetitivo": boolean,
    "sin_alucinaciones": boolean,
    "sin_obviedades": boolean,
    "terminologia_correcta": boolean
  },
  "comentarios": "string (breve observacion general)"
}"""


def _extraer_json(texto: str) -> dict:
    """Parsea el JSON de la respuesta del modelo de forma tolerante.

    Quita un bloque <think>...</think>, fences y prosa envolvente, y toma del
    primer "{" al último "}".
    """
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin == -1 or fin < inicio:
        raise json.JSONDecodeError("sin objeto JSON en la respuesta", texto, 0)
    return json.loads(texto[inicio : fin + 1])


# ── Tareas ─────────────────────────────────────────────────────────────────────


def clasificar_articulo(titulo: str, cuerpo: str) -> dict:
    """Evalúa si un artículo merece guardarse en la BD.

    Política de fallos: si el proveedor no está o falla la llamada, se aprueba
    (modo degradado: no perder artículos por una caída ajena al contenido). Si
    el modelo respondió basura, se rechaza (el juicio existe pero no se lee).

    Returns:
        {"aprobado": bool, "razon": str}
    """
    if not llm.disponible():
        return {"aprobado": True, "razon": "modo degradado: proveedor de IA no disponible"}

    mensaje = f"<EVALUAR>\nTítulo: {titulo}\n\nCuerpo: {(cuerpo or '')[:2000]}"
    try:
        data = _extraer_json(llm.completar(_SYSTEM_EVALUAR, mensaje, temperature=0.1, tarea="clasificacion"))
        aprobado = data.get("aprobado", False)
        if isinstance(aprobado, str):  # algunos modelos devuelven "false" entre comillas
            aprobado = aprobado.strip().lower() in ("true", "si", "sí")
        return {
            "aprobado": aprobado is True,
            "razon": data.get("razon", "Sin razón especificada"),
        }
    except json.JSONDecodeError:
        return {"aprobado": False, "razon": "error: respuesta inválida del modelo"}
    except Exception as e:
        return {"aprobado": True, "razon": f"modo degradado: {e}"}


_SYSTEM_FICHA = """\
Extraés la ficha de una noticia del aftermarket automotor para que otro redactor la use como fuente.

## Reglas
- Escribí en español, aunque la noticia esté en otro idioma.
- Solo lo que dice la noticia. No agregues contexto, opiniones ni datos que no estén.
- Cifras con su unidad y a qué se refieren ("15% de aumento en ventas de pastillas en 2025").
- Si no hay cifras, empresas o fecha, dejá la lista vacía o null.

## Formato de salida
Respondé UNICAMENTE con este JSON:
{"resumen": "2 o 3 oraciones", "hechos": ["..."], "cifras": ["..."], "empresas": ["..."], "fecha": "AAAA-MM-DD o null"}"""

_FICHA_MAX_ITEMS = 8
_FICHA_MAX_CHARS = 300


def _lista(valor) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [" ".join(str(x).split())[:_FICHA_MAX_CHARS] for x in valor if str(x).strip()][:_FICHA_MAX_ITEMS]


def fichar_articulo(titulo: str, cuerpo: str) -> dict | None:
    """Ficha estructurada de una noticia: resumen, hechos, cifras, empresas y fecha.

    La generación la usa como contexto en lugar del cuerpo crudo: más corto (más
    barato) y con los datos ya separados (menos lugar para inventar). Si el
    proveedor falla o responde algo que no es una ficha, devuelve None y la
    noticia se sigue usando con su cuerpo.
    """
    if not (cuerpo or "").strip() or not llm.disponible():
        return None
    mensaje = f"Título: {titulo}\n\nNoticia:\n{(cuerpo or '')[:6000]}"
    try:
        data = _extraer_json(llm.completar(_SYSTEM_FICHA, mensaje, temperature=0.1, max_tokens=900,
                                           tarea="clasificacion"))
    except Exception as e:
        print(f"    [AVISO] No se pudo armar la ficha: {e}", flush=True)
        return None
    resumen = " ".join(str(data.get("resumen") or "").split())[:800]
    if not resumen:
        return None
    fecha = str(data.get("fecha") or "").strip()
    return {
        "resumen": resumen,
        "hechos": _lista(data.get("hechos")),
        "cifras": _lista(data.get("cifras")),
        "empresas": _lista(data.get("empresas")),
        "fecha": fecha if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha) else None,
    }


def evaluar_lineamientos(articulo: str) -> dict:
    """Checklist de lineamientos de una nota generada."""
    if not llm.disponible():
        return {"error": "Proveedor de IA no disponible para evaluación"}
    try:
        texto = llm.completar(
            _SYSTEM_EVALUAR_CONTENIDO,
            f"Analizá el siguiente artículo:\n\n{articulo}",
            temperature=0.1,
            max_tokens=1024,
            tarea="evaluacion",
        )
        return _extraer_json(texto)
    except Exception as e:
        return {"error": str(e), "lineamientos": {}}


def generar_articulo(contexto: str, research: str = "", persona: str = "analitico", tema: str = "") -> str:
    """Genera una nota Fase 1 (Markdown) a partir del contexto.

    Args:
        persona: "analitico", "periodistico", "comercial", "divulgativo", "ejecutivo"
        tema: tema específico pedido por el usuario (ej: "frenos")

    Raises:
        llm.ErrorLLM si el proveedor falla o si no sale una nota publicable.
    """
    if not llm.disponible():
        raise llm.ErrorLLM("El proveedor de IA no está disponible. Revisá la configuración y reintentá.")

    if tema:
        contexto = f"TEMA: {tema}\n\n{contexto}"
    mensaje = (
        "Redacta un articulo B2B estilo blog sobre el siguiente contexto. "
        f"Usa la estructura y reglas de tu system prompt.\n\nCONTEXTO:\n{contexto}"
    )
    if research:
        mensaje += f"\n\nRESEARCH:\n{research}"

    crudo = llm.completar(
        get_system_prompt_redactar(persona), mensaje,
        temperature=llm.ajustes_redaccion().temperatura, max_tokens=4000, stream=True, tarea="redaccion",
    )
    saneo = sanear(crudo)
    if not saneo.ok:
        raise llm.ErrorLLM(f"No se obtuvo una nota publicable: {saneo.motivo}")

    try:
        print(saneo.texto)
    except UnicodeEncodeError:
        print(saneo.texto.encode("utf-8", errors="replace").decode("utf-8"))
    print("\n[OK]")
    return saneo.texto


# ── Test rápido (python -m afterdrive.ia.lm_studio) ─────────────────────────────────────────

if __name__ == "__main__":
    print(f"Proveedor: {llm.estado()}")
    r = clasificar_articulo(
        "Nueva línea de frenos para camiones",
        "La empresa XYZ lanzó una nueva línea de pastillas de freno para camiones pesados.",
    )
    print(f"Resultado: {json.dumps(r, indent=2, ensure_ascii=False)}")
