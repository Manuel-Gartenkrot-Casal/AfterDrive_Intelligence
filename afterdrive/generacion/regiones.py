"""
regiones.py — Clasificación geográfica del contenido AfterDrive.

Regiones importantes:
    argentina, brasil, mexico, latinoamerica, europa, china, asia

Clasifica notas reales y filtra ejemplos para la generación usando
heurísticas por keywords normalizadas (minúsculas y sin acentos).
"""

import unicodedata
import re

REGIONES = {
    "argentina": "Argentina",
    "brasil": "Brasil",
    "mexico": "México",
    "latinoamerica": "Latinoamérica",
    "europa": "Europa",
    "china": "China",
    "asia": "Asia",
}

REGION_SLUGS = list(REGIONES.keys())

# Keywords clave por región (se buscan normalizadas, sin tildes)
_KEYWORDS = {
    "argentina": [
        "argentina", "argentino", "argentinos", "argentinas",
        "buenos aires", "cordoba", "rosario", "mendoza",
        "peso argentino", "pesos", "provincia de",
    ],
    "brasil": [
        "brasil", "brasilen", "brasileira", "brasilera",
        "sao paulo", "rio de janeiro", "parana", "santa catarina",
        "rio grande do sul", "real", "reales",
    ],
    "mexico": [
        "mexico", "mexicana", "mexicano", "mexicanos",
        "cdmx", "ciudad de mexico", "jalisco", "nuevo leon",
    ],
    "latinoamerica": [
        "latinoamerica", "latinoamericano", "latinoamericanos",
        "latinoamericana", "america latina", "latam", "iberoamerica",
        "region", "la region", "america del sur", "centroamerica",
    ],
    "europa": [
        "europa", "europeo", "europea", "europeos",
        "aleman", "alemania", "espana", "espanol", "espanola",
        "francia", "frances", "italia", "italiano", "reino unido",
        "union europea", "portugal",
    ],
    "china": [
        "china", "chino", "chinos", "china",
        "pekin", "beijing", "shanghai",
    ],
    "asia": [
        "asia", "asiat", "japon", "japones", "japonesa",
        "corea", "surcorean", "korea", "india", "indio",
        "tailandia", "vietnam",
    ],
}


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes para matching robusto."""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower()


_PATRON = re.compile(r"\b[a-z0-9\s-]+\b")


def clasificar_region(titulo: str, cuerpo: str) -> list[str]:
    """
    Clasifica una nota en una o más regiones según las keywords del texto.

    Returns:
        lista de slugs de regiones detectadas (ordenadas por relevancia).
    """
    texto_norm = _normalizar(f"{titulo} {cuerpo}")
    puntajes: dict[str, int] = {}

    for region, keywords in _KEYWORDS.items():
        score = 0
        for kw in keywords:
            kw_norm = _normalizar(kw)
            score += len(re.findall(re.escape(kw_norm), texto_norm)) * (1 if kw_norm not in ("real", "reales") else 1)
        if score > 0:
            puntajes[region] = score

    if not puntajes:
        return []

    top = max(puntajes.values())
    # Regiones con al menos 40% del puntaje máximo (permite multi-región)
    umbral = max(1, int(top * 0.4))
    ordenadas = sorted(
        [r for r, s in puntajes.items() if s >= umbral],
        key=lambda r: puntajes[r],
        reverse=True,
    )
    return ordenadas


def region_principal(slugs: list[str] | None) -> str:
    """Devuelve el slug de la región principal o vacío."""
    if not slugs:
        return ""
    return slugs[0]