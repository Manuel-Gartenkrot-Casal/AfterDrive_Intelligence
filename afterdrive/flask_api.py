import os
import re
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

from afterdrive import auth, cola, config_store, scheduler
from afterdrive.db import col_articulos, db
from afterdrive.ia import llm, modo_pago

# Aplicar el proveedor elegido en el dashboard (y el modo pago, si quedó
# prendido). llm lee AI_PROVIDER y MODO_PAGO_HASTA en cada llamada y los
# subprocesos heredan os.environ, así que alcanza con setearlos.
try:
    _p = config_store.get_provider_config()
    if _p and not os.getenv("AI_PROVIDER_OVERRIDE"):
        os.environ["AI_PROVIDER"] = _p
except Exception:
    pass
if not os.getenv("AI_PROVIDER_OVERRIDE"):
    modo_pago.restaurar()

app = Flask(__name__)
auth.init_app(app)

# 'unsafe-inline' en scripts y estilos: el dashboard es un solo HTML con
# <script>, <style> y onclick en línea. Sacarlo exige reescribir ese archivo.
_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
])
_CABECERAS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": _CSP,
}


@app.after_request
def _cabeceras_de_seguridad(resp):
    for clave, valor in _CABECERAS.items():
        resp.headers.setdefault(clave, valor)
    if os.getenv("RENDER"):  # solo en producción, donde siempre hay HTTPS
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp

# Dashboard estático. En la imagen Docker vive en static/; en local, sin build,
# se sirve directo desde la fuente (express/src/public).
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC_DIR = os.path.join(_RAIZ, "static")
if not os.path.isdir(_STATIC_DIR):
    _STATIC_DIR = os.path.join(_RAIZ, "express", "src", "public")


# ── Endpoint Raíz ──────────────────────────────────────────────────────────────


@app.route("/")
def root():
    """Sin sesión entrega solo la pantalla de login: el dashboard ni se descarga."""
    archivo = "index.html" if auth.hay_sesion() else "login.html"
    if not os.path.isfile(os.path.join(_STATIC_DIR, archivo)):
        return jsonify({"status": "online", "service": "After Drive Intelligence API"}), 200
    resp = send_from_directory(_STATIC_DIR, archivo)
    # Sin caché: que "atrás" después de salir no muestre el dashboard.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/ayuda")
def ayuda():
    """Documentación dentro de la app. Sin sesión, al login."""
    from flask import redirect
    if not auth.hay_sesion():
        return redirect("/")
    resp = send_from_directory(_STATIC_DIR, "ayuda.html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# Documentos que se pueden leer desde Ayuda: lista blanca (el slug llega del
# navegador). slug -> (archivo relativo a la raíz, título, grupo).
DOCUMENTOS = {
    "guia-de-uso": ("docs/guia-de-uso.md", "Guía de uso", "Usar la aplicación"),
    "glosario": ("CONTEXT.md", "Glosario", "Usar la aplicación"),
    "indice": ("docs/README.md", "Índice técnico", "Documentación técnica"),
    "01-arquitectura": ("docs/01-arquitectura.md", "Arquitectura", "Documentación técnica"),
    "02-instalacion": ("docs/02-instalacion.md", "Instalación", "Documentación técnica"),
    "03-pipelines": ("docs/03-pipelines.md", "Pipelines", "Documentación técnica"),
    "04-ia": ("docs/04-ia.md", "IA", "Documentación técnica"),
    "05-base-de-datos": ("docs/05-base-de-datos.md", "Base de datos", "Documentación técnica"),
    "06-dashboard": ("docs/06-dashboard.md", "Dashboard", "Documentación técnica"),
    "07-api": ("docs/07-api.md", "API", "Documentación técnica"),
    "08-despliegue": ("docs/08-despliegue.md", "Despliegue", "Documentación técnica"),
    "09-deuda-y-mejoras": ("docs/09-deuda-y-mejoras.md", "Deuda y mejoras", "Documentación técnica"),
    "hubspot-integration": ("docs/hubspot-integration.md", "HubSpot", "Documentación técnica"),
}


@app.route("/api/docs", methods=["GET"])
def listar_docs():
    return jsonify({"success": True, "documentos": [
        {"slug": s, "titulo": t, "grupo": g} for s, (a, t, g) in DOCUMENTOS.items()
        if os.path.isfile(os.path.join(_RAIZ, a))
    ]})


@app.route("/api/docs/<slug>", methods=["GET"])
def leer_doc(slug: str):
    if slug not in DOCUMENTOS:
        return jsonify({"success": False, "error": "Documento no encontrado."}), 404
    archivo, titulo, _ = DOCUMENTOS[slug]
    try:
        with open(os.path.join(_RAIZ, archivo), encoding="utf-8") as f:
            texto = f.read()
    except OSError:
        return jsonify({"success": False, "error": "Documento no disponible en este servidor."}), 404
    return jsonify({"success": True, "slug": slug, "titulo": titulo, "markdown": texto})


@app.route("/assets/<path:archivo>")
def assets(archivo: str):
    """CSS y JS del dashboard. Piden sesión (la guardia de auth.py), como el dashboard.

    no-cache: el navegador revalida con el ETag, así un deploy nuevo se ve sin
    tener que forzar la recarga.
    """
    if not archivo.endswith((".css", ".js")):
        return jsonify({"success": False, "error": "Recurso no encontrado"}), 404
    resp = send_from_directory(os.path.join(_STATIC_DIR, "assets"), archivo)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ── Manejadores Globales de Errores ────────────────────────────────────────────


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"success": False, "error": "Recurso no encontrado"}), 404


