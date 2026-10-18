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

> **Un solo worker es obligatorio.** El programador de tareas, el lock de Corridas y el contador de intentos de login viven en memoria. Con dos workers habría dos programadores y dos Corridas a la vez.

## Primer despliegue

1. En [Render](https://render.com): **New → Blueprint** con este repo (usa `render.yaml`).
2. Cargá en **Environment** las variables marcadas `sync: false`: `MONGO_URI`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `NVIDIA_EMB_MODEL`, `RENDER_EXTERNAL_URL`, `ADMIN_USER`, `ADMIN_PASSWORD_HASH` (en Render va **sin** comillas). `SECRET_KEY` y `CRON_TOKEN` las genera Render.
3. En Atlas, **Network Access** tiene que permitir `0.0.0.0/0`: Render free no tiene IP fija.
4. Configurá un monitor externo (ver abajo).

## Que no se duerma

Si la instancia está dormida, **las tareas programadas no corren**. Tres capas:

| Capa | Cómo | Costo |
|---|---|---|
| Keep-alive interno | `flask_api.py` le pega a `RENDER_EXTERNAL_URL/health` cada 5 min | Gratis, no alcanza solo |
| **Monitor externo** (recomendado) | UptimeRobot o cron-job.org: `GET /health` cada 5–10 min | Gratis |
| Cron externo a hora fija | `POST /api/run-automation` y `/api/run-generacion` con `Authorization: Bearer <CRON_TOKEN>` | Gratis |

`render.yaml` define también cron jobs de Render, pero **solo funcionan en plan pago**.

Si el cron externo y el programador interno piden lo mismo mientras la primera todavía espera en la cola, no se duplica. Si la primera ya empezó, la segunda queda en espera y corre después.

## Qué limita el plan free

| Límite | Efecto |
|---|---|
| < 600 MB de RAM | Nunca usa Chromium: los sitios con Cloudflare o JavaScript fallan o caen a Wayback |
| 0,1 CPU | El scraping con muchas fuentes es lento |
| Una Corrida a la vez | Mientras corre el scraping, una nota espera en la cola |
| Se duerme | Ver arriba |

**La redacción no usa la CPU de Render**: el LLM corre en el proveedor. La calidad y la velocidad de las notas dependen más del modelo que del plan.

## Ver qué pasó

- **Dashboard → Corridas**: estado, duración, error y log de cada Corrida (últimas 500 líneas, guardadas en Mongo).
- **Logs de Render**: todo lo que imprime el proceso, incluidos los prints del scheduler (`[Scheduler]`), la cola (`[Cola]`) y la base (`[DB]`).

## Local igual que producción

```bash
docker build -t afterdrive .
docker run --env-file .env -p 5000:5000 -m 512m afterdrive
```
