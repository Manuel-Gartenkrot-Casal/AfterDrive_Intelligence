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
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'historial') { cargarResumenHistorial(); cargarHistorial(_hist.pagina); cargarCalibracion(); } });
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

// silencioso: sin "Cargando…" (lo usa la actualización automática de vivo.js).
async function cargarHistorial(pagina, silencioso) {
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
  if (!silencioso) {
    lista.setAttribute('aria-busy', 'true');
    $('hist-paginador').textContent = '';
    lista.innerHTML = '<p class="corridas-vacio">Cargando…</p>';
  }
  var qs = '?pagina=' + _hist.pagina + '&por_pagina=15&q=' + encodeURIComponent(_hist.q)
    + (esNotas ? '&estado=' + _hist.estado : '');
  var d;
  try { d = await pedir('/api/historial/' + _hist.seccion + qs); }
  catch (e) { lista.removeAttribute('aria-busy'); lista.innerHTML = '<p class="corridas-vacio">No se pudo cargar: ' + escHtml(e.message) + '</p>'; return; }

  lista.removeAttribute('aria-busy');
  // La página quedó vacía (otro aprobó o borró lo que había): a la última que tiene algo.
  if (!d.items.length && _hist.pagina > 1 && d.paginas < _hist.pagina) return cargarHistorial(Math.max(1, d.paginas), silencioso);
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
      if (it.critica_puntaje) {
        // La de la IA va de 1 a 10: en estrellas, la mitad redondeada, con la marca IA para no confundirla.
        var deIA = Math.max(1, Math.round(it.critica_puntaje / 2));
        lado += '<span class="badge-estrellas badge-ia" title="Calificación de la IA: ' + it.critica_puntaje + '/10" aria-label="La IA la calificó con ' + deIA + ' de 5">'
          + '<span class="marca-ia" aria-hidden="true">IA</span>' + estrellas(deIA) + '</span>';
      }
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
  sinRecorrido();
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
// Desactivado por ahora: solo se sube como borrador (el servidor también lo frena, ver historial.py).
var PUBLICAR_DESDE_DASHBOARD = false;

/* Pie del modal. Izquierda: Editar, Vista previa y "Más" (lo que se usa
   poco). Derecha: una sola acción principal, la que corresponde al paso del
   recorrido (ver recorrido.js) y al estado de la nota. */
function pintarAccionesNota() {
  var cont = $('nota-acciones'), chip = $('modal-estado');
  if (!_notaActual) {
    chip.hidden = true;
    cont.innerHTML = '<button type="button" class="btn btn-xs" onclick="copiar()">Copiar texto</button>';
    return;
  }
  var n = _notaActual, e = n.estado;
  chip.hidden = false;
  chip.className = 'estado-chip ' + e;
  chip.textContent = NOMBRE_ESTADO_NOTA[e];
  // En todas las notas, esté o no configurado HubSpot en este servidor: si falta el
  // token, el bloque de la revisión lo dice y la subida devuelve el motivo.
  var subible = !n.sinDestino;   // sinDestino: no hay blog en su idioma
  var yaEnviada = n.hubspot && n.hubspot.id;
  var boton = function(onclick, texto, clase) {
    return '<button type="button" class="btn btn-xs' + (clase || '') + '" onclick="' + onclick + '">' + texto + '</button>';
  };
  var item = function(onclick, texto, clase) {
    return '<button type="button" role="menuitem" class="' + (clase || '') + '" onclick="' + onclick + '">' + texto + '</button>';
  };
  var izq = (e !== 'publicado' ? boton('editarNota()', 'Editar') : '') + boton('vistaPreviaNota()', 'Vista previa');

  var menu = item('copiar()', 'Copiar texto');
  if (n.hubspot && n.hubspot.url) {
    menu += '<a role="menuitem" href="' + urlSegura(n.hubspot.url) + '" target="_blank" rel="noopener">Ver en HubSpot</a>';
  }
  if (subible && e === 'aprobada') menu += item('enviarAHubspot(false)', yaEnviada ? 'Actualizar borrador en HubSpot' : 'Subir borrador a HubSpot');
  if (e === 'aprobada' || e === 'rechazada') menu += item("cambiarEstadoNota('borrador')", 'Volver a revisar');
  if (e === 'publicado') menu += item("cambiarEstadoNota('aprobada')", 'Despublicar', 'peligro');
  if (e === 'borrador') menu += '<hr>' + item("cambiarEstadoNota('rechazada')", 'Rechazar', 'peligro');

  var paso = _recorrido.activo ? _recorrido.paso : 'publicar', der = '';
  if (_recorrido.activo && enCelular() && $('modal-caja').dataset.vista === 'nota') der = boton("verPanelModal('revision')", 'Revisar y publicar →', ' btn-primary');
  else if (paso === 'revisar') der = boton("irAPaso('calificar')", 'Siguiente: calificar →', ' btn-primary');
  else if (paso === 'calificar') der = boton("irAPaso('publicar')", 'Siguiente: publicar →', ' btn-primary');
  else if (e === 'borrador') der = subible ? boton('aprobarYSubir()', 'Aprobar y subir a HubSpot', ' btn-primary')
                                           : boton("cambiarEstadoNota('aprobada')", 'Aprobar', ' btn-primary');
  else if (e === 'aprobada' && subible && !PUBLICAR_DESDE_DASHBOARD)
    der = boton('enviarAHubspot(false)', yaEnviada ? 'Actualizar borrador en HubSpot' : 'Subir borrador a HubSpot', ' btn-primary');
  else if (e === 'aprobada' && subible) der = boton('enviarAHubspot(true)', 'Publicar en HubSpot', ' btn-primary');
  else if (e === 'publicado' && subible && yaEnviada && PUBLICAR_DESDE_DASHBOARD) der = boton('enviarAHubspot(true)', 'Actualizar en HubSpot', ' btn-primary');
  else if (e === 'rechazada') der = boton("cambiarEstadoNota('borrador')", 'Volver a revisar', ' btn-primary');

  cont.innerHTML = '<div class="acciones-izq">' + izq
    + '<div class="menu-nota"><button type="button" class="btn btn-xs" id="nota-mas" aria-haspopup="menu" aria-expanded="false"'
    + ' aria-controls="nota-menu" onclick="alternarMenuNota()">Más ▾</button>'
    + '<div class="menu-nota-lista" id="nota-menu" role="menu" aria-label="Más acciones" hidden>' + menu + '</div></div></div>'
    + (der ? '<div class="acciones-der">' + der + '</div>' : '');
  actualizarPasos();
}

var _estadoHubspot = null;
/* Si HubSpot tiene token en este servidor. Si la nota se abre antes de que
   llegue, o el pedido falló, la revisión lo espera (y lo vuelve a pedir). */
function cargarEstadoHubspot() {
  _estadoHubspot = pedir('/api/hubspot/estado')
    .then(function(d) { return !!d.configurado; })
    .catch(function() { _estadoHubspot = null; return false; });
  return _estadoHubspot;
}
function hubspotConfigurado() { return _estadoHubspot || cargarEstadoHubspot(); }

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
    avisarTraducciones(d.traducciones);
    ok = true;
  } catch (e) { showToast(e.message, 'error'); }
  cargarResumenHistorial();
  if (_seccion === 'historial') cargarHistorial(_hist.pagina);
  pintarAccionesNota();
  return ok;
}

