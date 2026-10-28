# 08 · Despliegue

## Producción: Render

| | |
|---|---|
| Servicio | Un web service Docker, definido en `render.yaml` |
| Rama | `Render_Testing`: **cada push despliega** |
| Plan | Free: 512 MB de RAM, 0,1 CPU, se duerme tras ~15 min sin tráfico |
| Arranque | `gunicorn --workers 1 --threads 4 --timeout 1800 afterdrive.flask_api:app` |
| Health check | `GET /health` |

La imagen (`Dockerfile`) instala Python, Chromium (para Scrapling) y copia `afterdrive/` y el dashboard (`express/src/public/` → `static/`).

> **Un solo worker es obligatorio.** El programador de tareas, el lock de Corridas y el contador de intentos de login viven en memoria.

## Antes de que llegue a producción: CI

`.github/workflows/ci.yml` corre `ruff` y `pytest` en cada push y pull request. Render no lo espera: si el CI queda rojo, arreglalo enseguida.

## Primer despliegue

1. En [Render](https://render.com): **New → Blueprint** con este repo (usa `render.yaml`).
2. Cargá en **Environment** las variables marcadas `sync: false`: `MONGO_URI`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `NVIDIA_EMB_MODEL`, `RENDER_EXTERNAL_URL`, `ADMIN_USER`, `ADMIN_PASSWORD_HASH` (en Render va **sin** comillas). `SECRET_KEY` y `CRON_TOKEN` las genera Render. Opcionales: `HUBSPOT_TOKEN` (la app privada con los scopes `content` y `files`), `HUBSPOT_BLOG_PRUEBAS` (solo para mandar todo a un blog de pruebas; el viejo `HUBSPOT_BLOG_ID` ya no se usa), `ATLAS_VECTOR_INDEX`, `CORRIDAS_EXTERNAS` y los `PAGA_*` de la API paga (ver [04-ia.md](04-ia.md)).
3. En Atlas, **Network Access** tiene que permitir `0.0.0.0/0`: Render free no tiene IP fija.
4. Elegí cómo corren las tareas programadas (abajo).

## Tareas programadas: dos opciones

### A. En Render (como viene)

El programador interno las corre a la hora del dashboard, **si la instancia está despierta**. Para que no se duerma:

| Capa | Cómo |
|---|---|
| Keep-alive interno | `flask_api.py` le pega a `RENDER_EXTERNAL_URL/health` cada 5 min (no alcanza solo) |
| **Monitor externo** (recomendado) | UptimeRobot o cron-job.org: `GET /health` cada 5–10 min |
| Cron externo | `POST /api/run-automation` y `/api/run-generacion` con `Authorization: Bearer <CRON_TOKEN>` |

### B. En GitHub Actions (recomendado)

`.github/workflows/corridas.yml` corre cada hora en GitHub, lee la programación del dashboard y ejecuta lo que tocaba. Gana ~7 GB de RAM, Chromium y no depende de que Render esté despierto. Las Corridas aparecen igual en el panel del dashboard, con su log, y se pueden cancelar desde ahí.

Para activarlo:

0. **El workflow tiene que estar en la rama por defecto del repo** (hoy `main`): GitHub solo dispara los `schedule` desde ahí, y corre el código de esa rama. Mergeá `Render_Testing` en `main`, o cambiá la rama por defecto a `Render_Testing` (**Settings → General → Default branch**).
1. GitHub → **Settings → Secrets and variables → Actions**:
   - **Secrets**: `MONGO_URI`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY` (y `PAGA_API_KEY` para la API paga).
   - **Variables**: `CORRIDAS_EN_GITHUB` = `true`. Opcionales: `AI_PROVIDER`, `EMBEDDINGS_PROVIDER`, `OPENROUTER_MODEL`, `NVIDIA_MODEL`, `NVIDIA_EMB_MODEL`, `ATLAS_VECTOR_INDEX` y, para la API paga, `PAGA_BASE_URL`, `PAGA_MODEL`, `PAGA_MODEL_CLASIFICACION`, `PAGA_MODEL_EVALUACION`, `PAGA_MODEL_REDACCION`, `PAGA_EMB_MODEL` (y, si hace falta, `PAGA_FALLBACK_MODEL`, `PAGA_CAMPO_MAX_TOKENS`, `PAGA_TEMPERATURA`).
2. En Render: `CORRIDAS_EXTERNAS=github`. Sin esto, se corren dos veces.
3. Probalo a mano: **Actions → Corridas → Run workflow** (elegí `scraping`).

Detalles:

- Corre al minuto 7 de cada hora: una tarea programada a las 05:30 se ejecuta a las 06:07. GitHub puede demorar el cron unos minutos; si se saltea una hora, la siguiente la recupera.
- El repo es público: los minutos de Actions son gratis.
- Los botones del dashboard (Buscar ahora, Generar nota…) siguen corriendo en Render.

## Atlas Vector Search (opcional)

Mejora la elección de noticias para cada nota: busca entre las más parecidas de toda la base y no solo entre las 200 más recientes.

1. En Atlas → tu cluster → **Atlas Search → Create Search Index → Vector Search**, base `afterdrive`, colección `articulos`, con esta definición (2048 son las dimensiones de `nvidia/nemotron-3-embed-1b`; `text-embedding-3-small` de OpenAI tiene 1536):

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 2048, "similarity": "cosine" },
    { "type": "filter", "path": "embedding_modelo" }
  ]
}
```

   El `filter` hace que la búsqueda compare solo vectores del modelo actual. Un índice viejo sin él sigue andando: la búsqueda se reintenta sin filtro y avisa en el log. Antes de usarlo, corré una vez `python -m afterdrive.ingesta.embeddings` para etiquetar los vectores existentes.

2. Poné el nombre del índice en `ATLAS_VECTOR_INDEX` (Render y, si usás la opción B, también en la variable de GitHub).

Si el índice no existe o Atlas falla, la elección sigue como antes, con un aviso en el log. Si cambiás el modelo de embeddings (p. ej. a la API paga), el índice tiene que tener sus dimensiones: editalo con el `numDimensions` nuevo y corré el backfill.

## Qué limita el plan free de Render

| Límite | Efecto |
|---|---|
| < 600 MB de RAM | Nunca usa Chromium: los sitios con Cloudflare o JavaScript caen a Wayback (salvo con la opción B) |
| 0,1 CPU | El scraping con muchas fuentes es lento (salvo con la opción B) |
| Una Corrida a la vez | Mientras corre el scraping, una nota espera en la cola |
| Se duerme | Ver arriba |

**La redacción no usa la CPU de Render**: el LLM corre en el proveedor.

## Ver qué pasó

- **Dashboard → Corridas**: estado, duración, error y log de cada Corrida (de Render o de GitHub).
- **Logs de Render** o **GitHub → Actions → Corridas**: todo lo que imprime el proceso.

## Local igual que producción

```bash
docker build -t afterdrive .
docker run --env-file .env -p 5000:5000 -m 512m afterdrive
```
