# Login y endurecimiento de seguridad — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar el dashboard y la API detrás de un login de un solo usuario y corregir SSRF, XSS, CORS, inyección de argumentos y fuga de credenciales.

**Architecture:** Un módulo `afterdrive/auth.py` registra login, logout y un `before_request` que exige sesión firmada de Flask (o un bearer para los dos endpoints de cron). El dashboard se sirve solo desde Flask: sin sesión, `/` entrega `login.html`. El resto son correcciones puntuales en `flask_api.py`, `scraper.py` e `index.html`, y la eliminación del proxy Express.

**Tech Stack:** Python 3.12, Flask 3.1, Werkzeug (scrypt, ProxyFix), pytest, HTML/JS sin build, DOMPurify + marked por CDN.

**Spec:** `docs/superpowers/specs/2026-10-06-login-y-seguridad-design.md`

## Global Constraints

- Rama de trabajo: `feat/login-seguridad`. No se pushea ni se integra a `Render_Testing` (rama que Render despliega) dentro de este plan.
- Sin dependencias Python nuevas. `flask-cors` se elimina.
- Ninguna credencial en el código: el repo es público.
- Variables: `ADMIN_USER`, `ADMIN_PASSWORD_HASH`, `SECRET_KEY`, `CRON_TOKEN`. Si falta alguna de las tres primeras, el login responde 503 y nada queda abierto.
- Rutas sin sesión: `GET /health`, `POST /api/login`, `GET /`. Con bearer válido: `POST /api/run-automation` y `POST /api/run-generacion`. Todo lo demás, 401 `{"success": false, "error": "No autenticado"}`.
- Cookie: `HttpOnly`, `SameSite=Strict`, 7 días, `Secure` solo si existe la variable `RENDER`.
- Bloqueo: 5 fallos por IP, 900 segundos.
- Ninguna función existente del dashboard se pierde; la suite actual sigue en verde.
- Mensajes de commit en español, formato convencional, con el trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests: `python -m pytest -q`. Lint: `python -m ruff check afterdrive tests`.

## Review Focus

1. **Body de login que no es JSON o trae campos que no son texto** (`null`, número, objeto): debe dar 401, nunca 500. → Task 1.
2. **`ADMIN_PASSWORD_HASH` mal formado** (contraseña pegada en claro, hash truncado): debe dar 401, nunca 500 ni acceso. → Task 1.
3. **El hash scrypt contiene `$`** y un `.env` puede interpolarlo y romperlo: el formato documentado (comillas simples) debe sobrevivir a `python-dotenv`. → Task 1.
4. **Listas enviadas como texto o con elementos que no son texto** (`"categorias": "autopartes"`, `[1, {}]`): 400, no un 500 ni un `argv` raro. → Task 3.
5. **URLs en formas no obvias**: IPv6 loopback `http://[::1]/`, host que no resuelve, sin esquema. Todas deben rechazarse. → Task 4.

---

### Task 1: Autenticación en el backend

**Files:**
- Create: `afterdrive/auth.py`, `tests/conftest.py`, `tests/test_auth.py`
- Modify: `afterdrive/flask_api.py` (llamar a `auth.init_app(app)` después de crear `app`), `tests/test_config_api.py` (fixture `client`), `.env.example`, `render.yaml`

**Interfaces:**
- Produces:
  - `auth.init_app(app: Flask) -> None`
  - `auth.hay_sesion() -> bool` (hay `session["usuario"]`)
  - `auth._fallos: dict[str, tuple[int, float]]`, `auth._ahora: Callable[[], float]` (alias de `time.monotonic`, para parchear en tests), `auth.MAX_FALLOS = 5`, `auth.BLOQUEO_S = 900`
  - Fixture `api` en `tests/conftest.py` → `(flask_api, store)` con la app configurada: `ADMIN_USER=admin`, hash de `secreta123`, `CRON_TOKEN=cron-test`, `app.config["SECRET_KEY"]="clave-de-test"`, `auth._fallos` vacío, y los parches de `config_store` y `scheduler` que hoy hace el fixture `client`.
  - Fixture `client` de `test_config_api.py` → `(test_client, store)` con sesión iniciada vía `session_transaction()`.

