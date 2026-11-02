/* prompts.js — Prompts de redacción editables, con aprobación.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Cada pieza del prompt (identidad, audiencia, reglas, enfoque Alephee,
   formato, SEO, respuesta y las 5 personas) es Markdown. Se ve el prompt
   completo como un archivo, con números de línea; "Editar" abre la pieza
   elegida ahí mismo y, con un borrador, lo que cambia queda marcado en verde
   (entra) y rojo (sale) dentro del prompt. Recorrido:
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
  modo: 'ver',          // ver | editar | historial
  activas: [],          // el prompt activo, por partes (/api/prompts/vista-previa)
  conBorrador: null,    // el mismo con el texto del editor, si cambia algo
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
  var espera = null;
  $('pe-texto').addEventListener('input', function() {
    _ajustarAlto();
    pintarAccionesPrompt();
    clearTimeout(espera);
    espera = setTimeout(validarPrompt, 400);
  });
  $('pe-motivo').addEventListener('input', pintarAccionesPrompt);
  $('pe-persona').addEventListener('change', function() { refrescarArchivoPrompt(); });
  $('pe-editar').addEventListener('click', function() { modoPrompt(PROMPTS.modo === 'editar' ? 'ver' : 'editar'); });
  $('pe-ver-historial').addEventListener('click', function() { modoPrompt(PROMPTS.modo === 'historial' ? 'ver' : 'historial'); });
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
  var html = '<ul class="prompts-leyenda" aria-label="' + escHtml(tr('Estados')) + '">'
    + '<li class="estado-original">' + escHtml(tr('Original')) + '</li><li class="estado-editada">' + escHtml(tr('Editada')) + '</li>'
    + '<li class="estado-borrador">' + escHtml(tr('Borrador')) + '</li><li class="estado-en_revision">' + escHtml(tr('En revisión')) + '</li></ul>';
  Object.keys(grupos).forEach(function(g) {
    html += '<p class="prompts-grupo">' + escHtml(grupos[g]) + '</p>';
    PROMPTS.piezas.filter(function(p) { return p.grupo === g; }).forEach(function(p) {
      var pend = p.pendiente;
      // Una sola etiqueta: lo pendiente manda; si no, si la activa es la original o una editada.
      var estado = pend ? pend.estado : (p.version_activa ? 'editada' : 'original');
      var etiqueta = pend ? _ESTADOS_PROMPT[pend.estado] : (p.version_activa ? 'v' + p.version_activa : 'Original');
      html += '<button type="button" class="prompts-item estado-' + estado + (p.clave === PROMPTS.clave ? ' activo' : '') + '" data-clave="' + escHtml(p.clave) + '"'
        + (p.clave === PROMPTS.clave ? ' aria-current="true"' : '') + '>'
        + '<span class="prompts-item-punto" aria-hidden="true"></span>'
        + '<span class="prompts-item-nombre">' + escHtml(p.titulo) + '</span>'
        + '<span class="prompts-chip ' + estado + '">' + escHtml(etiqueta) + '</span>'
        + '</button>';
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
  $('pe-grupo').textContent = tr(item && item.grupo === 'persona' ? 'Persona' : 'Base del prompt');
  var esPersona = d.clave.indexOf('persona_') === 0;
  $('pe-persona').disabled = esPersona;
  if (esPersona) $('pe-persona').value = d.clave.slice(8);
  PROMPTS.validacion = null;
  validarPrompt();
  pintarHistorialPrompt();
  modoPrompt(PROMPTS.modo === 'historial' ? 'historial' : 'ver', true);
  pintarAccionesPrompt();
  refrescarArchivoPrompt(true);
}

/* ver: el prompt completo, como un archivo. editar: la pieza elegida se abre en su lugar.
   historial: las versiones de la pieza. */
