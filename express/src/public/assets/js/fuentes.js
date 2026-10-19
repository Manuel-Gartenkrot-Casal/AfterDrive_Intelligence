/* fuentes.js — Fuentes de noticias.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   ADD URL
   ═══════════════════════════════════════════════════════════════════════ */
async function loadTrustedUrls() {
  try {
    var r = await fetch('/api/trusted-urls');
    var d = await r.json();
    var list = $('trusted-urls-list');
    var badge = $('trusted-urls-count');
    if (!list) return;
    var n = d.urls ? d.urls.length : 0;
    badge.textContent = n + (n === 1 ? ' fuente' : ' fuentes');
    if (!d.urls || d.urls.length === 0) {
      list.innerHTML = '<div class="fuentes-vacio">Todavía no hay fuentes. Agregá una a mano o sumá una recomendada.</div>';
      return;
    }
    list.innerHTML = d.urls.map(function(u) {
      var activa = u.estado === 'activo';
      return '<div class="fuente-fila' + (activa ? '' : ' pausada') + '">'
        + '<div class="fuente-info"><div class="fuente-url" title="'+escHtml(u.url)+'">'+escHtml(u.url)+'</div>'
        + '<div class="fuente-meta">'+(activa?'✓ activa':'⏸ pausada')+(u.ultima_ejecucion?' · '+new Date(u.ultima_ejecucion).toLocaleDateString(localeUI()):'')+'</div></div>'
        + '<button class="btn btn-xs" onclick="pausarFuente(\''+encArg(u.url)+'\', '+activa+', this)">'+(activa?'Pausar':'Activar')+'</button>'
        + '<button class="icon-btn" title="Eliminar" aria-label="Eliminar fuente '+escHtml(u.url)+'" onclick="deleteTrustedUrl(\''+encArg(u.url)+'\')">✕</button>'
        + '</div>';
    }).join('');
  } catch(e) {}
}

async function addUrlDirect() {
  var url = $('url-in').value.trim();
  if (!url) return;
  var el = $('url-status');
  var btn = $('btn-addurl-direct');
  btn.disabled = true;
  el.className = 'feedback info';
  el.textContent = 'Guardando...';
  try {
    var r = await fetch('/api/trusted-urls', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: url})
    });
    var d = await r.json();
    if (d.success) {
      el.className = 'feedback ok';
      el.textContent = 'URL guardada como activa';
      $('url-in').value = '';
      log('URL agregada directamente: ' + url, 'success');
      showToast('URL guardada', 'success');
      loadTrustedUrls();
      updateStats();
    } else {
      el.className = 'feedback err';
      el.textContent = 'Error: ' + (d.error || 'Fallo');
    }
  } catch(e) { el.className = 'feedback err'; el.textContent = 'Error de conexion'; }
  finally { btn.disabled = false; }
}

async function pausarFuente(encodedUrl, activa, btn) {
  var url = decodeURIComponent(encodedUrl);
  btn.disabled = true;
  try {
    await pedir('/api/trusted-urls/' + encodedUrl, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({estado: activa ? 'inactivo' : 'activo'})
    });
    log((activa ? 'Fuente pausada: ' : 'Fuente activada: ') + url, 'info');
    loadTrustedUrls();
    updateStats();
  } catch(e) {
    btn.disabled = false;
    showToast('No se pudo cambiar la fuente: ' + e.message, 'error');
  }
}

async function deleteTrustedUrl(encodedUrl) {
  var url = decodeURIComponent(encodedUrl);
  var ok = await confirmar({
    titulo: '¿Eliminar esta fuente?',
    mensaje: url + ' deja de scrapearse y sale de la lista. Los artículos que ya se guardaron de ella no se borran. '
      + 'Si solo querés que deje de buscarse por un tiempo, pausala.',
    accion: 'Eliminar fuente'
  });
  if (!ok) return;
  try {
    await pedir('/api/trusted-urls/' + encodedUrl, {method: 'DELETE'});
    log('URL eliminada: ' + url, 'warn');
    showToast('Fuente eliminada', 'success');
    loadTrustedUrls();
    updateStats();
  } catch(e) {
    showToast('No se pudo eliminar la fuente: ' + e.message, 'error');
  }
}

async function addUrl() {
  var url = $('url-in').value;
  if (!url) return;
  var el = $('url-status');
  var btn = $('btn-addurl');
  btn.disabled = true;
  el.className = 'feedback info';
  el.textContent = 'Probando la fuente: se leen sus artículos y la IA decide si son del rubro...';
  var agregada = false, ultima = '';
  try {
    var fin = await correrEnCola('/api/corridas/probar-fuente', {url: url}, function(l) {
      if (l.indexOf('[OK] URL agregada') >= 0) agregada = true;
      if (/^\s*\[(FAIL|WARN|ERROR)\]/.test(l)) ultima = l.replace(/^\s*\[[A-Z]+\]\s*/, '');
      log(l, l.indexOf('[OK]') >= 0 ? 'success' : /\[(FAIL|ERROR)\]/.test(l) ? 'error' : 'info');
    }, function(d) {
      var t = textoEnCola(d);
      if (t) el.textContent = 'Hay otra corrida en curso: la prueba quedó ' + t.toLowerCase().replace('…', '') + '.';
      else el.textContent = 'Probando la fuente: se leen sus artículos y la IA decide si son del rubro...';
    });
    if (agregada) {
      el.className = 'feedback ok';
      el.textContent = 'Fuente agregada: tenía artículos del rubro.';
      $('url-in').value = '';
      showToast('Fuente agregada', 'success');
      loadTrustedUrls();
      updateStats();
    } else {
      el.className = 'feedback err';
      el.textContent = fin.estado === 'cancelada' ? 'La prueba se canceló.'
        : 'No se agregó: ' + (ultima || 'no se encontraron artículos del rubro.');
    }
  } catch(e) { el.className = 'feedback err'; el.textContent = e.message; }
  finally { btn.disabled = false; }
}
