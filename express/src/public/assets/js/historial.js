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
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'historial') { cargarHistorial(_hist.pagina); cargarCalibracion(); } });
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
  return iso ? new Date(iso).toLocaleString(localeUI(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
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
      if (it.calificacion && it.calificacion.puntaje)
        lado += '<span class="badge-estrellas" title="Tu calificación" aria-label="Calificada con ' + it.calificacion.puntaje + ' de 5">' + estrellas(it.calificacion.puntaje) + '</span>';
      return '<button type="button" class="hist-item" onclick="abrirItemHistorial(\'' + it.seccion + '\', \'' + it.coleccion + '\', \'' + it.id + '\')">'
        + '<div class="hist-cuerpo"><div class="hist-titulo" translate="no">' + escHtml(it.titulo) + '</div>'
        + (it.resumen ? '<div class="hist-resumen" translate="no">' + escHtml(extractoHistorial(it)) + '</div>' : '')
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
    ? '<div translate="no">' + DOMPurify.sanitize(marked.parse(it.contenido || '')) + '</div>'
    : (it.contenido ? '<div translate="no"><p>' + escHtml(it.contenido).replace(/\n+/g, '</p><p>') + '</p></div>' : '<p>(sin texto guardado)</p>');
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
  var subible = _hubspotConfigurado && !_notaActual.sinDestino;   // sinDestino: no hay blog en su idioma
  if (e === 'borrador') html += (subible
      ? '<button type="button" class="btn btn-xs btn-primary" onclick="aprobarYSubir()">Aprobar y subir a HubSpot</button>'
      : b('aprobada', 'Aprobar', true)) + b('rechazada', 'Rechazar');
  if (e === 'aprobada') html += b('borrador', 'Volver a revisar');
  if (e === 'rechazada') html += b('borrador', 'Volver a revisar');
  if (e === 'publicado') html += b('aprobada', 'Despublicar');
  if (e !== 'publicado') html += '<button type="button" class="btn btn-xs" onclick="editarNota()">Editar</button>';
  html += '<button type="button" class="btn btn-xs" onclick="vistaPreviaNota()">Vista previa</button>';
  if (subible && (e === 'aprobada' || e === 'publicado')) {
    var yaEnviada = _notaActual.hubspot && _notaActual.hubspot.id;
    if (e === 'aprobada') html += '<button type="button" class="btn btn-xs" onclick="enviarAHubspot(false)">'
      + (yaEnviada ? 'Actualizar borrador en HubSpot' : 'Subir borrador a HubSpot') + '</button>';
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

async function enviarAHubspot(publicar, mensajeOk) {
  var n = _notaActual;
  if (publicar && !await confirmar({
    titulo: 'Publicar en el blog',
    mensaje: 'La nota queda publicada en el blog de AfterDrive en HubSpot, visible para cualquiera. Si ya estaba, se actualiza con este texto.',
    accion: 'Publicar', peligro: false
  })) return false;
  var botones = document.querySelectorAll('#nota-acciones button');
  botones.forEach(function(b) { b.disabled = true; });
  var autor = $('hubspot-autor'), ok = false;
  try {
    var d = await pedir('/api/hubspot/enviar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id, publicar: publicar, autor_id: autor && autor.value ? autor.value : null })
    });
    n.estado = d.item.estado;
    n.hubspot = d.item.hubspot;
    showToast(mensajeOk || (publicar ? 'Publicada en HubSpot' : 'Guardada como borrador en HubSpot'), 'success');
    if (d.item.aviso) showToast(d.item.aviso, 'warn', 8000);
    ok = true;
  } catch (e) { showToast(e.message, 'error'); }
  cargarResumenHistorial();
  if (_seccion === 'historial') cargarHistorial(_hist.pagina);
  pintarAccionesNota();
  return ok;
}

/* Aprobar sube la nota a HubSpot como borrador: el equipo la termina y publica allá.
   Si la subida falla, la nota queda aprobada y "Subir borrador a HubSpot" reintenta. */
async function aprobarYSubir() {
  // Sin esto, un doble clic llega dos veces a /api/hubspot/enviar antes de que
  // exista el post y crea dos.
  document.querySelectorAll('#nota-acciones button').forEach(function(b) { b.disabled = true; });
  if (!await cambiarEstadoNota('aprobada', true)) { pintarAccionesNota(); return; }
  if (!await enviarAHubspot(false, 'Nota aprobada y subida a HubSpot como borrador')) {
    showToast('La nota quedó aprobada. Reintentá con «Subir borrador a HubSpot».', 'warn', 8000);
  }
}

/* Bloque de la revisión: a qué blog va, con qué etiqueta y quién firma. */
async function pintarDestinoHubspot(nota, contenedor) {
  if (!_hubspotConfigurado) return;
  var bloque = bloqueRevision('Publicación en HubSpot', '<p class="revision-sub">Cargando…</p>');
  contenedor.appendChild(bloque);
  var d;
  try { d = await pedir('/api/hubspot/destino/notas_fase2/' + nota._id); }
  catch (e) {
    if (e.status === 422 && _notaActual && _notaActual.id === nota._id) {
      _notaActual.sinDestino = true;   // sin blog en su idioma: se aprueba sin subir
      pintarAccionesNota();
    }
    bloque.classList.add('con-fallas');
    bloque.innerHTML = '<h4>' + escHtml(tr('Publicación en HubSpot')) + '</h4><p class="revision-mal">' + escHtml(e.message) + '</p>';
    return;
  }
  var opciones = d.autores.length ? d.autores : [{ id: d.autor_id, nombre: 'Autor por defecto' }];
  if (!opciones.some(function(a) { return a.id === d.autor_id; })) opciones.unshift({ id: d.autor_id, nombre: 'Autor ' + d.autor_id });
  var editable = _notaActual && _notaActual.estado !== 'publicado';
  bloque.innerHTML = '<h4>' + escHtml(tr('Publicación en HubSpot')) + '</h4>'
    + '<p>' + escHtml('Blog: ' + d.blog) + '</p>'
    + '<p>' + (d.etiquetas.length ? escHtml('Etiqueta: ' + d.etiquetas.join(', ')) : escHtml('Sin etiqueta para estas categorías.')) + '</p>'
    + '<label class="control-label" for="hubspot-autor">Autor</label>'
    + '<select id="hubspot-autor" class="input-field hubspot-autor"' + (editable ? '' : ' disabled') + '>'
    + opciones.map(function(a) {
        return '<option value="' + escHtml(a.id) + '"' + (a.id === d.autor_id ? ' selected' : '') + ' translate="no">' + escHtml(a.nombre) + '</option>';
      }).join('')
    + '</select>'
    + (d.autores.length ? '' : '<p class="revision-sub">No se pudieron cargar los autores: se usa el autor por defecto.</p>')
    + '<p class="revision-sub">Al aprobar, la nota se sube como borrador. Se publica desde HubSpot.</p>';
}

async function cambiarEstadoNota(estado, sinAviso) {
  var n = _notaActual;
  var motivo = null;
  if (estado === 'aprobada' && n.estado === 'publicado' && n.hubspot && n.hubspot.id && !await confirmar({
    titulo: '¿Despublicar esta nota?', accion: 'Despublicar',
    mensaje: 'Deja de verse en el blog: en HubSpot vuelve a borrador. Acá queda aprobada, lista para publicar de nuevo.'
  })) return false;
  if (estado === 'rechazada') {
    motivo = await confirmar({
      titulo: '¿Rechazar esta nota?', accion: 'Rechazar',
      mensaje: 'Queda en el historial como rechazada y no se publica. Las próximas notas van a tener en cuenta el motivo.',
      campo: '¿Qué tiene mal?', placeholder: 'Ej: inventa cifras, suena a folleto, repite la introducción…'
    });
    if (!motivo) return false;
  }
  try {
    var d = await pedir('/api/historial/estado', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id, estado: estado, motivo: motivo })
    });
    n.estado = d.item.estado;
    pintarAccionesNota();
    if (!sinAviso) showToast('Nota: ' + NOMBRE_ESTADO_NOTA[n.estado].toLowerCase(), 'success');
    cargarResumenHistorial();
    if (_seccion === 'historial') cargarHistorial(_hist.pagina);
    return true;
  } catch (e) { showToast(e.message, 'error'); return false; }
}

