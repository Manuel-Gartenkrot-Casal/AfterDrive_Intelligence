# Plan: mejoras del dashboard (navegación, guardado, borrados, cola, estilo)

Fecha: 2026-10-16 · Rama: `Render_Testing` · Estado: propuesta, sin implementar.

## 1. Hallazgos del código

Lo verificado leyendo el código está marcado con `archivo:línea`. Lo que no pude confirmar sin ejecutar está marcado como **(sin verificar)**.

**Navegación**
- Ya hay dos navegaciones distintas. En modo cliente hay un carrusel "coverflow" con 4 secciones (`CARRUSEL`: Inicio, Crear nota, Programación, Fuentes) en `express/src/public/index.html:2486`. Mueve los nodos reales a diapositivas, marca como `inert` las inactivas y recuerda la sección en `localStorage('ad-seccion')` (`index.html:2677-2702`). En modo dev no hay navegación: stats, HUD, agenda, generador y consola van uno debajo del otro (`index.html:1411-1730`).
- El header tiene el switch de modo, el selector de Proveedor, el estado, el tema y el botón de salir, todo en una sola fila (`index.html:1373-1399`).
- Supuesto falso del prompt: el problema no es solo agregar navegación. Hay que **unificar** las dos que existen.

**Guardado**
- La agenda se autoguarda con un debounce de 450 ms en cada `change`, en el reloj, en AM/PM y en el switch (`guardarAgenda`, `index.html:2391-2472`).
- La config de Fase 2 se guarda en cada clic de chip de categoría, región o cliente y en el Puntapié (`index.html:3108, 3143, 3187, 3223, 3235`). Además, `fase2GuardarConfig` **traga los errores en silencio** (`index.html:3057-3072`): hoy un guardado fallido no se ve.
- Los `POST` de config aceptan actualizaciones parciales: un campo `None` no se toca (`afterdrive/flask_api.py:308-388`). Eso sirve tal cual para un guardado por lotes. `scraping-config` y `generacion-config` validan, pero **`/api/fase2/config` no valida nada** (`flask_api.py:377-388`).
- Hay un solo usuario administrador (`afterdrive/auth.py`), así que pisarse cambios entre personas no es un riesgo real.

**Borrados**
- `deleteTrustedUrl` borra sin confirmar, no mira `r.ok` y traga errores (`index.html:2151-2159`).
- El endpoint dice "Elimina o desactiva", pero **solo borra** (`flask_api.py:563-573`). **No existe ningún endpoint para pausar o activar una fuente**, aunque la UI muestra "activa/inactiva" (`index.html:2113`) y el scraping solo toma `estado: "activo"` (`afterdrive/corridas.py:89`).
- `fase2EliminarCliente` (`index.html:3218`) y `descartarSug` (`index.html:2952`) tienen el mismo patrón. `descartarSug` borra **todas** las sugerencias del dominio (`flask_api.py:500-514`) y el usuario no lo sabe.
- Supuesto falso del prompt: **no existe un borrado de Notas**. No hay que cubrirlo.
- Los Artículos se guardan por URL de artículo (`afterdrive/ingesta/ingesta.py:71`). No vi un campo que los ligue a su Fuente, así que borrar una Fuente no borra Artículos **(sin verificar a fondo en `scraper.py`)**.
- Ya existe un modal con `role="dialog"` y `aria-modal` (`index.html:1732`), pero es específico de "Última nota" y no vi un foco atrapado.

**Corridas**
- Hay un lock en memoria y se rechaza sin encolar (`corridas.py:41-60`). Los botones reciben 409 (`flask_api.py:390-405`), el SSE emite `[OCUPADO]` (`corridas.py:212`) y **el scheduler llama a `corridas.scraping`/`generacion` directo, así que si choca, la Corrida programada se pierde con solo un print en el log** (`afterdrive/scheduler.py:26-31`, `corridas.py:69-73`).
- `en_curso()` devuelve solo un nombre: no hay historial ni estado consultable.
- gunicorn corre con `--workers 1 --threads 4 --timeout 1800` (`Dockerfile`, CMD). **Cada SSE abierto ocupa uno de los 4 threads durante toda la Corrida.** Con dos pestañas mirando un stream y un poll, el dashboard se queda sin threads.
- Hay un keep-alive que evita que Render duerma la instancia (`flask_api.py:771`). Igual, un redeploy o un crash borra todo lo que esté en memoria.

