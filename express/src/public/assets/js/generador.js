/* generador.js — Modal de la nota y generador de notas.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   GENERATE (STREAMING)
   ═══════════════════════════════════════════════════════════════════════ */
function playClick() {
  try {
    var ctx = new (window.AudioContext || window.webkitAudioContext)();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.frequency.value = 800; gain.gain.value = 0.1;
    osc.start(); osc.stop(ctx.currentTime + 0.06);
  } catch(e) {}
}


/* ═══════════════════════════════════════════════════════════════════════
   VIEW LAST ARTICLE
   ═══════════════════════════════════════════════════════════════════════ */

var _focoAntesNota = null;
function abrirModal() {
  if (!$('modal-art').classList.contains('open')) _focoAntesNota = document.activeElement;
  $('modal-art').classList.add('open');
  document.body.classList.add('modal-abierto');
  document.querySelector('.app-container').inert = true;
  $('actividad-dock').inert = true;
  $('art-body').scrollTop = 0;
  $('modal-art').querySelector('.modal-close').focus();
}
function cerrar() {
  $('modal-art').classList.remove('open');
  document.body.classList.remove('modal-abierto');
  document.querySelector('.app-container').inert = false;
  $('actividad-dock').inert = false;
  var foco = _focoAntesNota;
  if (!foco || !foco.isConnected || !foco.getClientRects().length) foco = $('contenido');
  foco.focus({preventScroll: true});
}
document.addEventListener('keydown', function(ev) {
  if (!$('modal-art').classList.contains('open') || $('confirmar').open) return;
  if (ev.key === 'Escape') { ev.preventDefault(); cerrar(); }
  if (ev.key !== 'Tab') return;
  var controles = Array.from($('modal-art').querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex="0"]'))
    .filter(function(el) { return !el.disabled && el.getClientRects().length; });
  var primero = controles[0], ultimo = controles[controles.length - 1];
  if (ev.shiftKey && document.activeElement === primero) { ev.preventDefault(); ultimo.focus(); }
  else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primero.focus(); }
});

function copiar() {
  navigator.clipboard.writeText($('art-body').textContent);
  log('Texto copiado al portapapeles', 'success');
}

/* ═══════════════════════════════════════════════════════════════════════
   FASE 2: GENERADOR DE NOTAS
   ═══════════════════════════════════════════════════════════════════════ */

var _f2Categorias = [];
var _f2CategoriasActivas = new Set();
var _f2Regiones = [];
var _f2RegionesActivas = new Set();
var _f2Clientes = [];
var _f2ClientesActivos = new Set();
var _f2PuntapieActivo = false;


async function fase2Init() {
  ['f2-tema', 'f2-puntapie-url'].forEach(function(id) { $(id).addEventListener('input', marcarCrear); });
  var form = formulario('crear', {
    leer: function() {
      return {
        categorias: Array.from(_f2CategoriasActivas).sort(),
        regiones: Array.from(_f2RegionesActivas).sort(),
        clientes: Array.from(_f2ClientesActivos).sort(),
        puntapie_activo: _f2PuntapieActivo,
        puntapie_url: $('f2-puntapie-url').value.trim(),
        tema: $('f2-tema').value.trim(),
        largo: $('f2-largo').value
      };
    },
    aplicar: function(st) {
      _f2CategoriasActivas = new Set(st.categorias);
      _f2RegionesActivas = new Set(st.regiones);
      _f2ClientesActivos = new Set(st.clientes);
      pintarToggles('#f2-categorias-grid', _f2CategoriasActivas);
      pintarToggles('#f2-regiones-grid', _f2RegionesActivas);
      renderClientes();
      pintarPuntapie(st.puntapie_activo);
      $('f2-puntapie-url').value = st.puntapie_url;
      $('f2-tema').value = st.tema;
      $('f2-largo').value = st.largo || 'medio';
      resumenCrear();
    },
    guardar: async function(st, base) {
      await pedir('/api/fase2/config', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          categorias: st.categorias, regiones: st.regiones, clientes: st.clientes,
          puntapie_activo: st.puntapie_activo, puntapie_url: st.puntapie_url
        })
      });
      if (st.tema !== base.tema || st.largo !== base.largo) {
        await pedir('/api/generacion-config', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ tema: st.tema, largo: st.largo })
        });
      }
    }
  });
  await Promise.all([fase2CargarCategorias(), fase2CargarRegiones(), fase2CargarClientes()]);
  await fase2CargarConfig();
  form.tomarBase();
  resumenCrear();
  $('f2-persona').addEventListener('change', resumenCrear);
  $('f2-largo').addEventListener('change', marcarCrear);
}

