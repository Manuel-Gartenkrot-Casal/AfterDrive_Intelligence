"""
discover_sources.py — Busca sitios de noticias del sector para sugerirlos como Fuentes.

Uso (lo encola "Buscar recomendaciones" en Fuentes):
    python -m afterdrive.ingesta.discover_sources

Interfaz:
    discover() -> {"guardadas", "motores_bloqueados", "errores"}
    dominio(url) -> str
    raiz(url) -> str

Dos caminos, y alcanza con que funcione uno:
1. Buscadores: Google Noticias (RSS), DuckDuckGo, DuckDuckGo Lite y Bing, en
   ese orden. El RSS de Google Noticias trae el sitio de cada medio y no pide
   captcha; los demás quedan de respaldo. Desde un
   servidor en la nube (Render, GitHub Actions) los buscadores suelen
   responder con un desafío anti-bots (DuckDuckGo devuelve 202) en vez de
   resultados: antes eso se contaba como "0 resultados" y la búsqueda
   terminaba "bien" sin encontrar nada. Ahora se detecta y se pasa al
   siguiente buscador.
2. La IA: se le piden medios del sector que conozca.

Primero se juntan los candidatos de todas las búsquedas y de la IA, sin filtrar
por palabras: un resultado no necesita nombrar "autopartes" para ser del
sector. Cada candidato suma POPULARIDAD según en cuántas búsquedas distintas
aparece (y si la IA también lo conoce): los medios que salen una y otra vez
son los que más se leen. Se verifican en ese orden, los más populares primero.

Todo sitio, venga de donde venga, se verifica entrando a su portada: tiene que
responder, tener notas enlazadas y que al menos MIN_PROPORCION_SECTOR de sus
titulares sean del sector. Si la portada es de un medio general, se prueban sus
secciones del sector ("/autos/", "/motor/") y se sugiere la que pase.
Lo que no se puede verificar no se sugiere.

RELEVANCIA: un titular es del sector por lo que dice, no por una palabra
literal. Se compara (embeddings) con titulares de referencia del rubro: los de
las noticias que ya se guardaron y unos fijos. El umbral se calibra solo con
esas referencias contra titulares de otros temas (política, deportes, recetas),
así no depende del modelo de embeddings. Las palabras del nicho siguen
contando, y sin embeddings son lo único que se mira (como antes).

Cada sugerencia guarda `relevancia` (parte de titulares del sector),
`popularidad` y `puntaje` (las dos juntas); el dashboard las lista por puntaje.

Si los dos caminos fallan, la corrida termina con error y un motivo claro.
"""

from __future__ import annotations

import datetime
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0 Safari/537.36")
_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Language": "es-AR,es;q=0.9,pt;q=0.8,en;q=0.7"}

# Palabras del nicho (sin tildes), como palabras enteras. Sin las ambiguas de antes: "filtro" (también
# "filtró"), "bateria" ("batería de medidas"), "suspension" ("de clases"), "talleres", "reposicion" y
# "frenos" metían diarios generales que después rechazaba la ingesta.
_KEYWORDS_NICHO = [
    "autopartes", "autopecas", "repuestos", "refacciones", "aftermarket", "automotriz", "automotrices",
    "automotor", "automotores", "automotivo", "automotiva", "taller mecanico", "talleres mecanicos",
    "oficina mecanica", "distribucion de repuestos", "amortiguadores?", "embragues?", "pastillas de freno",
    "neumaticos?", "pneus?", "lubricantes?", "posventa", "postventa", "pos-venda", "autopiezas",
    "auto parts", "reposicao automotiva", "mercado de reposicion",
]
_PATRON_NICHO = [(kw, re.compile(rf"\b{kw}\b")) for kw in _KEYWORDS_NICHO]

