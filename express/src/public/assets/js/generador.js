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
  fondoInerte(true);
  $('art-body').scrollTop = 0;
  $('modal-art').querySelector('.modal-close').focus();
}
function cerrar() {
  $('modal-art').classList.remove('open');
  document.body.classList.remove('modal-abierto');
  fondoInerte(false);
  var foco = _focoAntesNota;
  if (!foco || !foco.isConnected || !foco.getClientRects().length) foco = $('contenido');
  foco.focus({preventScroll: true});
}
/* Con la nota abierta, lo de atrás no responde. Salvo la barra de íconos (vista Cliente
   en escritorio): queda a la vista junto a la nota y se puede usar para ir a otra sección. */
function fondoInerte(si) {
  var riel = si && document.documentElement.getAttribute('data-modo') === 'cliente' && window.matchMedia('(min-width: 901px)').matches;
  document.querySelector('.app-container').inert = si && !riel;
  [$('contenido'), $('menu-movil'), document.querySelector('.header-right')].forEach(function(el) {
    if (el) el.inert = si && riel;
  });
  $('actividad-dock').inert = si;
}
function notaAbierta() { return $('modal-art').classList.contains('open'); }

// Ir a otra sección con la nota abierta la cierra (si se está editando el texto, pregunta antes).
async function cerrarNotaParaNavegar() {
  if (!notaAbierta()) return true;
  if ($('editor-nota') && !(await confirmar({ titulo: '¿Salir sin guardar?', mensaje: 'Estás editando el texto de la nota y los cambios no se guardaron.',
                                                accion: 'Salir sin guardar', cancelar: 'Seguir editando' }))) return false;
  cerrar();
  return true;
}

document.addEventListener('keydown', function(ev) {
  if (!$('modal-art').classList.contains('open') || $('confirmar').open) return;
  if (ev.key === 'Escape') {
    ev.preventDefault();
    if ($('nota-menu') && !$('nota-menu').hidden) { alternarMenuNota(false); $('nota-mas').focus(); }
    else cerrar();
  }
  if (ev.key !== 'Tab') return;
  var controles = Array.from($('modal-art').querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex="0"]'))
    .filter(function(el) { return !el.disabled && el.getClientRects().length; });
  var primero = controles[0], ultimo = controles[controles.length - 1];
  if (ev.shiftKey && document.activeElement === primero) { ev.preventDefault(); ultimo.focus(); }
  else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primero.focus(); }
});

function tituloDeNota(md) {
  var m = String(md || '').match(/^#\s+(.+)$/m);
  return m ? m[1].trim() : '';
}

function copiar() {
  navigator.clipboard.writeText(($('nota-texto') || $('art-body')).textContent);
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
var _f2RotarCategorias = false;


async function fase2Init() {
  // El tema y las indicaciones son solo para la próxima nota: no se guardan ni marcan cambios.
  $('f2-puntapie-url').addEventListener('input', marcarCrear);
  var form = formulario('crear', {
    leer: function() {
      return {
        categorias: Array.from(_f2CategoriasActivas).sort(),
        regiones: Array.from(_f2RegionesActivas).sort(),
        clientes: Array.from(_f2ClientesActivos).sort(),
        puntapie_activo: _f2PuntapieActivo,
        puntapie_url: $('f2-puntapie-url').value.trim(),
        rotar_categorias: _f2RotarCategorias,
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
      pintarRotarCategorias(!!st.rotar_categorias);
      $('f2-puntapie-url').value = st.puntapie_url;
      $('f2-largo').value = st.largo || 'medio';
      resumenCrear();
    },
    guardar: async function(st, base) {
      await pedir('/api/fase2/config', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          categorias: st.categorias, regiones: st.regiones, clientes: st.clientes,
          puntapie_activo: st.puntapie_activo, puntapie_url: st.puntapie_url,
          rotar_categorias: st.rotar_categorias
        })
      });
      if (st.largo !== base.largo) {
        await pedir('/api/generacion-config', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ largo: st.largo })
        });
      }
    }
  });
  await Promise.all([fase2CargarCategorias(), fase2CargarRegiones(), fase2CargarClientes()]);
  await fase2CargarConfig();
  form.tomarBase();
  resumenCrear();
  $('f2-persona').addEventListener('change', resumenCrear);
  document.addEventListener('idioma', resumenCrear);
  $('f2-largo').addEventListener('change', marcarCrear);
  var panel = document.querySelector('.fase2-section');
  panel.inert = false;
  panel.setAttribute('aria-busy', 'false');
}

