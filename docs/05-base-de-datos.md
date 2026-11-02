# 05 · Base de datos (MongoDB)

Una base, **`afterdrive`**, en MongoDB Atlas (`MONGO_URI`). No hay esquema formal: estos son los campos que usa el código. Las colecciones se crean solas y los índices se crean al arrancar (`db.crear_indices()`). Las referencias a colecciones están en `afterdrive/db.py`.

## Entrada: lo que se junta

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `trusted_urls` | Fuentes de noticias | `url`, `nombre_fuente`, `estado` (`activo` / `inactivo`), `fecha_agregado`, `ultima_ejecucion` |
| `suggested_urls` | Sitios recomendados, uno por dominio | `url`, `dominio`, `titulo`, `snippet`, `fecha_sugerida` |
| `articulos` | **Noticias que la IA aprobó** | `url` (clave), `titulo`, `cuerpo`, `fecha` (publicación), `fuente`, `embedding`, `usado_para_articulo`, `usado_en` (cuándo alimentó una nota), `ficha` (resumen, hechos, cifras, empresas, fecha), `imagen` (`{url, alt}` de la foto principal del artículo; `null` si se buscó y no tenía), `imagenes` (hasta 8 `{url, alt}`: todas las fotos de la página, la principal primero; falta en los artículos guardados antes, y se completa la primera vez que una nota necesita más fotos) |
| `articulos_descartados` | Noticias que la IA rechazó | `url`, `titulo`, `cuerpo` (hasta 5000 caracteres), `fuente`, `fecha`, `razon`, `fecha_descarte`. Las viejas solo tienen `url` |
| `afterdrive_ejemplos` | **Notas reales del blog** (referencia de estilo) | `url`, `titulo`, `cuerpo`, `categoria`, `regiones`, `region_principal` |
| `clientes` | Empresas que las notas pueden nombrar y las que no (`clientes.py`) | `slug`, `nombre`, `descripcion`, `productos`, `sector`, `url`, `modo` (`mencionar`, o sin el campo los viejos; `no_mencionar`: ninguna nota la nombra), `alias` (otras formas de escribirla, cuentan como mención) |
| `afterdrive` | Resto de una versión vieja; ya nadie la escribe | — |

## Salida: lo que se genera

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `notas_fase2` | **Las notas del generador principal** | `contenido` (markdown), `categorias`, `regiones`, `clientes_mencionados`, `puntapie_url`, `persona`, `tema`, `indicaciones` (lo escrito en la caja de Crear nota), `empresas_prohibidas` (empresas `no_mencionar` que quedaron nombradas en el texto, sin contar la sección de fuentes; se recalcula al editar), `fuentes` (con `reutilizada: true` si la noticia venía de una nota rechazada), `evaluacion`, `calidad`, `proveedor`, `embedding`, `generado_en`, **`estado`**, `motivo_rechazo`, `rechazado_en`, `correcciones_usadas`, `imagen` (`url`, `alt`, `origen`: la noticia o la página del banco de la que sale la foto, y `hubspot_url`: la copia en los archivos de HubSpot), `imagenes_cuerpo` (las 4 del texto, con los mismos campos y, si salen de un banco de imágenes, `banco`, `credito` y `atribucion: true` cuando la licencia pide mostrar el crédito), `imagen_eleccion` (`metodo`: ia, primera o ninguna, y `motivo`), `notas_blog_sugeridas` y `notas_blog_citadas` (notas de AfterDrive que se le pasaron para citar y las que citó), `traducciones` (por idioma: `contenido`, `huella` del original, `traducido_en`), `hubspot_traducciones` (por idioma: `id`, `url`, `estado`, `slug`, `vinculada`, `aviso` o `error`), `editado_en`, `publicado_en`, `hubspot`, `plan`, `verificacion` (datos respaldados, sin respaldo y dudosos), `estilo` (hallazgos), `seo`, `parecida_a`, `enlaces_quitados`, `calibracion_usada`, `largo`, `costo` (USD total y por tarea de la API paga), `calificacion` (puntaje 1-5, etiquetas, comentario), `contenido_original` (lo que escribió el modelo, antes de la primera edición), `leccion_edicion`, `carrusel` (`textos`: titulo, subtitulo, puntos, cta; `origen_textos`: ia, nota o editado; `idioma`, `url` del blog, `diapositivas`: las 3 URLs `/api/imagenes/<id>`, `pdf_id`, `generado_en`) |
| `notas_descartadas` | Notas que el saneo rechazó | `origen`, `contenido` (crudo, hasta 20000 caracteres), `motivo`, `descartado_en`, parámetros del pedido |
| `articulos_generados` | Notas del generador viejo (Fase 1, ya borrado). Solo se leen en el Historial | `contenido`, `tema`, `fuentes`, `embedding`, `generado_en`, `estado` |

**Estado de una nota**: `borrador` (o sin el campo, las viejas) → `aprobada` / `rechazada` → `publicado`. El valor es `publicado` y no `publicada` por compatibilidad con lo que guardó `Front-Testing`.

**`calidad`**: `{puntaje (0–9), fallas_criticas, intentos, reescrita_por}`.

**`hubspot`**: `{id, url, estado (DRAFT / PUBLISHED), enviado_en}`, solo si se envió.

**`imagen`**: la imagen destacada (https pública): la foto de una noticia de la nota o de un banco de imágenes (con `origen`) o una pegada a mano. Nunca una que pida crédito: HubSpot no muestra texto debajo de la destacada. Al enviar a HubSpot se copia a sus archivos (`hubspot_url`). Sin ella se usa `HUBSPOT_IMAGEN_DEFAULT`. Las fotos de las noticias de la nota están en `fuentes[].imagen`, con `imagen_apta` e `imagen_motivo` si las miró la IA.

## Operación

| Colección | Qué guarda | Campos principales |
|---|---|---|
| `config` | Lo que se guarda desde el dashboard, un documento por sección | `key` (`scraping`, `generacion`, `fase2`, `provider`, `modo_pago`, `ejecutor_externo`), `value` |
| `imagenes` | **En desuso**: imágenes que se generaban con NVIDIA. Ya nada la lee; se puede borrar | |
| `imagenes_subidas` | Imágenes subidas desde la computadora, fotos de Pixabay guardadas y las diapositivas y el PDF de los carruseles (`carrusel: true`; al regenerar se borran las anteriores) | `contenido` (bytes), `mime`, `nombre`, `nota_id`, `fecha` |
| `corridas` | **La cola y el historial de Corridas** (30 días) | `tipo`, `params`, `etiqueta`, `origen` (`manual` / `cron`), `ejecutor` (`servidor` / `github`), `estado`, `creada`, `inicio`, `fin`, `resultado`, `log` (últimas 500 líneas), `cancelar_pedido` |

Estados de una Corrida: `pendiente → en_curso → ok | error | cancelada | interrumpida`.

## Valores por defecto de `config`

Definidos en `config_store.py`:

| Sección | Por defecto |
|---|---|
| `scraping` | Activo, 05:30, cada 1 día, 10 artículos por fuente |
| `generacion` | Activa, 11:00, cada 1 día, persona `comercial`, largo `medio` |
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
