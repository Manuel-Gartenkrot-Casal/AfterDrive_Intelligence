# 03 · Pipelines: qué pasa paso a paso

Hay tres flujos: **juntar noticias** (scraping), **escribir notas** (generación) y **revisar y publicar**. El resto los alimenta.

## Scraping de fuentes (todos los días, 05:30)

Archivos: `corridas.py` (`_scrapear_fuentes`), `ingesta/scraper.py`, `ingesta/ingesta.py`.

```
trusted_urls con estado "activo"
      │  por cada fuente
      ▼
scraper.py   baja el listado → detecta links de artículos (prioriza URLs con fecha)
      │      saltea los links ya guardados o descartados antes
      │      baja cada artículo nuevo → trafilatura extrae título, cuerpo y fecha
      │      si el sitio bloquea o está caído → copia de Wayback Machine
      ▼
ingesta.py   el LLM decide si es del rubro
      ├── no ──► articulos_descartados  (con título, cuerpo y motivo)
      └── sí ──► embedding ──► articulos  (upsert por url)
```

- Máximo de artículos por fuente: `max_articulos` (10 por defecto, se cambia en Programación).
- **No se vuelve a procesar lo ya visto**: antes de descargar se consultan `articulos` y `articulos_descartados` (`corridas.ya_procesadas`). El contador de "nuevos" es real.
- Se descartan cuerpos de menos de 100 caracteres.
- **Modo degradado**: si el LLM no responde, el artículo se aprueba igual para no perderlo. La disponibilidad del proveedor se vuelve a chequear al minuto, así que una caída no deja el modo degradado activo para siempre.
- Cómo baja cada página depende de la RAM (`ingesta/resource_detector.py`). Con menos de 600 MB (Render free) nunca usa Chromium: `requests` y, si falla, Wayback. En GitHub Actions (~7 GB) usa Chromium. Se fuerza con `FORCE_PROFILE=alto|medio|bajo`.
- Los dominios que no respondieron van directo a Wayback **solo durante esa corrida**.
- Las fuentes **pausadas** (`estado: "inactivo"`) no se scrapean.

## Alta de una fuente

| Botón | Qué hace |
|---|---|
| **Probar y agregar** (`ingesta/add_url.py`, por la cola) | Scrapea la URL y la clasifica. **Solo si aprueba al menos un artículo**, queda como fuente activa |
| **Agregar** (`POST /api/trusted-urls`) | La agrega directo, sin probarla |
| **Buscar recomendaciones** (`ingesta/discover_sources.py`, por la cola) | Busca sitios del rubro en DuckDuckGo por palabras clave (sin IA) y los deja como sugerencias |

## Ejemplos del blog AfterDrive

`generacion/scraper_afterdrive.py` baja notas **reales** del blog de AfterDrive por categoría (16 categorías) y las guarda en `afterdrive_ejemplos` con las regiones detectadas por palabras clave. Son la **referencia de estilo** del generador. Se corre a mano: **Sincronizar Ejemplos**.

## Generación de notas Fase 2 (todos los días, 11:00)

Archivo: `generacion/generar_nota_fase2.py`. Es el **generador principal**.

**Entrada**

| Parámetro | Qué define |
|---|---|
| Categorías (obligatorio) | De qué trata la nota |
| Regiones | Contexto e idioma: Brasil → portugués, Argentina o sin región → español rioplatense, otras de habla hispana → español neutro |
| Clientes | Empresas que se mencionan como casos reales |
| Puntapié | Una URL a la que la nota tiene que llevar al lector (600–900 palabras). Sin puntapié: 900–1400 palabras |
| Persona | Estilo de redacción (ver [04 IA](04-ia.md)) |
| Tema | Opcional, para acotar |

**Pasos**

1. **Noticias de contexto** (`contexto_noticias.py`): entre las 200 noticias más recientes (y, con Atlas Vector Search, las 100 más parecidas de toda la base) elige 5, combinando parecido con el pedido (65 %), recencia por **fecha de publicación** (25 %) y que no se hayan usado (10 %). **Son la única fuente permitida de cifras, empresas y casos.**
2. **Referencias de estilo**: hasta 2 notas reales por categoría.
3. **Prompt**: `ia/redaccion.py` arma el system prompt (persona + voz de la región). Al pedido se suman las **correcciones**: los motivos de las últimas notas rechazadas en el Historial (hasta 5, de los últimos 60 días, `historial.motivos_recientes`), como errores a no repetir. La nota guarda cuáles usó en `correcciones_usadas`.
4. **Redacción** con el LLM.
5. **Saneo** (`ia/saneo.py`): limpia la respuesta y **la descarta si el modelo escribió su razonamiento en vez de la nota**. Lo descartado queda en `notas_descartadas` con el motivo.
6. **Evaluación**: el LLM revisa la nota contra un checklist de 9 puntos.
7. **Reescritura**: si la nota no pasó el saneo o falló un punto crítico (inventa datos, paywall, repeticiones o estructura), se escribe **una vez más** diciéndole al modelo qué falló. Queda la mejor de las dos.
8. Se guarda en `notas_fase2` como **borrador**, con su evaluación y `calidad` (puntaje, fallas, intentos), y las noticias usadas quedan marcadas.

**Manual o automática**

| | Usa los parámetros de… |
|---|---|
| Botón **Generar nota** | Lo que está en pantalla, aunque no esté guardado |
| Generación automática (11:00) | La config guardada con **Guardar cambios** en Crear nota, y el tono de Programación |

La automática no hace nada si no hay categorías guardadas.

## Revisión y publicación

```
borrador ──Aprobar──► aprobada ──Publicar en HubSpot──► publicado
   │                     │                                  │
   └──Rechazar──► rechazada   Borrador en HubSpot        Despublicar → aprobada
```

Todo desde **Historial** (`historial.py`). Una nota sin aprobar no se puede enviar a HubSpot.

- **Rechazar pide un motivo** (mínimo 3 caracteres): queda en `motivo_rechazo` y alimenta las correcciones de las notas siguientes (paso 3).
- **Vista previa** muestra la nota como va a salir en el blog: título, meta description, etiquetas, slug, cuerpo e imagen destacada, que se puede cambiar ahí mismo.

Detalle en [hubspot-integration.md](hubspot-integration.md).

El generador viejo (Fase 1, `generar_articulo.py`) se borró. Sus notas viejas (`articulos_generados`) siguen apareciendo en el Historial.