function modoPrompt(modo, sinRefrescar) {
  PROMPTS.modo = modo;
  var editando = modo === 'editar';
  $('pe-editar').innerHTML = editando ? escHtml(tr('Listo')) : '<span aria-hidden="true">✎</span> ' + escHtml(tr('Editar'));
  $('pe-editar').setAttribute('aria-pressed', editando ? 'true' : 'false');
  $('pe-ver-historial').setAttribute('aria-pressed', modo === 'historial' ? 'true' : 'false');
  $('pe-archivo-cuerpo').hidden = modo === 'historial';
  $('pe-historial-panel').hidden = modo !== 'historial';
  pintarAccionesPrompt();
  if (sinRefrescar) return;
  if (editando) {
    pintarArchivoPrompt();
    var bloque = $('pe-texto').closest('.pa-bloque');
    if (bloque) bloque.scrollIntoView({ block: 'nearest' });
    $('pe-texto').focus({ preventScroll: true });
  } else if (modo === 'ver') {
    refrescarArchivoPrompt();
  }
}

/* Pide el prompt activo y, si el texto del editor cambia algo, el mismo con ese texto. */
async function refrescarArchivoPrompt(irAPieza) {
  if (!PROMPTS.clave) return;
  var persona = $('pe-persona').value, texto = _promptTexto(), clave = PROMPTS.clave;
  var cuerpo = function(extra) {
    return { method: 'POST', headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify(Object.assign({ persona: persona }, extra || {})) };
  };
  try {
    var activas = await pedir('/api/prompts/vista-previa', cuerpo());
    var cambia = PROMPTS.detalle && texto.trim() !== PROMPTS.detalle.activo.contenido.trim();
    var borrador = cambia ? await pedir('/api/prompts/vista-previa', cuerpo({ clave: clave, contenido: texto })) : null;
    if (clave !== PROMPTS.clave) return;   // mientras tanto se eligió otra pieza
    PROMPTS.activas = activas.partes;
    PROMPTS.conBorrador = borrador ? borrador.partes : null;
  } catch (e) {
    $('pe-archivo-cuerpo').innerHTML = '<p class="prompts-vacio">' + escHtml(tr('No se pudo armar la vista previa: ') + e.message) + '</p>';
    return;
  }
  pintarArchivoPrompt();
  if (irAPieza) {
    var sel = $('pe-archivo-cuerpo').querySelector('.pa-bloque.elegido');
    if (sel) $('pe-archivo-cuerpo').scrollTop = sel.offsetTop - 8;
  }
}

function _filasPrompt(lineas, clase, num, tramos) {
  return lineas.map(function(l) {
    var n = clase === 'quita' ? '' : num.valor++;
    var marca = clase === 'pone' ? '+' : clase === 'quita' ? '−' : '';
    return '<div class="pa-linea' + (clase ? ' ' + clase : '') + (tramos ? ' par' : '') + '"><span class="pa-num">' + n + '</span>'
      + '<span class="pa-marca" aria-hidden="true">' + marca + '</span><span class="pa-txt">' + _textoConTramos(l, tramos) + '</span></div>';
  }).join('');
}

/* El prompt completo, con números de línea. La pieza elegida queda resaltada; con un
   borrador, sus líneas muestran lo que entra y lo que sale. Editando, el texto se edita en su lugar. */
