/* corridas.js — Cola de Actividad y botones que encolan.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   COLA DE CORRIDAS
   Encolar devuelve un id; el log se lee por polling (?desde=N), así
   ninguna request queda abierta mientras la Corrida espera o corre.
   ═══════════════════════════════════════════════════════════════════════ */
var TERMINALES = ['ok', 'error', 'cancelada', 'interrumpida'];
var NOMBRE_ESTADO = {
  pendiente: 'En espera', en_curso: 'Corriendo', ok: 'Terminó bien', error: 'Con error',
  cancelada: 'Cancelada', interrumpida: 'Interrumpida'
};
var _corridasActivas = 0;

function esperar(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }

/* Encola en `ruta` y sigue la Corrida hasta que termina.
   onLinea(texto) por cada línea nueva del log; onEstado(d) cuando cambia
   el estado o la posición en la cola; onEncolada(id) apenas se encola (para
   poder cancelarla). Devuelve el estado final. */
async function correrEnCola(ruta, body, onLinea, onEstado, onEncolada) {
  var enc = await pedir(ruta, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})
  });
  if (onEncolada) onEncolada(enc.id);
  refrescarCorridas();
  var desde = 0, previo = '', fallos = 0;
  while (true) {
    var d;
    try {
      d = await pedir('/api/corridas/' + enc.id + '/log?desde=' + desde);
      fallos = 0;
    } catch (e) {
      if (++fallos >= 5) throw e;   // el server reinició o se cortó la red
      await esperar(3000);
      continue;
    }
    d.lineas.forEach(function(l) { if (l) onLinea(l); });
    desde = d.siguiente;
    var clave = d.estado + ':' + (d.posicion || '');
    if (clave !== previo) { previo = clave; if (onEstado) onEstado(d); }
    if (TERMINALES.indexOf(d.estado) >= 0) { refrescarCorridas(); return d; }
    await esperar(d.estado === 'pendiente' ? 3000 : 1500);
  }
}

function textoEnCola(d) {
  return d.estado === 'pendiente' ? 'En cola (#' + d.posicion + ')…' : null;
}

function hace(iso) {
  if (!iso) return '';
  var s = Math.max(0, Math.round((Date.now() - new Date(iso)) / 1000));
  if (s < 60) return 'hace ' + s + ' s';
  if (s < 3600) return 'hace ' + Math.round(s / 60) + ' min';
  if (s < 86400) return 'hace ' + Math.round(s / 3600) + ' h';
  return new Date(iso).toLocaleDateString(localeUI(), { day: 'numeric', month: 'short' });
}

function duracion(a, b) {
  if (!a || !b) return '';
  var s = Math.round((new Date(b) - new Date(a)) / 1000);
  return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + (s % 60) + ' s';
}

function filaCorrida(c, extra) {
  var origen = c.origen === 'cron' ? 'automática' : 'manual';
  return '<div class="corrida">'
    + '<div class="corrida-info"><div class="corrida-nombre">' + escHtml(c.etiqueta) + '</div>'
    + '<div class="corrida-meta">' + origen + ' · ' + escHtml(extra || '')
    + (c.equipo ? ' · <span title="Servidor que la corrió">' + escHtml(c.equipo) + '</span>' : '') + '</div>'
    + (c.error ? '<div class="corrida-meta" style="color:var(--err)">' + escHtml(c.error) + '</div>' : '')
    + '</div>'
    + '<span class="estado-chip ' + c.estado + '">' + NOMBRE_ESTADO[c.estado] + '</span>'
    + (c.estado === 'pendiente' || c.estado === 'en_curso'
        ? '<button class="btn btn-xs" onclick="cancelarCorrida(\'' + c.id + '\', this)">Cancelar</button>' : '')
    + '</div>';
}

var _logActual = { id: null, desde: 0 };
var _dockLog = { id: null, desde: 0, lineas: [] };
var _leyendoCorridas = false;

