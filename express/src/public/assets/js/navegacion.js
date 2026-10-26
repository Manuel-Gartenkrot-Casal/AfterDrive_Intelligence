/* navegacion.js — Barra lateral, secciones y vistas.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   SECCIONES: una a la vez, elegida en la barra lateral.
   La sección activa vive en el hash (#crear), así andan atrás/adelante y
   los links directos; también se recuerda para la próxima visita.
   Antes de salir se consultan los guardianes (cambios sin guardar).
   ═══════════════════════════════════════════════════════════════════════ */
var SECCIONES = ['inicio', 'crear', 'historial', 'programacion', 'fuentes', 'corridas'];
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
  document.querySelectorAll('#contenido [data-seccion]').forEach(function(el) {
    el.classList.toggle('activa', el.dataset.seccion === id);
  });
  document.querySelectorAll('.nav-link').forEach(function(a) {
    if (a.dataset.seccion === id) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  try { localStorage.setItem('ad-seccion', id); } catch(e) {}
  if (!opts.desdeHash && location.hash !== '#' + id) {
    if (anterior) history.pushState(null, '', '#' + id);
    else history.replaceState(null, '', '#' + id);
  }
  if (anterior) {
    window.scrollTo({ top: 0 });
    $('contenido').focus({ preventScroll: true });
  }
  document.dispatchEvent(new CustomEvent('seccion', { detail: id }));
}

function initSecciones() {
  document.querySelectorAll('.nav-link').forEach(function(a) {
    a.addEventListener('click', function(ev) {
      ev.preventDefault();
      irASeccion(a.dataset.seccion);
    });
  });
  window.addEventListener('popstate', function() {
    irASeccion(seccionDelHash() || 'inicio', { desdeHash: true });
  });
  var guardada = null;
  try { guardada = localStorage.getItem('ad-seccion'); } catch(e) {}
  irASeccion(seccionDelHash() || guardada || 'inicio', { forzar: true });
}

/* ═══════════════════════════════════════════════════════════════════════
   MODOS DE VISTA
   ═══════════════════════════════════════════════════════════════════════ */
function setModo(modo) {
  modo = modo === 'dev' ? 'dev' : 'cliente';
  document.documentElement.setAttribute('data-modo', modo);
  try { localStorage.setItem('ad-modo', modo); } catch(e) {}

  document.querySelectorAll('.modo-switch button').forEach(function(b) {
    b.setAttribute('aria-checked', b.dataset.modo === modo);
  });
  // Textos: data-cliente guarda la versión cliente; la original se recuerda en data-dev.
  document.querySelectorAll('[data-cliente]').forEach(function(el) {
    if (el.dataset.dev === undefined) el.dataset.dev = el.textContent;
    if (!el.classList.contains('loading')) el.textContent = modo === 'cliente' ? el.dataset.cliente : el.dataset.dev;
  });
  // Si la sección actual no existe en esta vista, se vuelve al inicio.
  if (_seccion && !seccionVisible(_seccion)) irASeccion('inicio', { forzar: true });
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
  $('btn-mas-opciones').textContent = abierto ? 'Menos opciones' : 'Más opciones';
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

/* Escritorio: el header queda fijo (ver .header en dashboard.css). Se mide su
   alto para correr lo sticky de abajo, y la barra lateral va del borde de
   arriba que tenga ahora hasta el pie de la pantalla: ni corta ni se sale. */
(function () {
  var pendiente = false;
  function ajustar() {
    pendiente = false;
    var header = document.getElementById('appHeader');
    if (header) document.documentElement.style.setProperty('--header-alto', header.offsetHeight + 'px');
    var barra = document.querySelector('.sidebar');
    if (!barra || window.innerWidth <= 900) return;
    var arriba = Math.max(barra.getBoundingClientRect().top, 20);
    barra.style.setProperty('--sidebar-alto', (window.innerHeight - arriba - 20) + 'px');
  }
  function pedir() { if (!pendiente) { pendiente = true; requestAnimationFrame(ajustar); } }
  window.addEventListener('scroll', pedir, { passive: true });
  window.addEventListener('resize', pedir);
  document.addEventListener('DOMContentLoaded', pedir);
  pedir();
})();
