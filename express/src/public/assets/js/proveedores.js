/* proveedores.js — Proveedor de IA.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   PROVIDER MANAGEMENT
   ═══════════════════════════════════════════════════════════════════════ */
async function checkProviders() {
  try {
    var r = await fetch('/api/providers');
    var d = await r.json();
    if (d.success) {
      _estadoProveedor = d;
      updateProviderUI(d.provider);
      log('Proveedor activo: ' + d.provider + ' (' + d.model + ')', 'info');
      avisarConsumo(d);
    }
  } catch(e) { console.error('Error checking providers:', e); }
}

// Gasto del mes de la API paga y aviso si se llegó al tope (el chat pasa a NVIDIA).
function avisarConsumo(d) {
  if (d.paga_gastado_mes_usd === undefined || d.provider !== 'paga') return;
  var resumen = 'API paga: USD ' + d.paga_gastado_mes_usd.toFixed(2) + ' de ' + d.paga_tope_usd + ' este mes';
  if (d.paga_tope_alcanzado) {
    log(resumen + '. Tope alcanzado: se usa NVIDIA hasta el mes que viene.', 'error');
    showToast('Tope mensual de la API paga alcanzado: se usa NVIDIA.', 'error');
  } else {
    log(resumen, 'info');
  }
}

function updateProviderUI(provider) {
  var localBtn = $('prov-local');
  var nvidiaBtn = $('prov-nvidia');
  var openrouterBtn = $('prov-openrouter');
  if (localBtn) {
    localBtn.classList.toggle('active', provider === 'local');
  }
  if (nvidiaBtn) {
    nvidiaBtn.classList.toggle('active', provider === 'nvidia');
  }
  if (openrouterBtn) {
    openrouterBtn.classList.toggle('active', provider === 'openrouter');
  }
  var pagaBtn = $('prov-paga');
  if (pagaBtn) {
    pagaBtn.classList.toggle('active', provider === 'paga');
  }
}

var _estadoProveedor = null;  // la última respuesta de /api/providers

// La API paga cuesta plata en cada llamada: se confirma antes de pasar a ella.
async function confirmarApiPaga() {
  var d = _estadoProveedor || {};
  var gasto = d.paga_gastado_mes_usd !== undefined
    ? '\n\nGastado este mes: USD ' + d.paga_gastado_mes_usd.toFixed(2) + ' de un tope de USD ' + d.paga_tope_usd + '.'
    : '';
  return confirmar({
    titulo: '¿Usar la API paga?',
    mensaje: 'Desde ahora todo el pipeline usa la API paga y cada llamada cuesta dinero: filtrar las noticias, '
      + 'escribir las notas y revisarlas, incluida la corrida automática programada.'
      + '\n\nQueda así hasta que elijas otro proveedor. Si se llega al tope del mes, se pasa solo a NVIDIA.' + gasto,
    accion: 'Sí, usar la API paga',
    cancelar: 'Cancelar'
  });
}

