/* estado.js — Indicador de actividad del header y estadísticas.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* Mientras corre un scraping, el header muestra una línea animada y el logo late.
   (Antes había además un gráfico de etapas del pipeline; se sacó: la actividad
   se sigue en el dock y en la sección Actividad.) */
function marcarHeaderActivo() {
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