function pintarArchivoPrompt() {
  var caja = $('pe-archivo-cuerpo');
  if (!PROMPTS.activas.length) return;
  $('pe-guardado').appendChild($('pe-texto'));   // sacarlo antes de pisar el HTML
  var partes = PROMPTS.conBorrador || PROMPTS.activas, num = { valor: 1 }, html = '';
  var lineas = 0;
  partes.forEach(function(parte, i) {
    var elegido = parte.clave === PROMPTS.clave;
    var activa = PROMPTS.activas[i] || parte;
    var cuerpo;
    if (elegido && PROMPTS.modo === 'editar') {
      cuerpo = '<div class="pa-editor" id="pe-editor-lugar"></div>';
    } else if (elegido && PROMPTS.conBorrador && activa.texto !== parte.texto) {
      cuerpo = _diffPrompt(activa.texto, parte.texto, num);
    } else {
      cuerpo = _filasPrompt(parte.texto.split('\n'), '', num);
    }
    lineas += parte.texto.split('\n').length;
    var etiqueta = parte.editable
      ? '<button type="button" class="pa-abrir" data-clave="' + escHtml(parte.clave) + '">' + escHtml(tr(parte.titulo))
        + (elegido ? '' : ' <span aria-hidden="true">✎</span>') + '</button>'
      : '<span class="pa-auto">' + escHtml(tr(parte.titulo)) + ' · ' + escHtml(tr('lo arma el sistema')) + '</span>';
    html += '<section class="pa-bloque' + (elegido ? ' elegido' : '') + (parte.editable ? '' : ' automatico') + '">'
      + '<div class="pa-bloque-cabeza">' + etiqueta + '</div>' + cuerpo + '</section>';
  });
  caja.innerHTML = html;
  $('pe-archivo-lineas').textContent = lineas + ' ' + tr('líneas');
  var lugar = $('pe-editor-lugar');
  if (lugar) { lugar.appendChild($('pe-texto')); _ajustarAlto(); }
  caja.querySelectorAll('.pa-abrir').forEach(function(b) {
    b.addEventListener('click', async function() {
      if (b.dataset.clave !== PROMPTS.clave) await elegirPrompt(b.dataset.clave);
      if (b.dataset.clave === PROMPTS.clave) modoPrompt('editar');
    });
  });
}

function _ajustarAlto() {
  var t = $('pe-texto');
  t.style.height = 'auto';
  t.style.height = Math.max(120, t.scrollHeight + 2) + 'px';
}