- [ ] **Step 1: Mover los parches comunes a `tests/conftest.py` (fixture `api`) y hacer que `client` lo use e inicie sesión**

- [ ] **Step 2: Escribir `tests/test_auth.py`**

```python
OK = {"usuario": "admin", "password": "secreta123"}

def test_sin_sesion_es_401(api):
    c = api[0].app.test_client()
    r = c.get("/api/scraping-config")
    assert r.status_code == 401 and r.json == {"success": False, "error": "No autenticado"}
    assert c.post("/api/fase2/clientes", json={"nombre": "x"}).status_code == 401
    assert c.get("/ruta-que-no-existe").status_code == 401

def test_health_abierto(api):
    assert api[0].app.test_client().get("/health").status_code == 200

def test_login_abre_sesion_y_logout_la_cierra(api):
    c = api[0].app.test_client()
    r = c.post("/api/login", json=OK)
    assert r.status_code == 200 and r.json == {"success": True}
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert c.get("/api/scraping-config").status_code == 200
    assert c.post("/api/logout").status_code == 200
    assert c.get("/api/scraping-config").status_code == 401

@pytest.mark.parametrize("body", [
    {"usuario": "admin", "password": "mala"}, {"usuario": "otro", "password": "secreta123"},
    {}, {"usuario": None, "password": 5}, {"usuario": {"$ne": ""}, "password": ["x"]},
])
def test_credenciales_malas_son_401(api, body):
    assert api[0].app.test_client().post("/api/login", json=body).status_code == 401

def test_body_no_json_es_401(api):
    assert api[0].app.test_client().post("/api/login", data="hola").status_code == 401

def test_bloqueo_al_quinto_fallo_y_vence(api, monkeypatch):
    from afterdrive import auth
    reloj = [1000.0]
    monkeypatch.setattr(auth, "_ahora", lambda: reloj[0])
    c = api[0].app.test_client()
    for _ in range(5):
        assert c.post("/api/login", json={"usuario": "admin", "password": "mala"}).status_code == 401
    assert c.post("/api/login", json=OK).status_code == 429
    reloj[0] += 901
    assert c.post("/api/login", json=OK).status_code == 200

def test_login_correcto_limpia_fallos(api):
    c = api[0].app.test_client()
    for _ in range(4):
        c.post("/api/login", json={"usuario": "admin", "password": "mala"})
    assert c.post("/api/login", json=OK).status_code == 200
    c.post("/api/logout")
    for _ in range(4):
        assert c.post("/api/login", json={"usuario": "admin", "password": "mala"}).status_code == 401

@pytest.mark.parametrize("falta", ["ADMIN_USER", "ADMIN_PASSWORD_HASH", "SECRET_KEY"])
def test_sin_configuracion_es_503_y_sigue_cerrado(api, monkeypatch, falta):
    # SECRET_KEY vive en app.config; las otras dos en el entorno.
    ...  # quitar `falta`; assert login == 503 y GET /api/scraping-config == 401

def test_hash_mal_formado_es_401(api, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "secreta123")
    assert api[0].app.test_client().post("/api/login", json=OK).status_code == 401

def test_cron_token_solo_en_sus_dos_endpoints(api, monkeypatch):
    fa = api[0]
    monkeypatch.setattr(fa.corridas, "en_segundo_plano", lambda *a: None)
    c, h = fa.app.test_client(), {"Authorization": "Bearer cron-test"}
    assert c.post("/api/run-automation", headers=h).status_code == 200
    assert c.post("/api/run-generacion", headers=h).status_code == 200
    assert c.get("/api/scraping-config", headers=h).status_code == 401
    assert c.post("/api/run-automation", headers={"Authorization": "Bearer otro"}).status_code == 401

def test_sin_cron_token_ningun_bearer_vale(api, monkeypatch):
    monkeypatch.delenv("CRON_TOKEN")
    r = api[0].app.test_client().post("/api/run-automation", headers={"Authorization": "Bearer "})
    assert r.status_code == 401

def test_hash_entre_comillas_simples_sobrevive_a_dotenv(tmp_path):
    from dotenv import dotenv_values
    from werkzeug.security import generate_password_hash
    h = generate_password_hash("x")
    (tmp_path / ".env").write_text(f"ADMIN_PASSWORD_HASH='{h}'\n")
    assert dotenv_values(tmp_path / ".env")["ADMIN_PASSWORD_HASH"] == h
```

