import os
import re
import threading
import time

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS

from afterdrive import config_store
from afterdrive import corridas
from afterdrive.ia import llm
from afterdrive import scheduler
from afterdrive.db import col_articulos, db

# Aplicar el proveedor elegido en el dashboard. llm lee AI_PROVIDER en cada
# llamada y los subprocesos heredan os.environ, así que alcanza con setearlo.
try:
    _p = config_store.get_provider_config()
    if _p and not os.getenv("AI_PROVIDER_OVERRIDE"):
        os.environ["AI_PROVIDER"] = _p
except Exception:
    pass

app = Flask(__name__)
CORS(app)

# Dashboard estático (build del frontend Express). Si no está presente
# (dev local sin build), se responde el JSON de estado de la API.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


# ── Endpoint Raíz ──────────────────────────────────────────────────────────────


@app.route("/")
def root():
    index_path = os.path.join(_STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return send_from_directory(_STATIC_DIR, "index.html")
    return jsonify({"status": "online", "service": "After Drive Intelligence API"}), 200


# ── Manejadores Globales de Errores ────────────────────────────────────────────


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"success": False, "error": "Recurso no encontrado"}), 404


@app.errorhandler(500)
def internal_error(_error):
    return jsonify({"success": False, "error": "Error interno del servidor"}), 500

