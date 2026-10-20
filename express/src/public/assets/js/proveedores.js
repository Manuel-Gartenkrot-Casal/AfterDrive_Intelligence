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
