/* promptsia.js — Prompts con IA: las dos pestañas de la sección Prompts.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   "Prompts actuales" es el editor de siempre (prompts.js). "Prompts de la IA"
   tiene la misma forma, con la COPIA que mejora la IA: el prompt completo con lo
   que cambió la IA marcado, el análisis de las notas, un lugar para pedirle un
   cambio y el historial. La IA mejora la copia sola cada pocas notas (mejora
   automática) o al tocar "Analizar y mejorar ahora"; todos los cambios van
   directo a la copia y se pueden deshacer. Los prompts actuales no se tocan
   nunca. "Usar estos prompts" elige con cuáles escribe la redacción.
   Ver afterdrive/prompts_ia.py. Usa _filasPrompt y _diffPrompt de prompts.js. */

var PIA = { estado: null, vista: 'actuales', corriendo: false, recien: [], elegida: null };

function initPromptsIA() {
  document.querySelectorAll('#prompts-vistas [role="tab"]').forEach(function(b) {
    b.addEventListener('click', function() { verVistaPrompts(b.dataset.vista); });
  });
  $('pv-volver').addEventListener('click', function() { usarPromptsIA('actuales'); });
  $('pia-usar').addEventListener('click', function() { usarPromptsIA(PIA.estado && PIA.estado.usar === 'ia' ? 'actuales' : 'ia'); });
  $('pia-mejorar').addEventListener('click', function() { mejorarPromptsIA(null); });
  $('pia-pedir').addEventListener('click', function() {
    var pedido = $('pia-pedido').value.trim();
    if (pedido.length < 8) { showToast(tr('Contá qué querés cambiar en los prompts.'), 'error'); $('pia-pedido').focus(); return; }
    mejorarPromptsIA(pedido, $('pia-pieza').value);
  });
  $('pia-pedido').addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); $('pia-pedir').click(); }
  });
  // La caja crece con lo que se escribe; enviar se habilita con un pedido de verdad.
  $('pia-pedido').addEventListener('input', ajustarPedidoIA);
  document.querySelectorAll('.pia-sugerencia').forEach(function(b) {
    b.addEventListener('click', function() { $('pia-pedido').value = b.textContent.trim(); ajustarPedidoIA(); $('pia-pedido').focus(); });
  });
  $('pia-restablecer-todo').addEventListener('click', function() { restablecerPromptIA(null); });
  $('pia-persona').addEventListener('change', pintarArchivoIA);
  var sw = $('pia-auto');
  sw.addEventListener('click', cambiarAutoIA);
  sw.addEventListener('keydown', function(ev) { if (ev.key === ' ' || ev.key === 'Enter') { ev.preventDefault(); cambiarAutoIA(); } });
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'prompts') cargarPromptsIA(); });
}

function ajustarPedidoIA() {
  var t = $('pia-pedido');
  t.style.height = 'auto';
  t.style.height = Math.min(220, Math.max(52, t.scrollHeight)) + 'px';
  $('pia-pedir').disabled = PIA.corriendo || t.value.trim().length < 8;
}

function verVistaPrompts(vista) {
  PIA.vista = vista;
  document.querySelectorAll('#prompts-vistas [role="tab"]').forEach(function(b) {
    b.setAttribute('aria-selected', b.dataset.vista === vista ? 'true' : 'false');
  });
  $('prompts-actuales').hidden = vista !== 'actuales';
  $('pia-vista').hidden = vista !== 'ia';
  pintarAvisoIA();
  if (vista === 'ia') pintarArchivoIA();
}

async function cargarPromptsIA() {
  try {
    PIA.estado = await pedir('/api/prompts-ia');
    pintarPromptsIA();
  } catch (e) { /* sin la API, la sección sigue funcionando como antes */ }
}

function pintarAvisoIA() {
  var e = PIA.estado, enIA = !!e && e.usar === 'ia';
  $('pv-aviso').hidden = !(enIA && PIA.vista === 'actuales');
}

