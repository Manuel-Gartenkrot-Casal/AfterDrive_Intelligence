# 09 · Deuda conocida y mejoras

## Problemas conocidos

| Problema | Dónde | Impacto |
|---|---|---|
| **Dos ramas sin unificar** | `Render_Testing` y `Front-Testing` | Cada una tiene mejoras que la otra no (cola, noticias de contexto y evaluación en una; historial, borrador/publicado y traductor en la otra). Cada arreglo se hace dos veces. **Es lo más importante pendiente** |
| Se vuelven a bajar artículos ya vistos | `ingesta/scraper.py` | No consulta `articulos` ni `articulos_descartados` antes de descargar. Existe `db.obtener_urls_procesados()` sin usar |
| El generador Fase 1 no lee las noticias | `generacion/generar_articulo.py` | La fuente `"general"` apunta a `articulos_generados` en vez de `articulos`. Probablemente un error |
| Modo degradado aprueba todo | `ingesta/ingesta.py` | Si el LLM no responde, puede entrar contenido irrelevante a `articulos`. Es intencional |
| Descartes sin motivo | `articulos_descartados` | Solo guarda la URL (`Front-Testing` ya lo corrige) |
| Endpoints viejos fuera de la cola | `flask_api.py` | "Probar y agregar", "Buscar recomendaciones", Fase 1 y los `/stream/*` corren sincrónicos y responden "ocupado" si hay otra Corrida |
| Log de la Corrida con ruido | `cola.py` | Mientras corre un scraping o una nota programada, lo que imprimen otros threads también entra a su log |
| Una generación empezada no se cancela | `cola.py` | Corre dentro del proceso; hay que esperar que termine |
| Todo en memoria de un proceso | lock, scheduler, login | Obliga a un solo worker. El contador de intentos de login se reinicia en cada deploy |
| Sin publicación automática | — | Las notas quedan en la base. Ver [`hubspot-integration.md`](hubspot-integration.md) |
| Código sin uso | `ia/lm_studio.py` (`extraer_temas`, `research_contexto`), `ingesta/jev_clasificador.py`, colección `afterdrive` | Ruido al leer |
| Historial de Corridas sin limpieza | colección `corridas` | Crece sin límite; conviene borrar las de más de 30 días |

## Mejoras con mejor relación costo / beneficio

| Mejora | Por qué |
|---|---|
| **Unificar las ramas** | Deja de duplicar trabajo |
| **No re-descargar lo ya procesado** | Menos descargas, llamadas al LLM y embeddings en cada scraping |
| **MongoDB Atlas Vector Search** | La similitud pasa a Atlas (gratis en M0): menos RAM en Render y búsquedas en milisegundos |
| **Scraping y generación en GitHub Actions** | Gratis, ~7 GB de RAM, Chromium disponible y no depende de que Render esté despierto. Render queda solo para el dashboard. Requiere mover el lock de Corridas a Mongo |
| **Ingesta por RSS / sitemaps** | Menos CPU, menos bloqueos y alta de fuentes más rápida |
| **Clasificar en lote** | Menos llamadas al LLM y menos errores 429 |
| **Deduplicar notas** | El embedding de cada nota ya se guarda: compararlo evita notas casi iguales |
| **Imagen sin Chromium para Render** | Producción nunca lo usa: imagen más chica y deploys más rápidos |
| **Proveedor de IA pago o modelo local** | Calidad más estable, sin límites ni bajas sorpresivas. Con modelos chicos, centavos por nota |

## Alternativas de infraestructura

De menor a mayor cambio (precios a verificar):

| Opción | Gana | Pierde |
|---|---|---|
| Monitor externo como cron | Tareas confiables, gratis | Sigue en 512 MB |
| Render Starter (~USD 7/mes) | No se duerme; cron jobs de `render.yaml` | Sigue en 512 MB |
| Render Standard (~USD 25/mes) | 2 GB: Chromium y scraping rápido | Costo |
| Google Cloud Run + Jobs | Pago por uso, 2–4 GB por job | Más configuración; lock y login a Mongo |
| VM propia (p. ej. Oracle Always Free) | Muchos recursos gratis, hasta modelo local | Hay que administrarla |

**Recomendación:** Atlas Vector Search + GitHub Actions para scraping y generación, y Render (free o Starter) solo para el dashboard.
