/* animaciones.js — Movimiento del dashboard.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Las animaciones siguen lo que de verdad está pasando: los pasos de la nota
   se encienden con las líneas del log, el encabezado y "Corridas" se mueven
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
  /nota guardada/i,
];
var _pasoNota = -1;

function _pintarPasos(actual, final) {
  document.querySelectorAll('#f2-pasos li').forEach(function(li, i) {
    li.classList.toggle('hecho', i < actual || (final === 'ok' && i <= actual));
    li.classList.toggle('actual', i === actual && !final);
    li.classList.toggle('fallo', i === actual && final === 'error');
  });
}

function iniciarPasosNota() {
  var ol = $('f2-pasos');
  if (!ol) return;
  _pasoNota = 0;
  ol.hidden = false;
  ol.classList.remove('terminado');
  _pintarPasos(0, null);
}

function marcarPasoNota(linea) {
  for (var i = PASOS_NOTA.length - 1; i >= 0; i--) {
    // Solo avanza: una reescritura vuelve a "Revisión", no a "Redacción".
    if (PASOS_NOTA[i].test(linea) && i > _pasoNota) { _pasoNota = i; _pintarPasos(i, null); return; }
  }
}

function terminarPasosNota(exito) {
  var ol = $('f2-pasos');
  if (!ol || _pasoNota < 0) return;
  if (exito) _pasoNota = PASOS_NOTA.length - 1;
  _pintarPasos(_pasoNota, exito ? 'ok' : 'error');
  ol.classList.add('terminado');
  _pasoNota = -1;
}

/* ── Números que cuentan hasta su valor ──────────────────────────────── */
// Lee el número del primer texto del elemento (formato es-AR: 1.234,5) y lo anima desde 0.
function contarHasta(el, duracion) {
  var nodo = el && Array.prototype.find.call(el.childNodes, function(n) { return n.nodeType === 3 && /\d/.test(n.nodeValue); });
  if (!nodo) return;
  var original = nodo.nodeValue;
  var m = original.match(/[\d.]+(,\d+)?/);
  if (!m) return;
  var objetivo = parseFloat(m[0].replace(/\./g, '').replace(',', '.'));
  var decimales = m[1] ? m[1].length - 1 : 0;
  if (!isFinite(objetivo) || objetivo === 0) return;
  var formato = new Intl.NumberFormat('es-AR', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  var inicio = null;
  duracion = duracion || 900;
  function paso(t) {
    if (inicio === null) inicio = t;
    var p = Math.min((t - inicio) / duracion, 1), e = 1 - Math.pow(1 - p, 3);
    nodo.nodeValue = original.replace(m[0], formato.format(objetivo * e));
    if (p < 1) requestAnimationFrame(paso); else nodo.nodeValue = original;
  }
  requestAnimationFrame(paso);
}

/* ── Entrada escalonada de las tarjetas de cada sección ──────────────── */
var TARJETAS = '.tablero-card, .stat-card, .inicio-panel, .hero-cliente, .agenda-card, .fuentes-panel,'
  + ' .corridas-bloque, .fase2-grupo, .hist-item, .kpi';

function entradaEscalonada(seccion) {
  document.querySelectorAll('.contenido > [data-seccion="' + seccion + '"]').forEach(function(bloque) {
    bloque.querySelectorAll(TARJETAS).forEach(function(el, i) {
      el.classList.remove('entra');
      void el.offsetWidth;   // reinicia la animación si la sección se vuelve a abrir
      el.style.setProperty('--i', Math.min(i, 12));
      el.classList.add('entra');
    });
  });
}

document.addEventListener('seccion', function(ev) { entradaEscalonada(ev.detail); });
