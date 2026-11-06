/* navegacion.js — Barra lateral, secciones y vistas.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   SECCIONES: una a la vez, elegida en la barra lateral.
   La sección activa vive en el hash (#crear), así andan atrás/adelante.
   Al abrir la app siempre se arranca en Inicio, aunque la dirección traiga
   otra sección; el logo también lleva a Inicio.
   Antes de salir se consultan los guardianes (cambios sin guardar).
   ═══════════════════════════════════════════════════════════════════════ */
var SECCIONES = ['inicio', 'crear', 'historial', 'programacion', 'fuentes', 'prompts', 'corridas'];
var _seccion = null;
var _guardianes = [];

/* fn(desde, hacia) -> false (o Promise<false>) para frenar la navegación */
function antesDeSalirDeSeccion(fn) { _guardianes.push(fn); }

function seccionVisible(id) {
  var link = document.querySelector('.nav-link[data-seccion="' + id + '"]');
  // El menú móvil plegado no invalida enlaces directos ni acciones del contenido.
  return !!link && getComputedStyle(link).display !== 'none';
}

function seccionDelHash() {
  var id = location.hash.replace('#', '');
  return SECCIONES.indexOf(id) >= 0 ? id : null;
}

async function irASeccion(id, opts) {
  opts = opts || {};
  if (SECCIONES.indexOf(id) < 0 || !seccionVisible(id)) id = 'inicio';
  if (id === _seccion) return;
  if (_seccion && !opts.forzar) {
    for (var i = 0; i < _guardianes.length; i++) {
      if (await _guardianes[i](_seccion, id) === false) {
        if (opts.desdeHash) history.replaceState(null, '', '#' + _seccion);
        return;
      }
    }
  }
  var anterior = _seccion;
  _seccion = id;
  pintarMiga(id);
  document.querySelectorAll('#contenido [data-seccion]').forEach(function(el) {
    el.classList.toggle('activa', el.dataset.seccion === id);
  });
  document.querySelectorAll('.nav-link').forEach(function(a) {
    if (a.dataset.seccion === id) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  if (!opts.desdeHash && location.hash !== '#' + id) {
    if (anterior) history.pushState(null, '', '#' + id);
    else history.replaceState(null, '', '#' + id);
  }
  if (anterior) {
    window.scrollTo({ top: 0 });
    $('contenido').scrollTop = 0;   // en escritorio scrollea el contenido, no la página
    $('contenido').focus({ preventScroll: true });
  }
  document.dispatchEvent(new CustomEvent('seccion', { detail: id }));
}

function initSecciones() {
  // Con una nota abierta (vista Cliente), la barra de íconos sigue andando: cierra la nota y va a la sección.
  var ir = async function(id) { if (await cerrarNotaParaNavegar()) irASeccion(id); };
  document.querySelectorAll('.nav-link').forEach(function(a) {
    a.addEventListener('click', function(ev) {
      ev.preventDefault();
      ir(a.dataset.seccion);
    });
  });
  window.addEventListener('popstate', function() {
    if (notaAbierta()) cerrar();
    irASeccion(seccionDelHash() || 'inicio', { desdeHash: true });
  });
  $('ir-inicio').addEventListener('click', function(ev) {
    ev.preventDefault();
    ir('inicio');
  });
  try { localStorage.removeItem('ad-seccion'); } catch(e) {}   // lo guardaban versiones anteriores
  irASeccion('inicio', { forzar: true });
}

/* ═══════════════════════════════════════════════════════════════════════
   MODOS DE VISTA
   ═══════════════════════════════════════════════════════════════════════ */
function setModo(modo) {
  modo = modo === 'dev' ? 'dev' : 'cliente';
  document.documentElement.setAttribute('data-modo', modo);
  try { sessionStorage.setItem('ad-modo', modo); } catch(e) {}   // al volver a entrar, arranca en Cliente

  document.querySelectorAll('.modo-switch button').forEach(function(b) {
    b.setAttribute('aria-checked', b.dataset.modo === modo);
  });
  // Textos: data-cliente guarda la versión cliente; la original se recuerda en data-dev.
  document.querySelectorAll('[data-cliente]').forEach(function(el) {
    if (el.dataset.dev === undefined) el.dataset.dev = el.textContent;
    if (!el.classList.contains('loading')) el.textContent = modo === 'cliente' ? el.dataset.cliente : el.dataset.dev;
  });
  if (typeof pintarDia === 'function') pintarDia();   // el día de Programación nombra las tareas
  ajustarMarcoCliente();
  // Si la sección actual no existe en esta vista, se vuelve al inicio.
  if (_seccion && !seccionVisible(_seccion)) irASeccion('inicio', { forzar: true });
  // Una nota abierta se vuelve a abrir en la vista nueva (en Cliente se lee como documento).
  if ($('modal-art') && $('modal-art').classList.contains('open') && typeof _notaActual !== 'undefined' && _notaActual
      && _notaActual.coleccion === 'notas_fase2') fase2MostrarUltima(_notaActual.id);
}

// Desde los botones de la barra lateral: pide confirmación antes de cambiar.
var _TEXTOS_MODO = {
  dev: { titulo: '¿Pasar a la vista Desarrollador?', accion: 'Pasar a Desarrollador',
         mensaje: 'Vas a ver la consola, las métricas del pipeline y la elección del proveedor de IA. Desde ahí se pueden cambiar cosas que afectan a todo el sistema.' },
  cliente: { titulo: '¿Pasar a la vista Cliente?', accion: 'Pasar a Cliente',
             mensaje: 'Vas a ver solo lo esencial para crear y revisar notas. La consola y las métricas quedan ocultas hasta que vuelvas a Desarrollador.' },
};
async function pedirModo(modo) {
  modo = modo === 'dev' ? 'dev' : 'cliente';
  if (document.documentElement.getAttribute('data-modo') === modo) return;
  var t = _TEXTOS_MODO[modo];
  if (await confirmar({ titulo: t.titulo, mensaje: t.mensaje, accion: t.accion, peligro: false })) setModo(modo);
}

function toggleMasOpciones() {
  var sec = document.querySelector('.fase2-section');
  var abierto = sec.classList.toggle('mas-abiertas');
  $('btn-mas-opciones').setAttribute('aria-expanded', abierto);
  $('btn-mas-opciones').querySelector('.mas-opciones-texto').textContent = abierto ? 'Menos opciones' : 'Más opciones';
  if (abierto) document.querySelector('.f2-regiones').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* Tarjeta "Última nota" de la bienvenida */
async function cargarUltimaNota() {
  try {
    var r = await fetch('/api/fase2/ultima-nota');
    var d = await r.json();
    if (!d.success || !d.nota || !d.nota.contenido) return;
    var md = d.nota.contenido;
    var titulo = (md.match(/^#{1,2}\s+(.+)$/m) || [])[1] || 'Nota sin título';
    var cuerpo = md.replace(/^#.*$/gm, '').replace(/[*_>`\[\]]/g, '').replace(/\(https?:[^)]+\)/g, '').replace(/\s+/g, ' ').trim();
    $('c-ultima-titulo').textContent = titulo.replace(/[*_]/g, '');
    $('c-ultima-extracto').textContent = cuerpo.slice(0, 220) + (cuerpo.length > 220 ? '...' : '');
    if (d.nota.generado_en) {
      $('c-ultima-fecha').textContent = new Date(d.nota.generado_en).toLocaleString(localeUI(), {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'
      });
    }
    $('c-ultima-btn').disabled = false;
  } catch(e) {}
}

/* Progreso de la generación en lenguaje simple (los dos modos) */
var PASOS_GENERACION = [
  [/noticias de contexto:\s*(\d+)/i, function(m) { return +m[1] ? 'Leyendo ' + m[1] + ' noticias recientes...' : 'No hay noticias recientes: se escribe sin datos concretos...'; }],
  [/few-shot|ejemplo\(s\) cargado/i, 'Buscando notas de referencia...'],
  [/planificando la nota/i, 'Armando el plan de la nota...'],
  [/verificando los datos/i, 'Verificando los datos contra las noticias...'],
  [/evaluando calidad/i, 'Revisando la calidad...'],
  [/reescribiendo la nota/i, 'Corrigiendo lo que la revisión encontró...'],
  [/generando nota/i, 'Escribiendo la nota...'],
  [/^\s*\[(\d+)s\]/, function(m) {
    var seg = +m[1], min = Math.floor(seg / 60), resto = seg % 60;
    return 'Escribiendo la nota... (' + (min ? min + ' min' + (resto ? ' ' + resto + ' s' : '') : seg + ' s') + ')';
  }],
  [/generaci[oó]n completa/i, 'Revisando el texto...'],
  [/nota guardada/i, 'Guardando la nota...']
];
function pasoGeneracion(linea) {
  for (var i = 0; i < PASOS_GENERACION.length; i++) {
    var m = linea.match(PASOS_GENERACION[i][0]);
    if (m) return typeof PASOS_GENERACION[i][1] === 'function' ? PASOS_GENERACION[i][1](m) : PASOS_GENERACION[i][1];
  }
  return null;
}

function toggleNavegacion() {
  var b = $('menu-movil'), abierto = b.getAttribute('aria-expanded') !== 'true';
  b.setAttribute('aria-expanded', abierto);
  document.querySelector('.sidebar').classList.toggle('menu-abierto', abierto);
}
document.addEventListener('seccion', function() {
  $('menu-movil').setAttribute('aria-expanded', 'false');
  document.querySelector('.sidebar').classList.remove('menu-abierto');
  if (_seccion === 'inicio') { cargarUltimaNota(); cargarResumenHistorial(); }
});
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && $('menu-movil').getAttribute('aria-expanded') === 'true') {
    toggleNavegacion(); $('menu-movil').focus();
  }
});


/* ═══════════════════════════════════════════════════════════════════════
   MARCO DE LA VISTA CLIENTE (escritorio)
   Arriba una barra fina con el logo y "afterdrive" como siempre, el idioma, el
   estado y el tema. A la izquierda la barra de secciones, ordenada como la de
   ChatGPT: arriba "Nueva nota" (el botón que la pliega, chico al costado); en el
   medio las secciones; abajo el perfil, que abre Ayuda, el paso a la vista
   Desarrollador y Cerrar sesión. El buscador se abre con ⌘K / Ctrl+K. Plegada muestra solo los íconos; desplegada, también
   los nombres (se recuerda en ad-riel). En Desarrollador y en el celular todo
   queda como siempre.
   ═══════════════════════════════════════════════════════════════════════ */
var NOMBRE_SECCION = { inicio: 'Inicio', crear: 'Nueva nota', historial: 'Notas', programacion: 'Programación',
                       fuentes: 'Fuentes', prompts: 'Prompts', corridas: 'Actividad' };
var _escritorio = window.matchMedia('(min-width: 901px)');

function pintarMiga(id) {
  document.documentElement.dataset.seccion = id;
  var miga = $('header-miga');
  if (miga) miga.textContent = tr(NOMBRE_SECCION[id] || '');
}

// Pie de la barra (vista Cliente): quién está conectado.
var _perfilCargado = false;
async function cargarPerfil() {
  if (_perfilCargado) return;
  _perfilCargado = true;
  try {
    var s = await pedir('/api/sesion');
    var nombre = (s && s.usuario) || '';
    if (!nombre) return;
    $('perfil-nombre').textContent = nombre;
  } catch (e) { _perfilCargado = false; }
}

function ajustarMarcoCliente() {
  var pie = $('rail-pie');
  if (!pie) return;
  var enRiel = document.documentElement.getAttribute('data-modo') === 'cliente' && _escritorio.matches;
  var ayuda = document.querySelector('.sidebar-ayuda');
  if (enRiel && ayuda.parentNode !== pie) pie.appendChild(ayuda);
  if (enRiel) cargarPerfil();
  else if (!enRiel && ayuda.parentNode === pie) pie.parentNode.insertBefore(ayuda, pie);
  pintarRiel();
}

/* Barra plegada (solo íconos) o desplegada (íconos y nombres, como antes). */
function rielAbierto() {
  try { return localStorage.getItem('ad-riel') === 'abierto'; } catch (e) { return false; }
}
function toggleRiel() {
  try { localStorage.setItem('ad-riel', rielAbierto() ? 'cerrado' : 'abierto'); } catch (e) {}
  pintarRiel();
}
function pintarRiel() {
  var abierto = rielAbierto(), btn = $('rail-toggle');
  var enRiel = document.documentElement.getAttribute('data-modo') === 'cliente' && _escritorio.matches;
  if (abierto) document.documentElement.dataset.riel = 'abierto';
  else delete document.documentElement.dataset.riel;
  if (btn) {
    btn.setAttribute('aria-expanded', abierto ? 'true' : 'false');
    var texto = tr(abierto ? 'Contraer menú' : 'Desplegar menú');
    btn.setAttribute('aria-label', texto);
    btn.title = texto;
  }
  // Plegada, cada ícono dice qué es al pasar el mouse; desplegada ya se lee el nombre.
  document.querySelectorAll('.nav-link').forEach(function(a) {
    if (enRiel && !abierto) a.title = tr(NOMBRE_SECCION[a.dataset.seccion] || '');
    else a.removeAttribute('title');
  });
}
(_escritorio.addEventListener ? _escritorio.addEventListener('change', ajustarMarcoCliente) : _escritorio.addListener(ajustarMarcoCliente));
document.addEventListener('idioma', function() { if (_seccion) pintarMiga(_seccion); ajustarMarcoCliente(); });
