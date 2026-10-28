/* animaciones.js — Movimiento del dashboard.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Las animaciones siguen lo que de verdad está pasando: los pasos de la nota
   se encienden con las líneas del log, el encabezado y "Actividad" se mueven
   solo con una corrida en curso (body.trabajando, ver corridas.js) y los
   números del tablero cuentan hasta su valor real. Con "reducir movimiento"
   activado en el sistema, el CSS las apaga todas. */

/* ── Pasos de la nota (Crear nota) ───────────────────────────────────── */
// Mismo orden que el <ol id="f2-pasos">: cada línea del log que coincide marca su paso.
var PASOS_NOTA = [
  /noticias de contexto/i,
  /few-shot|ejemplo\(s\) cargado/i,
  /planificando|plan de la nota/i,
  /generando nota|^\s*\[\d+s\]|generaci[oó]n completa/i,
  /verificando los datos/i,
  /evaluando calidad|corrigiendo la nota|reescribiendo la nota/i,
  /generando la imagen destacada/i,
  /nota guardada/i,
];
var _pasoNota = -1;

function _pintarPasos(actual, final) {
  document.querySelectorAll('#f2-pasos li').forEach(function(li, i) {
    li.classList.toggle('hecho', i < actual || (final === 'ok' && i <= actual));
    li.classList.toggle('actual', i === actual && !final);
    if (i === actual && !final) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    li.classList.toggle('fallo', i === actual && final === 'error');
  });
}

function iniciarPasosNota() {
  var ol = $('f2-pasos');
  if (!ol) return;
  _pasoNota = 0;
  ol.hidden = false;
  ol.classList.remove('terminado');
  ol.children[6].hidden = true; // La imagen es opcional: no simular un paso que no ocurrió.
  _pintarPasos(0, null);
}

function marcarPasoNota(linea) {
  if (PASOS_NOTA[6].test(linea)) $('f2-pasos').children[6].hidden = false;
  for (var i = PASOS_NOTA.length - 1; i >= 0; i--) {
    // Solo avanza: una reescritura vuelve a "Revisión", no a "Redacción".
    if (PASOS_NOTA[i].test(linea) && i > _pasoNota) { _pasoNota = i; _pintarPasos(i, null); return; }
  }
}

function terminarPasosNota(exito, cancelada) {
  var ol = $('f2-pasos');
  if (!ol || _pasoNota < 0) return;
  if (exito) _pasoNota = PASOS_NOTA.length - 1;
  _pintarPasos(_pasoNota, exito ? 'ok' : cancelada ? 'cancelada' : 'error');
  ol.classList.add('terminado');
  _pasoNota = -1;
}

/* ── Actualización sutil de los valores reales ───────────────────────── */
function contarHasta(el) {
  // Destaca el cambio sin inventar valores intermedios.
  if (!el || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  el.animate([{opacity:0.45}, {opacity:1}], {duration:320, easing:'ease-out'});
}

/* ── Entrada escalonada de las tarjetas de cada sección ──────────────── */
var TARJETAS = '.tablero-card, .stat-card, .inicio-panel, .hero-cliente, .agenda-card, .fuentes-panel,'
  + ' .corridas-bloque, .fase2-grupo, .hist-item, .kpi, .indicador';

function entradaEscalonada(seccion) {
  document.querySelectorAll('.contenido > [data-seccion="' + seccion + '"]').forEach(function(bloque) {
    bloque.querySelectorAll(TARJETAS).forEach(function(el, i) {
      el.classList.remove('entra');
      void el.offsetWidth;   // reinicia la animación si la sección se vuelve a abrir
      el.style.setProperty('--i', Math.min(i, 6));
      el.classList.add('entra');
    });
  });
}

document.addEventListener('seccion', function(ev) { entradaEscalonada(ev.detail); });
