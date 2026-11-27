/* carpetas.js — Carpeta de cada cliente: datos del cliente y eventos.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Las carpetas son los clientes de /api/fase2/clientes. Lo que se sube va a
   /api/carpetas/<slug>/(datos|eventos). */

function _slugCarpeta() { return $('carpeta-cliente').value; }

async function cargarClientesCarpetas(elegir) {
  var sel = $('carpeta-cliente');
  var actual = elegir || sel.value;
  try {
    var d = await pedir('/api/fase2/clientes');
    var lista = (d.clientes || []).slice().sort(function(a, b) { return a.nombre.localeCompare(b.nombre); });
    sel.innerHTML = '<option value="">Elegí un cliente</option>' + lista.map(function(c) {
      return '<option value="' + escHtml(c.slug) + '" translate="no">' + escHtml(c.nombre) + '</option>';
    }).join('');
    sel.value = lista.some(function(c) { return c.slug === actual; }) ? actual : '';
  } catch (e) {
    showToast('No se pudieron cargar los clientes: ' + e.message, 'error');
  }
  await cargarCarpeta();
}

async function crearCarpeta(ev) {
  ev.preventDefault();
  var campo = $('carpeta-nueva');
  try {
    var d = await pedir('/api/fase2/clientes', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nombre: campo.value.trim()})
    });
    campo.value = '';
    showToast('Carpeta creada', 'success');
    await cargarClientesCarpetas(d.cliente.slug);
  } catch (e) {
    showToast('No se pudo crear la carpeta: ' + e.message, 'error');
  }
}

async function cargarCarpeta(mantenerAviso) {
  var slug = _slugCarpeta();
  $('carpeta-paneles').disabled = !slug;
  if (mantenerAviso !== true) ['datos', 'eventos'].forEach(function(t) { $('carpeta-fb-' + t).textContent = ''; });
  if (!slug) { _pintarCarpeta({datos: [], eventos: []}, true); return; }
  try {
    _pintarCarpeta(await pedir('/api/carpetas/' + encodeURIComponent(slug)));
  } catch (e) {
    showToast('No se pudo abrir la carpeta: ' + e.message, 'error');
  }
}

function _pintarCarpeta(d, sinCliente) {
  var vacio = sinCliente ? 'Elegí un cliente para ver su carpeta.' : null;
  $('carpeta-n-datos').textContent = d.datos.length;
  $('carpeta-n-eventos').textContent = d.eventos.length;
  $('carpeta-datos').innerHTML = d.datos.length ? d.datos.map(function(x) {
    return _filaCarpeta(x, x.titulo, x.contenido,
      '<span>Cargado el</span> <span translate="no">' + new Date(x.creado_en).toLocaleDateString(localeUI()) + '</span>');
  }).join('') : '<div class="fuentes-vacio"><span>' + (vacio || 'Todavía no hay datos de este cliente.') + '</span></div>';
  $('carpeta-eventos').innerHTML = d.eventos.length ? d.eventos.map(function(x) {
    var fecha = new Date(x.fecha + 'T00:00:00Z').toLocaleDateString(localeUI(), {timeZone: 'UTC'});
    return _filaCarpeta(x, x.nombre, x.descripcion,
      '<span translate="no">' + fecha + (x.lugar ? ' · ' + escHtml(x.lugar) : '') + '</span>');
  }).join('') : '<div class="fuentes-vacio"><span>' + (vacio || 'Todavía no hay eventos de este cliente.') + '</span></div>';
}

function _filaCarpeta(x, titulo, texto, meta) {
  return '<div class="fuente-fila carpeta-fila">'
    + '<div class="fuente-info"><div class="fuente-url" translate="no">' + escHtml(titulo) + '</div>'
    + (texto ? '<p class="carpeta-texto" translate="no">' + escHtml(texto) + '</p>' : '')
    + '<div class="fuente-meta">' + meta + '</div></div>'
    + '<button type="button" class="icon-btn" title="Eliminar" aria-label="Eliminar" onclick="borrarDeCarpeta(\'' + encArg(x.id) + '\')">✕</button>'
    + '</div>';
}

async function subirCarpeta(ev, tipo) {
  ev.preventDefault();
  var form = ev.target, fb = $('carpeta-fb-' + tipo), boton = form.querySelector('button[type="submit"]');
  var body = {};
  Array.prototype.forEach.call(form.elements, function(el) { if (el.name) body[el.name] = el.value; });
  boton.disabled = true;
  try {
    await pedir('/api/carpetas/' + encodeURIComponent(_slugCarpeta()) + '/' + tipo, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    form.reset();
    fb.className = 'feedback ok';
    fb.textContent = 'Guardado.';
    cargarCarpeta(true);
  } catch (e) {
    fb.className = 'feedback err';
    fb.textContent = 'No se pudo guardar: ' + e.message;
  } finally {
    boton.disabled = false;
  }
}

async function borrarDeCarpeta(id) {
  var ok = await confirmar({
    titulo: '¿Eliminar de la carpeta?',
    mensaje: 'Se borra de la carpeta de este cliente y no se puede recuperar.',
    accion: 'Eliminar'
  });
  if (!ok) return;
  try {
    await pedir('/api/carpetas/' + encodeURIComponent(_slugCarpeta()) + '/' + id, {method: 'DELETE'});
    showToast('Eliminado de la carpeta', 'success');
    cargarCarpeta();
  } catch (e) {
    showToast('No se pudo eliminar: ' + e.message, 'error');
  }
}

document.addEventListener('seccion', function(e) { if (e.detail === 'clientes') cargarClientesCarpetas(); });
