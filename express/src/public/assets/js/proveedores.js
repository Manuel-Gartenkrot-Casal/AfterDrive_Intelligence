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
    }
  } catch(e) { console.error('Error checking providers:', e); }
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
      updateProviderUI(provider);
      log('Proveedor cambiado a: ' + provider + ' (' + d.model + ')', 'success');
    } else {
      log('Error: ' + d.error, 'error');
      showToast(d.error, 'error');
    }
  } catch(e) { log('Error al cambiar proveedor', 'error'); }
}
