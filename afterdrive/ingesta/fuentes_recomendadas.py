"""
fuentes_recomendadas.py — Fuentes para notas enfocadas en Alephee: marketplaces, e-commerce
automotor y material propio de Alephee.

Interfaz:
    RECOMENDADAS                         [{"url", "titulo", "tema"}]
    sembrar(base=None) -> int            las suma a Fuentes > Recomendadas (sin repetir sitios)

    python -m afterdrive.ingesta.fuentes_recomendadas

No entran directo como fuentes confiables: quedan en Recomendadas para que el
equipo las revise y las agregue con un clic. Al agregarlas, la app las prueba y
clasifica como a cualquier fuente; si la portada anuncia un RSS o la URL es un
sitemap, el scraper lee las notas de ahí (feeds.py). Las direcciones no se
pudieron verificar desde donde se escribió este archivo: revisarlas al agregarlas.
"""

from __future__ import annotations

import datetime

ORIGEN = "alephee"

RECOMENDADAS = [
    {"url": "https://alephee.com", "titulo": "Alephee", "tema": "material propio de Alephee"},
    {"url": "https://www.marketplacepulse.com", "titulo": "Marketplace Pulse",
     "tema": "marketplaces: Mercado Libre, Amazon y otros"},
    {"url": "https://www.ecommercebrasil.com.br", "titulo": "E-Commerce Brasil",
     "tema": "e-commerce y marketplaces en Brasil"},
    {"url": "https://www.americaretail.com", "titulo": "América Retail",
     "tema": "retail y e-commerce en Latinoamérica"},
    {"url": "https://www.aftermarketnews.com", "titulo": "aftermarketNews",
     "tema": "aftermarket automotor y venta online de autopartes"},
    {"url": "https://www.autocare.org/news", "titulo": "Auto Care Association",
     "tema": "aftermarket automotor: datos de catálogo y e-commerce"},
    {"url": "https://www.oficinabrasil.com.br", "titulo": "Oficina Brasil", "tema": "aftermarket automotor en Brasil"},
]


def sembrar(base=None) -> int:
    """Suma a Recomendadas las que todavía no son fuentes ni están recomendadas. Devuelve cuántas."""
    from afterdrive.ingesta.discover_sources import dominio, raiz

    if base is None:
        from afterdrive.db import db as base
    ya = {dominio(d["url"]) for d in base["trusted_urls"].find({}, {"url": 1})}
    ya |= {dominio(d["url"]) for d in base["suggested_urls"].find({}, {"url": 1})}
    ahora = datetime.datetime.now(datetime.UTC).isoformat()
    nuevas = [{
        "url": f["url"], "dominio": dominio(f["url"]), "ejemplo_url": raiz(f["url"]), "titulo": f["titulo"],
        "snippet": f"Recomendada para notas de Alephee: {f['tema']}.", "keyword_match": [], "keyword_busqueda": "",
        "origen": ORIGEN, "fecha_sugerida": ahora,
    } for f in RECOMENDADAS if dominio(f["url"]) not in ya]
    if nuevas:
        base["suggested_urls"].insert_many(nuevas)
    return len(nuevas)


def main() -> int:
    n = sembrar()
    print(f"[OK] {n} fuente(s) sumadas a Recomendadas." if n else "Ya estaban todas las fuentes recomendadas.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