/* Cómo quedaría el post en el blog: lo mismo que se manda a HubSpot. */
async function vistaPreviaNota() {
  var n = _notaActual, d;
  try { d = await pedir('/api/historial/vista-previa/' + n.coleccion + '/' + n.id); }
  catch (e) { showToast(e.message, 'error'); return; }
  var propia = d.imagen_propia || {};
  $('art-body').innerHTML =
    '<div class="previa">'
    + (d.imagen.url ? '<img class="previa-imagen" src="' + srcImagen(d.imagen.url) + '" alt="' + escHtml(d.imagen.alt || '') + '">'
                    : '<div class="previa-sin-imagen">Sin imagen destacada</div>')
    + '<h1 translate="no">' + escHtml(d.titulo) + '</h1>'
    + (d.meta ? '<p class="previa-meta" translate="no">' + escHtml(d.meta) + '</p>' : '<p class="previa-meta aviso">Sin meta description: la nota no termina con una línea en cursiva.</p>')
    + (d.etiquetas.length ? '<div class="previa-etiquetas">' + d.etiquetas.map(function(t) { return '<span>' + escHtml(t) + '</span>'; }).join('') + '</div>' : '')
    + '<div class="previa-url">/' + escHtml(d.slug) + '</div>'
    + '<div class="previa-cuerpo" translate="no">' + DOMPurify.sanitize(d.html) + '</div>'
    + '</div>'
    + '<fieldset class="previa-form"><legend>Imagen destacada</legend>'
    + bloqueGenerarImagen(d, propia)
    + '<label class="control-label" for="previa-img-url">O pegá la URL de una imagen (https)</label>'
    + '<input id="previa-img-url" class="input-field" type="url" placeholder="https://…/imagen.jpg">'
    + '<label class="control-label" for="previa-img-alt">Texto alternativo</label>'
    + '<input id="previa-img-alt" class="input-field" type="text" maxlength="200" placeholder="Qué muestra la imagen">'
    + '<div class="previa-acciones"><button type="button" class="btn btn-xs btn-primary" onclick="guardarImagenNota()">Guardar imagen</button>'
    + (propia.url || propia.generada ? '<button type="button" class="btn btn-xs" onclick="guardarImagenNota(true)">Quitar imagen</button>' : '')
    + '</div></fieldset>';
  $('previa-img-url').value = propia.url || '';
  $('previa-img-alt').value = propia.alt || '';
  $('nota-acciones').innerHTML = '<button type="button" class="btn btn-xs" onclick="cancelarEdicionNota()">Volver al texto</button>';
  $('art-body').scrollTop = 0;
}

