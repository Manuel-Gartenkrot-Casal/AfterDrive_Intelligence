# Las Corridas se encolan en Mongo en lugar de rechazarse

Reemplaza en parte a [ADR-0001](0001-corridas-serializadas-en-un-proceso.md): se mantiene que corre **una sola Corrida a la vez** en un único proceso, pero la que llega mientras otra corre ya no se rechaza, **se encola**.

Con el rechazo, el scheduler perdía la Corrida programada si a esa hora había otra en curso (solo quedaba un print en el log), y el usuario tenía que reintentar a mano. Además, los endpoints con streaming (SSE) ocupaban uno de los 4 threads de gunicorn durante toda la Corrida.

## Decisión

- `afterdrive/cola.py` guarda la Cola en la colección `corridas` de Mongo: estado `pendiente → en_curso → ok | error | cancelada | interrumpida`, con su log (últimas 500 líneas).
- Un único thread consumidor (lo arranca `scheduler.iniciar()`) toma la pendiente más vieja con `find_one_and_update` y la corre con el lock de `corridas.py`, **esperando** su turno si una Corrida vieja (endpoints síncronos como "Probar y agregar") lo tiene.
- Orden de llegada (FIFO), sin prioridades. Una Corrida idéntica a una pendiente no se duplica: se devuelve la existente. Tope de 5 pendientes (429).
- El dashboard encola (`POST /api/corridas/...`, 202) y lee el log por **polling** (`GET /api/corridas/<id>/log?desde=N`), sin tener una request abierta.
- Al arrancar, las que estaban `en_curso` quedan `interrumpida` y no se reintentan; las `pendiente` se retoman.
- Cancelar: una pendiente no corre nunca; un script en curso se mata; el scraping se corta entre fuente y fuente; la generación in-process no se puede cortar a mitad (409).

## Consequences

Sigue dependiendo de `gunicorn --workers 1`: el claim en Mongo es atómico, pero el lock de `corridas.py` es por proceso. Subir workers exige mover ese lock a Mongo.

La Cola sobrevive redeploys y reinicios, a costa de una colección más en Mongo. Las terminadas quedan como historial; no hay limpieza automática todavía.
