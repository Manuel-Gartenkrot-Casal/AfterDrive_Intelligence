/* prompts.js — Prompts de redacción editables, con aprobación.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Cada pieza del prompt (identidad, audiencia, reglas, enfoque Alephee,
   formato, SEO, respuesta y las 5 personas) es Markdown. Recorrido:
   Borrador → Validar → Enviar a revisión → Aprobar y activar (con el diff a la
   vista) → Activa. La versión anterior queda en el historial y se puede
   restaurar, que vuelve a pasar por revisión. El backend es
   afterdrive/prompts_editables.py (/api/prompts). */

var PROMPTS = {
  piezas: [],
  clave: null,
  detalle: null,
  base: { texto: '', motivo: '' },   // lo cargado en el editor: si difiere, hay cambios sin guardar
  validacion: null,
  tab: 'editar',
  cargado: false
};
var _PASOS_PROMPT = ['borrador', 'validar', 'en_revision', 'activo'];
var _ESTADOS_PROMPT = { borrador: 'Borrador', en_revision: 'En revisión', activo: 'Activa', archivado: 'Archivada' };

function _promptTexto() { return $('pe-texto').value.replace(/\r\n/g, '\n'); }
function _promptSucio() {
  return PROMPTS.detalle !== null && (_promptTexto().trim() !== PROMPTS.base.texto.trim()
    || $('pe-motivo').value.trim() !== PROMPTS.base.motivo.trim());
}
function _fechaPrompt(iso) {
  if (!iso) return '';
  var d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleString(localeUI(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function initPrompts() {
  document.querySelectorAll('.prompts-tabs [role="tab"]').forEach(function(b) {
    b.addEventListener('click', function() { elegirTabPrompt(b.dataset.tab); });
  });
  var espera = null;
  $('pe-texto').addEventListener('input', function() {
    pintarAccionesPrompt();
    clearTimeout(espera);
    espera = setTimeout(validarPrompt, 400);
  });
  $('pe-motivo').addEventListener('input', pintarAccionesPrompt);
  $('pe-persona').addEventListener('change', pintarPromptCompleto);
  $('pe-guardar').addEventListener('click', function() { guardarPrompt(); });
  $('pe-enviar').addEventListener('click', enviarPrompt);
  $('pe-aprobar').addEventListener('click', aprobarPrompt);
  $('pe-rechazar').addEventListener('click', rechazarPrompt);
  $('pe-descartar').addEventListener('click', descartarPrompt);
  // Con cambios sin guardar, salir de la sección pide confirmación (base.js).
  FORMULARIOS.prompts = {
    sucio: _promptSucio,
    descartar: function() { if (PROMPTS.detalle) cargarEditorPrompt(PROMPTS.detalle); }
  };
  document.addEventListener('seccion', function(ev) {
    if (ev.detail === 'prompts') cargarPiezasPrompt();
  });
  cargarPiezasPrompt(true);   // para el aviso de la barra lateral
}

async function cargarPiezasPrompt(soloAviso) {
  try {
    var d = await pedir('/api/prompts');
    PROMPTS.piezas = d.piezas;
  } catch (e) {
    if (!soloAviso) $('prompts-lista').innerHTML = '<p class="prompts-vacio">' + escHtml(tr('No se pudieron cargar los prompts.')) + '</p>';
    return;
  }
  var enRevision = PROMPTS.piezas.filter(function(p) { return p.pendiente && p.pendiente.estado === 'en_revision'; }).length;
  $('nav-badge-prompts').textContent = enRevision || '';
  if (soloAviso) return;
  pintarListaPrompts();
  if (!PROMPTS.cargado) {
    PROMPTS.cargado = true;
    elegirPrompt(PROMPTS.piezas[0].clave, true);
  }
}

function pintarListaPrompts() {
  var grupos = { base: 'Base del prompt', persona: 'Personas' };
  var html = '';
  Object.keys(grupos).forEach(function(g) {
    html += '<p class="prompts-grupo">' + escHtml(grupos[g]) + '</p>';
    PROMPTS.piezas.filter(function(p) { return p.grupo === g; }).forEach(function(p) {
      var pend = p.pendiente;
      html += '<button type="button" class="prompts-item' + (p.clave === PROMPTS.clave ? ' activo' : '') + '" data-clave="' + escHtml(p.clave) + '"'
        + (p.clave === PROMPTS.clave ? ' aria-current="true"' : '') + '>'
        + '<span class="prompts-item-nombre">' + escHtml(p.titulo) + '</span>'
        + '<span class="prompts-item-meta">'
        + (pend ? '<span class="prompts-chip ' + pend.estado + '">' + escHtml(_ESTADOS_PROMPT[pend.estado]) + '</span>' : '')
        + '<span class="prompts-version">' + (p.version_activa ? 'v' + p.version_activa : escHtml(tr('original'))) + '</span>'
        + '</span></button>';
    });
  });
  $('prompts-lista').innerHTML = html;
  $('prompts-lista').querySelectorAll('.prompts-item').forEach(function(b) {
    b.addEventListener('click', function() { elegirPrompt(b.dataset.clave); });
  });
}

async function elegirPrompt(clave, forzar) {
  if (!forzar && clave === PROMPTS.clave) return;
  if (!forzar && _promptSucio()) {
    var seguir = await confirmar({
      titulo: 'Tenés cambios sin guardar',
      mensaje: 'Si cambiás de pieza, se pierde lo que escribiste y no guardaste.',
      accion: 'Descartar cambios', cancelar: 'Seguir editando'
    });
    if (!seguir) return;
  }
  PROMPTS.clave = clave;
  pintarListaPrompts();
  try {
    cargarEditorPrompt(await pedir('/api/prompts/' + encodeURIComponent(clave)));
  } catch (e) {
    showToast(tr('No se pudo abrir la pieza: ') + e.message, 'error');
  }
}

/* Lo que se edita: el borrador o la versión en revisión si hay; si no, la activa. */
function cargarEditorPrompt(d) {
  PROMPTS.detalle = d;
  var p = d.pendiente;
  PROMPTS.base = { texto: p ? p.contenido : d.activo.contenido, motivo: p ? (p.motivo || '') : '' };
  $('pe-texto').value = PROMPTS.base.texto;
  $('pe-motivo').value = PROMPTS.base.motivo;
  var item = PROMPTS.piezas.filter(function(x) { return x.clave === d.clave; })[0];
  $('pe-titulo').textContent = d.titulo;
  $('pe-descripcion').textContent = item ? item.descripcion : '';
  var esPersona = d.clave.indexOf('persona_') === 0;
  $('pe-persona').disabled = esPersona;
  if (esPersona) $('pe-persona').value = d.clave.slice(8);
  PROMPTS.validacion = null;
  validarPrompt();
  pintarAccionesPrompt();
  pintarHistorialPrompt();
  elegirTabPrompt(PROMPTS.tab);
}

function elegirTabPrompt(tab) {
  PROMPTS.tab = tab;
  document.querySelectorAll('.prompts-tabs [role="tab"]').forEach(function(b) {
    b.setAttribute('aria-selected', b.dataset.tab === tab ? 'true' : 'false');
  });
  document.querySelectorAll('.prompts-panel').forEach(function(p) { p.hidden = p.dataset.panel !== tab; });
  if (tab === 'ver') {
    var html = window.marked ? marked.parse(_promptTexto()) : escHtml(_promptTexto());
    $('pe-ver').innerHTML = window.DOMPurify ? DOMPurify.sanitize(html) : escHtml(_promptTexto());
  }
  if (tab === 'completo') pintarPromptCompleto();
}

async function validarPrompt() {
  if (!PROMPTS.clave) return;
  var texto = _promptTexto();
  try {
    var d = await pedir('/api/prompts/' + encodeURIComponent(PROMPTS.clave) + '/validar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contenido: texto })
    });
    if (texto !== _promptTexto()) return;   // ya cambió: valida la próxima
    PROMPTS.validacion = d;
  } catch (e) {
    PROMPTS.validacion = null;
  }
  pintarAccionesPrompt();
}

function pintarValidacionPrompt() {
  var v = PROMPTS.validacion, ul = $('pe-validacion');
  var largo = _promptTexto().trim().length;
  $('pe-largo').textContent = largo + ' ' + tr('caracteres');
  if (!v) { ul.innerHTML = ''; return; }
  var items = v.errores.map(function(e) { return '<li class="err">' + escHtml(e) + '</li>'; })
    .concat(v.avisos.map(function(a) { return '<li class="aviso">' + escHtml(a) + '</li>'; }));
  if (!items.length) items = ['<li class="ok">' + escHtml(tr('Validado: se puede enviar a revisión.')) + '</li>'];
  ul.innerHTML = items.join('');
}

function _estadoPrompt() {
  var p = PROMPTS.detalle && PROMPTS.detalle.pendiente;
  if (_promptSucio() || (p && p.estado === 'borrador')) return 'borrador';
  return p ? p.estado : 'activo';
}

function pintarAccionesPrompt() {
  var d = PROMPTS.detalle;
  if (!d) return;
  pintarValidacionPrompt();
  var p = d.pendiente, sucio = _promptSucio(), estado = _estadoPrompt();
  var valido = !!PROMPTS.validacion && !PROMPTS.validacion.errores.length;
  var igualActiva = _promptTexto().trim() === d.activo.contenido.trim();

  // Estado y pasos.
  var chip = $('pe-estado');
  chip.className = 'prompts-estado ' + estado;
  chip.textContent = estado === 'activo'
    ? (d.activo.version ? tr('Activa') + ' · v' + d.activo.version : tr('Activa · texto original'))
    : (sucio ? tr('Cambios sin guardar') : tr(_ESTADOS_PROMPT[estado]) + ' · v' + p.version);
  var actual = estado === 'activo' ? 3 : estado === 'en_revision' ? 2 : (valido && !igualActiva ? 1 : 0);
  document.querySelectorAll('#pe-pasos li').forEach(function(li, i) {
    li.classList.toggle('hecho', i < actual || (estado === 'activo' && i === 3));
    li.classList.toggle('actual', i === actual);
    if (i === actual) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  });

  // Aviso del momento.
  var aviso = '';
  if (p && p.rechazo && estado === 'borrador') aviso = tr('Devuelta a borrador') + (p.rechazo.motivo ? ': ' + p.rechazo.motivo : '.');
  else if (estado === 'en_revision' && p.restaurado_de !== undefined) aviso = p.restaurado_de ? tr('Restaura la versión') + ' ' + p.restaurado_de + '. ' + tr('Revisá el cambio y aprobalo para activarla.') : tr('Vuelve al texto original. Revisá el cambio y aprobalo para activarlo.');
  else if (estado === 'en_revision') aviso = tr('Lista para revisar. Mirá los cambios y aprobala para que la IA la use desde la próxima nota.');
  else if (estado === 'activo') aviso = tr('Es la versión que usa la IA. Si la editás, se guarda como borrador y la activa sigue igual hasta que apruebes el cambio.');
  else if (!p) aviso = tr('Al guardar se crea un borrador: la versión activa sigue igual hasta que apruebes el cambio.');
  $('pe-aviso').textContent = aviso;
  $('pe-aviso').hidden = !aviso;
  $('pe-aviso').classList.toggle('rechazo', !!(p && p.rechazo && estado === 'borrador'));

  // Botones.
  $('pe-descartar').hidden = !p;
  $('pe-guardar').hidden = estado === 'en_revision' || (!sucio && !p);
  $('pe-guardar').disabled = !sucio;
  $('pe-enviar').hidden = estado !== 'borrador';
  $('pe-enviar').disabled = !valido || igualActiva;
  $('pe-enviar').title = igualActiva ? tr('El texto es igual al de la versión activa.') : (!valido ? tr('Primero corregí lo que marca la validación.') : '');
  $('pe-aprobar').hidden = $('pe-rechazar').hidden = estado !== 'en_revision';
}

function _cuerpoPrompt() {
  return JSON.stringify({ contenido: _promptTexto(), motivo: $('pe-motivo').value.trim() });
}

async function _accionPrompt(btn, url, opciones, okMsg) {
  setBtnLoading(btn, true);
  try {
    var d = await pedir(url, opciones);
    if (okMsg) showToast(tr(okMsg), 'success');
    return d;
  } catch (e) {
    showToast(e.message, 'error', 6000);
    return null;
  } finally {
    setBtnLoading(btn, false);
  }
}

async function _recargarPrompt() {
  cargarEditorPrompt(await pedir('/api/prompts/' + encodeURIComponent(PROMPTS.clave)));
  cargarPiezasPrompt();
}

async function guardarPrompt(silencioso) {
  var d = await _accionPrompt($('pe-guardar'), '/api/prompts/' + encodeURIComponent(PROMPTS.clave) + '/borrador',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: _cuerpoPrompt() },
    silencioso ? null : 'Borrador guardado');
  if (d) await _recargarPrompt();
  return !!d;
}

async function enviarPrompt() {
  if (_promptSucio() && !(await guardarPrompt(true))) return;
  var d = await _accionPrompt($('pe-enviar'), '/api/prompts/' + encodeURIComponent(PROMPTS.clave) + '/enviar',
    { method: 'POST' }, 'Enviada a revisión');
  if (d) await _recargarPrompt();
}

async function aprobarPrompt() {
  var d = PROMPTS.detalle, p = d.pendiente;
  $('pa-texto').textContent = tr('Pasa a ser la versión activa de') + ' ' + d.titulo + ' (v' + p.version + ') '
    + tr('y la IA la usa desde la próxima nota.') + ' '
    + (d.activo.version ? tr('La versión') + ' v' + d.activo.version + ' ' + tr('queda archivada y se puede restaurar.')
                        : tr('El texto original queda archivado y se puede restaurar.'));
  $('pa-diff').innerHTML = diffPromptHtml(d.activo.contenido, p.contenido);
  var dlg = $('prompts-aprobar');
  dlg.returnValue = '';
  var ok = await new Promise(function(resolve) {
    dlg.addEventListener('close', function() { resolve(dlg.returnValue === 'si'); }, { once: true });
    dlg.showModal();
    $('pa-no').focus();
  });
  if (!ok) return;
  var r = await _accionPrompt($('pe-aprobar'), '/api/prompts/' + encodeURIComponent(PROMPTS.clave) + '/aprobar',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version: p.version }) },
    'Versión activada');
  if (r) await _recargarPrompt();
}

