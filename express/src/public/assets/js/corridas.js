/* corridas.js — Cola de Corridas y botones que encolan.
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
   el estado o la posición en la cola. Devuelve el estado final. */
async function correrEnCola(ruta, body, onLinea, onEstado) {
  var enc = await pedir(ruta, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})
  });
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
  return new Date(iso).toLocaleDateString('es-AR', { day: 'numeric', month: 'short' });
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
    + '<div class="corrida-meta">' + origen + ' · ' + escHtml(extra || '') + '</div>'
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
  var c = d.en_curso || d.pendientes[0];
  $('inicio-actividad').textContent = c ? c.etiqueta + ' · ' + NOMBRE_ESTADO[c.estado] : 'Todo al día. No hay tareas en curso.';
  $('inicio-recientes').innerHTML = d.recientes.slice(0, 3).map(function(it) {
    return filaCorrida(it, hace(it.fin));
  }).join('') || '<p class="corridas-vacio">Las tareas terminadas aparecerán acá.</p>';
  if (!c && _dockLog.id) c = d.recientes.find(function(it) { return it.id === _dockLog.id; });
  var dock = $('actividad-dock');
  if (!c) { dock.hidden = true; return; }
  if (_dockLog.id !== c.id) {
    _dockLog = { id: c.id, desde: 0, lineas: [] };
    dock.open = true;
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
    pre.textContent = _dockLog.lineas.join('\n');
    if (abajo) pre.scrollTop = pre.scrollHeight;
    $('actividad-paso').textContent = c.estado === 'pendiente' ? 'Esperando su turno en la cola.'
      : TERMINALES.includes(c.estado) ? (c.error || 'La tarea finalizó. Podés consultar el registro.')
      : pasoGeneracion(_dockLog.lineas.at(-1) || '') || 'Procesando. El registro se actualiza automáticamente.';
  } catch(e) { $('actividad-paso').textContent = 'No se pudo actualizar el registro. Reintentando…'; }
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
    actual.innerHTML = '<p class="corridas-vacio">No está corriendo nada.</p>';
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
    titulo: '¿Cancelar esta corrida?',
    mensaje: 'Si todavía no empezó, no va a correr. Si ya está corriendo, se corta y lo que haya llegado a guardar queda guardado.',
    accion: 'Cancelar corrida',
    cancelar: 'Volver'
  });
  if (!ok) return;
  btn.disabled = true;
  try {
    await pedir('/api/corridas/' + id + '/cancelar', { method: 'POST' });
    showToast('Corrida cancelada', 'success');
  } catch (e) {
    btn.disabled = false;
    showToast(e.message, 'error');
  }
  refrescarCorridas();
}

function initCorridas() {
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
  showPipeline();
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
      advancePipeline(l);
    }, function(d) {
      var t = textoEnCola(d);
      botones.forEach(function(b) { b.textContent = t || 'Scrapeando...'; });
      if (t) log('Hay otra corrida en curso: el scraping quedó en cola (#' + d.posicion + ').', 'warn');
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
    finishPipeline(estado, msg);
    log('--- SCRAPING FINALIZADO: ' + msg + ' ---', estado === 'ok' ? 'success' : estado === 'warn' ? 'warn' : 'error');
    showToast(msg, estado === 'ok' ? 'success' : estado === 'warn' ? 'warn' : 'error');
  } catch(e) {
    finishPipeline('err', e.message);
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
