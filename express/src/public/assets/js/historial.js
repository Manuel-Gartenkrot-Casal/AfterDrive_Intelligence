/* historial.js — Historial, revisión de notas y HubSpot.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   HISTORIAL
   Cuatro listas (notas y artículos, guardados o descartados) con
   búsqueda y páginas. Abrir una nota permite revisarla: aprobar,
   rechazar, editar o volver a borrador.
   ═══════════════════════════════════════════════════════════════════════ */
var _hist = { seccion: 'generados_aprobados', estado: 'todos', q: '', pagina: 1, timer: null };
var NOMBRE_ESTADO_NOTA = { borrador: 'Para revisar', aprobada: 'Aprobada', publicado: 'Publicada', rechazada: 'Rechazada' };

function initHistorial() {
  document.querySelectorAll('#hist-pestanas .pestana').forEach(function(b) {
    b.onclick = function() { _hist.seccion = b.dataset.hist; cargarHistorial(1); };
  });
  document.querySelectorAll('#hist-estados .chip').forEach(function(b) {
    b.onclick = function() { _hist.estado = b.dataset.estado; cargarHistorial(1); };
  });
  $('hist-q').addEventListener('input', function() {
    clearTimeout(_hist.timer);
    _hist.timer = setTimeout(function() { _hist.q = $('hist-q').value.trim(); cargarHistorial(1); }, 300);
  });
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'historial') cargarHistorial(_hist.pagina); });
  $('hist-pestanas').addEventListener('keydown', function(ev) {
    var tabs = Array.from(this.querySelectorAll('[role="tab"]')), i = tabs.indexOf(document.activeElement);
    if (i < 0 || !['ArrowLeft','ArrowRight','Home','End'].includes(ev.key)) return;
    ev.preventDefault();
    i = ev.key === 'Home' ? 0 : ev.key === 'End' ? tabs.length - 1 : (i + (ev.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[i].focus(); tabs[i].click();
  });
  cargarResumenHistorial();
}

async function cargarResumenHistorial() {
  try {
    var r = await pedir('/api/historial/resumen');
    ['generados_aprobados', 'generados_descartados', 'scrapeados_aprobados', 'scrapeados_descartados'].forEach(function(k) {
      $('hc-' + k).textContent = r[k] ? r[k].total : '';
    });
    var porRevisar = (r.generados_aprobados.por_estado || {}).borrador || 0;
    $('nav-badge-historial').textContent = porRevisar || '';
    $('inicio-pendientes').textContent = porRevisar;
    cargarPendientesInicio();
  } catch (e) {}
}

function fechaCorta(iso) {
  return iso ? new Date(iso).toLocaleString('es-AR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
}

async function cargarHistorial(pagina) {
  _hist.pagina = pagina || 1;
  var esNotas = _hist.seccion === 'generados_aprobados';
  document.querySelectorAll('#hist-pestanas .pestana').forEach(function(b) {
    var on = b.dataset.hist === _hist.seccion;
    b.setAttribute('aria-selected', on);
    b.tabIndex = on ? 0 : -1;
  });
  $('hist-estados').hidden = !esNotas;
  document.querySelectorAll('#hist-estados .chip').forEach(function(b) {
    b.setAttribute('aria-pressed', b.dataset.estado === _hist.estado);
  });
  var lista = $('hist-lista');
  lista.setAttribute('aria-busy', 'true');
  $('hist-paginador').textContent = '';
  lista.innerHTML = '<p class="corridas-vacio">Cargando…</p>';
  var qs = '?pagina=' + _hist.pagina + '&por_pagina=15&q=' + encodeURIComponent(_hist.q)
    + (esNotas ? '&estado=' + _hist.estado : '');
  var d;
  try { d = await pedir('/api/historial/' + _hist.seccion + qs); }
  catch (e) { lista.removeAttribute('aria-busy'); lista.innerHTML = '<p class="corridas-vacio">No se pudo cargar: ' + escHtml(e.message) + '</p>'; return; }

  lista.removeAttribute('aria-busy');
  if (!d.items.length) {
    lista.innerHTML = '<p class="corridas-vacio">' + (_hist.q ? 'No hay resultados para esa búsqueda.' : ({generados_aprobados: 'No hay notas en este estado. Probá otro filtro o creá una nueva nota.', generados_descartados: 'No hay notas descartadas por la evaluación automática.', scrapeados_aprobados: 'Todavía no hay noticias guardadas. Revisá tus fuentes para empezar.', scrapeados_descartados: 'No hay noticias descartadas.'}[_hist.seccion])) + '</p>';
  } else {
    lista.innerHTML = d.items.map(function(it) {
      var lado = '';
      if (it.estado) lado += '<span class="estado-chip ' + it.estado + '">' + NOMBRE_ESTADO_NOTA[it.estado] + '</span>';
      if (it.calidad && it.calidad.puntaje !== null && it.calidad.puntaje !== undefined)
        lado += '<span class="badge-calidad" title="Lineamientos de calidad cumplidos">' + it.calidad.puntaje + '/9</span>';
      return '<button type="button" class="hist-item" onclick="abrirItemHistorial(\'' + it.seccion + '\', \'' + it.coleccion + '\', \'' + it.id + '\')">'
        + '<div class="hist-cuerpo"><div class="hist-titulo">' + escHtml(it.titulo) + '</div>'
        + (it.resumen ? '<div class="hist-resumen">' + escHtml(extractoHistorial(it)) + '</div>' : '')
        + (it.motivo ? '<div class="hist-motivo">Motivo: ' + escHtml(it.motivo) + '</div>' : '')
        + '<div class="hist-meta">' + escHtml(it.origen) + ' · ' + fechaCorta(it.fecha) + '</div></div>'
        + (lado ? '<div class="hist-lado">' + lado + '</div>' : '')
        + '</button>';
    }).join('');
  }
  var pag = $('hist-paginador');
  pag.innerHTML = d.paginas > 1
    ? '<button type="button" class="btn btn-xs" ' + (d.pagina <= 1 ? 'disabled' : '') + ' onclick="cargarHistorial(' + (d.pagina - 1) + ')">Anterior</button>'
      + '<span>Página ' + d.pagina + ' de ' + d.paginas + ' · ' + d.total + ' en total</span>'
      + '<button type="button" class="btn btn-xs" ' + (d.pagina >= d.paginas ? 'disabled' : '') + ' onclick="cargarHistorial(' + (d.pagina + 1) + ')">Siguiente</button>'
    : (d.total ? '<span>' + d.total + ' en total</span>' : '');
}

async function abrirItemHistorial(seccion, coleccion, id) {
  if (coleccion === 'notas_fase2') return fase2MostrarUltima(id);
  var d;
  try { d = await pedir('/api/historial/' + seccion + '/' + coleccion + '/' + id); }
  catch (e) { showToast('No se pudo abrir: ' + e.message, 'error'); return; }
  var it = d.item;
  $('modal-titulo').textContent = it.titulo;
  $('modal-meta').textContent = it.origen + ' · ' + fechaCorta(it.fecha);
  $('check-list').innerHTML = '';
  $('eval-comms').textContent = '';
  var html = '';
  if (it.motivo) html += '<p><strong>Por qué se descartó:</strong> ' + escHtml(it.motivo) + '</p>';
  if (it.url) html += '<p><a href="' + urlSegura(it.url) + '" target="_blank" rel="noopener">Ver el original</a></p>';
  html += seccion.indexOf('generados') === 0
    ? DOMPurify.sanitize(marked.parse(it.contenido || ''))
    : '<p>' + escHtml(it.contenido || '(sin texto guardado)').replace(/\n+/g, '</p><p>') + '</p>';
  $('art-body').innerHTML = html;
  _notaActual = it.estado ? { coleccion: coleccion, id: it.id, estado: it.estado, contenido: it.contenido, hubspot: it.hubspot || null } : null;
  pintarAccionesNota();
  abrirModal();
}

/* ── Revisión de la nota abierta ── */
var _notaActual = null;

function pintarAccionesNota() {
  var cont = $('nota-acciones');
  if (!_notaActual) { cont.innerHTML = ''; return; }
  var e = _notaActual.estado;
  var b = function(estado, texto, primario) {
    return '<button type="button" class="btn btn-xs' + (primario ? ' btn-primary' : '') + '" onclick="cambiarEstadoNota(\'' + estado + '\')">' + texto + '</button>';
  };
  var html = '<span class="estado-chip ' + e + '">' + NOMBRE_ESTADO_NOTA[e] + '</span>';
  if (e === 'borrador') html += b('aprobada', 'Aprobar', true) + b('rechazada', 'Rechazar');
  if (e === 'aprobada') html += b('borrador', 'Volver a revisar');
  if (e === 'rechazada') html += b('borrador', 'Volver a revisar');
  if (e === 'publicado') html += b('aprobada', 'Despublicar');
  if (e !== 'publicado') html += '<button type="button" class="btn btn-xs" onclick="editarNota()">Editar</button>';
  html += '<button type="button" class="btn btn-xs" onclick="vistaPreviaNota()">Vista previa</button>';
  if (_hubspotConfigurado && (e === 'aprobada' || e === 'publicado')) {
    var yaEnviada = _notaActual.hubspot && _notaActual.hubspot.id;
    if (e === 'aprobada') html += '<button type="button" class="btn btn-xs" onclick="enviarAHubspot(false)">'
      + (yaEnviada ? 'Actualizar borrador en HubSpot' : 'Borrador en HubSpot') + '</button>';
    html += '<button type="button" class="btn btn-xs btn-primary" onclick="enviarAHubspot(true)">'
      + (e === 'publicado' && yaEnviada ? 'Actualizar en HubSpot' : 'Publicar en HubSpot') + '</button>';
  }
  if (_notaActual.hubspot && _notaActual.hubspot.url) {
    html += '<a class="btn btn-xs" href="' + urlSegura(_notaActual.hubspot.url) + '" target="_blank" rel="noopener">Ver en HubSpot</a>';
  }
  cont.innerHTML = html;
}

var _hubspotConfigurado = false;
async function cargarEstadoHubspot() {
  try { _hubspotConfigurado = (await pedir('/api/hubspot/estado')).configurado; } catch (e) {}
}

async function enviarAHubspot(publicar) {
  var n = _notaActual;
  if (publicar && !await confirmar({
    titulo: 'Publicar en el blog',
    mensaje: 'La nota queda publicada en el blog de AfterDrive en HubSpot, visible para cualquiera. Si ya estaba, se actualiza con este texto.',
    accion: 'Publicar', peligro: false
  })) return;
  var botones = document.querySelectorAll('#nota-acciones button');
  botones.forEach(function(b) { b.disabled = true; });
  try {
    var d = await pedir('/api/hubspot/enviar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id, publicar: publicar })
    });
    n.estado = d.item.estado;
    n.hubspot = d.item.hubspot;
    showToast(publicar ? 'Publicada en HubSpot' : 'Guardada como borrador en HubSpot', 'success');
    cargarResumenHistorial();
    if (_seccion === 'historial') cargarHistorial(_hist.pagina);
  } catch (e) { showToast(e.message, 'error'); }
  pintarAccionesNota();
}

async function cambiarEstadoNota(estado) {
  var n = _notaActual;
  var motivo = null;
  if (estado === 'aprobada' && n.estado === 'publicado' && n.hubspot && n.hubspot.id && !await confirmar({
    titulo: '¿Despublicar esta nota?', accion: 'Despublicar',
    mensaje: 'Deja de verse en el blog: en HubSpot vuelve a borrador. Acá queda aprobada, lista para publicar de nuevo.'
  })) return;
  if (estado === 'rechazada') {
    motivo = await confirmar({
      titulo: '¿Rechazar esta nota?', accion: 'Rechazar',
      mensaje: 'Queda en el historial como rechazada y no se publica. Las próximas notas van a tener en cuenta el motivo.',
      campo: '¿Qué tiene mal?', placeholder: 'Ej: inventa cifras, suena a folleto, repite la introducción…'
    });
    if (!motivo) return;
  }
  try {
    var d = await pedir('/api/historial/estado', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id, estado: estado, motivo: motivo })
    });
    n.estado = d.item.estado;
    pintarAccionesNota();
    showToast('Nota: ' + NOMBRE_ESTADO_NOTA[n.estado].toLowerCase(), 'success');
    cargarResumenHistorial();
    if (_seccion === 'historial') cargarHistorial(_hist.pagina);
  } catch (e) { showToast(e.message, 'error'); }
}