async function pintarActividad(d) {
  document.body.classList.toggle('trabajando', !!d.en_curso);
  var c = d.en_curso || d.pendientes[0];
  $('inicio-actividad').textContent = c ? c.etiqueta + ' · ' + NOMBRE_ESTADO[c.estado] : 'Todo al día. No hay tareas en curso.';
  $('inicio-actividad').dataset.estado = c ? c.estado : 'ok';
  $('inicio-recientes').innerHTML = d.recientes.slice(0, 3).map(function(it) {
    return filaCorrida(it, hace(it.fin));
  }).join('') || '<p class="corridas-vacio">Las tareas terminadas aparecerán acá.</p>';
  if (!c && _dockLog.id) c = d.recientes.find(function(it) { return it.id === _dockLog.id; });
  var dock = $('actividad-dock');
  pintarColaTerminal(d);
  if (!c || c.id === _term.cerrada) { dock.hidden = true; return; }
  if (_dockLog.id !== c.id) {
    // Una tarea nueva: la terminal se abre con su registro.
    _dockLog = { id: c.id, desde: 0, lineas: [] };
    abrirTerminal(true);
  }
  dock.hidden = false;
  dock.dataset.estado = c.estado;
  $('actividad-titulo').textContent = c.etiqueta + ' · ' + NOMBRE_ESTADO[c.estado];
  try {
    var lg = await pedir('/api/corridas/' + c.id + '/log?desde=' + _dockLog.desde);
    _dockLog.desde = lg.siguiente;
    _dockLog.lineas = _dockLog.lineas.concat(lg.lineas).slice(-500);
    var pre = $('actividad-log');
    var abajo = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
    pre.innerHTML = _dockLog.lineas.map(lineaTerminal).join('\n');
    if (abajo) pre.scrollTop = pre.scrollHeight;
    $('actividad-paso').textContent = c.estado === 'pendiente' ? 'Esperando su turno en la cola.'
      : TERMINALES.includes(c.estado) ? (c.error || 'La tarea finalizó. Podés consultar el registro.')
      : pasoGeneracion(_dockLog.lineas.at(-1) || '') || 'Procesando. El registro se actualiza automáticamente.';
  } catch(e) { $('actividad-paso').textContent = 'No se pudo actualizar el registro. Reintentando…'; }
}

/* ═══════════════════════════════════════════════════════════════════════
   TERMINAL: el panel de abajo, como el de VS Code. En escritorio ocupa una
   fila propia debajo del contenido (el contenido se achica y scrollea, nada
   queda encimado); en el celular flota abajo. El alto se cambia arrastrando
   el borde de arriba (o con las flechas, con el borde enfocado) y se recuerda.
   ═══════════════════════════════════════════════════════════════════════ */
var TERMINAL_ALTO = 240, TERMINAL_MIN = 120;
var _term = { alto: TERMINAL_ALTO, max: false, cerrada: null };
try { _term.alto = Math.max(TERMINAL_MIN, parseInt(localStorage.getItem('ad-terminal-alto'), 10) || TERMINAL_ALTO); } catch (e) {}

// Una línea del registro, con color según su marca: [OK], [ERROR], [AVISO]...
function lineaTerminal(l) {
  var clase = /\[(ERROR|FALLA)\]|Traceback|Error:/i.test(l) ? 'err'
    : /\[(AVISO|WARN|CANCELADA)\]/i.test(l) ? 'aviso'
    : /\[OK\]|^>>>/.test(l) ? 'ok'
    : /^\s*\[(TOKENS|COSTO|DB|MODO PAGO)\]/.test(l) ? 'tenue' : '';
  return clase ? '<span class="t-' + clase + '">' + escHtml(l) + '</span>' : escHtml(l);
}

function altoMaximoTerminal() {
  var layout = document.querySelector('.layout');
  var disponible = layout && window.matchMedia('(min-width: 901px)').matches ? layout.getBoundingClientRect().height : window.innerHeight;
  return Math.max(TERMINAL_MIN, Math.round(disponible - 160));
}

