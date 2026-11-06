/* promptsia.js — Prompts con IA (arriba de la sección Prompts).
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   La IA lee las calificaciones de las notas y mejora sola una COPIA de los
   prompts: cada pocas notas nuevas (mejora automática) o al tocar "Analizar y
   mejorar ahora". También se le puede pedir un cambio a mano. Todo se aplica
   directo en la copia y se puede deshacer; los prompts actuales nunca se tocan.
   Arriba se elige con cuáles escribe la redacción. Las mejoras corren en la cola
   (el registro se ve en la terminal). Ver afterdrive/prompts_ia.py. */

var PIA = { estado: null, abierto: false, corriendo: false };

function initPromptsIA() {
  $('pia-abrir').addEventListener('click', function() { abrirPanelIA(!PIA.abierto); });
  $('pia-mejorar').addEventListener('click', function() { mejorarPromptsIA(null); });
  $('pia-pedir').addEventListener('click', function() {
    var pedido = $('pia-pedido').value.trim();
    if (pedido.length < 8) { showToast(tr('Contá qué querés cambiar en los prompts.'), 'error'); $('pia-pedido').focus(); return; }
    mejorarPromptsIA(pedido, $('pia-pieza').value);
  });
  $('pia-pedido').addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); $('pia-pedir').click(); }
  });
  $('pia-restablecer-todo').addEventListener('click', function() { restablecerPromptIA(null); });
  var sw = $('pia-auto');
  sw.addEventListener('click', cambiarAutoIA);
  sw.addEventListener('keydown', function(ev) { if (ev.key === ' ' || ev.key === 'Enter') { ev.preventDefault(); cambiarAutoIA(); } });
  document.querySelectorAll('#pia-usar [role="radio"]').forEach(function(b) {
    b.addEventListener('click', function() { usarPromptsIA(b.dataset.usar); });
  });
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'prompts') cargarPromptsIA(); });
}

function abrirPanelIA(si) {
  PIA.abierto = si;
  $('pia-panel').hidden = !si;
  $('pia-abrir').setAttribute('aria-expanded', si ? 'true' : 'false');
  $('pia-abrir').textContent = tr(si ? 'Ocultar los cambios' : 'Ver qué cambió');
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
  var sw = $('pia-auto');
  sw.setAttribute('aria-checked', e.auto ? 'true' : 'false');
  sw.classList.toggle('active', !!e.auto);
  $('pia-auto-estado').textContent = e.auto ? tr('Cada') + ' ' + e.auto_cada + ' ' + tr('notas nuevas') : tr('Apagada');
  var ultima = (e.mejoras || [])[0];
  var partes = [];
  partes.push(e.cambiadas ? e.cambiadas + ' ' + tr(e.cambiadas === 1 ? 'pieza mejorada en la copia' : 'piezas mejoradas en la copia')
                          : tr('La copia todavía es igual a los prompts actuales'));
  if (ultima) partes.push(tr('última mejora') + ' ' + hace(ultima.fecha));
  if (e.auto) partes.push(e.faltan ? tr('la próxima, en') + ' ' + e.faltan + ' ' + tr(e.faltan === 1 ? 'nota' : 'notas')
                                   : tr('la próxima, después de la próxima nota'));
  $('pia-estado').textContent = partes.join(' · ');
  var sel = $('pia-pieza'), previa = sel.value;
  sel.innerHTML = '<option value="">' + escHtml(tr('La IA elige qué piezas cambiar')) + '</option>'
    + e.copia.map(function(c) { return '<option value="' + escHtml(c.clave) + '">' + escHtml(tr(c.titulo)) + '</option>'; }).join('');
  sel.value = previa;
  pintarDiagnosticoIA(e.analisis);
  pintarCopiaIA(e.copia);
  pintarMejorasIA(e.mejoras || []);
}

async function usarPromptsIA(usar) {
  if (!PIA.estado || PIA.estado.usar === usar) return;
  if (usar === 'ia' && !PIA.estado.cambiadas) {
    showToast(tr('La copia de la IA todavía es igual a los prompts actuales.'), 'info');
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

async function cambiarAutoIA() {
  if (!PIA.estado) return;
  try {
    PIA.estado = await pedir('/api/prompts-ia/auto', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ auto: !PIA.estado.auto })
    });
    pintarPromptsIA();
  } catch (e) { showToast(e.message, 'error'); }
}