**Estilo**
- La sombra está centralizada en tokens: `--raised`, `--raised-sm`, `--raised-xs`, `--inset`, `--inset-sm` (`index.html:89-95`). Hay **74 usos directos** de esos tokens y unos 6 hardcodeados (`index.html:570, 700, 847, 851, 953`).
- La causa de fondo: **todas las superficies son alias de `--bg`** (`--surface`, `--surface-panel`, `--surface-input`, etc., `index.html:98-103`). Sin diferencia de color entre fondo, card e input, la sombra es lo único que separa los elementos. Sacar sombras sin dar color a las superficies deja la UI plana e ilegible.

**Tests**
- Backend: `tests/test_corridas.py` cubre el lock, el rechazo, el corte del stream y la liberación al fallar. Es la base para testear la cola.
- Frontend: no hay tests de JS. Existe `scripts/manual/smoke_playwright.py` **(sin verificar qué cubre)**.

## 2. Dependencias y orden

```
PR1 Tokens planos ──┬──> PR3 Navegación ──> PR4 Guardar explícito
                    │                         ▲
PR2 Confirmar ──────┴─────────────────────────┘ (usa el mismo <dialog>)
PR5 Cola (backend + ADR-0002) ──> PR6 Panel de cola (necesita la sección de PR3)
PR7 Pulido de estilo por componente (al final)
```

Contra la hipótesis del prompt:
- **Confirmada:** el estilo va primero, pero solo la capa de tokens (PR1). Es barata, cambia todo de una y evita rediseñar la navegación sobre un estilo que se va.
- **Refutada en parte:** sectorización y estilo no van en el mismo PR. El HTML tiene 3463 líneas y mezclar los dos hace imposible revisar o revertir. Van en PRs consecutivos.
- **Confirmada:** el componente compartido real es uno solo, un `<dialog>` genérico. Lo usan el borrado (PR2) y el aviso de "cambios sin guardar" al cambiar de sección (PR4). La barra de guardado y el panel de cola no comparten código con él.
- **Nueva:** la cola (PR5) es casi toda backend e independiente. Puede avanzar en paralelo desde el día 1.

## 3. Plan por cambio

### Cambio 5 (parte A): estilo plano por tokens · PR1 · S/M

- **Objetivo:** pasar de neumorfismo a superficies planas con borde, sin tocar componentes.
- **Opciones:**
  - **A. Plano con bordes.** Fondo de la app más oscuro que las cards, borde de 1 px y sombra solo en lo flotante.
  - **B. Elevación suave.** Igual que A, pero las cards conservan una única sombra `0 1px 2px`.
  - **Recomiendo A**, con la sombra de B solo para modal, toast y dropdown. Es la que más se aleja del "abuso", y A no pierde jerarquía porque la dan el color de superficie y el espaciado.
- **Pasos:**
  1. En `index.html:30-103` reemplazar `--sh-dark` y `--sh-light` por tokens nuevos, en claro y oscuro: `--bg` (lienzo), `--surface` (card), `--surface-2` (input y pozo), `--border`, `--border-strong` y `--shadow-float`.
  2. Darles valores reales a los alias de `--surface-*`, que hoy son todos `--bg`.
  3. Redefinir los tokens viejos para que los 74 usos cambien solos: `--raised*` → `0 0 0 1px var(--border)`, `--inset*` → `inset 0 0 0 1px var(--border-strong)`. Así no se toca ninguna regla y el cambio se revierte en un commit.
  4. Revisar que los estados activos no dependan solo del inset. El comentario de `index.html:30-40` dice que también cambian de color: verificarlo en botones de modo, chips y tabs.
  5. Bajar los radios: contenedores de 22 a 12 px, controles de 14 a 8 px.
  6. Reemplazar el comentario "NEUMORPHISM" por el nuevo sistema.
- **Riesgos:** las cards que hoy usan `background: var(--bg)` en vez de `--surface` no cambiarían de color **(sin verificar cuántas)**. Hay que hacer un grep de `background: var(--bg)` en el paso 2.
- **Tests:** capturas con Playwright en claro y oscuro, en los dos modos, a 1280 y 390 px. Medir contraste: texto AA 4.5:1 y bordes de inputs 3:1 (WCAG 1.4.11).
- **Terminado cuando:** no queda ninguna sombra de doble luz, las capturas pasan revisión visual y los contrastes medidos cumplen.

### Cambio 3: confirmar antes de borrar · PR2 · M

