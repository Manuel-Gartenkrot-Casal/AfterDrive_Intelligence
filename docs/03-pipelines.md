# 03 · Pipelines: qué pasa paso a paso

Hay tres flujos: **juntar noticias** (scraping), **escribir notas** (generación) y **revisar y publicar**. El resto los alimenta.

## Scraping de fuentes (todos los días, 05:30)

Archivos: `corridas.py` (`_scrapear_fuentes`), `ingesta/scraper.py`, `ingesta/ingesta.py`.

```
trusted_urls con estado "activo"
      │  por cada fuente
      ▼
scraper.py   baja el listado → si es un RSS, Atom o sitemap (o la portada anuncia su
      │      feed), las notas salen de ahí con su fecha (ingesta/feeds.py); si no,
      │      detecta links de artículos en el HTML (prioriza URLs con fecha)
      │      saltea los links ya guardados o descartados antes
      │      baja cada artículo nuevo → trafilatura extrae título, cuerpo y fecha,
      │      y se guardan hasta 8 fotos de la página (imagen_articulo.extraer_todas)
      │      si el sitio bloquea o está caído → copia de Wayback Machine
      ▼
ingesta.py   el LLM decide si es del rubro
      ├── no ──► articulos_descartados  (con título, cuerpo y motivo)
      └── sí ──► ficha ──► embedding ──► articulos  (upsert por url)
```

- **Ficha** (`lm_studio.fichar_articulo`): el modelo de clasificación (el barato) resume cada artículo aprobado en español: resumen, hechos, cifras, empresas y fecha. La generación usa la ficha en lugar del cuerpo crudo. Una llamada por artículo aprobado; `FICHAS_NOTICIAS=0` la apaga. Los artículos viejos sin ficha la reciben la primera vez que se eligen para una nota.

- Máximo de artículos por fuente: `max_articulos` (10 por defecto, se cambia en Programación).
- **No se vuelve a procesar lo ya visto**: antes de descargar se consultan `articulos` y `articulos_descartados` (`corridas.ya_procesadas`). El contador de "nuevos" es real.
- Se descartan cuerpos de 100 caracteres o menos.
- **Dónde se pierde lo scrapeado**: cada fuente cierra con una línea "Links que no dieron artículo" con un conteo por motivo (`sin_html`: no se pudo bajar; `sin_texto`: la página no es una nota; `sin_titulo`; `cuerpo_corto`; `error`; `sin_probar`: quedaron fuera de los `max_articulos × 3` candidatos). Al final de la corrida, `[RESUMEN]` suma eso más lo que la IA rechazó (`rechazado_ia`) o dejó pendiente (`pendiente_ia`). Antes los errores de extracción se tragaban sin aviso.
- **Criterio del filtro** (`lm_studio._SYSTEM_EVALUAR`): aprueba toda noticia útil para el negocio de distribuidoras, fabricantes, talleres y lubricentros (repuestos, mercado de reposición, industria automotriz y autopartista, parque automotor, neumáticos, lubricantes, logística, ferias) y rechaza solo lo claramente ajeno (otros temas, reviews de autos nuevos para consumidores, seguros, contenido vacío). Antes aprobaba "solo si" el artículo trataba de piezas, catálogos o fitment, y rechazaba casi todas las noticias del sector.
- **Pendientes**: si el LLM no responde (caído o con límite de uso) o responde algo que no se entiende dos veces seguidas, el artículo no se guarda ni se descarta, así la próxima corrida lo vuelve a clasificar. Antes se aprobaba y entraba contenido fuera de tema; y una respuesta rota contaba como rechazo para siempre. La disponibilidad del proveedor se vuelve a chequear al minuto.
- **Reclasificar descartados** (`python -m afterdrive.ingesta.reclasificar --dias 30`): vuelve a juzgar con el criterio actual los descartados de los últimos días. Los que ahora aprueba pasan a `articulos`. Sirve después de cambiar el filtro; cuesta una llamada por artículo.
- Cómo baja cada página depende de la RAM (`ingesta/resource_detector.py`). Con menos de 600 MB (Render free) nunca usa Chromium: `requests` y, si falla, Wayback. En GitHub Actions (~7 GB) usa Chromium. Se fuerza con `FORCE_PROFILE=alto|medio|bajo`.
- Los dominios que no respondieron van directo a Wayback **solo durante esa corrida**.
- Las fuentes **pausadas** (`estado: "inactivo"`) no se scrapean.

## Alta de una fuente

