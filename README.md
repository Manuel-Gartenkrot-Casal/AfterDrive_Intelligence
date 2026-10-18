# AfterDrive Intelligence

Genera **notas de blog B2B para [AfterDrive by Alephee](https://afterdrive.alephee.com/es/blog/)** (sector autopartes y aftermarket) de forma automática.

1. **Junta material**: scrapea noticias de fuentes del rubro y notas reales del blog de AfterDrive.
2. **Filtra con IA**: un LLM descarta lo que no es del rubro; lo que sirve se guarda con su embedding.
3. **Redacta con IA**: un LLM escribe notas nuevas usando las noticias como datos y las notas del blog como referencia de estilo.

Todo se maneja desde un dashboard web con login, y corre solo todos los días. Cada nota queda como borrador: una persona la **revisa y aprueba**, y recién ahí se puede publicar en el blog de HubSpot desde el mismo dashboard.

```
 Fuentes de noticias ──► Scraping ──► Filtro IA ──► articulos ─┐
 Blog AfterDrive ──────► Ejemplos de estilo ───────────────────┼──► Redacción IA ──► notas_fase2 ──► revisión ──► HubSpot
                                                               │      (+ saneo y evaluación)     (aprobar/editar)
 Dashboard (Flask) ─── configura, encola y revisa todo ────────┘
```

## Arrancar en 5 minutos

Necesitás Python 3.12 (mínimo 3.11), una base en MongoDB Atlas y una API key de OpenRouter y otra de NVIDIA. El paso a paso completo está en [docs/02-instalacion.md](docs/02-instalacion.md).

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/AfterDrive_Intelligence.git
cd AfterDrive_Intelligence && git checkout Render_Testing

python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env        # completar MONGO_URI, API keys y usuario del dashboard
python -m afterdrive.flask_api                          # → http://localhost:5000
```

Tests: `python -m pytest`. Dashboard en un navegador: `python -m pytest -m e2e tests/e2e`.

## Documentación

Empezá por **[docs/README.md](docs/README.md)**: dice qué leer según lo que vayas a hacer. Cada guía se lee en menos de 10 minutos.

| Guía | Para qué |
|---|---|
| [Arquitectura](docs/01-arquitectura.md) | Las piezas del sistema y cómo se hablan |
| [Instalación](docs/02-instalacion.md) | De cero a tu primera nota, local o con Docker |
| [Pipelines](docs/03-pipelines.md) | Qué pasa paso a paso al scrapear y al generar |
| [IA](docs/04-ia.md) | Dónde se usa IA, proveedores, modelos y prompts |
| [Base de datos](docs/05-base-de-datos.md) | Colecciones de MongoDB y sus campos |
| [Dashboard](docs/06-dashboard.md) | Cómo está hecho el frontend y cómo tocarlo |
| [API](docs/07-api.md) | Login y endpoints |
| [Despliegue](docs/08-despliegue.md) | Render, límites del plan free y monitoreo |
| [Deuda y mejoras](docs/09-deuda-y-mejoras.md) | Problemas conocidos y próximos pasos |
| [Glosario](CONTEXT.md) | El vocabulario del proyecto (Corrida, Nota, Persona…) |
| [Decisiones (ADR)](docs/adr/) | Por qué algunas cosas son como son |

## Ramas

| Rama | Qué es |
|---|---|
| **`Render_Testing`** | **Producción y desarrollo activo.** Render despliega desde acá. Es la referencia de toda la documentación |
| `main` | Recibió `Render_Testing` el 16/10 ([PR #13](https://github.com/Manuel-Gartenkrot-Casal/AfterDrive_Intelligence/pull/13)). No tiene lo posterior: cola de Corridas, historial y revisión, HubSpot, GitHub Actions |
| `Front-Testing` | Rama paralela vieja. Su historial, estados de las notas y descartes con motivo ya están en `Render_Testing`. Lo que queda (rediseño visual) está **pospuesto** |
| `Render_FrontTesting` | Copia de `Render_Testing` del 16/10, sin cambios propios |

## Stack

Python 3.12 · Flask + Gunicorn · APScheduler · MongoDB Atlas (opcional: Vector Search) · Scrapling + trafilatura · OpenRouter / NVIDIA Build / LM Studio · HubSpot CMS API · dashboard en HTML/CSS/JS sin framework · Docker en Render · GitHub Actions (CI y, opcional, Corridas programadas).

> El repo es público: **nunca subas el `.env`** ni pegues API keys en issues o commits.
