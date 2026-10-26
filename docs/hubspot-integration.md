# Publicación en HubSpot

Aprobar una nota la **sube a HubSpot como borrador**, en el blog de After Drive de su idioma. El equipo la revisa y la publica desde HubSpot. El código está en `afterdrive/hubspot.py` y el flujo en `afterdrive/historial.py` (`enviar_a_hubspot`, `destino_hubspot`).

## Cómo se usa

1. **Historial → Notas → Para revisar**: abrí la nota, revisala y, si hace falta, editala.
2. En el bloque **Publicación en HubSpot** se ve a qué blog va y con qué etiqueta. Ahí se elige el **autor** (por defecto, Gastón Zelerteins).
3. **Vista previa** (opcional): cómo va a salir en el blog. Ahí se elige la imagen destacada.
4. **Aprobar y subir a HubSpot**: queda aprobada acá y como borrador allá. Además se encola la traducción a los otros dos idiomas: cada versión queda como borrador en su blog (ver [Otros idiomas](#otros-idiomas)).

- Si la subida falla, la nota igual queda aprobada. **Subir borrador a HubSpot** la reintenta.
- Reenviar una nota ya enviada (**Actualizar borrador en HubSpot**) **actualiza el mismo post**, no crea otro. No cambian ni el slug ni el blog, así no se rompen links.
- **Publicar en HubSpot** sigue disponible para publicar desde acá. **Despublicar** vuelve el post a borrador.
- Una nota sin aprobar **no se puede enviar**: nada llega al blog sin que una persona la haya revisado.
- Sin `HUBSPOT_TOKEN`, el botón es "Aprobar" a secas y no se sube nada.

## Configuración (una sola vez)

1. En HubSpot: **Configuración → Integraciones → Apps privadas → Crear app privada**.
2. En **Scopes**, agregá **`content`** y **`files`** (este último para subir las imágenes destacadas). Creá la app y copiá el token (empieza con `pat-`).
3. Cargá las variables en `.env` (local) o en **Environment** de Render:

| Variable | Obligatoria | Qué es |
|---|---|---|
| `HUBSPOT_TOKEN` | Sí | Token de la app privada |
| `HUBSPOT_BLOG_PRUEBAS` | No | Manda **todas** las notas a este blog. Para probar: `114283349257` (Blog test). Vacío en producción |

> **Migración:** `HUBSPOT_BLOG_ID` ya no se usa (antes era el blog de producción). Borrala del Environment de Render: el blog ahora sale del idioma de cada nota.
| `HUBSPOT_IMAGEN_DEFAULT` | No | URL https de la imagen destacada para las notas que no tienen una propia |
| `HUBSPOT_TRADUCCIONES` | No | `0` apaga las versiones en los otros idiomas |
| `HUBSPOT_LENGUAJES` | No | Código de idioma de cada blog si no es `es`, `pt-br`, `en`. Ej.: `es=es-ar,pt=pt-br,en=en` |

Para probar la API a mano hay una colección de Postman en [hubspot-postman/](hubspot-postman/README.md).

## A dónde va cada nota

**Blog**: sale del idioma de la nota (`idioma`). Las notas nuevas se escriben todas en portugués, así que el post principal va al blog PT y el español y el inglés son sus traducciones. Las notas anteriores a este cambio lo deducen de sus regiones (`redaccion.voz`).

| Idioma de la nota | Blog | Autor por defecto (Gastón Zelerteins) |
|---|---|---|
| Español (Argentina, neutro) | After Drive ES `41065736183` | `37798507784` |
| Portugués (Brasil) | After Drive PT `43859303259` | `192904642075` |
| Inglés (Asia) | After Drive EN `43859745706` | `194508336788` |
| Chino | No se sube: no hay blog en chino | — |

**Etiquetas**: una por categoría de la nota, **la que ya existe en HubSpot en el idioma del blog** (tabla `ETIQUETAS` en `hubspot.py`; por ejemplo, autopartes → Autopartes, Autopeças, Auto Parts). Nunca se crean etiquetas nuevas, porque son compartidas por toda la cuenta. Si se agrega una categoría a `CATEGORIAS`, hay que sumar sus 3 ids a `ETIQUETAS`; un test lo controla.

**Autor**: los autores de HubSpot son por idioma. El selector muestra solo los del idioma de la nota, y el elegido se guarda en la nota (`hubspot_autor_id`).

## Qué se manda

API de CMS v3: `POST /cms/v3/blogs/posts` para crear y `PATCH /cms/v3/blogs/posts/{id}` para actualizar, con `Authorization: Bearer <HUBSPOT_TOKEN>`.

| Campo de HubSpot | Sale de |
|---|---|
| `contentGroupId` | El blog del idioma (o `HUBSPOT_BLOG_PRUEBAS`). Solo al crear |
| `name`, `htmlTitle` | El título de la nota (la línea `# …`), que se saca del cuerpo para que no salga dos veces |
| `postBody` | El resto de la nota, de Markdown a HTML. Los subtítulos `##` salen como `<h3>`, igual que en los posts del blog |
| `metaDescription` | La última línea en cursiva de la nota, recortada a 155 caracteres sin cortar palabras |
| `blogAuthorId` | El autor elegido o, si no, el autor por defecto del idioma |
| `tagIds` | Las etiquetas de las categorías, en el idioma del blog |
| `slug` | El título sin acentos ni símbolos + 6 caracteres del id de la nota (para que sea único). Solo al crear |
| `state` | `DRAFT` al aprobar; `PUBLISHED` solo con "Publicar en HubSpot" |
| `postBody` (imágenes) | Las 2 imágenes del cuerpo de la nota (`imagenes_cuerpo`), copiadas a los archivos de HubSpot y repartidas entre las secciones. Van también en las traducciones |
| `featuredImage`, `featuredImageAltText` | La imagen de la nota (la foto de una de sus noticias, copiada primero a los archivos de HubSpot; si la copia falla, el link original) o, si no tiene, `HUBSPOT_IMAGEN_DEFAULT`. Sin ninguna, el post sale sin imagen |

En la nota se guarda `hubspot: {id, url, estado, slug, enviado_en}`, `hubspot_autor_id` y, si se publicó, `estado: "publicado"` y `publicado_en`.

## Otros idiomas

Cada nota se escribe en portugués y **se traduce al crearla** al español rioplatense y al inglés (`afterdrive/traducciones.py`). Las traducciones se ven y se editan en el historial. Al subir la nota, una corrida de la Cola (aparece en Actividad) sube cada versión **como borrador**, con el texto guardado. Nunca se publica sola.

1. **Variación de idioma** (`POST /cms/v3/blogs/posts/multi-language/create-language-variation`): HubSpot clona el post original como su traducción, en el blog de ese idioma, y después se le carga el texto traducido, la meta, las etiquetas y el autor de ese idioma. Así quedan vinculadas (selector de idioma y hreflang).
2. Si HubSpot no la crea (por ejemplo, porque los tres blogs no están configurados como versiones de un mismo blog multilenguaje, o porque el código de idioma no coincide), se crea un **borrador normal** en el blog del idioma y se intenta vincularlo con `attach-to-lang-group`.
3. Si tampoco se puede vincular, queda como **borrador suelto**, con un aviso en la nota.

- La traducción queda guardada con la huella del texto original: subir o reenviar sin editar el original **no vuelve a pagar** la traducción, solo actualiza el borrador (con los cambios hechos a mano en esa versión). Si editaste el original, la traducción queda desactualizada y al subir se traduce de nuevo (se pierden los cambios a mano de esa versión).
- La traducción mantiene el Markdown, las cifras, los nombres y los enlaces del original (un enlace nuevo se quita). Si sale cortada o sin título, esa versión no se sube y el error se ve al abrir la nota.
- Con `HUBSPOT_BLOG_PRUEBAS`, las versiones van a ese blog sin vincular.
- Al abrir la nota, el bloque **Otros idiomas** muestra cada versión, su link y el texto traducido. **Volver a subir las traducciones** reintenta.
- Los enlaces a notas de AfterDrive dentro de la traducción siguen apuntando a la nota original (en su idioma).
- **Pendiente de confirmar en la cuenta**: que los blogs ES, PT y EN estén configurados como versiones de un mismo blog multilenguaje y sus códigos de idioma. Probalo primero con una nota.

## Errores

| Mensaje | Qué hacer |
|---|---|
| "HubSpot rechazó el token" (401/403) | Revisá `HUBSPOT_TOKEN` y que la app tenga el scope `content` |
| "No se pudo copiar la imagen a HubSpot… scope 'files'" | Agregá el scope `files` a la app privada. Mientras tanto, la nota se sube con el link original de la foto |
| "No encontró el blog, el post o el autor" (404) | Revisá `HUBSPOT_BLOG_PRUEBAS` (si está cargado) y el autor elegido |
| "No hay un blog de After Drive en el idioma de esta nota" | La nota es en chino: no hay blog para ese idioma |
| "Está limitando las llamadas" (429) | Esperá un minuto |

Referencia oficial: [Blog posts API](https://developers.hubspot.com/docs/api-reference/latest/cms/blogs/posts/guide).