function resumenCrear() {
  pintarToggles('#f2-categorias-grid', _f2CategoriasActivas);
  pintarToggles('#f2-regiones-grid', _f2RegionesActivas);
  var n = _f2CategoriasActivas.size;
  $('crear-resumen').textContent = n ? n + (n === 1 ? ' categoría' : ' categorías') + ' · ' + $('f2-persona').selectedOptions[0].textContent
    + ' · ' + $('f2-largo').selectedOptions[0].textContent.split(' (')[0].toLowerCase() : 'Elegí las categorías de tu nota';
}
function marcarCrear() { resumenCrear(); if (FORMULARIOS.crear) FORMULARIOS.crear.marcar(); }

function pintarToggles(grid, activos) {
  document.querySelectorAll(grid + ' .toggle-item').forEach(function(el) {
    el.classList.toggle('active', activos.has(el.dataset.slug));
    el.setAttribute('aria-pressed', activos.has(el.dataset.slug));
  });
}

function pintarPuntapie(activo) {
  _f2PuntapieActivo = activo;
  $('f2-puntapie-toggle').classList.toggle('active', activo);
  $('f2-puntapie-toggle').setAttribute('aria-checked', activo);
  $('f2-puntapie-label').textContent = activo ? 'Activado' : 'Desactivado';
  $('f2-puntapie-url-wrap').style.display = activo ? 'block' : 'none';
}

async function fase2CargarConfig() {
  try {
    var r = await fetch('/api/fase2/config');
    var d = await r.json();
    if (!d.success) return;
    (d.categorias || []).forEach(function(c) {
      var el = document.querySelector('#f2-categorias-grid .toggle-item[data-slug="' + c + '"]');
      if (el) { _f2CategoriasActivas.add(c); el.classList.add('active'); }
    });
    (d.regiones || []).forEach(function(rg) {
      var el = document.querySelector('#f2-regiones-grid .toggle-item[data-slug="' + rg + '"]');
      if (el) { _f2RegionesActivas.add(rg); el.classList.add('active'); }
    });
    (d.clientes || []).forEach(function(c) {
      _f2ClientesActivos.add(c);
    });
    pintarPuntapie(!!d.puntapie_activo);
    if (d.puntapie_url) $('f2-puntapie-url').value = d.puntapie_url;
    renderClientes();
    var genR = await fetch('/api/generacion-config');
    var genD = await genR.json();
    if (genD.success) {
      if (genD.persona) $('f2-persona').value = genD.persona;
      if (genD.tema) $('f2-tema').value = genD.tema;
      if (genD.largo) $('f2-largo').value = genD.largo;
      if (genD.puntapie_url && !d.puntapie_url) $('f2-puntapie-url').value = genD.puntapie_url;
    }
  } catch(e) {}
}

async function fase2CargarCategorias() {
  try {
    var r = await fetch('/api/fase2/categorias');
    var d = await r.json();
    if (!d.success) return;
    _f2Categorias = d.categorias;
    var totalEjemplos = _f2Categorias.reduce(function(a, c) { return a + (c.ejemplos || 0); }, 0);
    $('f2-ejemplos-badge').textContent = totalEjemplos + ' ejemplos';
    var grid = $('f2-categorias-grid');
    grid.innerHTML = '';
    _f2Categorias.forEach(function(cat) {
      var item = document.createElement('button');
      item.type = 'button';
      item.setAttribute('aria-pressed', 'false');
      item.className = 'toggle-item';
      item.dataset.slug = cat.slug;
      item.setAttribute('aria-label', cat.nombre);
      item.title = (cat.ejemplos || 0) + ' ejemplos de referencia';
      item.innerHTML =
        '<span class="toggle-label">' + escHtml(cat.nombre) + '</span>' +
        '<div style="display:flex;align-items:center;gap:6px">' +
          '<span class="toggle-count">' + (cat.ejemplos || 0) + '</span>' +
          '<span class="selection-check" aria-hidden="true">✓</span>' +
        '</div>';
      item.onclick = function() { fase2ToggleCategoria(cat.slug, item); };
      grid.appendChild(item);
    });
  } catch(e) { console.error('Error cargando categorías:', e); }
}