/* Cómo quedaría el post en el blog: lo mismo que se manda a HubSpot. */
async function vistaPreviaNota() {
  var n = _notaActual, d;
  try { d = await pedir('/api/historial/vista-previa/' + n.coleccion + '/' + n.id); }
  catch (e) { showToast(e.message, 'error'); return; }
  var propia = d.imagen_propia || {};
  $('art-body').innerHTML =
    '<div class="previa">'
    + (d.imagen.url ? '<img class="previa-imagen" src="' + urlSegura(d.imagen.url) + '" alt="' + escHtml(d.imagen.alt || '') + '">'
                    : '<div class="previa-sin-imagen">Sin imagen destacada</div>')
    + '<h1>' + escHtml(d.titulo) + '</h1>'
    + (d.meta ? '<p class="previa-meta">' + escHtml(d.meta) + '</p>' : '<p class="previa-meta aviso">Sin meta description: la nota no termina con una línea en cursiva.</p>')
    + (d.etiquetas.length ? '<div class="previa-etiquetas">' + d.etiquetas.map(function(t) { return '<span>' + escHtml(t) + '</span>'; }).join('') + '</div>' : '')
    + '<div class="previa-url">/' + escHtml(d.slug) + '</div>'
    + '<div class="previa-cuerpo">' + DOMPurify.sanitize(d.html) + '</div>'
    + '</div>'
    + '<fieldset class="previa-form"><legend>Imagen destacada</legend>'
    + '<label class="control-label" for="previa-img-url">URL de la imagen (https)</label>'
    + '<input id="previa-img-url" class="input-field" type="url" placeholder="https://…/imagen.jpg">'
    + '<label class="control-label" for="previa-img-alt">Texto alternativo</label>'
    + '<input id="previa-img-alt" class="input-field" type="text" maxlength="200" placeholder="Qué muestra la imagen">'
    + '<div class="previa-acciones"><button type="button" class="btn btn-xs btn-primary" onclick="guardarImagenNota()">Guardar imagen</button>'
    + (propia.url ? '<button type="button" class="btn btn-xs" onclick="guardarImagenNota(true)">Quitar imagen</button>' : '')
    + '</div></fieldset>';
  $('previa-img-url').value = propia.url || '';
  $('previa-img-alt').value = propia.alt || '';
  $('nota-acciones').innerHTML = '<button type="button" class="btn btn-xs" onclick="cancelarEdicionNota()">Volver al texto</button>';
  $('art-body').scrollTop = 0;
}

