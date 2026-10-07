# Login y endurecimiento de seguridad — diseño

Fecha: 2026-10-06
Estado: aprobado en conversación, pendiente de revisión escrita

## Objetivo

Que nadie sin credenciales pueda leer datos, cambiar configuración ni disparar
corridas en el dashboard de AfterDrive Intelligence, y cerrar las fallas que
el login por sí solo no tapa.

**Para quién:** un único usuario administrador con todos los permisos.

**Criterio de éxito:**

- Sin sesión, todo `/api/*` responde 401 (salvo las excepciones listadas abajo)
  y `/` muestra solo la pantalla de login.
- Con sesión, el dashboard funciona igual que hoy: ninguna función existente
  se pierde.
- El scraping y la generación programados siguen corriendo.
- La suite de tests existente sigue en verde.

## Punto de partida (hallazgos del análisis)

| # | Severidad | Problema | Dónde |
|---|---|---|---|
| 1 | Crítica | 44 endpoints sin autenticación en la URL pública | `afterdrive/flask_api.py` |
| 2 | Crítica | `/api/db-check` publica usuario y primeros caracteres de la contraseña de Mongo | `flask_api.py:99` |
| 3 | Crítica | URI de Mongo completa en el historial de un repo público | commits `c6ee771`, `30515cd` |
| 4 | Alta | SSRF: el servidor visita cualquier URL que se le pase | `ingesta/scraper.py` |
| 5 | Alta | XSS almacenado en fuentes y en el render de notas | `index.html:2100`, `:3364`, `:3413` |
| 6 | Alta | CORS abierto a cualquier origen | `flask_api.py:25` |
| 7 | Alta | Listas del body pasan a `argv` y pueden inyectar flags | `flask_api.py:553`, `:562`, `:634-646` |
| 8 | Media | `str(e)` devuelto al cliente | varios en `flask_api.py` |
| 9 | Media | Sin cabeceras de seguridad; `marked` sin versión fija ni SRI | `flask_api.py`, `index.html:7` |

## Decisiones

- **Sin base de datos de usuarios.** Con un solo usuario, las credenciales
  viven en variables de entorno. Cuando haga falta más de uno, se agrega una
  colección `usuarios` en el MongoDB Atlas actual.
- **Nada de credenciales en el código.** El repo es público.
- **Sin dependencias nuevas en Python.** Sesiones firmadas de Flask y
  `werkzeug.security` para el hash.
- **Se elimina el proxy Express.** Mantener autenticación en dos servidores no
  se justifica; el dashboard se sirve siempre desde Flask.

## Diseño

### 1. Configuración

| Variable | Contenido |
|---|---|
| `ADMIN_USER` | Nombre de usuario |
| `ADMIN_PASSWORD_HASH` | Salida de `werkzeug.security.generate_password_hash` (scrypt) |
| `SECRET_KEY` | Cadena aleatoria de al menos 32 bytes; firma la cookie |
| `CRON_TOKEN` | Cadena aleatoria; autoriza las corridas automáticas |

Si falta `ADMIN_USER`, `ADMIN_PASSWORD_HASH` o `SECRET_KEY`, `POST /api/login`
responde 503 y ninguna sesión es válida. Si falta `CRON_TOKEN`, ningún bearer
es válido. La app nunca queda abierta por falta de configuración.

Se agregan a `.env.example` y a `render.yaml` (`sync: false` para usuario y
hash; `generateValue: true` para `SECRET_KEY` y `CRON_TOKEN`).

### 2. Backend: `afterdrive/auth.py`

Módulo nuevo que expone `init_app(app)`. `flask_api.py` lo llama una vez.

**Rutas**

- `POST /api/login` con `{"usuario", "password"}`:
  - 200 `{"success": true}` y sesión creada.
  - 401 con mensaje genérico si usuario o contraseña no coinciden.
  - 429 si la IP está bloqueada.
  - 503 si falta configuración.
- `POST /api/logout`: limpia la sesión, responde 200.