async function rechazarPrompt() {
  var motivo = await confirmar({
    titulo: '¿Devolver a borrador?', mensaje: 'No se activa: vuelve a borrador para corregirla, con el motivo a la vista.',
    campo: 'Qué hay que corregir', placeholder: 'Por ejemplo: falta nombrar a Mercado Libre', accion: 'Devolver a borrador'
  });
  if (!motivo) return;
  var d = await _accionPrompt($('pe-rechazar'), '/api/prompts/' + encodeURIComponent(PROMPTS.clave) + '/rechazar',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ motivo: motivo }) },
    'Devuelta a borrador');
  if (d) await _recargarPrompt();
}

async function descartarPrompt() {
  var ok = await confirmar({
    titulo: '¿Descartar el borrador?', mensaje: 'Se borra el cambio sin aprobar. La versión activa sigue igual.',
    accion: 'Descartar borrador'
  });
  if (!ok) return;
  var d = await _accionPrompt($('pe-descartar'), '/api/prompts/' + encodeURIComponent(PROMPTS.clave) + '/borrador',
    { method: 'DELETE' }, 'Borrador descartado');
  if (d) await _recargarPrompt();
}

async function restaurarPrompt(version) {
  var d = PROMPTS.detalle;
  var ok = await confirmar({
    titulo: version ? '¿Restaurar la versión ' + version + '?' : '¿Volver al texto original?',
    mensaje: 'Pasa a revisión: la versión activa sigue igual hasta que la apruebes.'
      + (d.pendiente ? ' El borrador que tenés sin aprobar se reemplaza.' : ''),
    accion: 'Restaurar', peligro: !!d.pendiente
  });
  if (!ok) return;
  var r = await _accionPrompt(null, '/api/prompts/' + encodeURIComponent(PROMPTS.clave) + '/restaurar',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version: version }) },
    'Enviada a revisión');
  if (r) { PROMPTS.tab = 'editar'; await _recargarPrompt(); }
}