// Las notas se escriben siempre en el idioma principal (lo dice /api/fase2/config); las regiones eligen el mercado.
var _idiomaPrincipal = 'pt';
function idiomaNotaElegido() {
  return {es:'Español rioplatense', pt:'Português do Brasil', en:'English'}[_idiomaPrincipal] || 'Português do Brasil';
}
var TONOS = { comercial: 'Comercial', analitico: 'Analítico-Técnico', periodistico: 'Periodístico', divulgativo: 'Divulgativo', ejecutivo: 'Ejecutivo' };
var LARGOS = { corto: 'Corto', medio: 'Medio', largo: 'Largo' };

/* El resumen de la nota: en Desarrollador, una línea ("2 categorías · Comercial · …");
   en Cliente, el panel "Tu nota" con cada cosa en su renglón. */
function resumenCrear() {
  pintarToggles('#f2-categorias-grid', _f2CategoriasActivas);
  pintarToggles('#f2-regiones-grid', _f2RegionesActivas);
  pintarChipsSelect('f2-persona');
  pintarChipsSelect('f2-largo');
  var n = _f2CategoriasActivas.size;
  $('idioma-nota-valor').textContent = tr(idiomaNotaElegido());
  var fila = function(clave, valor, clase) {
    return '<span class="cr-item' + (clase ? ' ' + clase : '') + '"><span class="cr-k">' + escHtml(tr(clave)) + '</span><span class="cr-v">' + escHtml(valor) + '</span></span>';
  };
  var temas = n ? n + ' ' + tr(n === 1 ? 'categoría' : 'categorías') + (_f2RotarCategorias && n > 1 ? ' · ' + tr('rotando') : '') : tr('Elegí las categorías de tu nota');
  $('crear-resumen').innerHTML = fila('Temas', temas, n ? '' : 'falta')
    + fila('Tono', tr(TONOS[$('f2-persona').value]))
    + fila('Extensión', tr(LARGOS[$('f2-largo').value] || ''), 'cr-largo')
    + fila('Idioma', tr(idiomaNotaElegido()));
}

/* Vista Cliente: el tono y el largo se eligen con botones (el select queda para
   Desarrollador y para guardar; los botones solo cambian su valor). */
