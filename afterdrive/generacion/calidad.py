"""
calidad.py — Controles de estilo y SEO de una Nota, sin IA.

Interfaz:
    revisar(texto, voz, faq=True, palabra_clave="") -> Revision
    partes(texto) -> Partes                 título, meta description, secciones

Complementa al evaluador con IA (lm_studio.evaluar_lineamientos): estas
reglas son gratis, no fallan y no dependen del proveedor. Cada problema es un
Hallazgo; los `graves` justifican reescribir la nota, el resto se muestra al
revisar.

Las listas de frases y palabras son conservadoras a propósito: una frase que
el equipo usa de verdad no debería marcarse. Se amplían acá.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from afterdrive.ia.redaccion import Voz

TITULO_MAX = 60
TITULO_MAX_GRAVE = 80
META_MAX = 155
PARRAFO_MAX_PALABRAS = 120

# Muletillas que delatan texto de IA y no aportan nada.
FRASES_IA = (
    r"en el (dinámico|cambiante|vertiginoso|competitivo) mundo",
    r"en el mundo actual",
    r"en la era digital",
    r"en un mundo cada vez más",
    r"no es ningún secreto",
    r"cabe destacar",
    r"es importante (destacar|mencionar|señalar|resaltar)",
    r"sin lugar a dudas",
    r"juega un (papel|rol) (crucial|fundamental|clave|vital)",
    r"un antes y un después",
    r"panorama en constante evolución",
    r"en constante evolución",
    r"desbloque(ar|a|ando) (el|todo su) potencial",
    r"llevar(lo)? al siguiente nivel",
    r"(sumergirnos|adentrarnos|exploraremos|vamos a explorar)",
    r"en este artículo (vamos a|te contamos|exploramos)",
    r"en conclusión,",
    r"a fin de cuentas",
    r"ni más ni menos",
)
_FRASES_IA = [re.compile(r"\b" + f + r"\b", re.IGNORECASE) for f in FRASES_IA]

# Anglicismos con equivalente claro en español. Los que el sector usa a diario
# (stock, e-commerce, marketplace, retail, fitment) no se marcan.
ANGLICISMOS = {
    "insights": "conclusiones",
    "performance": "rendimiento",
    "partner": "socio",
    "partners": "socios",
    "engagement": "interacción",
    "feedback": "comentarios",
    "deadline": "plazo",
    "know-how": "experiencia",
    "target": "público objetivo",
    "benchmark": "referencia",
    "workflow": "flujo de trabajo",
    "approach": "enfoque",
    "game changer": "cambio de reglas",
    "update": "actualización",
    "delivery": "entrega",
    "customer journey": "recorrido del cliente",
}

# Términos de la casa: (patrón, qué decir).
TERMINOS = (
    (r"\bauto partes\b", "\"Repuestos\" o \"autopartes\", nunca \"auto partes\"."),
    (r"\bmillas\b", "Kilómetros, nunca millas."),
    (r"\bbalatas?\b", "Pastillas de freno, no balatas."),
    (r"\bpastillas de seguridad\b", "Pastillas de freno, no \"pastillas de seguridad\"."),
)

# Huecos que el modelo deja cuando no tiene el dato ("un X%", "[cifra]").
_HUECOS = re.compile(r"\b[XYZ]\s?%|\bcada [XYZ]\b|\[(dato|cifra|empresa|nombre|fuente)[^\]]*\]", re.IGNORECASE)


@dataclass(frozen=True)
class Hallazgo:
    codigo: str
    detalle: str
    grave: bool = False


@dataclass
class Revision:
    hallazgos: list[Hallazgo] = field(default_factory=list)
    seo: dict = field(default_factory=dict)

    @property
    def graves(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.grave]

    def como_dict(self) -> dict:
        return {"hallazgos": [asdict(h) for h in self.hallazgos], "seo": self.seo}


@dataclass
class Partes:
    titulo: str = ""
    meta: str = ""
    secciones: list[str] = field(default_factory=list)   # títulos "## "
    cuerpo: str = ""                                     # sin título ni meta


def _plano(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def partes(texto: str) -> Partes:
    lineas = (texto or "").strip().splitlines()
    p = Partes()
    for i, ln in enumerate(lineas):
        if ln.startswith("# "):
            p.titulo = ln[2:].strip().strip("*_ ")
            lineas = lineas[:i] + lineas[i + 1:]
            break
    while lineas and not lineas[-1].strip():
        lineas.pop()
    if lineas:
        m = re.fullmatch(r"[*_]{1,2}([^*_].*?)[*_]{1,2}", lineas[-1].strip())
        if m:
            p.meta = m.group(1).strip()
            lineas.pop()
    p.secciones = [ln[3:].strip() for ln in lineas if ln.startswith("## ")]
    p.cuerpo = "\n".join(lineas).strip()
    return p


def _tiene_seccion(p: Partes, titulo: str) -> bool:
    buscado = _plano(titulo)
    return any(buscado in _plano(s) for s in p.secciones)


def _faq(p: Partes, titulo: str) -> int:
    """Cuántas preguntas (### ) hay dentro de la sección de preguntas frecuentes."""
    bloque = re.split(r"^## ", p.cuerpo, flags=re.MULTILINE)
    for b in bloque:
        if _plano(b.split("\n", 1)[0]).startswith(_plano(titulo)):
            return len(re.findall(r"^### ", b, flags=re.MULTILINE))
    return 0


def _parrafos(cuerpo: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", cuerpo)
            if b.strip() and not b.strip().startswith(("#", "-", "*", ">", "1."))]


def _primer_parrafo(cuerpo: str) -> str:
    ps = _parrafos(cuerpo)
    return ps[0] if ps else ""


def _links(texto: str) -> list[tuple[str, str]]:
    return re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", texto or "")


def _estilo_es(texto: str, hallazgos: list[Hallazgo]) -> None:
    frases = sorted({m.group(0).lower() for rx in _FRASES_IA for m in rx.finditer(texto)})
    if frases:
        hallazgos.append(Hallazgo("frases_ia", "Frases de relleno típicas de IA: " + ", ".join(f'"{f}"' for f in frases),
                                  grave=len(frases) >= 3))
    plano = texto.lower()
    usados = [f'"{a}" (mejor: {s})' for a, s in ANGLICISMOS.items() if re.search(r"\b" + re.escape(a) + r"\b", plano)]
    if usados:
        hallazgos.append(Hallazgo("anglicismos", "Anglicismos con equivalente en español: " + ", ".join(usados)))
    for patron, detalle in TERMINOS:
        if re.search(patron, plano):
            hallazgos.append(Hallazgo("termino", detalle))
    if "!" in texto or "¡" in texto:
        hallazgos.append(Hallazgo("exclamaciones", "Tiene signos de exclamación: el tono B2B no los usa."))


def revisar(texto: str, voz: Voz, faq: bool = True, palabra_clave: str = "",
            dominio_blog: str = "afterdrive.alephee.com") -> Revision:
    """Controles de estilo y SEO. `faq=False` para el modo compacto (modelos chicos)."""
    r = Revision()
    h = r.hallazgos
    p = partes(texto)

    if not p.titulo:
        h.append(Hallazgo("sin_titulo", "La nota no tiene título (# ...).", grave=True))
    elif len(p.titulo) > TITULO_MAX:
        h.append(Hallazgo("titulo_largo", f"El título tiene {len(p.titulo)} caracteres (máximo {TITULO_MAX}).",
                          grave=len(p.titulo) > TITULO_MAX_GRAVE))
    if not p.meta:
        h.append(Hallazgo("sin_meta", "Falta la meta description en cursiva al final.", grave=True))
    elif len(p.meta) > META_MAX:
        h.append(Hallazgo("meta_larga", f"La meta description tiene {len(p.meta)} caracteres (máximo {META_MAX})."))

    if not _tiene_seccion(p, voz.titulo_implicancias):
        h.append(Hallazgo("sin_implicancias", f"Falta la sección \"{voz.titulo_implicancias}\".", grave=True))
    preguntas = _faq(p, voz.titulo_faq) if faq else 0
    if faq and preguntas < 2:
        h.append(Hallazgo("sin_faq", f"Falta la sección \"{voz.titulo_faq}\" con al menos 2 preguntas."))

    if huecos := sorted({m.group(0) for m in _HUECOS.finditer(texto)}):
        h.append(Hallazgo("huecos", "Quedaron huecos sin dato: " + ", ".join(huecos), grave=True))

    largos = [len(x.split()) for x in _parrafos(p.cuerpo) if len(x.split()) > PARRAFO_MAX_PALABRAS]
    if largos:
        h.append(Hallazgo("parrafos_largos", f"{len(largos)} párrafo(s) de más de {PARRAFO_MAX_PALABRAS} palabras."))

    if voz.idioma.startswith("español"):
        _estilo_es(texto, h)

    clave = (palabra_clave or "").strip()
    links = _links(texto)
    r.seo = {
        "titulo_caracteres": len(p.titulo),
        "meta_caracteres": len(p.meta),
        "palabra_clave": clave,
        "preguntas_frecuentes": preguntas,
        "enlaces_internos": sum(1 for _, u in links if dominio_blog in u),
        "enlaces": len(links),
        "palabras": len(re.findall(r"\w+", p.cuerpo)),
    }
    if clave:
        k = _plano(clave)
        en = {"titulo": k in _plano(p.titulo), "meta": k in _plano(p.meta),
              "primer_parrafo": k in _plano(_primer_parrafo(p.cuerpo))}
        r.seo["palabra_clave_en"] = en
        faltan = [n.replace("_", " ") for n, ok in en.items() if not ok]
        if faltan:
            h.append(Hallazgo("palabra_clave", f"La palabra clave \"{clave}\" no aparece en: {', '.join(faltan)}."))
    return r