function pintarHistorialPrompt() {
  var d = PROMPTS.detalle;
  var filas = [d.activo].concat(d.historial);
  $('pe-historial').innerHTML = filas.map(function(v) {
    var activa = v === d.activo;
    var nombre = v.version ? 'v' + v.version : tr('Texto original');
    var cuando = activa ? (v.aprobado ? tr('Activa desde el') + ' ' + _fechaPrompt(v.aprobado) : tr('Activa'))
      : (v.archivado ? tr('Archivada el') + ' ' + _fechaPrompt(v.archivado) : tr('Archivada'));
    return '<li class="prompts-version-fila' + (activa ? ' activa' : '') + '">'
      + '<div class="prompts-version-cabeza"><strong>' + escHtml(nombre) + '</strong>'
      + '<span class="prompts-version-cuando">' + escHtml(cuando) + '</span>'
      + (activa ? '' : '<button type="button" class="btn btn-sm" data-ver="' + v.version + '">' + escHtml(tr('Ver cambios')) + '</button>'
        + '<button type="button" class="btn btn-sm" data-restaurar="' + v.version + '">' + escHtml(tr('Restaurar')) + '</button>')
      + '</div>'
      + (v.motivo ? '<p class="prompts-version-motivo" translate="no">' + escHtml(v.motivo) + '</p>' : '')
      + '<div class="prompts-diff" hidden translate="no"></div></li>';
  }).join('');
  $('pe-historial').querySelectorAll('[data-ver]').forEach(function(b) {
    b.addEventListener('click', function() {
      var caja = b.closest('li').querySelector('.prompts-diff');
      var v = filas.filter(function(x) { return String(x.version) === b.dataset.ver && x !== d.activo; })[0];
      if (caja.hidden) caja.innerHTML = diffPromptHtml(d.activo.contenido, v.contenido);
      caja.hidden = !caja.hidden;
      b.textContent = tr(caja.hidden ? 'Ver cambios' : 'Ocultar cambios');
    });
  });
  $('pe-historial').querySelectorAll('[data-restaurar]').forEach(function(b) {
    b.addEventListener('click', function() { restaurarPrompt(Number(b.dataset.restaurar)); });
  });
}

