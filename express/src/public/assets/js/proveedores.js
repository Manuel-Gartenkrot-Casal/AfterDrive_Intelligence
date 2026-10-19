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
      actualizarModoPago(d);
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
      actualizarModoPago(d);
      log('Proveedor cambiado a: ' + provider + ' (' + d.model + ')', 'success');
      avisarConsumo(d);
    } else {
      log('Error: ' + d.error, 'error');
      showToast(d.error, 'error');
    }
  } catch(e) { log('Error al cambiar proveedor', 'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════
   MODO API PAGA (vista Cliente)
   Todo el pipeline usa la API paga por un día como máximo y después vuelve
   solo al proveedor elegido en Desarrollador. Ver afterdrive/ia/modo_pago.py.
   ═══════════════════════════════════════════════════════════════════════ */
var NOMBRES_PROVEEDOR = { local: 'LM Studio local', nvidia: 'NVIDIA', openrouter: 'OpenRouter', paga: 'API paga' };
var _modoPago = { estado: null, vence: 0, reloj: null };

function _restante(ms) {
  var min = Math.max(1, Math.ceil(ms / 60000));
  var h = Math.floor(min / 60), m = min % 60;
  return h ? h + ' h ' + (m < 10 ? '0' : '') + m + ' min' : m + ' min';
}

function _horaVence(fecha) {
  return fecha.toLocaleString('es-AR', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
}

function _pintarModoPago() {
  var d = _modoPago.estado, btn = $('modo-pago-btn'), det = $('modo-pago-detalle');
  if (!d || !btn) return;
  var activo = !!d.modo_pago_activo;
  var fijo = !activo && d.provider_base === 'paga';
  btn.setAttribute('aria-checked', activo || fijo ? 'true' : 'false');
  btn.disabled = !d.paga_available || fijo;
  var texto;
  if (!d.paga_available) texto = 'No configurada en el servidor';
  else if (fijo) texto = 'Fijada desde la vista Desarrollador';
  else if (activo) {
    var falta = _modoPago.vence - Date.now();
    if (falta <= 0) { texto = 'Apagándose…'; refrescarModoPago(); }
    else texto = 'Activa · se apaga en ' + _restante(falta);
  } else texto = 'Apagada · se usa ' + (NOMBRES_PROVEEDOR[d.provider_base] || d.provider_base);
  if ((activo || fijo) && d.paga_tope_alcanzado) texto = 'Tope del mes alcanzado · se usa NVIDIA';
  det.textContent = texto;
  btn.title = activo ? 'Todo el pipeline usa la API paga hasta el ' + _horaVence(new Date(_modoPago.vence)) : '';
}

function actualizarModoPago(d) {
  _modoPago.estado = d;
  // El vencimiento se cuenta con el reloj de esta máquina a partir de lo que
  // falta según el servidor: así un reloj local corrido no lo adelanta.
  _modoPago.vence = d.modo_pago_activo ? Date.now() + d.modo_pago_restante_s * 1000 : 0;
  _pintarModoPago();
  if (!_modoPago.reloj) {
    _modoPago.reloj = setInterval(_pintarModoPago, 30000);
    setInterval(refrescarModoPago, 120000);  // por si lo cambiaron desde otra pestaña
  }
}

async function refrescarModoPago() {
  try {
    var r = await fetch('/api/providers');
    var d = await r.json();
    if (d.success) { updateProviderUI(d.provider); actualizarModoPago(d); }
  } catch (e) { /* se reintenta en el próximo ciclo */ }
}

async function toggleModoPago() {
  var d = _modoPago.estado;
  if (!d) return;
  var prender = !d.modo_pago_activo;
  var base = NOMBRES_PROVEEDOR[d.provider_base] || d.provider_base;
  if (prender) {
    var vence = new Date(Date.now() + 24 * 3600 * 1000);
    var gasto = d.paga_gastado_mes_usd !== undefined
      ? '\n\nGastado este mes en la API paga: USD ' + d.paga_gastado_mes_usd.toFixed(2) + ' de un tope de USD ' + d.paga_tope_usd + '.'
      : '';
    var ok = await confirmar({
      titulo: '¿Activar la API paga por 24 horas?',
      mensaje: 'Mientras esté activa, todo el pipeline usa la API paga y cada paso cuesta dinero: '
        + 'filtrar las noticias encontradas, escribir las notas y revisarlas.'
        + '\n\nIncluye la corrida automática programada y todas las notas y búsquedas que pidas a mano en ese tiempo.'
        + '\n\nSe apaga sola el ' + _horaVence(vence) + ' y vuelve a ' + base + '. Podés apagarla antes cuando quieras.'
        + gasto,
      accion: 'Sí, activar por 24 h',
      cancelar: 'Cancelar'
    });
    if (!ok) return;
  }
  var btn = $('modo-pago-btn');
  btn.disabled = true;
  try {
    var r = await fetch('/api/modo-pago', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({activo: prender})
    });
    var res = await r.json();
    if (!res.success) {
      showToast(res.error || 'No se pudo cambiar la API paga.', 'error');
      log('Modo API paga: ' + (res.error || 'error'), 'error');
      _pintarModoPago();
      return;
    }
    updateProviderUI(res.provider);
    actualizarModoPago(res);
    if (prender) {
      showToast('API paga activa por 24 horas.', 'success');
      log('Modo API paga activado hasta el ' + _horaVence(new Date(_modoPago.vence)), 'success');
    } else {
      showToast('API paga apagada. Se vuelve a usar ' + base + '.', 'success');
      log('Modo API paga apagado. Proveedor: ' + res.provider, 'success');
    }
  } catch (e) {
    showToast('No se pudo cambiar la API paga.', 'error');
    _pintarModoPago();
  }
}
