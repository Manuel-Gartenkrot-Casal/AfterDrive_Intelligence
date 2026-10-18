Actuá como arquitecto de software senior. Tu tarea es **planear, no implementar**: producí un plan de implementación para 5 cambios sobre AfterDrive Intelligence. No modifiques código ni hagas commits; el único entregable es el plan.

## Contexto del proyecto

Pipeline que junta noticias de autopartes/aftermarket y las convierte en notas de blog B2B. Stack: Python/Flask (`afterdrive/flask_api.py`, 830 líneas), MongoDB Atlas, dashboard en un único `express/src/public/index.html` (3463 líneas, HTML+CSS+JS inline, estilo neumórfico), deploy en Render plan free con gunicorn `--workers 1`.

Antes de planear, leé estos archivos (no asumas su contenido):
- `CONTEXT.md`: vocabulario del dominio. Usá esos términos exactos (Corrida, Fuente confiable, Proveedor, Nota, Saneo, Modo degradado) y evitá los marcados como _Avoid_.
- `docs/adr/0001-corridas-serializadas-en-un-proceso.md`: hoy las Corridas se serializan con un lock en memoria y **rechazan sin encolar**. La cola de procesos contradice esta decisión: tratalo explícitamente (ver cambio 4).
- `afterdrive/corridas.py`, `afterdrive/config_store.py`, `afterdrive/scheduler.py`.
- `render.yaml`, `Dockerfile`.
- `express/src/public/index.html`: estructura del header (~línea 1373), sección de fuentes (~1711) y `deleteTrustedUrl` (~2151), autoguardado de agenda (`guardarAgenda`, ~2391) y de fase 2 (`fase2GuardarConfig`, ~3057), y el sistema de sombras (`--raised`, `--inset`, `--sh-dark`, `--sh-light`, ~100 usos de `box-shadow`).
- `tests/` (especialmente `test_corridas.py` y `test_config_api.py`) para respetar el patrón de seams y fakes.

## Los 5 cambios

### 1. Barra lateral o header bien sectorizado
El dashboard es una sola página larga con modos `cliente`/`dev`. Proponé una navegación que separe por zonas (por ejemplo: Panel/Estado, Fuentes, Generación de Notas, Configuración, Corridas/Cola, Costos). Compará sidebar vs. header con pestañas considerando: mobile, los dos modos `data-modo`, accesibilidad (landmarks, foco, teclado) y el hecho de que todo vive en un solo HTML. Recomendá una y justificá. Indicá qué secciones se mueven, cómo se conserva el estado al navegar y si conviene (o no) partir el `index.html`.

### 2. Guardar cambios con un botón aparte
Hoy la configuración se autoguarda en cada `change`. Planeá el paso a **edición explícita**: estado "sucio" por formulario, botón Guardar y Descartar, aviso de cambios sin guardar al navegar o cerrar, deshabilitado cuando no hay cambios, feedback de éxito/error. Cubrí agenda de scraping/generación, config de Fase 2 (categorías, regiones, clientes) y selector de Proveedor. Definí qué pasa con acciones que hoy son inmediatas por naturaleza (alta/baja de fuentes, toggles activo/inactivo): ¿siguen siendo inmediatas o entran al lote? Verificá el contrato de los endpoints `POST /api/*-config` y proponé si hace falta validación o versionado para evitar pisar cambios.

### 3. Confirmar antes de borrar fuentes
`deleteTrustedUrl` borra de inmediato. Planeá un diálogo de confirmación accesible (modal con foco atrapado, Esc, texto que nombre la fuente y diga qué se pierde). Evaluá si borrar debería ser **desactivar** por defecto, y qué pasa con los Artículos ya ingeridos de esa fuente. Aplicá la misma solución reutilizable al resto de borrados (`/api/suggested-urls` DELETE, `/api/fase2/clientes/<slug>` DELETE, notas), sin hacer un diálogo distinto por cada uno.

### 4. Cola de procesos
Hoy una Corrida que llega con otra en curso se rechaza (ADR-0001). Planeá una **cola visible** de Corridas. Tenés que resolver explícitamente:
- Dónde vive la cola, dado `--workers 1` y el plan free de Render (RAM limitada, el servicio se duerme: ¿qué pasa con la cola si el proceso se reinicia?). Compará en memoria vs. persistida en Mongo.
- Semántica: orden, prioridad (cron vs. botón manual), deduplicación, cancelación, timeout (hoy 30 min), qué ocurre con los endpoints SSE (`/stream/...`) que hoy esperan una respuesta HTTP larga.
- Qué UI la muestra (estado, posición, log, cancelar) y cómo se actualiza (polling vs. SSE).
- Cómo cambia `corridas.py`, y si hace falta **escribir un ADR nuevo que reemplace o enmiende el 0001** (casi seguro que sí).

### 5. Abusar menos del shadow (cambiar el estilo)
El estilo neumórfico usa ~100 `box-shadow`. Proponé un sistema visual nuevo, más plano, con jerarquía por borde, color de superficie y espaciado en lugar de sombras. Entregá: tokens de diseño propuestos (superficies, bordes, radios, elevación mínima), qué componentes cambian y cuáles conservan una sombra sutil (modal, dropdown), contraste AA en tema claro y oscuro, y una estrategia de migración por tokens (cambiar `--raised`/`--inset` centralmente antes de tocar componentes uno por uno). Si hace falta decidir entre estilos, mostrá 2 opciones con sus tradeoffs y recomendá una.

## Cómo quiero el plan

1. **Hallazgos del código**: qué encontraste que afecta el plan (con `archivo:línea`), incluyendo supuestos que resultaron falsos.
2. **Dependencias y orden**: grafo de qué va antes de qué. Mi hipótesis, que tenés que confirmar o refutar: sectorización (1) y estilo (5) conviene hacerlos juntos o el estilo primero; guardar explícito (2), confirmar borrado (3) y cola (4) dependen de componentes de UI compartidos (botón, modal, panel de estado) que conviene construir una sola vez.
3. **Plan por cambio**: objetivo, alcance, archivos a tocar, pasos ordenados, riesgos, estrategia de tests (qué se prueba automáticamente y qué no), criterio de "terminado" verificable, tamaño estimado (S/M/L).
4. **Decisiones abiertas**: lo que solo yo puedo decidir. Para cada una, tus opciones y tu recomendación. No frenes el plan por ellas: asumí tu recomendación y marcá qué cambiaría si respondo distinto.
5. **Riesgos transversales**: regresiones en el HTML monolítico y límites del plan free de Render.
6. **Propuesta de entregas**: cortá el trabajo en PRs chicos e independientes, cada uno desplegable y reversible, en orden recomendado.

## Restricciones

- Respetá las convenciones del repo: el vocabulario de `CONTEXT.md`, el patrón de seams para tests, comentarios y mensajes en español.
- No agregues dependencias ni frameworks (React, etc.) sin justificarlo contra el costo de migrar un HTML monolítico; la preferencia por defecto es no agregarlos.
- No propongas nada que exija más de un worker de gunicorn sin plantearlo como decisión abierta.
- Distinguí lo que verificaste leyendo el código de lo que suponés. Si algo no se puede confirmar sin ejecutar, decilo.
- Sé concreto: nada de "mejorar la UX" o "agregar tests" sin decir cuáles ni dónde. Preferí un plan más corto y accionable a uno exhaustivo y genérico.
