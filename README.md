# AfterDrive Intelligence

Sistema que **genera notas de blog B2B para AfterDrive by Alephee** (sector autopartes / aftermarket) de forma automática.

En resumen, hace tres cosas:

1. **Junta material**: scrapea noticias de fuentes confiables y notas reales publicadas en el blog de AfterDrive.
2. **Filtra con IA**: un LLM descarta lo que no es del rubro autopartes, y lo que sirve se vectoriza (embeddings).
3. **Redacta con IA**: un LLM escribe notas nuevas usando las noticias como fuente de datos y las notas del blog como referencia de estilo. Las notas quedan guardadas para revisión.

Todo se maneja desde un dashboard web con login, y además corre solo todos los días con un programador de tareas interno.

Este documento explica la arquitectura parte por parte para que alguien nuevo pueda entender el sistema y seguir desarrollándolo.

---

## Índice

0. [Estado de las ramas (leer primero)](#0-estado-de-las-ramas-leer-primero)
1. [Vista general](#1-vista-general)
2. [Infraestructura y despliegue](#2-infraestructura-y-despliegue)
3. [Mapa del código](#3-mapa-del-código)
4. [Procesos (pipelines) paso a paso](#4-procesos-pipelines-paso-a-paso)
5. [Dónde se usa IA y de qué tipo](#5-dónde-se-usa-ia-y-de-qué-tipo)
6. [Base de datos (MongoDB)](#6-base-de-datos-mongodb)
7. [Configuración](#7-configuración)
8. [Tareas automáticas y Corridas](#8-tareas-automáticas-y-corridas)
9. [Acceso y API](#9-acceso-y-api)
10. [Tutorial: clonar y ejecutar el proyecto](#10-tutorial-clonar-y-ejecutar-el-proyecto)
11. [Puntos de atención y deuda conocida](#11-puntos-de-atención-y-deuda-conocida)
12. [Limitaciones de infraestructura y mejoras a futuro](#12-limitaciones-de-infraestructura-y-mejoras-a-futuro)
13. [Otros archivos del repo](#13-otros-archivos-del-repo)

---

## 0. Estado de las ramas (leer primero)

El desarrollo activo **no está en `main`**. Hay dos ramas de trabajo que se separaron de un tronco común y todavía no se unificaron:

| Rama | Qué es | Particularidades |
|---|---|---|
| **`Render_Testing`** | **La que está en producción**: Render despliega desde esta rama (`render.yaml`). Es la referencia de este README | Código organizado en el paquete `afterdrive/` (`ingesta/`, `generacion/`, `ia/`). Sin Express. Las notas Fase 2 usan las noticias scrapeadas. La evaluación de calidad se guarda con cada nota. Dashboard con vista Cliente / Desarrollador |
| **`Front-Testing`** | Rediseño del dashboard y funciones de historial | Archivos `.py` sueltos en la raíz (sin el paquete `afterdrive/`). Agrega **historial** de artículos y notas, **estados borrador/publicado**, registro de **notas descartadas**, motivo de rechazo en los artículos descartados y **traductor** del dashboard a portugués. **Todavía no tiene** las noticias de contexto en la Fase 2 |
| `main` | Versión estable vieja | Muy atrás de las dos ramas anteriores: no tiene login, ni Corridas, ni los módulos `llm.py` / `saneo.py`. **No usar como referencia del código** |

Las dos ramas comparten: login de un usuario, módulo único de IA (`llm.py`), saneo de la salida del modelo (`saneo.py`), ingesta (`ingesta.py`), Corridas que nunca corren en paralelo (`corridas.py`), horarios configurables en hora argentina y tests con `pytest`.

En este README las rutas de archivos son las de `Render_Testing` (por ejemplo `afterdrive/ia/llm.py`). En `Front-Testing` el mismo archivo está en la raíz (`llm.py`). Cuando algo existe en una sola rama, se indica.

---

## 1. Vista general

```
                         ┌──────────────────────────────────────────────┐
                         │      Contenedor Docker (Render / local)      │
                         │                                              │
  Navegador ───────────► │  Flask + Gunicorn  (afterdrive/flask_api.py) │
  (dashboard,            │   ├─ login de un usuario (auth.py)           │
   login)                │   ├─ sirve el dashboard estático  (/)        │
                         │   ├─ API REST + streaming SSE     (/api/*)   │
                         │   └─ APScheduler (tareas diarias)            │
                         │                                              │
                         │  Corridas: scraping, generación, scripts     │
                         │  (una sola a la vez, corridas.py)            │
                         └───────┬──────────────┬───────────────┬───────┘
                                 │              │               │
                     ┌───────────▼───┐   ┌──────▼───────┐  ┌────▼──────────────────┐
                     │ Sitios web    │   │ MongoDB Atlas│  │ Proveedores de IA     │
                     │ - fuentes de  │   │ (base        │  │ (API estilo OpenAI)   │
                     │   noticias    │   │ "afterdrive")│  │ - LLM: OpenRouter     │
                     │ - blog        │   └──────────────┘  │   (prod), NVIDIA o    │
                     │   AfterDrive  │                     │   LM Studio local     │
                     │ - Wayback     │                     │ - Embeddings: NVIDIA  │
                     │ - DuckDuckGo  │                     │   o LM Studio         │
                     └───────────────┘                     └───────────────────────┘
```

| Pieza | Tecnología | Rol |
|---|---|---|
| Backend / API | Python 3.12, Flask, Gunicorn | Expone la API, sirve el dashboard, lanza las Corridas |
| Acceso | Sesión firmada de Flask, un usuario definido por variables de entorno | Protege el dashboard y la API |
| Programador de tareas | APScheduler (dentro del proceso Flask) | Scraping y generación diarios |
| Scraping | `requests` + Scrapling `StealthyFetcher` (Chromium headless) + Wayback Machine | Bajar HTML de los sitios |
| Extracción de texto | `trafilatura` + BeautifulSoup | Sacar título, cuerpo y fecha del HTML |
| Base de datos | MongoDB Atlas (`pymongo`) | Todo el estado del sistema |
| IA generativa (LLM) | OpenRouter (producción), NVIDIA Build o LM Studio | Clasificar artículos, redactar notas, evaluar calidad |
| Embeddings | NVIDIA Build (producción) o LM Studio | Vectorizar textos para medir similitud |
| Dashboard | HTML/CSS/JS sin framework (`express/src/public/`) | Interfaz de operación |
| Hosting | Render (web service Docker, plan free) | Producción |

> La carpeta se sigue llamando `express/` por historia: en `Render_Testing` ya no hay servidor Express, solo los archivos del dashboard.

---

## 2. Infraestructura y despliegue

### Producción: Render (un solo contenedor)

- Definido en `render.yaml`: **un único web service Docker**, rama `Render_Testing`, plan free.
- El `Dockerfile` instala las dependencias de Python y Chromium (para Scrapling/patchright), copia el paquete `afterdrive/` y el dashboard (`express/src/public/` → `static/`). En `Front-Testing` hay además una etapa de Node que compila el dashboard antes de copiarlo.
- Arranca con `gunicorn --workers 1 --threads 4 --timeout 1800 afterdrive.flask_api:app`. **Un solo worker es obligatorio**: el programador de tareas, el bloqueo de Corridas y el contador de intentos de login viven en memoria del proceso (ver `docs/adr/0001-corridas-serializadas-en-un-proceso.md`).
- Health check de Render: `GET /health`. A propósito no consulta Mongo ni la IA, para que una caída externa no haga reiniciar el contenedor en bucle.

**Problema del plan free y cómo se resuelve:** Render apaga el contenedor tras ~15 minutos sin tráfico externo, y si está apagado el programador de tareas no corre. Por eso:
- `flask_api.py` tiene un **keep-alive** que cada 5 minutos le pega a `RENDER_EXTERNAL_URL/health` (la URL pública; pegarle a localhost no cuenta como tráfico).
- Se recomienda un monitor externo (UptimeRobot, cron-job.org) pegándole a `/health`, o directamente a `POST /api/run-automation` y `POST /api/run-generacion` con el header `Authorization: Bearer <CRON_TOKEN>`.
- `render.yaml` define también dos **cron jobs de Render** que hacen esos POST con el token, pero **solo funcionan en plan pago**.

### Local

- `python -m afterdrive.flask_api` levanta todo en `http://localhost:5000`. Si no existe la carpeta `static/`, Flask sirve el dashboard directo desde `express/src/public/` (no hace falta compilar nada).
- `docker compose up --build` levanta el mismo contenedor con 2 GB de RAM, monta el código como volumen y apunta LM Studio a `host.docker.internal:1234`.

Detalle paso a paso en la [sección 10](#10-tutorial-clonar-y-ejecutar-el-proyecto).

### Perfiles de recursos (`afterdrive/ingesta/resource_detector.py`)

Al arrancar, el sistema mide la RAM disponible del contenedor (leyendo cgroups) y elige cómo se scrapea:

| Perfil | RAM | Estrategia de descarga | Hilos |
|---|---|---|---|
| `alto` | > 1500 MB | Chromium → requests → Wayback | 4 |
| `medio` | 600–1500 MB | requests → Chromium (si hay bloqueo) → Wayback | 3 |
| `bajo` | < 600 MB | requests → Wayback (nunca Chromium) | 2 |

**En Render free (512 MB) siempre queda en `bajo`.** Se puede forzar con `FORCE_PROFILE=alto|medio|bajo` o `DISABLE_BROWSER=true` (fuerza `bajo`).

---

## 3. Mapa del código

Rutas de `Render_Testing`. En `Front-Testing` los mismos archivos están en la raíz.

| Archivo | Qué hace |
|---|---|
| `afterdrive/flask_api.py` | Punto de entrada. API REST, endpoints con streaming (SSE), cabeceras de seguridad, sirve el dashboard, arranca el programador de tareas y el keep-alive |
| `afterdrive/auth.py` | Login de un único usuario, guardia de sesión en todos los endpoints, token para las corridas automáticas, bloqueo tras 5 intentos fallidos |
| `afterdrive/corridas.py` | **Único camino para ejecutar una Corrida** (scraping, generación o un script). Bloqueo para que nunca corran dos a la vez |
| `afterdrive/scheduler.py` | Agenda scraping y generación según la configuración guardada (hora argentina) |
| `afterdrive/config_store.py` | Lee y guarda la configuración del dashboard en la colección `config` |
| `afterdrive/db.py` | Conexión a MongoDB, colecciones e índices de texto |
| **Ingesta** | |
| `afterdrive/ingesta/scraper.py` | Scraper de fuentes de noticias: descarga el listado, encuentra links a artículos y extrae cada uno. Rechaza URLs que no sean http(s) públicas |
| `afterdrive/ingesta/ingesta.py` | Artículos scrapeados → clasificar → vectorizar → guardar (o descartar) |
| `afterdrive/ingesta/jev_clasificador.py` | Adaptador para el clasificador Jev (TypeSafe). **Hoy no se usa** (ver sección 5) |
| `afterdrive/ingesta/add_url.py` | Prueba una URL nueva y, si aprueba algún artículo, la da de alta como fuente confiable |
| `afterdrive/ingesta/discover_sources.py` | Busca sitios candidatos en DuckDuckGo y guarda sugerencias (sin IA) |
| `afterdrive/ingesta/embeddings.py` | Similitud coseno y completado de embeddings faltantes |
| `afterdrive/ingesta/run_automation.py` | Scraping de fuentes confiables desde línea de comandos |
| `afterdrive/ingesta/resource_detector.py` | Detección de RAM/CPU y perfil de scraping |
| **Generación** | |
| `afterdrive/generacion/generar_nota_fase2.py` | **Generador principal**: nota estilo AfterDrive por categorías, regiones, clientes y puntapié |
| `afterdrive/generacion/contexto_noticias.py` | Elige qué noticias scrapeadas alimentan cada nota (solo `Render_Testing`) |
| `afterdrive/generacion/scraper_afterdrive.py` | Scraper del blog oficial de AfterDrive por categoría; guarda los ejemplos de estilo |
| `afterdrive/generacion/regiones.py` | Clasifica un texto por región **por palabras clave** (no usa IA) |
| `afterdrive/generacion/generar_articulo.py` | Generador anterior (Fase 1) basado en embeddings |
| **IA** | |
| `afterdrive/ia/llm.py` | **Único lugar que habla con los proveedores de IA**: perfiles por proveedor, reintentos, modelos de respaldo, streaming, embeddings |
| `afterdrive/ia/redaccion.py` | Prompts de redacción: 5 personas + voz según la región (solo `Render_Testing`; en `Front-Testing` los prompts siguen en `lm_studio.py`) |
| `afterdrive/ia/lm_studio.py` | Prompts y tareas de IA: clasificar artículos, evaluar calidad, redactar Fase 1. El nombre es histórico; no es solo para LM Studio |
| `afterdrive/ia/saneo.py` | Convierte la respuesta cruda del modelo en una nota publicable, o la rechaza con un motivo |
| **Solo en `Front-Testing`** | |
| `historial.py` | Consulta paginada de artículos y notas (aprobados y descartados) y cambio de estado borrador/publicado |
| `express/src/public/historial.js`, `traductor.js`, `workspace.*` | Historial, traductor a portugués y nuevo diseño del dashboard |
| **Dashboard** | |
| `express/src/public/index.html`, `login.html` | Dashboard y pantalla de login |

`CONTEXT.md` define el vocabulario del proyecto (Corrida, Nota, Ejemplo, Persona, Puntapié, Saneo, etc.); conviene leerlo.

---

## 4. Procesos (pipelines) paso a paso

### 4.1 Scraping de fuentes confiables (diario)

Es la ingesta de noticias del sector. Corre por defecto todos los días a las **05:30 (hora argentina)**; la hora se cambia desde el dashboard. También se puede lanzar a mano.

```
trusted_urls (estado = "activo")
      │  por cada fuente
      ▼
scraper.py: baja la página de listado → detecta links de artículos
      │       (prioriza URLs con fecha /AAAA/MM/DD/, descarta login, tag, etc.)
      ▼
Descarga cada artículo en paralelo (según perfil) → trafilatura extrae título,
cuerpo y fecha  (se descartan cuerpos de < 100 caracteres)
      │       si el sitio está caído o bloquea → copia de Wayback Machine
      ▼
ingesta.py → Clasificación de relevancia con el LLM
      │
      ├── rechazado ──► articulos_descartados
      │
      └── aprobado ──► Embeddings en lote ──► articulos  (upsert por url)
      │
      ▼
trusted_urls.ultima_ejecucion = ahora
```

- Máximo de artículos por fuente: configurable (`max_articulos`, default 10).
- Si el origen de un dominio no respondió una vez en la corrida, el resto de sus artículos va directo a Wayback.

### 4.2 Alta de una fuente nueva (`add_url.py`)

Desde el dashboard:
1. Scrapea la URL como listado.
2. Clasifica y guarda los artículos igual que en 4.1.
3. **Solo si al menos un artículo fue aprobado**, la URL queda en `trusted_urls` con `estado: "activo"`.

También existe `POST /api/trusted-urls`, que la agrega directo **sin** esa prueba.

### 4.3 Descubrimiento de fuentes (`discover_sources.py`)

Busca en DuckDuckGo frases como "noticias autopartes latinoamerica", filtra por palabras clave del rubro, excluye redes sociales y marketplaces, y guarda hasta 30 sugerencias **por sitio** (una por dominio) en `suggested_urls`. **No usa IA.** Desde el dashboard cada sugerencia se agrega como fuente (4.2) o se descarta.

### 4.4 Ejemplos del blog AfterDrive (`scraper_afterdrive.py`)

Scrapea notas **reales** del blog de AfterDrive recorriendo sus 16 categorías (casos de éxito, autopartes, marketplaces, neumáticos, logística, etc.). Por cada nota guarda título, cuerpo (hasta 5000 caracteres), categoría y las **regiones detectadas por palabras clave**. Van a `afterdrive_ejemplos` y son la **referencia de estilo** del generador. Se corre a mano desde el dashboard.

### 4.5 Generación de notas Fase 2 (`generar_nota_fase2.py`): el generador principal

Corre por defecto todos los días a las **11:00 (hora argentina)** con la configuración guardada, o a mano desde el dashboard.

Parámetros:
- **Categorías** (obligatorio): de qué trata la nota.
- **Regiones**: contextualizan la nota y definen el idioma y el trato (Brasil → portugués, China → mandarín, Asia → inglés, Argentina o sin región → español rioplatense con voseo, otras regiones de habla hispana → español neutro con tuteo).
- **Clientes**: se mencionan como casos reales (colección `clientes`).
- **Puntapié**: la nota se arma para llevar al lector a una URL (600–900 palabras, CTA con ese link). Sin puntapié: 900–1400 palabras con CTA a Alephee.
- **Persona**: estilo de redacción (ver 5.3).
- **Tema** (opcional).

Pasos en `Render_Testing`:
1. **Noticias de contexto** (`contexto_noticias.py`): toma las 200 noticias más recientes de `articulos` y elige las 5 más útiles combinando similitud con el pedido (embeddings, 65 %), recencia (25 %, pierde la mitad del peso cada 10 días) y que no se hayan usado antes (10 %). Son **la única fuente de cifras, empresas y casos** que se le permite usar al modelo.
2. **Referencias de estilo**: hasta 2 notas reales por categoría de `afterdrive_ejemplos` (filtrando por región si se eligió).
3. **Prompt**: system prompt de `redaccion.py` (persona + voz de la región) ajustado al proveedor activo, más el pedido con noticias y referencias.
4. **Generación** con el LLM en streaming.
5. **Saneo** (`saneo.py`): quita envoltorios JSON, fences de markdown y texto degenerado; **descarta la respuesta si el modelo escribió su razonamiento en vez de la nota**; elimina oraciones, secciones y CTA repetidos.
6. **Evaluación de calidad** automática (checklist de 9 puntos, ver 4.7) que se guarda con la nota.
7. Embedding de la nota, guardado en `notas_fase2` y las noticias usadas quedan marcadas con `usado_para_articulo: true`.

En `Front-Testing` el flujo es el anterior: sin noticias de contexto (el modelo escribe solo con categorías y ejemplos de estilo) y sin evaluación automática. A cambio, si el saneo descarta la nota, el texto crudo y el motivo se guardan en `notas_descartadas`, y cada nota nace con `estado: "borrador"`.

### 4.6 Generación de artículos Fase 1 (`generar_articulo.py`): generador anterior

Pipeline basado en embeddings. En `Render_Testing` ya no aparece en el dashboard, pero sigue disponible por API (`/generar`, `/api/stream/generar`) y por línea de comandos.

1. Carga los documentos con embedding y los embeddings de lo ya generado (para no repetir temas).
2. **Sin tema**: elige como semilla el documento menos parecido a lo ya escrito y le suma sus vecinos más cercanos (similitud coseno ≥ 0.70, hasta 15) más una búsqueda de texto de Mongo. **Con tema**: busca los documentos más similares al tema (≥ 0.50).
3. Arma el contexto con un presupuesto de tokens, redacta con el LLM y sanea.
4. Filtro de calidad por reglas (largo, secciones, repeticiones) y deduplicación (descarta si se parece ≥ 0.95 a uno anterior).
5. Guarda en `articulos_generados`.

> Tiene un error conocido en su origen de datos: ver [sección 11](#11-puntos-de-atención-y-deuda-conocida).

### 4.7 Evaluación de calidad (checklist)

Un LLM revisa la nota contra 9 lineamientos (estructura, negritas, vocabulario de negocio, tono B2B, sin paywall, sin repeticiones, sin alucinaciones, sin obviedades, terminología correcta) y devuelve verdadero/falso por cada uno más un comentario. En `Render_Testing` se ejecuta al generar y se guarda en el campo `evaluacion` de la nota. También se puede pedir a mano con `POST /api/evaluate-article`.

---

## 5. Dónde se usa IA y de qué tipo

| Proceso | Tipo de IA | Proveedor / modelo en producción | Qué hace | Si falla |
|---|---|---|---|---|
| Clasificar relevancia de artículos scrapeados | **LLM** (chat, temperatura 0.1) | OpenRouter `mistralai/mistral-small-3.1-24b-instruct:free` | Responde `{"aprobado": bool, "razon": ...}` siguiendo reglas y 5 ejemplos (aprobar repuestos, rechazar 0 km, seguros, contenido para consumidor final, alucinaciones) | Si el proveedor no responde o la llamada falla: **aprueba** (modo degradado, para no perder artículos). Si responde algo que no es JSON: **rechaza** |
| Vectorizar artículos, notas y consultas | **Modelo de embeddings** | NVIDIA `nvidia/nemotron-3-embed-1b` (vectores de 2048 números) | Convierte texto en un vector para medir similitud | El documento se guarda sin `embedding`; la selección de noticias cae a "las más recientes". Se completa después con `embeddings.py` |
| Redactar notas Fase 2 | **LLM** (streaming) | OpenRouter (ídem) | Escribe la nota | Se informa el error y no se guarda nada (en `Front-Testing` el descarte queda en `notas_descartadas`) |
| Redactar artículos Fase 1 | **LLM** (streaming) | Proveedor activo | Escribe el artículo a partir del contexto | Ídem |
| Checklist de calidad | **LLM** (temperatura 0.1) | Proveedor activo | Evalúa 9 lineamientos editoriales | La nota se guarda igual, con `evaluacion: null` |
| Clasificación por región | *No es IA* | — | Conteo de palabras clave | — |
| Descubrimiento de fuentes | *No es IA* | — | Búsqueda + palabras clave | — |
| Traductor del dashboard a portugués (`Front-Testing`) | Servicio externo (widget de Google Translate en el navegador) | — | Traduce la interfaz y el contenido mostrado | La página sigue en español |

> **Sobre Jev (TypeSafe):** el código tiene la estructura para usar Jev como primer clasificador (`jev_clasificador.py`), con el LLM como respaldo. **Hoy no se usa**: no hay `TYPESAFE_API_KEY` configurada en producción, y sin esa variable el adaptador se saltea y clasifica directamente el LLM. Si algún día se activa, alcanza con definir `TYPESAFE_API_KEY` (y opcionalmente `JEV_THRESHOLD`).

### 5.1 Proveedores de LLM (`afterdrive/ia/llm.py`)

Todos se hablan con la **misma API estilo OpenAI** (`/chat/completions`, `/embeddings`) usando `requests`. El proveedor se elige con `AI_PROVIDER` o desde el dashboard (queda guardado en Mongo). Cada proveedor es un **perfil** con su URL, modelo, modelo de respaldo y ajustes de redacción:

| `AI_PROVIDER` | Dónde corre | Modelo principal | Respaldo | Ajustes de redacción |
|---|---|---|---|---|
| `openrouter` (**producción**) | Cloud | `mistralai/mistral-small-3.1-24b-instruct:free` | el mismo | temperatura 0.55, 4000 tokens |
| `nvidia` | Cloud (NVIDIA Build) | `moonshotai/kimi-k3` | `openai/gpt-oss-20b` | temperatura 0.6, 16000 tokens (son modelos que "razonan" antes de escribir) + instrucción extra para que no escriban su razonamiento |
| `local` | LM Studio en la máquina (puerto 1234) | `mistral-7b-instruct-v0.3` | — | temperatura 0.45, prompt compacto y menos ejemplos (los modelos chicos pierden instrucciones con prompts largos) |

Los ajustes de redacción por proveedor son de `Render_Testing`; en `Front-Testing` la Fase 2 usa temperatura 0.72 y 4000 tokens para todos.

- **OpenRouter no tiene endpoint de embeddings**, por eso existe `EMBEDDINGS_PROVIDER` (en producción `nvidia`). Chat y embeddings van por proveedores distintos.
- No se puede elegir `local` si LM Studio no responde (evita dejar la generación programada fallando en Render).
- Manejo de errores: **429** (límite de uso) → prueba el modelo de respaldo y reintenta con espera creciente. **404/410** (modelo dado de baja) → prueba el respaldo y, si falla, muestra un error con la lista de modelos disponibles hoy en ese proveedor. Si en streaming no llega nada en `STREAM_READ_TIMEOUT` segundos (180), corta. Si el modelo gastó todos los tokens razonando sin escribir, reintenta con el respaldo.
- Solo se toma el campo `content` de la respuesta, nunca el `reasoning_content` de los modelos que razonan.

> Los modelos gratuitos cambian o se dan de baja seguido. Si la generación empieza a fallar con 404/410, casi siempre la solución es cambiar `OPENROUTER_MODEL` / `NVIDIA_MODEL` / `NVIDIA_EMB_MODEL`.

### 5.2 Prompts

- Clasificador y checklist de calidad: `afterdrive/ia/lm_studio.py`.
- Redacción: `afterdrive/ia/redaccion.py` arma el system prompt con piezas comunes (identidad, audiencia, reglas sobre datos, oficio, formato, cierre) + el bloque de la persona + la voz de la región. Regla clave: **no inventar cifras, empresas ni casos; los hechos salen solo de las noticias de contexto**.
- `generar_nota_fase2.py` agrega encima región, categorías y clientes.

### 5.3 Personas de redacción

| Persona | Enfoque |
|---|---|
| `analitico` | Explica un fenómeno técnico o de negocio a partir de las noticias |
| `periodistico` | Cuenta una novedad con pirámide invertida |
| `comercial` (default) | Vende una solución concreta al problema del lector |
| `divulgativo` | Explica didácticamente un solo concepto |
| `ejecutivo` | Visión de alto nivel para quienes deciden |

---

## 6. Base de datos (MongoDB)

Base **`afterdrive`** en MongoDB Atlas (`MONGO_URI`). No hay esquema formal; estos son los campos que usa el código. Las colecciones se crean solas al primer uso.

### Contenido de entrada

| Colección | Qué guarda | Quién escribe | Quién lee | Campos principales |
|---|---|---|---|---|
| `trusted_urls` | Fuentes de noticias confiables que se scrapean | `add_url.py`, `POST /api/trusted-urls` | Corrida de scraping | `url`, `nombre_fuente`, `estado` (`"activo"`), `fecha_agregado`, `ultima_ejecucion` |
| `suggested_urls` | Sitios candidatos encontrados por el descubrimiento | `discover_sources.py` | Dashboard | `url` (raíz del sitio), `dominio`, `ejemplo_url`, `titulo`, `snippet`, `keyword_match`, `fecha_sugerida` |
| `articulos` | **Noticias scrapeadas que la IA aprobó** | `ingesta.py` | Generación Fase 2 (noticias de contexto), dashboard | `url` (clave), `titulo`, `cuerpo`, `fecha`, `fuente`, `embedding`, `usado_para_articulo` |
| `articulos_descartados` | **Noticias que la IA rechazó** | `ingesta.py` | Historial (`Front-Testing`) | `Render_Testing`: solo `url` y `fecha_descarte`. `Front-Testing`: además `titulo`, `cuerpo`, `fuente`, `fecha` y `razon` |
| `afterdrive_ejemplos` | **Notas reales del blog AfterDrive** (referencia de estilo) | `scraper_afterdrive.py` | Generación Fase 2 | `url`, `titulo`, `cuerpo`, `categoria`, `tag_slug`, `regiones`, `region_principal`, `scrapeado_en` |
| `afterdrive` | Colección heredada de una versión anterior | Nadie | `generar_articulo.py` | `url`, `titulo`, `cuerpo`, `embedding` |
| `clientes` | Clientes que se pueden mencionar en las notas | Dashboard | Generación Fase 2 | `slug`, `nombre`, `descripcion`, `productos`, `sector`, `url` |

### Contenido generado

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `notas_fase2` | **Notas del generador principal** (manual o automático) | `contenido` (markdown), `categorias`, `regiones`, `clientes_mencionados`, `puntapie_url`, `persona`, `tema`, `ejemplos_usados`, `embedding`, `generado_en`. En `Render_Testing` además: `fuentes` (noticias usadas), `evaluacion` (checklist), `proveedor`. En `Front-Testing` además: `estado` (`borrador`/`publicado`), `publicado_en` |
| `articulos_generados` | Artículos del generador Fase 1 | `contenido`, `tema`, `fuentes`, `docs_usados`, `embedding`, `generado_en` (+ `estado` en `Front-Testing`) |
| `notas_descartadas` (solo `Front-Testing`) | Notas que el modelo escribió pero el saneo o el filtro de calidad descartó | `origen` (`fase1`/`fase2`), `contenido` (crudo, hasta 20000 caracteres), `motivo` y los parámetros del pedido |

Las notas **no se publican solas**: quedan en la base y se revisan en el dashboard. En `Front-Testing` se pueden marcar como publicadas a mano; todavía no hay conexión con HubSpot (ver `docs/hubspot-integration.md`).

### Configuración

| Colección | Qué guarda |
|---|---|
| `config` | Un documento por sección (`key` = `scraping`, `generacion`, `fase2`, `provider`) con su `value`: activar/desactivar tareas, hora e intervalo, artículos por fuente, persona, tema, categorías/regiones/clientes de la generación automática y proveedor de IA |

### Índices y búsqueda vectorial

`db.crear_indices_texto()` crea índices de texto en español sobre `articulos`, `afterdrive`, `afterdrive_ejemplos` y `articulos_generados`; se ejecuta al correr el generador Fase 1. **No se usan índices vectoriales de Atlas**: los embeddings se traen a memoria y la similitud se calcula en Python.

---

## 7. Configuración

### Variables de entorno (`.env`, ver `.env.example`)

| Variable | Para qué |
|---|---|
| `MONGO_URI` | **Obligatoria.** Conexión a MongoDB Atlas |
| `ADMIN_USER`, `ADMIN_PASSWORD_HASH`, `SECRET_KEY` | **Obligatorias para entrar al dashboard.** Si falta alguna, nadie puede loguearse (ver 10, paso 4) |
| `CRON_TOKEN` | Token para disparar las corridas automáticas por HTTP (cron o monitor externo) |
| `AI_PROVIDER` | `openrouter`, `nvidia` o `local` |
| `EMBEDDINGS_PROVIDER` | Proveedor de embeddings (`nvidia` o `local`). Vacío = el mismo que `AI_PROVIDER` |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL` | OpenRouter |
| `NVIDIA_API_KEY`, `NVIDIA_MODEL`, `NVIDIA_FALLBACK_MODEL`, `NVIDIA_EMB_MODEL`, `NVIDIA_BASE_URL` | NVIDIA Build |
| `LMSTUDIO_URL`, `LMSTUDIO_MODEL`, `LMSTUDIO_EMB_MODEL` | LM Studio local |
| `TYPESAFE_API_KEY`, `JEV_ENDPOINT`, `JEV_MODEL`, `JEV_THRESHOLD` | Clasificador Jev. **Hoy sin configurar** (no se usa) |
| `RENDER_EXTERNAL_URL` (o `PUBLIC_BASE_URL`) | URL pública para el keep-alive |
| `SCHEDULER_TZ` | Zona horaria de las tareas (default `America/Argentina/Buenos_Aires`) |
| `REDACCION_TEMPERATURA` | Pisa la temperatura de redacción del proveedor (`Render_Testing`) |
| `STREAM_READ_TIMEOUT` | Segundos sin respuesta antes de cortar una generación (180) |
| `FORCE_PROFILE`, `DISABLE_BROWSER` | Forzar perfil de scraping |
| `AI_PROVIDER_OVERRIDE` | Si está definida, se ignora el proveedor guardado en Mongo |

### Configuración guardada (Mongo `config`)

Lo que se cambia en el dashboard se guarda en `config` y sobrevive reinicios y redeploys. **El proveedor de IA guardado en Mongo pisa a `AI_PROVIDER`** del entorno, salvo que exista `AI_PROVIDER_OVERRIDE`.

Valores por defecto (`config_store.py`): scraping activo a las 05:30, cada 1 día, 10 artículos por fuente; generación activa a las 11:00, cada 1 día, persona `comercial`. **La generación automática no hace nada hasta que se guarden categorías** en el dashboard.

---

## 8. Tareas automáticas y Corridas

### Programador de tareas (`scheduler.py`)

| Tarea | Hora por defecto (Argentina) | Qué ejecuta |
|---|---|---|
| `scraping` | 05:30, cada N días | Pipeline 4.1 |
| `generacion` | 11:00, cada N días | Pipeline 4.5 con la configuración guardada |

Hora, intervalo y activación se cambian desde el dashboard y se aplican en el momento. También se pueden lanzar a mano (`POST /api/run-automation`, `POST /api/run-generacion`). Requieren que el contenedor esté despierto (sección 2).

### Corridas (`corridas.py`)

Toda ejecución del pipeline (programada, botón del dashboard o endpoint con streaming) pasa por `corridas.py`, que toma un bloqueo en memoria. **Si ya hay una Corrida en curso, la nueva no espera: se rechaza con un aviso de "ocupado"** (HTTP 409 en los endpoints de disparo). El motivo es la RAM: en Render free dos Corridas simultáneas se quedan sin memoria.

- Las Corridas programadas y los botones de disparo corren **dentro del proceso** (en un hilo).
- Las Corridas con salida en vivo (SSE) corren el script como **subproceso** y van mandando cada línea; si el navegador corta la conexión, el subproceso se mata.

---

## 9. Acceso y API

### Login (`auth.py`)

- Un solo usuario administrador, definido por `ADMIN_USER` y `ADMIN_PASSWORD_HASH` (hash scrypt, **nunca la contraseña en texto**). La sesión se firma con `SECRET_KEY` y dura 7 días.
- Todos los endpoints exigen sesión, salvo `/`, `/health` y `/api/login`. Sin sesión responden 401 y el dashboard vuelve a la pantalla de login.
- `POST /api/run-automation` y `POST /api/run-generacion` aceptan además `Authorization: Bearer <CRON_TOKEN>` para los disparos automáticos.
- 5 intentos fallidos desde la misma IP bloquean el login 15 minutos.
- Además: cabeceras de seguridad (CSP, `X-Frame-Options`, etc.), cookie `HttpOnly` y `SameSite=Strict`, y el scraper rechaza URLs internas o no http(s) para evitar SSRF.

### Endpoints (`flask_api.py`)

Los endpoints `stream/*` devuelven el log del proceso en vivo (Server-Sent Events).

| Grupo | Endpoints |
|---|---|
| Salud y acceso | `GET /health`, `GET /api/health`, `GET /api/db-check`, `POST /api/login`, `POST /api/logout` |
| Fuentes | `GET/POST /api/trusted-urls`, `DELETE /api/trusted-urls/<url>`, `GET /api/trusted-urls-stats`, `POST /api/add-url`, `POST /stream/add-url`, `POST /api/discover-sources`, `GET/DELETE /api/suggested-urls` |
| Scraping | `GET/POST /api/scraping-config`, `POST /api/run-automation`, `POST /api/stream/run-automation`, `GET /api/articulos-stats`, `GET /api/check-volume?keyword=` |
| Generación Fase 2 | `GET /api/fase2/categorias`, `GET /api/fase2/regiones`, `POST /api/fase2/scrape` (+ `/api/fase2/stream/scrape`), `GET/POST/DELETE /api/fase2/clientes`, `POST /api/fase2/generar` (+ `/api/fase2/stream/generar`), `GET /api/fase2/ultima-nota`, `GET /api/fase2/notas`, `GET /api/fase2/notas/<id>` (estos dos últimos solo `Render_Testing`), `GET/POST /api/fase2/config` |
| Generación automática | `GET/POST /api/generacion-config`, `POST /api/run-generacion` |
| Generación Fase 1 | `POST /generar`, `POST /api/stream/generar`, `GET /ultimo-articulo` |
| Historial (solo `Front-Testing`) | `GET /api/historial/resumen`, `GET /api/historial/<seccion>`, `GET /api/historial/<seccion>/<coleccion>/<id>`, `POST /api/historial/estado` |
| IA | `GET/POST /api/providers`, `POST /api/evaluate-article` |

---

## 10. Tutorial: clonar y ejecutar el proyecto

Esta guía va de cero a tener el sistema generando una nota. Hay dos formas de correrlo: **local con Python** (la más cómoda para desarrollar) o **con Docker** (igual que producción). Los pasos 1 a 4 son comunes a las dos. Los comandos son para `Render_Testing`; las diferencias con `Front-Testing` se indican.

### Paso 1: instalar lo necesario

| Herramienta | Para qué | Obligatoria |
|---|---|---|
| [Git](https://git-scm.com/downloads) | Clonar el repo | Sí |
| [Python 3.12](https://www.python.org/downloads/) (mínimo 3.11) | Correr el backend | Sí, si corrés local |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Correr en contenedor | Solo si usás Docker |
| [LM Studio](https://lmstudio.ai/) | IA local sin APIs externas | No (opcional) |

> En Windows, al instalar Python marcá la opción **"Add python.exe to PATH"**.

### Paso 2: clonar el repositorio y elegir la rama

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/AfterDrive_Intelligence.git
cd AfterDrive_Intelligence
git checkout Render_Testing        # la rama de producción (ver sección 0)
```

### Paso 3: crear la base de datos en MongoDB Atlas

Si ya tenés acceso al cluster del proyecto, pedí la cadena de conexión y pasá al paso 4.

1. Crear una cuenta en [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) y un cluster gratuito (**M0**).
2. **Database Access** → crear un usuario con contraseña.
3. **Network Access** → agregar tu IP (o `0.0.0.0/0` para permitir cualquier origen; necesario para Render, que no tiene IP fija en el plan free).
4. **Connect → Drivers** → copiar la cadena `mongodb+srv://usuario:password@cluster.xxxxx.mongodb.net/...`.

No hace falta crear la base ni las colecciones: se crean solas.

### Paso 4: API keys, usuario del dashboard y `.env`

| Servicio | Para qué | Dónde se saca |
|---|---|---|
| OpenRouter | LLM de redacción y clasificación (producción) | <https://openrouter.ai/keys> |
| NVIDIA Build | Embeddings (y LLM alternativo) | <https://build.nvidia.com> → "Get API Key" |

```bash
cp .env.example .env        # en Windows (cmd): copy .env.example .env
```

Generar el hash de la contraseña del dashboard y las dos claves secretas:

```bash
python -c "from getpass import getpass; from werkzeug.security import generate_password_hash as g; print(g(getpass('Contraseña: ')))"
python -c "import secrets; print(secrets.token_urlsafe(48))"     # SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"     # CRON_TOKEN (otro valor)
```

(El primer comando necesita Flask instalado; si todavía no lo tenés, hacé antes el paso 5A hasta `pip install`.)

Completar en `.env` como mínimo:

```env
MONGO_URI=mongodb+srv://usuario:password@cluster.xxxxx.mongodb.net/?appName=AfterDrive
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
EMBEDDINGS_PROVIDER=nvidia
NVIDIA_API_KEY=nvapi-...
ADMIN_USER=admin
ADMIN_PASSWORD_HASH='scrypt:32768:8:1$...'     # entre comillas simples: el hash tiene signos $
SECRET_KEY=...
CRON_TOKEN=...
```

`TYPESAFE_API_KEY` se deja sin completar (Jev no se usa). El `.env` está en `.gitignore`: **nunca lo subas al repo** (el repo es público).

### Paso 5A: ejecutar local con Python

```bash
# 1. Crear y activar un entorno virtual
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
.venv\Scripts\activate             # Windows

# 2. Instalar dependencias (requirements-dev.txt agrega pytest y ruff)
pip install -r requirements.txt -r requirements-dev.txt

# 3. (Opcional) Chromium para el scraping con navegador.
#    Solo se usa si hay más de 600 MB de RAM libre (perfil medio/alto).
python -m patchright install chromium

# 4. Levantar el servidor
python -m afterdrive.flask_api     # en Front-Testing: python flask_api.py
```

Abrir <http://localhost:5000> y entrar con el usuario y contraseña del paso 4. En la consola deberían aparecer líneas como:

```
[DB] Conectando a MongoDB: mongodb+srv://***@cluster.xxxxx.mongodb.net
[PERFIL] RAM container: ... MB → perfil 'alto'
[Scheduler] scraping: 05:30 (America/Argentina/Buenos_Aires) cada 1 día(s).
```

El dashboard se sirve directo desde `express/src/public/`: los cambios en el HTML se ven recargando la página.

Para correr los tests: `python -m pytest`.

### Paso 5B: ejecutar con Docker

```bash
docker compose up --build
```

Abrir <http://localhost:5000>. El primer build tarda varios minutos (descarga Chromium). `docker compose` le da 2 GB de RAM al contenedor; para simular Render:

```bash
docker build -t afterdrive .
docker run --env-file .env -p 5000:5000 -m 512m afterdrive
```

### Paso 6: primer uso, de base vacía a la primera nota

1. **Verificar la IA**: el indicador del dashboard tiene que mostrar el proveedor conectado.
2. **Cargar ejemplos del blog**: desde el dashboard, scrapear ejemplos de AfterDrive por categoría. Sin esto, la nota se genera sin referencia de estilo.
3. **Agregar fuentes de noticias**: pegar la URL del listado de noticias de un sitio del rubro. Si la IA aprueba algún artículo, queda como fuente activa. El descubrimiento de fuentes sugiere sitios candidatos.
4. **Correr el scraping** una vez para tener noticias de contexto (sin noticias, la nota sale sin datos concretos).
5. **Generar una nota**: elegir categorías (y opcionalmente regiones, clientes, persona, tema, puntapié). El texto aparece en vivo y queda guardado en `notas_fase2`.
6. **Dejarlo automático**: guardar las categorías/regiones de la generación automática y revisar la hora de cada tarea.

### Paso 7: desplegar en Render

1. En [Render](https://render.com): **New → Blueprint** con este repo (usa `render.yaml`), o **New → Web Service** con runtime **Docker**.
2. Rama: `Render_Testing`.
3. Cargar en **Environment** las variables marcadas `sync: false` en `render.yaml`: `MONGO_URI`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `NVIDIA_EMB_MODEL`, `RENDER_EXTERNAL_URL`, `ADMIN_USER`, `ADMIN_PASSWORD_HASH` (en el panel de Render va **sin** comillas). `SECRET_KEY` y `CRON_TOKEN` las genera Render.
4. Health check path: `/health`.
5. Cada push a la rama despliega automáticamente.
6. Configurar un monitor externo (UptimeRobot / cron-job.org) que haga `GET /health` cada 5–10 minutos para que la instancia no se duerma.

### Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| "Login no configurado en el servidor" | Falta `ADMIN_USER`, `ADMIN_PASSWORD_HASH` o `SECRET_KEY` | Completarlas (paso 4) |
| Usuario y contraseña correctos pero no entra (Docker) | El hash en `.env` sin comillas simples: Docker interpreta los `$` | Poner el hash entre comillas simples |
| "Demasiados intentos" | 5 fallos seguidos | Esperar 15 minutos o reiniciar el servidor |
| `ServerSelectionTimeoutError` al arrancar | Mongo no acepta la conexión | Revisar `MONGO_URI` y que tu IP esté en *Network Access* de Atlas |
| HTTP 404/410 al generar | El modelo fue dado de baja | Cambiar `OPENROUTER_MODEL` / `NVIDIA_MODEL` / `NVIDIA_EMB_MODEL` por uno de la lista que imprime el error |
| HTTP 429 | Límite de uso del plan gratuito del proveedor | Esperar, o cambiar de proveedor o modelo |
| "Otra corrida en curso" | Ya hay un scraping o una generación corriendo | Esperar a que termine |
| Los artículos se guardan sin `embedding` | Falta `NVIDIA_API_KEY` o `EMBEDDINGS_PROVIDER` mal configurado | Configurarlo y correr `python -m afterdrive.ingesta.embeddings` |
| "Sin categorías activas guardadas" | La generación automática no tiene configuración | Guardar categorías en el dashboard |
| No corrió la tarea programada en Render | La instancia estaba dormida | Monitor externo (paso 7.6) o disparar `POST /api/run-automation` con el `CRON_TOKEN` |

### Scripts por línea de comandos

Con el entorno virtual activado y el `.env` completo (en `Front-Testing`: `python <archivo>.py` en lugar de `python -m afterdrive...`):

```bash
python -m afterdrive.ingesta.run_automation 10                    # scraping de fuentes confiables
python -m afterdrive.ingesta.add_url https://sitio.com/noticias   # probar y dar de alta una fuente
python -m afterdrive.ingesta.discover_sources                     # buscar fuentes nuevas
python -m afterdrive.ingesta.embeddings                           # completar embeddings faltantes
python -m afterdrive.generacion.scraper_afterdrive --tags autopartes marketplaces --max 5
python -m afterdrive.generacion.generar_nota_fase2 --categorias autopartes --regiones argentina --persona comercial
python -m afterdrive.generacion.generar_articulo --persona analitico --tema "frenos"
```

---

## 11. Puntos de atención y deuda conocida

- **Las dos ramas de trabajo están separadas** y cada una tiene mejoras que la otra no (sección 0). Unificarlas es la tarea más importante pendiente.
- **El generador Fase 1 no lee las noticias scrapeadas** (en las dos ramas): en `generar_articulo.py`, la fuente `"general"` apunta a `articulos_generados` (lo que ya generó) en vez de a `articulos`. Probablemente es un error.
- **`Front-Testing` todavía no usa noticias en la Fase 2**: ahí los datos concretos de las notas dependen de lo que "sabe" el modelo.
- **Los artículos descartados no evitan volver a descargarlos**: se guardan "para no volver a procesarlos", pero el scraper no consulta esa colección (ni `articulos`) antes de descargar. Cada corrida vuelve a bajar y clasificar artículos ya vistos.
- En `Render_Testing`, `articulos_descartados` guarda solo la URL, sin título ni motivo (`Front-Testing` ya lo corrige).
- Si el proveedor de IA no responde, el clasificador **aprueba todo** (modo degradado, decisión intencional): puede entrar contenido irrelevante a `articulos`.
- Jev (TypeSafe) está integrado pero no se usa.
- La colección `afterdrive` ya no la escribe ningún proceso; es un resto de una versión anterior.
- En `ia/lm_studio.py` hay funciones sin uso (`extraer_temas`, `research_contexto`).
- No hay publicación en HubSpot; en `Render_Testing` tampoco hay estados borrador/publicado.
- El bloqueo de Corridas y el contador de intentos de login viven en memoria: obligan a usar un solo worker y se reinician con cada deploy.
- Las tareas programadas dependen de que la instancia de Render esté despierta (plan free).

---

## 12. Limitaciones de infraestructura y mejoras a futuro

### 12.1 Las trabas actuales

El servicio corre en el **plan free de Render**: **512 MB de RAM**, **0,1 CPU** (una décima de núcleo) y la instancia **se duerme tras ~15 minutos sin tráfico**. Eso condiciona casi todo:

| Traba | Por qué pasa | Efecto |
|---|---|---|
| **Sin navegador headless** | Con < 600 MB el sistema elige el perfil `bajo` y nunca usa Chromium | Los sitios con Cloudflare o contenido cargado por JavaScript fallan o caen a la copia de Wayback (más lenta y a veces vieja). Igual la imagen Docker incluye Chromium, que ocupa espacio y alarga cada deploy sin usarse |
| **Scraping lento** | 0,1 CPU y 2 hilos en perfil `bajo`; `trafilatura`/`lxml` parsean HTML con CPU | Con muchas fuentes, el scraping diario se estira mucho |
| **Una sola Corrida a la vez** | El bloqueo de `corridas.py` existe justamente porque dos no entran en 512 MB | Mientras corre el scraping no se puede generar una nota, y al revés |
| **Embeddings comparados en Python puro** | Los vectores (2048 números cada uno) se traen de Mongo a memoria y la similitud coseno se calcula con bucles de Python | La selección de noticias de la Fase 2 (200 candidatas) es manejable, pero el generador Fase 1 compara todo contra todo y crece en tiempo y RAM con cada documento |
| **Subprocesos para las Corridas con salida en vivo** | Cada ejecución desde el dashboard con log en vivo lanza un Python nuevo que vuelve a importar todo | Más RAM y arranque más lento dentro de los 512 MB |
| **Tareas programadas atadas a que la instancia esté despierta** | APScheduler vive dentro del proceso web | Si Render duerme o reinicia la instancia, la tarea del día no corre. Hoy se depende del keep-alive y de un monitor externo |
| **Un solo worker** | Bloqueo de Corridas, programador de tareas y login viven en memoria | No se puede escalar horizontalmente sin mover ese estado a Mongo |
| **Modelos gratuitos de IA** | OpenRouter y NVIDIA en sus planes gratuitos | Límites diarios y por minuto (errores 429), modelos que se dan de baja sin aviso (404/410) y calidad variable de redacción |

> Importante: **la redacción en sí no usa la CPU de Render**. El LLM corre en los servidores del proveedor; Render solo espera la respuesta. Para la *calidad* y la *velocidad* de las notas pesa más el modelo elegido que el plan de Render. Lo que Render limita es el **scraping, el procesamiento de embeddings, la concurrencia y la estabilidad** de las tareas programadas.

### 12.2 Alternativas de infraestructura

Ordenadas de menor a mayor cambio. Los precios son los publicados al momento de escribir esto; conviene verificarlos.

| Alternativa | Qué cambia | Por qué estaría bueno | Contras |
|---|---|---|---|
| **MongoDB Atlas Vector Search** | Reemplazar la comparación coseno en Python por `$vectorSearch` sobre un índice vectorial en Atlas (disponible en el tier gratuito M0) | Mueve el cálculo a Atlas: Render ya no carga los vectores en RAM y la búsqueda de vecinos pasa a milisegundos. Es el cambio con mejor relación costo/beneficio | Requiere crear el índice y reescribir la selección en `contexto_noticias.py` y `generar_articulo.py` |
| **Corridas pesadas en GitHub Actions** | Un workflow programado (`on: schedule`) que ejecute el scraping y la generación directamente | Gratis (ilimitado en repos públicos), cada ejecución tiene ~7 GB de RAM y varias CPUs, **permite usar Chromium**, no depende de que Render esté despierto y deja logs de cada corrida. Render queda solo para el dashboard | Las credenciales van como *secrets* del repo; el cron de Actions puede demorarse algunos minutos; el bloqueo en memoria no coordina con el dashboard (habría que pasarlo a Mongo) |
| **Monitor externo como cron** | cron-job.org / UptimeRobot hace los `POST` con el `CRON_TOKEN` a hora fija | Gratis y sin tocar código; reemplaza a los cron jobs de Render (pagos) | Sigue corriendo dentro de los 512 MB |
| **Render Starter (~USD 7/mes)** | Mismo servicio, plan pago | No se duerme nunca (las tareas programadas pasan a ser confiables) y habilita los cron jobs de `render.yaml` | Sigue teniendo 512 MB: no resuelve Chromium ni la concurrencia |
| **Render Standard (~USD 25/mes)** | 2 GB de RAM, 1 CPU | Perfil `alto` automático: Chromium, 4 hilos, scraping mucho más rápido y robusto | Costo mensual |
| **Google Cloud Run (servicio + Jobs + Cloud Scheduler)** | El dashboard como servicio que escala a cero y el scraping/generación como *jobs* programados | Se paga por uso (con un tier gratuito amplio); cada job puede tener 2–4 GB y varias CPUs solo mientras corre | Más configuración inicial; el bloqueo de Corridas y el login tendrían que pasar a Mongo |
| **VM propia (p. ej. Oracle Cloud Always Free, ARM con hasta 24 GB de RAM)** | Correr el contenedor en una VM | Muchos recursos gratis; permite incluso un modelo local con LM Studio/Ollama, sin depender de APIs ni límites | Hay que administrar el servidor (actualizaciones, seguridad, backups) |

**Recomendación:** combinar **Atlas Vector Search** + **GitHub Actions para scraping y generación**, y dejar Render (free o Starter) solo para el dashboard. Es casi gratis y elimina las trabas principales: RAM, Chromium, concurrencia y tareas que no corren.

### 12.3 Mejoras de eficiencia en el código

| Mejora | Por qué estaría buena |
|---|---|
| **Unificar `Render_Testing` y `Front-Testing`** | Hoy hay mejoras repartidas (noticias de contexto y evaluación en una; historial, estados y descartes con motivo en la otra). Mientras sigan separadas, cada arreglo se hace dos veces |
| **No re-descargar lo ya procesado** | Antes de bajar un artículo, chequear si su URL ya está en `articulos` o `articulos_descartados` (existe `db.obtener_urls_procesados()` sin usar). Ahorra descargas, llamadas al LLM y embeddings en cada corrida |
| **Ingesta por RSS / sitemaps** | Muchos sitios publican feeds con título, fecha y link sin tener que descargar y parsear la portada: menos CPU, menos bloqueos y alta de fuentes más rápida |
| **Usar `numpy` para la similitud** (si no se adopta Vector Search) | Las operaciones vectorizadas son decenas de veces más rápidas que los bucles de Python y ocupan menos memoria (un vector de 2048 `float32` = 8 KB contra ~64 KB como lista de Python) |
| **Clasificar en lote** | Mandar varios artículos por llamada al LLM (o filtrar antes por palabras clave) reduce llamadas y errores 429 |
| **Deduplicar notas Fase 2** | Ya se guarda el embedding de cada nota; compararlo contra las anteriores evitaría generar notas casi iguales |
| **Corregir el origen de datos de la Fase 1** | Que lea `articulos` en lugar de `articulos_generados` |
| **Bloqueo de Corridas y login en Mongo** | Permitiría más de un worker, ejecutar Corridas desde fuera de Render (GitHub Actions) y no perder el estado en cada deploy |
| **Imagen Docker sin Chromium para Render** | Si producción nunca lo usa, quitarlo achica la imagen y acelera los deploys |
| **Publicación en HubSpot** | Completar el flujo `borrador → publicado` de `Front-Testing` publicando por API (ver `docs/hubspot-integration.md`) |
| **Proveedor de IA pago o modelo local** | Un modelo pago económico (o uno local en una VM con recursos) da calidad más estable y elimina los límites y las bajas sorpresivas de los modelos gratuitos. Con modelos chicos, el costo por nota es de centavos |

---

## 13. Otros archivos del repo

En `Render_Testing`:

| Archivo / carpeta | Qué es |
|---|---|
| `CONTEXT.md` | Vocabulario del dominio |
| `docs/adr/` | Decisiones de arquitectura (por qué las Corridas se serializan en un proceso) |
| `docs/hubspot-integration.md` | Guía para la futura publicación en HubSpot (en `Front-Testing` y `main`: `HUBSPOT_INTEGRATION_GUIDE.md`) |
| `docs/superpowers/` | Spec y plan de implementación del login y la seguridad |
| `tests/` | Tests con `pytest` (auth, configuración, Corridas, generación, LLM, redacción, saneo, scheduler, scraper) |
| `scripts/demo_mode.py` | Versión acelerada del pipeline para demos en vivo |
| `scripts/manual/` | Pruebas manuales (conexión con NVIDIA, smoke test con Playwright) |
| `data/*.json` | Volcados de artículos de ejemplo |
| `AGENTS.md`, `opencode.json`, `.opencode/`, `.agents/` | Configuración de agentes de IA para desarrollo (OpenCode) y sincronización de specs desde Google Drive. No forman parte del sistema en producción |
| `render.yaml` | Blueprint de Render (web service + cron jobs de plan pago) |