- **Objetivo:** que ningún borrado sea accidental y que pausar sea la acción normal.
- **Pasos:**
  1. Crear `confirmar({titulo, mensaje, accion, peligro}) → Promise<boolean>` sobre un `<dialog>` nativo con `showModal()`. Trae gratis el foco dentro del diálogo, Esc y el fondo inerte. El foco inicial va en "Cancelar" y vuelve al botón que lo abrió. Un solo `<dialog>` en el DOM, reutilizado.
  2. Backend: agregar `PATCH /api/trusted-urls/<path:url>` con `{"estado": "activo"|"inactivo"}` y validación, en `flask_api.py`, junto al DELETE. Corregir el docstring del DELETE.
  3. UI de fuentes (`index.html:2113`):
     - El toggle Pausar/Activar es inmediato y no pide confirmación, porque es reversible.
     - "✕" pasa a ser "Eliminar" y pide confirmación con el texto: "Se elimina *{url}* de las fuentes. Los artículos ya guardados no se borran. Si solo querés que deje de buscarse, pausala."
  4. Aplicar `confirmar()` también a `fase2EliminarCliente` y a `descartarSug`. Esta última avisa que se descartan todas las sugerencias del dominio.
  5. En los tres borrados, revisar `r.ok` y `d.success` y mostrar el error con `showToast`. Hoy se traga.
- **Tests:**
  - pytest: el PATCH valida el estado, da 404 si la URL no existe y no toca otros campos.
  - Playwright: cancelar no borra, Esc no borra, confirmar sí borra.
- **Terminado cuando:** ningún DELETE sale sin pasar por `confirmar()` (se puede comprobar con un grep de `method: 'DELETE'`) y una fuente puede pausarse y reactivarse.

### Cambio 1: navegación sectorizada · PR3 · M/L

- **Opciones:**
  - **Sidebar.** Recomendado: entran 5 o 6 secciones con nombre completo, deja el header liviano y en mobile se convierte en una barra de pestañas arriba.
  - **Header con pestañas.** Con 6 pestañas más los controles actuales no entra en mobile sin un menú extra.
- **Secciones:**
  - Inicio (hero y KPIs; en dev, también las stats)
  - Crear nota
  - Programación
  - Fuentes
  - Corridas (vacía hasta PR6; en dev incluye HUD y consola)
- **Header:** queda la marca, el estado, el tema y salir. El switch de modo y el selector de Proveedor bajan al pie de la sidebar.
- **Pasos:**
  1. Generalizar `CARRUSEL` a `SECCIONES`, conservando su mecanismo: mover nodos reales con ancla, `inert` en las inactivas y `localStorage`.
  2. Agregar ruteo por hash (`#fuentes`) para que funcionen atrás y adelante y los links directos.
  3. Usar landmarks: `<nav aria-label="Secciones">` con links y `aria-current="page"`. No usar `role=tablist`, porque son vistas completas.
  4. Que los dos modos usen la misma navegación. El modo solo filtra qué secciones y bloques se ven (`.solo-dev` / `.solo-cliente`, como hoy).
  5. Borrar el carrusel coverflow (CSS `index.html:~1200-1310` y JS `~2486-2700`). Es la decisión abierta D1.
  6. Hook `antesDeSalirDeSeccion()`: hoy no hace nada, PR4 lo usa.
- **No partir `index.html` en este PR.** Es un cambio de build y de cómo Flask sirve los estáticos, sin beneficio para el usuario. Queda como deuda en los riesgos.
- **Tests:** Playwright para navegar por clic, por teclado y por hash, recargar y volver a la misma sección, y comprobar que en mobile no hay scroll horizontal.
- **Terminado cuando:** las dos vistas usan la misma navegación y el carrusel no existe más.

### Cambio 2: guardar con un botón aparte · PR4 · M

- **Alcance de "edición explícita":**
  - Programación: scraping y generación juntos. Una barra de guardado para la sección.
  - Config de Crear nota: categorías, regiones, puntapié, persona y tema.
- **Siguen siendo inmediatas:**
  - Alta y baja de Fuentes, Clientes y Sugerencias: son acciones sobre entidades, no config.
  - Pausar/activar una Fuente.
  - Selector de Proveedor: es solo de dev y es un interruptor operativo.
  - "Generar ahora": usa lo que se ve en pantalla aunque no esté guardado. Hay que verificar que `fase2/generar` ya mande los params del formulario.
