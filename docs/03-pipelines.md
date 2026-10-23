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
      └── sí ──► ficha ──► embedding ──► articulos  (upsert por url)
```

- **Ficha** (`lm_studio.fichar_articulo`): el modelo de clasificación (el barato) resume cada artículo aprobado en español: resumen, hechos, cifras, empresas y fecha. La generación usa la ficha en lugar del cuerpo crudo. Una llamada por artículo aprobado; `FICHAS_NOTICIAS=0` la apaga. Los artículos viejos sin ficha la reciben la primera vez que se eligen para una nota.

- Máximo de artículos por fuente: `max_articulos` (10 por defecto, se cambia en Programación).
- **No se vuelve a procesar lo ya visto**: antes de descargar se consultan `articulos` y `articulos_descartados` (`corridas.ya_procesadas`). El contador de "nuevos" es real.
- Se descartan cuerpos de menos de 100 caracteres.
- **Pendientes**: si el LLM no responde (caído o con límite de uso), el artículo no se guarda ni se descarta, así la próxima corrida lo vuelve a clasificar. Antes se aprobaba y entraba contenido fuera de tema. La disponibilidad del proveedor se vuelve a chequear al minuto.
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
| Puntapié | Una URL a la que la nota tiene que llevar al lector |
| Largo aproximado | Corto (500–700 palabras), medio (700–1000, por defecto) o largo (1000–1400), con las secciones fijas incluidas. Se elige en Crear nota y queda guardado para la automática |
| Persona | Estilo de redacción (ver [04 IA](04-ia.md)) |
| Tema | Opcional, para acotar |

**Pasos**

1. **Noticias de contexto** (`contexto_noticias.py`): entre las 200 noticias más recientes (y, con Atlas Vector Search, las 100 más parecidas de toda la base) elige 5, combinando parecido con el pedido (65 %), recencia por **fecha de publicación** (25 %) y que no se hayan usado (10 %). Las que ya alimentaron una nota en los **últimos 30 días** quedan para el final: solo entran si no alcanzan las demás. Al prompt va la **ficha** de cada una más un extracto. **Son la única fuente permitida de cifras, empresas y casos.**
2. **Referencias de estilo**: hasta 2 notas reales por categoría, que además son los **enlaces internos** sugeridos. Se suman hasta 2 **notas propias que el equipo calificó con 4 o 5 estrellas**.
3. **Calibración** (`calibracion.py`, ver abajo): correcciones del equipo (rechazos, calificaciones bajas, etiquetas que se repiten, ediciones), aciertos y el umbral del evaluador.
4. **Plan** (`generacion/plan.py`): el modelo barato (con la API paga, el de evaluación; 4000 tokens) propone ángulo, título (máx. 60 caracteres), palabra clave, secciones con qué noticia alimenta cada una e implicancias. Recibe los títulos de las últimas 15 notas para **no repetir su ángulo**. Si el plan falla, la nota se escribe sin plan.
5. **Prompt**: `ia/redaccion.py` arma el system prompt (persona + voz de la región + **secciones fijas**: "Qué significa para tu negocio" con 3 a 5 acciones concretas y "Preguntas frecuentes" con 3 preguntas + reglas de SEO + citas con link a la noticia + CTA con link a Alephee). El pedido lleva noticias, referencias, correcciones, aciertos y el plan.
6. **Redacción** con el LLM y **saneo** (`ia/saneo.py`): limpia la respuesta y **la descarta si el modelo escribió su razonamiento en vez de la nota**. Lo descartado queda en `notas_descartadas` con el motivo.
7. **Revisión de la versión**:
   - **Enlaces**: se quitan los links a URLs que no salen de las noticias, del blog o de alephee.com (el texto queda).
   - **Datos contra las noticias** (`generacion/verificacion.py`): cifras y nombres en negrita se buscan literal en las noticias, sus fichas, los clientes y el tema; lo que no aparece se le pregunta al modelo de evaluación (una llamada). Si el modelo no responde, una cifra no encontrada cuenta como sin respaldo.
   - **Estilo y SEO sin IA** (`generacion/calidad.py`): título, meta description, secciones fijas, huecos tipo "un X%", muletillas de IA, anglicismos, términos de la casa, párrafos largos, palabra clave.
   - **Evaluación** con el LLM (checklist de 9 puntos).
   - **Repetición**: si el vector de la nota se parece a una de las últimas 15 más que `NOTA_PARECIDO_MAX` (0.93), es una repetida.
8. **Corrección**: si hay un problema grave (datos sin respaldo, un punto crítico de la evaluación, falta título, meta o la sección de implicancias, huecos, tres o más muletillas, o menos lineamientos que el umbral calibrado), el **modelo de corrección** (`generacion/correccion.py`; con la API paga, el de evaluación, unas 12 veces más barato que el de redacción) recibe la nota y la lista de problemas y devuelve la misma nota con solo eso arreglado. Solo una nota **repetida** se redacta de cero, porque el problema es el ángulo. La corrección se revisa igual que la primera versión y queda la mejor de las dos (`calidad.segundo_intento` dice cuál de los dos caminos se usó).
9. **Imagen destacada**: la foto de una de las noticias usadas (primero las que respaldan la nota), que el scraper guardó con el artículo (`ingesta/imagen_articulo.py`: og:image, twitter:image, JSON-LD o la primera foto del cuerpo; sin logos ni íconos, solo https). A los artículos guardados antes de esto se les busca una vez, hasta 3 por nota. Sin ninguna foto, la nota se guarda sin imagen. Las fotos de las demás noticias quedan en `fuentes` para elegir otra desde la vista previa; al enviar a HubSpot la elegida se copia a sus archivos.
10. Se agrega la sección **Fuentes** (antes de la meta description) con las noticias citadas en el texto, las que respaldaron algún dato y las que el plan asignó a una sección.
11. Se guarda en `notas_fase2` como **borrador**, con **lo que costó** (`costo`: total, por tarea y cantidad de llamadas a la API paga; se ve al abrir la nota), su evaluación, `calidad`, `verificacion`, `estilo`, `seo`, `plan`, `parecida_a` y `calibracion_usada`, y las noticias usadas quedan marcadas con la fecha.

**Manual o automática**

| | Usa los parámetros de… |
|---|---|
| Botón **Generar nota** | Lo que está en pantalla, aunque no esté guardado |
| Generación automática (11:00) | La config guardada con **Guardar cambios** en Crear nota, y el tono de Programación |

La automática no hace nada si no hay categorías guardadas.

## Revisión y publicación

```
borrador ──Aprobar y subir──► aprobada + borrador en HubSpot ──Publicar en HubSpot──► publicado
   │                                                                                     │
   └──Rechazar──► rechazada                                                  Despublicar → aprobada
