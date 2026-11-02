"""
redaccion.py — System prompts de redacción de notas.

Interfaz:
    system_prompt(persona, region=None, compacto=False, extension=None, directiva="") -> str
    voz(regiones) -> Voz
    voz_de_idioma(cod) -> Voz          es, pt o en (los blogs de HubSpot)
    idioma_principal() -> "pt"         en el que se escriben las notas (IDIOMA_PRINCIPAL)
    extension(largo) -> str          "corto" | "medio" | "largo" -> rango de palabras
    alephee_url() -> str
    persona(slug) -> dict              rol, tarea, estructura (lista) y estilo de la versión activa
    texto(clave) -> str                el Markdown activo de una pieza editable
    PIEZAS, PERSONAS (textos originales)

Toda nota cierra igual: la sección de implicancias para el negocio, las
preguntas frecuentes (salvo en modo compacto), la llamada a la acción y la
meta description. La sección de fuentes no la escribe el modelo: se agrega
después con las noticias realmente usadas (ver generacion/verificacion.py).

El prompt se arma con piezas comunes (identidad, audiencia, reglas de datos,
formato, cierre) y el bloque propio de cada persona (tarea, estructura,
estilo). Antes cada persona repetía las reglas a mano y se contradecían
entre sí; además estaban escritas sin tildes, y el modelo imitaba eso.

Las piezas (identidad, audiencia, reglas de datos, oficio, enfoque Alephee,
formato, SEO, respuesta y las 5 personas) se editan como Markdown desde el
dashboard y pasan por aprobación (prompts_editables.py). Acá se lee la versión
activa; si no hay o Mongo falla, se usan los textos originales de este archivo.
Las personas se escriben como: el rol, y después `## Tu tarea`, `## Estructura`
(lista numerada) y `## Estilo`.

Reglas de diseño:
- Sin casos ni cifras de ejemplo con marcas reales: el modelo los copiaba en
  cada nota. Los hechos salen de las noticias que se pasan como contexto.
- La voz (idioma, voseo/tuteo, ejemplo de CTA) depende de la región.
- `compacto=True` es para modelos chicos (7B locales), que siguen peor un
  prompt largo: mismas reglas esenciales, menos texto.
"""

import os
import re
from dataclasses import dataclass

# ── Voz por región ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Voz:
    idioma: str
    trato: str
    ejemplo_cta: str
    # Títulos de las secciones fijas, en el idioma de la nota. Los controles de
    # calidad los buscan tal cual (generacion/calidad.py).
    titulo_implicancias: str = "Qué significa para tu negocio"
    titulo_faq: str = "Preguntas frecuentes"
    titulo_fuentes: str = "Fuentes"


_VOCES = {
    "argentina": Voz("español rioplatense", "voseo (\"descubrí\", \"conocé\", \"sumá\")",
                     "Descubrí cómo Alephee conecta tu catálogo con los principales marketplaces."),
    "neutro": Voz("español latinoamericano neutro", "tuteo (\"descubre\", \"conoce\", \"suma\")",
                  "Descubre cómo Alephee conecta tu catálogo con los principales marketplaces."),
    "brasil": Voz("portugués de Brasil", "tratamiento de \"você\"",
                  "Descubra como a Alephee conecta seu catálogo aos principais marketplaces.",
                  "O que isso significa para o seu negócio", "Perguntas frequentes", "Fontes"),
    "asia": Voz("inglés", "segunda persona (\"you\")",
                "Discover how Alephee connects your catalog to the leading marketplaces.",
                "What this means for your business", "Frequently asked questions", "Sources"),
    "china": Voz("chino mandarín simplificado", "registro profesional",
                 "了解 Alephee 如何将您的目录与主要电商平台连接。",
                 "这对您的业务意味着什么", "常见问题", "资料来源"),
}


# Voz de cada blog de AfterDrive en HubSpot: la que usan las traducciones.
_VOZ_DE_BLOG = {"es": "argentina", "pt": "brasil", "en": "asia"}


def voz_de_idioma(cod: str) -> Voz:
    """Voz de una traducción al idioma de un blog (es, pt, en)."""
    return _VOCES[_VOZ_DE_BLOG[cod]]


def idioma_principal() -> str:
    """Idioma en el que se escriben todas las notas (es, pt o en): portugués salvo IDIOMA_PRINCIPAL.

    Las regiones ya no cambian el idioma: eligen el mercado del que habla la
    nota. Las otras versiones se traducen apenas se crea (traducciones.py).
    """
    cod = os.getenv("IDIOMA_PRINCIPAL", "pt").strip().lower()
    return cod if cod in _VOZ_DE_BLOG else "pt"


