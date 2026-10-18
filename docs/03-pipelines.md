# 03 · Pipelines: qué pasa paso a paso

Hay dos flujos que importan: **juntar noticias** (scraping) y **escribir notas** (generación). El resto los alimenta.

## Scraping de fuentes (todos los días, 05:30)

Archivos: `corridas.py` (`_scrapear_fuentes`), `ingesta/scraper.py`, `ingesta/ingesta.py`.

```
trusted_urls con estado "activo"
      │  por cada fuente
      ▼
scraper.py   baja el listado → detecta links de artículos (prioriza URLs con fecha)
      │      baja cada artículo → trafilatura extrae título, cuerpo y fecha
      │      si el sitio bloquea o está caído → copia de Wayback Machine
      ▼
ingesta.py   el LLM decide si es del rubro
      ├── no ──► articulos_descartados
      └── sí ──► embedding ──► articulos  (upsert por url)
```

- Máximo de artículos por fuente: `max_articulos` (10 por defecto, se cambia en Programación).
- Se descartan cuerpos de menos de 100 caracteres.
- **Modo degradado**: si el LLM no responde, el artículo se aprueba igual para no perderlo.
- Cómo baja cada página depende de la RAM (`ingesta/resource_detector.py`). Con menos de 600 MB (Render free) nunca usa Chromium: `requests` y, si falla, Wayback. Se fuerza con `FORCE_PROFILE=alto|medio|bajo`.
- Las fuentes **pausadas** (`estado: "inactivo"`) no se scrapean.

## Alta de una fuente

| Botón | Qué hace |
|---|---|
| **Probar y agregar** (`ingesta/add_url.py`) | Scrapea la URL y la clasifica. **Solo si aprueba al menos un artículo**, queda como fuente activa |
| **Agregar** (`POST /api/trusted-urls`) | La agrega directo, sin probarla |
| **Buscar recomendaciones** (`ingesta/discover_sources.py`) | Busca sitios del rubro en DuckDuckGo por palabras clave (sin IA) y los deja como sugerencias |

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

1. **Noticias de contexto** (`contexto_noticias.py`): de las 200 noticias más recientes elige 5, combinando parecido con el pedido (65 %), recencia (25 %) y que no se hayan usado (10 %). **Son la única fuente permitida de cifras, empresas y casos.**
2. **Referencias de estilo**: hasta 2 notas reales por categoría.
3. **Prompt**: `ia/redaccion.py` arma el system prompt (persona + voz de la región).
4. **Redacción** con el LLM.
5. **Saneo** (`ia/saneo.py`): limpia la respuesta y **la descarta si el modelo escribió su razonamiento en vez de la nota**.
6. **Evaluación**: el LLM revisa la nota contra un checklist de 9 puntos; el resultado se guarda con la nota.
7. Se guarda en `notas_fase2` con su embedding, y las noticias usadas quedan marcadas.

**Manual o automática**

| | Usa los parámetros de… |
|---|---|
| Botón **Generar nota** | Lo que está en pantalla, aunque no esté guardado |
| Generación automática (11:00) | La config guardada con **Guardar cambios** en Crear nota, y el tono de Programación |

La automática no hace nada si no hay categorías guardadas.

## Generador Fase 1 (viejo)

`generacion/generar_articulo.py`. Elige un tema por embeddings y redacta. Ya no aparece en el dashboard; queda por API (`/generar`) y línea de comandos. Tiene un error conocido de origen de datos: ver [09 Deuda](09-deuda-y-mejoras.md).