function pintarPromptsIA() {
  var e = PIA.estado;
  if (!e) return;
  var enIA = e.usar === 'ia';
  document.querySelectorAll('#prompts-vistas [role="tab"]').forEach(function(b) {
    b.querySelector('.pv-uso').hidden = (b.dataset.vista === 'ia') !== enIA;
  });
  $('pv-ia-sub').textContent = e.cambiadas
    ? e.cambiadas + ' ' + tr(e.cambiadas === 1 ? 'pieza mejorada por la IA' : 'piezas mejoradas por la IA')
    : tr('Una copia que la IA mejora sola');
  pintarAvisoIA();
  // Estado de uso, como el de una pieza: "En uso" o "Sin usar".
  var est = $('pia-uso-estado');
  est.className = 'prompts-estado ' + (enIA ? 'activo' : 'borrador');
  est.textContent = enIA ? tr('En uso: la redacción escribe con estos') : tr('Sin usar: la redacción usa los actuales');
  var usar = $('pia-usar');
  usar.textContent = tr(enIA ? 'Volver a los actuales' : 'Usar estos prompts');
  usar.classList.toggle('pia-usando', enIA);
  var sw = $('pia-auto');
  sw.setAttribute('aria-checked', e.auto ? 'true' : 'false');
  sw.classList.toggle('active', !!e.auto);
  $('pia-auto-estado').textContent = e.auto ? tr('Cada') + ' ' + e.auto_cada + ' ' + tr('notas nuevas') : tr('Apagada');
  var ultima = (e.mejoras || [])[0], partes = [];
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
  $('pia-restablecer-todo').hidden = !e.cambiadas;
  pintarListaIA(e.copia);
  pintarDiagnosticoIA(e.analisis);
  pintarMejorasIA(e.mejoras || []);
  if (PIA.vista === 'ia') pintarArchivoIA();
}

/* ── La lista de piezas, como la de los actuales ─────────────────────── */

function pintarListaIA(copia) {
  var grupos = { base: tr('Base del prompt'), persona: tr('Personas') }, html = '';
  html += '<ul class="prompts-leyenda"><li class="estado-ia">' + escHtml(tr('Cambiada por la IA')) + '</li>'
    + '<li class="estado-original">' + escHtml(tr('Igual a la actual')) + '</li></ul>';
  ['base', 'persona'].forEach(function(g) {
    html += '<p class="prompts-grupo">' + escHtml(grupos[g]) + '</p>';
    copia.filter(function(c) { return c.grupo === g; }).forEach(function(c) {
      html += '<button type="button" class="prompts-item ' + (c.cambiada ? 'estado-ia' : 'estado-original') + (c.clave === PIA.elegida ? ' activo' : '')
        + '" data-clave="' + escHtml(c.clave) + '"' + (c.clave === PIA.elegida ? ' aria-current="true"' : '') + '>'
        + '<span class="prompts-item-punto" aria-hidden="true"></span>'
        + '<span class="prompts-item-nombre">' + escHtml(tr(c.titulo)) + '</span>'
        + '<span class="prompts-chip ' + (c.cambiada ? 'ia' : 'original') + '">'
        + escHtml(c.cambiada ? '✦ ' + c.cambios : tr('Igual')) + '</span></button>';
    });
  });
  $('pia-lista').innerHTML = html;
  $('pia-lista').querySelectorAll('.prompts-item').forEach(function(b) {
    b.addEventListener('click', function() { irAPiezaIA(b.dataset.clave, true); });
  });
}

/* La pieza elegida queda marcada en la lista y en el prompt. */
function marcarPiezaIA(clave) {
  PIA.elegida = clave;
  $('pia-lista').querySelectorAll('.prompts-item').forEach(function(b) {
    var si = b.dataset.clave === clave;
    b.classList.toggle('activo', si);
    if (si) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
  });
  $('pia-archivo').querySelectorAll('.pa-bloque').forEach(function(s) { s.classList.toggle('pia-elegida', s.dataset.clave === clave); });
}

async function irAPiezaIA(clave, bajar) {
  PIA.elegida = clave;
  if (clave.indexOf('persona_') === 0 && $('pia-persona').value !== clave.slice(8)) {
    $('pia-persona').value = clave.slice(8);
    await pintarArchivoIA();
  }
  marcarPiezaIA(clave);
  if (bajar) verPromptEnPantalla($('pia-archivo'));
  var bloque = $('pia-archivo').querySelector('.pa-bloque[data-clave="' + clave + '"]');
  if (!bloque) return;
  $('pia-archivo').scrollTop = bloque.offsetTop - 8;
  bloque.classList.remove('recien');
  void bloque.offsetWidth;
  bloque.classList.add('recien');
}

/* ── El prompt completo de la IA, con lo que cambió marcado ─────────── */