/* Las versiones en los otros idiomas se traducen y suben en la Cola: se avisa y se sigue en Actividad. */
function avisarTraducciones(t) {
  if (!t) return;
  var nombres = { es: 'español', pt: 'portugués', en: 'inglés' };
  var idiomas = (t.idiomas || []).map(function(c) { return nombres[c] || c; }).join(' y ');
  if (t.error) { showToast('No se pudieron encolar las traducciones: ' + t.error, 'warn', 8000); return; }
  showToast('Las versiones en ' + idiomas + ' se traducen y suben como borrador en segundo plano. Seguilas en Actividad.', 'info', 8000);
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
  var bloque = bloqueRevision('Publicación en HubSpot', '<p class="revision-sub">Cargando…</p>');
  contenedor.appendChild(bloque);
  var configurado = await hubspotConfigurado();
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
    + (d.autores.length || !configurado ? '' : '<p class="revision-sub">No se pudieron cargar los autores: se usa el autor por defecto.</p>')
    + (configurado
      ? '<p class="revision-sub">Al aprobar, la nota se sube como borrador. Se publica desde HubSpot.</p>'
      : '<p class="revision-mal">HubSpot no está configurado en este servidor: falta HUBSPOT_TOKEN. Al aprobar, la nota queda aprobada pero no se sube.</p>');
  if (!configurado) bloque.classList.add('con-fallas');
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
  verPanelModal('nota');
  try { d = await pedir('/api/historial/vista-previa/' + n.coleccion + '/' + n.id); }
  catch (e) { showToast(e.message, 'error'); return; }
  var propia = d.imagen_propia || {};
  // El formulario de la imagen va primero: es lo que se viene a cambiar acá.
  $('art-body').innerHTML =
    '<fieldset class="previa-form"><legend>Imagen destacada</legend>'
    + zonaImagenHtml('')
    + bloqueImagenesNoticias(d, propia)
    + '<label class="control-label" for="previa-img-url">O pegá la URL de una imagen (https)</label>'
    + '<input id="previa-img-url" class="input-field" type="url" placeholder="https://…/imagen.jpg">'
    + '<label class="control-label" for="previa-img-alt">Texto alternativo</label>'
    + '<input id="previa-img-alt" class="input-field" type="text" maxlength="200" placeholder="Qué muestra la imagen">'
    + '<div class="previa-acciones"><button type="button" class="btn btn-xs btn-primary" onclick="guardarImagenNota()">Guardar imagen</button>'
    + (propia.url ? '<button type="button" class="btn btn-xs" onclick="guardarImagenNota(true)">Quitar imagen</button>' : '')
    + '</div></fieldset>'
    + '<div class="previa">'
    + (d.imagen.url ? '<img class="previa-imagen" src="' + urlSegura(d.imagen.url) + '" alt="' + escHtml(d.imagen.alt || '') + '" referrerpolicy="no-referrer">'
                    : '<div class="previa-sin-imagen">Sin imagen destacada</div>')
    + '<h1 translate="no">' + escHtml(d.titulo) + '</h1>'
    + (d.meta ? '<p class="previa-meta" translate="no">' + escHtml(d.meta) + '</p>' : '<p class="previa-meta aviso">Sin meta description: la nota no termina con una línea en cursiva.</p>')
    + (d.etiquetas.length ? '<div class="previa-etiquetas">' + d.etiquetas.map(function(t) { return '<span>' + escHtml(t) + '</span>'; }).join('') + '</div>' : '')
    + '<div class="previa-url">/' + escHtml(d.slug) + '</div>'
    + '<div class="previa-cuerpo" translate="no">' + DOMPurify.sanitize(d.html) + '</div>'
    + '</div>';
  $('previa-img-url').value = propia.subida ? '' : (propia.url || '');   // la subida no tiene URL pública
  $('previa-img-alt').value = propia.alt || '';
  prepararZonaImagen($('zona-imagen'));
  $('nota-acciones').innerHTML = '<button type="button" class="btn btn-xs" onclick="cancelarEdicionNota()">Volver al texto</button>';
  $('art-body').scrollTop = 0;
}