El usuario se compara con `hmac.compare_digest` y el hash se verifica siempre,
coincida o no el usuario, para no filtrar por tiempo cuál de los dos falló.
Al entrar se hace `session.clear()` antes de marcar la sesión.

**Guardia (`before_request`)**

Pasan sin sesión únicamente:

- `GET /health` (lo usa Render y el keep-alive).
- `POST /api/login`.
- `GET /` (sirve `login.html` sin sesión, `index.html` con sesión).
- `POST /api/run-automation` y `POST /api/run-generacion` con
  `Authorization: Bearer <CRON_TOKEN>` válido (comparado con
  `hmac.compare_digest`).

Todo lo demás sin sesión responde 401 `{"success": false, "error": "No autenticado"}`.

**Cookie de sesión**

- `HttpOnly`, `SameSite=Strict`, duración 7 días.
- `Secure` cuando existe la variable `RENDER` (producción); apagado en local
  para poder usar `http://localhost`.
- `SameSite=Strict` es la defensa contra CSRF; no se agregan tokens.

**Fuerza bruta**

- 5 intentos fallidos por IP abren un bloqueo de 15 minutos. Un login correcto
  limpia el contador de esa IP.
- Contador en memoria (un `dict` con lock). Alcanza porque gunicorn corre con
  `--workers 1`; se reinicia en cada deploy.
- La IP sale de `X-Forwarded-For` vía `ProxyFix(x_for=1)`. **Límite conocido:**
  si Render antepone más de un proxy, varias personas comparten la misma IP
  aparente y el bloqueo se comporta como global (un atacante puede dejar al
  admin 15 minutos afuera, pero nunca entrar). Se ajusta `x_for` si los
  headers reales lo muestran.

### 3. Frontend

- `express/src/public/login.html`: página autocontenida (estilos y script en
  línea, misma tipografía y tokens que el dashboard). Formulario usuario +
  contraseña, hace `POST /api/login` y recarga `/` al entrar. Muestra el error
  de 401, 429 y 503.
- `index.html`:
  - Envoltorio de `window.fetch`: ante un 401 hace `location.reload()`, que
    cae en el login.
  - Botón "Salir" en el encabezado: `POST /api/logout` y recarga.

### 4. Corridas automáticas

- El scheduler interno (APScheduler) llama a `corridas` en proceso, no por
  HTTP: no lo afecta el login.
- Los dos cron de `render.yaml` envían `Authorization: Bearer $CRON_TOKEN`,
  tomando el valor del web service con `fromService`.
- Cualquier monitor externo que hoy pegue a esos dos endpoints necesita el
  mismo header.

### 5. Endurecimiento

**`/api/db-check`** usa `uri_segura(MONGO_URI)` en lugar de cortar a 40
caracteres.

**XSS**

- `escHtml()` en la URL de cada fuente (texto y atributo `title`) y en las
  claves de la evaluación de lineamientos.
- La nota se renderiza con `DOMPurify.sanitize(marked.parse(contenido))`.
- `marked` y DOMPurify se cargan desde jsDelivr con versión fija y atributo
  `integrity` (SRI).

**SSRF**

- `url_publica(url) -> bool` en `afterdrive/ingesta/scraper.py`: exige esquema
  `http` o `https` y que el host no resuelva a direcciones privadas, loopback,
  link-local ni reservadas (módulo `ipaddress`).
- Se aplica en las funciones de descarga del scraper, que es por donde pasa
  toda URL (las que entran por la API, las guardadas en Mongo y los enlaces
  descubiertos en las páginas).
- `/api/add-url`, `/stream/add-url` y `POST /api/trusted-urls` la llaman
  además para responder 400 temprano.
- **Límite conocido:** no cubre redirecciones hacia hosts internos ni DNS
  rebinding. Queda anotado en el código.

**Argumentos a subprocesos**

- Las listas (`tags`, `categorias`, `clientes`, `regiones`) deben ser listas de
  textos que no empiecen con `-`; si no, 400.
- Los escalares (`tema`, `persona`, `puntapie_url`, `max`) se pasan como
  `--opcion=valor`, que argparse nunca interpreta como otra flag.