- **Pasos:**
  1. Por sección, guardar al cargar un `snapshot` serializado de los valores y calcular `sucio = estadoActual() !== snapshot`. Sacar todos los `guardarAgenda`/`fase2GuardarConfig` de los handlers `change`/`click`, que pasan a solo repintar.
  2. Una barra fija abajo de la sección: "Cambios sin guardar · Descartar · Guardar". Oculta si no hay cambios y con el botón deshabilitado mientras guarda. Errores visibles en la barra, nunca tragados.
  3. Guardar manda un único POST por endpoint, en paralelo, solo con los campos cambiados (los endpoints ya aceptan parciales). Si sale bien, se toma un nuevo snapshot y `scheduler.aplicar()` corre en el server como hoy.
  4. Descartar restaura el snapshot en los controles, incluido el reloj SVG (`AGENDA[tipo].reloj.set`).
  5. Para avisar de cambios sin guardar: `beforeunload` y el hook `antesDeSalirDeSeccion()` de PR3, con `confirmar()` de PR2 ("Descartar cambios / Seguir editando").
  6. Backend: validar `/api/fase2/config`. Que sean listas de strings y que `puntapie_url` sea una URL pública reutilizando `_url_publica_o_400`.
- **Versionado:** no hace falta, porque hay un solo usuario (ver D3).
- **Tests:**
  - pytest para la validación de `fase2/config` en `tests/test_config_api.py`.
  - Playwright: tocar un chip no dispara un POST; Guardar dispara uno; Descartar restaura; navegar con cambios pide confirmación.
- **Terminado cuando:** ningún control de config dispara una red sin Guardar.

### Cambio 4: cola de Corridas · PR5 (backend) + PR6 (UI) · L

- **Dónde vive:** recomiendo **persistirla en Mongo**, en una colección `corridas`. En memoria la cola se pierde en cada redeploy, que justo es cuando más se nota, y no deja historial.
  - El lock en memoria se queda: sigue habiendo **un solo consumidor**, un thread en el único worker de gunicorn.
  - No hace falta un lock distribuido mientras siga `--workers 1`.
- **Documento:** `{_id, tipo, params, origen: cron|manual, estado: pendiente|en_curso|ok|error|cancelada|interrumpida, creada, inicio, fin, resultado, log_tail}`.
- **Semántica:**
  - **Orden:** FIFO.
  - **Deduplicación:** si ya hay una Corrida `pendiente` del mismo `tipo` con los mismos `params`, devolver su id en vez de crear otra. Así el cron no se suma a un clic manual idéntico.
  - **Tope:** 5 pendientes; si se pasa, 429 con un mensaje claro.
  - **Prioridad:** ninguna en v1 (decisión abierta D4).
  - **Cancelar:**
    - Una pendiente se cancela marcándola `cancelada`.
    - Una en curso de tipo `script`/`stream` mata el subprocess, como ya hace `stream` en `corridas.py:245`.
    - El scraping in-process mira un flag entre fuente y fuente (`corridas.py:103`).
  - **Timeout:** se mantiene en 30 min, pero se aplica en el consumidor y no en la request.
  - **Al arrancar:** las `en_curso` pasan a `interrumpida` y no se reintentan. Las `pendiente` se retoman.
- **Streaming:** los endpoints SSE dejan de correr el subprocess dentro de la request. Pasan a encolar y devolver `{id}`.
  - El log se lee con **polling**: `GET /api/corridas/<id>/log?desde=N` cada 1,5 s, desde un buffer en memoria de la Corrida actual más `log_tail` persistido al terminar.
  - Se elige polling y no SSE porque cada SSE ocupa uno de los 4 threads de gunicorn durante 30 minutos (ver hallazgos).
  - La lista de la cola también se consulta por polling (`GET /api/corridas`), cada 3 s mientras la sección está visible.
- **Cambios en `corridas.py`:**
  - Agregar `encolar(tipo, params, origen) → id`, `cancelar(id)`, `listar()`, `log(id, desde)`, `_consumidor()` (un thread que arranca con el scheduler en `scheduler.iniciar()`) y `recuperar_al_arrancar()`.
  - `scraping`, `generacion`, `script` y `stream` pasan a ser ejecutores internos del consumidor.
  - El scheduler llama a `encolar(..., origen="cron")`, así que **los choques del cron dejan de perder Corridas**.
  - `/api/run-*` devuelve 202 con el id en vez de 409.
- **ADR:** escribir `docs/adr/0002-cola-de-corridas-persistida.md`, que reemplaza a la 0001. Se mantiene que corre una sola Corrida a la vez y que depende de `--workers 1`. Cambia que las Corridas se encolan en lugar de rechazarse y que la cola sobrevive reinicios. Actualizar `CONTEXT.md` con el término **Cola**.
- **UI (PR6):**
  - En la sección Corridas: la que está en curso, con su log en vivo y el botón "Cancelar" (que pasa por `confirmar()`); las pendientes con su posición; y las últimas 20 terminadas, con su estado y duración.
  - Los botones "Generar ahora" y "Buscar noticias" muestran "En cola (#2)" en vez de un error.
  - El HUD y la consola de dev pasan a leer este mismo log.