# Un sitio se sugiere si al menos esta parte de los titulares de su portada (o de la sección) es del
# sector y son al menos MIN_TITULARES_SECTOR: un diario general con una nota de repuestos no pasa.
MIN_PROPORCION_SECTOR = 0.25
MIN_TITULARES_SECTOR = 3
# Secciones de un medio general que valen la pena probar si su portada no pasa.
_SECCIONES = re.compile(r"autos?|motor|autopartes|repuestos|posventa|aftermarket|automotriz|automotor|"
                        r"fierros|vehiculos|movilidad|talleres|autopecas|automoveis|carros|veiculos")
_MAX_SECCIONES = 3

_BUSQUEDAS = [
    "noticias autopartes latinoamerica",
    "mercado de repuestos automotrices noticias",
    "aftermarket automotor noticias",
    "noticias posventa automotriz argentina",
    "notícias autopeças reposição brasil",
    "noticias refacciones automotrices mexico",
    "revista talleres mecanicos repuestos",
    "automotive aftermarket news latin america",
]

_MAX_SUGERENCIAS_TOTAL = 30
_MAX_IA = 15
_MAX_VERIFICAR = 45   # sitios que se visitan como mucho (los más populares primero)
POPULARIDAD_SATURA = 3   # en 3 búsquedas distintas (o 2 y la IA) la popularidad es máxima
PESO_RELEVANCIA = 0.6
PESO_POPULARIDAD = 0.4

# Titulares de referencia del sector (se suman a los de las noticias guardadas) y de otros temas,
# para calibrar cuándo un titular "suena" al sector sin depender de palabras exactas.
_REFERENCIAS_SECTOR = [
    "Crecen las ventas de repuestos en las casas de autopartes del país",
    "Distribuidoras de autopartes advierten por la falta de stock de amortiguadores",
    "Bosch presenta una nueva línea de bujías para el mercado de reposición",
    "El parque automotor envejece y sube la demanda de mantenimiento en talleres",
    "Lubricentros: cómo impacta la suba de precios de los aceites",
    "Fabricantes de neumáticos anuncian inversiones en su planta",
    "Mercado de reposição automotiva cresce no Brasil",
    "Distribuidores de autopeças apostam no e-commerce",
    "Oficinas mecânicas enfrentam falta de peças de suspensão",
    "Refaccionarias en México reportan alza en ventas de frenos",
    "Automotive aftermarket sales rise as vehicles age",
    "Parts distributors expand catalog data for online marketplaces",
]
_CONTROL_FUERA = [
    "El Congreso debate la reforma del sistema jubilatorio",
    "River y Boca empataron en un clásico sin goles",
    "Receta de torta de chocolate fácil y rápida",
    "Pronóstico: llega una ola de calor al centro del país",
    "Estreno de la nueva temporada de la serie más vista",
    "El dólar volvió a subir en la apertura de hoy",
    "Vacunación antigripal: quiénes deben aplicarse la dosis",
    "Los mejores destinos para viajar en vacaciones de invierno",
    "Câmara aprova projeto sobre educação básica",
    "Stock markets close higher on tech earnings",
]
_TITULARES_GUARDADOS = 40   # titulares de noticias ya guardadas que se suman a las referencias
_MAX_TITULARES_SITIO = 30   # titulares de cada sitio que se comparan

# Sitios que aparecen en las búsquedas pero no son fuentes de noticias del sector.
_DOMINIOS_EXCLUIDOS = (
    "youtube.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "linkedin.com", "wikipedia.org", "mercadolibre.", "mercadolivre.", "amazon.", "google.", "pinterest.",
    "reddit.com", "duckduckgo.com", "bing.com", "microsoft.com", "alephee.com",
)

_transporte = {"get": requests.get, "post": requests.post}   # seam para los tests
_dormir = time.sleep


class Bloqueado(RuntimeError):
    """El buscador respondió con un desafío anti-bots o un límite, no con resultados."""


@dataclass
class Resultado:
    url: str
    titulo: str = ""
    snippet: str = ""


def dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def raiz(url: str) -> str:
    """Una Fuente se sugiere por su sitio, no por la nota puntual que apareció en la búsqueda."""
    p = urlparse(url)
    return f"{p.scheme or 'https'}://{p.netloc}/"


def _excluido(dom: str) -> bool:
    return any(x in dom for x in _DOMINIOS_EXCLUIDOS)


