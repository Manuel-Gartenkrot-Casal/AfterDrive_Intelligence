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

async function switchProvider(provider) {
  try {
    var r = await fetch('/api/providers', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({provider: provider})
    });
    var d = await r.json();
    if (d.success) {
      updateProviderUI(d.provider);
      log('Proveedor cambiado a: ' + provider + ' (' + d.model + ')', 'success');
      avisarConsumo(d);
    } else {
      log('Error: ' + d.error, 'error');
      showToast(d.error, 'error');
    }
  } catch(e) { log('Error al cambiar proveedor', 'error'); }
}
