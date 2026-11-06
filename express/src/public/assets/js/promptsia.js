/* promptsia.js — Prompts con IA (sección Prompts).
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   1. Por qué las notas no sacan más: la IA lee las calificaciones de las últimas
      notas y los prompts y dice qué falla y en qué pieza.
   2. Pedile un cambio: la IA reescribe piezas de una COPIA de los prompts. Se ven
      las diferencias y se decide si se aplica.
   3. Copia de la IA: lo que cambió. Arriba se elige con qué escribe la redacción:
      los prompts actuales (nunca se tocan desde acá) o la copia de la IA.
   Ver afterdrive/prompts_ia.py. */

var PIA = { estado: null, abierto: false };

function initPromptsIA() {
  $('pia-abrir').addEventListener('click', function() { abrirPanelIA(!PIA.abierto); });
  $('pia-analizar').addEventListener('click', analizarPromptsIA);
  $('pia-proponer').addEventListener('click', proponerPromptsIA);
  $('pia-restablecer-todo').addEventListener('click', function() { restablecerPromptIA(null); });
  document.querySelectorAll('#pia-usar [role="radio"]').forEach(function(b) {
    b.addEventListener('click', function() { usarPromptsIA(b.dataset.usar); });
  });
  // Pedido con Ctrl/⌘+Enter.
  $('pia-pedido').addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); proponerPromptsIA(); }
  });
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'prompts') cargarPromptsIA(); });
}

function abrirPanelIA(si) {
  PIA.abierto = si;
  $('pia-panel').hidden = !si;
  $('pia-abrir').setAttribute('aria-expanded', si ? 'true' : 'false');
  $('pia-abrir').classList.toggle('activo', si);
  if (si) cargarPromptsIA();
}

async function cargarPromptsIA() {
  try {
    PIA.estado = await pedir('/api/prompts-ia');
    pintarPromptsIA();
  } catch (e) { /* sin la API, la sección sigue funcionando como antes */ }
}

function pintarPromptsIA() {
  var e = PIA.estado;
  if (!e) return;
  document.querySelectorAll('#pia-usar [role="radio"]').forEach(function(b) {
    b.setAttribute('aria-checked', b.dataset.usar === e.usar ? 'true' : 'false');
  });
  $('pia-cambiadas').textContent = e.cambiadas ? e.cambiadas : '';
  $('pia-cambiadas').title = e.cambiadas ? tr('Piezas cambiadas por la IA') + ': ' + e.cambiadas : '';
  var sel = $('pia-pieza'), previa = sel.value;
  sel.innerHTML = '<option value="">' + escHtml(tr('La IA elige qué piezas cambiar')) + '</option>'
    + e.copia.map(function(c) { return '<option value="' + escHtml(c.clave) + '">' + escHtml(tr(c.titulo)) + '</option>'; }).join('');
  sel.value = previa;
  pintarDiagnosticoIA(e.analisis);
  pintarPropuestasIA(e.propuestas);
  pintarCopiaIA(e.copia);
}

async function usarPromptsIA(usar) {
  if (!PIA.estado || PIA.estado.usar === usar) return;
  if (usar === 'ia' && !PIA.estado.cambiadas) {
    showToast(tr('La copia de la IA todavía es igual a los prompts actuales: pedile un cambio primero.'), 'info');
  }
  try {
    PIA.estado = await pedir('/api/prompts-ia/usar', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ usar: usar })
    });
    pintarPromptsIA();
    showToast(usar === 'ia' ? tr('Las próximas notas se escriben con la copia de la IA.')
                            : tr('Las próximas notas se escriben con los prompts actuales.'), 'success');
  } catch (e) { showToast(e.message, 'error'); }
}

/* ── 1. Diagnóstico ─────────────────────────────────────────────────── */

function _nota(v, de) { return v == null ? '—' : String(v).replace('.', ',') + '<small>/' + de + '</small>'; }

