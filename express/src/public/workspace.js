/* Navigation only: existing API handlers retain ownership of the data. */
const workspacePages = {
  redaccion: ['Redacción', 'Convertí noticias del sector en contenido con una voz propia.'],
  fuentes: ['Fuentes', 'Construí la base informativa de tus próximos contenidos.'],
  automatizacion: ['Automatización', 'Definí el ritmo de recopilación y redacción.'],
  historial: ['Historial', 'Consultá todo lo generado y recopilado, y por qué se descartó lo que no pasó.'],
  actividad: ['Actividad', 'Seguí las ejecuciones y consultá sus resultados técnicos.']
};

function showCollectionError(id, label, retry) {
  const grid = document.getElementById(id);
  grid.replaceChildren();
  const message = document.createElement('p');
  message.textContent = 'No se pudieron cargar las ' + label + '.';
  message.setAttribute('role', 'alert');
  const button = document.createElement('button');
  button.className = 'btn'; button.textContent = 'Reintentar';
  button.onclick = retry;
  grid.append(message, button);
}

function markScheduleDirty(kind) {
  document.getElementById(kind === 'auto' ? 'btn-savecfg' : 'btn-savegencfg').textContent = 'Guardar cambios';
}
function clearScheduleDirty(kind) {
  document.getElementById(kind === 'auto' ? 'btn-savecfg' : 'btn-savegencfg').textContent = 'Guardar programación';
}
['auto-days', 'auto-max-art', 'auto-hora', 'gen-days', 'gen-auto-persona', 'gen-hora'].forEach(id => {
  document.getElementById(id).addEventListener('input', () => markScheduleDirty(id.startsWith('auto') ? 'auto' : 'gen'));
});

function openWorkspace(name, focus = true) {
  if (!Object.hasOwn(workspacePages, name)) name = 'redaccion';
  document.querySelectorAll('.workspace-view').forEach(el => { el.hidden = el.id !== 'view-' + name; });
  document.querySelectorAll('[data-workspace]').forEach(el => {
    if (el.dataset.workspace === name) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });
  document.getElementById('workspace-title').textContent = workspacePages[name][0];
  document.getElementById('workspace-description').textContent = workspacePages[name][1];
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  if (focus) document.getElementById('workspace-main').focus({preventScroll: true});
  if (name === 'actividad') setConsoleOpen(true);
  // Las vistas que cargan datos al abrirse (como el historial) escuchan esto.
  document.dispatchEvent(new CustomEvent('workspace:open', {detail: name}));
}

function selectWriting(kind) {
  document.querySelector('.editorial-guidance').textContent = kind === 'nota'
    ? 'Elegí el enfoque, la cobertura y la voz. Revisá el resultado antes de usarlo.'
    : 'Consultá el material sobre tu tema, elegí una voz y revisá el artículo generado.';
  ['nota', 'articulo'].forEach(name => {
    const active = name === kind;
    const tab = document.getElementById('tab-' + name);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById('writing-' + name).hidden = !active;
  });
}

document.querySelectorAll('[data-workspace]').forEach(link => {
  link.addEventListener('click', event => {
    event.preventDefault();
    history.pushState(null, '', link.hash);
    openWorkspace(link.dataset.workspace);
  });
});
window.addEventListener('hashchange', () => openWorkspace(location.hash.slice(1)));
document.querySelector('.writing-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const kind = event.key === 'Home' ? 'nota' : event.key === 'End' ? 'articulo' :
    event.target.id === 'tab-nota' ? 'articulo' : 'nota';
  selectWriting(kind);
  document.getElementById('tab-' + kind).focus();
});

