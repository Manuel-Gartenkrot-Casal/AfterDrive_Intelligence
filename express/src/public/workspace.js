/* Navigation only: existing API handlers retain ownership of the data. */
const workspacePages = {
  redaccion: ['Redacción', 'Convertí noticias del sector en contenido con una voz propia.'],
  fuentes: ['Fuentes', 'Construí la base informativa de tus próximos contenidos.'],
  automatizacion: ['Automatización', 'Definí el ritmo de recopilación y redacción.'],
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
}

function selectWriting(kind) {
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
let dialogWasOpen = false;
new MutationObserver(() => {
  const open = resultDialog.classList.contains('open');
  if (open === dialogWasOpen) return;
  dialogWasOpen = open;
  if (open) returnFocus = document.activeElement;
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

function setConsoleOpen(open) {
  document.getElementById('execution-dock').classList.toggle('expanded', open);
  document.getElementById('execution-content').hidden = !open;
  document.getElementById('execution-collapse').hidden = !open;
  document.getElementById('execution-toggle').setAttribute('aria-expanded', String(open));
  document.body.classList.toggle('console-expanded', open);
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
    const dock = document.getElementById('execution-dock');
    activeOperation = {started: Date.now(), error: false, blocked: false};
    dock.dataset.result = '';
    dock.classList.add('running');
    document.body.classList.add('op-running');
    document.getElementById('execution-title').textContent = title;
    document.getElementById('execution-state').textContent = 'En curso';
    setConsoleOpen(true);
    const updateElapsed = () => {
      const seconds = Math.floor((Date.now() - activeOperation.started) / 1000);
      document.getElementById('execution-elapsed').textContent = `${seconds}s`;
    };
    updateElapsed();
    operationTimer = setInterval(updateElapsed, 1000);
    try {
      return await execute(...args);
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
      activeOperation = null;
    }
  };
});

openWorkspace(location.hash.slice(1), false);
