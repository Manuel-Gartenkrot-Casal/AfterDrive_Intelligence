# 05 · Base de datos (MongoDB)

Una base, **`afterdrive`**, en MongoDB Atlas (`MONGO_URI`). No hay esquema formal: estos son los campos que usa el código. Las colecciones se crean solas. Las referencias a colecciones están en `afterdrive/db.py`.

## Entrada: lo que se junta

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `trusted_urls` | Fuentes de noticias | `url`, `nombre_fuente`, `estado` (`activo` / `inactivo`), `fecha_agregado`, `ultima_ejecucion` |
| `suggested_urls` | Sitios recomendados, uno por dominio | `url`, `dominio`, `titulo`, `snippet`, `fecha_sugerida` |
| `articulos` | **Noticias que la IA aprobó** | `url` (clave), `titulo`, `cuerpo`, `fecha`, `fuente`, `embedding`, `usado_para_articulo` |
| `articulos_descartados` | Noticias que la IA rechazó | `url`, `fecha_descarte` |
| `afterdrive_ejemplos` | **Notas reales del blog** (referencia de estilo) | `url`, `titulo`, `cuerpo`, `categoria`, `regiones`, `region_principal` |
| `clientes` | Empresas que se pueden mencionar en las notas | `slug`, `nombre`, `descripcion`, `productos`, `sector`, `url` |
| `afterdrive` | Resto de una versión vieja; ya nadie la escribe | — |

## Salida: lo que se genera

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `notas_fase2` | **Las notas del generador principal** | `contenido` (markdown), `categorias`, `regiones`, `clientes_mencionados`, `puntapie_url`, `persona`, `tema`, `fuentes` (noticias usadas), `evaluacion` (checklist), `proveedor`, `embedding`, `generado_en` |
| `articulos_generados` | Artículos del generador viejo (Fase 1) | `contenido`, `tema`, `fuentes`, `embedding`, `generado_en` |

## Operación

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `config` | Lo que se guarda desde el dashboard, un documento por sección | `key` (`scraping`, `generacion`, `fase2`, `provider`), `value` |
| `corridas` | **La cola y el historial de Corridas** | `tipo`, `params`, `etiqueta`, `origen` (`manual` / `cron`), `estado`, `creada`, `inicio`, `fin`, `resultado`, `log` (últimas 500 líneas) |

Estados de una Corrida: `pendiente → en_curso → ok | error | cancelada | interrumpida`.

## Valores por defecto de `config`

Definidos en `config_store.py`:

| Sección | Por defecto |
|---|---|
| `scraping` | Activo, 05:30, cada 1 día, 10 artículos por fuente |
| `generacion` | Activa, 11:00, cada 1 día, persona `comercial` |
| `fase2` | Sin categorías: **la nota automática no corre hasta que se guarden** |
| `provider` | `openrouter` |

## Búsqueda

- **No se usan índices vectoriales de Atlas**: los embeddings se traen a memoria y la similitud se calcula en Python (`ingesta/embeddings.py`).
- `db.crear_indices_texto()` crea índices de texto en español; lo usa el generador Fase 1.

## Para agregar una colección

1. Declarala en `afterdrive/db.py` (`col_algo = db["algo"]`).
2. Importala **dentro de la función** que la usa (`from afterdrive.db import col_algo`): así los tests la pueden reemplazar.
3. En los tests usá `mongomock` (ver `tests/test_cola.py`).
4. Agregala a la tabla de arriba.