def _plano(texto: str) -> str:
    return unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode()


def _keywords_en_texto(texto: str) -> list[str]:
    texto_l = _plano(texto)
    return [m.group(0) for _, patron in _PATRON_NICHO if (m := patron.search(texto_l))]


# ── Buscadores ────────────────────────────────────────────────────────────────

_SENALES_BLOQUEO = ("anomaly-modal", "anomaly.js", "captcha", "unusual traffic", "are you a robot",
                    "challenge-form", "bots use duckduckgo")


def _revisar(resp, motor: str) -> str:
    """El HTML de la respuesta, o Bloqueado si no son resultados."""
    if resp.status_code in (202, 403, 429, 503):
        raise Bloqueado(f"{motor} respondió {resp.status_code} (bloquea búsquedas automáticas desde servidores)")
    if resp.status_code >= 400:
        raise Bloqueado(f"{motor} respondió {resp.status_code}")
    html = resp.text or ""
    if any(s in html.lower() for s in _SENALES_BLOQUEO):
        raise Bloqueado(f"{motor} pidió un captcha (bloquea búsquedas automáticas desde servidores)")
    return html


def _url_ddg(href: str) -> str:
    if "duckduckgo.com/l/?" in href:
        return parse_qs(urlparse(href).query).get("uddg", [""])[0]
    return "https:" + href if href.startswith("//") else href


def _ddg(q: str) -> list[Resultado]:
    resp = _transporte["post"]("https://html.duckduckgo.com/html/", data={"q": q}, headers=_HEADERS, timeout=15)
    soup = BeautifulSoup(_revisar(resp, "DuckDuckGo"), "html.parser")
    resultados = []
    for r in soup.select(".result"):
        a = r.select_one("a.result__a")
        if a and a.get("href"):
            snippet = r.select_one(".result__snippet")
            resultados.append(Resultado(_url_ddg(a["href"]), a.get_text(strip=True),
                                        snippet.get_text(strip=True) if snippet else ""))
    return resultados


def _ddg_lite(q: str) -> list[Resultado]:
    resp = _transporte["post"]("https://lite.duckduckgo.com/lite/", data={"q": q}, headers=_HEADERS, timeout=15)
    soup = BeautifulSoup(_revisar(resp, "DuckDuckGo Lite"), "html.parser")
    links = soup.select("a.result-link")
    snippets = soup.select("td.result-snippet")
    return [Resultado(_url_ddg(a.get("href", "")), a.get_text(strip=True),
                      snippets[i].get_text(strip=True) if i < len(snippets) else "")
            for i, a in enumerate(links) if a.get("href")]


def _bing(q: str) -> list[Resultado]:
    resp = _transporte["get"](f"https://www.bing.com/search?q={quote_plus(q)}&setlang=es", headers=_HEADERS,
                              timeout=15)
    soup = BeautifulSoup(_revisar(resp, "Bing"), "html.parser")
    resultados = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if a and a.get("href", "").startswith("http"):
            p = li.select_one(".b_caption p") or li.select_one("p")
            resultados.append(Resultado(a["href"], a.get_text(strip=True), p.get_text(strip=True) if p else ""))
    return resultados


def _google_noticias(q: str) -> list[Resultado]:
    """Notas del RSS de Google Noticias; la URL es el sitio del medio (el link de la nota es una redirección)."""
    resp = _transporte["get"](
        f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=es-419&gl=AR&ceid=AR:es-419",
        headers=_HEADERS, timeout=15,
    )
    try:
        items = ET.fromstring(_revisar(resp, "Google Noticias")).findall("./channel/item")
    except ET.ParseError:
        return []
    resultados = []
    for item in items:
        fuente = item.find("source")
        if fuente is not None and fuente.get("url"):
            resultados.append(Resultado(fuente.get("url"), item.findtext("title", ""), (fuente.text or "").strip()))
    return resultados


MOTORES = [("Google Noticias", _google_noticias), ("DuckDuckGo", _ddg), ("DuckDuckGo Lite", _ddg_lite),
           ("Bing", _bing)]