- **Tests (pytest, siguiendo `tests/test_corridas.py` y el fake de Mongo de `tests/conftest.py`, que hay que verificar):**
  - Encolar dos Corridas ejecuta en orden.
  - Encolar un duplicado devuelve el mismo id.
  - Pasar el tope da 429.
  - Cancelar una pendiente hace que nunca corra.
  - Cancelar una en curso mata el proceso.
  - Al arrancar, una `en_curso` queda `interrumpida`.
  - El cron que choca queda encolado.
  - El log se pagina por offset.
- **Terminado cuando:** dos clics seguidos ejecutan dos Corridas sin error, un redeploy no pierde las pendientes y el ADR-0002 está mergeado.

### Cambio 5 (parte B): pulido por componente · PR7 · M

- Reemplazar los ~6 `box-shadow` hardcodeados (`index.html:570, 700, 847, 851, 953`) y los `transition: box-shadow` que quedan sin efecto.
- Pasar las cards a `background: var(--surface)` donde haga falta.
- Sacar los alias de tokens viejos (`--raised*`/`--inset*`) una vez que nadie los use.
- **Tests y criterio:** las mismas capturas de PR1, con un grep de `--sh-dark|--raised|--inset` igual a 0.

## 4. Decisiones abiertas

| # | Decisión | Opciones | Recomiendo | Si respondés distinto |
|---|---|---|---|---|
| D1 | ¿Se elimina el carrusel coverflow del modo cliente? | Eliminar / conservarlo como vista alternativa | Eliminar: una sola navegación, ~400 líneas menos | PR3 pasa a L y la sidebar convive con el carrusel |
| D2 | ¿El selector de Proveedor queda inmediato o entra al Guardar? | Inmediato / con Guardar | Inmediato: es operativo y solo de dev | PR4 suma un formulario más |
| D3 | ¿Versionado para no pisar cambios? | No / timestamp con 409 | No: hay un solo usuario | +1 campo en `config_store` y manejo del 409 en la barra |
| D4 | ¿Las Corridas manuales pasan delante de las del cron? | FIFO / prioridad manual | FIFO más deduplicación (más simple y predecible) | Un campo `prioridad` y orden compuesto en el consumidor |
| D5 | Cola persistida en Mongo o en memoria | Mongo / memoria | Mongo | En memoria: PR5 baja a M, pero se pierde todo en cada redeploy |
| D6 | Estilo A (plano con bordes) o B (sombra suave en cards) | A / B | A | Cambia un solo token: `--raised` → `0 1px 2px …` |

## 5. Riesgos transversales

- **HTML monolítico de 3463 líneas:** los conflictos de merge entre PRs son casi seguros. Hay que mergear en orden y no abrir PR3 y PR4 a la vez. Partir el archivo (CSS y JS a `/static`) queda como deuda explícita para después de PR7.
- **Render free:** la RAM limitada es la razón de que corra una sola Corrida a la vez y la cola no la cambia. Sí cambia el uso de threads: hay que confirmar con una prueba en Render que el polling cada 1,5 a 3 s no despierta ni sobrecarga la instancia.
- **`--workers 1` es una precondición.** Si algún día suben los workers, la cola en Mongo necesita un claim atómico (`find_one_and_update`). Conviene diseñarlo así desde PR5: es casi gratis y elimina el riesgo.
- **Regresión de accesibilidad** al sacar el neumorfismo: medir contraste en PR1 y PR7, no a ojo.
- **Comportamiento visible que cambia:** el autoguardado desaparece. El usuario que hoy cambia una hora y se va va a perder el cambio si no guarda. El aviso de "cambios sin guardar" es obligatorio en PR4, no opcional.

## 6. Entregas propuestas

1. **PR1:** tokens planos (S/M). Reversible con un commit.
2. **PR2:** `confirmar()` + PATCH de estado de fuente + borrados con confirmación (M). Puede ir en paralelo con PR1.
3. **PR5:** cola backend + ADR-0002 (L). En paralelo desde el inicio, porque no toca el HTML.
4. **PR3:** navegación sectorizada (M/L). Después de PR1 y PR2.
5. **PR4:** guardar explícito (M). Después de PR3.
6. **PR6:** panel de Corridas (M). Después de PR3 y PR5.
7. **PR7:** pulido de estilo y limpieza de tokens viejos (M).

Cada PR se despliega solo y se valida en Render antes del siguiente.
