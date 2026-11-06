/* buscador.js — "Buscar o saltar a…" de la vista Cliente (botón del encabezado, ⌘K / Ctrl+K).
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Una ventana con un campo: sin escribir muestra las secciones para ir directo;
   al escribir filtra las secciones y busca notas por título, tema o texto (la
   misma búsqueda del Historial). Flechas para moverse, Enter para abrir, Esc
   para cerrar. */

var SECCIONES_BUSCADOR = [['inicio', 'Inicio'], ['historial', 'Notas'], ['crear', 'Nueva nota'], ['programacion', 'Programación'],
                          ['fuentes', 'Fuentes'], ['prompts', 'Prompts'], ['corridas', 'Actividad']];
var _bus = { items: [], i: 0, timer: null, pedido: 0 };

function abrirBuscador() {
  var d = $('buscador');
  if (!d || d.open) return;
  d.showModal();
  $('buscador-q').value = '';
  buscarEnBuscador('');
  $('buscador-q').focus();
}

function cerrarBuscador() { if ($('buscador').open) $('buscador').close(); }

function buscarEnBuscador(q) {
  var texto = q.trim(), bajo = texto.toLocaleLowerCase();
  var secciones = SECCIONES_BUSCADOR.filter(function(s) {
    return seccionVisible(s[0]) && (!bajo || tr(s[1]).toLocaleLowerCase().indexOf(bajo) >= 0 || s[1].toLocaleLowerCase().indexOf(bajo) >= 0);
  }).map(function(s) { return { tipo: 'seccion', id: s[0], titulo: tr(s[1]) }; });
  _bus.items = secciones;
  _bus.i = 0;
  _bus.cargando = texto.length >= 2;
  pintarBuscador();
  clearTimeout(_bus.timer);
  if (texto.length < 2) return;
  var n = ++_bus.pedido;
  _bus.timer = setTimeout(async function() {
    var d;
    try { d = await pedir('/api/historial/generados_aprobados?pagina=1&por_pagina=6&estado=todos&q=' + encodeURIComponent(texto)); }
    catch (e) { d = { items: [] }; }
    if (n !== _bus.pedido) return;
    _bus.cargando = false;
    _bus.items = secciones.concat((d.items || []).map(function(it) { return { tipo: 'nota', it: it, titulo: it.titulo }; }));
    pintarBuscador();
  }, 220);
}

function pintarBuscador() {
  var lista = $('buscador-lista'), html = '', grupo = '';
  _bus.items.forEach(function(x, i) {
    var g = x.tipo === 'seccion' ? tr('Ir a') : tr('Notas');
    if (g !== grupo) { html += '<p class="buscador-grupo" role="presentation">' + escHtml(g) + '</p>'; grupo = g; }
    var sub = x.tipo === 'nota' ? (NOMBRE_ESTADO_NOTA[x.it.estado] || '') + (x.it.fecha ? ' · ' + fechaCorta(x.it.fecha) : '') : '';
    html += '<button type="button" role="option" id="bus-' + i + '" class="buscador-item" aria-selected="' + (i === _bus.i) + '"'
      + ' onmouseenter="_bus.i=' + i + ';marcarBuscador()" onclick="elegirEnBuscador(' + i + ')">'
      + '<span' + (x.tipo === 'nota' ? ' translate="no"' : '') + '>' + escHtml(x.titulo) + '</span>'
      + (sub ? '<small>' + escHtml(sub) + '</small>' : '') + '</button>';
  });
  if (_bus.cargando) html += '<p class="buscador-vacio">' + escHtml(tr('Buscando notas…')) + '</p>';
  else if (!_bus.items.length) html += '<p class="buscador-vacio">' + escHtml(tr('Sin resultados')) + '</p>';
  lista.innerHTML = html;
  marcarBuscador();
}

function marcarBuscador() {
  document.querySelectorAll('#buscador-lista .buscador-item').forEach(function(b, i) { b.setAttribute('aria-selected', i === _bus.i); });
  var actual = $('bus-' + _bus.i);
  $('buscador-q').setAttribute('aria-activedescendant', actual ? actual.id : '');
  if (actual) actual.scrollIntoView({ block: 'nearest' });
}

function elegirEnBuscador(i) {
  var x = _bus.items[i];
  if (!x) return;
  cerrarBuscador();
  if (x.tipo === 'seccion') irASeccion(x.id);
  else abrirItemHistorial(x.it.seccion, x.it.coleccion, x.it.id);
}

function initBuscador() {
  var q = $('buscador-q'), d = $('buscador');
  if (!q) return;
  // Mac: ⌘K. El resto: Ctrl K.
  if ($('buscador-atajo') && !/Mac|iPhone|iPad/.test(navigator.platform || '')) $('buscador-atajo').textContent = 'Ctrl K';
  q.addEventListener('input', function() { buscarEnBuscador(q.value); });
  q.addEventListener('keydown', function(ev) {
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      var n = _bus.items.length;
      if (n) { _bus.i = (_bus.i + (ev.key === 'ArrowDown' ? 1 : n - 1)) % n; marcarBuscador(); }
    } else if (ev.key === 'Enter') { ev.preventDefault(); elegirEnBuscador(_bus.i); }
  });
  d.addEventListener('click', function(ev) { if (ev.target === d) cerrarBuscador(); });   // clic afuera de la caja
  document.addEventListener('keydown', function(ev) {
    if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && (ev.key || '').toLowerCase() === 'k'
        && document.documentElement.getAttribute('data-modo') === 'cliente' && !$('confirmar').open) {
      ev.preventDefault();
      if ($('modal-art').classList.contains('open')) cerrar();
      abrirBuscador();
    }
  });
}
initBuscador();