var AYUDA_CHIPS = {
  'f2-persona': { comercial: 'Muestra el valor y llama a la acción', analitico: 'Datos, cifras y precisión técnica',
                  periodistico: 'Cuenta qué pasó y por qué importa', divulgativo: 'Explica simple, para cualquiera',
                  ejecutivo: 'Directo, para quien decide' },
  'f2-largo': { corto: '500 a 700 palabras', medio: '700 a 1000 palabras', largo: '1000 a 1400 palabras' }
};
function pintarChipsSelect(id) {
  var sel = $(id), cont = $(id + '-chips');
  if (!sel || !cont) return;
  if (!cont.children.length) {
    cont.innerHTML = Array.from(sel.options).map(function(o) {
      var nombre = id === 'f2-largo' ? LARGOS[o.value] : TONOS[o.value];
      return '<button type="button" role="radio" class="f2-chip" data-valor="' + escHtml(o.value) + '" aria-checked="false" tabindex="-1">'
        + '<b>' + escHtml(nombre || o.textContent) + '</b><small>' + escHtml((AYUDA_CHIPS[id] || {})[o.value] || '') + '</small></button>';
    }).join('');
    cont.addEventListener('click', function(ev) {
      var b = ev.target.closest('.f2-chip');
      if (b) elegirChip(id, b.dataset.valor);
    });
    // Radios: las flechas mueven la elección.
    cont.addEventListener('keydown', function(ev) {
      var paso = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
      if (!paso) return;
      ev.preventDefault();
      var i = (sel.selectedIndex + paso + sel.options.length) % sel.options.length;
      elegirChip(id, sel.options[i].value);
      cont.querySelector('[aria-checked="true"]').focus();
    });
  }
  cont.querySelectorAll('.f2-chip').forEach(function(b) {
    var on = b.dataset.valor === sel.value;
    b.setAttribute('aria-checked', on);
    b.tabIndex = on ? 0 : -1;
  });
}
function elegirChip(id, valor) {
  var sel = $(id);
  if (sel.value === valor) return;
  sel.value = valor;
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  pintarChipsSelect(id);
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
    if (d.idioma_principal) _idiomaPrincipal = d.idioma_principal;
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
    pintarRotarCategorias(!!d.rotar_categorias);
    if (d.puntapie_url) $('f2-puntapie-url').value = d.puntapie_url;
    renderClientes();
    var genR = await fetch('/api/generacion-config');
    var genD = await genR.json();
    if (genD.success) {
      if (genD.persona) $('f2-persona').value = genD.persona;
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

function esProhibido(c) { return c.modo === 'no_mencionar'; }

function renderClientes() {
  var list = $('f2-clientes-list'), prohibidos = $('f2-prohibidos-list');
  var paraMencionar = _f2Clientes.filter(function(c) { return !esProhibido(c); });
  var noNombrar = _f2Clientes.filter(esProhibido);
  // Uno que pasó a "no nombrar" deja de estar elegido.
  noNombrar.forEach(function(c) { _f2ClientesActivos.delete(c.slug); });
  if (!paraMencionar.length) {
    list.innerHTML = '<div style="color:var(--text-lo);font-size:0.8rem">Sin clientes para mencionar. Podés agregar uno abajo.</div>';
  } else {
    list.innerHTML = '';
    paraMencionar.forEach(function(c) {
      var item = document.createElement('div');
      item.className = 'cliente-item toggle-item' + (_f2ClientesActivos.has(c.slug) ? ' active' : '');
      item.innerHTML =
        '<button type="button" class="cliente-seleccion" aria-pressed="' + _f2ClientesActivos.has(c.slug) + '" onclick="fase2ToggleCliente(\'' + encArg(c.slug) + '\', this.parentElement)">' +
          '<span class="cliente-nombre">' + escHtml(c.nombre) + '</span>' +
          (c.sector ? '<span class="cliente-sector">' + escHtml(c.sector) + '</span>' : '') +
        '</button>' +
        '<div style="display:flex;align-items:center;gap:6px">' +
          '<div class="toggle-switch"></div>' +
          '<button class="icon-btn" onclick="fase2ModoCliente(\'' + encArg(c.slug) + '\', \'no_mencionar\')" title="No nombrar nunca" aria-label="No nombrar nunca a ' + escHtml(c.nombre) + '">⊘</button>' +
          '<button class="icon-btn" onclick="fase2EliminarCliente(\'' + encArg(c.slug) + '\')" title="Eliminar" aria-label="Eliminar cliente ' + escHtml(c.nombre) + '">✕</button>' +
        '</div>';
      list.appendChild(item);
    });
  }
  prohibidos.innerHTML = noNombrar.length
    ? noNombrar.map(function(c) {
        return '<span class="cliente-prohibido" title="' + escHtml(c.descripcion || '') + '">' + escHtml(c.nombre)
          + '<button type="button" class="icon-btn" onclick="fase2ModoCliente(\'' + encArg(c.slug) + '\', \'mencionar\')" title="Permitir mencionarla" aria-label="Permitir mencionar a ' + escHtml(c.nombre) + '">↺</button>'
          + '<button type="button" class="icon-btn" onclick="fase2EliminarCliente(\'' + encArg(c.slug) + '\')" title="Eliminar" aria-label="Eliminar ' + escHtml(c.nombre) + '">✕</button></span>';
      }).join('')
    : '<div style="color:var(--text-lo);font-size:0.8rem">Ninguna por ahora.</div>';
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
  var modo = $('f2-cli-modo').value;
  if (!nombre) return;
  var st = $('f2-cli-status');
  st.className = 'feedback info';
  st.textContent = 'Guardando...';
  try {
    var r = await fetch('/api/fase2/clientes', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ nombre: nombre, descripcion: desc, modo: modo })
    });
    var d = await r.json();
    if (d.success) {
      st.className = 'feedback ok';
      st.textContent = modo === 'no_mencionar' ? 'Guardada: ninguna nota la va a nombrar.' : 'Cliente guardado.';
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

/* La lista que pasan, de una vez. Confirma antes: con "Ninguna se nombra" cambia qué pueden decir las notas. */
async function fase2ImportarClientes() {
  var texto = $('f2-cli-lista').value.trim();
  var modo = $('f2-cli-lista-modo').value;
  var st = $('f2-cli-status');
  if (!texto) { st.className = 'feedback err'; st.textContent = 'Pegá la lista: una empresa por línea.'; return; }
  var lineas = texto.split('\n').filter(function(l) { return l.trim(); }).length;
  var ok = await confirmar({
    titulo: modo === 'no_mencionar' ? '¿Cargar la lista de empresas que no se nombran?' : '¿Cargar la lista de clientes?',
    mensaje: lineas + (lineas === 1 ? ' empresa' : ' empresas') + (modo === 'no_mencionar'
      ? ': ninguna nota las va a nombrar. Las que ya estaban cargadas pasan a este modo.'
      : ': quedan disponibles para mencionar en las notas. Las que ya estaban cargadas pasan a este modo.'),
    accion: 'Cargar lista'
  });
  if (!ok) return;
  var btn = $('btn-cli-importar');
  setBtnLoading(btn, true);
  try {
    var d = await pedir('/api/fase2/clientes/importar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ texto: texto, modo: modo })
    });
    st.className = 'feedback ok';
    st.textContent = 'Lista cargada: ' + d.nuevos + ' nuevas y ' + d.actualizados + ' actualizadas.';
    $('f2-cli-lista').value = '';
    await fase2CargarClientes();
    showToast('Lista cargada (' + d.total + ')', 'success');
  } catch(e) {
    st.className = 'feedback err';
    st.textContent = e.message;
  } finally {
    setBtnLoading(btn, false);
  }
}

async function fase2ModoCliente(slug, modo) {
  slug = decodeURIComponent(slug);
  var cliente = _f2Clientes.find(function(c) { return c.slug === slug; });
  var nombre = cliente ? cliente.nombre : slug;
  var ok = await confirmar(modo === 'no_mencionar'
    ? { titulo: '¿No nombrar nunca a ' + nombre + '?', mensaje: 'Ninguna nota nueva la va a nombrar, aunque aparezca en las noticias. Las notas ya generadas no cambian.', accion: 'No nombrar' }
    : { titulo: '¿Permitir mencionar a ' + nombre + '?', mensaje: 'Vuelve a la lista de clientes que se pueden elegir para una nota.', accion: 'Permitir' });
  if (!ok) return;
  try {
    await pedir('/api/fase2/clientes/' + encodeURIComponent(slug), {
      method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ modo: modo })
    });
    if (modo === 'no_mencionar' && FORMULARIOS.crear) {
      _f2ClientesActivos.delete(slug);
      FORMULARIOS.crear.quitarDeBase('clientes', slug);   // el servidor ya la sacó de la config guardada
    }
    await fase2CargarClientes();
    marcarCrear();
  } catch(e) {
    showToast('No se pudo cambiar el cliente: ' + e.message, 'error');
  }
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