function aplicarAltoTerminal() {
  var alto = _term.max ? altoMaximoTerminal() : Math.min(_term.alto, altoMaximoTerminal());
  var dock = $('actividad-dock');
  dock.style.setProperty('--terminal-alto', alto + 'px');
  var borde = $('terminal-borde');
  borde.setAttribute('aria-valuenow', alto);
  borde.setAttribute('aria-valuemin', TERMINAL_MIN);
  borde.setAttribute('aria-valuemax', altoMaximoTerminal());
  $('terminal-maximizar').setAttribute('aria-pressed', _term.max ? 'true' : 'false');
  $('terminal-maximizar').title = _term.max ? 'Restaurar el tamaño' : 'Maximizar';
  dock.classList.toggle('maximizada', _term.max);
}

function abrirTerminal(si) {
  var dock = $('actividad-dock');
  if (si) dock.setAttribute('data-abierta', ''); else dock.removeAttribute('data-abierta');
  $('terminal-plegar').setAttribute('aria-expanded', si ? 'true' : 'false');
  $('terminal-plegar').title = si ? 'Ocultar el panel' : 'Mostrar el panel';
  aplicarAltoTerminal();
}
function plegarTerminal() { abrirTerminal(!$('actividad-dock').hasAttribute('data-abierta')); }
function maximizarTerminal() { _term.max = !_term.max; abrirTerminal(true); }
// Cerrar la oculta hasta que empiece otra tarea.
function cerrarTerminal() { _term.cerrada = _dockLog.id; $('actividad-dock').hidden = true; }

function verPestanaTerminal(vista) {
  document.querySelectorAll('.terminal-pestana').forEach(function(b) {
    b.setAttribute('aria-selected', b.dataset.vista === vista ? 'true' : 'false');
  });
  $('actividad-log').hidden = vista !== 'registro';
  $('terminal-cola').hidden = vista !== 'cola';
  abrirTerminal(true);
}

function pintarColaTerminal(d) {
  var filas = (d.en_curso ? [d.en_curso] : []).concat(d.pendientes || []);
  $('terminal-cuenta').textContent = filas.length ? filas.length : '';
  $('terminal-cola').innerHTML = filas.length ? filas.map(function(c, i) {
    return '<div class="terminal-fila"><span class="terminal-fila-n">' + (c.estado === 'en_curso' ? '▶' : i) + '</span>'
      + '<span class="terminal-fila-nombre">' + escHtml(c.etiqueta) + '</span>'
      + '<span class="estado-chip ' + c.estado + '">' + NOMBRE_ESTADO[c.estado] + '</span></div>';
  }).join('') : '<p class="terminal-vacio">No hay nada corriendo ni esperando.</p>';
}