def _sse(lineas):
    return Response(
        stream_with_context(lineas),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    Devuelve la forma anidada que el frontend espera: cuando Express hacía de
    proxy respondía {express, scrapers}, y el dashboard chequea
    `scrapers.status === 'ok'`. Al pasar a un solo contenedor, Flask empezó a
    responder {"status": "ok"} sin esa clave, así que la comprobación del
    dashboard lanzaba excepción y el badge quedaba en "Sin Conexion" de forma
    permanente, sin importar el estado real del proveedor de IA.

    La forma sirve en los dos despliegues: con Express adelante, este objeto
    queda anidado bajo `scrapers` y la comprobación sigue dando bien.
    """
    return jsonify({"status": "ok", "express": "ok", "scrapers": {"status": "ok"}})


@app.route("/api/db-check", methods=["GET"])
def db_check():
    """Diagnóstico de conexión a MongoDB y estado de URLs confiables."""
    from afterdrive.db import MONGO_URI, col_trusted_urls

    uri_log = MONGO_URI[:40] + "..." if len(MONGO_URI) > 40 else MONGO_URI
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
        return jsonify({
            "success": False,
            "mongo_uri_preview": uri_log,
            "error": str(e),
        }), 500


@app.route("/api/articulos-stats", methods=["GET"])
def articulos_stats():
    """Cantidad de artículos guardados, para la tarjeta 'Artículos en DB'.

    Cuenta documentos en vez de reutilizar /api/check-volume, que resuelve
    con una búsqueda $text. Esa búsqueda exige un índice de texto que solo
    se crea al generar un artículo, así que en una base donde todavía no se
    generó ninguno devolvía 500 y la tarjeta quedaba vacía.
    """
    try:
        return jsonify({"success": True, "total": col_articulos.count_documents({})})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/check-volume", methods=["GET"])
def check_volume():
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"success": False, "error": "Se requiere el parámetro 'keyword'."}), 400

    try:
        count = col_articulos.count_documents({"$text": {"$search": keyword}})
        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Endpoints de Generación ───────────────────────────────────────────────────────


@app.route("/ultimo-articulo", methods=["GET"])
def ultimo_articulo():
    col_generados = db["articulos_generados"]
    doc = col_generados.find_one({}, sort=[("generado_en", -1)])
    if not doc:
        return jsonify({"success": False, "error": "Todavía no hay artículos generados."}), 404
    return jsonify(
        {
            "success": True,
            "articulo": {
                "contenido": doc.get("contenido", ""),
                "tema": doc.get("tema", ""),
                "fuentes": doc.get("fuentes", []),
                "generado_en": doc.get("generado_en", ""),
                "docs_usados": doc.get("docs_usados", []),
            },
        }
    )


def _parse_request_args(body: dict) -> list[str]:
    """Extrae argumentos de tema/persona del request body."""
    args_list = []
    tema = body.get("tema", "").strip()
    persona = body.get("persona", "").strip()
    if tema:
        args_list.extend(["--tema", tema])
    if persona and persona in ("analitico", "periodistico", "comercial", "divulgativo", "ejecutivo"):
        args_list.extend(["--persona", persona])
    return args_list


@app.route("/generar", methods=["POST"])
def generar():
    body = request.get_json(silent=True) or {}
    args_list = _parse_request_args(body)
    result = corridas.script("afterdrive.generacion.generar_articulo", args_list)
    status = 200 if result["success"] else 500
    return jsonify(result), status


# ── Endpoints streaming (SSE) ─────────────────────────────────────────────────


@app.route("/stream/generar", methods=["POST"])
@app.route("/api/stream/generar", methods=["POST"])
def stream_generar():
    body = request.get_json(silent=True) or {}
    args_list = _parse_request_args(body)
    return _sse(corridas.stream("afterdrive.generacion.generar_articulo", args_list))


# ── Endpoints para URLs Custom (Nuevas) ──────────────────────────────────────────


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
    )
    scheduler.aplicar()
    return jsonify({"success": True, "message": "Configuración de generación actualizada."})


@app.route("/api/fase2/config", methods=["GET"])
def get_fase2_config():
    return jsonify({"success": True, **config_store.get_fase2_config()})


@app.route("/api/fase2/config", methods=["POST"])
def set_fase2_config():
    body = request.get_json(silent=True) or {}
    cfg = config_store.set_fase2_config(
        categorias=body.get("categorias"),
        regiones=body.get("regiones"),
        clientes=body.get("clientes"),
        puntapie_activo=body.get("puntapie_activo"),
        puntapie_url=body.get("puntapie_url"),
    )
    return jsonify({"success": True, **cfg})


@app.route("/api/run-automation", methods=["POST"])
def run_automation():
    """Dispara ya el scraping de URLs confiables (en background)."""
    if corridas.en_curso():
        return jsonify({"success": False, "error": f"Otra corrida en curso ({corridas.en_curso()})."}), 409
    corridas.en_segundo_plano(corridas.scraping)
    return jsonify({"success": True, "message": "Scraping automatizado iniciado manualmente."})


@app.route("/api/run-generacion", methods=["POST"])
def run_generacion():
    """Dispara ya la generación de una Nota Fase 2 con la config guardada (en background)."""
    if corridas.en_curso():
        return jsonify({"success": False, "error": f"Otra corrida en curso ({corridas.en_curso()})."}), 409
    corridas.en_segundo_plano(corridas.generacion)
    return jsonify({"success": True, "message": "Generación automática iniciada."})


@app.route("/api/stream/run-automation", methods=["POST"])
def stream_run_automation():
    """Streaming SSE con el output en vivo del scraping de URLs confiables."""
    return _sse(corridas.stream("afterdrive.ingesta.run_automation"))


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
        return jsonify({"success": False, "error": str(e)}), 500


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
    """Cambiar proveedor de IA (local / nvidia / openrouter)."""
    body = request.get_json(silent=True) or {}
    provider = body.get("provider", "")
    if not provider:
        return jsonify({"success": False, "error": "Se requiere el campo 'provider'."}), 400

    result = llm.set_proveedor(provider)
    if result.get("success"):
        config_store.set_provider_config(provider)
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
        return jsonify({"success": False, "error": str(e)}), 500


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


@app.route("/api/discover-sources", methods=["POST"])
def discover_sources():
    result = corridas.script("afterdrive.ingesta.discover_sources")
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/api/trusted-urls", methods=["GET"])
def list_trusted_urls():
    """Lista todas las URLs confiables registradas."""
    from afterdrive.db import col_trusted_urls
    try:
        docs = list(col_trusted_urls.find({}, {"_id": 0}).sort("fecha_agregado", -1))
        return jsonify({"success": True, "urls": docs, "total": len(docs)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/trusted-urls", methods=["POST"])
def add_trusted_url_direct():
    """Agrega una URL directamente a trusted_urls sin pasar por el clasificador."""
    import datetime

    from afterdrive.db import col_trusted_urls
    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip()
    nombre = body.get("nombre", "").strip()
    if not url:
        return jsonify({"success": False, "error": "Se requiere la URL."}), 400
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
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/trusted-urls/<path:url>", methods=["DELETE"])
def delete_trusted_url(url):
    """Elimina o desactiva una URL confiable."""
    from afterdrive.db import col_trusted_urls
    try:
        result = col_trusted_urls.delete_one({"url": url})
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "URL no encontrada."}), 404
        return jsonify({"success": True, "message": "URL eliminada."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/add-url", methods=["POST"])
def add_url():
    body = request.get_json(silent=True) or {}
    url = body.get("url", "")
    if not url:
        return jsonify({"success": False, "error": "Se requiere la URL."}), 400

    # Ejecutamos el nuevo script add_url.py
    result = corridas.script("afterdrive.ingesta.add_url", [url])
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/stream/add-url", methods=["POST"])
def stream_add_url():
    body = request.get_json(silent=True) or {}
    url = body.get("url", "")
    if not url:
        return jsonify({"success": False, "error": "Se requiere la URL."}), 400

    return _sse(corridas.stream("afterdrive.ingesta.add_url", [url]))


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


@app.route("/api/fase2/scrape", methods=["POST"])
def fase2_scrape():
    body = request.get_json(silent=True) or {}
    tags = body.get("tags") or None
    max_por_tag = int(body.get("max", 5))
    result = corridas.script("afterdrive.generacion.scraper_afterdrive",
                        (["--tags"] + tags if tags else []) + ["--max", str(max_por_tag)])
    return jsonify(result), 200 if result["success"] else 500


@app.route("/api/fase2/stream/scrape", methods=["POST"])
def fase2_stream_scrape():
    body = request.get_json(silent=True) or {}
    tags = body.get("tags") or []
    max_por_tag = str(body.get("max", 5))
    extra = (["--tags"] + tags if tags else []) + ["--max", max_por_tag]
    return _sse(corridas.stream("afterdrive.generacion.scraper_afterdrive", extra))


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


@app.route("/api/fase2/generar", methods=["POST"])
def fase2_generar():
    body = request.get_json(silent=True) or {}
    categorias = body.get("categorias", [])
    clientes = body.get("clientes", [])
    puntapie_url = body.get("puntapie_url", None)
    persona = body.get("persona", "comercial")
    tema = body.get("tema", None)
    regiones = body.get("regiones", [])

    if not categorias:
        return jsonify({"success": False, "error": "Se requiere al menos una categoría."}), 400

    resultado = corridas.generacion({
        "categorias": categorias,
        "clientes_ids": clientes,
        "puntapie_url": puntapie_url,
        "persona": persona,
        "tema": tema,
        "regiones": regiones,
    })
    status = 200 if resultado["success"] else 500
    return jsonify(resultado), status


@app.route("/api/fase2/stream/generar", methods=["POST"])
def fase2_stream_generar():
    body = request.get_json(silent=True) or {}
    categorias = body.get("categorias", [])
    clientes = body.get("clientes", [])
    puntapie_url = body.get("puntapie_url", "") or ""
    persona = body.get("persona", "comercial")
    tema = body.get("tema", "") or ""
    regiones = body.get("regiones", []) or []

    extra = []
    if categorias:
        extra += ["--categorias"] + categorias
    if clientes:
        extra += ["--clientes"] + clientes
    if regiones:
        extra += ["--regiones"] + regiones
    if puntapie_url:
        extra += ["--puntapie", puntapie_url]
    if persona:
        extra += ["--persona", persona]
    if tema:
        extra += ["--tema", tema]

    return _sse(corridas.stream("afterdrive.generacion.generar_nota_fase2", extra))


@app.route("/api/fase2/ultima-nota", methods=["GET"])
def fase2_ultima_nota():
    from afterdrive.generacion.generar_nota_fase2 import get_ultima_nota
    doc = get_ultima_nota()
    if not doc:
        return jsonify({"success": False, "error": "No hay notas generadas aún."}), 404
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