function fase2ToggleCategoria(slug, el) {
  if (_f2CategoriasActivas.has(slug)) {
    _f2CategoriasActivas.delete(slug);
    el.classList.remove('active');
  } else {
    _f2CategoriasActivas.add(slug);
    el.classList.add('active');
  }
  marcarCrear();
}

async function fase2CargarRegiones() {
  try {
    var r = await fetch('/api/fase2/regiones');
    var d = await r.json();
    if (!d.success) return;
    _f2Regiones = d.regiones;
    var grid = $('f2-regiones-grid');
    grid.innerHTML = '';
    _f2Regiones.forEach(function(reg) {
      var item = document.createElement('button');
      item.type = 'button';
      item.setAttribute('aria-pressed', 'false');
      item.className = 'toggle-item';
      item.dataset.slug = reg.slug;
      item.setAttribute('aria-label', reg.nombre);
      item.title = (reg.ejemplos || 0) + ' ejemplos de referencia';
      item.innerHTML =
        '<span class="toggle-label">' + escHtml(reg.nombre) + '</span>' +
        '<div style="display:flex;align-items:center;gap:6px">' +
          '<span class="toggle-count">' + (reg.ejemplos || 0) + '</span>' +
          '<span class="selection-check" aria-hidden="true">✓</span>' +
        '</div>';
      item.onclick = function() { fase2ToggleRegion(reg.slug, item); };
      grid.appendChild(item);
    });
  } catch(e) { console.error('Error cargando regiones:', e); }
}

function fase2ToggleRegion(slug, el) {
  if (_f2RegionesActivas.has(slug)) {
    _f2RegionesActivas.delete(slug);
    el.classList.remove('active');
  } else {
    _f2RegionesActivas.add(slug);
    el.classList.add('active');
  }
  marcarCrear();
}

async function fase2CargarClientes() {
  try {
    var r = await fetch('/api/fase2/clientes');
    var d = await r.json();
    if (!d.success) return;
    _f2Clientes = d.clientes;
    renderClientes();
  } catch(e) {}
}

function renderClientes() {
  var list = $('f2-clientes-list');
  if (!_f2Clientes.length) {
    list.innerHTML = '<div style="color:var(--text-lo);font-size:0.8rem">Sin clientes cargados. Podés agregar uno abajo.</div>';
    return;
  }
  list.innerHTML = '';
  _f2Clientes.forEach(function(c) {
    var item = document.createElement('div');
    item.className = 'cliente-item toggle-item' + (_f2ClientesActivos.has(c.slug) ? ' active' : '');
    item.innerHTML =
      '<button type="button" class="cliente-seleccion" aria-pressed="' + _f2ClientesActivos.has(c.slug) + '" onclick="fase2ToggleCliente(\'' + encArg(c.slug) + '\', this.parentElement)">' +
        '<span class="cliente-nombre">' + escHtml(c.nombre) + '</span>' +
        (c.sector ? '<span class="cliente-sector">' + escHtml(c.sector) + '</span>' : '') +
      '</button>' +
      '<div style="display:flex;align-items:center;gap:6px">' +
        '<div class="toggle-switch"></div>' +
        '<button class="icon-btn" onclick="fase2EliminarCliente(\'' + encArg(c.slug) + '\')" title="Eliminar" aria-label="Eliminar cliente ' + escHtml(c.nombre) + '">✕</button>' +
      '</div>';
    list.appendChild(item);
  });
}

function fase2ToggleCliente(slug, el) {
  slug = decodeURIComponent(slug);
  if (_f2ClientesActivos.has(slug)) {
    _f2ClientesActivos.delete(slug);
    el.classList.remove('active');
  } else {
    _f2ClientesActivos.add(slug);
    el.classList.add('active');
  }
  el.querySelector('.cliente-seleccion').setAttribute('aria-pressed', _f2ClientesActivos.has(slug));
  marcarCrear();
}