function pintarDiagnosticoIA(a) {
  var caja = $('pia-diagnostico');
  if (!a) {
    caja.innerHTML = '<p class="pia-vacio">' + escHtml(tr('Todavía no se analizaron las notas.')) + '</p>';
    return;
  }
  var s = a.estadisticas || {}, html = '';
  html += '<div class="pia-kpis">'
    + '<div class="pia-kpi"><strong>' + (s.notas || 0) + '</strong><span>' + escHtml(tr('notas analizadas')) + '</span></div>'
    + '<div class="pia-kpi"><strong>' + _nota(s.redaccion, 10) + '</strong><span>' + escHtml(tr('redacción (crítica)')) + '</span></div>'
    + '<div class="pia-kpi"><strong>' + _nota(s.juez, 5) + '</strong><span>' + escHtml(tr('calificación del juez')) + '</span></div>'
    + '<div class="pia-kpi"><strong>' + _nota(s.humana, 5) + '</strong><span>' + escHtml(tr('calificación del equipo')) + '</span></div>'
    + '</div>';
  var juegos = s.por_juego || {};
  if (juegos.ia && juegos.actuales) {
    html += '<p class="pia-compara">' + escHtml(tr('Con la copia de la IA')) + ': <b>' + _nota(juegos.ia.redaccion, 10) + '</b> '
      + escHtml(tr('en')) + ' ' + juegos.ia.notas + ' ' + escHtml(tr('notas')) + ' · '
      + escHtml(tr('con los actuales')) + ': <b>' + _nota(juegos.actuales.redaccion, 10) + '</b></p>';
  }
  var fallas = (s.errores || []).slice(0, 4).map(function(e) {
    return '<li><b>' + escHtml(tr(e.nombre)) + '</b> <span class="pia-veces">×' + e.veces + '</span>'
      + (e.ejemplos && e.ejemplos[0] ? '<span class="pia-ejemplo">' + escHtml(e.ejemplos[0]) + '</span>' : '') + '</li>';
  }).concat((s.alephee || []).slice(0, 2).map(function(x) {
    return '<li><b>' + escHtml(tr('Checklist de Alephee')) + '</b> <span class="pia-veces">×' + x.veces + '</span>'
      + '<span class="pia-ejemplo">' + escHtml(x.texto) + '</span></li>';
  }));
  if (fallas.length) html += '<h4 class="pia-sub">' + escHtml(tr('Lo que más se repite')) + '</h4><ul class="pia-fallas">' + fallas.join('') + '</ul>';
  var d = a.diagnostico;
  if (d) {
    if (d.resumen) html += '<p class="pia-resumen"><span class="pia-chispa" aria-hidden="true">✦</span>' + escHtml(d.resumen) + '</p>';
    html += '<ol class="pia-problemas">' + (d.problemas || []).map(function(p, i) {
      return '<li><div class="pia-problema-cabeza"><b>' + escHtml(p.titulo) + '</b>'
        + (p.titulo_pieza ? '<span class="pia-pieza-chip">' + escHtml(tr(p.titulo_pieza)) + '</span>' : '') + '</div>'
        + (p.detalle ? '<p>' + escHtml(p.detalle) + '</p>' : '')
        + (p.evidencia ? '<p class="pia-evidencia">' + escHtml(p.evidencia) + '</p>' : '')
        + (p.pedido ? '<button type="button" class="btn btn-xs" data-problema="' + i + '">' + escHtml(tr('Pedir este cambio')) + '</button>' : '')
        + '</li>';
    }).join('') + '</ol>';
  }
  if (a.error) html += '<p class="pia-error">' + escHtml(a.error) + '</p>';
  html += '<p class="pia-fecha">' + escHtml(tr('Analizado')) + ' ' + escHtml(hace(a.fecha)) + '</p>';
  caja.innerHTML = html;
  caja.querySelectorAll('[data-problema]').forEach(function(b) {
    b.addEventListener('click', function() {
      var p = d.problemas[+b.dataset.problema];
      $('pia-pedido').value = p.pedido;
      $('pia-pieza').value = p.pieza || '';
      $('pia-pedido').focus();
    });
  });
}

