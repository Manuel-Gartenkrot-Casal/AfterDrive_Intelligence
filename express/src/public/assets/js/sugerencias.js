/* sugerencias.js — Fuentes recomendadas.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   DISCOVER
   ═══════════════════════════════════════════════════════════════════════ */
function renderSugerencias(urls) {
  var list = $('sug-list');
  list.innerHTML = '';
  if (!urls.length) {
    list.innerHTML = '<div class="fuentes-vacio"><span>No hay recomendaciones pendientes. Tocá <strong>Buscar recomendaciones</strong> para encontrar sitios nuevos del sector.</span></div>';
    return;
  }
  urls.forEach(function(u) {
    var item = document.createElement('div');
    item.className = 'suggestion-item';
    var titulo = u.titulo ? '<div class="suggestion-title">' + escHtml(u.titulo) + '</div>' : '';
    if (u.origen === 'ia') titulo += '<div class="suggestion-title">Sugerida por la IA (sitio verificado)</div>';
    item.innerHTML =
      '<div class="suggestion-info"><div class="suggestion-url">' + escHtml(u.dominio || u.url) + '</div>' + titulo + '</div>' +
      '<div class="suggestion-actions">' +
        '<button class="btn btn-sm btn-primary" onclick="addSug(\'' + encArg(u.url) + '\', this)">Agregar</button>' +
        '<button class="icon-btn" title="Descartar" aria-label="Descartar recomendación" onclick="descartarSug(\'' + encArg(u.url) + '\', this)">✕</button>' +
      '</div>';
    list.appendChild(item);
  });
}

async function loadSugerencias() {
  try {
    var r = await fetch('/api/suggested-urls');
    var d = await r.json();
    renderSugerencias(d.success ? d.urls : []);
  } catch(e) { renderSugerencias([]); }
}

async function discover() {
  var btn = $('btn-disc');
  btn.disabled = true;
  btn.textContent = 'Buscando...';
  $('sug-list').innerHTML = '<div class="fuentes-vacio"><span>Buscando sitios del sector...</span></div>';
  log('Buscando fuentes recomendadas...', 'warn');
  try {
    var fin = await correrEnCola('/api/corridas/recomendaciones', null, function(l) { log(l, 'info'); }, function(d) {
      var t = textoEnCola(d);
      btn.textContent = t || 'Buscando...';
    });
    if (fin.estado !== 'ok') log('La búsqueda terminó: ' + NOMBRE_ESTADO[fin.estado].toLowerCase() + '.', 'warn');
    if (fin.estado === 'error') showToast(fin.error || 'No se pudo buscar. Mirá el registro en Actividad.', 'error');
    var r2 = await fetch('/api/suggested-urls');
    var d2 = await r2.json();
    var urls = d2.success ? d2.urls : [];
    renderSugerencias(urls);
    log(urls.length ? urls.length + ' fuentes recomendadas' : 'No se encontraron fuentes nuevas', urls.length ? 'success' : 'info');
    if (urls.length) showToast(urls.length + ' fuentes recomendadas', 'success');
  } catch(e) {
    log('Error buscando fuentes', 'error');
    renderSugerencias([]);
  }
  finally { btn.disabled = false; btn.textContent = 'Buscar recomendaciones'; }
}

async function addSug(encodedUrl, btn) {
  var url = decodeURIComponent(encodedUrl);
  btn.disabled = true;
  try {
    var r = await fetch('/api/trusted-urls', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: url})
    });
    var d = await r.json();
    if (!d.success) throw new Error(d.error || 'Fallo');
    log('Fuente agregada: ' + url, 'success');
    showToast('Fuente agregada', 'success');
    loadTrustedUrls();
    loadSugerencias();
    updateStats();
  } catch(e) {
    btn.disabled = false;
    log('No se pudo agregar la fuente: ' + e.message, 'error');
  }
}

async function descartarSug(encodedUrl, btn) {
  var url = decodeURIComponent(encodedUrl);
  var dominio = url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0];
  var ok = await confirmar({
    titulo: '¿Descartar esta recomendación?',
    mensaje: 'Se descartan todas las recomendaciones de ' + dominio + '. Podés volver a encontrarlas con Buscar recomendaciones.',
    accion: 'Descartar'
  });
  if (!ok) return;
  btn.disabled = true;
  try {
    await pedir('/api/suggested-urls', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: url})
    });
    loadSugerencias();
  } catch(e) {
    btn.disabled = false;
    showToast('No se pudo descartar: ' + e.message, 'error');
  }
}
