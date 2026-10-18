# Documentación técnica

Guías cortas para entender y desarrollar AfterDrive Intelligence. Las rutas de archivos son las de la rama `Render_Testing`.

## Por dónde empezar

| Si querés… | Leé |
|---|---|
| Entender qué hace el sistema | [01 Arquitectura](01-arquitectura.md) y el [glosario](../CONTEXT.md) |
| Correrlo en tu máquina | [02 Instalación](02-instalacion.md) |
| Tocar el scraping o la generación | [03 Pipelines](03-pipelines.md) y [04 IA](04-ia.md) |
| Agregar o cambiar datos guardados | [05 Base de datos](05-base-de-datos.md) |
| Cambiar algo del dashboard | [06 Dashboard](06-dashboard.md) |
| Agregar o usar un endpoint | [07 API](07-api.md) |
| Desplegar o revisar producción | [08 Despliegue](08-despliegue.md) |
| Saber qué está roto o pendiente | [09 Deuda y mejoras](09-deuda-y-mejoras.md) |

## Primer día en el proyecto

1. Leé el [glosario](../CONTEXT.md): el código usa esas palabras (Corrida, Nota, Ejemplo, Persona, Saneo…).
2. Leé [01 Arquitectura](01-arquitectura.md).
3. Levantá el proyecto con [02 Instalación](02-instalacion.md) y generá una nota.
4. Corré los tests: `python -m pytest` (y `python -m pytest -m e2e tests/e2e` si tocás el dashboard). Tienen que pasar todos antes y después de cualquier cambio.

## Reglas que conviene saber desde el día 1

- **Todo lo que llama a un proveedor de IA pasa por `afterdrive/ia/llm.py`.** No hagas requests a OpenRouter o NVIDIA desde otro lado.
- **Toda ejecución del pipeline es una Corrida y pasa por `corridas.py` / `cola.py`.** Nunca corren dos a la vez (la RAM de Render no alcanza).
- **Gunicorn corre con un solo worker.** El programador de tareas, el lock de Corridas y el contador de intentos de login viven en memoria.
- **El dashboard no tiene build**: `index.html` más su CSS y JS en `assets/`. Editás, recargás y lo ves.
- **El proyecto está en español**: comentarios, mensajes de commit, interfaz y la mayoría de los nombres del código.

## Otras carpetas

| Carpeta | Qué hay |
|---|---|
| [`adr/`](adr/) | Decisiones de arquitectura, una por archivo. Si tomás una decisión que alguien podría querer deshacer sin saber por qué, escribí un ADR |
| [`superpowers/`](superpowers/) | Specs, planes y prompts de trabajos ya hechos (login y seguridad, mejoras del dashboard). Sirven como historial |
| [`hubspot-integration.md`](hubspot-integration.md) | Publicación en HubSpot: configuración, imagen, etiquetas y errores |

## Otros archivos del repo

| Archivo / carpeta | Qué es |
|---|---|
| `CONTEXT.md` | Glosario del dominio |
| `tests/` | Tests con `pytest`: auth, configuración, Corridas, cola, historial, HubSpot, generación, LLM, redacción, saneo, scheduler, scraper. `tests/e2e/`: el dashboard en un navegador |
| `scripts/demo_mode.py` | Pipeline acelerado para demos en vivo |
| `scripts/manual/` | Pruebas manuales: conexión con NVIDIA y smoke test del dashboard con Playwright |
| `data/*.json` | Volcados de artículos de ejemplo |
| `render.yaml`, `Dockerfile`, `docker-compose.yml` | Despliegue (ver [08](08-despliegue.md)) |
| `AGENTS.md`, `opencode.json`, `.opencode/`, `.agents/` | Configuración de agentes de IA para desarrollo (OpenCode) y sincronización de specs desde Google Drive. No son parte del sistema en producción |