async function analizarPromptsIA() {
  var btn = $('pia-analizar');
  btn.disabled = true;
  btn.textContent = tr('Analizando…');
  $('pia-diagnostico').setAttribute('aria-busy', 'true');
  try {
    var r = await pedir('/api/prompts-ia/analizar', { method: 'POST' });
    PIA.estado.analisis = r.analisis;
    pintarDiagnosticoIA(r.analisis);
  } catch (e) { showToast(e.message, 'error'); }
  finally {
    btn.disabled = false;
    btn.textContent = tr('Analizar de nuevo');
    $('pia-diagnostico').removeAttribute('aria-busy');
  }
}

/* ── 2. Pedido y propuestas ─────────────────────────────────────────── */

async function proponerPromptsIA() {
  var pedido = $('pia-pedido').value.trim(), clave = $('pia-pieza').value;
  if (pedido.length < 8) { showToast(tr('Contá qué querés cambiar en los prompts.'), 'error'); $('pia-pedido').focus(); return; }
  var btn = $('pia-proponer');
  btn.disabled = true;
  btn.textContent = tr('La IA está escribiendo…');
  try {
    var r = await pedir('/api/prompts-ia/proponer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ pedido: pedido, claves: clave ? [clave] : [] })
    });
    PIA.estado.propuestas = [r.propuesta].concat(PIA.estado.propuestas || []);
    pintarPropuestasIA(PIA.estado.propuestas);
    $('pia-pedido').value = '';
  } catch (e) { showToast(e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = tr('Proponer cambios'); }
}

function pintarPropuestasIA(lista) {
  $('pia-propuestas').innerHTML = (lista || []).map(function(p) {
    var aplicables = p.cambios.filter(function(c) { return !c.errores.length; }).length;
    return '<article class="pia-propuesta" data-id="' + escHtml(p.id) + '">'
      + '<header><span class="pia-chispa" aria-hidden="true">✦</span><div><b>' + escHtml(tr('Propuesta')) + '</b>'
      + '<p class="pia-pedido-eco">“' + escHtml(p.pedido) + '”</p>'
      + (p.comentario ? '<p>' + escHtml(p.comentario) + '</p>' : '') + '</div></header>'
      + p.cambios.map(function(c) {
        return '<section class="pia-cambio' + (c.errores.length ? ' con-errores' : '') + '">'
          + '<h5>' + escHtml(tr(c.titulo)) + (c.errores.length ? ' <span class="pia-no-aplica">· ' + escHtml(tr('no se puede aplicar')) + '</span>' : '') + '</h5>'
          + (c.explicacion ? '<p>' + escHtml(c.explicacion) + '</p>' : '')
          + c.errores.map(function(x) { return '<p class="pia-error">' + escHtml(x) + '</p>'; }).join('')
          + c.avisos.map(function(x) { return '<p class="pia-aviso">' + escHtml(x) + '</p>'; }).join('')
          + '<div class="prompts-diff" translate="no">' + diffPromptHtml(c.antes, c.despues) + '</div></section>';
      }).join('')
      + '<footer><button type="button" class="btn btn-sm" data-accion="descartar">' + escHtml(tr('Descartar')) + '</button>'
      + '<button type="button" class="btn btn-primary btn-sm" data-accion="aplicar"' + (aplicables ? '' : ' disabled') + '>'
      + escHtml(tr('Aplicar a la copia de la IA')) + '</button></footer></article>';
  }).join('');
  $('pia-propuestas').querySelectorAll('.pia-propuesta').forEach(function(art) {
    art.querySelector('[data-accion="aplicar"]').addEventListener('click', function() { aplicarPropuestaIA(art.dataset.id, this); });
    art.querySelector('[data-accion="descartar"]').addEventListener('click', function() { descartarPropuestaIA(art.dataset.id, this); });
  });
}

