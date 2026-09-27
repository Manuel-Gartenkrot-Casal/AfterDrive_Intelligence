# Enviar artículos a HubSpot: Guía completa

HubSpot ofrece dos formas de crear artículos de blog, dependiendo del tipo de cuenta y el tipo de contenido:

## 1. Endpoints de la API de HubSpot

### Opción A: Blog clásico (recomendado para la mayoría)
```
POST https://api.hubapi.com/blogs/v3/blog/{blog_guid}/posts
```
- Requiere: `blog_guid` (ID único del blog)
- Auth: `access_token` o `hapikey` como parámetro de query

### Opción B: HubSpot CMS Hub (para sitios propios)
```
POST https://api.hubapi.com/cms/v3/blogs/{blog_guid}/posts
```
- Requiere: `blog_guid` y permisos de CMS
- Auth: `access_token` OAuth 2.0

## 2. Parámetros obligatorios

Para crear un artículo, envía un JSON con estos campos:

```json
{
  "title": "Título del artículo",
  "author": "Nombre del autor (opcional)",
  "slug": "título-en-minúsculas-con-guiones",  // opcional, se genera automáticamente
  "publish_date": "2026-01-15T14:30:00Z",  // opcional, si no se envía se publica al instante
  "meta_description": "Descripción meta de 150 caracteres (opcional)",
  "content": "Cuerpo del artículo en HTML o formato de Markdown (opcional, dependiendo del modo)",
  "tags": ["etiqueta1", "etiqueta2"],  // opcional
  "status": "PUBLISHED", "DRAFT", "UNPUBLISHED"  // por defecto: PUBLISHED
}
```

## 3. Autenticación

Hay dos formas de autenticar:

### A. API Key (más simple)
```
?hapikey=tu-api-key-aqui
```
En el query string de la URL.

### B. OAuth 2.0 (recomendado para producción)
- Obtener `access_token` mediante el flujo de OAuth
- Enviar en header: `Authorization: Bearer {access_token}`

## 4. Ejemplo práctidad con Python (requests)

### Ejemplo 1: Blog clásico con API Key

```python
import requests

API_KEY = "tu-hubspot-api-key"
BLOG_GUID = "tu-blog-guid-aqui"  # Ejemplo: "623456789012345678"

url = f"https://api.hubapi.com/blogs/v3/blog/{BLOG_GUID}/posts"

article_data = {
    "title": "Nuevo artículo sobre autopartes aftermarket",
    "content": "<h1> artículo sobre pastillas de freno </h1><p>Contenido del artículo...</p>",
    "slug": "pastillas-freno-aftermarket-2026",
    "publish_date": "2026-01-15T14:30:00Z",
    "meta_description": "Pastillas de freno de alto rendimiento para el aftermarket automotriz",
    "tags": ["autopartes", "aftermarket", "frenos"],
    "status": "PUBLISHED"
}

params = {
    "hapikey": API_KEY
}

response = requests.post(url, json=article_data, params=params)

if response.status_code == 200:
    print("¡Artículo publicado exitosamente!")
    print("URL del artículo:", response.json().get("url"))
else:
    print(f"Error: {response.status_code}")
    print(response.text)
```

### Ejemplo 2: CMS Hub con OAuth token

```python
import requests

ACCESS_TOKEN = "tu-access-token-oauth"
BLOG_GUID = "tu-blog-guid-aqui"

url = f"https://api.hubapi.com/cms/v3/blogs/{BLOG_GUID}/posts"

article_data = {
    "title": "Nuevo artículo sobre autopartes aftermarket",
    "content": "<h1> artículo sobre pastillas de freno </h1><p>Contenido del artículo...</p>",
    "slug": "pastillas-freno-aftermarket-2026",
    "publish_date": "2026-01-15T14:30:00Z",
    "meta_description": "Pastillas de freno de alto rendimiento para el aftermarket automotriz",
    "tags": ["autopartes", "aftermarket", "frenos"],
    "status": "PUBLISHED"
}

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

response = requests.post(url, json=article_data, headers=headers)

if response.status_code == 200:
    print("¡Artículo publicado exitosamente!")
else:
    print(f"Error: {response.status_code}")
    print(response.text)
```

## 5. Consideraciones importantes

### Límites de tasa:
- HubSpot limita las requests según el plan
- Typical: 100-1000 requests por minuto
- Implementa backoff exponencial ante errores 429

### Validaciones comunes:
- El `slug` debe ser único por blog
- El `title` no puede estar vacío
- El `content` debe tener al menos 50 caracteres (según modo)
- Las `tags` deben existir en la cuenta o crearse primero