async function guardarImagenNota(quitar) {
  var n = _notaActual;
  try {
    await pedir('/api/historial/imagen', {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id,
                             url: quitar ? '' : $('previa-img-url').value.trim(), alt: $('previa-img-alt').value.trim() })
    });
    showToast(quitar ? 'Imagen quitada' : 'Imagen guardada', 'success');
    vistaPreviaNota();
  } catch (e) { showToast(e.message, 'error'); }
}

function editarNota() {
  var n = _notaActual;
  $('art-body').innerHTML = '<label class="control-label" for="editor-nota">Texto de la nota (Markdown)</label>'
    + '<textarea id="editor-nota" class="editor-nota"></textarea>';
  $('editor-nota').value = n.contenido || '';
  $('editor-nota').focus();
  $('nota-acciones').innerHTML = '<button type="button" class="btn btn-xs btn-primary" onclick="guardarEdicionNota()">Guardar texto</button>'
    + '<button type="button" class="btn btn-xs" onclick="cancelarEdicionNota()">Cancelar</button>';
}

function cancelarEdicionNota() {
  $('art-body').innerHTML = DOMPurify.sanitize(marked.parse(_notaActual.contenido || ''));
  pintarAccionesNota();
}

async function guardarEdicionNota() {
  var n = _notaActual;
  try {
    var d = await pedir('/api/historial/contenido', {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id, contenido: $('editor-nota').value })
    });
    n.contenido = d.item.contenido;
    $('modal-titulo').textContent = d.item.titulo;
    cancelarEdicionNota();
    showToast('Texto guardado', 'success');
    if (_seccion === 'historial') cargarHistorial(_hist.pagina);
  } catch (e) { showToast(e.message, 'error'); }
}