function initTerminal() {
  var dock = $('actividad-dock'), borde = $('terminal-borde');
  document.querySelectorAll('.terminal-pestana').forEach(function(b) {
    b.addEventListener('click', function() { verPestanaTerminal(b.dataset.vista); });
  });
  function guardar() { try { localStorage.setItem('ad-terminal-alto', String(_term.alto)); } catch (e) {} }
  borde.addEventListener('pointerdown', function(ev) {
    if (ev.button !== 0) return;
    ev.preventDefault();
    // Plegada, arrastrar hacia arriba la abre desde cero.
    var y0 = ev.clientY;
    var alto0 = dock.hasAttribute('data-abierta') ? parseInt(dock.style.getPropertyValue('--terminal-alto'), 10) || _term.alto : 0;
    borde.setPointerCapture(ev.pointerId);
    document.body.classList.add('arrastrando-terminal');
    function mover(e) {
      _term.max = false;
      _term.alto = Math.max(TERMINAL_MIN, Math.min(altoMaximoTerminal(), Math.round(alto0 + (y0 - e.clientY))));
      abrirTerminal(true);
    }
    function soltar() {
      borde.removeEventListener('pointermove', mover);
      document.body.classList.remove('arrastrando-terminal');
      guardar();
    }
    borde.addEventListener('pointermove', mover);
    borde.addEventListener('pointerup', soltar, { once: true });
    borde.addEventListener('pointercancel', soltar, { once: true });
  });
  // Doble clic en el borde: vuelve al alto de siempre.
  borde.addEventListener('dblclick', function() { _term.alto = TERMINAL_ALTO; _term.max = false; abrirTerminal(true); guardar(); });
  borde.addEventListener('keydown', function(ev) {
    var paso = ev.shiftKey ? 80 : 24;
    if (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown') return;
    ev.preventDefault();
    _term.max = false;
    _term.alto = Math.max(TERMINAL_MIN, Math.min(altoMaximoTerminal(), _term.alto + (ev.key === 'ArrowUp' ? paso : -paso)));
    abrirTerminal(true);
    guardar();
  });
  window.addEventListener('resize', aplicarAltoTerminal);
  // En el celular la terminal flota abajo: se reserva su alto para que no tape Guardar/Descartar.
  new ResizeObserver(function() {
    var flota = !window.matchMedia('(min-width: 901px)').matches && !dock.hidden;
    document.body.style.setProperty('--dock-height', flota ? Math.ceil(dock.getBoundingClientRect().height) + 'px' : '0px');
  }).observe(dock);
  aplicarAltoTerminal();
}

async function refrescarCorridas() {
  if (_leyendoCorridas) return;
  _leyendoCorridas = true;
  try { await actualizarCorridas(); }
  finally { _leyendoCorridas = false; }
}

async function actualizarCorridas() {
  var d;
  try { d = await pedir('/api/corridas'); } catch (e) { return; }
  _corridasActivas = (d.en_curso ? 1 : 0) + d.pendientes.length;
  $('nav-badge-corridas').textContent = _corridasActivas || '';
  await pintarActividad(d);
  if (_seccion !== 'corridas') return;

  var actual = $('corrida-actual');
  if (!d.en_curso) {
    // Se pinta una sola vez: repintar en cada consulta le saca el foco a los botones.
    if (!actual.querySelector('.corridas-reposo')) actual.innerHTML = '<div class="corridas-vacio corridas-reposo"><strong>Sistema en reposo</strong>'
      + '<span>No está corriendo nada.<span class="reposo-extra"> Las búsquedas y notas programadas arrancan solas; también podés pedir una ahora.</span></span>'
      + '<span class="corridas-vacio-acciones"><button class="btn btn-sm btn-primary" onclick="irASeccion(\'crear\')">Crear una nota</button>'
      + '<button class="btn btn-sm" onclick="irASeccion(\'programacion\')">Ver programación</button></span></div>';
    _logActual = { id: null, desde: 0 };
  } else {
    var c = d.en_curso;
    if (_logActual.id !== c.id) {
      actual.innerHTML = '<div class="corrida-actual">' + filaCorrida(c, 'empezó ' + hace(c.inicio))
        + '<pre class="corrida-log" id="corrida-log" aria-live="off"></pre></div>';
      _logActual = { id: c.id, desde: 0 };
    } else {
      actual.querySelector('.corrida-meta').textContent =
        (c.origen === 'cron' ? 'automática' : 'manual') + ' · empezó ' + hace(c.inicio);
    }
    try {
      var lg = await pedir('/api/corridas/' + c.id + '/log?desde=' + _logActual.desde);
      var pre = $('corrida-log');
      if (pre && lg.lineas.length) {
        var abajo = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
        pre.textContent += lg.lineas.join('\n') + '\n';
        if (abajo) pre.scrollTop = pre.scrollHeight;
      }
      _logActual.desde = lg.siguiente;
    } catch (e) {}
  }

  $('corridas-pendientes').innerHTML = d.pendientes.length
    ? d.pendientes.map(function(c, i) { return filaCorrida(c, '#' + (i + 1) + ' en la cola · pedida ' + hace(c.creada)); }).join('')
    : '<p class="corridas-vacio">No hay nada esperando.</p>';
  $('corridas-recientes').innerHTML = d.recientes.length
    ? d.recientes.map(function(c) {
        var dur = duracion(c.inicio, c.fin);
        return filaCorrida(c, hace(c.fin) + (dur ? ' · duró ' + dur : ''));
      }).join('')
    : '<p class="corridas-vacio">Todavía no corrió nada.</p>';
}

async function cancelarCorrida(id, btn) {
  var ok = await confirmar({
    titulo: '¿Cancelar esta tarea?',
    mensaje: 'Si todavía no empezó, no va a correr. Si ya está corriendo, se corta y lo que haya llegado a guardar queda guardado.',
    accion: 'Cancelar tarea',
    cancelar: 'Volver'
  });
  if (!ok) return;
  btn.disabled = true;
  try {
    var r = await pedir('/api/corridas/' + id + '/cancelar', { method: 'POST' });
    // "cancelando": se pidió el corte y la fila pasa a "Cancelada" cuando termina de verdad.
    if (r.estado === 'cancelada') showToast('Tarea cancelada', 'success');
    else if (r.estado === 'cancelando') showToast('Cancelando… se corta en unos segundos.', 'info');
    else showToast('No se pudo cancelar: la tarea ya terminó.', 'warn');
  } catch (e) {
    btn.disabled = false;
    showToast(e.message, 'error');
  }
  refrescarCorridas();
}

function initCorridas() {
  initTerminal();
  var tick = 0;
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'corridas') refrescarCorridas(); });
  setInterval(function() {
    tick++;
    // Mirando la sección o con algo corriendo: cada 3 s. Si no, cada 30 s (solo el contador).
    if (_seccion === 'corridas' || _corridasActivas || tick % 10 === 0) refrescarCorridas();
  }, 3000);
  refrescarCorridas();
}

