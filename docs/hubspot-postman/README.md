# Probar la API de HubSpot con Postman

Colección para probar a mano las mismas llamadas que hace `afterdrive/hubspot.py`.

## 1. Importar
1. Postman → **Import** → arrastrá `AfterDrive-HubSpot.postman_collection.json`.
2. Abrí la colección → pestaña **Variables** → en `token` pegá el token **solo en "Current value"** (no en "Initial value"). Así no viaja si exportás o compartís la colección. Nunca lo subas al repo.

## 2. Variables
| Variable | Valor por defecto | Qué es |
|---|---|---|
| `blogId` | `114283349257` | **Blog test**. Las pruebas de escritura van acá |
| `authorId` | `37798507784` | Gaston Zelerteins (ES) |
| `tagId` | `193208803411` | Una etiqueta existente |
| `postReferenciaId` | `41066128552` | Un post real en PT para ver cómo está armado |
| `postId` | (vacío) | Se llena solo al crear el borrador |

## 3. Correr
**Carpeta 1 Lectura**: no cambia nada. Mirá la **Console** de Postman (abajo a la izquierda), donde cada request deja una tabla con IDs.
- *Listar blogs*: elegí el blog destino con Melisa. Los principales son ES `41065736183`, PT `43859303259`, EN `43859745706` y ES-AR `196388597892`.
- *Listar autores*: los autores son **por idioma**. El mismo nombre tiene un ID distinto en ES, PT y EN, así que usá el del idioma del blog.
- *Chequear scope files*: si da **403**, la app privada no tiene el scope `files` y AfterDrive no va a poder subir imágenes destacadas.

**Carpeta 2 Ciclo de un post de prueba**: corré los 4 pasos en orden (o con **Run folder**): crear borrador, leer, editar, borrar. Antes de empezar, confirmá que `blogId` sigue siendo el Blog test.

Cada request ya trae tests (pestaña **Tests**) que comprueban el código de respuesta, el estado DRAFT y el blog correcto.

## 4. Pasarlo a AfterDrive
Con los IDs elegidos, cargá en `.env` (local) o en Environment de Render:

```
HUBSPOT_TOKEN=pat-...
# Solo para pruebas: manda todo al Blog test. Vacío en producción.
HUBSPOT_BLOG_PRUEBAS=114283349257
```

El blog, el autor y las etiquetas salen solos del idioma y las categorías de cada nota. Después, en el dashboard: abrí una nota → **Aprobar y subir a HubSpot** → revisala en HubSpot. Detalle completo en [../hubspot-integration.md](../hubspot-integration.md).