| Botón | Qué hace |
|---|---|
| **Recomendadas para Alephee** (`ingesta/fuentes_recomendadas.py`) | Marketplaces, e-commerce automotor y material propio de Alephee: `python -m afterdrive.ingesta.fuentes_recomendadas` las suma a Recomendadas para revisarlas y agregarlas |
| **Probar y agregar** (`ingesta/add_url.py`, por la cola) | Scrapea la URL y la clasifica. **Solo si aprueba al menos un artículo**, queda como fuente activa |
| **Agregar** (`POST /api/trusted-urls`) | La agrega directo, sin probarla |
| **Buscar recomendaciones** (`ingesta/discover_sources.py`, por la cola) | Busca sitios del rubro en Google Noticias, DuckDuckGo, DuckDuckGo Lite y Bing (si uno bloquea la búsqueda desde el servidor, pasa al siguiente) y además le pide a la IA medios del sector. **Todos se verifican entrando a la portada**: tiene que tener notas enlazadas y al menos el 25% de sus titulares (y 3 como mínimo) tiene que ser del sector. Así no entran diarios generales con una sola nota de repuestos, cuyos artículos después rechazaba casi todos la ingesta. Si la portada es general, prueba sus secciones del rubro (`/autos/`, `/motor/`...) y sugiere la que pase. Si no puede buscar por ningún camino, la corrida termina con error y el motivo |

## Ejemplos del blog AfterDrive

`generacion/scraper_afterdrive.py` baja notas **reales** del blog de AfterDrive por categoría (16 categorías) y las guarda en `afterdrive_ejemplos` con las regiones detectadas por palabras clave. Son la **referencia de estilo** del generador. Se corre a mano: **Sincronizar Ejemplos**.

## Generación de notas Fase 2 (todos los días, 11:00)

Archivo: `generacion/generar_nota_fase2.py`. Es el **generador principal**.

**Entrada**

| Parámetro | Qué define |
|---|---|
| Categorías (obligatorio) | De qué trata la nota |
| Regiones | El mercado del que habla la nota. **No cambian el idioma**: todas se escriben en portugués de Brasil (`IDIOMA_PRINCIPAL`, por defecto `pt`) y se traducen al español y al inglés al crearlas |
| Clientes | Empresas que se mencionan como casos reales |
| Puntapié | Una URL a la que la nota tiene que llevar al lector |
| Largo aproximado | Corto (500–700 palabras), medio (700–1000, por defecto) o largo (1000–1400), con las secciones fijas incluidas. Se elige en Crear nota y queda guardado para la automática |
| Persona | Estilo de redacción (ver [04 IA](04-ia.md)) |
| Tema | Opcional, para acotar |

**Pasos**

1. **Noticias de contexto** (`contexto_noticias.py`): entre las 200 noticias más recientes (y, con Atlas Vector Search, las 100 más parecidas de toda la base) elige 5, combinando parecido con el pedido (65 %), recencia por **fecha de publicación** (25 %) y que no se hayan usado (10 %). Las que ya alimentaron una nota en los **últimos 30 días** quedan para el final: solo entran si no alcanzan las demás. Las que solo alimentaron notas **rechazadas** vuelven a contar como no usadas (`urls_liberadas`, mira las últimas 300 notas); si la nota vuelve a borrador, dejan de estar libres. Al prompt va la **ficha** de cada una más un extracto. **Son la única fuente permitida de cifras, empresas y casos.**
2. **Referencias de estilo**: hasta 2 notas reales por categoría. Se suman hasta 2 **notas propias que el equipo calificó con 4 o 5 estrellas**.
   **Notas de AfterDrive para citar** (`generacion/notas_blog.py`): las 4 notas del blog más parecidas al tema (embeddings, con un plus si comparten categoría), en el idioma de la nota: las del blog scrapeado (solo español) y las propias ya publicadas en HubSpot. El plan puede asignar una a una sección y la redacción la cita como análisis propio ("como analizamos en AfterDrive by Alephee, [texto](url)") **solo si encaja**, con lo que dice su resumen y como mucho dos. Lo que dicen esos resúmenes cuenta como respaldo de datos. Las citadas quedan en `notas_blog_citadas`.
