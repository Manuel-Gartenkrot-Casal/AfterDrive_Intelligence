# Publicación en HubSpot

Las notas **aprobadas** se pueden mandar al blog de AfterDrive en HubSpot desde el dashboard, como borrador o publicadas. El código está en `afterdrive/hubspot.py` y el flujo en `afterdrive/historial.py` (`enviar_a_hubspot`).

## Cómo se usa

1. **Historial → Notas → Para revisar**: abrí la nota, revisala y, si hace falta, editala.
2. **Aprobar**.
3. **Vista previa** (opcional): cómo va a salir en el blog. Ahí se elige la imagen destacada (URL https y texto alternativo).
4. **Borrador en HubSpot** (queda como borrador allá, para terminarla en HubSpot) o **Publicar en HubSpot** (sale en el blog).

- Una nota sin aprobar **no se puede enviar**: nada llega al blog sin que una persona lo haya revisado.
- Reenviar una nota ya enviada **actualiza el mismo post**, no crea otro. El slug no cambia, así no se rompen links.
- **Despublicar** vuelve el post a borrador en HubSpot y la nota a "aprobada".

## Configuración (una sola vez)

1. En HubSpot: **Configuración → Integraciones → Apps privadas → Crear app privada**.
2. En **Scopes**, agregá **`content`**. Creá la app y copiá el token (empieza con `pat-`).
3. Buscá el id del blog (`contentGroupId`) con la [API de configuración de blogs](https://developers.hubspot.com/docs/api-reference/latest/cms/blogs/blog-settings/guide) (lista los blogs de la cuenta con su id), o en la configuración del blog dentro de HubSpot.
4. Cargá las variables en `.env` (local) o en **Environment** de Render:

| Variable | Obligatoria | Qué es |
|---|---|---|
| `HUBSPOT_TOKEN` | Sí | Token de la app privada |
| `HUBSPOT_BLOG_ID` | Sí | Id del blog (`contentGroupId`) |
| `HUBSPOT_AUTOR_ID` | No | Id del autor del blog (`blogAuthorId`) |
| `HUBSPOT_IMAGEN_DEFAULT` | No | URL https de la imagen destacada para las notas que no tienen una propia |
| `HUBSPOT_IDIOMA` | No | Idioma de las etiquetas que se crean (por defecto `es`) |

Sin las dos primeras, los botones de HubSpot no aparecen.

## Qué se manda

API de CMS v3: `POST /cms/v3/blogs/posts` para crear y `PATCH /cms/v3/blogs/posts/{id}` para actualizar, con `Authorization: Bearer <HUBSPOT_TOKEN>`.

| Campo de HubSpot | Sale de |
|---|---|
| `name`, `htmlTitle` | El título de la nota (la línea `# …`), que se saca del cuerpo para que no salga dos veces |
| `postBody` | El resto de la nota, de Markdown a HTML |
| `metaDescription` | La última línea en cursiva de la nota |
| `slug` | El título sin acentos ni símbolos + 6 caracteres del id de la nota (para que sea único) |
| `state` | `DRAFT` o `PUBLISHED` |
| `featuredImage`, `featuredImageAltText` | La imagen de la nota o, si no tiene, `HUBSPOT_IMAGEN_DEFAULT`. Sin ninguna, el post sale sin imagen |
| `tagIds` | Las categorías de la nota, con su nombre legible. Las etiquetas que no existen en el blog se crean (`/cms/v3/blogs/tags`). Si falla, el post se manda igual sin etiquetas |

En la nota se guarda `hubspot: {id, url, estado, enviado_en}` y, si se publicó, `estado: "publicado"` y `publicado_en`.

## Errores

| Mensaje | Qué hacer |
|---|---|
| "HubSpot rechazó el token" (401/403) | Revisá `HUBSPOT_TOKEN` y que la app tenga el scope `content` |
| "No encontró el blog o el post" (404) | Revisá `HUBSPOT_BLOG_ID` |
| "Está limitando las llamadas" (429) | Esperá un minuto |

Referencia oficial: [Blog posts API](https://developers.hubspot.com/docs/api-reference/latest/cms/blogs/posts/guide).