/* Imagen desde la computadora: se arrastra a la zona o se elige con el botón. */
var IMAGEN_MAX_BYTES = 5 * 1024 * 1024;

/* La zona: en la vista previa (sufijo '') y en el paso Publicar ('-publicar'). */
function zonaImagenHtml(sufijo) {
  return '<div class="zona-imagen" id="zona-imagen' + sufijo + '">'
    + '<input type="file" id="archivo-imagen' + sufijo + '" accept="image/jpeg,image/png,image/webp,image/gif" hidden>'
    + '<p><strong>Arrastrá una imagen acá</strong> o elegila desde tu computadora.</p>'
    + '<button type="button" class="btn btn-xs" onclick="$(\'archivo-imagen' + sufijo + '\').click()">Elegir archivo</button>'
    + '<small>JPG, PNG, WebP o GIF, hasta 5 MB.</small></div>';
}

function prepararZonaImagen(zona) {
  if (!zona) return;
  var input = zona.querySelector('input[type="file"]');
  input.onchange = function() { if (input.files[0]) subirArchivoImagen(input.files[0], zona); input.value = ''; };
  ['dragenter', 'dragover'].forEach(function(t) {
    zona.addEventListener(t, function(ev) { ev.preventDefault(); zona.classList.add('activa'); });
  });
  ['dragleave', 'drop'].forEach(function(t) {
    zona.addEventListener(t, function(ev) { ev.preventDefault(); zona.classList.remove('activa'); });
  });
  zona.addEventListener('drop', function(ev) {
    var f = ev.dataTransfer && ev.dataTransfer.files[0];
    if (f) subirArchivoImagen(f, zona);
  });
}