def _buscar(q: str, bloqueados: dict) -> list[Resultado]:
    """Resultados del primer buscador que responda. Anota en `bloqueados` los que no."""
    for nombre, motor in MOTORES:
        if nombre in bloqueados:
            continue
        try:
            resultados = motor(q)
        except Bloqueado as e:
            print(f"  [BLOQUEADO] {e}. Se prueba con otro buscador.", flush=True)
            bloqueados[nombre] = str(e)
            continue
        except requests.RequestException as e:
            print(f"  [ERROR] {nombre}: {e}", flush=True)
            continue
        if resultados:
            print(f"  {len(resultados)} resultados en {nombre}", flush=True)
            return resultados
        print(f"  {nombre}: sin resultados.", flush=True)
    return []


# ── Sugerencias de la IA, verificadas ─────────────────────────────────────────

_SYSTEM_IA = """\
Conocés los medios del aftermarket automotor. Te piden sitios web de NOTICIAS del sector (autopartes, \
repuestos, posventa, talleres, distribución, neumáticos, lubricantes) en Argentina, Brasil, México y el \
resto de Latinoamérica, y medios internacionales del aftermarket. Solo medios o secciones de noticias que \
publiquen notas seguido: no tiendas, no fabricantes, no marketplaces, no redes sociales.

Respondé solo con este JSON (sitios reales que conozcas; si dudás de un dominio, no lo pongas):
{"sitios": [{"url": "https://dominio/", "nombre": "...", "pais": "..."}]}"""


def _sugeridos_por_ia(ya: set[str]) -> list[dict]:
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    excluir = ", ".join(sorted(ya)[:80]) or "ninguno"
    pedido = f"Dame hasta {_MAX_IA} sitios. Ya tenemos estos (no los repitas): {excluir}."
    crudo = llm.completar(_SYSTEM_IA, pedido, temperature=0.2, max_tokens=2500, tarea="clasificacion")
    data = _extraer_json(crudo)
    sitios = data.get("sitios") if isinstance(data, dict) else None
    if not isinstance(sitios, list):
        raise ValueError("la IA no devolvió la lista de sitios")
    return [s for s in sitios if isinstance(s, dict) and str(s.get("url", "")).startswith("http")][:_MAX_IA]


def _embeber(textos: list[str]) -> list | None:
    """Vectores de los textos, o None si los embeddings no están disponibles. Seam para los tests."""
    from afterdrive.ia import llm
    try:
        return llm.embeber(textos, tipo="passage")
    except Exception as e:
        print(f"  [AVISO] Sin embeddings para medir la relevancia ({e}): se miran solo las palabras.", flush=True)
        return None


def _norma(v):
    if not v:
        return None
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v] if n else None


