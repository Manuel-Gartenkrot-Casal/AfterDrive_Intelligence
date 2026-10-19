"""
Servidor del dashboard para los tests e2e: la app real con Mongo en memoria.

    python -m tests.e2e.servidor 5077

Mongo se reemplaza por mongomock ANTES de importar la app (los módulos toman
las colecciones al importarse). El scraping y HubSpot son falsos: no sale
nada a internet salvo el CDN de marked/DOMPurify, que el navegador puede no
alcanzar (los tests lo cubren con un reemplazo mínimo).
"""

import os
import sys
import time

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient

from werkzeug.security import generate_password_hash  # noqa: E402

USUARIO, CLAVE = "admin", "e2e-clave-123"
os.environ.update(
    ADMIN_USER=USUARIO, ADMIN_PASSWORD_HASH=generate_password_hash(CLAVE), SECRET_KEY="e2e",
    AI_PROVIDER_OVERRIDE="1", AI_PROVIDER="local", MONGO_URI="mongodb://e2e",
    HUBSPOT_TOKEN="pat-e2e", HUBSPOT_BLOG_ID="123",
)

from afterdrive import corridas, hubspot  # noqa: E402
from afterdrive import db as dbm  # noqa: E402

CUERPO = "## Qué pasó\n\n" + "El mercado de repuestos crece y los distribuidores ajustan su stock. " * 8


def sembrar() -> None:
    dbm.col_trusted_urls.insert_many([
        {"url": "https://fuente-uno.com/noticias", "estado": "activo", "fecha_agregado": "2026-10-01T00:00:00+00:00"},
        {"url": "https://fuente-dos.com/blog", "estado": "inactivo", "fecha_agregado": "2026-10-02T00:00:00+00:00"},
    ])
    dbm.col_clientes.insert_one({"slug": "acme", "nombre": "ACME Autopartes"})
    dbm.db.notas_fase2.insert_many([
        {"contenido": "# Frenos: la demanda sube\n\n" + CUERPO + "\n*La demanda de frenos crece.*",
         "generado_en": "2026-10-17T14:00:00+00:00", "estado": "borrador", "categorias": ["autopartes"],
         "calidad": {"puntaje": 8, "fallas_criticas": [], "intentos": 1, "reescrita_por": []},
         "evaluacion": {"lineamientos": {"estructura_correcta": True}, "comentarios": "Bien"}},
        {"contenido": "# Marketplaces y catálogo\n\n" + CUERPO, "generado_en": "2026-10-16T14:00:00+00:00",
         "estado": "aprobada", "categorias": ["marketplaces"],
         "evaluacion": {"lineamientos": {}, "comentarios": "Evaluación de prueba"}},
    ])
    dbm.db.articulos.insert_many(
        [{"url": f"https://s.com/{i}", "titulo": f"Noticia {i}", "cuerpo": "Texto. " * 20} for i in range(3)])


def scraping_falso(max_articulos):
    for i in range(2):
        print(f"Scrapeando: fuente {i}", flush=True)
        time.sleep(0.3)
    print("  [OK] 2 nuevos artículos aprobados.", flush=True)
    return {"success": True, "aprobados": 2}


class _Resp:
    status_code = 200

    def __init__(self, estado):
        self._estado = estado

    def json(self):
        return {"id": "555", "url": "https://blog.e2e/nota", "state": self._estado, "results": []}


def hubspot_falso() -> None:
    def post(url, json=None, headers=None, timeout=None, params=None):
        return _Resp(json.get("state", "DRAFT") if json else "DRAFT")
    hubspot._transporte = {"post": post, "patch": post, "get": post}


if __name__ == "__main__":
    sembrar()
    corridas._scrapear_fuentes = scraping_falso
    hubspot_falso()
    from afterdrive import flask_api, scheduler
    scheduler.iniciar()
    flask_api.app.run(host="127.0.0.1", port=int(sys.argv[1]), threaded=True)