@app.errorhandler(500)
def internal_error(_error):
    return jsonify({"success": False, "error": "Error interno del servidor"}), 500

def _error_interno(e: Exception, status: int = 500, **extra):
    """Loguea el detalle en el servidor y responde un mensaje genérico.

    El texto de la excepción no viaja al cliente: suele traer hosts internos
    y detalles de Mongo.
    """
    print(f"[API ERROR] {request.path}: {e!r}", flush=True)
    return jsonify({"success": False, "error": "Error interno del servidor", **extra}), status


def _lista_texto(valor) -> list[str] | None:
    """Lista de textos apta para el argv de un subproceso, o None si no lo es.

    Un elemento que empiece con "-" sería leído por argparse como otra opción
    (p. ej. colar "--puntapie" dentro de las categorías).
    """
    if valor is None:
        return []
    if not isinstance(valor, list) or not all(isinstance(v, str) and v and not v.startswith("-") for v in valor):
        return None
    return valor


def _listas(body: dict, *claves: str):
    """(listas por clave, None), o (None, respuesta 400) si alguna no es válida."""
    listas = {}
    for clave in claves:
        listas[clave] = _lista_texto(body.get(clave))
        if listas[clave] is None:
            return None, (jsonify({"success": False, "error": f"Parámetro '{clave}' inválido."}), 400)
    return listas, None


def _url_publica_o_400(body: dict):
    """(url, None), o (None, respuesta 400) si no es una URL http(s) pública."""
    from afterdrive.ingesta.scraper import url_publica

    url = body.get("url")
    url = url.strip() if isinstance(url, str) else ""
    if not url:
        return None, (jsonify({"success": False, "error": "Se requiere la URL."}), 400)
    if not url_publica(url):
        return None, (jsonify({"success": False, "error": "La URL debe ser http(s) y pública."}), 400)
    return url, None


# ── Endpoints de Gestión de Datos ────────────────────────────────────────────────


@app.route("/health")
def health():
    """Health check de la plataforma (healthCheckPath de Render).

    Se mantiene mínimo y sin dependencias externas a propósito: si consultara
    MongoDB o el proveedor de IA, una caída de esos servicios haría que Render
    considere el contenedor no sano y lo reinicie en bucle.
    """
    return jsonify({"status": "ok"})


@app.route("/api/health")
def api_health():
    """Health check que consume el dashboard.

    Devuelve la forma anidada que el dashboard espera: chequea
    `scrapers.status === 'ok'`, herencia de cuando un proxy Express respondía
    {express, scrapers}. Sin esa clave la comprobación lanza excepción y el
    badge queda en "Sin Conexion" de forma permanente.
    """
    return jsonify({"status": "ok", "express": "ok", "scrapers": {"status": "ok"}})


@app.route("/api/db-check", methods=["GET"])
def db_check():
    """Diagnóstico de conexión a MongoDB y estado de URLs confiables."""
    from afterdrive.db import MONGO_URI, col_trusted_urls, uri_segura

    uri_log = uri_segura(MONGO_URI)
    try:
        total = col_trusted_urls.count_documents({})
        activas = col_trusted_urls.count_documents({"estado": "activo"})
        muestra = [
            {"url": d.get("url"), "estado": d.get("estado")}
            for d in col_trusted_urls.find({}, {"url": 1, "estado": 1, "_id": 0}).limit(5)
        ]
        return jsonify({
            "success": True,
            "mongo_uri_preview": uri_log,
            "trusted_urls_total": total,
            "trusted_urls_activas": activas,
            "muestra": muestra,
        })
    except Exception as e:
        return _error_interno(e, mongo_uri_preview=uri_log)


@app.route("/api/articulos-stats", methods=["GET"])
def articulos_stats():
    """Cantidad de artículos guardados, para la tarjeta 'Artículos en DB'."""
    try:
        return jsonify({"success": True, "total": col_articulos.count_documents({})})
    except Exception as e:
        return _error_interno(e)


# ── Configuración de scraping y generación ────────────────────────────────────


