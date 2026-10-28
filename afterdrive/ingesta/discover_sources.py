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
2. La IA: se le piden medios del sector que conozca y cada uno se verifica
   entrando al sitio (responde, habla del sector y tiene notas enlazadas).
   Lo que no se puede verificar no se sugiere.

Si los dos caminos fallan, la corrida termina con error y un motivo claro.
"""

from __future__ import annotations

import datetime
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0 Safari/537.36")
_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Language": "es-AR,es;q=0.9,pt;q=0.8,en;q=0.7"}

# Palabras del nicho (sin tildes): un resultado o un sitio tiene que nombrar alguna.
_KEYWORDS_NICHO = [
    "autopartes", "autopecas", "repuestos", "refacciones", "aftermarket", "automotriz", "automotor",
    "automotivo", "taller mecanico", "talleres", "oficina mecanica", "distribucion de repuestos", "frenos",
    "filtro", "amortiguador", "embrague", "pastillas de freno", "neumatico", "pneu", "lubricante",
    "bateria", "suspension", "reposicion", "posventa", "pos-venda", "autopiezas", "auto parts",
]

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
    return [kw for kw in _KEYWORDS_NICHO if kw in texto_l]


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


def _verificar_sitio(url: str) -> tuple[bool, str, str]:
    """(ok, título del sitio, motivo): responde, habla del sector y tiene notas enlazadas."""
    from afterdrive.ingesta import scraper

    if not scraper.url_publica(url):
        return False, "", "no es una URL pública o el dominio no existe"
    try:
        resp = _transporte["get"](url, headers=_HEADERS, timeout=15)
    except requests.RequestException as e:
        return False, "", f"no respondió ({e.__class__.__name__})"
    if resp.status_code >= 400:
        return False, "", f"respondió {resp.status_code}"
    html = resp.text or ""
    soup = BeautifulSoup(html, "html.parser")
    titulo = (soup.title.get_text(strip=True) if soup.title else "")[:150]
    descripcion = soup.find("meta", attrs={"name": "description"})
    texto = f"{titulo} {descripcion.get('content', '') if descripcion else ''} {soup.get_text(' ', strip=True)[:4000]}"
    if not _keywords_en_texto(texto):
        return False, titulo, "no habla del sector"
    if len(scraper._encontrar_links(html, url)) < 3:
        return False, titulo, "no tiene notas enlazadas en la portada"
    return True, titulo, ""


# ── Recorrido ─────────────────────────────────────────────────────────────────


def _sugerencia(url: str, titulo: str, snippet: str, matches: list[str], origen: str, busqueda: str = "") -> dict:
    return {
        "url": raiz(url), "dominio": dominio(url), "ejemplo_url": url, "titulo": titulo, "snippet": snippet,
        "keyword_match": matches, "keyword_busqueda": busqueda, "origen": origen,
        "fecha_sugerida": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def discover(base=None) -> dict:
    if base is None:
        from afterdrive.db import db as base
    print("Buscando nuevas fuentes del sector...", flush=True)
    ya = {dominio(d["url"]) for d in base["trusted_urls"].find({}, {"url": 1})}
    ya |= {dominio(d["url"]) for d in base["suggested_urls"].find({}, {"url": 1})}
    vistas, nuevas, bloqueados, errores = set(), [], {}, []

    for q in _BUSQUEDAS:
        if len(nuevas) >= _MAX_SUGERENCIAS_TOTAL or len(bloqueados) == len(MOTORES):
            break
        print(f"\n--- Buscando: '{q}' ---", flush=True)
        for r in _buscar(q, bloqueados):
            dom = dominio(r.url)
            if not r.url.startswith("http") or not dom or dom in vistas or _excluido(dom):
                continue
            vistas.add(dom)
            if dom in ya:
                print(f"  [SKIP] ya registrada: {dom}", flush=True)
                continue
            matches = _keywords_en_texto(f"{r.titulo} {r.snippet}")
            if matches:
                print(f"  [OK] {dom}: {r.titulo[:60]}", flush=True)
                nuevas.append(_sugerencia(r.url, r.titulo, r.snippet, matches, "buscador", q))
            if len(nuevas) >= _MAX_SUGERENCIAS_TOTAL:
                break
        _dormir(1)

    if len(bloqueados) == len(MOTORES):
        print("\n[AVISO] Todos los buscadores bloquearon la búsqueda desde este servidor.", flush=True)

    print("\n--- Pidiendo sugerencias a la IA (cada sitio se verifica) ---", flush=True)
    try:
        candidatos = _sugeridos_por_ia(ya | vistas)
    except Exception as e:
        candidatos = []
        errores.append(f"la IA no pudo sugerir sitios: {e}")
        print(f"  [AVISO] La IA no pudo sugerir sitios: {e}", flush=True)
    for s in candidatos:
        if len(nuevas) >= _MAX_SUGERENCIAS_TOTAL:
            break
        url = raiz(str(s["url"]).strip())
        dom = dominio(url)
        if not dom or dom in ya or dom in vistas or _excluido(dom):
            continue
        vistas.add(dom)
        ok, titulo, motivo = _verificar_sitio(url)
        if not ok:
            print(f"  [DESCARTADA] {dom}: {motivo}", flush=True)
            continue
        print(f"  [OK] {dom}: {titulo[:60]}", flush=True)
        nuevas.append(_sugerencia(url, titulo or str(s.get("nombre") or ""), str(s.get("pais") or ""),
                                  _keywords_en_texto(titulo), "ia"))

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