async function pintarArchivoIA() {
  var persona = $('pia-persona').value, caja = $('pia-archivo');
  var cuerpo = function(juego) {
    return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ persona: persona, juego: juego }) };
  };
  try {
    var r = await Promise.all([pedir('/api/prompts/vista-previa', cuerpo('ia')), pedir('/api/prompts/vista-previa', cuerpo('actuales'))]);
  } catch (e) {
    caja.innerHTML = '<p class="prompts-vacio">' + escHtml(tr('No se pudo armar la vista previa: ') + e.message) + '</p>';
    return;
  }
  var ia = r[0].partes, actuales = {}, num = { valor: 1 }, html = '', lineas = 0;
  r[1].partes.forEach(function(p) { actuales[p.clave] = p.texto; });
  var copia = {};
  ((PIA.estado && PIA.estado.copia) || []).forEach(function(c) { copia[c.clave] = c; });
  ia.forEach(function(parte) {
    var antes = actuales[parte.clave], cambiada = antes != null && antes !== parte.texto;
    lineas += parte.texto.split('\n').length;
    var cabeza = parte.editable
      ? '<span class="pa-pieza">' + escHtml(tr(parte.titulo)) + '</span>'
      : '<span class="pa-auto">' + escHtml(tr(parte.titulo)) + ' · ' + escHtml(tr('lo arma el sistema')) + '</span>';
    if (cambiada) {
      cabeza += '<span class="pia-marca-ia">✦ ' + escHtml(tr('Cambiada por la IA')) + '</span>'
        + '<span class="pia-bloque-acciones">'
        + '<button type="button" class="btn btn-xs" data-deshacer="' + escHtml(parte.clave) + '">' + escHtml(tr('Deshacer el último')) + '</button>'
        + '<button type="button" class="btn btn-xs" data-restablecer="' + escHtml(parte.clave) + '">' + escHtml(tr('Volver al actual')) + '</button></span>';
    }
    html += '<section class="pa-bloque' + (cambiada ? ' pia-cambiada' : '') + (parte.editable ? '' : ' automatico')
      + (PIA.recien.indexOf(parte.clave) >= 0 ? ' recien' : '') + (parte.clave === PIA.elegida ? ' pia-elegida' : '')
      + '" data-clave="' + escHtml(parte.clave) + '">'
      + '<div class="pa-bloque-cabeza">' + cabeza + '</div>'
      + (cambiada ? _diffPrompt(antes, parte.texto, num) : _filasPrompt(parte.texto.split('\n'), '', num)) + '</section>';
  });
  caja.innerHTML = html;
  $('pia-archivo-lineas').textContent = lineas + ' ' + tr('líneas');
  caja.querySelectorAll('[data-deshacer]').forEach(function(b) {
    b.addEventListener('click', function() { deshacerPromptIA(b.dataset.deshacer, b); });
  });
  caja.querySelectorAll('[data-restablecer]').forEach(function(b) {
    b.addEventListener('click', function() { restablecerPromptIA(b.dataset.restablecer); });
  });
}

/* ── Acciones ───────────────────────────────────────────────────────── */