async function fase2AgregarCliente() {
  var nombre = $('f2-cli-nombre').value.trim();
  var desc = $('f2-cli-desc').value.trim();
  if (!nombre) return;
  var st = $('f2-cli-status');
  st.className = 'feedback info';
  st.textContent = 'Guardando...';
  try {
    var r = await fetch('/api/fase2/clientes', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ nombre: nombre, descripcion: desc })
    });
    var d = await r.json();
    if (d.success) {
      st.className = 'feedback ok';
      st.textContent = 'Cliente guardado.';
      $('f2-cli-nombre').value = '';
      $('f2-cli-desc').value = '';
      await fase2CargarClientes();
      showToast('Cliente agregado: ' + nombre, 'success');
    } else {
      st.className = 'feedback err';
      st.textContent = d.error || 'Error';
    }
  } catch(e) { st.className = 'feedback err'; st.textContent = 'Error de conexión'; }
}

async function fase2EliminarCliente(slug) {
  var cliente = _f2Clientes.find(function(c) { return c.slug === slug; });
  var ok = await confirmar({
    titulo: '¿Eliminar este cliente?',
    mensaje: (cliente ? cliente.nombre : slug) + ' deja de estar disponible para mencionarse en las notas. Las notas ya generadas no cambian.',
    accion: 'Eliminar cliente'
  });
  if (!ok) return;
  try {
    await pedir('/api/fase2/clientes/' + encodeURIComponent(slug), { method: 'DELETE' });
    _f2ClientesActivos.delete(slug);
    // El cliente ya no existe: sale también de la config guardada, sin
    // arrastrar los demás cambios sin guardar.
    FORMULARIOS.crear.quitarDeBase('clientes', slug);
    await pedir('/api/fase2/config', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ clientes: FORMULARIOS.crear.base().clientes })
    });
    await fase2CargarClientes();
    marcarCrear();
  } catch(e) {
    showToast('No se pudo eliminar el cliente: ' + e.message, 'error');
  }
}

function togglePuntapie() {
  pintarPuntapie(!_f2PuntapieActivo);
  marcarCrear();
}

async function fase2Scrape() {
  var btn = $('btn-f2-scrape');
  setBtnLoading(btn, true);
  log('--- SINCRONIZANDO EJEMPLOS DE AFTERDRIVE ---', 'warn');
  try {
    var activasArr = Array.from(_f2CategoriasActivas);
    var body = activasArr.length ? { tags: activasArr, max: 5 } : { max: 3 };
    var fin = await correrEnCola('/api/corridas/ejemplos', body, function(l) {
      var type = l.indexOf('[OK]') >= 0 ? 'success' : l.indexOf('[ERROR]') >= 0 ? 'error' : 'info';
      log(l, type);
    }, function(d) {
      if (textoEnCola(d)) log('Sincronización en cola (#' + d.posicion + ').', 'warn');
    });
    if (fin.estado === 'ok') {
      log('Sincronización de ejemplos completada.', 'success');
      showToast('Ejemplos sincronizados', 'success');
    } else {
      log('La sincronización terminó: ' + NOMBRE_ESTADO[fin.estado].toLowerCase() + '.', 'warn');
    }
    await fase2CargarCategorias();
    pintarToggles('#f2-categorias-grid', _f2CategoriasActivas);
  } catch(e) {
    log('Error en sincronización: ' + e.message, 'error');
  } finally {
    setBtnLoading(btn, false);
  }
}