```

Todo desde **Historial** (`historial.py`). Una nota sin aprobar no se puede enviar a HubSpot.

- **Rechazar pide un motivo** (mínimo 3 caracteres): queda en `motivo_rechazo` y alimenta las correcciones de las notas siguientes (paso 3).
- **Calificar**: al abrir una nota, 1 a 5 estrellas, etiquetas (datos dudosos, genérica, suena a IA, muy larga, tono, poco útil, errores técnicos; y las positivas) y un comentario.
- **Editar** guarda, la primera vez, la versión que escribió el modelo (`contenido_original`).
- Al lado de la nota se ve lo que se revisó al generarla: datos sin respaldo, estilo, SEO y el plan.

## Calibración: cómo aprende la generación

Archivo: `calibracion.py`. Se lee de Mongo en cada nota; el estado se ve en **Historial → Cómo aprende la generación**.

| Señal | Qué cambia en la próxima nota |
|---|---|
| Una etiqueta negativa en 2 o más de las últimas 20 notas calificadas (90 días) | Activa su regla fija en el prompt (por ejemplo "Suena a IA" → sin muletillas, oraciones concretas) |
| Comentario de una nota con 1 o 2 estrellas | Entra como corrección a respetar |
| Comentario de una nota con 4 o 5 estrellas | Entra como "lo que el equipo valoró" |
| Nota con 4 o 5 estrellas | Pasa a ser referencia de estilo (primero las de la misma persona) |
| Motivo de rechazo | Corrección (como antes) |
| Edición de una nota | En la próxima generación, el modelo de evaluación resume la diferencia entre lo generado y lo editado en hasta 2 reglas generales; quedan guardadas en la nota (`leccion_edicion`) |
| 8 o más notas calificadas con evaluación automática | Se calcula el puntaje automático mínimo (0 a 9) que mejor separa lo que el equipo califica con 3 o más; una nota por debajo se reescribe |

Como mucho 8 correcciones por nota. El panel muestra además el promedio por persona y por proveedor, para decidir con datos (eso no cambia nada solo).
- **Vista previa** muestra la nota como va a salir en el blog: título, meta description, etiquetas, slug, cuerpo e imagen destacada, que se puede cambiar ahí mismo.

Detalle en [hubspot-integration.md](hubspot-integration.md).

El generador viejo (Fase 1, `generar_articulo.py`) se borró. Sus notas viejas (`articulos_generados`) siguen apareciendo en el Historial.
