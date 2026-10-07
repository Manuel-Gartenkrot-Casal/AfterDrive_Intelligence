"""auth.py — Login de un único usuario administrador y guardia de sesión.

Las credenciales viven en variables de entorno, nunca en el código (el repo es
público): ADMIN_USER, ADMIN_PASSWORD_HASH (hash scrypt de werkzeug), SECRET_KEY
(firma la cookie de sesión) y CRON_TOKEN (corridas automáticas).

Si falta alguna de las tres primeras nadie entra: la app nunca queda abierta
por un olvido de configuración.

Interfaz:
    init_app(app)          registra login, logout y la guardia
    hay_sesion() -> bool   el request trae la sesión del admin
"""

import datetime
import hmac
import os
import threading
import time

from flask import current_app, jsonify, request, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

MAX_FALLOS = 5
BLOQUEO_S = 900  # 15 min
_MAX_PASSWORD = 1024  # scrypt sobre un texto enorme es una forma barata de tirar el servicio

# ponytail: contador en memoria. Alcanza con gunicorn --workers 1 y se pierde
# en cada deploy; pasarlo a Mongo si hay más de un worker. La IP sale del
# último salto de X-Forwarded-For: si Render antepone más de un proxy, varias
# personas comparten IP y el bloqueo se vuelve global (ajustar x_for abajo).
_fallos: dict[str, tuple[int, float]] = {}  # ip -> (cantidad, instante del último fallo)
_lock = threading.Lock()
_ahora = time.monotonic

_ABIERTAS = ("/", "/health", "/api/login")
_CRON = {("POST", "/api/run-automation"), ("POST", "/api/run-generacion")}


def _configurado() -> bool:
    return bool(current_app.secret_key and os.getenv("ADMIN_USER") and os.getenv("ADMIN_PASSWORD_HASH"))


def hay_sesion() -> bool:
    return _configurado() and session.get("usuario") == os.getenv("ADMIN_USER")


def _bearer_valido() -> bool:
    token = os.getenv("CRON_TOKEN", "")
    if not token or (request.method, request.path) not in _CRON:
        return False
    enviado = request.headers.get("Authorization", "")
    return hmac.compare_digest(enviado.encode(), f"Bearer {token}".encode())


def _guardia():
    if request.path in _ABIERTAS or hay_sesion() or _bearer_valido():
        return None
    return jsonify({"success": False, "error": "No autenticado"}), 401


def _bloqueada(ip: str) -> bool:
    with _lock:
        cantidad, ultimo = _fallos.get(ip, (0, 0.0))
        if cantidad and _ahora() - ultimo >= BLOQUEO_S:
            del _fallos[ip]
            return False
        return cantidad >= MAX_FALLOS


def _credenciales_ok(usuario, password) -> bool:
    son_texto = isinstance(usuario, str) and isinstance(password, str) and len(password) <= _MAX_PASSWORD
    # El hash se verifica siempre, coincida o no el usuario, para que el tiempo
    # de respuesta no delate cuál de los dos falló.
    try:
        clave_ok = check_password_hash(os.environ["ADMIN_PASSWORD_HASH"], password if son_texto else "")
        usuario_ok = son_texto and hmac.compare_digest(usuario.encode(), os.environ["ADMIN_USER"].encode())
    except Exception:
        # Hash mal formado en el entorno o texto que no se puede codificar
        # (un sustituto suelto): es un intento fallido, nunca un 500.
        return False
    return usuario_ok and clave_ok


def _login():
    if not _configurado():
        return jsonify({"success": False, "error": "Login no configurado en el servidor."}), 503
    ip = request.remote_addr or "?"
    if _bloqueada(ip):
        return jsonify({"success": False, "error": "Demasiados intentos. Probá de nuevo en 15 minutos."}), 429

    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    if not _credenciales_ok(body.get("usuario"), body.get("password")):
        with _lock:
            _fallos[ip] = (_fallos.get(ip, (0, 0.0))[0] + 1, _ahora())
        return jsonify({"success": False, "error": "Usuario o contraseña incorrectos."}), 401

    with _lock:
        _fallos.pop(ip, None)
    session.clear()
    session["usuario"] = body["usuario"]
    session.permanent = True
    return jsonify({"success": True})


def _logout():
    session.clear()
    return jsonify({"success": True})


def init_app(app) -> None:
    app.secret_key = os.getenv("SECRET_KEY") or None
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",  # también es la defensa contra CSRF
        SESSION_COOKIE_SECURE=bool(os.getenv("RENDER")),  # en local se usa http://localhost
    )
    app.permanent_session_lifetime = datetime.timedelta(days=7)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
    app.before_request(_guardia)
    app.add_url_rule("/api/login", view_func=_login, methods=["POST"])
    app.add_url_rule("/api/logout", view_func=_logout, methods=["POST"])