async function aplicarPropuestaIA(id, btn) {
  btn.disabled = true;
  try {
    var analisis = PIA.estado.analisis;
    PIA.estado = await pedir('/api/prompts-ia/propuestas/' + encodeURIComponent(id) + '/aplicar', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
    });
    PIA.estado.analisis = PIA.estado.analisis || analisis;
    pintarPromptsIA();
    showToast(PIA.estado.usar === 'ia' ? tr('Aplicada: las próximas notas ya la usan.')
                                       : tr('Aplicada a la copia. Elegí "Copia de la IA" arriba para que la redacción la use.'), 'success');
  } catch (e) { btn.disabled = false; showToast(e.message, 'error'); }
}

async function descartarPropuestaIA(id, btn) {
  btn.disabled = true;
  try {
    await pedir('/api/prompts-ia/propuestas/' + encodeURIComponent(id), { method: 'DELETE' });
    PIA.estado.propuestas = PIA.estado.propuestas.filter(function(p) { return p.id !== id; });
    pintarPropuestasIA(PIA.estado.propuestas);
  } catch (e) { btn.disabled = false; showToast(e.message, 'error'); }
}

/* ── 3. Copia de la IA ──────────────────────────────────────────────── */

function pintarCopiaIA(copia) {
  var cambiadas = copia.filter(function(c) { return c.cambiada; });
  $('pia-restablecer-todo').hidden = !cambiadas.length;
  $('pia-copia').innerHTML = cambiadas.length ? cambiadas.map(function(c) {
    return '<li class="pia-copia-fila"><div><b>' + escHtml(tr(c.titulo)) + '</b>'
      + '<span class="pia-copia-meta">' + c.cambios + ' ' + escHtml(tr(c.cambios === 1 ? 'cambio' : 'cambios'))
      + (c.actualizado ? ' · ' + escHtml(hace(c.actualizado)) : '') + '</span>'
      + (c.desactualizada ? '<span class="pia-aviso">' + escHtml(tr('El prompt actual cambió después: revisá la copia.')) + '</span>' : '')
      + '</div><button type="button" class="btn btn-xs" data-ver="' + escHtml(c.clave) + '" aria-expanded="false">' + escHtml(tr('Ver diferencias')) + '</button>'
      + '<button type="button" class="btn btn-xs" data-restablecer="' + escHtml(c.clave) + '">' + escHtml(tr('Volver al actual')) + '</button>'
      + '<div class="prompts-diff" translate="no" hidden></div></li>';
  }).join('') : '<li class="pia-vacio">' + escHtml(tr('La copia es igual a los prompts actuales: la IA todavía no cambió nada.')) + '</li>';
  $('pia-copia').querySelectorAll('[data-ver]').forEach(function(b) {
    b.addEventListener('click', async function() {
      var caja = b.parentNode.querySelector('.prompts-diff');
      var abrir = caja.hidden;
      b.setAttribute('aria-expanded', abrir ? 'true' : 'false');
      if (abrir && !caja.innerHTML) {
        try {
          var p = await pedir('/api/prompts-ia/pieza/' + encodeURIComponent(b.dataset.ver));
          caja.innerHTML = diffPromptHtml(p.actual, p.ia);
        } catch (e) { showToast(e.message, 'error'); return; }
      }
      caja.hidden = !abrir;
    });
  });
  $('pia-copia').querySelectorAll('[data-restablecer]').forEach(function(b) {
    b.addEventListener('click', function() { restablecerPromptIA(b.dataset.restablecer); });
  });
}

async function restablecerPromptIA(clave) {
  var ok = await confirmar({
    titulo: clave ? tr('¿Volver esta pieza al prompt actual?') : tr('¿Volver toda la copia a los prompts actuales?'),
    mensaje: tr('Se borran los cambios de la IA en la copia. Los prompts actuales no cambian.'),
    accion: tr('Volver a los actuales')
  });
  if (!ok) return;
  try {
    await pedir('/api/prompts-ia/restablecer', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ clave: clave })
    });
    await cargarPromptsIA();
  } catch (e) { showToast(e.message, 'error'); }
}