// Soltar un archivo fuera de la zona no tiene que abrirlo en la pestaña.
['dragover', 'drop'].forEach(function(t) {
  document.addEventListener(t, function(ev) {
    if ($('modal-art').classList.contains('open') && !ev.target.closest('.zona-imagen')) ev.preventDefault();
  });
});

async function subirArchivoImagen(archivo, zona) {
  if (!/^image\/(jpeg|png|webp|gif)$/.test(archivo.type)) { showToast('El archivo tiene que ser una imagen JPG, PNG, WebP o GIF.', 'error'); return; }
  if (archivo.size > IMAGEN_MAX_BYTES) { showToast('La imagen pesa más de 5 MB.', 'error'); return; }
  var n = _notaActual;
  if (zona) zona.classList.add('subiendo');
  var datos = new FormData();
  datos.append('archivo', archivo);
  datos.append('coleccion', n.coleccion);
  datos.append('id', n.id);
  datos.append('alt', $('previa-img-alt') ? $('previa-img-alt').value.trim() : '');
  try {
    var d = await pedir('/api/historial/imagen/archivo', { method: 'POST', body: datos });
    showToast('Imagen guardada', 'success');
    imagenCambiada(d.imagen);
    if ($('zona-imagen')) vistaPreviaNota();   // si la vista previa está abierta, se ve con la imagen nueva
  } catch (e) {
    if (zona) zona.classList.remove('subiendo');
    showToast(e.message, 'error');
  }
}

/* Fotos de las noticias de la nota: elegir una la deja como destacada. */
var _fotosNoticias = [];

function bloqueImagenesNoticias(d, propia) {
  _fotosNoticias = d.imagenes_noticias || [];
  var html = '<div class="previa-fotos-bloque">';
  if (propia.origen) {
    html += '<p class="previa-ayuda">Foto de la noticia: <a href="' + urlSegura(propia.origen.url) + '" target="_blank" rel="noopener">'
      + escHtml(propia.origen.titulo || propia.origen.url) + '</a></p>'
      + '<p class="previa-ayuda">' + (propia.hubspot_url ? 'Ya está copiada en HubSpot.' : 'Se copia a HubSpot al subir la nota.') + '</p>';
  }
  if (!_fotosNoticias.length) {
    return html + '<p class="previa-ayuda">Las noticias de esta nota no tienen fotos guardadas.</p></div>';
  }
  return html + '<p class="previa-ayuda">Elegí la foto de una de sus noticias:</p><div class="previa-fotos">'
    + _fotosNoticias.map(function(f, i) {
        var descartada = f.apta === false, personas = !descartada && f.personas === true;
        var detalle = f.titulo + (f.motivo ? ' — ' + (descartada ? 'La IA la descartó: ' : 'IA: ') + f.motivo : '');
        var marca = descartada ? 'IA: no apta' : personas ? 'Tiene personas: no va de portada' : '';
        return '<button type="button" class="previa-foto' + (f.url === propia.url ? ' elegida' : '') + (descartada || personas ? ' descartada' : '') + '"'
          + ' onclick="elegirImagenNoticia(' + i + ')" title="' + escHtml(detalle) + '" aria-label="' + escHtml(f.titulo) + '">'
          + '<img src="' + urlSegura(f.url) + '" alt="" loading="lazy" referrerpolicy="no-referrer">'
          + (marca ? '<span class="previa-foto-marca">' + marca + '</span>' : '') + '</button>';
      }).join('')
    + '</div></div>';
}

