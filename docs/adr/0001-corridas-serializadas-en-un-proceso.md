# Las Corridas se serializan con un lock en memoria de un único proceso

Todas las Corridas (cron, botones del dashboard y endpoints con streaming) pasan por `corridas.py`, que toma un lock en memoria y rechaza, sin encolar, cualquier Corrida que llegue mientras otra está en curso. En el plan free de Render, dos Corridas simultáneas (por ejemplo scraping con navegador y generación) se quedan sin RAM, y encolar dejaría requests HTTP colgadas hasta 30 minutos.

## Consequences

El lock solo protege dentro de un proceso: depende de que gunicorn corra con `--workers 1` (ver Dockerfile). Subir la cantidad de workers o instancias exige mover el lock a Mongo (o a Key Value) antes.