- [ ] **Step 3: Correr y ver que fallan**

Run: `python -m pytest tests/test_auth.py -q` — Expected: FAIL (`afterdrive.auth` no existe / 200 donde se espera 401).

- [ ] **Step 4: Implementar `afterdrive/auth.py` y cablearlo**

  - `init_app` fija `app.secret_key = os.getenv("SECRET_KEY") or None`, `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Strict"`, `SESSION_COOKIE_SECURE=bool(os.getenv("RENDER"))`, `permanent_session_lifetime = timedelta(days=7)`, envuelve `app.wsgi_app` con `ProxyFix(x_for=1)`, y registra las dos rutas y el `before_request`.
  - `ADMIN_USER`, `ADMIN_PASSWORD_HASH` y `CRON_TOKEN` se leen con `os.getenv` en cada request; `SECRET_KEY` se consulta como `app.secret_key`.
  - Login: orden de chequeos 503 (config) → 429 (bloqueo) → credenciales. Usuario con `hmac.compare_digest`; `check_password_hash` se ejecuta siempre y cualquier excepción suya cuenta como contraseña incorrecta. Al entrar: `session.clear()`, `session["usuario"]`, `session.permanent = True`.
  - Mensajes: 401 `"Usuario o contraseña incorrectos."`, 429 `"Demasiados intentos. Probá de nuevo en 15 minutos."`, 503 `"Login no configurado en el servidor."`.
  - Bloqueo: `_fallos[ip] = (cantidad, instante_del_último_fallo)`; bloqueada si `cantidad >= MAX_FALLOS` y pasaron menos de `BLOQUEO_S`; una entrada vencida se descarta. Mientras está bloqueada no se evalúa la contraseña ni se extiende el bloqueo. Acceso bajo `threading.Lock`. Comentario `# ponytail:` con los dos techos: en memoria (un worker) e IP compartida detrás del proxy.
  - Bearer: `hmac.compare_digest` contra `CRON_TOKEN`, solo si `CRON_TOKEN` no está vacío y `(request.method, request.path)` es uno de los dos endpoints.

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -q` — Expected: PASS, incluidos los tests previos.

- [ ] **Step 6: Configuración**

  - `.env.example`: bloque nuevo con las cuatro variables. `ADMIN_PASSWORD_HASH` entre comillas simples, con un comentario que explique que el hash trae `$` y que sin comillas simples se rompe. Incluir los dos comandos:
    - hash: `python -c "from getpass import getpass; from werkzeug.security import generate_password_hash as g; print(g(getpass('Contraseña: ')))"`
    - secretos: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
  - `render.yaml`, web service: `ADMIN_USER` y `ADMIN_PASSWORD_HASH` con `sync: false`; `SECRET_KEY` y `CRON_TOKEN` con `generateValue: true`.
  - `render.yaml`, los dos cron: `envVars` con `CRON_TOKEN` vía `fromService` (`type: web`, `name: afterdrive-intelligence`, `envVarKey: CRON_TOKEN`), y el `startCommand` envía `headers={'Authorization': 'Bearer ' + os.environ['CRON_TOKEN']}`. Actualizar el comentario que sugiere pegarle desde un monitor externo: ahora requiere ese header.
  - Verificar: `python -c "import yaml,sys; yaml.safe_load(open('render.yaml'))"` sin error (si `yaml` no está instalado, `render blueprints validate` o dejar constancia).

- [ ] **Step 7: Commit** — `feat(auth): login de un usuario, guardia de sesion y token de cron`

---

### Task 2: Pantalla de login y sesión en el dashboard

**Files:**
- Create: `express/src/public/login.html`
- Modify: `afterdrive/flask_api.py:27-40` (`_STATIC_DIR`, `root()`), `express/src/public/index.html` (envoltorio de `fetch` al inicio del `<script>` principal; botón junto a `#themeBtn`, línea ~1394)
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `auth.hay_sesion()`, fixtures `api` y `client`.
- Produces: `flask_api._STATIC_DIR` (parcheable en tests).

- [ ] **Step 1: Tests**