def alephee_url() -> str:
    """A dónde lleva el CTA cuando la nota no tiene un puntapié propio."""
    return os.getenv("ALEPHEE_URL", "https://alephee.com").strip() or "https://alephee.com"
_ESPAÑOL_NEUTRO = {"mexico", "latinoamerica", "europa"}


def voz(regiones: list[str] | None) -> Voz:
    """Voz de la nota según las regiones elegidas.

    Sin región, la voz de la casa: rioplatense (AfterDrive es argentino). Si
    se mezclan regiones de habla hispana, tuteo neutro. Si hay una región de
    otro idioma, manda la primera que aparezca.
    """
    regiones = [r for r in (regiones or []) if r]
    for r in regiones:
        if r in ("brasil", "asia", "china"):
            return _VOCES[r]
    if not regiones or regiones == ["argentina"]:
        return _VOCES["argentina"]
    return _VOCES["neutro"]


# ── Piezas comunes ────────────────────────────────────────────────────────────

_IDENTIDAD = (
    "Escribís notas para el blog de AfterDrive by Alephee, un medio B2B sobre el aftermarket "
    "automotor en Latinoamérica."
)

_AUDIENCIA = """\
## Para quién escribís
Repuesteros, distribuidores, gerentes de e-commerce automotor y talleres multimarca. \
Les importan la rotación, los márgenes, las devoluciones por fitment incorrecto, el catálogo \
digital y la integración con marketplaces. No escribís para el conductor ni el consumidor final."""

_REGLAS_DATOS = """\
## Datos: la regla que no se negocia
- Todo hecho concreto (cifras, porcentajes, empresas, casos, citas, fechas) sale de las \
noticias de contexto o de los clientes indicados. Si no está ahí, no existe: no inventes \
estadísticas, estudios, consultoras ni casos de éxito.
- Si no tenés un dato para una afirmación, escribila sin cifras. Nunca dejes huecos del \
tipo "cada X km" o "un Y%".
- Transformá la información: no copies listados de productos, precios ni tablas.
- La primera vez que uses un dato de una noticia, enlazala en el texto: \
"según [el medio o la noticia](url de esa noticia)". Solo URLs que aparecen en las noticias \
de contexto o en los enlaces sugeridos del pedido: nunca inventes una URL.
- No escribas una sección de fuentes al final: se agrega sola.
- Las notas de AfterDrive by Alephee que trae el pedido son análisis propios del blog: si una \
encaja con lo que estás contando, citala como fuente propia ("como analizamos en AfterDrive by \
Alephee, [texto descriptivo](url de esa nota)"), solo con lo que dice su resumen. Una o dos como \
mucho, y ninguna si no encajan."""

_REGLAS_OFICIO = """\
## Oficio del sector
- Terminología exacta: neumáticos o cubiertas (la goma) no son llantas (el aro); pastillas de \
freno, no "pastillas de seguridad". El desgaste y el envejecimiento son del neumático, nunca \
de la rueda.
- No confundas sistemas: motor no es transmisión, freno no es suspensión.
- No expliques obviedades ("los frenos son importantes"). Hablá de márgenes, rotación, \
devoluciones, indexación, ERP y fitment.
- Nombrá las plataformas reales cuando correspondan (Alephee, Mercado Libre, TecDoc), \
no "una plataforma" o "un marketplace".
- Kilómetros, nunca millas. "Repuestos", nunca "auto partes".
- Cada sección aporta información nueva. No repitas frases ni ideas, sobre todo en el cierre."""


_FORMATO = """\
## Formato
- Markdown. El título va con "# " y las secciones con "## ".
- Títulos de sección descriptivos, que nombren un dolor o un beneficio del negocio. Nunca \
"Problema:", "Solución:" ni "Introducción".
- **Negrita** en cifras y nombres de empresas. Oraciones cortas, voz activa.
- Ortografía, tildes y puntuación impecables.
- Extensión: {extension}."""

# Cómo entra Alephee en la nota. Bloque nuevo, pedido en la reunión del equipo:
# hasta ahora Alephee solo aparecía en el CTA y en "Nombrá las plataformas reales".
_ENFOQUE_ALEPHEE = """\
## Enfoque Alephee
- Alephee conecta el catálogo de autopartes de distribuidores y repuesteros con los \
principales marketplaces. Cuando la nota hable de catálogo, marketplaces o venta online, \
mostrá dónde encaja, en una o dos oraciones y donde resuelva un problema que la nota planteó.
- La nota informa primero: Alephee no es el tema salvo que el pedido lo diga. Nada de \
tono publicitario en el cuerpo; la invitación va en la llamada a la acción.
- No le atribuyas funciones, precios, cifras ni clientes que no estén en este bloque, en \
las noticias o en el pedido."""