/* Una imagen generada se sirve desde /api/imagenes/<id> hasta que se sube a HubSpot. */
function srcImagen(u) {
  return /^\/api\/imagenes\/[0-9a-f]{24}$/.test(u || '') ? u : urlSegura(u);
}

function bloqueGenerarImagen(d, propia) {
  if (!d.imagenes_disponibles) {
    return '<p class="previa-ayuda">Para generar imágenes con IA falta configurar NVIDIA_API_KEY en el servidor.</p>';
  }
  var gen = propia.generada;
  return '<div class="previa-generar">'
    + (gen ? '<p class="previa-ayuda">Imagen generada con IA (' + escHtml(gen.modelo || '') + ').'
             + (propia.url ? ' Ya está subida a HubSpot.' : ' Se sube a HubSpot al enviar la nota.') + '</p>'
           : '<p class="previa-ayuda">Generá una imagen con IA (NVIDIA, sin costo). Sin descripción usa la que propuso el plan de la nota.</p>')
    + '<label class="control-label" for="previa-img-desc">Qué querés que muestre (opcional, mejor en inglés)</label>'
    + '<textarea id="previa-img-desc" class="input-field" rows="2" maxlength="600" placeholder="Ej: a parts store counter with brake pads on display"></textarea>'
    + '<button type="button" class="btn btn-xs btn-primary" id="btn-generar-imagen" onclick="generarImagenNota()">'
    + (gen ? 'Generar otra imagen' : 'Generar imagen con IA') + '</button>'
    + '</div>';
}

/* La imagen va por la Cola: aparece en Corridas con su registro y se puede
   cancelar desde ahí. Si hay otra corrida en curso, espera su turno. */
async function generarImagenNota() {
  var n = _notaActual, btn = $('btn-generar-imagen');
  var restaurar = function() { btn.disabled = false; btn.textContent = 'Generar imagen con IA'; };
  btn.disabled = true;
  btn.textContent = 'Generando… (puede tardar un minuto)';
  var errores = [];
  try {
    var fin = await correrEnCola('/api/historial/imagen/generar',
      { coleccion: n.coleccion, id: n.id, descripcion: $('previa-img-desc').value.trim() },
      function(l) {
        var m = l.match(/\[ERROR\]\s*(.+)/);
        if (m) errores.push(m[1].trim());
        log(l, m ? 'error' : l.indexOf('[OK]') >= 0 ? 'success' : 'info');
      },
      function(d) {
        btn.textContent = textoEnCola(d) || 'Generando… (puede tardar un minuto)';
      });
    if (fin.estado === 'ok') {
      showToast('Imagen generada', 'success');
      if (_notaActual === n) vistaPreviaNota();
      else restaurar();
    } else if (fin.estado === 'cancelada') {
      showToast('Se canceló la imagen.', 'info');
      restaurar();
    } else {
      showToast(errores[errores.length - 1] || fin.error || 'No se pudo generar la imagen. Mirá el registro en Corridas.', 'error');
      restaurar();
    }
  } catch (e) {
    showToast(e.message, 'error');
    restaurar();
  }
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
  $('art-body').innerHTML = '<div translate="no">' + DOMPurify.sanitize(marked.parse(_notaActual.contenido || '')) + '</div>';
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