```python
def test_raiz_sirve_login_o_dashboard_segun_sesion(api, monkeypatch, tmp_path):
    (tmp_path / "login.html").write_text("PANTALLA-LOGIN")
    (tmp_path / "index.html").write_text("PANTALLA-DASHBOARD")
    monkeypatch.setattr(api[0], "_STATIC_DIR", str(tmp_path))
    c = api[0].app.test_client()
    assert b"PANTALLA-LOGIN" in c.get("/").data
    c.post("/api/login", json=OK)
    assert b"PANTALLA-DASHBOARD" in c.get("/").data

def test_dashboard_fuente_tiene_login_y_no_expone_datos():
    html = open("express/src/public/login.html", encoding="utf-8").read()
    assert "/api/login" in html and 'type="password"' in html
```

- [ ] **Step 2: Correr y ver que fallan** — `python -m pytest tests/test_auth.py -q -k "raiz or fuente"`.

- [ ] **Step 3: `flask_api.py`**

  - `_STATIC_DIR`: `static/` si existe; si no, `express/src/public/`.
  - `root()`: sirve `index.html` con sesión y `login.html` sin sesión; si el archivo no existe conserva la respuesta JSON de estado actual.
  - Ambas respuestas HTML con `Cache-Control: no-store`, para que "atrás" después de salir no muestre el dashboard.

- [ ] **Step 4: `login.html`**

Página autocontenida. Reutiliza del dashboard las variables CSS de color, la tipografía Outfit y la lectura de `localStorage["ad-theme"]`, para que respete claro/oscuro. Un formulario con `usuario`, `password` (`autocomplete="username"` / `"current-password"`) y botón "Entrar". Al enviar: `POST /api/login` con JSON; 200 → `location.replace("/")`; otro código → muestra `error` del cuerpo en un elemento con `role="alert"` (asignado con `textContent`). Botón deshabilitado mientras espera.

- [ ] **Step 5: `index.html`**

  - Primer bloque del script principal:
    ```js
    const _fetch = window.fetch;
    window.fetch = async (...a) => { const r = await _fetch(...a); if (r.status === 401) location.reload(); return r; };
    ```
  - Botón "Salir" junto a `#themeBtn`, con la misma clase visual; llama a `salir()`, que hace `POST /api/logout` y `location.reload()`.

- [ ] **Step 6: `python -m pytest -q`** — Expected: PASS.

- [ ] **Step 7: Commit** — `feat(dashboard): pantalla de login, boton de salir y recarga ante 401`

---

### Task 3: Endurecimiento de la API

**Files:**
- Modify: `afterdrive/flask_api.py`, `requirements.txt`, `pyproject.toml`
- Test: `tests/test_config_api.py`, `tests/test_auth.py`

**Interfaces:**
- Produces: `flask_api._lista_texto(valor) -> list[str] | None` (`[]` si falta; `None` si no es una lista de textos o alguno empieza con `-`), `flask_api._error_interno(e: Exception, status: int = 500)`.

- [ ] **Step 1: Tests**