_SEO = """\
## SEO
- Título de 60 caracteres como máximo, concreto, sin signos de exclamación.
- Si el pedido trae una palabra clave, usala en el título, en el primer párrafo, en un título \
de sección y en la meta description, sin forzarla.
- Los enlaces a notas de AfterDrive by Alephee llevan un texto de enlace descriptivo (nunca \
"click acá" ni la URL sola) y van donde el lector quiera profundizar, no amontonados al final."""


def _secciones_fijas(v: Voz, compacto: bool) -> str:
    implicancias = (
        f"1. `## {v.titulo_implicancias}`: de 3 a 5 viñetas con acciones concretas para un "
        "distribuidor, repuestero o taller (precios, stock, canales, catálogo). Cada viñeta empieza "
        "con un verbo y se apoya en algo dicho en la nota. Nada genérico como \"adaptarse al cambio\"."
    )
    if compacto:
        return f"## Al final de la nota\n{implicancias}\nDespués: la llamada a la acción y la meta description."
    faq = (
        f"2. `## {v.titulo_faq}`: 3 preguntas que alguien del sector buscaría en Google, cada una "
        "como `### ¿…?`, con una respuesta de 2 o 3 oraciones que use solo información de la nota."
    )
    return (
        "## Secciones fijas al final (después de la estructura, en este orden)\n"
        f"{implicancias}\n{faq}\nDespués: la llamada a la acción y la meta description."
    )


def _cierre(v: Voz, puntapie_url: str | None) -> str:
    destino = (
        f"El CTA lleva al lector a {puntapie_url} con un link explícito en Markdown."
        if puntapie_url else f"El CTA invita a conocer Alephee con un link explícito en Markdown a {alephee_url()}."
    )
    return f"""\
## Idioma y cierre
- Escribí toda la nota en {v.idioma}, con {v.trato}.
- El penúltimo párrafo es una sola llamada a la acción en presente, nunca en infinitivo. \
{destino} Ejemplo del tono (no lo copies): "{v.ejemplo_cta}"
- La nota termina con la meta description en *cursiva* (máximo 155 caracteres), sin \
ninguna etiqueta delante."""


_SALIDA = """\
## Respuesta
Respondé solo con la nota terminada, empezando por el título. No escribas tu plan, notas, \
explicaciones ni comentarios antes o después."""


# ── Personas ──────────────────────────────────────────────────────────────────

