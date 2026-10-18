# 07 · API

Todo en `afterdrive/flask_api.py`. Las respuestas son JSON con `success: true|false` y, si falla, `error` con un mensaje para el usuario.

## Acceso

- **Un solo usuario** admin: `ADMIN_USER` + `ADMIN_PASSWORD_HASH` (hash scrypt, nunca la contraseña). La sesión se firma con `SECRET_KEY` y dura 7 días.
- **Todo pide sesión** salvo `/`, `/health` y `/api/login`. Sin sesión: 401.
- **Cron externo**: `POST /api/run-automation` y `POST /api/run-generacion` aceptan también `Authorization: Bearer <CRON_TOKEN>`.
- 5 intentos fallidos desde una IP bloquean el login 15 minutos.
- Cabeceras de seguridad (CSP, `X-Frame-Options`…), cookie `HttpOnly` + `SameSite=Strict`, y el scraper rechaza URLs internas (SSRF). La CSP permite los dominios de Google Translate para el traductor.

Login y guardia en `afterdrive/auth.py`.

## Endpoints

**Salud y sesión**

| | |
|---|---|
| `GET /health` | Para Render. A propósito no consulta Mongo ni la IA |
| `GET /api/health` | Lo consulta el dashboard para el indicador "Online" |
| `GET /api/db-check` | Diagnóstico de la conexión a Mongo (sin credenciales) |
| `POST /api/login`, `POST /api/logout` | |

**Corridas (la cola)**

Encolar responde **202** con `id`, `posicion` y `duplicada`; **429** si ya hay 5 esperando.

| | |
|---|---|
| `POST /api/corridas/scraping` | Scraping de todas las fuentes activas |
| `POST /api/corridas/generacion` | Una nota con los parámetros del body (`categorias`, `regiones`, `clientes`, `persona`, `tema`, `puntapie_url`) |
| `POST /api/corridas/ejemplos` | Sincronizar ejemplos (`tags`, `max`) |
| `POST /api/corridas/probar-fuente` | Probar y agregar una fuente (`url`) |
| `POST /api/corridas/recomendaciones` | Buscar fuentes recomendadas |
| `POST /api/run-automation`, `POST /api/run-generacion` | Scraping / nota automática con la config guardada (para el cron) |
| `GET /api/corridas` | `en_curso`, `pendientes` y `recientes` |
| `GET /api/corridas/<id>/log?desde=N` | Líneas nuevas del log desde la N, estado y posición en la cola |
| `POST /api/corridas/<id>/cancelar` | Cancela (409 si es una generación ya empezada en el servidor) |

**Historial y revisión de notas**

| | |
|---|---|
| `GET /api/historial/resumen` | Totales por sección y notas por estado |
| `GET /api/historial/<seccion>?pagina=&por_pagina=&q=&estado=` | Lista paginada. Secciones: `generados_aprobados`, `generados_descartados`, `scrapeados_aprobados`, `scrapeados_descartados` |
| `GET /api/historial/<seccion>/<coleccion>/<id>` | Un ítem con su contenido completo |
| `POST /api/historial/estado` | `{coleccion, id, estado}`: `borrador`, `aprobada`, `rechazada` o `publicado` |
| `PATCH /api/historial/contenido` | `{coleccion, id, contenido}`: editar el texto de una nota no publicada |
| `GET /api/hubspot/estado` | `{configurado}` |
| `POST /api/hubspot/enviar` | `{coleccion, id, publicar}`: manda una nota aprobada a HubSpot (502 si HubSpot falla) |

**Fuentes**

| | |
|---|---|
| `GET/POST /api/trusted-urls` | Listar / agregar sin probar |
| `PATCH /api/trusted-urls/<url>` | Pausar o activar: `{"estado": "activo" \| "inactivo"}` |
| `DELETE /api/trusted-urls/<url>` | Eliminar |
| `GET/DELETE /api/suggested-urls` | Recomendaciones |
| `GET /api/trusted-urls-stats`, `GET /api/articulos-stats` | Números para el dashboard |

**Configuración**

| | |
|---|---|
| `GET/POST /api/scraping-config` | Hora, frecuencia, activación, artículos por fuente |
| `GET/POST /api/generacion-config` | Hora, frecuencia, activación, persona, tema |
| `GET/POST /api/fase2/config` | Categorías, regiones, clientes y puntapié de la nota automática. Solo cambia las claves que vienen |
| `GET/POST /api/providers` | Proveedor de IA |

**Notas**

| | |
|---|---|
| `GET /api/fase2/categorias`, `GET /api/fase2/regiones` | Opciones con la cantidad de ejemplos |
| `GET/POST /api/fase2/clientes`, `DELETE /api/fase2/clientes/<slug>` | Clientes |
| `GET /api/fase2/ultima-nota`, `GET /api/fase2/notas/<id>` | Leer una nota |
| `POST /api/evaluate-article` | Checklist de calidad a demanda |

Quedan endpoints viejos que el dashboard ya no usa y corren sin pasar por la cola: `/api/add-url`, `/api/discover-sources`, `/api/stream/*`, `/api/fase2/stream/*`, `/api/fase2/generar`, `/api/fase2/scrape` y los de Fase 1 (`/generar`, `/ultimo-articulo`).

## Para agregar un endpoint

1. Validá todo lo que viene del body antes de usarlo; si termina en el argv de un subproceso, usá `_listas()` (rechaza valores que empiezan con `-`).
2. Si ejecuta algo del pipeline, **encolalo** con `_encolar(...)`; no lo corras dentro de la request.
3. Errores inesperados: `return _error_interno(e)` (no filtra la excepción al cliente).
4. Agregá su test en `tests/` usando el fixture `api` (ver `tests/test_config_api.py`).