/* ── Mejorar: corre en la cola y se sigue acá (y en la terminal) ──────── */

async function mejorarPromptsIA(pedido, clave) {
  if (PIA.corriendo) return;
  PIA.corriendo = true;
  var btn = pedido ? $('pia-pedir') : $('pia-mejorar'), texto = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = tr(pedido ? 'La IA está cambiando la copia…' : 'Analizando y mejorando…');
  var prog = $('pia-progreso');
  prog.hidden = false;
  prog.textContent = tr('En cola…');
  try {
    var d = await correrEnCola('/api/prompts-ia/mejorar', pedido ? { pedido: pedido, claves: clave ? [clave] : [] } : {},
      function(linea) {
        var m = linea.match(/\[PROMPTS IA\]\s*(.*)/) || linea.match(/^\[(?:OK|ERROR)\]\s*(.*)/);
        if (m) prog.textContent = m[1];
      },
      function(e) { var t = textoEnCola(e); if (t) prog.textContent = t; });
    await cargarPromptsIA();
    if (d.estado === 'ok') {
      showToast(tr('Listo: la IA mejoró la copia de los prompts.'), 'success');
      if (pedido) $('pia-pedido').value = '';
      abrirPanelIA(true);
    } else {
      showToast((d.error || tr('La IA no pudo mejorar los prompts.')), 'error');
    }
  } catch (e) { showToast(e.message, 'error'); }
  finally {
    PIA.corriendo = false;
    btn.disabled = false;
    btn.innerHTML = texto;
    prog.hidden = true;
  }
}

/* ── Último análisis ────────────────────────────────────────────────── */

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
  var d = a.diagnostico;
  if (d && d.resumen) html += '<p class="pia-resumen"><span class="pia-chispa" aria-hidden="true">✦</span>' + escHtml(d.resumen) + '</p>';
  if (d && d.problemas && d.problemas.length) {
    html += '<ol class="pia-problemas">' + d.problemas.map(function(p) {
      return '<li><div class="pia-problema-cabeza"><b>' + escHtml(p.titulo) + '</b>'
        + (p.titulo_pieza ? '<span class="pia-pieza-chip">' + escHtml(tr(p.titulo_pieza)) + '</span>' : '') + '</div>'
        + (p.detalle ? '<p>' + escHtml(p.detalle) + '</p>' : '')
        + (p.evidencia ? '<p class="pia-evidencia">' + escHtml(p.evidencia) + '</p>' : '') + '</li>';
    }).join('') + '</ol>';
  } else {
    var fallas = (s.errores || []).slice(0, 4).map(function(e) {
      return '<li><b>' + escHtml(tr(e.nombre)) + '</b> <span class="pia-veces">×' + e.veces + '</span>'
        + (e.ejemplos && e.ejemplos[0] ? '<span class="pia-ejemplo">' + escHtml(e.ejemplos[0]) + '</span>' : '') + '</li>';
    });
    if (fallas.length) html += '<h4 class="pia-sub">' + escHtml(tr('Lo que más se repite')) + '</h4><ul class="pia-fallas">' + fallas.join('') + '</ul>';
  }
  if (a.error) html += '<p class="pia-error">' + escHtml(a.error) + '</p>';
  html += '<p class="pia-fecha">' + escHtml(tr('Analizado')) + ' ' + escHtml(hace(a.fecha)) + '</p>';
  caja.innerHTML = html;
}

/* ── Cambios de la IA: la copia pieza por pieza y las últimas mejoras ── */

var _ORIGEN_MEJORA = { automatica: 'Automática', manual: 'Analizar y mejorar', pedido: 'Pedido' };