```python
# test_config_api.py — usan `client` (con sesión)
@pytest.mark.parametrize("ruta", ["/api/fase2/stream/generar", "/api/fase2/generar"])
@pytest.mark.parametrize("categorias", ["autopartes", ["autopartes", "--puntapie", "http://x"], [1], [{}]])
def test_listas_invalidas_son_400(client, monkeypatch, ruta, categorias):
    from afterdrive import corridas
    monkeypatch.setattr(corridas, "stream", lambda *a, **k: pytest.fail("no debe ejecutarse"))
    monkeypatch.setattr(corridas, "generacion", lambda *a, **k: pytest.fail("no debe ejecutarse"))
    assert client[0].post(ruta, json={"categorias": categorias}).status_code == 400

@pytest.mark.parametrize("body", [{"tags": ["--max", "9"]}, {"max": "5; rm"}, {"max": 0}, {"tags": "x"}])
def test_scrape_fase2_valida_parametros(client, monkeypatch, body): ...  # 400 en /api/fase2/scrape y /api/fase2/stream/scrape

def test_escalares_viajan_como_opcion_igual_valor(client, monkeypatch):
    visto = {}
    from afterdrive import corridas
    monkeypatch.setattr(corridas, "stream", lambda nombre, argv=None: visto.update(argv=argv) or iter(()))
    client[0].post("/api/fase2/stream/generar", json={"categorias": ["autopartes"], "tema": "--persona", "puntapie_url": "-x"})
    assert "--tema=--persona" in visto["argv"] and "--puntapie=-x" in visto["argv"]

def test_db_check_no_expone_credenciales(client, monkeypatch):
    from afterdrive import db
    monkeypatch.setattr(db, "MONGO_URI", "mongodb+srv://usuario:clave-secreta@cluster.mongodb.net/x")
    cuerpo = client[0].get("/api/db-check").get_data(as_text=True)
    assert "usuario" not in cuerpo and "clave" not in cuerpo and "cluster.mongodb.net" in cuerpo

def test_errores_no_filtran_la_excepcion(client, monkeypatch):
    from afterdrive import flask_api
    class Rota:
        def count_documents(self, *_): raise RuntimeError("host-interno-10.0.0.7")
    monkeypatch.setattr(flask_api, "col_articulos", Rota())
    r = client[0].get("/api/articulos-stats")
    assert r.status_code == 500 and "host-interno" not in r.get_data(as_text=True)

# test_auth.py
def test_cabeceras_de_seguridad(api, monkeypatch):
    c = api[0].app.test_client()
    h = c.get("/health").headers
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "same-origin" and "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in h and "Access-Control-Allow-Origin" not in h
    monkeypatch.setenv("RENDER", "true")
    assert c.get("/health").headers["Strict-Transport-Security"] == "max-age=31536000"
```

- [ ] **Step 2: Correr y ver que fallan.**

- [ ] **Step 3: Implementar**

  - `/api/db-check`: `uri_log = uri_segura(MONGO_URI)`.
  - Quitar `from flask_cors import CORS` y `CORS(app)`; quitar `flask-cors` de `requirements.txt` y de `pyproject.toml`.
  - `_lista_texto` en los cuatro endpoints de fase 2 que reciben `tags`, `categorias`, `clientes`, `regiones`; respuesta 400 `"Parámetro '<clave>' inválido."`. `max` con `_entero_valido`.
  - Escalares como `--opcion=valor`: `--tema=`, `--persona=`, `--puntapie=`, `--max=` (también en `_parse_request_args`).
  - `_error_interno`: imprime `[API ERROR] <path>: <repr(e)>` y responde `{"success": False, "error": "Error interno del servidor"}`. Reemplaza las 8 apariciones de `str(e)`.
  - `@app.after_request`: las cuatro cabeceras fijas, HSTS si `os.getenv("RENDER")`, y esta CSP exacta:
    `default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`

- [ ] **Step 4: `python -m pytest -q` y `python -m ruff check afterdrive tests`** — Expected: PASS, sin errores.

- [ ] **Step 5: Commit** — `fix(api): db-check sin credenciales, sin CORS, argumentos validados y cabeceras de seguridad`

---

### Task 4: Protección contra SSRF

**Files:**
- Modify: `afterdrive/ingesta/scraper.py` (`url_publica`, guardia al inicio de `_fetch`), `afterdrive/flask_api.py` (`add_trusted_url_direct`, `add_url`, `stream_add_url`)
- Test: `tests/test_scraper.py`, `tests/test_config_api.py`

**Interfaces:**
- Produces: `scraper.url_publica(url: str) -> bool`.

- [ ] **Step 1: Tests**

