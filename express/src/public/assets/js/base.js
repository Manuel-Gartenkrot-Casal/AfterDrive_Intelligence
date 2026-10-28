/* base.js — Utilidades, avisos, confirmar(), pedir(), formularios con guardado y tema.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════════════════════════════════ */
const $ = id => document.getElementById(id);
// Sesión vencida o cerrada: cualquier 401 recarga la página, que cae en el login.
const _fetch = window.fetch;
window.fetch = async (...a) => { const r = await _fetch(...a); if (r.status === 401) location.reload(); return r; };
async function salir() { await fetch('/api/logout', { method: 'POST' }); location.reload(); }
function now() { return new Date().toLocaleTimeString(localeUI(), {hour:'2-digit', minute:'2-digit', second:'2-digit'}); }

function log(msg, type='info') {
  const entry = document.createElement('div');
  entry.className = 'log-entry log-' + type;
  entry.innerHTML = '<span class="log-timestamp">' + now() + '</span> <span class="console-prompt">afterdrive &#9656;</span> ' + escHtml(msg);
  const c = $('logs');
  c.appendChild(entry);
  c.scrollTop = c.scrollHeight;
}

// Escapa también comillas: el resultado se usa dentro de atributos (title="...", href="...").
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
// Para argumentos de onclick='fn('...')': encodeURIComponent deja pasar la comilla simple.
function encArg(s) { return encodeURIComponent(s).replace(/'/g, '%27'); }
// Un href armado con datos solo puede ser http(s): nunca javascript: ni data:.
// Links de afuera (http/https) o una imagen subida desde la computadora, servida por este servidor.
function urlSegura(u) { return /^https?:\/\//i.test(u || '') || /^\/api\/imagenes\/[0-9a-f]{24}$/.test(u || '') ? escHtml(u) : '#'; }

/* ═══════════════════════════════════════════════════════════════════════
   PARTICLES BACKGROUND
   ═══════════════════════════════════════════════════════════════════════ */
function initParticles() {
  var canvas = document.querySelector('.particles-canvas');
  if (!canvas) return;
  var count = window.innerWidth < 768 ? 10 : 20;
  for (var i = 0; i < count; i++) {
    var p = document.createElement('div');
    p.className = 'particle';
    p.style.left = (Math.random() * 100) + '%';
    p.style.animationDuration = (8 + Math.random() * 12) + 's';
    p.style.animationDelay = (Math.random() * 10) + 's';
    p.style.setProperty('--drift', (Math.random() * 60 - 30) + 'px');
    var size = 1 + Math.random() * 2;
    p.style.width = size + 'px';
    p.style.height = size + 'px';
    canvas.appendChild(p);
  }
}

/* ═══════════════════════════════════════════════════════════════════════
   BUTTON RIPPLE EFFECT
   ═══════════════════════════════════════════════════════════════════════ */
document.addEventListener('click', function(e) {
  var btn = e.target.closest('.btn');
  if (!btn || btn.disabled) return;
  var rect = btn.getBoundingClientRect();
  var ripple = document.createElement('span');
  ripple.className = 'btn-ripple';
  var size = Math.max(rect.width, rect.height);
  ripple.style.width = ripple.style.height = size + 'px';
  ripple.style.left = (e.clientX - rect.left - size / 2) + 'px';
  ripple.style.top = (e.clientY - rect.top - size / 2) + 'px';
  btn.style.position = btn.style.position || 'relative';
  btn.style.overflow = 'hidden';
  btn.appendChild(ripple);
  setTimeout(function() { ripple.remove(); }, 650);
});

/* ═══════════════════════════════════════════════════════════════════════
   TOAST NOTIFICATIONS
   ═══════════════════════════════════════════════════════════════════════ */
/* Pregunta antes de una acción. Resuelve true solo si el usuario confirma;
   Esc, Cancelar o cerrar resuelven false. Con opts.campo pide además un
   texto (obligatorio) y resuelve ese texto en lugar de true. */
function confirmar(opts) {
  var dlg = $('confirmar');
  var conCampo = !!opts.campo;
  $('confirmar-etiqueta').hidden = $('confirmar-valor').hidden = !conCampo;
  $('confirmar-etiqueta').textContent = opts.campo || '';
  $('confirmar-valor').value = '';
  $('confirmar-valor').placeholder = opts.placeholder || '';
  $('confirmar-titulo').textContent = opts.titulo;
  $('confirmar-texto').textContent = opts.mensaje;
  var si = $('confirmar-si');
  si.textContent = opts.accion || 'Confirmar';
  si.className = 'btn ' + (opts.peligro === false ? 'btn-primary' : 'btn-peligro');
  $('confirmar-no').textContent = opts.cancelar || 'Cancelar';
  dlg.returnValue = '';
  function validar() { si.disabled = conCampo && $('confirmar-valor').value.trim().length < 3; }
  $('confirmar-valor').oninput = validar;
  validar();
  return new Promise(function(resolve) {
    dlg.addEventListener('close', function() {
      var ok = dlg.returnValue === 'si';
      resolve(conCampo ? (ok ? $('confirmar-valor').value.trim() : false) : ok);
    }, { once: true });
    dlg.showModal();
    (conCampo ? $('confirmar-valor') : $('confirmar-no')).focus();
  });
}

/* ═══════════════════════════════════════════════════════════════════════
   FORMULARIOS CON GUARDADO EXPLÍCITO
   Cada sección editable compara su estado con el último guardado (base).
   Si difieren aparece su barra con Guardar / Descartar; salir de la
   sección o de la página con cambios pide confirmación.
   def = { leer(), aplicar(estado), guardar(estado, base), despues()? }
   ═══════════════════════════════════════════════════════════════════════ */
var FORMULARIOS = {};

function formulario(id, def) {
  var barra = $('barra-' + id);
  var estado = barra.querySelector('.barra-estado');
  var btnGuardar = barra.querySelector('[data-accion="guardar"]');
  var base = null;
  var f = {
    base: function() { return JSON.parse(base); },
    sucio: function() { return base !== null && JSON.stringify(def.leer()) !== base; },
    tomarBase: function() { base = JSON.stringify(def.leer()); f.marcar(); },
    marcar: function() {
      var sucio = f.sucio();
      if (sucio && barra.hidden) { estado.textContent = ''; estado.classList.remove('err'); }
      barra.hidden = !sucio;
    },
    descartar: function() { if (base !== null) def.aplicar(JSON.parse(base)); f.marcar(); },
    quitarDeBase: function(clave, valor) {
      var b = JSON.parse(base);
      b[clave] = b[clave].filter(function(v) { return v !== valor; });
      base = JSON.stringify(b);
    },
    guardar: async function() {
      var actual = def.leer();
      btnGuardar.disabled = true;
      estado.classList.remove('err');
      estado.textContent = 'Guardando...';
      try {
        await def.guardar(actual, JSON.parse(base));
        base = JSON.stringify(actual);
        f.marcar();
        showToast('Cambios guardados', 'success');
        if (def.despues) def.despues();
      } catch (e) {
        estado.classList.add('err');
        estado.textContent = 'No se pudo guardar: ' + e.message;
      } finally {
        btnGuardar.disabled = false;
      }
    }
  };
  barra.querySelector('[data-accion="descartar"]').onclick = f.descartar;
  btnGuardar.onclick = f.guardar;
  FORMULARIOS[id] = f;
  return f;
}

function hayCambiosSinGuardar() {
  return Object.keys(FORMULARIOS).some(function(id) { return FORMULARIOS[id].sucio(); });
}

function initFormularios() {
  antesDeSalirDeSeccion(async function(desde) {
    var f = FORMULARIOS[desde];
    if (!f || !f.sucio()) return true;
    var salir = await confirmar({
      titulo: 'Tenés cambios sin guardar',
      mensaje: 'Si salís de esta sección, se pierden los cambios que no guardaste.',
      accion: 'Descartar cambios',
      cancelar: 'Seguir editando'
    });
    if (salir) f.descartar();
    return salir;
  });
  window.addEventListener('beforeunload', function(ev) {
    if (!hayCambiosSinGuardar()) return;
    ev.preventDefault();
    ev.returnValue = '';
  });
}

/* fetch que falla si el server responde error, con el mensaje del server. */
// Cambios que hizo esta pestaña (todo lo que no es GET), en curso y terminados: vivo.js no los avisa como ajenos.
var _cambiosPropios = { enCurso: 0, total: 0 };

async function pedir(url, opciones) {
  var cambio = !!opciones && !!opciones.method && opciones.method.toUpperCase() !== 'GET';
  if (!cambio) return _pedir(url, opciones);
  _cambiosPropios.enCurso++;
  _cambiosPropios.total++;
  try { return await _pedir(url, opciones); }
  finally { _cambiosPropios.enCurso--; _cambiosPropios.total++; }
}

async function _pedir(url, opciones) {
  var r = await fetch(url, opciones);
  var d = {};
  try { d = await r.json(); } catch (e) {}
  if (!r.ok || d.success === false) {
    var error = new Error(d.error || ('Error ' + r.status));
    error.status = r.status;
    throw error;
  }
  return d;
}

var _toastContainer = null;
function showToast(msg, type, duration) {
  type = type || 'info';
  duration = duration || 4000;
  if (!_toastContainer) {
    _toastContainer = document.createElement('div');
    _toastContainer.className = 'toast-container';
    document.body.appendChild(_toastContainer);
  }
  var icons = { success: '\u2713', error: '\u2717', warn: '\u26A0', info: '\u2139' };
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.innerHTML = '<span class="toast-icon">' + (icons[type] || icons.info) + '</span><span>' + escHtml(msg) + '</span>';
  _toastContainer.appendChild(toast);
  setTimeout(function() {
    toast.classList.add('toast-exit');
    setTimeout(function() { toast.remove(); }, 300);
  }, duration);
}

/* ═══════════════════════════════════════════════════════════════════════
   BUTTON LOADING STATE
   ═══════════════════════════════════════════════════════════════════════ */
function setBtnLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn.dataset.origText = btn.innerHTML;
    btn.textContent = tr(btn.id === 'btn-f2-generar' ? 'Generando nota…' : 'Procesando…');
    btn.setAttribute('aria-busy', 'true');
    btn.classList.add('loading');
    btn.disabled = true;
  } else {
    btn.classList.remove('loading');
    btn.removeAttribute('aria-busy');
    btn.disabled = false;
    if (btn.dataset.origText) btn.innerHTML = btn.dataset.origText;
  }
}

function limpiarLogs() {
  $('logs').innerHTML = '';
  log('Logs limpiados.');
}

/* ═══════════════════════════════════════════════════════════════════════
   THEME TOGGLE
   ═══════════════════════════════════════════════════════════════════════ */
var _temaTimer;
function toggleTheme() {
  var html = document.documentElement;
  clearTimeout(_temaTimer);
  html.classList.add('theme-changing');
  var next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('ad-theme', next);
  $('themeBtn').innerHTML = next === 'dark' ? '&#9790;' : '&#9728;';
  _temaTimer = setTimeout(function() { html.classList.remove('theme-changing'); }, 280);
}

(function() {
  var current = document.documentElement.getAttribute('data-theme');
  $('themeBtn').innerHTML = current === 'dark' ? '&#9790;' : '&#9728;';
})();

/* ═══════════════════════════════════════════════════════════════════════
   COUNT-UP ANIMATION
   ═══════════════════════════════════════════════════════════════════════ */
function countUp(el, target, duration) {
  duration = duration || 800;
  var start = parseInt(el.textContent.replace(/\D/g, '')) || 0;
  if (start === target) return;
  var startTime = null;
  function step(ts) {
    if (!startTime) startTime = ts;
    var p = Math.min((ts - startTime) / duration, 1);
    var ease = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(start + (target - start) * ease).toLocaleString();
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