PERSONAS = {
    "analitico": {
        "rol": "Sos un analista del aftermarket automotor.",
        "tarea": "Explicá un fenómeno técnico o de negocio del sector a partir de las noticias de contexto.",
        "estructura": [
            "Un hecho o tendencia concreta de las noticias, presentada en el primer párrafo.",
            "Por qué ocurre: las causas técnicas o de mercado.",
            "Cómo se reacomoda el mercado: quién gana, quién pierde y qué plataformas intervienen.",
        ],
        "estilo": "Preciso y técnico, sin adornos. Explicá qué resuelve cada norma o tecnología que menciones.",
    },
    "periodistico": {
        "rol": "Sos un periodista especializado en la industria automotriz y el aftermarket.",
        "tarea": "Contá una novedad del sector con pirámide invertida: lo más importante primero.",
        "estructura": [
            "El hecho: qué pasó, quién, dónde y cuándo.",
            "Los datos clave que lo dimensionan.",
            "Cómo impacta o cómo responde el sector.",
            "Qué viene: próximos pasos y tendencias.",
        ],
        "estilo": "Neutral y objetivo. Atribuí cada dato a la noticia de la que sale.",
    },
    "comercial": {
        "rol": "Sos un redactor comercial B2B del aftermarket automotor.",
        "tarea": (
            "Mostrá cómo una solución concreta resuelve un problema del negocio. No te quedes en "
            "describir el problema: después de cada dolor, mostrá cómo se resuelve."
        ),
        "estructura": [
            "Un gancho con un hecho concreto de las noticias.",
            "La solución: qué hace y cómo lo resuelve, paso a paso.",
            "Casos o ejemplos, solo de las noticias o de los clientes indicados.",
            "Por qué conviene actuar ahora.",
        ],
        "estilo": (
            "Persuasivo sin exagerar. Verbos en presente y afirmativos (\"reduce\", \"ordena\", "
            "\"acelera\"), no \"puede mejorar\". Sin signos de exclamación ni fórmulas como "
            "\"no te lo pierdas\". Cada beneficio con un dato o un ejemplo, nunca una lista genérica."
        ),
    },
    "divulgativo": {
        "rol": "Sos un divulgador técnico del aftermarket automotor.",
        "tarea": (
            "Explicá UN solo concepto concreto del sector (por ejemplo: fitment por año y motor, "
            "catálogo con referencias cruzadas, integración ERP-marketplace). Nunca \"la tecnología\" "
            "en general ni varios temas a la vez."
        ),
        "estructura": [
            "El concepto con una analogía del mundo real que no sea obvia.",
            "Cómo funciona en la práctica, paso a paso.",
            "Un ejemplo concreto tomado de las noticias.",
        ],
        "estilo": "Didáctico y simple, con al menos tres oraciones con contenido real por sección.",
    },
    "ejecutivo": {
        "rol": "Sos un analista de estrategia para la industria de autopartes y el e-commerce B2B.",
        "tarea": "Escribí una nota de alto nivel para quienes deciden: dueños, gerentes y directores.",
        "estructura": [
            "Panorama: qué está pasando en el sector, según las noticias.",
            "El desafío: márgenes, costos logísticos, integración digital.",
            "Hoja de ruta: cómo digitalizar la cadena de valor, con plataformas reales.",
        ],
        "estilo": "Directivo y conciso. Hablá de ROI, costos, márgenes y riesgos, sin lenguaje corporativo vacío.",
    },
}

# Largo aproximado de la nota, elegible en Crear nota. Incluye las secciones
# fijas. Más largo no es mejor: la nota de 1400 palabras repetía ideas.
LARGOS = {
    "corto": "entre 500 y 700 palabras",
    "medio": "entre 700 y 1000 palabras",
    "largo": "entre 1000 y 1400 palabras",
}
LARGO_DEFAULT = "medio"
_EXTENSION_DEFAULT = LARGOS[LARGO_DEFAULT]


def extension(largo: str | None) -> str:
    return LARGOS.get(largo or "", _EXTENSION_DEFAULT)


def _bloque_persona(p: dict) -> str:
    pasos = "\n".join(f"{i}. {paso}" for i, paso in enumerate(p["estructura"], 1))
    return f"""\
## Tu tarea
{p["tarea"]}

## Estructura (una sección "## " por punto, en este orden)
{pasos}

## Estilo
{p["estilo"]}"""


# ── Piezas editables ──────────────────────────────────────────────────────────
# Cada pieza es Markdown. El orden es el del prompt completo.

def persona_a_markdown(p: dict) -> str:
    """Una persona como se edita en el dashboard."""
    pasos = "\n".join(f"{i}. {paso}" for i, paso in enumerate(p["estructura"], 1))
    return f"{p['rol']}\n\n## Tu tarea\n{p['tarea']}\n\n## Estructura\n{pasos}\n\n## Estilo\n{p['estilo']}"


_SECCIONES_PERSONA = {"tu tarea": "tarea", "tarea": "tarea", "estructura": "estructura", "estilo": "estilo"}


def parsear_persona(md: str) -> dict:
    """{"rol", "tarea", "estructura": [...], "estilo"} desde el Markdown de una persona.

    El rol es el texto antes del primer "## ". Las secciones se reconocen por el
    comienzo del título ("## Estructura (lo que sea)" también vale). La
    estructura es la lista numerada; una línea sin número sigue el punto anterior.
    """
    partes: dict[str, list[str]] = {"rol": []}
    actual = "rol"
    for linea in (md or "").replace("\r\n", "\n").split("\n"):
        titulo = re.match(r"^##\s+(.+?)\s*$", linea)
        if titulo:
            nombre = titulo.group(1).lower().strip(" :")
            actual = next((v for k, v in _SECCIONES_PERSONA.items() if nombre.startswith(k)), "_otra")
            partes.setdefault(actual, [])
            continue
        partes.setdefault(actual, []).append(linea)

    def junto(clave):
        return " ".join(" ".join(partes.get(clave, [])).split())

    pasos: list[str] = []
    for linea in partes.get("estructura", []):
        item = re.match(r"^\s*\d+[.)]\s+(.*)$", linea)
        if item:
            pasos.append(item.group(1).strip())
        elif linea.strip() and pasos:
            pasos[-1] = f"{pasos[-1]} {linea.strip()}"
    rol = re.sub(r"^#\s+\S.*$", "", "\n".join(partes["rol"]), flags=re.M)   # un "# Título" arriba no es parte del rol
    return {"rol": " ".join(rol.split()), "tarea": junto("tarea"), "estructura": pasos, "estilo": junto("estilo")}


