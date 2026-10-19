/* estado.js — Panel del pipeline y estadísticas.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   PIPELINE HUD
   ═══════════════════════════════════════════════════════════════════════ */
/* Lee un stream de texto y llama onLine por cada línea COMPLETA.
   Sin buffer, una línea que llega partida en dos chunks se mostraba rota. */
var PIPELINE_STAGES = ['pn-init','pn-scrape','pn-parse','pn-classify','pn-embed','pn-store'];
var PIPELINE_EDGES = ['pe-1','pe-2','pe-3','pe-4','pe-5'];
var currentStage = -1;

function resetPipeline() {
  currentStage = -1;
  PIPELINE_STAGES.forEach(function(id) {
    $(id).className = 'pipeline-node';
  });
  PIPELINE_EDGES.forEach(function(id) {
    $(id).className = 'pipeline-edge';
  });
  $('pipelineTicker').textContent = 'Inicializando...';
}

// Etapa -> marcadores que la emiten los scripts del backend (no substrings sueltos:
// antes 'ok' matcheaba en "MongoDB" y el HUD saltaba a Guardar al arrancar).
var PIPELINE_MARCAS = [
  [0, /iniciando|inicializ|\[run_automation\]|few-shot|con embedding disponibles/i, 'Preparando la corrida...'],
  [1, /scrapeando:|>>> url|explorand|intento \d+|modo tema/i, 'Leyendo las fuentes...'],
  [2, /enlaces encontrados|total art[ií]culos extra[ií]dos|t[oó]pico armado|generando (nota|art[ií]culo)/i, 'Extrayendo contenido...'],
  [3, /clasificando \[|generaci[oó]n completa/i, 'Clasificando con IA...'],
  [4, /generando embeddings|vectoriz/i, 'Vectorizando...'],
  [5, /nuevos art[ií]culos aprobados|nota guardada|art[ií]culo guardado/i, 'Guardando en la base...']
];

function advancePipeline(text) {
  var newStage = currentStage, ticker = null;
  PIPELINE_MARCAS.forEach(function(m) {
    if (m[1].test(text) && m[0] >= newStage) { newStage = m[0]; ticker = m[2]; }
  });
  if (ticker) $('pipelineTicker').textContent = ticker;
  if (newStage <= currentStage) return;
  for (var i = Math.max(currentStage, 0); i <= newStage; i++) {
    var nodo = $(PIPELINE_STAGES[i]);
    nodo.classList.remove('active');
    nodo.classList.add(i < newStage ? 'done' : 'active');
    if (i > 0) {
      var edge = $(PIPELINE_EDGES[i - 1]);
      edge.classList.remove('active');
      edge.classList.add(i < newStage ? 'done' : 'active');
    }
  }
  currentStage = newStage;
}

// estado: 'ok' | 'warn' | 'err'. Solo 'ok' completa todas las etapas.
function finishPipeline(estado, mensaje) {
  if (estado === true) estado = 'ok';
  if (estado === false) estado = 'err';
  PIPELINE_STAGES.forEach(function(id, i) {
    var n = $(id);
    n.classList.remove('active');
    if (estado === 'ok' || i < currentStage) n.classList.add('done');
  });
  PIPELINE_EDGES.forEach(function(id, i) {
    var e = $(id);
    e.classList.remove('active');
    if (estado === 'ok' || i < currentStage - 1) e.classList.add('done');
  });
  var hud = $('pipelineHud');
  hud.classList.remove('hud-ok', 'hud-warn', 'hud-err');
  hud.classList.add('hud-' + estado);
  $('pipelineTicker').textContent = mensaje ||
    (estado === 'ok' ? 'Pipeline completado.' : estado === 'warn' ? 'Terminó sin resultados nuevos.' : 'Terminó con errores.');
  clearTimeout(window._hudTimer);
  window._hudTimer = setTimeout(function() {
    hud.classList.remove('visible');
    document.body.classList.remove('hud-open');
  }, estado === 'ok' ? 4000 : 9000);
}

function showPipeline() {
  resetPipeline();
  clearTimeout(window._hudTimer);
  $('pipelineHud').classList.remove('hud-ok', 'hud-warn', 'hud-err');
  $('pipelineHud').classList.add('visible');
  document.body.classList.add('hud-open');
  $('appHeader').classList.add('active');
  $('logoEl').classList.add('pulse');
}

function hidePipelineHeader() {
  $('appHeader').classList.remove('active');
  $('logoEl').classList.remove('pulse');
}

/* ═══════════════════════════════════════════════════════════════════════
   BUTTON PHYSICS
   ═══════════════════════════════════════════════════════════════════════ */
document.addEventListener('mousedown', function(e) {
  var btn = e.target.closest('.btn');
  if (btn && !btn.disabled) btn.style.transform = 'scale(0.97)';
});
document.addEventListener('mouseup', function() {
  document.querySelectorAll('.btn').forEach(function(b) { b.style.transform = ''; });
});

/* ═══════════════════════════════════════════════════════════════════════
   STATS
   ═══════════════════════════════════════════════════════════════════════ */
var _firstStatsLoad = true;

async function updateStats() {
  try {
    var r = await fetch('/api/trusted-urls-stats');
    var d = await r.json();
    if (d.success) {
      if (_firstStatsLoad) { countUp($('statUrls'), d.activas, 900); } else { $('statUrls').textContent = d.activas.toLocaleString(); }
      $('statUrls').classList.add('flash');
      setTimeout(function() { $('statUrls').classList.remove('flash'); }, 600);
      $('statUrlsSub').textContent = d.total + ' registradas';
      $('c-fuentes').textContent = d.activas.toLocaleString(localeUI());
      if (d.ultima_ejecucion) {
        var dt = new Date(d.ultima_ejecucion);
        $('statLastRun').textContent = dt.toLocaleDateString(localeUI());
      } else {
        $('statLastRun').textContent = 'Nunca';
      }
    }
  } catch(e) {}

  try {
    var r2 = await fetch('/api/articulos-stats');
    var d2 = await r2.json();
    if (d2.success) {
      $('c-articulos').textContent = d2.total.toLocaleString(localeUI());
      if (_firstStatsLoad) { countUp($('statArticles'), d2.total, 1100); }
      else { $('statArticles').textContent = d2.total.toLocaleString(); }
      $('statArticles').classList.add('flash');
      setTimeout(function() { $('statArticles').classList.remove('flash'); }, 600);
    }
  } catch(e) { console.error('Error al cargar /api/articulos-stats:', e); }

  try {
    var r3 = await fetch('/api/scraping-config');
    var d3 = await r3.json();
    if (d3.success) {
      $('statNextRunVal').textContent = d3.next_execution ? new Date(d3.next_execution).toLocaleDateString(localeUI()) : 'Pausado';
      $('statInterval').textContent = 'A las ' + d3.hora + ', cada ' + d3.interval_days + ' día(s)';
    }
  } catch(e) {}

  try {
    var r4 = await fetch('/api/health');
    if (!r4.ok) throw new Error('HTTP ' + r4.status);
    var d4 = await r4.json();
    // Se aceptan las dos formas de respuesta: {status:'ok'} cuando Flask
    // responde directo (un solo contenedor) y {scrapers:{status:'ok'}}
    // cuando Express hace de proxy. Exigir solo la anidada dejaba el badge
    // en "Sin Conexion" para siempre en el despliegue de un contenedor.
    var ok = d4.status === 'ok' || (d4.scrapers && d4.scrapers.status === 'ok');
    if (ok) {
      $('statusPulse').className = 'status-dot';
      $('statusText').textContent = 'Online';
    } else { throw new Error('respuesta inesperada'); }
  } catch(e) {
    $('statusPulse').className = 'status-dot off';
    $('statusText').textContent = 'Sin Conexion';
  }

  _firstStatsLoad = false;
}
