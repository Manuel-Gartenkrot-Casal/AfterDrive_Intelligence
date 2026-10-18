# 02 · Instalación: de cero a la primera nota

## 1. Lo que necesitás

| Herramienta | Obligatoria |
|---|---|
| [Git](https://git-scm.com/downloads) | Sí |
| [Python 3.12](https://www.python.org/downloads/) (mínimo 3.11) | Sí, para correr local. En Windows marcá **"Add python.exe to PATH"** |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Solo si preferís correrlo en contenedor |
| [LM Studio](https://lmstudio.ai/) | No. Solo para usar IA local sin APIs |

Y tres cuentas (todas tienen plan gratis):

| Servicio | Para qué | Dónde |
|---|---|---|
| MongoDB Atlas | Base de datos | <https://www.mongodb.com/cloud/atlas> |
| OpenRouter | LLM que redacta y clasifica | <https://openrouter.ai/keys> |
| NVIDIA Build | Embeddings | <https://build.nvidia.com> → "Get API Key" |

> Si ya tenés acceso al cluster de Mongo del proyecto, pedí la cadena de conexión y salteá el paso 3.

## 2. Clonar

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/AfterDrive_Intelligence.git
cd AfterDrive_Intelligence
git checkout Render_Testing
```

## 3. Crear la base en MongoDB Atlas

1. Crear un cluster gratis (**M0**).
2. **Database Access** → crear un usuario con contraseña.
3. **Network Access** → agregar tu IP (o `0.0.0.0/0`, necesario para Render).
4. **Connect → Drivers** → copiar la cadena `mongodb+srv://...`.

No hace falta crear colecciones: se crean solas.

## 4. Instalar dependencias

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

Opcional: `python -m patchright install chromium` para scrapear con navegador. Solo se usa con más de 600 MB de RAM libre.

## 5. Completar el `.env`

```bash
cp .env.example .env                   # Windows (cmd): copy .env.example .env
```

Generá la contraseña del dashboard (como hash) y dos claves secretas:

```bash
python -c "from getpass import getpass; from werkzeug.security import generate_password_hash as g; print(g(getpass('Contraseña: ')))"
python -c "import secrets; print(secrets.token_urlsafe(48))"     # SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"     # CRON_TOKEN (otro valor)
```

Mínimo indispensable en `.env`:

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

El resto de las variables están explicadas en `.env.example`. **El `.env` nunca se sube al repo** (es público).

## 6. Levantar

**Con Python** (lo más cómodo para desarrollar):

```bash
python -m afterdrive.flask_api
```

**Con Docker** (igual que producción):

```bash
docker compose up --build                                   # 2 GB de RAM
docker build -t afterdrive . && docker run --env-file .env -p 5000:5000 -m 512m afterdrive   # simula Render
```

Abrí <http://localhost:5000> y entrá con tu usuario. En la consola tienen que aparecer `[DB] Conectando a MongoDB…`, `[Cola] consumidor iniciado.` y `[Scheduler] iniciado.`

## 7. Primera nota

Todo desde el dashboard, en la barra lateral:

1. **Crear nota → Sincronizar Ejemplos** (vista Desarrollador): baja notas reales del blog como referencia de estilo.
2. **Fuentes**: pegá la URL del listado de noticias de un sitio del rubro y tocá **Probar y agregar**. O usá **Buscar recomendaciones**.
3. **Programación → Buscar ahora** ("Scrapear ahora" en la vista Desarrollador): corre el scraping una vez para tener noticias de contexto.
4. **Crear nota**: elegí categorías y tocá **Generar nota**. Mirá el avance en **Corridas**.
5. Para que se genere sola: dejá las categorías elegidas y tocá **Guardar cambios**. Revisá los horarios en **Programación**.

## Tests y lint

```bash
python -m pytest           # todos tienen que pasar
ruff check afterdrive tests
```

Los tests no tocan Mongo real ni proveedores de IA: usan fakes y `mongomock`.

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| "Login no configurado en el servidor" | Falta `ADMIN_USER`, `ADMIN_PASSWORD_HASH` o `SECRET_KEY` |
| Contraseña correcta pero no entra (Docker) | Poné el hash entre comillas simples en `.env` |
| "Demasiados intentos" | 5 fallos seguidos: esperá 15 minutos o reiniciá el servidor |
| `ServerSelectionTimeoutError` | Revisá `MONGO_URI` y que tu IP esté en *Network Access* de Atlas |
| HTTP 404/410 al generar | El modelo fue dado de baja: cambiá `OPENROUTER_MODEL` / `NVIDIA_MODEL` por uno de la lista que muestra el error |
| HTTP 429 | Límite del plan gratis del proveedor: esperá o cambiá de modelo |
| Artículos sin `embedding` | Falta `NVIDIA_API_KEY`. Configurala y corré `python -m afterdrive.ingesta.embeddings` |
| La nota automática no se genera | No hay categorías guardadas: elegilas en Crear nota y tocá Guardar cambios |
| Algo quedó "En espera" mucho tiempo | Hay otra Corrida corriendo; miralo en la sección Corridas |

## Scripts por línea de comandos

```bash
python -m afterdrive.ingesta.run_automation 10                    # scraping de fuentes
python -m afterdrive.ingesta.add_url https://sitio.com/noticias   # probar y dar de alta una fuente
python -m afterdrive.ingesta.discover_sources                     # buscar fuentes nuevas
python -m afterdrive.ingesta.embeddings                           # completar embeddings faltantes
python -m afterdrive.generacion.scraper_afterdrive --tags autopartes marketplaces --max 5
python -m afterdrive.generacion.generar_nota_fase2 --categorias autopartes --regiones argentina --persona comercial
```

Estos scripts no pasan por la cola del dashboard: si los corrés contra la base de producción, pueden coincidir con una Corrida del servidor.
