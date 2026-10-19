"""
verificacion.py — Los datos de una Nota contra las noticias que la alimentaron.

Interfaz:
    verificar(nota, noticias, extra="") -> Verificacion
    sanear_enlaces(nota, noticias, permitidas=()) -> (nota, quitados)
    agregar_fuentes(nota, noticias, titulo="Fuentes") -> nota

Un dato inventado es el error más caro de una nota B2B, y el evaluador con IA
juzga el texto en general, no dato por dato. Acá se revisa cada uno:

1. Se extraen los datos de la nota: cifras (con %, moneda, decimales o de dos
   dígitos o más) y lo que va en negrita con nombre propio (las reglas de
   redacción piden negrita en cifras y empresas).
2. Cada dato se busca literal en las noticias (título, ficha y cuerpo), en los
   clientes indicados y en el pedido. Gratis y sin falsos negativos raros.
3. Lo que no apareció literal se le pregunta al modelo de evaluación, que
   entiende paráfrasis ("15 por ciento" = "15%"). Una sola llamada por nota, y
   solo si quedó algo sin encontrar.

Si el modelo no responde, una cifra no encontrada cuenta como sin respaldo y
un nombre queda como dudoso: los nombres tienen más formas de escribirse.
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

# Nombres que pueden aparecer sin estar en las noticias: la casa y las
# plataformas que las reglas de redacción piden nombrar.
SIEMPRE_PERMITIDOS = ("alephee", "afterdrive", "mercado libre", "mercadolibre", "tecdoc", "amazon", "google")

_NUMERO = re.compile(
    r"(?:US\$|USD|U\$S|R\$|\$|€)\s?\d[\d.,]*(?:\s?(?:millones|mil millones|mil|M|B))?"
    r"|\d[\d.,]*\s?(?:%|por ciento|puntos porcentuales)"
    r"|\b\d+[.,]\d+\b"
    r"|\b\d{2,}(?:[.,]\d{3})*\b",
    re.IGNORECASE,
)
_NEGRITA = re.compile(r"\*\*([^*\n]{2,80})\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


@dataclass
class Verificacion:
    total: int = 0
    respaldados: list[str] = field(default_factory=list)
    sin_respaldo: list[str] = field(default_factory=list)
    dudosos: list[str] = field(default_factory=list)
    metodo: str = "literal"          # "literal" o "literal+modelo"
    noticias_citadas: list[int] = field(default_factory=list)   # índices (0..n-1) con algún dato encontrado

    @property
    def grave(self) -> bool:
        return bool(self.sin_respaldo)

    def como_dict(self) -> dict:
        return asdict(self)


def _plano(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _digitos(s: str) -> str:
    """'US$ 1.500,5 millones' -> '15005'. Compara cifras escritas con distintos separadores."""
    return re.sub(r"\D", "", s)


def _sin_links(texto: str) -> str:
    return _LINK.sub(lambda m: m.group(1), texto)


def _es_anio_obvio(dato: str) -> bool:
    if not re.fullmatch(r"\d{4}", dato.strip()):
        return False
    anio = int(dato)
    actual = datetime.datetime.now(datetime.UTC).year
    return actual - 1 <= anio <= actual + 1


def extraer_datos(nota: str) -> list[tuple[str, str]]:
    """[(dato, tipo)] con tipo "cifra" o "nombre", sin repetir, en orden de aparición."""
    texto = _sin_links(nota)
    # La meta description repite datos del cuerpo; los títulos de las preguntas frecuentes también.
    vistos, datos = set(), []

    def sumar(dato: str, tipo: str):
        clave = _digitos(dato) if tipo == "cifra" else _plano(dato).strip()
        if clave and clave not in vistos:
            vistos.add(clave)
            datos.append((dato.strip(), tipo))

    for m in _NEGRITA.finditer(texto):
        span = m.group(1).strip()
        if _NUMERO.search(span):
            continue  # la cifra se toma abajo, sola
        palabras = span.split()
        # Nombre propio: alguna palabra con mayúscula (un concepto en negrita va en minúscula).
        if any(p[:1].isupper() for p in palabras) and not any(x in _plano(span) for x in SIEMPRE_PERMITIDOS):
            sumar(span, "nombre")
    for m in _NUMERO.finditer(texto):
        dato = m.group(0)
        if not _es_anio_obvio(dato):
            sumar(dato, "cifra")
    return datos


def _evidencias(noticias, extra: str) -> list[str]:
    out = []
    for n in noticias:
        ficha = getattr(n, "ficha", None) or {}
        out.append(" ".join([n.titulo or "", n.cuerpo or "", json.dumps(ficha, ensure_ascii=False)]))
    return out + [extra or ""]


def _encontrar(dato: str, tipo: str, evidencias: list[str]) -> int | None:
    """Índice de la primera evidencia que contiene el dato, o None."""
    if tipo == "cifra":
        d = _digitos(dato)
        for i, ev in enumerate(evidencias):
            if d and d in {_digitos(x) for x in _NUMERO.findall(ev)}:
                return i
        return None
    buscado = _plano(dato)
    significativas = [p for p in re.findall(r"\w+", buscado) if len(p) > 3]
    for i, ev in enumerate(evidencias):
        e = _plano(ev)
        if buscado in e or (significativas and all(p in e for p in significativas)):
            return i
    return None


_SYSTEM = """\
Sos un verificador de datos. Te paso noticias y una lista de datos que aparecen en una nota.
Para cada dato decí si las noticias lo respaldan (el mismo hecho, aunque esté escrito distinto).
Un dato que no está en las noticias NO está respaldado, aunque sea verdad en el mundo.
Respondé solo con este JSON:
{"datos": [{"dato": "texto tal cual te lo pasé", "respaldado": true/false}]}"""


def _preguntar_al_modelo(pendientes: list[str], noticias, extra: str) -> dict[str, bool] | None:
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    bloques = []
    for i, n in enumerate(noticias, 1):
        ficha = getattr(n, "ficha", None)
        cuerpo = json.dumps(ficha, ensure_ascii=False) if ficha else (n.cuerpo or "")[:2500]
        bloques.append(f"[{i}] {n.titulo}\n{cuerpo}")
    if extra:
        bloques.append(f"[otros] {extra[:1500]}")
    user = "## Noticias\n" + "\n\n".join(bloques) + "\n\n## Datos a verificar\n" + "\n".join(f"- {d}" for d in pendientes)
    try:
        data = _extraer_json(llm.completar(_SYSTEM, user, temperature=0.0, max_tokens=1500, tarea="evaluacion"))
    except Exception as e:
        print(f"  [AVISO] No se pudo verificar con el modelo ({e}).", flush=True)
        return None
    resultado = {}
    for item in data.get("datos") or []:
        if isinstance(item, dict) and isinstance(item.get("dato"), str):
            resultado[_plano(item["dato"]).strip()] = item.get("respaldado") is True
    return resultado


def verificar(nota: str, noticias: list, extra: str = "", usar_modelo: bool = True) -> Verificacion:
    """Qué datos de la nota tienen respaldo en las noticias.

    `extra`: otro texto que vale como fuente (clientes indicados, tema pedido).
    """
    datos = extraer_datos(nota)
    v = Verificacion(total=len(datos))
    evidencias = _evidencias(noticias, extra)
    pendientes: list[tuple[str, str]] = []
    citadas = set()
    for dato, tipo in datos:
        i = _encontrar(dato, tipo, evidencias)
        if i is None:
            pendientes.append((dato, tipo))
        else:
            v.respaldados.append(dato)
            if i < len(noticias):
                citadas.add(i)
    respuesta = _preguntar_al_modelo([d for d, _ in pendientes], noticias, extra) if pendientes and usar_modelo else None
    if respuesta is not None:
        v.metodo = "literal+modelo"
    for dato, tipo in pendientes:
        veredicto = respuesta.get(_plano(dato).strip()) if respuesta is not None else None
        if veredicto is True:
            v.respaldados.append(dato)
        elif veredicto is False or tipo == "cifra":
            v.sin_respaldo.append(dato)
        else:
            v.dudosos.append(dato)
    v.noticias_citadas = sorted(citadas)
    return v


def pedido_de_correccion(v: Verificacion) -> str:
    return ("Estos datos no aparecen en las noticias de contexto: " + "; ".join(v.sin_respaldo)
            + ". Sacalos o reemplazalos por datos que sí estén en las noticias.")


# ── Enlaces y fuentes ─────────────────────────────────────────────────────────


def _normalizar_url(u: str) -> str:
    return (u or "").strip().rstrip("/").lower()


def _dominio(u: str) -> str:
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def sanear_enlaces(nota: str, noticias: list, permitidas: tuple[str, ...] = (),
                   dominios: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """Saca los links a URLs que no salen de las noticias ni de la lista permitida.

    Un modelo que inventa una URL deja un link roto (o peor, a otro sitio) en el
    blog. El texto del link queda; solo se quita el enlace.
    """
    exactas = {_normalizar_url(n.url) for n in noticias if n.url} | {_normalizar_url(u) for u in permitidas if u}
    doms = {d.lower().removeprefix("www.") for d in dominios if d}
    quitados = []

    def reemplazo(m: re.Match) -> str:
        texto, url = m.group(1), m.group(2)
        if _normalizar_url(url) in exactas:
            return m.group(0)
        dom = _dominio(url)
        if dom and any(dom == d or dom.endswith("." + d) for d in doms):
            return m.group(0)
        quitados.append(url)
        return texto

    return _LINK.sub(reemplazo, nota), quitados


def _escapar(titulo: str) -> str:
    """Título de noticia apto para el texto de un link Markdown."""
    return re.sub(r"([\\\[\]*_`])", r"\\\1", " ".join((titulo or "").split()))


def agregar_fuentes(nota: str, noticias: list, titulo: str = "Fuentes") -> str:
    """Agrega (o reemplaza) la sección de fuentes, antes de la meta description."""
    lineas = nota.rstrip().splitlines()
    # La meta va siempre última: se aparta antes de tocar las secciones.
    meta = []
    while lineas and not lineas[-1].strip():
        lineas.pop()
    if lineas and re.fullmatch(r"[*_]{1,2}[^*_].*?[*_]{1,2}", lineas[-1].strip()):
        meta = ["", lineas.pop()]
    # Si el modelo escribió su propia sección de fuentes, se saca: la buena es esta.
    propias = {_plano(titulo), "fuentes", "fontes", "sources", "referencias"}
    sin_propia, saltando = [], False
    for ln in lineas:
        if ln.startswith("## "):
            saltando = _plano(ln[3:]).strip() in propias
        if not saltando:
            sin_propia.append(ln)
    lineas = sin_propia
    while lineas and not lineas[-1].strip():
        lineas.pop()
    con_url = [n for n in noticias if n.url]
    bloque = ["", f"## {titulo}", ""] + [f"- [{_escapar(n.titulo)}]({n.url})" for n in con_url] if con_url else []
    return "\n".join(lineas + bloque + meta)


def urls_citadas(nota: str) -> set[str]:
    return {_normalizar_url(u) for _, u in _LINK.findall(nota)}
