# ── Etapa 1: build del dashboard (Express) ────────────────────────────────────
FROM node:20-alpine AS dash
WORKDIR /dash
COPY express/package*.json ./
RUN npm ci
COPY express/tsconfig.json .
COPY express/src/ ./src/
RUN npm run build

# ── Etapa 2: imagen final (API + dashboard) ───────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Dependencias de sistema necesarias para Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --default-timeout=300 --no-cache-dir -r requirements.txt

# Scrapling (StealthyFetcher) usa patchright (Chromium). Instalamos ESE navegador
# en una ruta compartida (/ms-playwright) para que el usuario no-root lo encuentre
# en runtime — si no, el browser queda en el cache de root y appuser no lo ve.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m patchright install --with-deps chromium && \
    python -c "from scrapling.cli import install; install([], standalone_mode=False)"

# Crear usuario no-root
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copiar código fuente
COPY db.py .
COPY lm_studio.py .
COPY embeddings.py .
COPY flask_api.py .
COPY config_store.py .
COPY generar_articulo.py .
COPY scraper.py .
COPY scraper_afterdrive.py .
COPY regiones.py .
COPY generar_nota_fase2.py .
COPY scheduler.py .
COPY add_url.py .
COPY discover_sources.py .
COPY run_automation.py .
COPY resource_detector.py .

# Dashboard estático generado en la etapa 1
COPY --from=dash /dash/dist/public/ ./static/

# Cambiar propiedad y usar usuario no-root
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 --timeout 1800 flask_api:app"]