/* Rotación de categorías: cada nota (también las automáticas) usa 1 o 2 de las marcadas. */
function pintarRotarCategorias(activo) {
  _f2RotarCategorias = activo;
  $('f2-rotar-toggle').classList.toggle('active', activo);
  $('f2-rotar-toggle').setAttribute('aria-checked', activo);
  if (typeof resumenCrear === 'function' && $('crear-resumen')) resumenCrear();
}

function toggleRotarCategorias() {
  pintarRotarCategorias(!_f2RotarCategorias);
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
    rotar_categorias: _f2RotarCategorias,
    indicaciones: $('f2-indicaciones').value.trim() || null,
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
      st.textContent = t ? 'Hay otra tarea en curso: tu nota quedó ' + t.toLowerCase().replace('…', '') + '. Se genera apenas termine.'
                         : 'Generando nota...';
    }, function(id) {
      _f2Corrida = id;
      cancelar.disabled = false;
    });
    exito = fin.estado === 'ok' && fullOutput.indexOf('[OK]') >= 0;

    if (exito) {
      // Se usan una sola vez: la próxima nota arranca sin tema ni indicaciones.
      $('f2-tema').value = '';
      $('f2-indicaciones').value = '';
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
    terminarPasosNota(exito, fin && fin.estado === 'cancelada');
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
    var r = await pedir('/api/corridas/' + _f2Corrida + '/cancelar', { method: 'POST' });
    if (r.estado === 'cancelada' || r.estado === 'cancelando') {
      log('Se pidió cancelar la generación desde el dashboard.', 'warn');
    } else {
      log('No se pudo cancelar: la generación ya terminó.', 'warn');
    }
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
    var check = $('check-list');
    var nota = d.nota;
    var firma = JSON.stringify(nota);   // antes de que la vista le agregue cosas: vivo.js compara contra esto
    $('modal-titulo').textContent = tituloDeNota(nota.contenido) || (id ? 'Nota' : 'Última nota');
    // Cada dato en su span: así se traduce cada uno (p. ej. "Generada el …").
    $('modal-meta').innerHTML = [
      nota.generado_en ? 'Generada el ' + new Date(nota.generado_en).toLocaleString(localeUI(), { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }) : '',
      nota.persona ? nota.persona.charAt(0).toUpperCase() + nota.persona.slice(1) : '',
      nota.idioma && NOMBRE_IDIOMA[nota.idioma] ? NOMBRE_IDIOMA[nota.idioma] : ''
    ].filter(Boolean).map(function(x) { return '<span>' + escHtml(x) + '</span>'; }).join(' · ');
    abrirModal();
    _notaActual = { coleccion: 'notas_fase2', id: nota._id, estado: nota.estado || 'borrador',
                    contenido: nota.contenido, hubspot: nota.hubspot || null,
                    idioma: nota.idioma || null, vista: nota.idioma || null, traducciones: nota.traducciones || {} };
    pintarCuerpoNota();   // pestañas por idioma; el contenido no se traduce con la UI
    verPanelModal('nota');
    armarRecorrido(nota, check);   // Revisar → Calificar → Publicar (recorrido.js)
    _recorrido.firma = firma;
    _recorrido.cambiosVistos = _cambiosPropios.total;

    // Criterios del evaluador, dentro de "Cómo se generó" (recorrido.js).
    var evD = { success: false };
    if (nota.evaluacion) {
      evD = { success: true, evaluation: nota.evaluacion };   // guardada al generar
    } else try {
      var evR = await fetch('/api/evaluate-article', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ articulo: nota.contenido })
      });
      evD = await evR.json();
    } catch(e) {}
    if (!_notaActual || _notaActual.id !== nota._id) return;
    pintarCriterios(evD.success ? (evD.evaluation.lineamientos || evD.evaluation) : null,
                    evD.success ? evD.evaluation.comentarios : '');
  } catch(e) { showToast('Error al cargar nota', 'error'); }
}
