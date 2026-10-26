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

from tests.e2e.credenciales import CLAVE, USUARIO  # noqa: E402

os.environ.update(
    ADMIN_USER=USUARIO, ADMIN_PASSWORD_HASH=generate_password_hash(CLAVE), SECRET_KEY="e2e",
    AI_PROVIDER_OVERRIDE="1", AI_PROVIDER="local", MONGO_URI="mongodb://e2e",
    HUBSPOT_TOKEN="pat-e2e", HUBSPOT_BLOG_PRUEBAS="123",
    # API paga configurada (a una URL falsa) para poder prender el modo pago.
    PAGA_API_KEY="pg-e2e", PAGA_BASE_URL="http://127.0.0.1:9/v1", PAGA_MODEL="modelo-e2e",
    NVIDIA_API_KEY="nvapi-e2e",
    # Las traducciones correrían en un subprocess que no ve la base en memoria.
    HUBSPOT_TRADUCCIONES="0",
)

from afterdrive import corridas, hubspot  # noqa: E402
from afterdrive import db as dbm  # noqa: E402

FOTO_E2E = "https://s.com/fotos/catalogo.jpg"
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
         "fuentes": [{"titulo": "Mercado Libre suma catálogo", "url": "https://s.com/ml", "imagen": FOTO_E2E,
                      "imagen_apta": True, "imagen_motivo": "Un depósito de repuestos."},
                     {"titulo": "Banner de una feria", "url": "https://s.com/feria", "imagen": "https://s.com/fotos/banner.jpg",
                      "imagen_apta": False, "imagen_motivo": "Es un banner publicitario."},
                     {"titulo": "Sin foto", "url": "https://s.com/sin"}],
         "evaluacion": {"lineamientos": {}, "comentarios": "Evaluación de prueba"}},
        {"contenido": "# Rotación de stock en el mostrador\n\n" + CUERPO + "\n*La rotación manda.*",
         "generado_en": "2026-10-15T14:00:00+00:00", "estado": "aprobada", "categorias": ["autopartes"],
         "persona": "comercial", "proveedor": "openrouter",
         "hubspot": {"id": "555", "url": "https://blog.e2e/nota", "estado": "DRAFT"},
         "notas_blog_sugeridas": [{"titulo": "Catálogo y fitment", "url": "https://afterdrive.alephee.com/es/blog/catalogo",
                                   "origen": "blog"}],
         "notas_blog_citadas": [{"titulo": "Catálogo y fitment", "url": "https://afterdrive.alephee.com/es/blog/catalogo",
                                 "origen": "blog"}],
         "imagen_eleccion": {"metodo": "ia", "motivo": "La IA descartó todas las fotos. Es un logo."},
         "critica": {"puntaje": 6, "fecha": "2026-10-15T14:05:00+00:00", "idioma": "es",
                     "resumen": "El gancho es concreto, pero mezcla voseo y tuteo y repite la misma idea.",
                     "aspectos": {"gramatica": 8, "redaccion": 5, "tono": 4, "estructura": 7},
                     "errores": [
                         {"tipo": "tono", "fragmento": "Descubre cómo ordenar el stock",
                          "problema": "Tutea en una nota con voseo.", "sugerencia": "Descubrí cómo ordenar el stock"},
                         {"tipo": "redaccion", "fragmento": "los distribuidores ajustan su stock",
                          "problema": "La misma oración se repite ocho veces.", "sugerencia": "Decirlo una vez y sumar un dato."},
                         {"tipo": "ortografia", "fragmento": "mas rotación", "problema": "Falta la tilde.",
                          "sugerencia": "más rotación"},
                         {"tipo": "estructura", "fragmento": "La rotación manda.",
                          "problema": "El cierre no deja una acción concreta.", "sugerencia": ""}]},
         "traducciones": {"pt": {"contenido": "# Giro de estoque no balcão\n\nTexto em português.", "huella": "x"}},
         "hubspot_traducciones": {"pt": {"id": "556", "url": "https://blog.e2e/pt/nota", "estado": "DRAFT", "vinculada": True},
                                  "en": {"error": "la traducción al inglés vino cortada"}},
         "calidad": {"puntaje": 7, "fallas_criticas": [], "intentos": 2, "reescrita_por": ["datos_sin_respaldo"],
                     "problemas": ["datos_sin_respaldo"], "segundo_intento": "correccion"},
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
        {"contenido": "# Baterías en el mostrador\n\n" + CUERPO, "generado_en": "2026-10-14T14:00:00+00:00",
         "estado": "aprobada", "categorias": ["autopartes"],
         "imagen": {"url": "https://s.com/fotos/bateria.jpg", "alt": "Batería",
                    "origen": {"titulo": "Baterías al alza", "url": "https://s.com/bat"}},
         "imagenes_cuerpo": [
             {"url": "https://s.com/fotos/deposito.jpg", "alt": "Depósito",
              "origen": {"titulo": "Depósitos llenos", "url": "https://s.com/dep"}},
             {"url": "https://s.com/fotos/mostrador.jpg", "alt": "Mostrador",
              "origen": {"titulo": "El mostrador vende más", "url": "https://s.com/mos"}}]},
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


# PNG de 1x1: la "foto de la noticia" que se copia a HubSpot, sin salir a internet.
PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def descarga_de_imagenes_falsa() -> None:
    import base64

    from afterdrive import imagen_web
    from afterdrive.ingesta import scraper

    class _RespImagen:
        status_code = 200
        headers = {"Content-Type": "image/png"}

        def iter_content(self, n):
            yield base64.b64decode(PNG_1X1)

    scraper.url_publica = lambda url: True
    imagen_web._transporte["get"] = lambda url, **kw: _RespImagen()


AUTORES_E2E = [{"id": "37798507784", "fullName": "Gaston Zelerteins", "language": "es"},
               {"id": "191488460449", "fullName": "Ana Dias", "language": "es"},
               {"id": "192900528951", "fullName": "Ana Dias", "language": "pt"}]


class _RespArchivo:
    status_code = 200

    def json(self):
        return {"url": "https://f.hubspot.e2e/nota.png"}


def hubspot_falso() -> None:
    class _RespAutores(_Resp):
        def json(self):
            return {"results": AUTORES_E2E}

    def post(url, json=None, headers=None, timeout=None, params=None):
        return _Resp(json.get("state", "DRAFT") if json else "DRAFT")

    def get(url, **kw):
        return _RespAutores("DRAFT") if url == hubspot.API_AUTORES else post(url)
    hubspot._transporte = {"post": post, "patch": post, "get": get,
                           "subir": lambda url, **kw: _RespArchivo()}


if __name__ == "__main__":
    sembrar()
    corridas._scrapear_fuentes = scraping_falso
    hubspot_falso()
    descarga_de_imagenes_falsa()
    from afterdrive import flask_api, scheduler
    scheduler.iniciar()
    flask_api.app.run(host="127.0.0.1", port=int(sys.argv[1]), threaded=True)
