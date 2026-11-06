# 06 · Dashboard

La interfaz está en **`express/src/public/`**, sin framework ni build. Flask sirve los archivos tal cual: editás, recargás el navegador y lo ves.

```
express/src/public/
├── login.html
├── ayuda.html              documentación dentro de la app (/ayuda)
├── index.html              solo el HTML (y el script del tema, para que no parpadee)
└── assets/                 se sirve en /assets/, pide sesión y no se cachea
    ├── css/dashboard.css   todos los estilos
    └── js/                 se cargan en este orden, como scripts comunes (no módulos)
        ├── base.js           $(), pedir(), escHtml(), confirmar(), formulario()
        ├── estado.js         indicador Online, estadísticas
        ├── fuentes.js        lista de fuentes, pausar, eliminar, agregar
        ├── programacion.js   relojes y formulario de Programación
        ├── navegacion.js     secciones y modos de vista
        ├── corridas.js       correrEnCola() y el panel de Corridas
        ├── proveedores.js    proveedor de IA
        ├── sugerencias.js    fuentes recomendadas
        ├── generador.js      Crear nota y el modal de la nota
        ├── historial.js      Historial y revisión de notas
        ├── revision.js       calificación, lo revisado al generar y panel de calibración
        ├── lectura.js        revisión de la nota en la vista Cliente (la nota como documento)
        ├── promptsia.js      Prompts con IA: análisis, pedidos a la IA y la copia de los prompts
        ├── tour.js           recorrido guiado y menú de Ayuda
        ├── arranque.js       inicializa todo al cargar
        └── paginas/ayuda.js  página /ayuda (documentación); no la carga index.html, sino ayuda.html
```

Todas las funciones son globales (los `onclick` del HTML las llaman). Si agregás un archivo JS, sumalo al final de `index.html` en el lugar que le toque: un test (`tests/test_auth.py`) revisa que `index.html` cargue todos los de `assets/js/`.

## Lo que ve el usuario

Una barra lateral con secciones; se ve una a la vez.

| Sección | Qué hay |
|---|---|
| **Inicio** | Resumen y última nota (vista Cliente) o estadísticas (vista Desarrollador) |
| **Crear nota** | Categorías (con **Rotar categorías automáticamente**), regiones, clientes, tono, tema y puntapié. Botón Generar nota. El tema y las indicaciones son solo para esa nota: se vacían al generarla y no se guardan |
| **Historial** | Notas para revisar (aprobar, rechazar, editar, publicar en HubSpot), notas descartadas y artículos guardados o descartados con su motivo |
| **Programación** | Hora, frecuencia y activación del scraping y de la nota automática. **Más notas por día**: horarios extra de generación, con lo que cuesta cada nota y cuántas entran en el tope de la API paga |
| **Fuentes** | Fuentes de noticias (pausar, eliminar, agregar) y recomendaciones, ordenadas por puntaje (relevancia y en cuántas búsquedas aparecen) |
| **Corridas** | Lo que está corriendo con su log, lo que espera y lo último que terminó |

Al pie de la barra se elige la **vista** (Cliente, simple; Desarrollador, completa) y, en Desarrollador, el **proveedor de IA**.

Arriba de eso, separado y en las dos vistas, está el interruptor **API paga**: pone todo el pipeline en la API paga por 24 horas como máximo, con un aviso de costo antes de prenderse y la cuenta regresiva hasta que se apaga solo (ver [04-ia.md](04-ia.md)).

## Cómo está organizado el código

Lo que más vas a tocar:

