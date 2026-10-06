# AfterDrive Intelligence

Automatización de contenidos inteligentes para el sector automotriz y postventa. Scraping automatizado de noticias + generador de artículos periodísticos por IA (RAG + embeddings).

Extrae artículos de múltiples fuentes, los guarda en MongoDB Atlas y genera contenido original combinando el material scrapeado con un pipeline semántico (KNN + text search).

---

## Arquitectura

En producción (Render) es **un solo contenedor**: Flask sirve la API en `/api/*` y el dashboard estático en `/`.
El dashboard es HTML sin build (`express/src/public`): el Dockerfile lo copia a `static/` y en local Flask lo
sirve directo desde la fuente. Todo está detrás de un login de un solo usuario (ver [Acceso](#acceso)).

```
Render:   Browser → Flask :$PORT (API + dashboard) → Mongo Atlas / proveedor de IA
Local:    Browser → Flask :5000  (API + dashboard) → Mongo Atlas / proveedor de IA
```

| Componente | Tecnología |
|---|---|
| Dashboard | HTML/CSS/JS sin build (`express/src/public/index.html` y `login.html`) |
| Acceso | Sesión firmada de Flask, un usuario por variables de entorno (`afterdrive/auth.py`) |
| API | Flask + gunicorn (`--workers 1`, ver `docs/adr/0001-*`) |
| Scraping | requests + trafilatura, Scrapling/Chromium según RAM, Wayback como respaldo |
| Clasificación | Jev (TypeSafe) → LLM como fallback |
| IA | LM Studio (local), NVIDIA Build u OpenRouter (`llm.py`) |
| Base de datos | MongoDB Atlas |

Vocabulario del dominio: ver `CONTEXT.md`.

---

## Requisitos

| Opción | Python | Docker |
|---|---|---|
| Docker (recomendado) | No | Sí |
| Local | 3.10+ | No |

---

## Opción A — Docker (recomendado)

No necesitás instalar nada más que Docker Desktop.

### 1. Clonar

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/afterdrive-intelligence.git
cd afterdrive-intelligence
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Abrí `.env` y completá al menos `MONGO_URI` y las variables de [Acceso](#acceso) (sin ellas nadie puede entrar).
Elegí el proveedor de IA:

```env
# Para NVIDIA (cloud, funciona sin nada local):
AI_PROVIDER=nvidia
NVIDIA_API_KEY=tu-api-key-aqui

# O para LM Studio (local, necesitás LM Studio corriendo):
AI_PROVIDER=local
```

### 3. Levantar

```bash
docker compose up --build
```

La primera vez tarda ~5-8 minutos (descarga Chromium + instala dependencias). Las siguientes es inmediato.

### 4. Abrir

```
http://localhost:5000
```

### 5. Detener

```bash
docker compose down
```

---

## Opción B — Local (desarrollo)

### 1. Clonar

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/afterdrive-intelligence.git
cd afterdrive-intelligence
```

### 2. Configurar entorno

```bash
cp .env.example .env
```

Editá `.env` con tus credenciales (ver [Configuración](#configuración) más abajo).

### 3. Python — dependencias

```bash
pip install -r requirements.txt
```

### 4. Python — navegador para scraping

```bash
python -c "from scrapling.cli import install; install([], standalone_mode=False)"
```

### 5. Levantar Flask

```bash
python -m afterdrive.flask_api
```

### 6. Abrir

```
http://localhost:5000
```

---

## Configuración (.env)

| Variable | Requerido | Descripción |
|---|---|---|
| `MONGO_URI` | Sí | URI de conexión a MongoDB Atlas |
| `AI_PROVIDER` | Sí | `local`, `nvidia` u `openrouter` |
| `NVIDIA_API_KEY` | Si nvidia | API key de NVIDIA Build |
| `OPENROUTER_API_KEY` | Si openrouter | API key de OpenRouter |
| `EMBEDDINGS_PROVIDER` | Si openrouter | Proveedor de embeddings (`nvidia` o `local`): OpenRouter no tiene `/embeddings` |
| `TYPESAFE_API_KEY` | No | Activa el clasificador Jev; sin ella se usa el LLM |
| `LMSTUDIO_URL` | Si local | URL de LM Studio (default: `http://localhost:1234/v1`) |
| `LMSTUDIO_MODEL` | Si local | Modelo a usar (default: `mistral-7b-instruct-v0.3`) |
| `ADMIN_USER` | Sí | Usuario del dashboard |
| `ADMIN_PASSWORD_HASH` | Sí | Hash de la contraseña (no la contraseña) |
| `SECRET_KEY` | Sí | Firma la cookie de sesión |
| `CRON_TOKEN` | Si hay cron | Autoriza las corridas automáticas por HTTP |

---

## Acceso

El dashboard y toda la API (`/api/*`) piden sesión. Solo quedan abiertos `/health` y la pantalla de login.
Hay un único usuario, definido por variables de entorno: nada de credenciales en el código.

| Variable | Qué es | Cómo se obtiene |
|---|---|---|
| `ADMIN_USER` | Nombre de usuario | Lo elegís vos |
| `ADMIN_PASSWORD_HASH` | Hash scrypt de la contraseña | Comando de abajo |
| `SECRET_KEY` | Clave que firma la cookie de sesión | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CRON_TOKEN` | Token de las corridas automáticas | El mismo comando que `SECRET_KEY` (otro valor) |

Generar el hash (pide la contraseña sin mostrarla):

```bash
python -c "from getpass import getpass; from werkzeug.security import generate_password_hash as g; print(g(getpass('Contraseña: ')))"
```

- **El hash trae signos `$`.** En un archivo `.env` va siempre entre comillas simples
  (`ADMIN_PASSWORD_HASH='scrypt:...'`); sin ellas `docker compose` lo interpreta como variables y lo rompe.
  En el panel de Render se pega tal cual, sin comillas.
- **Si falta `ADMIN_USER`, `ADMIN_PASSWORD_HASH` o `SECRET_KEY`, nadie entra.** El panel queda cerrado, no abierto.
- **Cambiar la contraseña:** generar otro hash y reemplazar `ADMIN_PASSWORD_HASH`.
- **Cerrar todas las sesiones:** cambiar `SECRET_KEY`. Una sesión dura 7 días.
- **Intentos fallidos:** 5 seguidos desde la misma IP bloquean el login 15 minutos.
- **Corridas automáticas:** `POST /api/run-automation` y `POST /api/run-generacion` aceptan además el header
  `Authorization: Bearer <CRON_TOKEN>`. Es lo que usan los cron de `render.yaml` y lo que necesita cualquier
  monitor externo que las dispare. El scheduler interno no lo necesita.

---

## Dashboard

El frontend en `http://localhost:5000` ofrece:

- **Scraping manual** — ejecutá cada fuente individualmente o todas juntas
- **Generador de artículos** — elegí tema, personalidad (divulgativo/técnico/negocios) y generá
- **Pipeline visual** — HUD animado que muestra el progreso del scraping
- **Descubrimiento de fuentes** — DuckDuckGo search para encontrar nuevos sitios del nicho
- **Configuración** — intervalo de ejecución, máximo de artículos por fuente
- **Selector de proveedor** — cambiar entre LM Studio y NVIDIA en un click
- **Logs en tiempo real** — consola con colores por tipo de evento
- **Generador de notas Fase 2** — generación guiada con toggles de categorías, regiones y clientes
- **Sincronización de ejemplos** — scrape automático del blog AfterDrive by Alephee como base de few-shot

---

## Fuentes de scraping

Las fuentes son **dinámicas**: viven en la colección `trusted_urls` y se administran desde el dashboard
(alta manual, sugerencias del descubridor, baja). No hay spiders por sitio: `scraper.py` toma la página de
listado de cada fuente activa, encuentra los links a artículos y extrae el texto.

---

## Generación de artículos con IA

Pipeline RAG híbrido:

1. **KNN** — selecciona semilla más novedosa (coseno entre embeddings) y encuentra vecinos semánticos
2. **Text search** — busca documentos relacionados por tema en MongoDB
3. **Merge** — combina ambos pools rankeando por `max(similitud_coseno, textScore)`
4. **Redacción** — IA escribe el artículo con contexto completo (~28K tokens)
5. **Dedup** — verifica que no se parezca a uno previo (coseno ≥ 0.95 = descarte)
6. **Post-procesamiento** — elimina secciones duplicadas, CTA repetido, errores gramaticales conocidos

### Uso por CLI

```bash
python -m afterdrive.generacion.generar_articulo

# Filtrar por fuentes
python -m afterdrive.generacion.generar_articulo --fuente lanacion aftermarket

# Generar con tema específico
python -m afterdrive.generacion.generar_articulo --tema "tendencias del aftermarket 2026"
```

### Backfill de embeddings

Si hay artículos previos al sistema de embeddings:

```bash
python -m afterdrive.ingesta.embeddings
```

---

## Fase 2 — Generador de Notas con Toggles

Sistema de generación de notas estilo AfterDrive by Alephee con pocos clicks.

### Flujo de uso

1. **Sincronizar Ejemplos** — scrapear el blog `afterdrive.alephee.com/es` por categoría/región y cargarlos como ejemplos few-shot en MongoDB
2. **Activar categorías** con toggles (ej: Autopartes, Marketplaces, Neumáticos…)
3. **Activar regiones** con toggles (Argentina, Brasil, México, Latinoamérica, Europa, China, Asia)
4. **Activar clientes** — insertar clientes que deseás mencionar (placeholder listo para carga)
5. **Elegir personalidad** — Comercial, Analítico, Periodístico, Divulgativo o Ejecutivo
6. **Tema libre** (opcional) — forzar un tema específico
7. **Modo puntapié** — activar si la nota tiene que redirigir a un link externo
8. **Generar Nota** — streaming en consola → resultado en modal + checklist de calidad

### Uso por CLI

```bash
# Ejemplo completo
python -m afterdrive.generacion.generar_nota_fase2 \
    --categorias autopartes marketplaces \
    --regiones brasil argentina \
    --clientes cliente_a \
    --puntapie https://alephee.com/landing \
    --persona comercial

# Solo categorías
python -m afterdrive.generacion.generar_nota_fase2 --categorias neumaticos logistica

# Regiones sin clientes
python -m afterdrive.generacion.generar_nota_fase2 --categorias marketplaces --regiones mexico europa
```

### Sincronizar ejemplos del blog

```bash
# Todas las categorías
python -m afterdrive.generacion.scraper_afterdrive

# Solo ciertas categorías
python -m afterdrive.generacion.scraper_afterdrive --tags autopartes marketplaces --max 5
```

### Regionales

Clasificación automática de cada nota scrapeada según keywords normalizadas.
Regiones: Argentina, Brasil, México, Latinoamérica, Europa, China, Asia.
El scraper clasifica al guardar; el generador filtra los ejemplos few-shot por región activa y ajusta el prompt con el contexto de mercado correspondiente.

### API Fase 2 (endpoints)

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/fase2/categorias` | GET | Lista de categorías con conteo de ejemplos |
| `/api/fase2/regiones` | GET | Lista de regiones con conteo de ejemplos |
| `/api/fase2/scrape` | POST | Lanza el scraper del blog (streaming disponible) |
| `/api/fase2/clientes` | GET/POST | CRUD de clientes (placeholder) |
| `/api/fase2/clientes/<slug>` | DELETE | Eliminar cliente |
| `/api/fase2/generar` | POST | Genera una nota (streaming en `/api/fase2/stream/generar`) |
| `/api/fase2/ultima-nota` | GET | Última nota generada |

---

## Base de datos (MongoDB Atlas)

Base: `afterdrive`

| Colección | Contenido |
|---|---|
| `articulos` | Artículos aprobados por la ingesta (con embedding y `usado_para_articulo`) |
| `articulos_descartados` | URLs rechazadas por el clasificador (para no reprocesarlas) |
| `trusted_urls` | Fuentes confiables (activas/inactivas) |
| `suggested_urls` | Fuentes sugeridas por el descubridor |
| `afterdrive_ejemplos` | Notas reales del blog AfterDrive (few-shot por categoría/región) |
| `notas_fase2` | Notas generadas (Fase 2) con evaluación de calidad |
| `articulos_generados` | Notas de la Fase 1 (heredada) |
| `clientes` | Clientes que una nota puede mencionar |
| `config` | Configuración del dashboard (horarios, toggles, proveedor) |
| `afterdrive` | Colección heredada, solo la lee la Fase 1 |

La URL se usa como clave única — no se duplican artículos.

---

## Agregar una fuente nueva

Desde el dashboard (sección Fuentes) o con `python -m afterdrive.ingesta.add_url <url>`: scrapea la página, clasifica y, si al
menos un artículo se aprueba, la guarda como fuente confiable. No hace falta tocar código.

## Estructura del proyecto

```
afterdrive/                    # paquete Python (el runtime)
├── flask_api.py               # API + dashboard estático + keep-alive
├── corridas.py                # único camino para correr scraping/generación (lock, ADR 0001)
├── scheduler.py               # APScheduler: agenda las corridas según config_store
├── config_store.py            # configuración persistida en Mongo
├── db.py                      # conexión y colecciones de Mongo
├── ingesta/                   # noticias: de la web a la base
│   ├── scraper.py             #   scraping de fuentes confiables
│   ├── resource_detector.py   #   perfil de recursos (RAM) → estrategia de fetch
│   ├── ingesta.py             #   clasificar → vectorizar → guardar
│   ├── jev_clasificador.py    #   clasificador Jev (adapter)
│   ├── embeddings.py          #   coseno, backfill de vectores
│   └── add_url.py, run_automation.py, discover_sources.py
├── generacion/                # notas: de la base al texto publicable
│   ├── generar_nota_fase2.py  #   generador principal (Fase 2)
│   ├── contexto_noticias.py   #   qué noticias alimentan la nota
│   ├── scraper_afterdrive.py  #   ejemplos: notas reales del blog (few-shot)
│   ├── regiones.py            #   clasificador geográfico
│   └── generar_articulo.py    #   Fase 1 (heredada)
└── ia/                        # todo lo que habla con modelos
    ├── llm.py                 #   proveedores (chat + embeddings)
    ├── lm_studio.py           #   prompts y tareas de IA (nombre histórico)
    ├── redaccion.py           #   system prompts (persona + región)
    └── saneo.py               #   texto crudo del modelo → nota publicable

tests/                         # pytest (python -m pytest)
scripts/                       # demo y pruebas manuales, no forman parte del deploy
docs/                          # ADRs y guía de HubSpot
express/src/public/            # dashboard (index.html) y pantalla de login (login.html)
Dockerfile, docker-compose.yml, render.yaml
CONTEXT.md, AGENTS.md, segundo-cerebro/   # vocabulario y memoria para agentes
```

Los scripts se corren como módulos desde la raíz: `python -m afterdrive.ingesta.add_url <url>`.