async function pintarPromptCompleto() {
  if (PROMPTS.tab !== 'completo' || !PROMPTS.clave) return;
  var pre = $('pe-completo');
  pre.textContent = tr('Armando el prompt…');
  try {
    var d = await pedir('/api/prompts/vista-previa', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clave: PROMPTS.clave, contenido: _promptTexto(), persona: $('pe-persona').value })
    });
    pre.textContent = d.prompt;
  } catch (e) {
    pre.textContent = tr('No se pudo armar la vista previa: ') + e.message;
  }
}

/* Diferencia por líneas (LCS) entre la versión activa y la nueva. Los tramos
   largos sin cambios se resumen para que se vea solo lo que cambia. */
function diffPromptHtml(antes, despues) {
  var a = (antes || '').split('\n'), b = (despues || '').split('\n');
  var n = a.length, m = b.length, i, j;
  var lcs = [];
  for (i = 0; i <= n; i++) { lcs.push(new Array(m + 1).fill(0)); }
  for (i = n - 1; i >= 0; i--) {
    for (j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  var filas = [];
  i = 0; j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { filas.push(['igual', a[i]]); i++; j++; }
    else if (j < m && (i >= n || lcs[i][j + 1] >= lcs[i + 1][j])) { filas.push(['pone', b[j]]); j++; }
    else { filas.push(['quita', a[i]]); i++; }
  }
  if (!filas.some(function(f) { return f[0] !== 'igual'; })) return '<p class="prompts-diff-igual">' + escHtml(tr('Sin cambios.')) + '</p>';
  var html = '', CONTEXTO = 2;
  for (var k = 0; k < filas.length; k++) {
    if (filas[k][0] === 'igual') {
      var fin = k;
      while (fin < filas.length && filas[fin][0] === 'igual') fin++;
      var corrido = fin - k;
      var desde = k === 0 ? 0 : CONTEXTO, hasta = fin === filas.length ? 0 : CONTEXTO;
      if (corrido > desde + hasta + 1) {
        for (var x = k; x < k + desde; x++) html += _filaDiff(filas[x]);
        html += '<div class="diff-salto">' + escHtml(tr('líneas sin cambios')) + ': ' + (corrido - desde - hasta) + '</div>';
        for (x = fin - hasta; x < fin; x++) html += _filaDiff(filas[x]);
        k = fin - 1;
        continue;
      }
    }
    html += _filaDiff(filas[k]);
  }
  return html;
}

function _filaDiff(f) {
  var marca = f[0] === 'pone' ? '+' : f[0] === 'quita' ? '−' : ' ';
  return '<div class="diff-linea ' + f[0] + '"><span class="diff-marca" aria-hidden="true">' + marca + '</span>'
    + '<span class="diff-texto">' + (escHtml(f[1]) || '&nbsp;') + '</span></div>';
}
