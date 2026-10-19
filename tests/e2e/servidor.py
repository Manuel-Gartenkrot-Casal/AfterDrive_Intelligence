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
    # API paga configurada (a una URL falsa) para poder prender el modo pago.
    PAGA_API_KEY="pg-e2e", PAGA_BASE_URL="http://127.0.0.1:9/v1", PAGA_MODEL="modelo-e2e",
    NVIDIA_API_KEY="nvapi-e2e", IMAGENES_AUTOMATICAS="0",
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
        {"contenido": "# Rotación de stock en el mostrador\n\n" + CUERPO + "\n*La rotación manda.*",
         "generado_en": "2026-10-15T14:00:00+00:00", "estado": "aprobada", "categorias": ["autopartes"],
         "persona": "comercial", "proveedor": "openrouter",
         "calidad": {"puntaje": 7, "fallas_criticas": [], "intentos": 2, "reescrita_por": ["datos_sin_respaldo"],
                     "problemas": ["datos_sin_respaldo"], "segundo_intento": "correccion"},
         "imagen_error": "NVIDIA respondió 500 al generar la imagen",
         "costo": {"total_usd": 0.231, "por_tarea": {"redaccion": 0.18, "correccion": 0.02, "planificacion": 0.031},
                   "llamadas": 6, "estimado": False},
         "verificacion": {"total": 3, "respaldados": ["Frasle", "15%"], "sin_respaldo": ["US$ 80 millones"],
                          "dudosos": [], "metodo": "literal+modelo", "noticias_citadas": [0]},
         "estilo": [{"codigo": "anglicismos", "detalle": "Anglicismos con equivalente en español: \"feedback\"",
                     "grave": False}],
         "seo": {"titulo_caracteres": 35, "meta_caracteres": 19, "palabra_clave": "rotación de stock",
                 "preguntas_frecuentes": 2, "enlaces_internos": 1, "enlaces": 3, "palabras": 120},
         "plan": {"angulo": "La rotación define el margen", "titulo": "Rotación de stock",
                  "palabra_clave": "rotación de stock", "implicancias": [],
                  "secciones": [{"titulo": "Qué pasó", "idea": "x", "noticias": [1]},
                                {"titulo": "Qué cambia", "idea": "y", "noticias": []}]}},
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


# PNG de 1x1: NVIDIA falso para generar imágenes sin salir a internet.
PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def nvidia_falso() -> None:
    from afterdrive import imagenes

    class _RespImagen:
        status_code = 200
        text = ""

        def json(self):
            return {"artifacts": [{"base64": PNG_1X1, "finishReason": "SUCCESS"}]}

    imagenes._transporte = {"post": lambda url, **kw: _RespImagen()}


def hubspot_falso() -> None:
    def post(url, json=None, headers=None, timeout=None, params=None):
        return _Resp(json.get("state", "DRAFT") if json else "DRAFT")
    hubspot._transporte = {"post": post, "patch": post, "get": post}


if __name__ == "__main__":
    sembrar()
    corridas._scrapear_fuentes = scraping_falso
    hubspot_falso()
    nvidia_falso()
    from afterdrive import flask_api, scheduler
    scheduler.iniciar()
    flask_api.app.run(host="127.0.0.1", port=int(sys.argv[1]), threaded=True)
