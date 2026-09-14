# AfterDrive Intelligence

Automatización de contenidos inteligentes para el sector automotriz y postventa. Scraping automatizado de noticias + generador de artículos periodísticos por IA (RAG + embeddings).

Extrae artículos de múltiples fuentes, los guarda en MongoDB Atlas y genera contenido original combinando el material scrapeado con un pipeline semántico (KNN + text search).

---

## Arquitectura

```
Browser → Express :3000 → Flask :5000 → Scrapling spiders → MongoDB Atlas
                                      → LM Studio / NVIDIA (IA)
```

| Componente | Tecnología | Puerto |
|---|---|---|
| Frontend (dashboard) | HTML/CSS/JS estático | 3000 |
| API proxy | Express + TypeScript | 3000 |
| API principal | Flask + Python | 5000 |
| Scraping | Scrapling (StealthyFetcher) | — |
| IA local | LM Studio (mistral-7b) | 1234 |
| IA cloud | NVIDIA Build (GLM-5.3-flash) | — |
| Base de datos | MongoDB Atlas | — |

---

## Requisitos

| Opción | Python | Node.js | Docker |
|---|---|---|---|
| Docker (recomendado) | No | No | Sí |
| Local | 3.10+ | 20+ | No |

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

Abrí `.env` y completá al menos `MONGO_URI`. Elegí el proveedor de IA:

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
http://localhost:3000
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

### 5. Node.js — compilar Express

```bash
cd express
npm install
npm run build
cd ..
```

### 6. Levantar Flask (terminal 1)

```bash
python flask_api.py
```

### 7. Levantar Express (terminal 2)

```bash
cd express
node dist/index.js
```

### 8. Abrir

```
http://localhost:3000
```

---

## Configuración (.env)

| Variable | Requerido | Descripción |
|---|---|---|
| `MONGO_URI` | Sí | URI de conexión a MongoDB Atlas |
| `AI_PROVIDER` | Sí | `local` o `nvidia` |
| `NVIDIA_API_KEY` | Si nvidia | API key de NVIDIA Build |
| `LMSTUDIO_URL` | Si local | URL de LM Studio (default: `http://localhost:1234/v1`) |
| `LMSTUDIO_MODEL` | Si local | Modelo a usar (default: `mistral-7b-instruct-v0.3`) |

---

## Dashboard

El frontend en `http://localhost:3000` ofrece:

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

| Fuente | Dominio | Colección MongoDB |
|---|---|---|
| La Nación | lanacion.com.ar | `autopartes` |
| Mundo Aftermarket | mundoaftermarket.com | `aftermarket` |
| Ambito Financiero | ambito.com | `ambito` |
| Cenital | cenital.com | `cenital` |
| Perfil | perfil.com | `perfil` |

Las fuentes se configuran en `scraper.py`. Cada spider busca "autopartes" y related terms en su sitio.

---

## Generación de artículos con IA

Pipeline RAG híbrido:

1. **KNN** — selecciona semilla más novedosa (coseno entre embeddings) y encuentra vecinos semánticos
2. **Text search** — busca documentos relacionados por tema en MongoDB
3. **Merge** — combina ambos pools rankeando por `max(similitud_coseno, textScore)`
4. **Redacción** — IA escribe el artículo con contexto completo (~28K tokens)
5. **Dedup** — verifica que no se parezca a uno previo (coseno ≥ 0.85 = descarte)
6. **Post-procesamiento** — elimina secciones duplicadas, CTA repetido, errores gramaticales conocidos

### Uso por CLI

```bash
python generar_articulo.py

# Filtrar por fuentes
python generar_articulo.py --fuente lanacion aftermarket

# Generar con tema específico
python generar_articulo.py --tema "tendencias del aftermarket 2026"
```

### Backfill de embeddings

Si hay artículos previos al sistema de embeddings:

```bash
python embeddings.py
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
python generar_nota_fase2.py \
    --categorias autopartes marketplaces \
    --regiones brasil argentina \
    --clientes cliente_a \
    --puntapie https://alephee.com/landing \
    --persona comercial

# Solo categorías
python generar_nota_fase2.py --categorias neumaticos logistica

# Regiones sin clientes
python generar_nota_fase2.py --categorias marketplaces --regiones mexico europa
```

### Sincronizar ejemplos del blog

```bash
# Todas las categorías
python scraper_afterdrive.py

# Solo ciertas categorías
python scraper_afterdrive.py --tags autopartes marketplaces --max 5
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
| `autopartes` | Artículos de La Nación |
| `aftermarket` | Artículos de Mundo Aftermarket |
| `ambito` | Artículos de Ambito Financiero |
| `cenital` | Artículos de Cenital |
| `perfil` | Artículos de Perfil |
| `articulos_generados` | Artículos generados por IA (con embeddings) |
| `trusted_urls` | URLs confiables para scraping automático |
| `suggested_urls` | URLs sugeridas por el descubridor de fuentes |
| `afterdrive` | Configuración del scheduler |
| `afterdrive_ejemplos` | Notas reales scrapeadas del blog AfterDrive (few-shot por categoría/región) |
| `notas_fase2` | Notas generadas por el sistema Fase 2 |
| `clientes` | Clientes para mencionar en notas (placeholder para carga futura) |

La URL se usa como clave única — no se duplican artículos.

---

## Agregar una fuente nueva

1. Crear `spiders/nuevo_spider.py`
2. Crear `runnuevo.py`
3. En `flask_api.py` agregar a `SPIDERS`: `"nuevo": "runnuevo.py"`
4. En `express/src/index.ts` agregar `"nuevo"` al array `VALID_SPIDERS`
5. En `express/src/public/index.html` copiar una card y cambiar el nombre
6. En `db.py` agregar la colección: `col_nuevo = db["nuevo"]`
7. En `generar_articulo.py` agregar a `FUENTES`: `"nuevo": db["nuevo"]`
8. Si usás Docker: `docker compose up --build`

---

## Estructura del proyecto

```
afterdrive-intelligence/
├── flask_api.py              # API principal (scraping, generación, health, Fase 2)
├── scraper.py                # Scrapling spiders (StealthyFetcher + fallback Wayback)
├── scraper_afterdrive.py     # Fase 2: scraper del blog AfterDrive por categoría/región
├── generar_articulo.py       # Orquestador de generación RAG
├── generar_nota_fase2.py     # Fase 2: generador de notas con few-shot + toggles
├── regiones.py               # Fase 2: clasificador geográfico (keywords normalizadas)
├── scheduler.py              # APScheduler para ejecución automática
├── lm_studio.py              # Prompts por personalidad + llamadas a IA
├── embeddings.py             # Cálculo de embeddings
├── db.py                     # Conexión MongoDB Atlas
├── discover_sources.py       # DuckDuckGo search para nuevas fuentes
├── add_url.py                # Alta de URLs manual
├── run_automation.py         # Runner del pipeline completo
├── requirements.txt          # Dependencias Python
├── Dockerfile                # Imagen Python (Flask + Scrapling)
├── docker-compose.yml        # Orquestación de servicios
├── .env.example              # Template de variables de entorno
└── express/
    ├── src/
    │   ├── index.ts          # Express proxy server (incluye endpoints Fase 2)
    │   └── public/
    │       └── index.html    # Dashboard completo (HTML/CSS/JS) con panel Fase 2
    ├── package.json
    ├── tsconfig.json
    └── Dockerfile            # Imagen Node.js (Express)
```
