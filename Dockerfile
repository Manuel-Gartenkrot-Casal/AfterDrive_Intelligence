# Imagen única: API Flask + dashboard estático
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
COPY afterdrive/ ./afterdrive/

# Dashboard estático: HTML sin build, Flask lo sirve desde static/
COPY express/src/public/ ./static/

# Cambiar propiedad y usar usuario no-root
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 --timeout 1800 afterdrive.flask_api:app"]