- `max` se valida como entero >= 1.

**Varios**

- Se elimina `CORS(app)` y `flask-cors` de `requirements.txt` y `pyproject.toml`.
- Los `except` de `flask_api.py` dejan de devolver `str(e)`: loguean el detalle
  en el servidor y responden un mensaje genérico.
- `after_request` agrega:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: same-origin`
  - `Strict-Transport-Security: max-age=31536000` (solo con `RENDER`)
  - `Content-Security-Policy` con `default-src 'self'`, `connect-src 'self'`,
    `frame-ancestors 'none'`, `base-uri 'none'`, `form-action 'self'`, y las
    fuentes externas que el dashboard ya usa (jsDelivr, Google Fonts).
- **Límite conocido:** la CSP permite scripts en línea (`'unsafe-inline'`)
  porque el dashboard usa `onclick` y `<script>` en línea en todo el archivo.
  Una CSP estricta exige reescribir el HTML y queda fuera de alcance.

### 6. Eliminación del proxy Express

- Se borran `express/src/index.ts`, `express/package.json`,
  `express/package-lock.json`, `express/tsconfig.json`, `express/build.js` y
  `express/Dockerfile`.
- `express/src/public/` se conserva como fuente del dashboard, en la misma
  ruta.
- `Dockerfile`: desaparece la etapa de Node; `COPY express/src/public/ ./static/`.
- `docker-compose.yml`: se quita el servicio `express`; el servicio `scrapers`
  monta `./express/src/public` en `/app/static`.
- `flask_api.py`: si no existe `static/`, usa `express/src/public/` como
  carpeta del dashboard, para que el desarrollo local no requiera copiar nada.
- README: el dashboard local pasa de `http://localhost:3000` a
  `http://localhost:5000`; se documentan las cuatro variables y el comando
  para generar el hash.

### 7. Tests

`tests/test_auth.py`:

- Endpoint protegido sin sesión devuelve 401.
- Login correcto abre sesión; con usuario o contraseña incorrectos, 401.
- Al quinto fallo, 429; un login correcto limpia el contador.
- `CRON_TOKEN` válido habilita solo `/api/run-automation` y
  `/api/run-generacion`; en cualquier otro endpoint, 401.
- `/health` responde 200 sin sesión.
- Sin `SECRET_KEY` o sin hash, login responde 503.
- `/` sirve el login sin sesión y el dashboard con sesión.

`tests/test_scraper.py`: casos de `url_publica` (http/https públicos pasan;
`file://`, `localhost`, `127.0.0.1`, `10.0.0.1`, `169.254.169.254` no).

`tests/test_config_api.py`: el fixture `client` entra con sesión iniciada. Se
agregan casos de listas inválidas (400).

Verificación manual antes de dar por terminado: levantar Flask en local,
entrar, recorrer las secciones del dashboard, salir.

## Puesta en producción

`Render_Testing` es la rama que Render despliega, así que el trabajo se hace
en la rama `feat/login-seguridad` y se integra cuando esté verificado.

Orden:

1. Cargar `ADMIN_USER`, `ADMIN_PASSWORD_HASH`, `SECRET_KEY` y `CRON_TOKEN` en
   Render. Si se despliega antes de cargarlas, el panel queda cerrado (no
   roto): nadie entra hasta que estén.
2. Integrar a `Render_Testing` y desplegar.
3. Verificar que `/api/db-check` sin sesión responde 401.
4. Rotar la contraseña del usuario de Mongo en Atlas y actualizar `MONGO_URI`
   en Render. Va después del paso 3: rotar antes volvería a publicar el
   prefijo de la contraseña nueva.

## Fuera de alcance

- Varios usuarios, roles, registro y recuperación de contraseña. Para cambiar
  la contraseña se reemplaza `ADMIN_PASSWORD_HASH`.
- Límite de uso en endpoints que no sean el login.
- Reescritura del historial de git. La mitigación es la rotación.
- Cierre de sesiones desde el servidor. La única forma es rotar `SECRET_KEY`.
- CSP sin `'unsafe-inline'`.