### Formato del contenido:
- **Modo "classic"**: HTML aceptado directamente
- **Modo "markdown"**: Usar `content_mode: "markdown"` y el contenido en formato Markdown
- **Modo "wysiwyg"**: Contenido Rich Text con formateo

### Props adicionales para después Drive:

Dado que trabajas con el sector automotriz aftermarket, te recomiendo añadir:

1. **`categories`**: `["autopartes", "aftermarket"]` (asegúrate de que existan en HubSpot)
2. **`hubspot_associations`**: Para asociar el artículo con empresas específicas (proveedores, talleres)
3. **`localization`**: Para versiones en múltiples idiomas (`"lang": "es"`)

## 6. Flujo recomendado en AfterDrive

Dado tu pipeline actual, el flujo ideal sería:

1. **Scrapeo** → `scraper.py` extrae artículos
2. **Clasificación** → `jev_clasificador.py` (o LLM) filtra relevancia
3. **Enriquecimiento** → Enriquecer con datos adicionales si es necesario
4. **Publicación en HubSpot** → Script/python que itera sobre los artículos aprobados y los envía a HubSpot
5. **Sincronización** → Opcional: mantener IDs en la base de MongoDB para evitar duplicados

### Script wrapper recomendado:

Podrías crear un script `publicar_hubspot.py` que:

1. Obtiene los artículos aprobados de MongoDB (`col_articulos` donde `aprobado=True`)
2. Para cada artículo, llama al endpoint correspondiente de HubSpot
3. Guarda el `hubspot_article_id` en el artículo MongoDB para futuras actualizaciones
4. Genera un reporte con: publicados, errores, duplicados

**Ejemplo de flujo en tu repositorio:**

Podrías añadir en `scheduler.py` o crear un nuevo script `publicar_hubspot.py`:

```python
import json
import requests
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/afterdrive"
HUBSPOT_API_KEY = "tu-api-key"
BLOG_GUID = "tu-blog-guid"

client = MongoClient(MONGO_URI)
col_articulos = client.afterdrive.articulos

# Obtener artículos aprobados sin publicar en HubSpot
articulos = col_articulos.find({
    "hubspot_published": False,
    "aprobado": True
})

for articulo in articulos:
    url = f"https://api.hubapi.com/blogs/v3/blog/{BLOG_GUID}/posts"
    params = {"hapikey": HUBSPOT_API_KEY}
    
    article_data = {
        "title": articulo["titulo"],
        "content": articulo.get("contenido_html", articulo.get("cuerpo", "")),
        "slug": articulo.get("slug", articulo["titulo"].lower().replace(" ", "-").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n")),
        "tags": ["autopartes", "aftermarket"],
        "status": "PUBLISHED"
    }
    
    response = requests.post(url, json=article_data, params={"hapikey": HUBSPOT_API_KEY})
    
    if response.status_code == 200:
        hubspot_id = response.json().get("id")
        # Actualizar MongoDB con el ID de HubSpot
        col_articulos.update_one(
            {"_id": articulo["_id"]},
            {"$set": {"hubspot_published": True, "hubspot_article_id": hubspot_id}}
        )
        print(f"Publicado: {articulo['titulo']} -> {hubspot_id}")
    else:
        print(f"Error al publicar {articulo['titulo']}: {response.status_code} - {response.text}")
```

## 7. Pasos para configurar en AfterDrive

1. **Crear un blog en HubSpot**:
   - Ve a Marketing > Blog > New blog
   - Anota el `blog_guid` (aparece en la URL o mediante API)

2. **Obtener API Key**:
   - Configuración > Cuentas y usuarios > API keys
   - Create API key
   - Copia el `hapikey`

3. **Configurar en AfterDrive**:
   - Agregar `HUBSPOT_API_KEY` y `HUBSPOT_BLOG_GUID` a tu `.env`
   - Modificar `scheduler.py` o crear `publicar_hubspot.py` según el script anterior

4. **Probar con un artículo**:
   - Ejecuta el script manualmente con 1-2 artículos para verificar
   - Revisa el resultado en HubSpot antes de automatizar

## 8. Próximos pasos en tu proyecto

Dado que ya integraste Jev AI para la clasificación, el siguiente paso lógico sería:

1. ✅ Integrar Jev AI (hecho)
2. 📤 **Integrar publicación en HubSpot** (siguiente paso)
3. 🔄 Automatizar la sincronización entre MongoDB y HubSpot
4. 📊 Agregar reporting de artículos publicados vs. rechazados

¿Te gustaría que desarrolle el script `publicar_hubspot.py` completo y lo añada al repositorio, o prefieres implementarlo tú mismo con la guía anterior?