def _producto(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


@dataclass
class Perfil:
    """Las referencias del sector (vectores normalizados) y el umbral calibrado."""
    referencias: list
    umbral: float

    def parecido(self, v, excluir: int | None = None) -> float:
        """Promedio de los 3 cosenos más altos contra las referencias."""
        if not v:
            return 0.0
        cos = sorted((_producto(v, r) for i, r in enumerate(self.referencias) if i != excluir), reverse=True)
        top = cos[:3]
        return sum(top) / len(top) if top else 0.0


def _mediana(xs: list[float]) -> float:
    xs = sorted(xs)
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _perfil_sector(base) -> Perfil | None:
    """Referencias del sector (fijas + titulares de las noticias guardadas) y su umbral, o None sin embeddings.

    Umbral: entre lo que puntúan las propias referencias (sacando cada una de la cuenta) y lo
    que puntúan titulares de otros temas; nunca por debajo de 4 de cada 5 de esos otros temas.
    """
    titulos = list(_REFERENCIAS_SECTOR)
    try:
        titulos += [d["titulo"] for d in base["articulos"].find({"titulo": {"$exists": True, "$ne": ""}}, {"titulo": 1})
                    .sort("_id", -1).limit(_TITULARES_GUARDADOS) if d.get("titulo")]
    except Exception as e:
        print(f"  [AVISO] No se pudieron leer las noticias guardadas para las referencias: {e}", flush=True)
    vectores = _embeber(titulos + _CONTROL_FUERA)
    if not vectores:
        return None
    refs = [v for v in (_norma(x) for x in vectores[:len(titulos)]) if v]
    fuera = [v for v in (_norma(x) for x in vectores[len(titulos):]) if v]
    if len(refs) < 5 or len(fuera) < 3:
        return None
    perfil = Perfil(refs, 0.0)
    dentro = [perfil.parecido(r, excluir=i) for i, r in enumerate(refs)]
    otros = sorted(perfil.parecido(v) for v in fuera)
    medio = (_mediana(dentro) + _mediana(otros)) / 2
    perfil.umbral = min(_mediana(dentro), max(medio, otros[int(0.8 * (len(otros) - 1))]))
    print(f"  Relevancia por significado: {len(refs)} titulares de referencia, umbral {perfil.umbral:.2f}.", flush=True)
    return perfil


def _titulares(html: str, url: str) -> dict[str, str]:
    """{link: texto} de las notas enlazadas en la página (los mismos links que seguiría el scraper)."""
    from urllib.parse import urljoin

    from afterdrive.ingesta import scraper

    links = set(scraper._encontrar_links(html, url))
    titulares = {}
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        destino = urljoin(url, a["href"].strip())
        if destino in links and destino not in titulares:
            titulares[destino] = a.get_text(" ", strip=True)
    return titulares


def _leer(url: str) -> tuple[str | None, str]:
    """(html, motivo si no se pudo)."""
    from afterdrive.ingesta import scraper

    if not scraper.url_publica(url):
        return None, "no es una URL pública o el dominio no existe"
    try:
        resp = _transporte["get"](url, headers=_HEADERS, timeout=15)
    except requests.RequestException as e:
        return None, f"no respondió ({e.__class__.__name__})"
    if resp.status_code >= 400:
        return None, f"respondió {resp.status_code}"
    return resp.text or "", ""


def _cuantos_del_sector(textos: list[str], perfil: Perfil | None) -> int:
    """Cuántos titulares son del sector: por las palabras del nicho o, con perfil, por lo que dicen."""
    por_palabras = [bool(_keywords_en_texto(t)) for t in textos]
    if perfil is None:
        return sum(por_palabras)
    vectores = _embeber(textos)
    if not vectores:
        return sum(por_palabras)
    return sum(p or (perfil.parecido(_norma(v)) >= perfil.umbral) for p, v in zip(por_palabras, vectores, strict=True))


def _del_sector(html: str, url: str, perfil: Perfil | None = None) -> tuple[bool, str, float]:
    """(ok, motivo, relevancia): la página tiene notas enlazadas y una buena parte de sus titulares
    es del sector. relevancia: la parte de titulares del sector (0 a 1)."""
    titulares = [t for t in _titulares(html, url).values() if t][:_MAX_TITULARES_SITIO]
    if len(titulares) < 3:
        return False, "no tiene notas enlazadas", 0.0
    del_sector = _cuantos_del_sector(titulares, perfil)
    proporcion = del_sector / len(titulares)
    if del_sector < MIN_TITULARES_SECTOR or proporcion < MIN_PROPORCION_SECTOR:
        if not del_sector:
            return False, "no habla del sector", 0.0
        return False, (f"solo {del_sector} de {len(titulares)} notas son del sector ({proporcion:.0%}): "
                       "es un medio general"), proporcion
    return True, "", proporcion


def _secciones(html: str, url: str) -> list[str]:
    """Links a secciones del mismo sitio que suenan al sector ("/autos/", "/motor/")."""
    from urllib.parse import urljoin

    secciones = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        destino = urljoin(url, a["href"].strip()).split("#")[0].split("?")[0]
        partes = [p for p in urlparse(destino).path.split("/") if p]
        if (dominio(destino) == dominio(url) and 1 <= len(partes) <= 2 and destino not in secciones
                and _SECCIONES.fullmatch(_plano(partes[-1]).replace("-", "")) is not None):
            secciones.append(destino if destino.endswith("/") else destino + "/")
    return secciones[:_MAX_SECCIONES]


@dataclass
class Evaluacion:
    ok: bool
    titulo: str = ""
    motivo: str = ""
    fuente: str = ""        # la página a scrapear: la portada o la sección del sector
    relevancia: float = 0.0


def _evaluar_sitio(url: str, perfil: Perfil | None = None) -> Evaluacion:
    """Responde, tiene notas y buena parte son del sector (con su relevancia).

    Si la portada es de un medio general, prueba sus secciones del sector (autos, motor,
    repuestos) y sugiere la primera que pase en vez de la portada.
    """
    html, motivo = _leer(url)
    if html is None:
        return Evaluacion(False, "", motivo, url)
    soup = BeautifulSoup(html, "html.parser")
    titulo = (soup.title.get_text(strip=True) if soup.title else "")[:150]
    ok, motivo, relevancia = _del_sector(html, url, perfil)
    if ok:
        return Evaluacion(True, titulo, "", url, relevancia)
    for seccion in _secciones(html, url):
        html_seccion, _ = _leer(seccion)
        if html_seccion:
            ok_s, _, relevancia_s = _del_sector(html_seccion, seccion, perfil)
            if ok_s:
                print(f"  La portada de {dominio(url)} es general: se sugiere su sección {seccion}", flush=True)
                return Evaluacion(True, titulo, "", seccion, relevancia_s)
    return Evaluacion(False, titulo, motivo, url, relevancia)


def _verificar_sitio(url: str, perfil: Perfil | None = None) -> tuple[bool, str, str, str]:
    """(ok, título, motivo, url a sugerir). Ver _evaluar_sitio."""
    e = _evaluar_sitio(url, perfil)
    return e.ok, e.titulo, e.motivo, e.fuente


# ── Recorrido ─────────────────────────────────────────────────────────────────


@dataclass
class Candidato:
    """Un sitio encontrado: dónde apareció y cuántas veces."""
    url: str
    titulo: str = ""
    snippet: str = ""
    busqueda: str = ""
    busquedas: set = field(default_factory=set)
    apariciones: int = 0
    ia: bool = False
    pais: str = ""

    @property
    def popularidad(self) -> float:
        """0 a 1: búsquedas distintas en las que aparece (y si la IA lo conoce), con un plus por repetirse."""
        menciones = len(self.busquedas) + (1 if self.ia else 0)
        extra = max(0, self.apariciones - len(self.busquedas)) * 0.25
        return min(1.0, (menciones + extra) / POPULARIDAD_SATURA)


def puntaje(relevancia: float, popularidad: float) -> float:
    """Relevancia (normalizada: con 60 % de titulares del sector ya es máxima) y popularidad juntas."""
    return round(PESO_RELEVANCIA * min(1.0, relevancia / 0.6) + PESO_POPULARIDAD * popularidad, 3)


def _sugerencia(c: Candidato, e: Evaluacion, origen: str) -> dict:
    url = c.url
    return {
        "url": e.fuente or raiz(url), "dominio": dominio(url), "ejemplo_url": url,
        "titulo": e.titulo if origen == "ia" and e.titulo else (c.titulo or e.titulo), "snippet": c.snippet or c.pais,
        "keyword_match": _keywords_en_texto(f"{c.titulo} {c.snippet} {e.titulo}"), "keyword_busqueda": c.busqueda,
        "origen": origen, "busquedas": len(c.busquedas), "sugerida_por_ia": c.ia,
        "relevancia": round(e.relevancia, 3), "popularidad": round(c.popularidad, 3),
        "puntaje": puntaje(e.relevancia, c.popularidad),
        "fecha_sugerida": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def _candidatos_de_busquedas(bloqueados: dict) -> dict[str, Candidato]:
    candidatos: dict[str, Candidato] = {}
    for q in _BUSQUEDAS:
        if len(bloqueados) == len(MOTORES):
            break
        print(f"\n--- Buscando: '{q}' ---", flush=True)
        for r in _buscar(q, bloqueados):
            dom = dominio(r.url)
            if not r.url.startswith("http") or not dom or _excluido(dom):
                continue
            c = candidatos.setdefault(dom, Candidato(r.url, r.titulo, r.snippet, q))
            c.busquedas.add(q)
            c.apariciones += 1
        _dormir(1)
    return candidatos


def discover(base=None) -> dict:
    if base is None:
        from afterdrive.db import db as base
    print("Buscando nuevas fuentes del sector...", flush=True)
    ya = {dominio(d["url"]) for d in base["trusted_urls"].find({}, {"url": 1})}
    ya |= {dominio(d["url"]) for d in base["suggested_urls"].find({}, {"url": 1})}
    bloqueados, errores = {}, []

    candidatos = _candidatos_de_busquedas(bloqueados)
    if len(bloqueados) == len(MOTORES):
        print("\n[AVISO] Todos los buscadores bloquearon la búsqueda desde este servidor.", flush=True)

    print("\n--- Pidiendo sugerencias a la IA (cada sitio se verifica) ---", flush=True)
    try:
        sugeridos = _sugeridos_por_ia(ya)
    except Exception as e:
        sugeridos = []
        errores.append(f"la IA no pudo sugerir sitios: {e}")
        print(f"  [AVISO] La IA no pudo sugerir sitios: {e}", flush=True)
    for s in sugeridos:
        url = raiz(str(s["url"]).strip())
        dom = dominio(url)
        if not dom or _excluido(dom):
            continue
        c = candidatos.setdefault(dom, Candidato(url, str(s.get("nombre") or "")))
        c.ia, c.pais = True, str(s.get("pais") or "")

    for dom in sorted(set(candidatos) & ya):
        print(f"  [SKIP] ya registrada: {dom}", flush=True)
    # Los más populares primero; entre iguales, los que ya nombran el sector en el resultado.
    pendientes = sorted((c for dom, c in candidatos.items() if dom not in ya),
                        key=lambda c: (-c.popularidad, not _keywords_en_texto(f"{c.titulo} {c.snippet}")))
    print(f"\n--- Verificando {min(len(pendientes), _MAX_VERIFICAR)} de {len(pendientes)} sitios candidatos ---",
          flush=True)
    perfil = _perfil_sector(base) if pendientes else None
    nuevas = []
    for c in pendientes[:_MAX_VERIFICAR]:
        if len(nuevas) >= _MAX_SUGERENCIAS_TOTAL:
            break
        dom = dominio(c.url)
        e = _evaluar_sitio(raiz(c.url), perfil)
        if not e.ok:
            print(f"  [DESCARTADA] {dom}: {e.motivo}", flush=True)
            continue
        origen = "buscador" if c.busquedas else "ia"
        sug = _sugerencia(c, e, origen)
        print(f"  [OK] {dom}: relevancia {e.relevancia:.0%}, en {len(c.busquedas)} búsqueda(s)"
              f"{' + IA' if c.ia else ''} → puntaje {sug['puntaje']:.2f}", flush=True)
        nuevas.append(sug)

    nuevas.sort(key=lambda n: -n["puntaje"])
    if nuevas:
        base["suggested_urls"].insert_many([dict(n) for n in nuevas])
        print(f"\n[OK] {len(nuevas)} sugerencias guardadas.", flush=True)
    else:
        print("\nNo se encontraron fuentes nuevas.", flush=True)
    return {"guardadas": len(nuevas), "motores_bloqueados": list(bloqueados.values()), "errores": errores}


def main() -> int:
    """Sale con 1 si no se pudo buscar por ningún camino: la corrida muestra el motivo."""
    r = discover()
    if not r["guardadas"] and len(r["motores_bloqueados"]) == len(MOTORES) and r["errores"]:
        print("[ERROR] No se pudo buscar: los buscadores bloquean las búsquedas desde el servidor y "
              f"{r['errores'][0]}.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