function _diffPrompt(antes, despues, num) {
  return _lineasDiff(antes, despues).map(function(f) { return _filasPrompt([f[1]], f[0] === 'igual' ? '' : f[0], num, f[2]); }).join('');
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
  var errores = PROMPTS.validacion ? PROMPTS.validacion.errores.length : 0;
  var pasos = ['', '', '', ''], notas = ['Escribí el cambio', 'Sin errores', 'Esperando tu aprobación', 'La usa la IA'];
  if (estado === 'activo') {
    pasos = ['hecho', 'hecho', 'hecho', 'actual'];
    notas[3] = d.activo.version ? tr('La usa la IA') + ' · v' + d.activo.version : 'La usa la IA · texto original';
  } else if (estado === 'en_revision') {
    pasos = ['hecho', 'hecho', 'actual', ''];
  } else if (errores) {
    pasos = ['actual', 'error', '', ''];
    notas[0] = 'Corregí lo marcado abajo';
    notas[1] = errores === 1 ? 'Hay 1 error' : 'Hay ' + errores + ' errores';
  } else if (igualActiva || !PROMPTS.validacion) {
    pasos = ['actual', '', '', ''];
  } else {
    // Escrito y sin errores: falta enviarlo. El paso 3 queda marcado como el próximo.
    pasos = ['hecho', 'hecho', 'siguiente', ''];
    notas[2] = 'Falta enviarla';
  }
  document.querySelectorAll('#pe-pasos li').forEach(function(li, i) {
    li.className = pasos[i];
    li.querySelector('small').textContent = tr(notas[i]);
    if (pasos[i] === 'actual') li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
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
  $('pe-aviso').className = 'prompts-aviso ' + (p && p.rechazo && estado === 'borrador' ? 'rechazo' : estado);

  // El motivo se pide al editar o mientras haya un cambio sin aprobar.
  $('pe-motivo-campo').hidden = PROMPTS.modo !== 'editar' && estado === 'activo';

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
  if (r) { PROMPTS.modo = 'ver'; await _recargarPrompt(); }
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

/* Diferencia por líneas (LCS) entre la versión activa y la nueva. Los tramos
   largos sin cambios se resumen para que se vea solo lo que cambia. */
function _lineasDiff(antes, despues) {
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
    else if (i < n && (j >= m || lcs[i + 1][j] >= lcs[i][j + 1])) { filas.push(['quita', a[i]]); i++; }
    else { filas.push(['pone', b[j]]); j++; }
  }
  return _emparejarLineas(filas);
}

/* Una tanda de líneas que salen seguida de otra que entra: la 1ª que sale con la 1ª que
   entra, y así. Si se parecen, cada una lleva en f[2] sus tramos [cambió, texto]: así se
   marca solo lo que cambió de verdad (una letra, una palabra) y no la oración entera. */
function _emparejarLineas(filas) {
  for (var k = 0; k < filas.length; k++) {
    if (filas[k][0] !== 'quita') continue;
    var q0 = k;
    while (k < filas.length && filas[k][0] === 'quita') k++;
    var p0 = k;
    while (k < filas.length && filas[k][0] === 'pone') k++;
    for (var x = 0; x < Math.min(p0 - q0, k - p0); x++) {
      var t = _tramosLinea(filas[q0 + x][1], filas[p0 + x][1]);
      if (t) { filas[q0 + x][2] = t.antes; filas[p0 + x][2] = t.despues; }
    }
    k--;
  }
  return filas;
}

/* Diferencia letra por letra entre dos versiones de una línea. Los pedacitos iguales de
   1 o 2 letras entre dos cambios se suman al cambio (si no, queda una sopa de marcas).
   null si cambió casi toda: ahí se marca la línea entera. */
function _tramosLinea(a, b) {
  if (!a || !b || a.length > 1500 || b.length > 1500) return null;
  var n = a.length, m = b.length, i, j;
  var lcs = [];
  for (i = 0; i <= n; i++) lcs.push(new Uint16Array(m + 1));
  for (i = n - 1; i >= 0; i--) {
    for (j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  var ops = [];   // ['=', texto] | ['-', texto] | ['+', texto]
  function sumar(op, ch) {
    if (ops.length && ops[ops.length - 1][0] === op) ops[ops.length - 1][1] += ch;
    else ops.push([op, ch]);
  }
  i = 0; j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { sumar('=', a[i]); i++; j++; }
    else if (i < n && (j >= m || lcs[i + 1][j] >= lcs[i][j + 1])) { sumar('-', a[i]); i++; }
    else { sumar('+', b[j]); j++; }
  }
  var antes = [], despues = [], cambiadas = 0;
  ops.forEach(function(op, x) {
    var chico = op[0] === '=' && op[1].length <= 2 && x > 0 && x < ops.length - 1;
    if (op[0] === '=' && !chico) { antes.push([false, op[1]]); despues.push([false, op[1]]); return; }
    if (op[0] !== '+') { antes.push([true, op[1]]); cambiadas += op[1].length; }
    if (op[0] !== '-') { despues.push([true, op[1]]); cambiadas += op[0] === '+' ? op[1].length : 0; }
  });
  if (cambiadas > 0.6 * (n + m)) return null;
  return { antes: _unirTramos(antes), despues: _unirTramos(despues) };
}

function _unirTramos(tramos) {
  var r = [];
  tramos.forEach(function(t) {
    if (r.length && r[r.length - 1][0] === t[0]) r[r.length - 1][1] += t[1];
    else r.push([t[0], t[1]]);
  });
  return r;
}

/* El texto de una línea, con lo que cambió marcado si hay tramos. */
function _textoConTramos(texto, tramos) {
  if (!tramos) return escHtml(texto) || '&nbsp;';
  return tramos.map(function(t) { return t[0] ? '<mark class="cambio">' + escHtml(t[1]) + '</mark>' : escHtml(t[1]); }).join('') || '&nbsp;';
}

function diffPromptHtml(antes, despues) {
  var filas = _lineasDiff(antes, despues);
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
  return '<div class="diff-linea ' + f[0] + (f[2] ? ' par' : '') + '"><span class="diff-marca" aria-hidden="true">' + marca + '</span>'
    + '<span class="diff-texto">' + _textoConTramos(f[1], f[2]) + '</span></div>';
}
