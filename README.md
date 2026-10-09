# AfterDrive Intelligence

Sistema que **genera notas de blog B2B para AfterDrive by Alephee** (sector autopartes / aftermarket) de forma automática.

En resumen, hace tres cosas:

1. **Junta material**: scrapea noticias de fuentes confiables y notas reales del blog de AfterDrive.
2. **Filtra con IA**: descarta lo que no es del rubro autopartes y vectoriza (embeddings) lo que sirve.
3. **Redacta con IA**: un LLM escribe notas nuevas siguiendo el estilo del blog, que quedan guardadas para revisión.

Todo se maneja desde un dashboard web y además corre solo todos los días con un scheduler interno.

Este documento explica la arquitectura parte por parte para que alguien nuevo pueda entender el sistema y seguir desarrollándolo.

---

## Índice

1. [Vista general](#1-vista-general)
2. [Infraestructura y despliegue](#2-infraestructura-y-despliegue)
3. [Mapa del código](#3-mapa-del-código)
4. [Procesos (pipelines) paso a paso](#4-procesos-pipelines-paso-a-paso)
5. [Dónde se usa IA y de qué tipo](#5-dónde-se-usa-ia-y-de-qué-tipo)
6. [Base de datos (MongoDB)](#6-base-de-datos-mongodb)
7. [Configuración](#7-configuración)
8. [Tareas automáticas (scheduler)](#8-tareas-automáticas-scheduler)
9. [API (endpoints)](#9-api-endpoints)
10. [Cómo correrlo](#10-cómo-correrlo)
11. [Puntos de atención y deuda conocida](#11-puntos-de-atención-y-deuda-conocida)
12. [Otros archivos del repo](#12-otros-archivos-del-repo)

---

## 1. Vista general

```
                         ┌──────────────────────────────────────────────┐
                         │      Contenedor Docker (Render / local)      │
                         │                                              │
  Navegador ───────────► │  Flask + Gunicorn  (flask_api.py)            │
  (dashboard)            │   ├─ sirve el dashboard estático  (/)        │
                         │   ├─ API REST + streaming SSE     (/api/*)   │
                         │   └─ APScheduler (tareas diarias)            │
                         │                                              │
                         │  Scripts Python (scraping, generación, ...)  │
                         └───────┬──────────────┬───────────────┬───────┘
                                 │              │               │
                     ┌───────────▼───┐   ┌──────▼───────┐  ┌────▼─────────────────┐
                     │ Sitios web    │   │ MongoDB Atlas│  │ Proveedores de IA    │
                     │ (fuentes de   │   │ (DB          │  │ - LLM: OpenRouter /  │
                     │  noticias,    │   │ "afterdrive")│  │   NVIDIA / LM Studio │
                     │  blog         │   └──────────────┘  │ - Embeddings: NVIDIA │
                     │  AfterDrive,  │                     │   / LM Studio        │
                     │  DuckDuckGo)  │                     │ - Clasificador: Jev  │
                     └───────────────┘                     │   (TypeSafe)         │
                                                           └──────────────────────┘
```

| Pieza | Tecnología | Rol |
|---|---|---|
| Backend / API | Python 3.12, Flask, Gunicorn | Expone la API, sirve el dashboard, lanza los procesos |
| Scheduler | APScheduler (dentro del proceso Flask) | Scraping diario y generación diaria |
| Scraping | `requests` + Scrapling `StealthyFetcher` (Chromium headless) + Wayback Machine | Bajar HTML de los sitios |
| Extracción de texto | `trafilatura` + BeautifulSoup | Sacar título/cuerpo/fecha del HTML |
| Base de datos | MongoDB Atlas (`pymongo`) | Todo el estado del sistema |
| IA generativa (LLM) | API compatible con OpenAI: OpenRouter, NVIDIA Build o LM Studio local | Clasificar, redactar, evaluar |
| Embeddings | NVIDIA Build o LM Studio | Vectorizar textos para buscar similitud |
| Clasificador de relevancia | Jev (API de TypeSafe) | Decidir si un artículo es del rubro |
| Dashboard | HTML/CSS/JS estático (`express/src/public/index.html`) | Interfaz de operación |
| Hosting | Render (web service Docker, plan free) | Producción |

---

## 2. Infraestructura y despliegue

### Producción: Render (un solo contenedor)

- Definido en `render.yaml`. Es **un único web service Docker** (rama `Render_Testing`, plan free).
- El `Dockerfile` tiene dos etapas:
  1. Una imagen Node compila el dashboard (`express/`) y copia el HTML a `dist/public`.
  2. La imagen final de Python instala dependencias, instala Chromium (para Scrapling/patchright), copia el código y el dashboard compilado a `./static/`.
- Arranca con `gunicorn --workers 1 --threads 4 --timeout 1800 flask_api:app`. Se usa **un solo worker** a propósito: el scheduler vive dentro del proceso y con varios workers las tareas se duplicarían.
- Health check de Render: `GET /health` (no consulta Mongo ni la IA a propósito, para que una caída externa no haga reiniciar el contenedor en bucle).

**Problema del plan free y cómo se resuelve:** Render apaga el contenedor después de ~15 minutos sin tráfico externo, y si está apagado el scheduler no corre. Para eso:
- `flask_api.py` tiene un **keep-alive** que cada 5 minutos le pega a `RENDER_EXTERNAL_URL/health` (la URL pública; pegarle a localhost no cuenta como tráfico).
- Se recomienda además un monitor externo (UptimeRobot, cron-job.org) pegándole a `/health`, o directamente a `POST /api/run-automation` y `POST /api/run-generacion`.
- `render.yaml` también define dos **cron jobs de Render** que hacen esos POST, pero **solo funcionan en plan pago** (en free no existen).

### Local con Docker Compose (dos contenedores)

`docker-compose.yml` levanta:
- `scrapers`: el mismo backend Flask (puerto 5000). Monta los `.py` como volumen para desarrollo y apunta LM Studio a `host.docker.internal:1234`.
- `express`: un servidor Express/TypeScript (puerto 3000) que sirve el dashboard y hace de **proxy** hacia Flask.

> Express es la arquitectura vieja. En producción ya no se usa: Flask sirve el dashboard directamente. Ver [Puntos de atención](#11-puntos-de-atención-y-deuda-conocida).

### Perfiles de recursos (`resource_detector.py`)

Al arrancar, el sistema mide la RAM disponible del contenedor (leyendo cgroups) y elige un perfil que define cómo se scrapea:

| Perfil | RAM | Estrategia de descarga | Hilos |
|---|---|---|---|
| `alto` | > 1500 MB | Chromium → requests → Wayback | 4 |
| `medio` | 600–1500 MB | requests → Chromium (si hay bloqueo) → Wayback | 3 |
| `bajo` | < 600 MB | requests → Wayback (nunca Chromium) | 2 |

Se puede forzar con `FORCE_PROFILE=alto|medio|bajo` o `DISABLE_BROWSER=true` (fuerza `bajo`).

---

## 3. Mapa del código

| Archivo | Qué hace |
|---|---|
| `flask_api.py` | Punto de entrada. API REST, endpoints de streaming (SSE), sirve el dashboard, arranca scheduler y keep-alive. |
| `scheduler.py` | Tareas programadas: scraping de fuentes confiables y generación automática de notas. Lock para que no corran dos a la vez. |
| `config_store.py` | Lee/guarda la configuración del dashboard en la colección `config` (sobrevive reinicios/redeploys). |
| `db.py` | Conexión a MongoDB, definición de colecciones, índices de texto y `clasificar_y_guardar()` (clasificar + embeddings + guardar). |
| `scraper.py` | Scraper genérico de fuentes de noticias: descarga el listado, encuentra links a artículos y extrae cada uno. |
| `scraper_afterdrive.py` | Scraper del blog oficial `afterdrive.alephee.com/es/blog` por categoría (tag). Guarda los ejemplos para few-shot. |
| `regiones.py` | Clasifica un texto por región (Argentina, Brasil, México, Latam, Europa, China, Asia) **por palabras clave** (no usa IA). |
| `jev_clasificador.py` | Clasificador de relevancia con Jev (TypeSafe). Si no hay API key o falla, usa el LLM. |
| `lm_studio.py` | **Cliente de IA unificado.** Proveedores, modelos, reintentos/fallbacks, todos los prompts (clasificar, redactar con 5 personalidades, evaluar), embeddings y limpieza del texto generado. |
| `embeddings.py` | Similitud coseno y backfill de embeddings para artículos que no los tengan. |
| `generar_nota_fase2.py` | **Generador principal (Fase 2):** nota estilo AfterDrive por categorías, regiones, clientes y "puntapié a link". |
| `generar_articulo.py` | Generador anterior (Fase 1): artículo a partir de material agrupado por embeddings (RAG). |
| `add_url.py` | Prueba una URL nueva: la scrapea, clasifica y, si aprueba al menos un artículo, la da de alta como fuente confiable. |
| `discover_sources.py` | Busca fuentes candidatas en DuckDuckGo y guarda sugerencias (sin IA, por palabras clave). |
| `run_automation.py` | Wrapper CLI del scraping de fuentes confiables (lo usa el endpoint con streaming). |
| `resource_detector.py` | Detección de RAM/CPU y perfil de scraping. |
| `express/` | Dashboard (`src/public/index.html`) + proxy Express viejo (`src/index.ts`). |

---

## 4. Procesos (pipelines) paso a paso

### 4.1 Scraping de fuentes confiables (diario)

Es la ingesta de noticias del sector. Corre todos los días a las **08:30 UTC** (o a mano desde el dashboard).

```
trusted_urls (estado = "activo")
      │  por cada fuente
      ▼
scraper.py: baja la página de listado → detecta links de artículos
      │       (prioriza URLs con fecha /AAAA/MM/DD/, descarta login, tag, etc.)
      ▼
Descarga cada artículo en paralelo (estrategia según perfil) → trafilatura extrae
título, cuerpo, fecha  (se descartan cuerpos de < 100 caracteres)
      │
      ▼
Clasificación de relevancia (IA)  ── Jev, o LLM como respaldo
      │
      ├── rechazado ──► articulos_descartados (url + fecha)
      │
      └── aprobado ──► Embeddings (IA) en batch ──► articulos  (upsert por url)
      │
      ▼
trusted_urls.ultima_ejecucion = ahora
```

- Máximo de artículos por fuente: configurable (`max_articulos`, default 10).
- Si un sitio bloquea (Cloudflare, HTML vacío) se prueba con navegador headless y por último con la copia de **Wayback Machine**.

### 4.2 Alta de una fuente nueva (`add_url.py`)

Desde el dashboard ("Agregar URL Confiable"):
1. Scrapea la URL como listado.
2. Clasifica y guarda los artículos igual que en 4.1.
3. **Solo si al menos un artículo fue aprobado**, la URL queda en `trusted_urls` con `estado: "activo"`.

También existe `POST /api/trusted-urls` que la agrega directo, **sin** pasar por la prueba.

### 4.3 Descubrimiento de fuentes (`discover_sources.py`)

Busca en DuckDuckGo frases como "noticias autopartes latinoamerica", filtra los resultados por una lista de palabras clave del rubro y guarda hasta 30 sugerencias en `suggested_urls`. **No usa IA.** Las sugerencias se revisan a mano en el dashboard y, si sirven, se agregan con 4.2.

### 4.4 Ejemplos del blog AfterDrive (`scraper_afterdrive.py`)

Scrapea notas **reales** publicadas en el blog de AfterDrive, recorriendo cada categoría (tag): casos de éxito, autopartes, marketplaces, neumáticos, logística, etc. (16 categorías, definidas en `CATEGORIAS`).

Por cada nota guarda título, cuerpo (hasta 5000 caracteres), categoría y las **regiones detectadas por palabras clave** (`regiones.py`). Van a `afterdrive_ejemplos`.

Estas notas son el **material de referencia de estilo (few-shot)** del generador Fase 2. Se corre a mano desde el dashboard (no está en el scheduler).

### 4.5 Generación de notas Fase 2 (`generar_nota_fase2.py`) — el generador principal

Corre todos los días a las **14:00 UTC** usando la configuración guardada, o a mano desde la sección "Generador de Notas" del dashboard.

Parámetros:
- **Categorías** (obligatorio): de qué tratan las notas.
- **Regiones**: contextualizan la nota y **definen el idioma** (Brasil → portugués, China → mandarín, Asia → inglés, el resto → variantes de español).
- **Clientes**: se mencionan como casos reales (vienen de la colección `clientes`).
- **Puntapié a link**: la nota se arma para llevar al lector a una URL (más corta, 600–900 palabras, CTA con ese link). Sin esto, 900–1400 palabras con CTA a Alephee.
- **Persona**: la personalidad de redacción (ver 5.3).
- **Tema** (opcional).

Pasos:
1. Trae hasta 2 ejemplos reales por categoría de `afterdrive_ejemplos` (filtrando por región si se eligió), máximo 6.
2. Arma el *system prompt*: personalidad + reglas editoriales + instrucciones de categoría, región/idioma, clientes y puntapié.
3. Arma el mensaje con los ejemplos ("imitá el estilo, no copies el contenido").
4. Llama al LLM en streaming (temperatura 0.72, hasta 4000 tokens).
5. Limpia la salida: quita fences de markdown, y **descarta la respuesta si el modelo devolvió su razonamiento interno en vez del artículo** (pasa con algunos modelos "reasoning").
6. Post-procesa: elimina oraciones, secciones y conclusiones repetidas.
7. Calcula el embedding de la nota y la guarda en `notas_fase2`.

### 4.6 Generación de artículos Fase 1 (`generar_articulo.py`) — generador anterior

Es un pipeline tipo **RAG basado en embeddings**. Sigue disponible en el dashboard ("Generador de Articulos con IA").

1. Carga los documentos que tienen embedding.
2. Carga los embeddings de lo ya generado ("memoria" para no repetir temas).
3. **Sin tema**: elige como semilla el documento menos parecido a lo ya escrito y le suma sus vecinos más cercanos (similitud coseno ≥ 0.70, hasta 15) más una búsqueda de texto (`$text`) de Mongo.
   **Con tema**: vectoriza el tema y busca los documentos más similares (≥ 0.50); si no encuentra, usa búsqueda de texto.
4. Arma el contexto respetando un presupuesto de tokens (~26K).
5. El LLM redacta con la personalidad elegida.
6. **Filtro de calidad** por reglas (sin IA): rechaza si es muy corto, no tiene secciones `##`, repite oraciones, tiene secciones clonadas, CTA repetido, etc.
7. **Deduplicación**: si el embedding del artículo se parece ≥ 0.95 a uno anterior, se descarta.
8. Guarda en `articulos_generados` y marca los documentos usados con `usado_para_articulo: true`.

### 4.7 Evaluación de calidad (checklist)

Desde el modal de resultado del dashboard se puede pedir `POST /api/evaluate-article`. Un LLM revisa la nota contra 9 lineamientos (estructura, negritas, vocabulario de negocio, tono B2B, sin paywall, sin repeticiones, sin alucinaciones, sin obviedades, terminología correcta) y devuelve un JSON con verdadero/falso por cada uno. **No se guarda en la base**, es solo una ayuda para el revisor.

---

## 5. Dónde se usa IA y de qué tipo

| Proceso | Tipo de IA | Proveedor / modelo (default) | Qué hace | Si falla |
|---|---|---|---|---|
| Clasificar relevancia de artículos scrapeados | **Modelo clasificador** (devuelve probabilidad 0–1 + motivo) | Jev — API TypeSafe (`JEV_MODEL=jev-latest`) | Aprueba si el puntaje ≥ `JEV_THRESHOLD` (0.5) | Usa el LLM de abajo |
| Clasificar relevancia (respaldo) | **LLM** (chat, temperatura 0.1) | El proveedor activo (ver 5.1) | Responde `{"aprobado": bool, "razon": ...}` con reglas y ejemplos few-shot | Si el proveedor no responde: **aprueba todo** (modo degradado). Si responde JSON inválido: rechaza |
| Vectorizar artículos y notas | **Modelo de embeddings** | NVIDIA `nvidia/nemotron-3-embed-1b` (2048 dimensiones) o LM Studio `nomic-embed-text-v1.5` | Convierte texto en un vector para medir similitud | El documento se guarda sin `embedding` (se puede completar luego con `python embeddings.py`) |
| Redactar notas Fase 2 | **LLM** (chat en streaming, temp. 0.72) | Proveedor activo | Escribe la nota | Se reporta error, no se guarda nada |
| Redactar artículos Fase 1 | **LLM** (streaming, temp. 0.7) | Proveedor activo | Escribe el artículo a partir del contexto | Idem |
| Checklist de calidad | **LLM** (temp. 0.1) | Proveedor activo | Evalúa 9 lineamientos editoriales | Devuelve error al dashboard |
| Clasificación por región | *No es IA* | — | Conteo de palabras clave | — |
| Descubrimiento de fuentes | *No es IA* | — | Búsqueda + palabras clave | — |

### 5.1 Proveedores de LLM

Todos se hablan con la **misma API estilo OpenAI** (`/chat/completions`, `/embeddings`) usando `requests` (no el SDK de OpenAI). Se elige con `AI_PROVIDER` o desde el dashboard (queda guardado en Mongo):

| `AI_PROVIDER` | Dónde corre | Modelo principal | Modelo de respaldo |
|---|---|---|---|
| `openrouter` (**default en producción**) | Cloud | `mistralai/mistral-small-3.1-24b-instruct:free` | mismo |
| `nvidia` | Cloud (NVIDIA Build) | `moonshotai/kimi-k3` | `openai/gpt-oss-20b` |
| `local` | LM Studio en la máquina (puerto 1234) | `mistral-7b-instruct-v0.3` | — |

**OpenRouter no tiene endpoint de embeddings**, por eso existe `EMBEDDINGS_PROVIDER` (en producción: `nvidia`). Chat y embeddings pueden ir por proveedores distintos.

Manejo de errores en `lm_studio.py` → `_post()`:
- **429 (rate limit)**: reintenta con espera exponencial y prueba el modelo de respaldo.
- **404/410 (modelo dado de baja)**: prueba el respaldo una vez y si falla muestra un error con la lista de modelos disponibles del proveedor, para saber qué poner en la variable de entorno.
- Streaming: si el proveedor no manda nada en `STREAM_READ_TIMEOUT` segundos (180), se corta.

> Los modelos gratuitos cambian o se dan de baja seguido. Si la generación empieza a fallar con 404/410, casi siempre la solución es cambiar `OPENROUTER_MODEL` / `NVIDIA_MODEL` / `NVIDIA_EMB_MODEL`.

### 5.2 Prompts

Todos los prompts están en `lm_studio.py`:
- `_SYSTEM_EVALUAR`: clasificador de relevancia (qué aprobar/rechazar, ejemplos).
- `_REGLAS_UNIVERSALES`: 20 reglas editoriales comunes a todas las personalidades (no inventar cifras, terminología correcta, CTA obligatorio, formato, ortografía, etc.).
- `SISTEMAS_REDACTAR`: un system prompt por personalidad.
- `_SYSTEM_EVALUAR_CONTENIDO`: el checklist de calidad.

`generar_nota_fase2.py` agrega encima las instrucciones de categoría, región, idioma, clientes y puntapié.

### 5.3 Personalidades de redacción

| Persona | Enfoque |
|---|---|
| `analitico` | Explica un fenómeno técnico o de negocio usando los datos como ejemplo |
| `periodistico` | Nota informativa, tono neutral, pirámide invertida |
| `comercial` (default en Fase 2) | Vende una solución concreta al problema del lector |
| `divulgativo` | Explica didácticamente un solo concepto |
| `ejecutivo` | Visión estratégica de alto nivel (ROI, eficiencia) |

---

## 6. Base de datos (MongoDB)

Base: **`afterdrive`** en MongoDB Atlas (conexión con `MONGO_URI`). No hay esquema formal; estos son los campos que usa el código.

### Contenido de entrada

| Colección | Qué guarda | Quién escribe | Quién lee | Campos principales |
|---|---|---|---|---|
| `trusted_urls` | Fuentes de noticias confiables que se scrapean a diario | `add_url.py`, `POST /api/trusted-urls` | `scheduler.py` | `url`, `nombre_fuente`, `estado` (`"activo"`), `fecha_agregado`, `ultima_ejecucion` |
| `suggested_urls` | Fuentes candidatas encontradas por el descubrimiento | `discover_sources.py` | Dashboard | `url`, `titulo`, `snippet`, `keyword_match`, `keyword_busqueda`, `fecha_sugerida` |
| `articulos` | **Noticias scrapeadas que la IA aprobó** como relevantes | `db.clasificar_y_guardar()` (scheduler, add_url) | Dashboard (conteo, filtro de volumen), `embeddings.py` | `url` (clave), `titulo`, `cuerpo`, `fecha`, `fuente`, `embedding`, `usado_para_articulo` |
| `articulos_descartados` | **Noticias que la IA rechazó** (auditoría) | `db.clasificar_y_guardar()` | — | `url`, `fecha_descarte` (el motivo **no** se guarda, solo se imprime en el log) |
| `afterdrive_ejemplos` | **Notas reales del blog AfterDrive**, usadas como ejemplos de estilo | `scraper_afterdrive.py` | `generar_nota_fase2.py`, dashboard (conteos) | `url`, `titulo`, `cuerpo`, `categoria`, `tag_slug`, `regiones`, `region_principal`, `fecha`, `scrapeado_en` |
| `afterdrive` | Colección heredada de artículos de AfterDrive (versión anterior del proyecto) | Nadie en el código actual | `generar_articulo.py`, `embeddings.py` | `url`, `titulo`, `cuerpo`, `embedding` |
| `clientes` | Clientes que se pueden mencionar en las notas | Dashboard (`/api/fase2/clientes`) | `generar_nota_fase2.py` | `slug`, `nombre`, `descripcion`, `productos`, `sector`, `url` |

### Contenido generado

| Colección | Qué guarda | Quién escribe | Campos principales |
|---|---|---|---|
| `notas_fase2` | **Notas generadas por el generador principal** (manual o automático) | `generar_nota_fase2.py` | `contenido` (markdown), `categorias`, `regiones`, `clientes_mencionados`, `puntapie_url`, `persona`, `tema`, `ejemplos_usados` (urls), `embedding`, `generado_en` |
| `articulos_generados` | Artículos del generador Fase 1 | `generar_articulo.py` | `contenido`, `tema`, `fuentes`, `docs_usados`, `embedding`, `generado_en` |

Las notas generadas **no se publican solas**: quedan en la base y se ven en el dashboard. Hoy no existe un estado de aprobación/rechazo de notas ni conexión con HubSpot (ver `HUBSPOT_INTEGRATION_GUIDE.md` para la integración planificada).

### Configuración

| Colección | Qué guarda |
|---|---|
| `config` | Un documento por sección (`key` = `scraping`, `generacion`, `fase2`, `provider`) con su `value`. Es lo que se toca en el dashboard: activar/desactivar tareas, intervalos, artículos por fuente, persona, tema, categorías/regiones/clientes de la generación automática, proveedor de IA. |

### Índices

`db.crear_indices_texto()` crea índices de texto (idioma español) sobre `titulo` + `cuerpo` en `articulos`, `afterdrive` y `afterdrive_ejemplos`, y sobre `contenido` en `articulos_generados`. Se ejecuta al correr el generador Fase 1. La búsqueda vectorial **no** usa índices de Atlas: los embeddings se traen a memoria y se compara con coseno en Python.

---

## 7. Configuración

### Variables de entorno (`.env`, ver `.env.example`)

| Variable | Para qué |
|---|---|
| `MONGO_URI` | **Obligatoria.** Conexión a MongoDB Atlas |
| `AI_PROVIDER` | `openrouter`, `nvidia` o `local` |
| `EMBEDDINGS_PROVIDER` | Proveedor de embeddings (`nvidia` o `local`). Vacío = el mismo que `AI_PROVIDER` |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL` | OpenRouter |
| `NVIDIA_API_KEY`, `NVIDIA_MODEL`, `NVIDIA_FALLBACK_MODEL`, `NVIDIA_EMB_MODEL`, `NVIDIA_BASE_URL` | NVIDIA Build |
| `LMSTUDIO_URL`, `LMSTUDIO_MODEL`, `LMSTUDIO_EMB_MODEL` | LM Studio local |
| `TYPESAFE_API_KEY`, `JEV_ENDPOINT`, `JEV_MODEL`, `JEV_THRESHOLD` | Clasificador Jev. Sin key se usa el LLM |
| `RENDER_EXTERNAL_URL` (o `PUBLIC_BASE_URL`) | URL pública para el keep-alive |
| `FORCE_PROFILE`, `DISABLE_BROWSER` | Forzar perfil de scraping |
| `STREAM_READ_TIMEOUT` | Segundos sin respuesta antes de cortar una generación (180) |
| `AI_PROVIDER_OVERRIDE` | Si está definida, se ignora el proveedor guardado en Mongo |

### Configuración persistida (Mongo `config`)

Lo que se cambia en el dashboard se guarda en la colección `config` y tiene prioridad al reiniciar. En particular, **el proveedor de IA guardado en Mongo pisa a `AI_PROVIDER`** del entorno (salvo que exista `AI_PROVIDER_OVERRIDE`).

Defaults (`config_store.py`): scraping activo, cada 1 día, 10 artículos por fuente; generación activa, cada 1 día, persona `comercial`. **La generación automática no hace nada hasta que se guarden categorías** en la sección de Fase 2 del dashboard.

---

## 8. Tareas automáticas (scheduler)

`scheduler.py` usa APScheduler dentro del proceso de Flask:

| Tarea | Horario | Qué ejecuta |
|---|---|---|
| `trusted_scraping` | 08:30 UTC (05:30 ART), cada N días | Pipeline 4.1 |
| `auto_generacion` | 14:00 UTC (11:00 ART), cada N días | Pipeline 4.5 con la config guardada (`fase2` + `generacion`) |

- Un lock evita que scraping y generación corran a la vez dentro del scheduler (si se pisan, la segunda se saltea).
- Ambas se pueden desactivar o cambiar de intervalo desde el dashboard; el cambio se aplica en caliente y queda guardado.
- Se pueden disparar a mano: `POST /api/run-automation` y `POST /api/run-generacion`.
- Requieren que el contenedor esté despierto (ver keep-alive en la sección 2).

---

## 9. API (endpoints)

Todo en `flask_api.py`. Los endpoints `stream/*` devuelven el log del proceso en vivo (Server-Sent Events): ejecutan el script como subproceso y van mandando cada línea.

| Grupo | Endpoints |
|---|---|
| Salud | `GET /health`, `GET /api/health`, `GET /api/db-check` |
| Fuentes | `GET/POST /api/trusted-urls`, `DELETE /api/trusted-urls/<url>`, `GET /api/trusted-urls-stats`, `POST /api/add-url`, `POST /stream/add-url`, `POST /api/discover-sources`, `GET /api/suggested-urls` |
| Scraping | `GET/POST /api/scraping-config`, `POST /api/run-automation`, `POST /api/stream/run-automation`, `GET /api/articulos-stats`, `GET /api/check-volume?keyword=` |
| Generación Fase 2 | `GET /api/fase2/categorias`, `GET /api/fase2/regiones`, `POST /api/fase2/scrape` (+ `/api/fase2/stream/scrape`), `GET/POST/DELETE /api/fase2/clientes`, `POST /api/fase2/generar` (+ `/api/fase2/stream/generar`), `GET /api/fase2/ultima-nota`, `GET/POST /api/fase2/config` |
| Generación automática | `GET/POST /api/generacion-config`, `POST /api/run-generacion` |
| Generación Fase 1 | `POST /generar`, `POST /api/stream/generar`, `GET /ultimo-articulo` |
| IA | `GET/POST /api/providers`, `POST /api/evaluate-article` |

> La API **no tiene autenticación**. Cualquiera con la URL puede usar el dashboard y disparar procesos.

---

## 10. Cómo correrlo

### Docker (lo más parecido a producción)

```bash
cp .env.example .env      # completar al menos MONGO_URI y las keys del proveedor de IA
docker build -t afterdrive .
docker run --env-file .env -p 5000:5000 afterdrive
# Abrir http://localhost:5000
```

O con dos contenedores (Flask + Express): `docker compose up --build` y abrir `http://localhost:3000` (ver limitaciones de Express en la sección 11).

### Local sin Docker

```bash
pip install -r requirements.txt
python -m patchright install chromium      # navegador para el scraping con perfil alto/medio
cp .env.example .env

# Dashboard: Flask lo sirve desde ./static
mkdir -p static && cp express/src/public/index.html static/

python flask_api.py                         # http://localhost:5000
```

Para usar IA local hay que tener LM Studio corriendo en el puerto 1234 con un modelo de chat y uno de embeddings cargados, y `AI_PROVIDER=local`.

### Scripts por línea de comandos

```bash
python run_automation.py 10                                    # scraping de fuentes confiables
python add_url.py https://sitio.com/noticias                   # probar y dar de alta una fuente
python discover_sources.py                                     # buscar fuentes nuevas
python scraper_afterdrive.py --tags autopartes marketplaces --max 5
python generar_nota_fase2.py --categorias autopartes --regiones argentina --persona comercial
python generar_articulo.py --persona analitico --tema "frenos"
python embeddings.py                                           # completar embeddings faltantes
python lm_studio.py                                            # probar conexión con el proveedor de IA
```

---

## 11. Puntos de atención y deuda conocida

Cosas a tener en cuenta antes de seguir desarrollando:

- **Las noticias scrapeadas todavía no alimentan la generación principal.** La Fase 2 usa solo las notas del blog (`afterdrive_ejemplos`) como referencia de estilo, más lo que el modelo ya sabe. Las noticias de `articulos` no se pasan al prompt, así que los datos concretos de las notas dependen del modelo (riesgo de datos inventados pese a la regla "no inventes cifras").
- **El generador Fase 1 no lee la colección `articulos`.** En `generar_articulo.py`, la fuente `"general"` apunta a `articulos_generados` (lo que ya generó) y no a `articulos` (lo scrapeado). Probablemente es un error a corregir.
- La colección `afterdrive` ya no la escribe ningún proceso; es un resto de la versión anterior.
- `articulos_descartados` no guarda el motivo del rechazo ni el título, por lo que es difícil auditar al clasificador.
- Si el proveedor de IA no responde, el clasificador **aprueba todo** (modo degradado): puede entrar contenido irrelevante a `articulos`.
- No hay estado de revisión de notas (aprobada/rechazada/publicada) ni publicación en HubSpot todavía.
- El proxy Express (`express/src/index.ts`) no está actualizado: no reenvía endpoints nuevos como `/api/fase2/config`, `/api/generacion-config`, `/api/trusted-urls`, `/api/articulos-stats` ni `/api/run-generacion`. Con `docker compose` esas funciones del dashboard fallan. En producción no afecta porque Flask sirve el dashboard directo.
- En `lm_studio.py` hay funciones sin uso actualmente (`extraer_temas`, `research_contexto`).
- La API no tiene autenticación.
- El scheduler depende de que la instancia de Render esté despierta (plan free).

---

## 12. Otros archivos del repo

| Archivo / carpeta | Qué es |
|---|---|
| `HUBSPOT_INTEGRATION_GUIDE.md` | Guía para la futura publicación automática en HubSpot |
| `demo_mode.py` | Versión acelerada del pipeline para demos en vivo (< 60 s) |
| `test_pipeline.py`, `test_nvidia.py` | Pruebas manuales (Playwright contra la app local; conexión con NVIDIA) |
| `data/*.json` | Volcados de artículos de ejemplo |
| `AGENTS.md`, `opencode.json`, `.opencode/`, `.agents/` | Configuración de agentes de IA para desarrollo (OpenCode) y sincronización de specs desde Google Drive. No forman parte del sistema en producción |
| `render.yaml` | Blueprint de Render (web service + cron jobs de plan pago) |