3. **Calibración** (`calibracion.py`, ver abajo): correcciones del equipo (rechazos, calificaciones bajas, etiquetas que se repiten, ediciones), aciertos y el umbral del evaluador.
4. **Plan** (`generacion/plan.py`): el modelo barato (con la API paga, el de evaluación; 4000 tokens) propone ángulo, título (máx. 60 caracteres), palabra clave, secciones con qué noticia alimenta cada una e implicancias. Recibe los títulos de las últimas 15 notas para **no repetir su ángulo**. Si el plan falla, la nota se escribe sin plan. **Memoria**: recibe los títulos de las últimas 15 notas, los ángulos y palabras clave de las últimas 50 (para elegir otros) y las aprobadas o publicadas como temas que el blog ya trató.
5. **Prompt**: `ia/redaccion.py` arma el system prompt (persona + voz de la región + **secciones fijas**: "Qué significa para tu negocio" con 3 a 5 acciones concretas y "Preguntas frecuentes" con 3 preguntas + reglas de SEO + citas con link a la noticia + CTA con link a Alephee). El pedido lleva noticias, referencias, correcciones, aciertos y el plan.
6. **Redacción** con el LLM y **saneo** (`ia/saneo.py`): limpia la respuesta y **la descarta si el modelo escribió su razonamiento en vez de la nota**. Lo descartado queda en `notas_descartadas` con el motivo.
7. **Revisión de la versión**:
   - **Enlaces**: se quitan los links a URLs que no salen de las noticias, del blog o de alephee.com (el texto queda).
   - **Empresas que no se nombran** (`clientes.py`): sin IA, se busca en el texto (sin tildes ni mayúsculas, palabra entera, también por alias) cada empresa marcada `no_mencionar`. Si aparece, es un problema grave: la nota se corrige, y si igual queda, se guarda en `empresas_prohibidas` y la aprobación automática la frena. Antes de escribir ya se avisaron en el prompt y se dejaron afuera las noticias que las tienen en el título.
   - **Datos contra las noticias** (`generacion/verificacion.py`): cifras y nombres en negrita se buscan literal en las noticias, sus fichas, los clientes y el tema; lo que no aparece se le pregunta al modelo de evaluación (una llamada). Si el modelo no responde, una cifra no encontrada cuenta como sin respaldo.
   - **Estilo y SEO sin IA** (`generacion/calidad.py`): título, meta description, secciones fijas, huecos tipo "un X%", muletillas de IA, anglicismos, términos de la casa, párrafos largos, palabra clave.
   - **Evaluación** con el LLM (checklist de 9 puntos).
   - **Repetición**: si el vector de la nota se parece a una de las últimas 50 más que `NOTA_PARECIDO_MAX` (0.85), es una repetida.
8. **Corrección**: si hay un problema grave (datos sin respaldo, un punto crítico de la evaluación, falta título, meta o la sección de implicancias, huecos, tres o más muletillas, o menos lineamientos que el umbral calibrado), el **modelo de corrección** (`generacion/correccion.py`; con la API paga, el de evaluación, unas 12 veces más barato que el de redacción) recibe la nota y la lista de problemas y devuelve la misma nota con solo eso arreglado. Solo una nota **repetida** se redacta de cero, porque el problema es el ángulo. La corrección se revisa igual que la primera versión y queda la mejor de las dos (`calidad.segundo_intento` dice cuál de los dos caminos se usó).
9. **Imágenes** (`generacion/imagen_destacada.py`): **5 por nota**, la destacada y 4 dentro del texto. El scraper guarda hasta 8 fotos por noticia (`imagenes`, la principal primero: og:image, twitter:image, JSON-LD o la primera del cuerpo, y después las otras `<img>` de la nota; sin logos ni íconos, solo https). Las fotos usadas en notas de los últimos 30 días no se repiten, así que si no se juntan 5 aptas busca **solo las que faltan**, en este orden: (1) las otras fotos de las páginas de sus noticias (a las scrapeadas antes de la lista se les relee la página); (2) otras noticias del mismo tema; (3) **bancos de imágenes** (`generacion/imagenes_respaldo.py`), una búsqueda por ronda y hasta 8, armadas por la IA en inglés a partir del título (si falla, búsquedas genéricas del sector): **Pexels** si está `PEXELS_API_KEY` y **Pixabay** si está `PIXABAY_API_KEY` (los dos sin atribución, así que sirven de portada; Pixabay no deja enlazar sus fotos para siempre, así que las elegidas se descargan a la base al generar la nota, como una imagen subida, y de ahí se copian a HubSpot) y **Wikimedia Commons** siempre, solo con licencias de uso comercial (dominio público, CC0, CC BY, CC BY-SA). El modelo de clasificación juzga las fotos contra el **tema concreto** de la nota (una foto genérica del sector no alcanza): **con la API paga las mira**; sin ella juzga sin verlas, por la noticia de la que salen, su texto alternativo y el nombre del archivo. La portada nunca tiene personas ni una foto que pida crédito (CC BY): esas van dentro del texto, con el crédito debajo. Si la IA falla, van las primeras. La destacada va en `imagen` y las otras en `imagenes_cuerpo`; al subir a HubSpot se copian a sus archivos y las del cuerpo se reparten entre las secciones en las 3 versiones.
10. **Traducciones** (`traducciones.py`): apenas se crea, la nota se traduce al español y al inglés (tarea `traduccion`) y se guardan en `traducciones.<idioma>`. Una que falla no frena la nota: queda el error y se reintenta desde el historial.
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
- Al lado de la nota se ve lo que se revisó al generarla: datos sin respaldo, estilo, SEO, imagen, citas a AfterDrive, otros idiomas y el plan.
- **Idiomas**: la nota abre con pestañas Português (principal), Español y English. Cada versión se lee y se **edita por separado**; si se edita el texto principal, las traducciones se marcan como desactualizadas (con **Volver a traducir**, que corre en la Cola). Al subir la nota a HubSpot se encola la subida de cada versión como **borrador vinculado** al post original. Ver [hubspot-integration.md](hubspot-integration.md#otros-idiomas).

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