/* ═══════════════════════════════════════════════════════════════════════
   RUN NOW (por la cola)
   ═══════════════════════════════════════════════════════════════════════ */
async function runNowStream() {
  var botones = [$('btn-runnow'), $('btn-f2-scrapear')].filter(Boolean);
  var textos = botones.map(function(b) { return b.textContent; });
  botones.forEach(function(b) { b.disabled = true; b.textContent = 'Scrapeando...'; });
  log('--- INICIANDO SCRAPING MANUAL ---', 'warn');
  marcarHeaderActivo();
  var extraidos = 0, aprobados = 0, errores = 0;
  try {
    var fin = await correrEnCola('/api/corridas/scraping', null, function(l) {
      var m;
      if ((m = l.match(/Total art[ií]culos extra[ií]dos:\s*(\d+)/i))) extraidos += +m[1];
      if ((m = l.match(/(\d+) nuevos art[ií]culos aprobados/i))) aprobados += +m[1];
      if (l.indexOf('[ERROR]') >= 0) errores++;
      var type = l.indexOf('[OK]') >= 0 ? 'success'
               : (l.indexOf('[ERROR]') >= 0 || l.indexOf('[FAIL]') >= 0) ? 'error'
               : (l.indexOf('[WARN]') >= 0 || l.indexOf('SIN RESPUESTA') >= 0) ? 'warn' : 'info';
      log(l, type);
    }, function(d) {
      var t = textoEnCola(d);
      botones.forEach(function(b) { b.textContent = t || 'Scrapeando...'; });
      if (t) log('Hay otra tarea en curso: el scraping quedó en cola (#' + d.posicion + ').', 'warn');
    });

    var estado, msg;
    if (fin.estado === 'cancelada') {
      estado = 'warn'; msg = 'El scraping se canceló.';
    } else if (aprobados > 0) {
      estado = 'ok'; msg = aprobados + (aprobados === 1 ? ' artículo nuevo guardado.' : ' artículos nuevos guardados.');
    } else if (extraidos > 0) {
      estado = 'warn'; msg = 'Se leyeron ' + extraidos + ' artículos pero ninguno nuevo pasó la clasificación.';
    } else {
      estado = errores ? 'err' : 'warn';
      msg = 'No se pudieron obtener artículos de las fuentes. Revisá la consola.';
    }
    log('--- SCRAPING FINALIZADO: ' + msg + ' ---', estado === 'ok' ? 'success' : estado === 'warn' ? 'warn' : 'error');
    showToast(msg, estado === 'ok' ? 'success' : estado === 'warn' ? 'warn' : 'error');
  } catch(e) {
    log('Error en scraping: ' + e.message, 'error');
    showToast(e.message, 'error');
  } finally {
    hidePipelineHeader();
    botones.forEach(function(b, i) { b.disabled = false; b.textContent = textos[i]; });
    updateStats();
    loadTrustedUrls();
    cargarAgenda('scraping');
  }
}
