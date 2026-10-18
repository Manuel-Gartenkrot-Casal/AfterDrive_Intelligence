# Las Corridas programadas pueden correr en GitHub Actions

En el plan free de Render (512 MB, 0,1 CPU, se duerme sin tráfico) el scraping no puede usar Chromium, es lento y la tarea programada no corre si la instancia está dormida. Los runners de GitHub Actions tienen ~7 GB de RAM, Chromium y un cron que no depende de Render, y son gratis en repos públicos.

## Decisión

- `.github/workflows/corridas.yml` corre cada hora y `afterdrive/ejecutor_externo.py` ejecuta lo que tocaba según **la misma programación del dashboard** (colección `config`), recordando hasta dónde revisó (`config.ejecutor_externo`). Los horarios se siguen cambiando desde Programación.
- Es opcional: se activa con la variable de repo `CORRIDAS_EN_GITHUB=true`, y en Render se pone `CORRIDAS_EXTERNAS=github` para que el servidor deje de programarlas.
- Las Corridas del runner se registran en la colección `corridas` con `ejecutor: "github"`. El dashboard las ve con su log (se vuelca a Mongo cada 5 s) y las puede cancelar (`cancelar_pedido`, que el runner lee al volcar).
- Un reinicio de Render no marca como interrumpidas las de GitHub; solo las que llevan más de 3 horas en curso.

## Consequences

Los botones del dashboard siguen corriendo en Render, con el lock de un proceso (ADR-0002). Una Corrida de GitHub y otra de Render pueden correr a la vez: están en máquinas distintas, así que la RAM no es problema, pero dos scrapings simultáneos repetirían trabajo. Para coordinarlas habría que mover el lock a Mongo.

Las credenciales viven también como secretos del repositorio de GitHub.