async function usarPromptsIA(usar) {
  if (!PIA.estado || PIA.estado.usar === usar) return;
  try {
    PIA.estado = await pedir('/api/prompts-ia/usar', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ usar: usar })
    });
    pintarPromptsIA();
    showToast(usar === 'ia' ? tr('Las próximas notas se escriben con los prompts de la IA.')
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

/* Corre en la cola. Al terminar se muestra el prompt de la IA con lo que cambió marcado
   y, arriba, qué cambió y por qué. */
async function mejorarPromptsIA(pedido, clave) {
  if (PIA.corriendo) return;
  PIA.corriendo = true;
  var btn = pedido ? $('pia-pedir') : $('pia-mejorar'), texto = btn.innerHTML;
  btn.disabled = true;
  if (pedido) btn.classList.add('cargando');
  else btn.textContent = tr('Analizando y mejorando…');
  var prog = $('pia-progreso');
  prog.hidden = false;
  prog.textContent = tr('En cola…');
  $('pia-resultado').hidden = true;
  try {
    var d = await correrEnCola('/api/prompts-ia/mejorar', pedido ? { pedido: pedido, claves: clave ? [clave] : [] } : {},
      function(linea) {
        var m = linea.match(/\[PROMPTS IA\]\s*(.*)/) || linea.match(/^\[(?:OK|ERROR)\]\s*(.*)/);
        if (m) prog.textContent = m[1];
      },
      function(e) { var t = textoEnCola(e); if (t) prog.textContent = t; });
    PIA.estado = await pedir('/api/prompts-ia');
    var mejora = (PIA.estado.mejoras || [])[0];
    PIA.recien = mejora ? (mejora.cambios || []).filter(function(c) { return c.aplicado; }).map(function(c) { return c.clave; }) : [];
    if (PIA.recien.length) PIA.elegida = PIA.recien[0];
    if (pedido && d.estado === 'ok') { $('pia-pedido').value = ''; ajustarPedidoIA(); }
    verVistaPrompts('ia');
    pintarPromptsIA();
    pintarResultadoIA(mejora, d);
    var primero = $('pia-archivo').querySelector('.pa-bloque.recien');
    if (primero) $('pia-archivo').scrollTop = primero.offsetTop - 8;
  } catch (e) { showToast(e.message, 'error'); }
  finally {
    PIA.corriendo = false;
    btn.disabled = false;
    btn.classList.remove('cargando');
    btn.innerHTML = texto;
    prog.hidden = true;
    ajustarPedidoIA();
  }
}

function pintarResultadoIA(mejora, d) {
  var caja = $('pia-resultado');
  var aplicadas = mejora ? (mejora.cambios || []).filter(function(c) { return c.aplicado; }) : [];
  caja.hidden = false;
  caja.className = 'pia-resultado ' + (aplicadas.length ? 'ok' : 'sin-cambios');
  if (!aplicadas.length) {
    caja.innerHTML = '<b>' + escHtml(tr('La IA no cambió nada esta vez.')) + '</b>'
      + '<p>' + escHtml((mejora && mejora.error) || d.error || tr('La IA no pudo mejorar los prompts.')) + '</p>';
    return;
  }
  caja.innerHTML = '<b>✦ ' + escHtml(tr('La IA cambió')) + ' ' + aplicadas.length + ' '
    + escHtml(tr(aplicadas.length === 1 ? 'pieza de la copia' : 'piezas de la copia')) + '</b>'
    + (mejora.resumen ? '<p>' + escHtml(mejora.resumen) + '</p>' : '')
    + '<ul>' + aplicadas.map(function(c) {
      return '<li><button type="button" class="pia-ir" data-clave="' + escHtml(c.clave) + '">' + escHtml(tr(c.titulo)) + '</button>'
        + (c.explicacion ? ' ' + escHtml(c.explicacion) : '') + '</li>';
    }).join('') + '</ul><p class="pia-nota">' + escHtml(tr('Abajo, en el prompt de la IA, lo nuevo está marcado en verde y lo que salió, en rojo.')) + '</p>';
  caja.querySelectorAll('.pia-ir').forEach(function(b) { b.addEventListener('click', function() { irAPiezaIA(b.dataset.clave, true); }); });
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

/* ── Análisis e historial ───────────────────────────────────────────── */

function _nota(v, de) { return v == null ? '—' : String(v).replace('.', ',') + '<small>/' + de + '</small>'; }

function pintarDiagnosticoIA(a) {
  var caja = $('pia-diagnostico');
  $('pia-analisis-fecha').textContent = a ? hace(a.fecha) : '';
  if (!a) {
    caja.innerHTML = '<p class="pia-vacio">' + escHtml(tr('Todavía no se analizaron las notas: tocá "Analizar y mejorar ahora".')) + '</p>';
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
    html += '<p class="pia-compara">' + escHtml(tr('Con los prompts de la IA')) + ': <b>' + _nota(juegos.ia.redaccion, 10) + '</b> '
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
  }
  if (a.error) html += '<p class="pia-error">' + escHtml(a.error) + '</p>';
  caja.innerHTML = html;
}

var _ORIGEN_MEJORA = { automatica: 'Automática', manual: 'Analizar y mejorar', pedido: 'Pedido' };

function pintarMejorasIA(mejoras) {
  $('pia-historial-cuenta').textContent = mejoras.length ? mejoras.length : '';
  $('pia-mejoras').innerHTML = mejoras.length ? mejoras.map(function(m) {
    var aplicadas = (m.cambios || []).filter(function(c) { return c.aplicado; });
    return '<li class="pia-mejora' + (aplicadas.length ? '' : ' sin-cambios') + '">'
      + '<div class="pia-mejora-cabeza"><span class="pia-origen ' + escHtml(m.origen) + '">' + escHtml(tr(_ORIGEN_MEJORA[m.origen] || m.origen)) + '</span>'
      + '<span class="pia-caja-meta">' + escHtml(hace(m.fecha)) + '</span></div>'
      + (m.origen === 'pedido' && m.pedido ? '<p class="pia-pedido-eco">“' + escHtml(m.pedido) + '”</p>' : '')
      + (aplicadas.length ? '<p>' + aplicadas.map(function(c) { return '<b>' + escHtml(tr(c.titulo)) + '</b>' + (c.explicacion ? ': ' + escHtml(c.explicacion) : ''); }).join('<br>') + '</p>' : '')
      + (m.error ? '<p class="pia-aviso">' + escHtml(m.error) + '</p>' : '') + '</li>';
  }).join('') : '<li class="pia-vacio">' + escHtml(tr('Todavía no hubo mejoras.')) + '</li>';
}