| Dónde | Qué hace |
|---|---|
| `navegacion.js` | Navegación. `irASeccion('fuentes')` cambia de sección; la sección vive en el hash (`#fuentes`) |
| `navegacion.js` | `setModo('cliente' \| 'dev')` |
| `buscador.js` | **Buscar o saltar a…** (⌘K / Ctrl+K): sin escribir lista las secciones; al escribir filtra y busca notas por título, tema o texto (`/api/historial/generados_aprobados?q=`). Flechas, Enter y Esc |
| `navegacion.js` | **Marco de la vista Cliente en escritorio** (`ajustarMarcoCliente`): arriba una barra fina con el logo, idioma, estado, tema y salir. A la izquierda la barra de secciones, ordenada como la de ChatGPT: arriba **Nueva nota** (la acción principal), con el botón que la pliega chico al costado; en el medio las secciones (`.nav-link`, con los íconos de las maquetas `.icono-riel`); abajo el perfil (la silueta de una persona y el usuario: `cargarPerfil`, `GET /api/sesion`), que abre el menú de Ayuda. En ese menú, **Pasar a la vista Desarrollador** (turquesa, `.ayuda-dev`) y **Cerrar sesión** (rojo, `.ayuda-salir`; sale del encabezado) van aparte, del mismo alto que el resto. Plegada muestra solo íconos; desplegada, los nombres (`ad-riel`). En Desarrollador y en el celular todo vuelve a su lugar. La revisión de una nota se abre a la derecha de la barra, que sigue andando: tocar una sección cierra la nota (`cerrarNotaParaNavegar`, en `generador.js`; si se está editando el texto, pregunta). `fondoInerte` deja inerte solo lo que queda tapado |
| `base.js` | `formulario(id, {leer, aplicar, guardar})`: estado sucio, barra Guardar/Descartar, aviso al salir |
| `corridas.js` | `correrEnCola(ruta, body, onLinea, onEstado)` y el panel de Corridas. También la **terminal** de abajo, como la de VS Code: en escritorio ocupa una fila de la grilla debajo del contenido (el contenido se achica y scrollea, nada queda encimado); en el celular flota abajo. Pestañas Terminal (el registro, con color por `[OK]`, `[ERROR]`, `[AVISO]`) y Cola; el borde de arriba se arrastra para cambiar el alto (`ad-terminal-alto`; con el borde enfocado, flechas), y tiene maximizar, ocultar y cerrar |
| `promptsia.js` | **Prompts con IA** (`prompts_ia.py`): la tarjeta de arriba de Prompts (qué hace, la mejora automática, con qué prompts escribe la redacción y **Analizar y mejorar ahora**, que corre en la cola con `correrEnCola` y muestra el avance) y el panel **Ver qué cambió**: último análisis, pedido a mano, la copia pieza por pieza (diferencias, deshacer el último cambio, volver a la actual) y las últimas mejoras con sus diferencias (`diffPromptHtml`) |
| `historial.js` | Listas del historial y acciones sobre la nota abierta (`_notaActual`, `pintarAccionesNota()`): aprobar, rechazar con motivo, editar, vista previa con imagen y HubSpot |
| `tour.js` | Recorrido guiado (`PASOS_TOUR`): se abre solo la primera vez en cada navegador (`localStorage` `ad-tour-visto`) y desde **Ayuda → Repetir el tutorial**. Cada paso va a su sección y resalta un elemento real; si no se ve en la vista actual, se saltea (`soloDev` marca los de Desarrollador). Al agregar una función nueva, sumale su paso |
| `paginas/ayuda.js` + `ayuda.html` | **Ayuda → Ver la documentación**: la guía de uso (`docs/guia-de-uso.md`), el glosario y la documentación técnica, renderizados con marked + DOMPurify. Los documentos son una lista blanca (`DOCUMENTOS` en `flask_api.py`) |
| `idioma.js` + `i18n/textos.js` | Interfaz en español, portugués o inglés (ver abajo) |
| `generador.js` | **Crear nota en la vista Cliente**: tres pasos (temas, enfoque, estilo) y, en escritorio, el panel fijo **Tu nota** a la derecha (`resumenCrear`) con el botón Generar. Tono y largo se eligen con botones (`pintarChipsSelect`) que cambian el valor del select de siempre (el que se guarda y lee la generación). Más opciones va al final del formulario. La vista Desarrollador no cambia |
| `lectura.js` | **Revisión de una nota en la vista Cliente**: la nota en serif con los datos verificados marcados (subrayado punteado con respaldo, fondo amarillo dudoso, rojo sin respaldo) y su aviso debajo del párrafo, también en las traducciones (las cifras se buscan por sus dígitos: `patronDeDato`). Las frases en negrita que guardaron notas viejas como dato no se marcan (`esDatoVerificable`, misma regla que `extraer_datos`); arriba "Notas / título", estado y Rechazar / Aprobar y subir; a la derecha un panel con la vista previa (switch Blog / Instagram / LinkedIn) o la calificación; abajo una barra flotante (Editar, Calificar, Vista previa, Más). Reusa las acciones de `historial.js`, `revision.js` y `carrusel.js`. La vista Desarrollador sigue con el recorrido de `recorrido.js` (`armarRecorrido` decide según la vista) |
| `revision.js` | Calificación de la nota abierta (estrellas, etiquetas, comentario), lo que se revisó al generarla (datos contra las noticias, estilo y SEO, plan) y el panel "Cómo aprende la generación" del Historial |
| `base.js` | `confirmar()` (diálogo; con `campo` pide un texto, como el motivo de un rechazo) y `pedir()` (`fetch` que lanza error si el server responde error) |