async function switchProvider(provider) {
  var pagaBtn = $('prov-paga');
  if (provider === 'paga' && !(pagaBtn && pagaBtn.classList.contains('active'))) {
    if (!(await confirmarApiPaga())) return;
  }
  try {
    var r = await fetch('/api/providers', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({provider: provider})
    });
    var d = await r.json();
    if (d.success) {
      _estadoProveedor = d;
      updateProviderUI(d.provider);
      log('Proveedor cambiado a: ' + provider + ' (' + d.model + ')', 'success');
      avisarConsumo(d);
    } else {
      log('Error: ' + d.error, 'error');
      showToast(d.error, 'error');
    }
  } catch(e) { log('Error al cambiar proveedor', 'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════
   BLOG DE PRUEBAS (HubSpot) — switch de la vista Desarrollador
   Prendido: los borradores van a blog_test (HUBSPOT_BLOG_PRUEBAS).
   Apagado: al blog de cada idioma.
   ═══════════════════════════════════════════════════════════════════════ */
var _blogPruebas = null;  // la última respuesta de /api/hubspot/blog-pruebas

function pintarBlogPruebas(d) {
  _blogPruebas = d;
  var sw = $('sw-blog-pruebas');
  if (!sw) return;
  sw.classList.toggle('active', !!d.activo);
  sw.classList.toggle('no-disponible', !d.disponible);
  sw.setAttribute('aria-checked', !!d.activo);
  sw.setAttribute('aria-disabled', !d.disponible);
  sw.querySelector('.ajuste-estado').textContent = !d.disponible ? 'Falta HUBSPOT_BLOG_PRUEBAS'
    : d.activo ? 'Van a blog_test' : 'Al blog de cada idioma';
  sw.title = !d.disponible
    ? 'Falta cargar HUBSPOT_BLOG_PRUEBAS en el Environment de Render.'
    : (d.activo ? 'Los borradores se suben a blog_test (' + d.blog_id + ').'
                : 'Los borradores se suben al blog de cada idioma.');
}

async function checkBlogPruebas() {
  try {
    var r = await fetch('/api/hubspot/blog-pruebas');
    var d = await r.json();
    if (d.success) pintarBlogPruebas(d);
  } catch(e) { console.error('Error leyendo blog de pruebas:', e); }
}

async function cambiarBlogPruebas() {
  if (!_blogPruebas) return;
  if (!_blogPruebas.disponible) {
    showToast('Falta cargar HUBSPOT_BLOG_PRUEBAS en el Environment de Render.', 'error');
    return;
  }
  var activo = !_blogPruebas.activo;
  if (!activo && !(await confirmar({
    titulo: '¿Subir a los blogs reales?',
    mensaje: 'Los borradores van a ir a los blogs de After Drive de cada idioma, no a blog_test.',
    accion: 'Sí, a los blogs reales',
    cancelar: 'Cancelar'
  }))) return;
  try {
    var r = await fetch('/api/hubspot/blog-pruebas', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({activo: activo})
    });
    var d = await r.json();
    if (d.success) {
      pintarBlogPruebas(d);
      log(d.activo ? 'Borradores a blog_test' : 'Borradores a los blogs de cada idioma', 'success');
    } else {
      showToast(d.error, 'error');
    }
  } catch(e) { log('Error al cambiar el blog de pruebas', 'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════
   APROBACIÓN AUTOMÁTICA — switch de la vista Desarrollador
   Prendida: las notas de la generación programada que pasan el filtro y el
   juez de IA se aprueban solas y suben a HubSpot como borrador (nunca se publican).
   ═══════════════════════════════════════════════════════════════════════ */
var _aprobacionAuto = null;

function pintarAprobacionAuto(d) {
  _aprobacionAuto = d;
  var sw = $('sw-aprobacion-auto');
  if (!sw) return;
  sw.classList.toggle('active', !!d.activo);
  sw.setAttribute('aria-checked', !!d.activo);
  sw.querySelector('.ajuste-estado').textContent = d.activo ? 'Prendida' : 'Apagada';
}

async function checkAprobacionAuto() {
  try {
    var r = await fetch('/api/aprobacion-auto');
    var d = await r.json();
    if (d.success) pintarAprobacionAuto(d);
  } catch(e) { console.error('Error leyendo aprobación automática:', e); }
}

async function cambiarAprobacionAuto() {
  if (!_aprobacionAuto) return;
  var activo = !_aprobacionAuto.activo;
  if (activo) {
    var destino = _blogPruebas && _blogPruebas.activo ? 'blog_test' : 'los blogs reales de cada idioma';
    if (!(await confirmar({
      titulo: '¿Prender la aprobación automática?',
      mensaje: 'Las notas de la generación programada que pasen los controles y el juez de IA (confianza ≥ '
        + _aprobacionAuto.confianza_min + ') se aprueban solas y suben como borrador a ' + destino
        + '. Nunca se publican solas. Las que no pasen quedan en borrador con el motivo.',
      accion: 'Sí, prender',
      cancelar: 'Cancelar'
    }))) return;
  }
  try {
    var r = await fetch('/api/aprobacion-auto', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({activo: activo})
    });
    var d = await r.json();
    if (d.success) {
      pintarAprobacionAuto(d);
      log('Aprobación automática ' + (d.activo ? 'prendida' : 'apagada'), 'success');
    } else {
      showToast(d.error, 'error');
    }
  } catch(e) { log('Error al cambiar la aprobación automática', 'error'); }
}