function pintarCopiaIA(copia) {
  var cambiadas = copia.filter(function(c) { return c.cambiada; });
  $('pia-restablecer-todo').hidden = !cambiadas.length;
  $('pia-copia').innerHTML = cambiadas.length ? cambiadas.map(function(c) {
    return '<li class="pia-copia-fila"><div><b>' + escHtml(tr(c.titulo)) + '</b>'
      + '<span class="pia-copia-meta">' + c.cambios + ' ' + escHtml(tr(c.cambios === 1 ? 'cambio' : 'cambios'))
      + (c.actualizado ? ' · ' + escHtml(hace(c.actualizado)) : '') + '</span>'
      + (c.desactualizada ? '<span class="pia-aviso">' + escHtml(tr('El prompt actual cambió después: revisá la copia.')) + '</span>' : '')
      + '</div><button type="button" class="btn btn-xs" data-ver="' + escHtml(c.clave) + '" aria-expanded="false">' + escHtml(tr('Ver diferencias')) + '</button>'
      + '<button type="button" class="btn btn-xs" data-deshacer="' + escHtml(c.clave) + '">' + escHtml(tr('Deshacer el último')) + '</button>'
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
  $('pia-copia').querySelectorAll('[data-deshacer]').forEach(function(b) {
    b.addEventListener('click', function() { deshacerPromptIA(b.dataset.deshacer, b); });
  });
  $('pia-copia').querySelectorAll('[data-restablecer]').forEach(function(b) {
    b.addEventListener('click', function() { restablecerPromptIA(b.dataset.restablecer); });
  });
}

function pintarMejorasIA(mejoras) {
  $('pia-mejoras').innerHTML = mejoras.length ? mejoras.map(function(m, i) {
    var aplicadas = (m.cambios || []).filter(function(c) { return c.aplicado; });
    return '<li class="pia-mejora' + (m.error && !aplicadas.length ? ' sin-cambios' : '') + '">'
      + '<div class="pia-mejora-cabeza"><span class="pia-origen ' + escHtml(m.origen) + '">' + escHtml(tr(_ORIGEN_MEJORA[m.origen] || m.origen)) + '</span>'
      + '<span class="pia-copia-meta">' + escHtml(hace(m.fecha)) + '</span></div>'
      + (m.origen === 'pedido' && m.pedido ? '<p class="pia-pedido-eco">“' + escHtml(m.pedido) + '”</p>' : '')
      + (m.resumen ? '<p>' + escHtml(m.resumen) + '</p>' : '')
      + (m.cambios || []).map(function(c, j) {
        return '<details class="pia-cambio' + (c.aplicado ? '' : ' con-errores') + '"><summary><b>' + escHtml(tr(c.titulo)) + '</b>'
          + (c.aplicado ? '' : ' <span class="pia-no-aplica">· ' + escHtml(tr('no se aplicó')) + '</span>')
          + (c.explicacion ? '<span class="pia-explicacion">' + escHtml(c.explicacion) + '</span>' : '') + '</summary>'
          + (c.errores || []).map(function(x) { return '<p class="pia-error">' + escHtml(x) + '</p>'; }).join('')
          + '<div class="prompts-diff" translate="no" data-mejora="' + i + '" data-cambio="' + j + '"></div></details>';
      }).join('')
      + (m.error ? '<p class="pia-aviso">' + escHtml(m.error) + '</p>' : '') + '</li>';
  }).join('') : '<li class="pia-vacio">' + escHtml(tr('Todavía no hubo mejoras.')) + '</li>';
  // Las diferencias se arman al abrir cada cambio.
  $('pia-mejoras').querySelectorAll('details.pia-cambio').forEach(function(det) {
    det.addEventListener('toggle', function() {
      var caja = det.querySelector('.prompts-diff');
      if (det.open && !caja.innerHTML) {
        var c = mejoras[+caja.dataset.mejora].cambios[+caja.dataset.cambio];
        caja.innerHTML = diffPromptHtml(c.antes, c.despues);
      }
    });
  });
}

async function deshacerPromptIA(clave, btn) {
  btn.disabled = true;
  try {
    await pedir('/api/prompts-ia/deshacer', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ clave: clave })
    });
    await cargarPromptsIA();
    showToast(tr('Listo: se deshizo el último cambio de la IA en esa pieza.'), 'success');
  } catch (e) { btn.disabled = false; showToast(e.message, 'error'); }
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