```python
# test_scraper.py
def _dns(monkeypatch, tabla):
    def fake(host, *a, **k):
        if host not in tabla: raise socket.gaierror
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, 0, 0, "", (ip, 0)) for ip in tabla[host]]
    monkeypatch.setattr(scraper.socket, "getaddrinfo", fake)

@pytest.mark.parametrize("url,ok", [
    ("https://sitio.com/noticias", True), ("http://sitio.com", True),
    ("file:///etc/passwd", False), ("ftp://sitio.com", False), ("sitio.com", False), ("", False),
    ("http://localhost:5000/", False), ("http://127.0.0.1/", False), ("http://[::1]/", False),
    ("http://10.0.0.1/", False), ("http://169.254.169.254/latest/meta-data/", False),
    ("http://interno.corp/", False), ("http://no-resuelve.invalid/", False),
    ("http://mixto.com/", False),
])
def test_url_publica(monkeypatch, url, ok):
    _dns(monkeypatch, {"sitio.com": ["93.184.216.34"], "localhost": ["127.0.0.1"], "127.0.0.1": ["127.0.0.1"],
                       "::1": ["::1"], "10.0.0.1": ["10.0.0.1"], "169.254.169.254": ["169.254.169.254"],
                       "interno.corp": ["192.168.1.20"], "mixto.com": ["93.184.216.34", "10.0.0.5"]})
    assert scraper.url_publica(url) is ok

def test_fetch_no_descarga_urls_internas(monkeypatch):
    monkeypatch.setattr(scraper, "url_publica", lambda u: False)
    for f in ("_http_get", "_browser_get", "_wayback_get"):
        monkeypatch.setattr(scraper, f, lambda *a, **k: pytest.fail("no debe descargar"))
    assert scraper._fetch("http://10.0.0.1/") is None

# test_config_api.py
@pytest.mark.parametrize("ruta", ["/api/trusted-urls", "/api/add-url", "/stream/add-url"])
def test_alta_de_url_interna_es_400(client, monkeypatch, ruta):
    from afterdrive import corridas
    from afterdrive.ingesta import scraper
    monkeypatch.setattr(scraper, "url_publica", lambda u: False)
    monkeypatch.setattr(corridas, "script", lambda *a, **k: pytest.fail("no debe ejecutarse"))
    monkeypatch.setattr(corridas, "stream", lambda *a, **k: pytest.fail("no debe ejecutarse"))
    assert client[0].post(ruta, json={"url": "http://127.0.0.1/"}).status_code == 400
```

- [ ] **Step 2: En el fixture `red` de `tests/test_scraper.py`, parchear `scraper.url_publica` a `lambda u: True`**, para que los tests existentes no hagan DNS real. Correr y ver que los tests nuevos fallan.

- [ ] **Step 3: Implementar**

  - `url_publica`: esquema en `{"http", "https"}`, hostname presente, `socket.getaddrinfo(hostname, None)` y **todas** las direcciones con `ipaddress.ip_address(...).is_global`. Cualquier excepción → `False`. Comentario `# ponytail:` con el techo: no cubre redirecciones ni DNS rebinding; para eso hay que fijar la IP resuelta en la conexión.
  - `_fetch`: primera línea, `if not url_publica(url): return None` con un `print` `[URL BLOQUEADA]`. Confirmar con grep que `_http_get` y `_browser_get` no tienen otros llamadores.
  - Los tres endpoints: 400 `"La URL debe ser http(s) y pública."` antes de tocar Mongo o lanzar el subproceso. Importar `url_publica` dentro de la función, como hacen los demás imports de `ingesta` en ese archivo.

- [ ] **Step 4: `python -m pytest -q`** — Expected: PASS.

- [ ] **Step 5: Commit** — `fix(scraper): rechazar URLs que no sean http(s) publicas`

---

### Task 5: XSS en el dashboard

**Files:**
- Modify: `express/src/public/index.html` (líneas ~7, ~2100, ~3364, ~3413)
- Test: `tests/test_auth.py`

- [ ] **Step 1: Test de regresión sobre la fuente**

```python
def test_dashboard_sanitiza_y_fija_versiones():
    html = open("express/src/public/index.html", encoding="utf-8").read()
    assert "DOMPurify.sanitize(marked.parse(" in html
    assert "body.innerHTML = marked.parse(" not in html
    for tag in re.findall(r'<script src="https://cdn\.jsdelivr\.net[^>]*>', html):
        assert re.search(r"@\d+\.\d+\.\d+/", tag) and 'integrity="sha384-' in tag and "crossorigin" in tag
    assert "+u.url+" not in html
```

- [ ] **Step 2: Correr y ver que falla.**

- [ ] **Step 3: Implementar**

  - Versiones: fijar `marked` en la que hoy resuelve `https://cdn.jsdelivr.net/npm/marked/package.json` (así no cambia el render) y DOMPurify (`dist/purify.min.js`) en la última 3.x de `https://cdn.jsdelivr.net/npm/dompurify/package.json`. Verificar que la URL fijada de `marked` responde 200 y sigue exponiendo el global `marked`.
  - SRI de cada archivo: `curl -s <url> | openssl dgst -sha384 -binary | openssl base64 -A`. Ambos `<script>` con `integrity` y `crossorigin="anonymous"`.
  - Nota: `body.innerHTML = DOMPurify.sanitize(marked.parse(d.nota.contenido));`
  - Fuentes: `escHtml(u.url)` en el texto y en el atributo `title`.
  - Evaluación: `escHtml(k.replace(/_/g, ' '))`.
  - Revisar el resto de los `innerHTML` del archivo y escapar cualquier otro dato del servidor que hoy entre sin `escHtml`.