function elegirImagenNoticia(i) {
  var f = _fotosNoticias[i];
  if (!f) return;
  $('previa-img-url').value = f.url;
  guardarImagenNota();
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
    imagenCambiada(quitar ? null : { url: $('previa-img-url').value.trim(), alt: $('previa-img-alt').value.trim() });
    vistaPreviaNota();
  } catch (e) { showToast(e.message, 'error'); }
}

/* ── Idiomas de la nota ──
   La nota se escribe en el idioma principal (portugués) y se traduce al crearla.
   Cada versión se ve en su pestaña y se edita por separado. */
var NOMBRE_IDIOMA = { pt: 'Português', es: 'Español', en: 'English' };

function _vistaEsPrincipal(n) { return !n.idioma || n.vista === n.idioma; }

function _traduccionVista(n) { return (n.traducciones || {})[n.vista] || {}; }

function pintarCuerpoNota() {
  var n = _notaActual, html = '';
  if (!n) return;
  if (n.idioma) {
    var orden = [n.idioma].concat(['pt', 'es', 'en'].filter(function(c) { return c !== n.idioma; }));
    html += '<div class="idiomas-nota" role="tablist" aria-label="Idioma">' + orden.map(function(c) {
      var t = (n.traducciones || {})[c] || {}, marca = '';
      if (c !== n.idioma) {
        if (t.error && !t.contenido) marca = ' <span class="marca">Error</span>';
        else if (!t.contenido) marca = ' <span class="marca">Sin traducir</span>';
        else if (t.al_dia === false) marca = ' <span class="marca">Desactualizada</span>';
        else if (t.editada) marca = ' <span class="marca">Editada</span>';
      }
      return '<button type="button" role="tab" class="chip' + (c === n.vista ? ' on' : '') + '" aria-selected="' + (c === n.vista)
        + '" onclick="verIdiomaNota(\'' + c + '\')">' + NOMBRE_IDIOMA[c] + (c === n.idioma ? ' · principal' : '') + marca + '</button>';
    }).join('') + '</div>';
  }
  var texto = n.contenido || '';
  if (!_vistaEsPrincipal(n)) {
    var t = _traduccionVista(n);
    texto = t.contenido || '';
    if (t.contenido && t.al_dia === false) {
      html += '<p class="revision-sub">El texto principal cambió después de esta traducción. Al subir a HubSpot se vuelve a traducir'
        + (t.editada ? ' (y se pierden tus cambios en esta versión)' : '') + ', o retraducila ahora.</p>';
    }
    if (!t.contenido) html += '<p class="revision-sub">' + (t.error ? 'No se pudo traducir: ' + escHtml(t.error) : 'Todavía no hay traducción a este idioma.') + '</p>';
    html += '<p><button type="button" class="btn btn-xs" onclick="retraducirNota()">' + (t.contenido ? 'Volver a traducir' : 'Traducir') + '</button></p>';
  }
  if (n.idioma) html = '<div class="idiomas-cab">' + html + '</div>';
  html += '<div id="nota-texto" translate="no">' + DOMPurify.sanitize(marked.parse(texto)) + '</div>';
  $('art-body').innerHTML = html;
}

