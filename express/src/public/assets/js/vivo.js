/* vivo.js — El dashboard se actualiza solo, sin refrescar la página.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Cada VIVO_MS, con la pestaña visible, se vuelve a pedir lo que se está
   mirando: así aparece lo que cambió otra persona o una tarea de la Cola.
   - Las listas (historial, fuentes, sugerencias, pendientes) se repintan solas
     cuando cambian sus datos.
   - La nota abierta nunca se repinta sola: repintarla en medio de una subida a
     HubSpot, de la vista previa o de una calificación pisaría lo que estás
     haciendo. Si la cambió otro, se avisa con un botón "Actualizar".
     Lo que cambia esta misma pestaña (ver _cambiosPropios en base.js) no se avisa.
   Las Corridas ya se refrescan solas (corridas.js) y los contadores (updateStats).

   ponytail: polling cada 10 s; si hace falta al instante, Server-Sent Events
   con change streams de Mongo. */

var VIVO_MS = 10000;
var VIVO_TIMEOUT_MS = 8000;   // un pedido colgado no frena las vueltas siguientes
var _vivo = { firmas: {}, enCurso: false };

function _vivoPedir(url) {
  var op = window.AbortSignal && AbortSignal.timeout ? { signal: AbortSignal.timeout(VIVO_TIMEOUT_MS) } : undefined;
  return pedir(url, op);
}

// Repinta si los datos son distintos a los de la vez anterior (y la primera vez, por si cambiaron desde que se cargó).
async function _vivoMirar(clave, url, repintar) {
  var datos;
  try { datos = JSON.stringify(await _vivoPedir(url)); } catch (e) { return; }
  if (_vivo.firmas[clave] === datos) return;
  _vivo.firmas[clave] = datos;
  repintar();
}

function _vivoHistorial() {
  var esNotas = _hist.seccion === 'generados_aprobados';
  var url = '/api/historial/' + _hist.seccion + '?pagina=' + _hist.pagina + '&por_pagina=15&q=' + encodeURIComponent(_hist.q)
    + (esNotas ? '&estado=' + _hist.estado : '');
  return _vivoMirar('historial:' + url, url, function() { cargarHistorial(_hist.pagina, true); });
}

async function refrescarVivo() {
  if (document.hidden || _vivo.enCurso) return;
  _vivo.enCurso = true;
  try {
    var pedidos = [_vivoMirar('resumen', '/api/historial/resumen', cargarResumenHistorial)];
    if ($('modal-art').classList.contains('open')) pedidos.push(revisarNotaAbierta());
    if (_seccion === 'historial') pedidos.push(_vivoHistorial());
    if (_seccion === 'fuentes') {
      pedidos.push(_vivoMirar('fuentes', '/api/trusted-urls', loadTrustedUrls),
                   _vivoMirar('sugerencias', '/api/suggested-urls', loadSugerencias));
    }
    await Promise.all(pedidos);
  } finally { _vivo.enCurso = false; }
}

/* ── Nota abierta ── */

async function revisarNotaAbierta() {
  if (!_recorrido.activo || !_notaActual || _notaActual.coleccion !== 'notas_fase2') return;
  if (_cambiosPropios.enCurso) return;   // algo tuyo está en camino: se mira en la próxima vuelta
  var id = _notaActual.id, cambiosAntes = _cambiosPropios.total, d;
  try { d = await _vivoPedir('/api/fase2/notas/' + id); } catch (e) { return; }
  if (!_notaActual || _notaActual.id !== id || !_recorrido.activo) return;   // se cerró o se abrió otra
  var firma = JSON.stringify(d.nota);
  var propio = _cambiosPropios.total !== _recorrido.cambiosVistos || _cambiosPropios.total !== cambiosAntes || _cambiosPropios.enCurso;
  _recorrido.cambiosVistos = _cambiosPropios.total;
  if (propio) {
    // Lo cambiaste vos desde esta pestaña: es la nueva base, sin aviso.
    // ponytail: si otra persona cambia la nota en esos mismos segundos, ese cambio no se avisa.
    _recorrido.firma = firma;
    return;
  }
  var aviso = $('nota-cambio');
  if (firma === _recorrido.firma) { if (aviso) aviso.remove(); return; }
  _recorrido.pendiente = d.nota;
  if (aviso) return;
  aviso = document.createElement('div');
  aviso.id = 'nota-cambio';
  aviso.className = 'nota-cambio';
  aviso.setAttribute('role', 'status');
  aviso.innerHTML = '<span>Esta nota cambió mientras la mirabas.</span>'
    + '<button type="button" class="btn btn-xs" onclick="aplicarNotaNueva(_recorrido.pendiente)">Actualizar</button>';
  $('art-body').prepend(aviso);
}

// Repinta la nota con los datos nuevos, en el mismo paso y con el mismo scroll. Solo a pedido (botón del aviso).
async function aplicarNotaNueva(nota) {
  if (!nota || !_notaActual || _notaActual.id !== nota._id) return;
  if (($('editor-nota') || _cal.tocada) && !(await confirmar({
        titulo: '¿Actualizar la nota?', mensaje: 'Se pierden los cambios que estás editando.',
        accion: 'Actualizar', cancelar: 'Seguir editando' }))) return;
  if (!_notaActual || _notaActual.id !== nota._id) return;
  var cuerpo = $('art-body'), scroll = cuerpo.scrollTop, paso = _recorrido.paso;
  var panel = $('paso-' + paso), scrollPanel = panel ? panel.scrollTop : 0;
  var evaluacion = $('recorrido-evaluacion');   // los criterios se cargan aparte: se conservan
  Object.assign(_notaActual, { estado: nota.estado || 'borrador', contenido: nota.contenido, hubspot: nota.hubspot || null,
                               idioma: nota.idioma || null, traducciones: nota.traducciones || {} });
  $('modal-titulo').textContent = tituloDeNota(nota.contenido) || 'Nota';
  pintarCuerpoNota();
  cuerpo.scrollTop = scroll;
  armarRecorrido(nota, $('check-list'));
  _recorrido.firma = JSON.stringify(nota);
  _recorrido.cambiosVistos = _cambiosPropios.total;
  var hueco = $('recorrido-evaluacion');
  if (evaluacion && hueco) hueco.replaceWith(evaluacion);
  irAPaso(paso, { sinFoco: true, sinVista: true });
  panel = $('paso-' + paso);
  if (panel) panel.scrollTop = scrollPanel;
}

function initVivo() {
  setInterval(refrescarVivo, VIVO_MS);
  // Al volver a la pestaña se actualiza en el momento, sin esperar al próximo turno.
  document.addEventListener('visibilitychange', function() { if (!document.hidden) refrescarVivo(); });
}