PIEZAS = {
    "identidad": _IDENTIDAD,
    "audiencia": _AUDIENCIA,
    "reglas_datos": _REGLAS_DATOS,
    "oficio": _REGLAS_OFICIO,
    "enfoque_alephee": _ENFOQUE_ALEPHEE,
    "formato": _FORMATO,
    "seo": _SEO,
    "salida": _SALIDA,
    **{f"persona_{slug}": persona_a_markdown(p) for slug, p in PERSONAS.items()},
}


def _activas() -> dict:
    """Las piezas aprobadas en el dashboard. Nunca falla: sin Mongo, {}."""
    try:
        from afterdrive import prompts_editables
        return prompts_editables.activos()
    except Exception as e:
        print(f"[AVISO] No se pudieron leer los prompts editados: {e}", flush=True)
        return {}


def texto(clave: str, piezas: dict | None = None) -> str:
    """El Markdown activo de una pieza (o el original). `piezas` pisa lo activo (vista previa)."""
    if piezas and clave in piezas:
        return piezas[clave]
    return _activas().get(clave) or PIEZAS[clave]


def persona(slug: str, piezas: dict | None = None) -> dict:
    """Rol, tarea, estructura y estilo de una persona; una desconocida es la analítica.

    Si la versión activa no se puede leer como persona (le falta una sección),
    se usa la original: un prompt roto nunca llega al modelo.
    """
    slug = slug if slug in PERSONAS else "analitico"
    clave = f"persona_{slug}"
    if (piezas and clave in piezas) or clave in _activas():
        p = parsear_persona(texto(clave, piezas))
        if p["rol"] and p["tarea"] and p["estructura"] and p["estilo"]:
            return p
    return dict(PERSONAS[slug])


def system_prompt(
    persona: str = "analitico",
    region: list[str] | None = None,
    compacto: bool = False,
    extension: str | None = None,
    puntapie_url: str | None = None,
    directiva: str = "",
    idioma: str | None = None,
    piezas: dict | None = None,
) -> str:
    """System prompt de redacción para una persona. `idioma` (es, pt, en) fija la voz; si no, sale de la región.

    `piezas` ({clave: markdown}) reemplaza las piezas activas: es para la vista
    previa de un borrador en el dashboard.
    """
    p = _persona(persona, piezas)
    v = voz_de_idioma(idioma) if idioma else voz(region)
    extension = extension or _EXTENSION_DEFAULT
    identidad = texto("identidad", piezas)

    if compacto:
        partes = [
            f"{p['rol']} {identidad}",
            "Lectores: repuesteros, distribuidores y gerentes de e-commerce automotor (no consumidores).",
            _bloque_persona(p),
            "## Reglas\n"
            "- Cifras, empresas y casos: solo de las noticias de contexto. Si no hay dato, no uses cifras.\n"
            "- Neumático (goma) no es llanta (aro). Motor no es transmisión.\n"
            "- Markdown: título con \"# \", secciones con \"## \". Negrita en cifras y empresas.\n"
            "- Título de 60 caracteres como máximo. No inventes URLs.\n"
            "- Si una nota de AfterDrive by Alephee del pedido encaja, citala como propia y enlazala; si no, no.\n"
            f"- Extensión: {extension}. Sin repetir ideas.",
            _secciones_fijas(v, compacto=True),
            _cierre(v, puntapie_url),
            texto("salida", piezas),
        ]
    else:
        partes = [
            f"{p['rol']} {identidad}",
            texto("audiencia", piezas),
            _bloque_persona(p),
            texto("reglas_datos", piezas),
            texto("oficio", piezas),
            texto("enfoque_alephee", piezas),
            # replace y no format: el texto lo escribe una persona y puede traer otras llaves.
            texto("formato", piezas).replace("{extension}", extension),
            texto("seo", piezas),
            _secciones_fijas(v, compacto=False),
            _cierre(v, puntapie_url),
            texto("salida", piezas),
        ]
    if directiva:
        partes.append(directiva)
    return "\n\n".join(partes)


_persona = persona   # system_prompt tiene un parámetro que se llama igual
