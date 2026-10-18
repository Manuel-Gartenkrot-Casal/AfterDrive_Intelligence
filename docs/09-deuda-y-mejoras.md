# 09 · Deuda conocida y mejoras

## Problemas conocidos

| Problema | Dónde | Impacto |
|---|---|---|
| Modo degradado aprueba todo | `ingesta/ingesta.py` | Si el LLM no responde, puede entrar contenido irrelevante a `articulos`. Es intencional; ahora se reintenta al minuto en vez de quedar activo |
| Una generación empezada en el servidor no se cancela | `cola.py` | Corre dentro del proceso; hay que esperar que termine |
| Log de la Corrida con ruido | `cola.py` | Mientras corre un scraping o una nota programada en el servidor, lo que imprimen otros threads también entra a su log |
| Todo en memoria de un proceso | lock, scheduler, login | Obliga a un solo worker. El contador de intentos de login se reinicia en cada deploy |
| Código sin uso | `ingesta/jev_clasificador.py`, colección `afterdrive`. `ia/lm_studio.generar_articulo` solo lo usa `scripts/demo_mode.py` | Ruido al leer |
| `Front-Testing` sigue existiendo (**pospuesto**) | rama | Sus funciones de historial, estados y descartes con motivo ya están en `Render_Testing`. Quedan sin decidir su rediseño visual (`workspace.*`, Express con TypeScript) y qué hacer con la rama. El traductor a portugués se descartó |

## Mejoras pendientes

| Mejora | Por qué |
|---|---|
| **Ingesta por RSS / sitemaps** | Menos CPU, menos bloqueos y alta de fuentes más rápida |
| **Clasificar en lote** | Menos llamadas al LLM y menos errores 429 |
| **Imagen sin Chromium para Render** | Si las Corridas van a GitHub Actions, Render nunca lo usa: imagen más chica y deploys más rápidos |
| **Lock de Corridas en Mongo** | Permitiría más de un worker y que los botones del dashboard también corran fuera de Render |
| **Proveedor de IA pago o modelo local** | Calidad más estable, sin límites ni bajas sorpresivas. Con modelos chicos, centavos por nota |

## Alternativas de infraestructura

| Opción | Gana | Pierde |
|---|---|---|
| **GitHub Actions para las Corridas** (ya disponible) | RAM, Chromium, tareas confiables, gratis | Hay que configurar secretos |
| Render Starter (~USD 7/mes) | No se duerme | Sigue en 512 MB |
| Render Standard (~USD 25/mes) | 2 GB: Chromium y scraping rápido | Costo |
| Google Cloud Run + Jobs | Pago por uso, 2–4 GB por job | Más configuración; lock y login a Mongo |
| VM propia (p. ej. Oracle Always Free) | Muchos recursos gratis, hasta modelo local | Hay que administrarla |

Precios a verificar.
