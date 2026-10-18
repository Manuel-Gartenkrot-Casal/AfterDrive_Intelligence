# 01 · Arquitectura

## El sistema en un dibujo

```
                     ┌────────────────── Contenedor Docker (Render) ──────────────────┐
                     │                                                                │
 Navegador ────────► │  Flask + Gunicorn (1 worker)        afterdrive/flask_api.py    │
 (dashboard)         │   ├─ login                          auth.py                    │
                     │   ├─ dashboard estático  (/)        express/src/public/        │
                     │   ├─ API REST            (/api/*)                              │
                     │   ├─ programador de tareas          scheduler.py (APScheduler) │
                     │   └─ cola de Corridas               cola.py → corridas.py      │
                     └──────────┬──────────────────┬──────────────────┬───────────────┘
                                │                  │                  │
                     ┌──────────▼─────┐  ┌─────────▼──────┐  ┌────────▼──────────────┐
                     │ Sitios web     │  │ MongoDB Atlas  │  │ Proveedores de IA     │
                     │ noticias, blog │  │ base           │  │ OpenRouter (LLM)      │
                     │ AfterDrive,    │  │ "afterdrive"   │  │ NVIDIA (embeddings)   │
                     │ Wayback, DDG   │  │                │  │ LM Studio (local)     │
                     └────────────────┘  └────────────────┘  └───────────────────────┘
```

Todo vive en **un solo proceso**: la API, el programador de tareas y la cola. No hay workers aparte ni colas externas.

## Las piezas

| Pieza | Archivo | Qué hace |
|---|---|---|
| API | `afterdrive/flask_api.py` | Endpoints, cabeceras de seguridad, sirve el dashboard, arranca el scheduler y el keep-alive |
| Login | `afterdrive/auth.py` | Un usuario admin, sesión firmada, bloqueo tras 5 intentos |
| Configuración | `afterdrive/config_store.py` | Lee y guarda lo que se cambia en el dashboard (colección `config`) |
| Programador | `afterdrive/scheduler.py` | Encola scraping y generación a la hora configurada (hora argentina), salvo que las corra GitHub Actions |
| Ejecutor externo | `afterdrive/ejecutor_externo.py` | Corre las tareas programadas en GitHub Actions (opcional, ver [08](08-despliegue.md)) |
| Cola | `afterdrive/cola.py` | Guarda en Mongo las Corridas pendientes y las corre de a una |
| Corridas | `afterdrive/corridas.py` | Ejecuta scraping, generación o scripts, con un lock para que nunca corran dos |
| Historial | `afterdrive/historial.py` | Notas y artículos guardados o descartados; estados de revisión y edición de notas |
| HubSpot | `afterdrive/hubspot.py` | Publica notas aprobadas en el blog |
| Ingesta | `afterdrive/ingesta/` | Scrapear, clasificar, vectorizar y guardar noticias |
| Generación | `afterdrive/generacion/` | Escribir Notas (Fase 2 es el generador principal) |
| IA | `afterdrive/ia/` | Hablar con los proveedores (`llm.py`), prompts (`redaccion.py`, `lm_studio.py`), limpiar la salida (`saneo.py`) |
| Dashboard | `express/src/public/` | `index.html` + CSS y JS en `assets/`, sin build. La carpeta se llama `express/` por historia: ya no hay servidor Express |

## Cómo se ejecuta una Corrida

Una **Corrida** es una ejecución del pipeline: scraping, generación de una nota, sincronizar ejemplos, etc. Pueden venir del programador, de un botón del dashboard o de un cron externo.

```
botón / scheduler / cron
        │  POST /api/corridas/...   o   cola.encolar(...)
        ▼
  colección "corridas" en Mongo  (estado: pendiente)
        │  un único thread consumidor toma la más vieja
        ▼
  corridas.py toma el lock  →  ejecuta  →  guarda estado final y log
        │
        ▼
  el dashboard lee el log cada 1,5 s  (GET /api/corridas/<id>/log?desde=N)
```

- **Corre una sola a la vez.** En el plan free de Render (512 MB) dos Corridas juntas se quedan sin memoria.
- **Las que llegan mientras otra corre esperan en la cola**, no se rechazan. Una idéntica a otra pendiente no se duplica. Máximo 5 esperando.
- **La cola sobrevive reinicios.** Si el servidor se cae con una Corrida a medias, queda marcada `interrumpida`; las pendientes se retoman.
- **Se pueden cancelar**, salvo una generación ya empezada.

El porqué está en [ADR-0001](adr/0001-corridas-serializadas-en-un-proceso.md) y [ADR-0002](adr/0002-cola-de-corridas.md).

## Tipos de Corrida

| Tipo | Cómo corre | Quién la pide |
|---|---|---|
| `scraping` | Dentro del proceso | Programador, botón "Buscar noticias", cron externo |
| `generacion` | Dentro del proceso, con la config guardada | Programador, cron externo |
| `script` | Subproceso de Python | "Generar nota" (con lo que hay en pantalla), "Sincronizar ejemplos", "Probar y agregar", "Buscar recomendaciones" |

Con GitHub Actions activado, las programadas las ejecuta el runner de GitHub (`ejecutor: "github"`): quedan en la misma colección y el dashboard las ve igual, con su log en vivo.

## Configuración: dos lugares

| Dónde | Qué | Cuándo cambia |
|---|---|---|
| `.env` / variables de Render | Secretos, URLs y modelos de IA, Mongo, usuario | Al desplegar |
| Colección `config` en Mongo | Horarios, categorías de la nota automática, proveedor elegido | Desde el dashboard, con "Guardar cambios" |

El proveedor de IA guardado en Mongo **pisa** a `AI_PROVIDER` del entorno, salvo que exista `AI_PROVIDER_OVERRIDE`.
