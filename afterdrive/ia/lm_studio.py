"""
lm_studio.py — Prompts y tareas de IA del pipeline.

Tareas (todas hablan con el proveedor a través del módulo LLM, llm.py):
  clasificar_articulo   ¿vale la pena guardar este artículo scrapeado?
  fichar_articulo       resumen, hechos, cifras y empresas de un artículo guardado
  evaluar_lineamientos  checklist de calidad de una nota generada
  generar_articulo      nota a partir de un contexto (sin uso: ver docs/09)

El nombre del archivo es histórico (empezó como cliente de LM Studio); el
proveedor, el transporte, los fallbacks y los embeddings viven en llm.py.
"""

import json
import re

from afterdrive.ia import llm, redaccion
from afterdrive.ia.saneo import sanear

# ── System prompts optimizados con patrones de prompt engineering ──────────────

_SYSTEM_EVALUAR = """\
Sos el editor de noticias del blog B2B AfterDrive by Alephee: lo leen dueños y gerentes de distribuidoras \
y casas de repuestos, fabricantes de autopartes, talleres mecánicos y lubricentros de Latinoamérica.

## Tu tarea
Decidir si una noticia scrapeada sirve como materia prima para una nota del blog.

## APROBÁ si a ese lector le sirve para su negocio. Por ejemplo:
- Autopartes y repuestos: fabricantes, distribuidores, lanzamientos, catálogos, precios, faltantes, calidad, \
falsificaciones.
- Mercado de reposición (aftermarket / posventa): ventas, cifras, tendencias, importaciones y exportaciones \
de autopartes, aranceles y regulaciones que lo afectan.
- Talleres, lubricentros, gomerías y servicio técnico: gestión, capacitación, herramientas, diagnóstico.
- Neumáticos, lubricantes, baterías, filtros, frenos, iluminación y demás rubros de reposición.
- Industria automotriz y autopartista: producción, inversiones, plantas, empleo, cámaras del sector.
- Parque automotor (cantidad y antigüedad de los vehículos), patentamientos y mercado de usados, como dato \
de la demanda de repuestos.
- Logística, distribución, e-commerce y digitalización del sector; ferias y eventos (Automechanika, etc.).
- Vehículos eléctricos e híbridos y nuevas tecnologías, cuando hablan de mantenimiento, repuestos o del \
negocio de posventa.
- Páginas de productos o catálogos de repuestos con especificaciones.

## RECHAZÁ solo si claramente no le sirve:
- Temas ajenos al sector: política general, policiales, deportes (también el automovilismo deportivo), \
espectáculos, clima, salud, recetas.
- Publicidad o review de un auto nuevo para el consumidor (prueba de manejo, precio de un 0 km, \
equipamiento) sin datos del negocio.
- Seguros, multas, licencias y trámites del conductor.
- Contenido vacío: anuncios del propio sitio, listados de links, avisos de empleo, textos inventados.

Ante la duda, si la noticia es del sector automotor y tiene algún dato útil para el negocio, APROBALA: \
después otro paso elige qué noticias van a cada nota.

## Formato de salida
Respondé ÚNICAMENTE con este JSON (sin texto adicional):
{"aprobado": true, "razon": "máximo 15 palabras"}

## Ejemplos
"Las pastillas de freno cerámicas ganan mercado en el aftermarket argentino" -> \
{"aprobado": true, "razon": "Mercado de repuestos"}
"La producción automotriz de Brasil creció 8% en septiembre" -> \
{"aprobado": true, "razon": "Industria automotriz: demanda autopartista"}
"El parque automotor argentino envejece: la edad promedio ya supera los 14 años" -> \
{"aprobado": true, "razon": "Parque automotor: demanda de reposición"}
"Bosch inaugura un centro de distribución en México" -> {"aprobado": true, "razon": "Distribución de autopartes"}
"Kit Correa Distribución Renault Master 2 2.5 G9u" -> {"aprobado": true, "razon": "Repuesto: kit de distribución"}
"Probamos el nuevo Toyota Corolla 2026: diseño y equipamiento" -> \
{"aprobado": false, "razon": "Review de auto nuevo para consumidores"}
"Los seguros de auto suben un 15%" -> {"aprobado": false, "razon": "Seguros, no autopartes"}
"Verstappen ganó el Gran Premio de Brasil" -> {"aprobado": false, "razon": "Automovilismo deportivo"}"""


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

    Política de fallos: si el proveedor no está o falla la llamada (p. ej. un 429
    del modelo gratis), el artículo queda pendiente: ni se guarda ni se descarta,
    así la próxima corrida lo vuelve a clasificar. Antes se aprobaba y entraba
    cualquier cosa (noticias de guerra de CNN, por ejemplo). Si el modelo
    respondió algo que no se entiende, se le pregunta una vez más y, si sigue
    sin entenderse, también queda pendiente. Antes se rechazaba y el artículo
    quedaba descartado para siempre: con un modelo local o gratis eso se
    llevaba buena parte de lo scrapeado.

    Returns:
        {"aprobado": bool, "razon": str, "pendiente"?: True}
    """
    if not llm.disponible():
        return {"aprobado": False, "pendiente": True, "razon": "sin clasificar: proveedor de IA no disponible"}

    mensaje = f"<EVALUAR>\nTítulo: {titulo}\n\nCuerpo: {(cuerpo or '')[:2000]}"
    for _ in range(2):
        try:
            data = _extraer_json(llm.completar(_SYSTEM_EVALUAR, mensaje, temperature=0.1, tarea="clasificacion"))
        except json.JSONDecodeError:
            continue   # respuesta rota: no es un juicio, se pregunta otra vez
        except Exception as e:
            return {"aprobado": False, "pendiente": True, "razon": f"sin clasificar: {e}"}
        if not isinstance(data, dict) or "aprobado" not in data:
            continue
        aprobado = data["aprobado"]
        if isinstance(aprobado, str):  # algunos modelos devuelven "false" entre comillas
            aprobado = aprobado.strip().lower() in ("true", "si", "sí")
        return {"aprobado": aprobado is True, "razon": data.get("razon", "Sin razón especificada")}
    return {"aprobado": False, "pendiente": True, "razon": "sin clasificar: respuesta inválida del modelo"}


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
