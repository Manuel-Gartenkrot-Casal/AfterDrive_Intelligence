# 05 · Base de datos (MongoDB)

Una base, **`afterdrive`**, en MongoDB Atlas (`MONGO_URI`). No hay esquema formal: estos son los campos que usa el código. Las colecciones se crean solas y los índices se crean al arrancar (`db.crear_indices()`). Las referencias a colecciones están en `afterdrive/db.py`.

## Entrada: lo que se junta

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `trusted_urls` | Fuentes de noticias | `url`, `nombre_fuente`, `estado` (`activo` / `inactivo`), `fecha_agregado`, `ultima_ejecucion` |
| `suggested_urls` | Sitios recomendados, uno por dominio | `url`, `dominio`, `titulo`, `snippet`, `fecha_sugerida` |
| `articulos` | **Noticias que la IA aprobó** | `url` (clave), `titulo`, `cuerpo`, `fecha` (publicación), `fuente`, `embedding`, `usado_para_articulo` |
| `articulos_descartados` | Noticias que la IA rechazó | `url`, `titulo`, `cuerpo` (hasta 5000 caracteres), `fuente`, `fecha`, `razon`, `fecha_descarte`. Las viejas solo tienen `url` |
| `afterdrive_ejemplos` | **Notas reales del blog** (referencia de estilo) | `url`, `titulo`, `cuerpo`, `categoria`, `regiones`, `region_principal` |
| `clientes` | Empresas que se pueden mencionar en las notas | `slug`, `nombre`, `descripcion`, `productos`, `sector`, `url` |
| `afterdrive` | Resto de una versión vieja; ya nadie la escribe | — |

## Salida: lo que se genera

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `notas_fase2` | **Las notas del generador principal** | `contenido` (markdown), `categorias`, `regiones`, `clientes_mencionados`, `puntapie_url`, `persona`, `tema`, `fuentes`, `evaluacion`, `calidad`, `proveedor`, `embedding`, `generado_en`, **`estado`**, `motivo_rechazo`, `rechazado_en`, `correcciones_usadas`, `imagen`, `editado_en`, `publicado_en`, `hubspot` |
| `notas_descartadas` | Notas que el saneo rechazó | `origen`, `contenido` (crudo, hasta 20000 caracteres), `motivo`, `descartado_en`, parámetros del pedido |
| `articulos_generados` | Notas del generador viejo (Fase 1, ya borrado). Solo se leen en el Historial | `contenido`, `tema`, `fuentes`, `embedding`, `generado_en`, `estado` |

**Estado de una nota**: `borrador` (o sin el campo, las viejas) → `aprobada` / `rechazada` → `publicado`. El valor es `publicado` y no `publicada` por compatibilidad con lo que guardó `Front-Testing`.

**`calidad`**: `{puntaje (0–9), fallas_criticas, intentos, reescrita_por}`.

**`hubspot`**: `{id, url, estado (DRAFT / PUBLISHED), enviado_en}`, solo si se envió.

**`imagen`**: `{url, alt}`, la imagen destacada elegida a mano (https pública). Sin ella se usa `HUBSPOT_IMAGEN_DEFAULT`.

## Operación

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `config` | Lo que se guarda desde el dashboard, un documento por sección | `key` (`scraping`, `generacion`, `fase2`, `provider`, `modo_pago`, `ejecutor_externo`), `value` |
| `corridas` | **La cola y el historial de Corridas** (30 días) | `tipo`, `params`, `etiqueta`, `origen` (`manual` / `cron`), `ejecutor` (`servidor` / `github`), `estado`, `creada`, `inicio`, `fin`, `resultado`, `log` (últimas 500 líneas), `cancelar_pedido` |

Estados de una Corrida: `pendiente → en_curso → ok | error | cancelada | interrumpida`.

## Valores por defecto de `config`

Definidos en `config_store.py`:

| Sección | Por defecto |
|---|---|
| `scraping` | Activo, 05:30, cada 1 día, 10 artículos por fuente |
| `generacion` | Activa, 11:00, cada 1 día, persona `comercial` |
| `fase2` | Sin categorías: **la nota automática no corre hasta que se guarden** |
| `provider` | `openrouter` |
| `modo_pago` | Apagado (`hasta` vacío). Prendido guarda cuándo vence, en UTC |
| `ejecutor_externo` | Cuándo revisó GitHub Actions qué tocaba correr |

## Búsqueda

- **Similitud**: por defecto los embeddings se traen a memoria y la similitud se calcula en Python. Con `ATLAS_VECTOR_INDEX`, la elección de noticias usa además `$vectorSearch` (ver [08 Despliegue](08-despliegue.md)).
- `db.crear_indices_texto()` crea índices de texto en español sobre `articulos` y `articulos_generados`.

## Para agregar una colección

1. Declarala en `afterdrive/db.py` (`col_algo = db["algo"]`) y, si se consulta por algún campo, sumalo a `INDICES`.
2. Importala **dentro de la función** que la usa (`from afterdrive.db import col_algo`): así los tests la pueden reemplazar.
3. En los tests usá `mongomock` (ver `tests/test_cola.py`).
4. Si el historial la tiene que mostrar, agregala a la lista blanca de `historial.SECCIONES`.
5. Agregala a la tabla de arriba.