// The original filters are divs rendered asynchronously. Give each its real
// checkbox semantics and keyboard equivalent, including saved selections.
function syncFilterAccessibility() {
  document.querySelectorAll('.toggle-item, .puntapie-toggle').forEach(item => {
    const target = item.classList.contains('cliente-item') ? item.firstElementChild : item;
    target.setAttribute('role', 'checkbox');
    target.tabIndex = 0;
    target.setAttribute('aria-checked', String(item.classList.contains('active')));
    const label = item.querySelector('.toggle-label, .cliente-nombre');
    if (label) target.setAttribute('aria-label', label.textContent);
    if (!target.dataset.keyboardReady) {
      target.dataset.keyboardReady = 'true';
      target.addEventListener('keydown', event => {
        if (event.target !== target || ![' ', 'Enter'].includes(event.key)) return;
        event.preventDefault(); target.click();
      });
    }
  });
  document.getElementById('activity-count').textContent = document.querySelectorAll('#logs .log-entry').length;
}
const observer = new MutationObserver(syncFilterAccessibility);
observer.observe(document.getElementById('workspace-main'), {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
observer.observe(document.getElementById('logs'), {childList: true});
syncFilterAccessibility();

const fieldLabels = {
  'vol-kw': 'Palabra clave', 'gen-tema': 'Tema del artículo', 'gen-persona': 'Voz del artículo',
  'auto-days': 'Intervalo de recopilación en días', 'auto-max-art': 'Máximo de artículos por fuente',
  'gen-days': 'Intervalo de redacción en días', 'gen-auto-persona': 'Voz de la redacción programada',
  'f2-cli-nombre': 'Nombre del cliente', 'f2-cli-desc': 'Descripción del cliente',
  'f2-persona': 'Voz de la nota', 'f2-tema': 'Tema específico de la nota', 'f2-puntapie-url': 'Enlace de destino'
};
Object.entries(fieldLabels).forEach(([id, label]) => document.getElementById(id).setAttribute('aria-label', label));
document.querySelectorAll('.feedback').forEach(el => { el.setAttribute('role', 'status'); });

// Keep focus within the review dialog and return to the opening control.
const resultDialog = document.getElementById('modal-art');
let returnFocus = null;
let operationTrigger = null;
let dialogWasOpen = false;
new MutationObserver(() => {
  const open = resultDialog.classList.contains('open');
  if (open === dialogWasOpen) return;
  dialogWasOpen = open;
  if (open) returnFocus = operationTrigger || document.activeElement;
  document.querySelector('.app-container').inert = open;
  document.querySelector('.workspace-nav').inert = open;
  document.getElementById('pipelineHud').inert = open;
  document.getElementById('execution-dock').inert = open;
  if (open) {
    resultDialog.querySelector('.modal-close').focus();
  } else if (returnFocus && returnFocus.isConnected) returnFocus.focus();
}).observe(resultDialog, {attributes: true, attributeFilter: ['class']});
resultDialog.addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); cerrar(); }
  if (event.key !== 'Tab') return;
  const controls = [...resultDialog.querySelectorAll('button, a[href], input, select, [tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
  const first = controls[0], last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
let activeOperation = null;
let operationTimer = null;
let consoleAnimation = null;

function setConsoleOpen(open) {
  const dock = document.getElementById('execution-dock');
  const content = document.getElementById('execution-content');
  const toggle = document.getElementById('execution-toggle');
  const height = content.getBoundingClientRect().height;
  if (consoleAnimation) consoleAnimation.cancel();
  consoleAnimation = null;
  if (!open && content.contains(document.activeElement)) toggle.focus({preventScroll:true});
  if (!open && document.activeElement.id === 'execution-collapse') toggle.focus({preventScroll:true});
  content.hidden = false;
  content.inert = !open;
  dock.classList.toggle('expanded', open);
  document.getElementById('execution-collapse').hidden = !open;
  toggle.setAttribute('aria-expanded', String(open));
  document.body.classList.toggle('console-expanded', open);
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    content.hidden = !open;
    return;
  }
  const animation = content.animate([
    {height: `${height}px`, opacity: height ? 1 : 0},
    {height: `${open ? content.scrollHeight : 0}px`, opacity: open ? 1 : 0}
  ], {duration: 280, easing: 'cubic-bezier(.22,1,.36,1)'});
  consoleAnimation = animation;
  animation.finished.then(() => {
    if (consoleAnimation !== animation) return;
    content.hidden = !open;
    consoleAnimation = null;
  }).catch(() => {}); // A second click reverses the current transition.
}

function observeOperationLine(line) {
  if (!activeOperation) return;
  if (/\[ERROR\]|\[FAIL\]/i.test(line)) activeOperation.error = true;
  if (/\[OCUPADO\]/.test(line)) activeOperation.blocked = true;
}

const originalLog = window.log;
window.log = function(message, type) {
  observeOperationLine(message);
  if (activeOperation && type === 'error') activeOperation.error = true;
  originalLog(message, type);
};

// Wrap the existing controllers, not fetch itself: background polling must not
// open the console or look like an editorial operation.
const operationLabels = {
  runNowStream: 'Recopilando noticias', discover: 'Buscando fuentes',
  fase2Scrape: 'Sincronizando ejemplos', generarStream: 'Redactando artículo',
  fase2GenerarStream: 'Redactando nota', addUrl: 'Validando fuente',
  verUltimo: 'Consultando artículo', fase2VerUltima: 'Consultando nota'
};
// Lock only controls that launch a serialized operation. Other actions retain
// their labels and availability; only the originating button shows progress.
function markOperationControls(name, title) {
  const selector = Object.keys(operationLabels).map(key => `button[onclick*="${key}("]`).join(',');
  const controls = [...document.querySelectorAll(selector)];
  const candidates = controls.filter(button => button.getAttribute('onclick').includes(name + '('));
  const trigger = candidates.includes(document.activeElement) ? document.activeElement :
    candidates.find(button => button.getClientRects().length);
  const snapshots = controls.map(button => ({button, disabled:button.disabled, title:button.getAttribute('title')}));
  const originalText = trigger?.textContent;
  operationTrigger = trigger;
  controls.forEach(button => {
    button.disabled = true;
    button.dataset.operationBlocked = 'true';
    button.title = 'Esperá a que termine la operación en curso';
  });
  if (trigger) {
    trigger.removeAttribute('data-operation-blocked');
    trigger.classList.add('is-running');
    trigger.setAttribute('aria-busy', 'true');
    trigger.textContent = title + '…';
    trigger.title = title;
  }
  return () => {
    snapshots.forEach(({button, disabled, title: previousTitle}) => {
      button.disabled = disabled;
      button.removeAttribute('data-operation-blocked');
      if (previousTitle === null) button.removeAttribute('title');
      else button.title = previousTitle;
    });
    if (trigger) {
      trigger.classList.remove('is-running');
      trigger.removeAttribute('aria-busy');
      trigger.textContent = originalText;
    }
    operationTrigger = null;
  };
}
Object.entries(operationLabels).forEach(([name, title]) => {
  const execute = window[name];
  window[name] = async function(...args) {
    if (activeOperation) {
      setConsoleOpen(true);
      showToast('Hay una operación en curso. Esperá a que termine.', 'warn');
      return;
    }
    if (name === 'fase2GenerarStream' && !_f2CategoriasActivas.size) {
      showToast('Seleccioná al menos una categoría', 'warn'); return;
    }
    if (name === 'addUrl' && !document.getElementById('url-in').value.trim()) return;
    const restoreControls = markOperationControls(name, title);
    const dock = document.getElementById('execution-dock');
    activeOperation = {started: Date.now(), error: false, blocked: false};
    dock.dataset.result = '';
    dock.classList.add('running');
    document.body.classList.add('op-running');
    document.getElementById('execution-title').textContent = title;
    document.getElementById('execution-state').textContent = 'En curso';
    document.getElementById('activity-operation').textContent = title;
    document.getElementById('activity-result').textContent = 'En curso · seguí el registro en la consola inferior.';
    setConsoleOpen(true);
    const updateElapsed = () => {
      const seconds = Math.floor((Date.now() - activeOperation.started) / 1000);
      document.getElementById('execution-elapsed').textContent = `${seconds}s`;
    };
    updateElapsed();
    operationTimer = setInterval(updateElapsed, 1000);
    try {
      const result = await execute(...args);
      if (name === 'fase2GenerarStream' && document.getElementById('f2-status').classList.contains('err')) {
        activeOperation.error = true;
      }
      return result;
    } catch (error) {
      activeOperation.error = true;
      log(error.message || 'La operación no pudo completarse.', 'error');
    } finally {
      clearInterval(operationTimer);
      dock.classList.remove('running');
      document.body.classList.remove('op-running');
      const failed = activeOperation.error || activeOperation.blocked;
      dock.dataset.result = failed ? 'error' : 'success';
      document.getElementById('execution-state').textContent = activeOperation.blocked ?
        'No ejecutada: servidor ocupado' : failed ? 'Terminó con errores · revisá el registro' : 'Finalizada';
      document.getElementById('activity-result').textContent = document.getElementById('execution-state').textContent +
        ' · ' + document.getElementById('execution-elapsed').textContent;
      restoreControls();
      activeOperation = null;
    }
  };
});

openWorkspace(location.hash.slice(1), false);
selectWriting('nota');

// ── Consola redimensionable ────────────────────────────────────────────────
// Arrastre vertical como la terminal de un editor. El alto vive en una variable
// CSS del dock para que el hueco del contenido lo siga sin recalcular nada.
const CONSOLE_MIN = 120;
const CONSOLE_KEY = 'afterdrive:console-h';
const consoleDock = document.getElementById('execution-dock');
const consoleResizer = document.getElementById('execution-resizer');
// Reserve the actual dock height, including its animation and resized content.
new ResizeObserver(() => {
  document.documentElement.style.setProperty('--console-space', consoleDock.offsetHeight + 24 + 'px');
}).observe(consoleDock);

const consoleMax = () => Math.max(CONSOLE_MIN, Math.round(window.innerHeight * 0.7));

function setConsoleHeight(px, persist = true) {
  const value = Math.min(Math.max(Math.round(px), CONSOLE_MIN), consoleMax());
  consoleDock.style.setProperty('--console-h', value + 'px');
  consoleResizer.setAttribute('aria-valuenow', String(value));
  consoleResizer.setAttribute('aria-valuemax', String(consoleMax()));
  if (persist) {
    // Puede fallar en modo privado o con el almacenamiento bloqueado.
    try { localStorage.setItem(CONSOLE_KEY, String(value)); } catch {}
  }
  return value;
}

function currentConsoleHeight() {
  const raw = parseInt(consoleDock.style.getPropertyValue('--console-h'), 10);
  return Number.isFinite(raw) ? raw : 180;
}

consoleResizer.setAttribute('aria-valuemin', String(CONSOLE_MIN));
let storedConsoleHeight = null;
try { storedConsoleHeight = localStorage.getItem(CONSOLE_KEY); } catch {}
setConsoleHeight(parseInt(storedConsoleHeight, 10) || 180, false);

consoleResizer.addEventListener('pointerdown', event => {
  if (!consoleDock.classList.contains('expanded')) return;
  event.preventDefault();
  const startY = event.clientY;
  const startHeight = currentConsoleHeight();
  consoleResizer.setPointerCapture(event.pointerId);
  consoleDock.classList.add('resizing');
  document.body.classList.add('resizing-console');

  const onMove = move => setConsoleHeight(startHeight + (startY - move.clientY));
  const onUp = () => {
    consoleResizer.removeEventListener('pointermove', onMove);
    consoleDock.classList.remove('resizing');
    document.body.classList.remove('resizing-console');
  };
  consoleResizer.addEventListener('pointermove', onMove);
  consoleResizer.addEventListener('pointerup', onUp, {once: true});
  consoleResizer.addEventListener('pointercancel', onUp, {once: true});
});

consoleResizer.addEventListener('keydown', event => {
  const paso = event.shiftKey ? 64 : 24;
  const acciones = {
    ArrowUp: () => currentConsoleHeight() + paso,
    ArrowDown: () => currentConsoleHeight() - paso,
    Home: () => CONSOLE_MIN,
    End: consoleMax
  };
  const siguiente = acciones[event.key];
  if (!siguiente) return;
  event.preventDefault();
  if (!consoleDock.classList.contains('expanded')) setConsoleOpen(true);
  setConsoleHeight(siguiente());
});

// Al achicar la ventana el tope baja: reencuadrar sin pisar la preferencia.
window.addEventListener('resize', () => setConsoleHeight(currentConsoleHeight(), false));

// ── Atmosfera de fondo ─────────────────────────────────────────────────────
// Particulas en los cuatro colores semanticos de la paleta. Es decoracion
// deliberada, por eso queda fuera del arbol de accesibilidad y se apaga con
// prefers-reduced-motion y en pantallas chicas (via CSS).
function initParticles() {
  const canvas = document.getElementById('particles');
  if (!canvas || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  canvas.textContent = '';
  // Ambar dominante: es el tono que pidio el equipo para el fondo. Los otros
  // tres aparecen de a poco para que la capa no se lea monocroma.
  const tonos = ['--warn', '--warn', '--warn', '--brand', '--ok', '--info'];
  const total = innerWidth < 1100 ? 16 : 28;
  for (let i = 0; i < total; i++) {
    const p = document.createElement('div');
    const size = 1.5 + Math.random() * 2.5;
    p.className = 'particle';
    p.style.left = (Math.random() * 94).toFixed(2) + '%';
    p.style.width = p.style.height = size.toFixed(1) + 'px';
    // El amarillo pesa el doble: es el tono que da la sensacion de actividad.
    p.style.background = `var(${tonos[Math.floor(Math.random() * tonos.length)]})`;
    p.style.animationDuration = (16 + Math.random() * 20).toFixed(1) + 's';
    p.style.animationDelay = '-' + (Math.random() * 30).toFixed(1) + 's';
    p.style.setProperty('--p-drift', (Math.random() * 120 - 60).toFixed(0) + 'px');
    p.style.setProperty('--p-op', (0.18 + Math.random() * 0.26).toFixed(2));
    p.style.setProperty('--p-fast', (4 + Math.random() * 4).toFixed(1) + 's');
    canvas.appendChild(p);
  }
}
initParticles();

let reflowParticles;
addEventListener('resize', () => {
  clearTimeout(reflowParticles);
  reflowParticles = setTimeout(initParticles, 400);
});

// ── Onda al pulsar ─────────────────────────────────────────────────────────
document.addEventListener('pointerdown', event => {
  const control = event.target.closest('.btn, .prov-btn, .topic-chip, .theme-toggle, .modal-close');
  if (!control || control.disabled) return;
  const caja = control.getBoundingClientRect();
  const onda = document.createElement('span');
  onda.className = 'ad-ripple';
  const lado = Math.max(caja.width, caja.height) * 2.2;
  onda.style.width = onda.style.height = lado + 'px';
  onda.style.left = event.clientX - caja.left + 'px';
  onda.style.top = event.clientY - caja.top + 'px';
  control.appendChild(onda);
  onda.addEventListener('animationend', () => onda.remove(), {once: true});
});

// ── Cambio de tema ─────────────────────────────────────────────────────────
// Interpolate the palette itself, including browsers without View Transitions.
// A rapid second click reverses from the current colors instead of flashing.
const themeButton = document.getElementById('themeBtn');
if (themeButton && typeof window.toggleTheme === 'function') {
  const cambiarTema = window.toggleTheme;
  let themeTimer;
  window.toggleTheme = function (...args) {
    const raiz = document.documentElement;
    clearTimeout(themeTimer);
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
      raiz.classList.add('theme-changing');
      themeButton.classList.add('swapping');
      getComputedStyle(document.body).backgroundColor;
    }
    cambiarTema.apply(this, args);
    themeTimer = setTimeout(() => {
      raiz.classList.remove('theme-changing');
      themeButton.classList.remove('swapping');
    }, 420);
  };
}

// ── Estado del sistema en el pie del riel ──────────────────────────────────
// Se alimenta de nodos que ya estan en la pagina: no agrega peticiones.
const navProvider = document.getElementById('navProvider');
const navNextRun = document.getElementById('navNextRun');
const navState = document.getElementById('navState');

function syncNavFoot() {
  const activo = document.querySelector('.prov-btn.active');
  if (activo) navProvider.textContent = activo.textContent.trim();
  const proxima = document.getElementById('statNextRunVal');
  if (proxima) navNextRun.textContent = proxima.textContent.trim() || '—';
  navState.textContent = document.body.classList.contains('op-running')
    ? 'Procesando' : 'En reposo';
}

syncNavFoot();
// Observadores acotados a las tres fuentes reales. Mirar todo el body haria
// que cada linea de log dispare el sync, y como este escribe dentro del body
// se realimentaria a si mismo.
const observador = new MutationObserver(syncNavFoot);
observador.observe(document.body, {attributes: true, attributeFilter: ['class']});
const barraProveedor = document.querySelector('.provider-toggle');
if (barraProveedor) {
  observador.observe(barraProveedor, {subtree: true, attributes: true, attributeFilter: ['class']});
}
const proximaCorrida = document.getElementById('statNextRunVal');
if (proximaCorrida) {
  observador.observe(proximaCorrida, {childList: true, characterData: true, subtree: true});
}