function verIdiomaNota(cod) {
  _notaActual.vista = cod;
  pintarCuerpoNota();
  pintarAccionesNota();
}

async function retraducirNota() {
  var n = _notaActual, t = _traduccionVista(n);
  if (t.editada && !(await confirmar({ titulo: '¿Volver a traducir?', mensaje: 'Se pierden los cambios que hiciste a mano en esta versión.',
                                       accion: 'Sí, traducir de nuevo', cancelar: 'Cancelar' }))) return;
  try {
    await pedir('/api/historial/retraducir', { method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id, idioma: n.vista }) });
    showToast('Traduciendo al ' + NOMBRE_IDIOMA[n.vista] + ': lo ves en Actividad. Volvé a abrir la nota cuando termine.', 'success');
    if (typeof refrescarCorridas === 'function') refrescarCorridas();
  } catch (e) { showToast(e.message, 'error'); }
}

function editarNota() {
  var n = _notaActual, principal = _vistaEsPrincipal(n);
  verPanelModal('nota');
  if (!principal && !_traduccionVista(n).contenido) { showToast('Primero traducila.', 'warn'); return; }
  $('art-body').innerHTML = '<label class="control-label" for="editor-nota">'
    + (principal ? 'Texto de la nota (Markdown)' : 'Versión en ' + NOMBRE_IDIOMA[n.vista] + ' (Markdown)') + '</label>'
    + '<textarea id="editor-nota" class="editor-nota"></textarea>';
  $('editor-nota').value = principal ? (n.contenido || '') : _traduccionVista(n).contenido;
  $('editor-nota').focus();
  $('nota-acciones').innerHTML = '<button type="button" class="btn btn-xs btn-primary" onclick="guardarEdicionNota()">Guardar texto</button>'
    + '<button type="button" class="btn btn-xs" onclick="cancelarEdicionNota()">Cancelar</button>';
}

function cancelarEdicionNota() {
  pintarCuerpoNota();
  pintarAccionesNota();
}

async function guardarEdicionNota() {
  var n = _notaActual;
  if (!_vistaEsPrincipal(n)) {
    try {
      var r = await pedir('/api/historial/traduccion', {
        method: 'PATCH', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ coleccion: n.coleccion, id: n.id, idioma: n.vista, contenido: $('editor-nota').value })
      });
      n.traducciones = n.traducciones || {};
      n.traducciones[n.vista] = Object.assign(r.traduccion, { al_dia: true });
      cancelarEdicionNota();
      showToast('Traducción guardada', 'success');
    } catch (e) { showToast(e.message, 'error'); }
    return;
  }
  try {
    var d = await pedir('/api/historial/contenido', {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: n.coleccion, id: n.id, contenido: $('editor-nota').value })
    });
    n.contenido = d.item.contenido;
    // Las traducciones guardadas pasan a estar desactualizadas.
    Object.keys(n.traducciones || {}).forEach(function(c) { if (n.traducciones[c].contenido) n.traducciones[c].al_dia = false; });
    $('modal-titulo').textContent = d.item.titulo;
    cancelarEdicionNota();
    showToast('Texto guardado', 'success');
    cargarResumenHistorial();
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
        + '<span translate="no">' + escHtml(it.titulo) + '</span><small>' + fechaCorta(it.fecha) + ' · Para revisar</small></button>';
    }).join('') + (d.total > d.items.length
      ? '<button class="btn btn-sm inicio-mas" onclick="abrirPendientes()">Ver las ' + d.total + ' notas pendientes</button>'
      : '<p class="corridas-vacio inicio-fin">No hay más notas para revisar. Las nuevas aparecen acá apenas se generan.</p>')
      : '<p class="corridas-vacio">Estás al día. Las nuevas notas aparecerán acá para revisarlas.</p>';
  } catch(e) { $('inicio-lista').textContent = 'No se pudieron cargar las notas. Podés reintentar desde Historial.'; }
}
