# 06 · Dashboard

La interfaz está en **`express/src/public/`**, sin framework ni build. Flask sirve los archivos tal cual: editás, recargás el navegador y lo ves.

```
express/src/public/
├── login.html
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
        └── arranque.js       inicializa todo al cargar
```

Todas las funciones son globales (los `onclick` del HTML las llaman). Si agregás un archivo JS, sumalo al final de `index.html` en el lugar que le toque: un test (`tests/test_auth.py`) revisa que `index.html` cargue todos los de `assets/js/`.

## Lo que ve el usuario

Una barra lateral con secciones; se ve una a la vez.

| Sección | Qué hay |
|---|---|
| **Inicio** | Resumen y última nota (vista Cliente) o estadísticas (vista Desarrollador) |
| **Crear nota** | Categorías, regiones, clientes, tono, tema y puntapié. Botón Generar nota |
| **Historial** | Notas para revisar (aprobar, rechazar, editar, publicar en HubSpot), notas descartadas y artículos guardados o descartados con su motivo |
| **Programación** | Hora, frecuencia y activación del scraping y de la nota automática |
| **Fuentes** | Fuentes de noticias (pausar, eliminar, agregar) y recomendaciones |
| **Corridas** | Lo que está corriendo con su log, lo que espera y lo último que terminó |

Al pie de la barra se elige la **vista** (Cliente, simple; Desarrollador, completa) y, en Desarrollador, el **proveedor de IA**.

## Cómo está organizado el código

Lo que más vas a tocar:

| Dónde | Qué hace |
|---|---|
| `navegacion.js` | Navegación. `irASeccion('fuentes')` cambia de sección; la sección vive en el hash (`#fuentes`) |
| `navegacion.js` | `setModo('cliente' \| 'dev')` |
| `base.js` | `formulario(id, {leer, aplicar, guardar})`: estado sucio, barra Guardar/Descartar, aviso al salir |
| `corridas.js` | `correrEnCola(ruta, body, onLinea, onEstado)` y el panel de Corridas |
| `historial.js` | Listas del historial y acciones sobre la nota abierta (`_notaActual`, `pintarAccionesNota()`): aprobar, rechazar con motivo, editar, vista previa con imagen y HubSpot |
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

- Probalo en las dos vistas y los dos temas.
- Probalo a 390 px de ancho: no puede aparecer scroll horizontal.
- Mirá la consola del navegador: cero errores.
- `python -m pytest` (hay tests que leen el HTML y el JS).
- `python -m pytest -m e2e tests/e2e`: abre el dashboard en Chromium y prueba login, secciones, guardado, fuentes, revisión de notas, la cola y el ancho de celular. Si agregás un flujo nuevo, sumale un test en `tests/e2e/test_dashboard.py`.