async function fase2GenerarStream() {
  var categorias = Array.from(_f2CategoriasActivas);
  if (!categorias.length) {
    showToast('Seleccioná al menos una categoría', 'warn');
    return;
  }
  var btn = $('btn-f2-generar');
  var st = $('f2-status');
  var cancelar = $('btn-f2-cancelar');
  setBtnLoading(btn, true);
  _f2Corrida = null;
  cancelar.hidden = false;
  cancelar.disabled = true;  // se habilita apenas la cola devuelve el id
  st.className = 'feedback info';
  st.textContent = 'Generando nota...';
  iniciarPasosNota();

  var body = {
    categorias: categorias,
    regiones: Array.from(_f2RegionesActivas).length ? Array.from(_f2RegionesActivas) : [],
    clientes: Array.from(_f2ClientesActivos),
    persona: $('f2-persona').value,
    tema: $('f2-tema').value.trim() || null,
    largo: $('f2-largo').value,
    puntapie_url: (_f2PuntapieActivo && $('f2-puntapie-url').value.trim()) ? $('f2-puntapie-url').value.trim() : null,
  };

  log('--- GENERANDO NOTA FASE 2 [' + categorias.join(', ') + '] ---', 'warn');
  var exito = false;
  try {
    var fullOutput = '';
    var fin = await correrEnCola('/api/corridas/generacion', body, function(l) {
      fullOutput += l + '\n';
      var type = l.indexOf('[OK]') >= 0 ? 'success' : l.indexOf('[ERROR]') >= 0 ? 'error' : 'info';
      log(l.trim(), type);
      var paso = pasoGeneracion(l);
      if (paso && !_f2Cancelando) st.textContent = paso;
      marcarPasoNota(l);
    }, function(d) {
      var t = textoEnCola(d);
      if (_f2Cancelando) return;
      st.textContent = t ? 'Hay otra corrida en curso: tu nota quedó ' + t.toLowerCase().replace('…', '') + '. Se genera apenas termine.'
                         : 'Generando nota...';
    }, function(id) {
      _f2Corrida = id;
      cancelar.disabled = false;
    });
    exito = fin.estado === 'ok' && fullOutput.indexOf('[OK]') >= 0;

    if (exito) {
      cargarUltimaNota();
      cargarResumenHistorial();
      st.className = 'feedback ok';
      st.textContent = 'Nota generada correctamente.';
      showToast('Nota generada', 'success');
      playClick();
    } else if (fin.estado === 'cancelada') {
      st.className = 'feedback info';
      st.textContent = 'Generación cancelada. No se guardó ninguna nota.';
      showToast('Generación cancelada', 'info');
    } else {
      st.className = 'feedback err';
      var motivo = (fullOutput.match(/\[ERROR\]\s*(.+)/) || [])[1];
      st.textContent = 'No se pudo generar la nota.' + (motivo ? ' ' + motivo.trim() : ' Revisá la consola en la vista Desarrollador.');
    }
  } catch(e) {
    log('Error: ' + e.message, 'error');
    st.className = 'feedback err';
    st.textContent = e.message;
  } finally {
    terminarPasosNota(exito);
    setBtnLoading(btn, false);
    cancelar.hidden = true;
    _f2Corrida = null;
    _f2Cancelando = false;
  }
  // Recién ahora se abre la nota: si la evaluación con IA tarda (o el
  // proveedor reintenta), el botón ya está libre para generar otra.
  if (exito) fase2MostrarUltima();
}

var _f2Corrida = null;      // id de la Corrida de la nota que se está generando
var _f2Cancelando = false;

/* Corta la nota en curso (o la saca de la cola si todavía no empezó).
   La IA se detiene en el próximo fragmento o llamada y la nota no se guarda. */
async function cancelarGeneracion() {
  if (!_f2Corrida || _f2Cancelando) return;
  var ok = await confirmar({
    titulo: '¿Cancelar la nota?',
    mensaje: 'Se corta la generación y no se guarda nada. Lo que la IA ya procesó igual se cobra si usás la API paga.',
    accion: 'Cancelar la nota',
    cancelar: 'Seguir generando'
  });
  if (!ok || !_f2Corrida) return;
  var btn = $('btn-f2-cancelar'), st = $('f2-status');
  _f2Cancelando = true;
  btn.disabled = true;
  st.className = 'feedback info';
  st.textContent = 'Cancelando… la IA se detiene en unos segundos.';
  try {
    await pedir('/api/corridas/' + _f2Corrida + '/cancelar', { method: 'POST' });
    log('Generación cancelada desde el dashboard.', 'warn');
  } catch (e) {
    _f2Cancelando = false;
    btn.disabled = false;
    showToast(e.message, 'error');
  }
  refrescarCorridas();
}

async function fase2VerUltima() {
  await fase2MostrarUltima();
}

function fase2VerHistorial() {
  irASeccion('historial');
  _hist.seccion = 'generados_aprobados';
  _hist.estado = 'todos';
  cargarHistorial(1);
}