## Patrones que hay que respetar

**Marcar a qué sección pertenece un bloque**

```html
<section class="fuentes-seccion" data-seccion="fuentes">…</section>
```

**Mostrar algo solo en una vista**: clases `solo-dev` y `solo-cliente`. Textos distintos por vista: `data-cliente="Texto para cliente"` (el contenido original es el de Desarrollador).

**Nada destructivo sin confirmar**

```js
if (!await confirmar({ titulo: '¿Eliminar…?', mensaje: 'Qué se pierde y qué no.', accion: 'Eliminar' })) return;
```

**La configuración no se guarda sola.** Si agregás un campo a Programación o Crear nota, sumalo al `leer()` y `aplicar()` de su formulario y llamá a `marcarProgramacion()` / `marcarCrear()` cuando cambie.

**Las Corridas se encolan**, nunca se ejecutan con un `fetch` largo:

```js
var fin = await correrEnCola('/api/corridas/scraping', null, function(linea) { log(linea); });
if (fin.estado === 'ok') { … }
```

**Datos del servidor dentro de HTML, siempre escapados**: `escHtml(texto)`, y `encArg(texto)` dentro de un `onclick='…'`. Un test (`tests/test_auth.py`) revisa que no se cuelen sin escapar.

**Idiomas (ES / PT / EN).** Se eligen en el login, en el primer paso del recorrido guiado, en el encabezado y en `/ayuda`; quedan en `localStorage` (`ad-idioma`; sin elegir, el del navegador). El código sigue escrito en español: `idioma.js` traduce lo que se ve (textos y `placeholder`, `title`, `aria-label`, `alt`) buscando cada texto en `i18n/textos.js`, y un `MutationObserver` traduce lo que el JS pinta después. Por eso:

- **Un texto nuevo de la interfaz** se suma a `_FILAS_TEXTOS` como `[español, português, english]`. Si lleva números o nombres, va un patrón en `PATRONES` (uno por idioma). Lo que falte queda en español; no rompe nada.
- **El contenido no se traduce**: notas, noticias, títulos y URLs van dentro de un elemento con `translate="no"`. Si pintás contenido nuevo, marcalo.
- **Fechas**: `toLocaleString(localeUI(), …)`, nunca `'es-AR'` fijo.
- Desde el JS, `tr('Texto en español')` devuelve la traducción (por ejemplo, para un `confirm` o un título de documento).
- El login (`login.html`) tiene sus propios textos (`TEXTOS_LOGIN`), porque no carga los scripts del dashboard.
- La guía de uso tiene traducción (`docs/guia-de-uso.pt.md`, `.en.md`): `/api/docs/<slug>?idioma=pt` la sirve si existe y si no, el original. Al cambiar la guía, cambiá las tres.

## Estilo

Superficies planas con borde; la sombra queda solo para lo que flota (modal, toasts, barra de guardado). Todo sale de variables CSS al principio de `dashboard.css`:

| Variable | Uso |
|---|---|
| `--canvas` | Fondo de la página |
| `--bg` | Superficie de cards, botones y chips |
| `--well` | Pozos: inputs, grupos, estado activo |
| `--border`, `--border-strong` | Bordes; el fuerte en campos editables (contraste ≥ 3:1) |
| `--raised`, `--inset`, `--field` | "Elevación" de un elemento (hoy son bordes) |
| `--shadow-float` | La única sombra real |
| `--brand`, `--ok`, `--err`, `--warn`, `--info` | Colores |

Cada color tiene versión clara y oscura (`[data-theme="dark"]`). **No uses colores sueltos**: agregá o reusá una variable y probá los dos temas.

## Antes de subir un cambio de dashboard

- Probalo en las dos vistas, los dos temas y, si agregaste textos, en portugués o inglés.
- Probalo a 390 px de ancho: no puede aparecer scroll horizontal.
- Mirá la consola del navegador: cero errores.
- `python -m pytest` (hay tests que leen el HTML y el JS).
- `python -m pytest -m e2e tests/e2e`: abre el dashboard en Chromium y prueba login, secciones, guardado, fuentes, revisión de notas, la cola y el ancho de celular. Si agregás un flujo nuevo, sumale un test en `tests/e2e/test_dashboard.py`.