- [ ] **Step 4: `python -m pytest -q`** — Expected: PASS.

- [ ] **Step 5: Commit** — `fix(dashboard): sanitizar notas, escapar URLs de fuentes y fijar scripts externos con SRI`

---

### Task 6: Eliminar el proxy Express

**Files:**
- Delete: `express/src/index.ts`, `express/package.json`, `express/package-lock.json`, `express/tsconfig.json`, `express/build.js`, `express/Dockerfile`
- Modify: `Dockerfile`, `docker-compose.yml`, `.gitignore`, `.dockerignore`, `README.md`, `scripts/manual/smoke_playwright.py`, comentarios de `afterdrive/flask_api.py:27` y `:77-91`

- [ ] **Step 1: Confirmar que nada más depende del proxy**

Run: `git grep -n -i -E "express|:3000|SCRAPERS_URL" -- . ':!express/' ':!docs/superpowers/' ':!.agents/'` — cada resultado se actualiza o se elimina en este task.

- [ ] **Step 2: Cambios**

  - `Dockerfile`: sin etapa `dash`; `COPY express/src/public/ ./static/` en lugar del `COPY --from=dash`.
  - `docker-compose.yml`: sin servicio `express`; `scrapers` suma el volumen `./express/src/public:/app/static`.
  - `.gitignore` y `.dockerignore`: quitar las entradas de `express/node_modules`, `express/dist` y `express/.npx-cache`; ajustar el comentario de `static/`.
  - `smoke_playwright.py`: quitar las pruebas contra Express en `:3000` y sus llamadas; queda la de Flask.
  - `flask_api.py`: actualizar los dos comentarios que hablan de Express. La forma de respuesta de `/api/health` **no cambia**: el dashboard la consume así.
  - `README.md`: arquitectura local sin Express, dashboard en `http://localhost:5000`, sección nueva "Acceso" con las cuatro variables, los dos comandos para generarlas y la nota de comillas simples; quitar los pasos de Node.

- [ ] **Step 3: Verificar**

  - `docker compose config -q` sin error.
  - `docker build -t afterdrive-test .` si hay daemon de Docker disponible; si no, dejar constancia de que no se pudo construir la imagen.
  - `python -m pytest -q` — Expected: PASS.

- [ ] **Step 4: Commit** — `refactor: eliminar el proxy Express, Flask sirve el dashboard tambien en local`

---

### Task 7: Verificación de punta a punta

**Files:** ninguno (correcciones, si aparecen, van al task dueño del código).

- [ ] **Step 1:** `python -m pytest -q` y `python -m ruff check afterdrive tests` — Expected: todo verde.

- [ ] **Step 2: Levantar Flask en local** con variables de prueba (`ADMIN_USER`, hash de una contraseña de prueba, `SECRET_KEY`, `CRON_TOKEN`) en el puerto 5000. Si `MONGO_URI` no está disponible en el entorno, los paneles de datos van a dar error: dejar constancia de qué quedó sin verificar contra datos reales.

- [ ] **Step 3: Recorrido en el navegador**

  - `/` sin sesión muestra el login; `curl -i http://localhost:5000/api/db-check` → 401.
  - Contraseña incorrecta muestra el error; la correcta entra al dashboard.
  - Recorrer todas las secciones del carrusel; abrir una nota si hay datos.
  - Consola del navegador: sin violaciones de CSP ni errores de SRI.
  - "Salir" vuelve al login; "atrás" no muestra el dashboard.
  - `curl -i -X POST http://localhost:5000/api/run-automation -H "Authorization: Bearer <token>"` → no es 401; sin header → 401.

- [ ] **Step 4:** Informar al usuario: qué se verificó, qué no, y el recordatorio de las cuatro variables con el orden de puesta en producción del spec.