async function fase2MostrarUltima(id) {
  try {
    var r = await fetch(id ? '/api/fase2/notas/' + id : '/api/fase2/ultima-nota');
    var d = await r.json();
    if (!d.success) {
      showToast('No hay notas generadas aún', 'warn');
      return;
    }
    var modal = $('modal-art');
    var body = $('art-body');
    var check = $('check-list');
    var comm = $('eval-comms');
    $('modal-titulo').textContent = id ? 'Nota' : 'Última nota';
    $('modal-meta').textContent = d.nota.generado_en ? 'Generada el ' + new Date(d.nota.generado_en).toLocaleString('es-AR', {
      day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'
    }) : '';
    abrirModal();
    body.innerHTML = DOMPurify.sanitize(marked.parse(d.nota.contenido));
    check.innerHTML = '';
    comm.textContent = '';
    _notaActual = { coleccion: 'notas_fase2', id: d.nota._id, estado: d.nota.estado || 'borrador',
                    contenido: d.nota.contenido, hubspot: d.nota.hubspot || null };
    pintarAccionesNota();
    var lugarCalificacion = document.createElement('div');
    check.appendChild(lugarCalificacion);
    pintarCalificacion(d.nota, lugarCalificacion);

    var cal = d.nota.calidad;
    if (cal && cal.puntaje !== null && cal.puntaje !== undefined) {
      var res = document.createElement('div');
      res.className = 'calidad-resumen' + (cal.fallas_criticas && cal.fallas_criticas.length ? ' con-fallas' : '');
      res.innerHTML = '<strong>' + cal.puntaje + '/9</strong> lineamientos cumplidos'
        + (cal.reescrita_por && cal.reescrita_por.length
            ? '<span>' + (cal.segundo_intento === 'correccion' ? 'Se corrigió' : 'Se reescribió') + ' porque falló en: '
              + escHtml(cal.reescrita_por.join(', ').replace(/_/g, ' ')) + '.</span>' : '')
        + (cal.fallas_criticas && cal.fallas_criticas.length
            ? '<span>Revisala antes de publicar: sigue fallando en ' + escHtml(cal.fallas_criticas.join(', ').replace(/_/g, ' ')) + '.</span>' : '');
      check.appendChild(res);
    }
    pintarRevisionNota(d.nota, check);

    if (d.nota.categorias && d.nota.categorias.length) {
      var info = document.createElement('div');
      info.style.cssText = 'margin-bottom:12px;font-size:0.8rem;color:var(--text-lo)';
      info.textContent = 'Categorías: ' + d.nota.categorias.join(', ');
      if (d.nota.puntapie_url) info.textContent += ' | Puntapié: ' + d.nota.puntapie_url;
      check.appendChild(info);
    }

    if (d.nota.fuentes && d.nota.fuentes.length) {
      var fu = document.createElement('details');
      fu.open = true;
      fu.className = 'fuentes-nota';
      fu.innerHTML = '<summary class="fuentes-nota-titulo">Noticias usadas</summary>' + d.nota.fuentes.map(function(f) {
        return '<a href="' + urlSegura(f.url) + '" target="_blank" rel="noopener">' + escHtml(f.titulo) + '</a>';
      }).join('');
      check.appendChild(fu);
    }

    var evaluando = document.createElement('div');
    evaluando.className = 'evaluando';
    evaluando.textContent = 'Evaluando la nota...';
    var evD = { success: false };
    if (d.nota.evaluacion) {
      evD = { success: true, evaluation: d.nota.evaluacion };   // guardada al generar
    } else try {
      check.appendChild(evaluando);
      var evR = await fetch('/api/evaluate-article', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ articulo: d.nota.contenido })
      });
      evD = await evR.json();
    } catch(e) {}
    evaluando.remove();
    if (!evD.success) {
      var nd = document.createElement('div');
      nd.className = 'evaluando-no';
      nd.style.cssText = 'font-size:0.8rem;color:var(--text-lo)';
      nd.textContent = 'La evaluación no está disponible ahora.';
      check.appendChild(nd);
    }
    if (evD.success) {
      var criterios = document.createElement('details');
      criterios.className = 'revision-criterios';
      criterios.innerHTML = '<summary>Ver criterios automáticos</summary>';
      check.appendChild(criterios);
      Object.entries(evD.evaluation.lineamientos || evD.evaluation).forEach(function(entry) {
        var k = entry[0], v = entry[1];
        var item = document.createElement('div');
        item.className = 'check-item ' + (v ? 'ok' : 'fail');
        item.innerHTML = '<div class="check-dot"></div> ' + escHtml(k === 'sin_alucinaciones' ? 'Sin indicios de invención detectados' : k.replace(/_/g, ' '));
        criterios.appendChild(item);
      });
      if (evD.evaluation.comentarios) comm.textContent = evD.evaluation.comentarios;
    }
  } catch(e) { showToast('Error al cargar nota', 'error'); }
}