@app.route("/api/scraping-config", methods=["GET"])
def get_scraping_config():
    cfg = config_store.get_scraping_config()
    return jsonify({
        "success": True,
        "interval_days": cfg["interval_days"],
        "max_articulos": cfg["max_articulos"],
        "hora": cfg["hora"],
        "zona": scheduler.ZONA,
        "next_execution": scheduler.proximas()["scraping"],
        "enabled": cfg["enabled"],
    })


def _entero_valido(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= 1


_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_ERROR_HORA = "Se requiere 'hora' en formato HH:MM (24 h)."


def _hora_valida(valor) -> bool:
    return isinstance(valor, str) and bool(_HORA.match(valor))


@app.route("/api/scraping-config", methods=["POST"])
def set_scraping_config():
    body = request.get_json(silent=True) or {}
    days = body.get("interval_days")
    max_art = body.get("max_articulos")
    enabled = body.get("enabled")
    hora = body.get("hora")

    if days is not None and not _entero_valido(days):
        return jsonify({"success": False, "error": "Se requiere 'interval_days' como un entero >= 1."}), 400
    if max_art is not None and not _entero_valido(max_art):
        return jsonify({"success": False, "error": "Se requiere 'max_articulos' como un entero >= 1."}), 400
    if hora is not None and not _hora_valida(hora):
        return jsonify({"success": False, "error": _ERROR_HORA}), 400

    config_store.set_scraping_config(enabled=enabled, interval_days=days, max_articulos=max_art, hora=hora)
    scheduler.aplicar()

    msg_parts = []
    if hora is not None:
        msg_parts.append(f"hora {hora}")
    if days is not None:
        msg_parts.append(f"intervalo a {days} día(s)")
    if max_art is not None:
        msg_parts.append(f"max artículos a {max_art}")
    if enabled is not None:
        msg_parts.append("scraping " + ("habilitado" if enabled else "deshabilitado"))
    message = "Configuración actualizada: " + ", ".join(msg_parts) if msg_parts else "Sin cambios"

    return jsonify({"success": True, "message": message})


_LARGOS = ("corto", "medio", "largo")   # redaccion.LARGOS, sin importar el módulo de prompts acá


@app.route("/api/generacion-config", methods=["GET"])
def get_generacion_config():
    cfg = config_store.get_generacion_config()
    return jsonify({**cfg, "success": True, "zona": scheduler.ZONA, "next_execution": scheduler.proximas()["generacion"]})


@app.route("/api/generacion-config", methods=["POST"])
def set_generacion_config():
    body = request.get_json(silent=True) or {}
    persona = body.get("persona")
    days = body.get("interval_days")
    hora = body.get("hora")

    if persona is not None and persona not in ("analitico", "periodistico", "comercial", "divulgativo", "ejecutivo"):
        return jsonify({"success": False, "error": "Persona inválida."}), 400
    largo = body.get("largo")
    if largo is not None and largo not in _LARGOS:
        return jsonify({"success": False, "error": "Largo inválido: corto, medio o largo."}), 400
    if days is not None and not _entero_valido(days):
        return jsonify({"success": False, "error": "Se requiere 'interval_days' como un entero >= 1."}), 400
    if hora is not None and not _hora_valida(hora):
        return jsonify({"success": False, "error": _ERROR_HORA}), 400

    config_store.set_generacion_config(
        enabled=body.get("enabled"),
        interval_days=days,
        persona=persona,
        tema=body.get("tema"),
        puntapie_url=body.get("puntapie_url"),
        hora=hora,
        largo=largo,
    )
    scheduler.aplicar()
    return jsonify({"success": True, "message": "Configuración de generación actualizada."})


@app.route("/api/fase2/config", methods=["GET"])
def get_fase2_config():
    return jsonify({"success": True, **config_store.get_fase2_config()})


@app.route("/api/fase2/config", methods=["POST"])
def set_fase2_config():
    """Guarda la config de la Nota automática. Solo cambia las claves que vienen."""
    body = request.get_json(silent=True) or {}
    presentes = [c for c in ("categorias", "regiones", "clientes") if c in body]
    listas, error = _listas(body, *presentes)
    if error:
        return error
    activo = body.get("puntapie_activo")
    if activo is not None and not isinstance(activo, bool):
        return jsonify({"success": False, "error": "Parámetro 'puntapie_activo' inválido."}), 400
    puntapie_url = body.get("puntapie_url")
    if puntapie_url is not None:
        if not isinstance(puntapie_url, str):
            return jsonify({"success": False, "error": "Parámetro 'puntapie_url' inválido."}), 400
        puntapie_url = puntapie_url.strip()
        if puntapie_url:
            _, error = _url_publica_o_400({"url": puntapie_url})
            if error:
                return error
    cfg = config_store.set_fase2_config(
        categorias=listas.get("categorias"),
        regiones=listas.get("regiones"),
        clientes=listas.get("clientes"),
        puntapie_activo=activo,
        puntapie_url=puntapie_url,
    )
    return jsonify({"success": True, **cfg})


def _encolar(tipo: str, params: dict | None = None, origen: str = "manual", etiqueta: str | None = None):
    """202 con el id y la posición en la Cola, o 429 si la cola está llena."""
    try:
        r = cola.encolar(tipo, params, origen=origen, etiqueta=etiqueta)
    except cola.ColaLlena as e:
        return jsonify({"success": False, "error": str(e)}), 429
    return jsonify({"success": True, **r}), 202


def _origen() -> str:
    """cron si la llamada vino con el token de las corridas automáticas."""
    return "cron" if request.headers.get("Authorization", "").startswith("Bearer ") else "manual"


@app.route("/api/run-automation", methods=["POST"])
def run_automation():
    """Encola el scraping de URLs confiables."""
    return _encolar("scraping", origen=_origen())


@app.route("/api/run-generacion", methods=["POST"])
def run_generacion():
    """Encola la generación de una Nota Fase 2 con la config guardada."""
    return _encolar("generacion", origen=_origen())


# ── Historial y revisión de notas ─────────────────────────────────────────────
# La lógica vive en historial.py; acá solo se traducen parámetros y errores.


@app.route("/api/historial/resumen", methods=["GET"])
def historial_resumen():
    from afterdrive import historial
    try:
        return jsonify({"success": True, **historial.resumen()})
    except Exception as e:
        return _error_interno(e)


@app.route("/api/historial/<seccion>", methods=["GET"])
def historial_listar(seccion: str):
    from afterdrive import historial
    try:
        datos = historial.listar(
            seccion,
            pagina=request.args.get("pagina", 1, type=int),
            por_pagina=request.args.get("por_pagina", 20, type=int),
            q=request.args.get("q", ""),
            estado=request.args.get("estado", "todos"),
        )
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return _error_interno(e)
    return jsonify({"success": True, **datos})


@app.route("/api/historial/<seccion>/<coleccion>/<item_id>", methods=["GET"])
def historial_detalle(seccion: str, coleccion: str, item_id: str):
    from afterdrive import historial
    try:
        item = historial.detalle(seccion, coleccion, item_id)
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return _error_interno(e)
    if item is None:
        return jsonify({"success": False, "error": "No encontrado."}), 404
    return jsonify({"success": True, "item": item})


@app.route("/api/historial/estado", methods=["POST"])
def historial_estado():
    from afterdrive import historial, hubspot
    body = request.get_json(silent=True) or {}
    try:
        item = historial.cambiar_estado(body.get("coleccion", ""), body.get("id", ""), body.get("estado", ""),
                                        motivo=body.get("motivo"))
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except hubspot.ErrorHubSpot as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        return _error_interno(e)
    if item is None:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    return jsonify({"success": True, "item": item})


@app.route("/api/historial/contenido", methods=["PATCH"])
def historial_editar():
    from afterdrive import historial
    body = request.get_json(silent=True) or {}
    try:
        item = historial.editar(body.get("coleccion", ""), body.get("id", ""), body.get("contenido"))
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return _error_interno(e)
    if item is None:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    return jsonify({"success": True, "item": item})


@app.route("/api/historial/calificacion", methods=["POST"])
def historial_calificar():
    """Calificación de una Nota: {"coleccion", "id", "puntaje": 1-5, "etiquetas": [...], "comentario"}."""
    from afterdrive import calibracion

    body = request.get_json(silent=True) or {}
    try:
        cal = calibracion.calificar(body.get("coleccion", ""), body.get("id", ""), body.get("puntaje"),
                                    body.get("etiquetas") or [], body.get("comentario") or "")
    except calibracion.ErrorCalibracion as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if cal is None:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    return jsonify({"success": True, "calificacion": cal})


@app.route("/api/calibracion", methods=["GET"])
def calibracion_resumen():
    """Lo que la generación aprendió de las calificaciones, rechazos y ediciones."""
    from afterdrive import calibracion

    try:
        return jsonify({"success": True, **calibracion.resumen()})
    except Exception as e:
        return jsonify({"success": False, "error": f"No se pudo leer la calibración: {e}"}), 500


@app.route("/api/historial/imagen/generar", methods=["POST"])
def historial_generar_imagen():
    """Genera la imagen destacada con NVIDIA: {"coleccion", "id", "descripcion" (opcional)}."""
    from afterdrive import historial

    body = request.get_json(silent=True) or {}
    try:
        item = historial.generar_imagen(body.get("coleccion", ""), body.get("id", ""), body.get("descripcion") or "")
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if item is None:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    return jsonify({"success": True, "item": item})


@app.route("/api/imagenes/<imagen_id>", methods=["GET"])
def ver_imagen(imagen_id: str):
    """Una imagen generada, para el dashboard (HubSpot recibe la suya subida a sus archivos)."""
    from flask import Response

    from afterdrive import imagenes
    datos = imagenes.leer(imagen_id)
    if not datos:
        return jsonify({"success": False, "error": "Imagen no encontrada."}), 404
    contenido, mime = datos
    return Response(contenido, mimetype=mime, headers={"Cache-Control": "private, max-age=86400"})


@app.route("/api/historial/imagen", methods=["PATCH"])
def historial_imagen():
    """{coleccion, id, url, alt}: imagen destacada de una nota (url vacía la saca)."""
    from afterdrive import historial
    body = request.get_json(silent=True) or {}
    try:
        item = historial.cambiar_imagen(body.get("coleccion", ""), body.get("id", ""), body.get("url", ""), body.get("alt", ""))
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return _error_interno(e)
    if item is None:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    return jsonify({"success": True, "item": item})


@app.route("/api/historial/vista-previa/<coleccion>/<item_id>", methods=["GET"])
def historial_vista_previa(coleccion: str, item_id: str):
    from afterdrive import historial
    try:
        previa = historial.vista_previa(coleccion, item_id)
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return _error_interno(e)
    if previa is None:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    return jsonify({"success": True, **previa})


@app.route("/api/hubspot/estado", methods=["GET"])
def hubspot_estado():
    from afterdrive import hubspot
    return jsonify({"success": True, "configurado": hubspot.configurado()})


@app.route("/api/hubspot/enviar", methods=["POST"])
def hubspot_enviar():
    """Envía una nota aprobada a HubSpot: {"coleccion", "id", "publicar": bool}."""
    from afterdrive import historial, hubspot
    body = request.get_json(silent=True) or {}
    try:
        item = historial.enviar_a_hubspot(body.get("coleccion", ""), body.get("id", ""), body.get("publicar") is True)
    except historial.ErrorHistorial as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except hubspot.ErrorHubSpot as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        return _error_interno(e)
    if item is None:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    return jsonify({"success": True, "item": item})


# ── Cola de Corridas ──────────────────────────────────────────────────────────


@app.route("/api/corridas", methods=["GET"])
def listar_corridas():
    try:
        return jsonify({"success": True, **cola.listar()})
    except Exception as e:
        return _error_interno(e)


@app.route("/api/corridas/<id_>/log", methods=["GET"])
def log_corrida(id_: str):
    desde = request.args.get("desde", "0")
    r = cola.log(id_, int(desde) if desde.isdigit() else 0)
    if r is None:
        return jsonify({"success": False, "error": "Corrida no encontrada."}), 404
    return jsonify({"success": True, **r})


@app.route("/api/corridas/<id_>/cancelar", methods=["POST"])
def cancelar_corrida(id_: str):
    try:
        return jsonify({"success": True, **cola.cancelar(id_)})
    except KeyError:
        return jsonify({"success": False, "error": "Corrida no encontrada."}), 404
    except cola.NoCancelable as e:
        return jsonify({"success": False, "error": str(e)}), 409


@app.route("/api/corridas/scraping", methods=["POST"])
def encolar_scraping():
    return _encolar("scraping")


@app.route("/api/corridas/generacion", methods=["POST"])
def encolar_generacion():
    """Encola una Nota Fase 2 con los parámetros del formulario (no los guardados)."""
    argv, error = _argv_generar(request.get_json(silent=True) or {})
    if error:
        return error
    return _encolar("script", {"modulo": "afterdrive.generacion.generar_nota_fase2", "argv": argv},
                    etiqueta="Generar nota")


@app.route("/api/corridas/probar-fuente", methods=["POST"])
def encolar_probar_fuente():
    """Encola 'Probar y agregar': scrapea la URL y la da de alta si aprueba algún artículo."""
    url, error = _url_publica_o_400(request.get_json(silent=True) or {})
    if error:
        return error
    from urllib.parse import urlparse
    return _encolar("script", {"modulo": "afterdrive.ingesta.add_url", "argv": [url]},
                    etiqueta=f"Probar fuente {urlparse(url).netloc}")


@app.route("/api/corridas/recomendaciones", methods=["POST"])
def encolar_recomendaciones():
    return _encolar("script", {"modulo": "afterdrive.ingesta.discover_sources", "argv": []},
                    etiqueta="Buscar recomendaciones")


@app.route("/api/corridas/ejemplos", methods=["POST"])
def encolar_ejemplos():
    argv, error = _args_scrape(request.get_json(silent=True) or {})
    if error:
        return error
    return _encolar("script", {"modulo": "afterdrive.generacion.scraper_afterdrive", "argv": argv},
                    etiqueta="Sincronizar ejemplos")


@app.route("/api/trusted-urls-stats", methods=["GET"])
def trusted_urls_stats():
    """Estadísticas de las URLs confiables y última ejecución."""
    try:
        total = db["trusted_urls"].count_documents({})
        activas = db["trusted_urls"].count_documents({"estado": "activo"})
        ultima = db["trusted_urls"].find_one({"ultima_ejecucion": {"$exists": True}}, sort=[("ultima_ejecucion", -1)])
        return jsonify(
            {
                "success": True,
                "total": total,
                "activas": activas,
                "ultima_ejecucion": ultima.get("ultima_ejecucion") if ultima else None,
            }
        )
    except Exception as e:
        return _error_interno(e)


@app.route("/api/evaluate-article", methods=["POST"])
def evaluate_article():
    body = request.get_json(silent=True) or {}
    articulo = body.get("articulo", "")
    if not articulo:
        return jsonify({"success": False, "error": "Se requiere el contenido del artículo."}), 400

    # Si el articulo tiene wrapper JSON (ej: "articulo": "markdown..."), limpiarlo
    m = re.search(r'"articulo"\s*:\s*"(.+)"\s*}', articulo, re.DOTALL)
    if m:
        articulo = m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
    articulo = articulo.lstrip("`").lstrip("markdown").strip()

    from afterdrive.ia.lm_studio import evaluar_lineamientos

    resultado = evaluar_lineamientos(articulo)

    if "error" in resultado:
        return jsonify({"success": False, "error": resultado["error"]}), 500

    return jsonify({"success": True, "evaluation": resultado})


# ── Endpoint: Proveedores de IA ───────────────────────────────────────────────


@app.route("/api/providers", methods=["GET"])
def get_providers():
    """Estado actual del proveedor de IA y disponibilidad."""
    return jsonify({"success": True, **llm.estado()})


@app.route("/api/providers", methods=["POST"])
def set_provider():
    """Cambiar proveedor de IA (local / nvidia / openrouter / paga)."""
    body = request.get_json(silent=True) or {}
    provider = body.get("provider", "")
    if not provider:
        return jsonify({"success": False, "error": "Se requiere el campo 'provider'."}), 400

    result = llm.set_proveedor(provider)
    if result.get("success"):
        config_store.set_provider_config(provider)
        if provider != "paga" and modo_pago.vigente():
            # Elegir otro proveedor a mano es más explícito que el modo pago: lo apaga.
            modo_pago.desactivar()
            result = {"success": True, **llm.estado()}
    return jsonify(result), 200 if result["success"] else 400


@app.route("/api/modo-pago", methods=["POST"])
def set_modo_pago():
    """Prende o apaga el modo API paga (como máximo un día). Body: {"activo": bool}."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("activo"), bool):
        return jsonify({"success": False, "error": "Se requiere el campo 'activo' (true o false)."}), 400
    result = modo_pago.activar() if body["activo"] else modo_pago.desactivar()
    if result.get("success"):
        result = {"success": True, **llm.estado()}
    return jsonify(result), 200 if result["success"] else 400


@app.route("/api/suggested-urls", methods=["GET"])
def suggested_urls():
    """Fuentes recomendadas: una por sitio, sin las que ya son confiables."""
    from afterdrive.ingesta.discover_sources import dominio

    try:
        confiables = {dominio(d["url"]) for d in db["trusted_urls"].find({}, {"url": 1})}
        vistas, urls = set(), []
        for d in db["suggested_urls"].find({}, {"_id": 0}).sort("fecha_sugerida", -1):
            dom = d.get("dominio") or dominio(d.get("url", ""))
            if not dom or dom in confiables or dom in vistas:
                continue
            vistas.add(dom)
            urls.append({**d, "dominio": dom})
            if len(urls) >= 20:
                break
        return jsonify({"success": True, "urls": urls})
    except Exception as e:
        return _error_interno(e)


@app.route("/api/suggested-urls", methods=["DELETE"])
def descartar_suggested_url():
    """Descarta una recomendación (todas las de ese sitio)."""
    from afterdrive.ingesta.discover_sources import dominio

    body = request.get_json(silent=True) or {}
    dom = dominio(body.get("url", ""))
    if not dom:
        return jsonify({"success": False, "error": "Se requiere la URL."}), 400
    pattern = re.escape(dom)
    db["suggested_urls"].delete_many({"$or": [
        {"dominio": dom},
        {"url": {"$regex": rf"^https?://(www\.)?{pattern}(/|$)"}},
    ]})
    return jsonify({"success": True})


@app.route("/api/trusted-urls", methods=["GET"])
def list_trusted_urls():
    """Lista todas las URLs confiables registradas."""
    from afterdrive.db import col_trusted_urls
    try:
        docs = list(col_trusted_urls.find({}, {"_id": 0}).sort("fecha_agregado", -1))
        return jsonify({"success": True, "urls": docs, "total": len(docs)})
    except Exception as e:
        return _error_interno(e)


@app.route("/api/trusted-urls", methods=["POST"])
def add_trusted_url_direct():
    """Agrega una URL directamente a trusted_urls sin pasar por el clasificador."""
    import datetime

    from afterdrive.db import col_trusted_urls
    body = request.get_json(silent=True) or {}
    url, error = _url_publica_o_400(body)
    if error:
        return error
    nombre = str(body.get("nombre") or "").strip()
    try:
        col_trusted_urls.update_one(
            {"url": url},
            {"$set": {
                "url": url,
                "nombre_fuente": nombre or url,
                "estado": "activo",
                "fecha_agregado": datetime.datetime.now(datetime.UTC).isoformat(),
                "ultima_ejecucion": None,
            }},
            upsert=True,
        )
        return jsonify({"success": True, "message": f"URL '{url}' agregada como activa."})
    except Exception as e:
        return _error_interno(e)


@app.route("/api/trusted-urls/<path:url>", methods=["PATCH"])
def set_estado_trusted_url(url):
    """Pausa o reactiva una Fuente confiable sin borrarla."""
    from afterdrive.db import col_trusted_urls
    estado = (request.get_json(silent=True) or {}).get("estado")
    if estado not in ("activo", "inactivo"):
        return jsonify({"success": False, "error": "Se requiere 'estado': 'activo' o 'inactivo'."}), 400
    try:
        result = col_trusted_urls.update_one({"url": url}, {"$set": {"estado": estado}})
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "URL no encontrada."}), 404
        return jsonify({"success": True, "estado": estado})
    except Exception as e:
        return _error_interno(e)


@app.route("/api/trusted-urls/<path:url>", methods=["DELETE"])
def delete_trusted_url(url):
    """Elimina una URL confiable. Para dejar de scrapearla sin perderla, PATCH con estado."""
    from afterdrive.db import col_trusted_urls
    try:
        result = col_trusted_urls.delete_one({"url": url})
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "URL no encontrada."}), 404
        return jsonify({"success": True, "message": "URL eliminada."})
    except Exception as e:
        return _error_interno(e)


# ── Fase 2: Endpoints ─────────────────────────────────────────────────────────


@app.route("/api/fase2/categorias", methods=["GET"])
def fase2_categorias():
    from afterdrive.generacion.scraper_afterdrive import CATEGORIAS, get_categorias_disponibles
    todas = [{"slug": slug, "nombre": nombre} for slug, nombre in CATEGORIAS.items()]
    disponibles = {r["_id"]: r["total"] for r in get_categorias_disponibles()}
    for cat in todas:
        cat["ejemplos"] = disponibles.get(cat["slug"], 0)
    return jsonify({"success": True, "categorias": todas})


@app.route("/api/fase2/regiones", methods=["GET"])
def fase2_regiones():
    from afterdrive.generacion.regiones import REGIONES
    from afterdrive.generacion.scraper_afterdrive import get_regiones_disponibles
    disponibles = {r["_id"]: r["total"] for r in get_regiones_disponibles()}
    todas = [{"slug": slug, "nombre": nombre, "ejemplos": disponibles.get(slug, 0)} for slug, nombre in REGIONES.items()]
    return jsonify({"success": True, "regiones": todas})


def _args_scrape(body: dict):
    """(argv del scraper de ejemplos, None), o (None, respuesta 400)."""
    listas, error = _listas(body, "tags")
    if error:
        return None, error
    max_por_tag = body.get("max", 5)
    if not _entero_valido(max_por_tag):
        return None, (jsonify({"success": False, "error": "Se requiere 'max' como un entero >= 1."}), 400)
    tags = listas["tags"]
    return (["--tags", *tags] if tags else []) + [f"--max={max_por_tag}"], None


@app.route("/api/fase2/clientes", methods=["GET"])
def fase2_get_clientes():
    from afterdrive.db import col_clientes
    docs = list(col_clientes.find({}, {"_id": 0, "embedding": 0}))
    return jsonify({"success": True, "clientes": docs})


@app.route("/api/fase2/clientes", methods=["POST"])
def fase2_crear_cliente():
    from afterdrive.db import col_clientes
    body = request.get_json(silent=True) or {}
    nombre = body.get("nombre", "").strip()
    if not nombre:
        return jsonify({"success": False, "error": "Se requiere 'nombre'."}), 400
    doc = {
        "slug": re.sub(r"[^a-z0-9]+", "-", nombre.lower()).strip("-"),
        "nombre": nombre,
        "descripcion": body.get("descripcion", ""),
        "productos": body.get("productos", []),
        "sector": body.get("sector", ""),
        "url": body.get("url", ""),
    }
    col_clientes.update_one({"slug": doc["slug"]}, {"$set": doc}, upsert=True)
    return jsonify({"success": True, "cliente": doc})


@app.route("/api/fase2/clientes/<slug>", methods=["DELETE"])
def fase2_eliminar_cliente(slug: str):
    from afterdrive.db import col_clientes
    col_clientes.delete_one({"slug": slug})
    return jsonify({"success": True})


def _argv_generar(body: dict):
    """(argv de generar_nota_fase2, None), o (None, respuesta 400)."""
    listas, error = _listas(body, "categorias", "clientes", "regiones")
    if error:
        return None, error
    if not listas["categorias"]:
        return None, (jsonify({"success": False, "error": "Se requiere al menos una categoría."}), 400)
    puntapie_url = body.get("puntapie_url", "") or ""
    persona = body.get("persona", "comercial")
    tema = body.get("tema", "") or ""
    largo = body.get("largo") or ""
    if largo and largo not in _LARGOS:
        return None, (jsonify({"success": False, "error": "Largo inválido: corto, medio o largo."}), 400)

    extra = []
    for clave in ("categorias", "clientes", "regiones"):
        if listas[clave]:
            extra += [f"--{clave}", *listas[clave]]
    # Escalares como "--opcion=valor": argparse nunca los toma por otra opción.
    if puntapie_url:
        extra.append(f"--puntapie={puntapie_url}")
    if persona:
        extra.append(f"--persona={persona}")
    if tema:
        extra.append(f"--tema={tema}")
    if largo:
        extra.append(f"--largo={largo}")
    return extra, None


@app.route("/api/fase2/ultima-nota", methods=["GET"])
def fase2_ultima_nota():
    from afterdrive.generacion.generar_nota_fase2 import get_ultima_nota
    doc = get_ultima_nota()
    if not doc:
        return jsonify({"success": False, "error": "No hay notas generadas aún."}), 404
    doc["_id"] = str(doc["_id"])
    doc.pop("embedding", None)
    return jsonify({"success": True, "nota": doc})


@app.route("/api/fase2/notas/<nota_id>", methods=["GET"])
def fase2_nota(nota_id: str):
    from bson import ObjectId
    from bson.errors import InvalidId

    from afterdrive.generacion.generar_nota_fase2 import col_notas_fase2
    try:
        doc = col_notas_fase2.find_one({"_id": ObjectId(nota_id)})
    except InvalidId:
        doc = None
    if not doc:
        return jsonify({"success": False, "error": "Nota no encontrada."}), 404
    doc["_id"] = str(doc["_id"])
    doc.pop("embedding", None)
    return jsonify({"success": True, "nota": doc})


def _keep_alive():
    """Mantiene despierta la instancia de Render (free tier).

    Render apaga el contenedor tras ~15 min SIN tráfico EXTERNO a la URL
    pública. Un ping a localhost nunca sale del contenedor y no cuenta como
    actividad, así que hay que pegarle a la URL pública que Render inyecta en
    $RENDER_EXTERNAL_URL (ej: https://afterdrive-intelligence.onrender.com).

    Esto reduce el spin-down pero no lo elimina al 100%: para garantía total,
    un monitor externo (UptimeRobot, cron-job.org) debe pegar a /health cada
    5-10 min. Sin instancia despierta, el scheduler de APScheduler no ejecuta
    el scraping diario a la hora programada.
    """
    import urllib.request

    def _base_url() -> str | None:
        ext = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        if ext:
            return ext
        # Fallback local de desarrollo: apuntar a la URL pública configurada.
        public = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if public:
            return public
        return None

    intervalo_s = 300  # 5 min: bajo el umbral de ~15 min de inactividad de Render
    while True:
        time.sleep(intervalo_s)
        base = _base_url()
        if not base:
            print("[keep-alive] Sin RENDER_EXTERNAL_URL/PUBLIC_BASE_URL, skip.", flush=True)
            continue
        url = f"{base}/health"
        try:
            urllib.request.urlopen(url, timeout=10)
        except Exception as e:
            print(f"[keep-alive] Ping a {url} falló: {e}", flush=True)


def _start_keep_alive():
    t = threading.Thread(target=_keep_alive, daemon=True)
    t.start()


if __name__ == "__main__":
    scheduler.iniciar()
    _start_keep_alive()

    PORT = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=PORT, threaded=True)
else:
    # Gunicorn: iniciar scheduler solo en el worker principal para evitar duplicados.
    # Con --workers 1 esto solo corre una vez; con múltiples workers usamos una flag
    # de entorno por proceso para que solo el primero en importar lo inicie.
    import multiprocessing
    if multiprocessing.current_process().name in ("MainProcess", "SpawnProcess-1") \
            or os.getenv("_SCHEDULER_STARTED") != "1":
        os.environ["_SCHEDULER_STARTED"] = "1"
        scheduler.iniciar()
        _start_keep_alive()