function extractoHistorial(it) {
  var texto = (it.resumen || '').trim(), titulo = (it.titulo || '').trim();
  if (titulo && texto.toLocaleLowerCase().startsWith(titulo.toLocaleLowerCase())) texto = texto.slice(titulo.length).trim();
  return texto;
}
function abrirPendientes() {
  _hist.seccion = 'generados_aprobados'; _hist.estado = 'borrador'; _hist.q = ''; $('hist-q').value = '';
  if (_seccion === 'historial') cargarHistorial(1);
  else { _hist.pagina = 1; irASeccion('historial'); }
}
async function cargarPendientesInicio() {
  try {
    var d = await pedir('/api/historial/generados_aprobados?estado=borrador&por_pagina=4&pagina=1');
    $('inicio-lista').innerHTML = d.items.length ? d.items.map(function(it) {
      return '<button class="inicio-nota" onclick="abrirItemHistorial(\'' + it.seccion + '\',\'' + it.coleccion + '\',\'' + it.id + '\')">'
        + '<span>' + escHtml(it.titulo) + '</span><small>' + fechaCorta(it.fecha) + ' · Para revisar</small></button>';
    }).join('') + (d.total > d.items.length
      ? '<button class="btn btn-sm inicio-mas" onclick="abrirPendientes()">Ver las ' + d.total + ' notas pendientes</button>'
      : '<p class="corridas-vacio inicio-fin">No hay más notas para revisar. Las nuevas aparecen acá apenas se generan.</p>')
      : '<p class="corridas-vacio">Estás al día. Las nuevas notas aparecerán acá para revisarlas.</p>';
  } catch(e) { $('inicio-lista').textContent = 'No se pudieron cargar las notas. Podés reintentar desde Historial.'; }
}
