/* metricas.js — Tablero de la vista Desarrollador (Inicio).
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Los datos vienen de /api/metricas (afterdrive/metricas.py). Los gráficos
   son SVG armados a mano, al ancho real del contenedor, con un tooltip por
   columna. Arriba, una fila de indicadores con su variación contra el
   período anterior (`anterior` en la respuesta). Rojo de la marca = lo que
   se guardó o escribió, azul = lo que se descartó: la misma codificación en
   todos los gráficos (paleta validada para daltonismo en los dos temas). El
   estado de las corridas y del gasto va siempre con ícono y texto. */

var _tablero = { dias: 14, datos: null, pedido: 0 };
var _NUM = new Intl.NumberFormat('es-AR');
var _NUM1 = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });
var _COMPACTO = new Intl.NumberFormat('es-AR', { notation: 'compact', maximumFractionDigits: 1 });
var _USD = new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });

function _plural(n, uno, varios) { return _NUM.format(n) + ' ' + (n === 1 ? uno : varios); }
function _suma(xs) { return xs.reduce(function(a, b) { return a + b; }, 0); }
function _pct(parte, total) { return total ? Math.round(parte * 100 / total) + '%' : '—'; }
function _diaCorto(iso) { var p = iso.split('-'); return p[2] + '/' + p[1]; }
function _diaLargo(iso) {
  var d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { weekday: 'short', day: 'numeric', month: 'short' });
}
function _duracion(s) {
  if (s === null || s === undefined) return '—';
  return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + (s % 60 ? (s % 60) + ' s' : '');
}

// Tope "lindo" para el eje, siempre par: la línea del medio cae en un entero.
function _topeEje(max) {
  if (max <= 4) return 4;
  var pot = Math.pow(10, Math.floor(Math.log10(max)));
  var pasos = [1, 2, 4, 6, 8, 10];
  for (var i = 0; i < pasos.length; i++) if (pasos[i] * pot >= max) return pasos[i] * pot;
  return 10 * pot;
}

/* ── Tooltip compartido ──────────────────────────────────────────────── */
function _tooltip() {
  var t = $('tablero-tooltip');
  if (!t) {
    t = document.createElement('div');
    t.id = 'tablero-tooltip';
    t.className = 'tablero-tooltip';
    t.setAttribute('role', 'tooltip');
    t.hidden = true;
    document.body.appendChild(t);
  }
  return t;
}
function _mostrarTooltip(ev, html) {
  var t = _tooltip();
  t.innerHTML = html;
  t.hidden = false;
  var r = t.getBoundingClientRect();
  var x = Math.min(ev.clientX + 14, window.innerWidth - r.width - 8);
  var y = ev.clientY - r.height - 12;
  if (y < 8) y = ev.clientY + 16;
  t.style.left = Math.max(8, x) + 'px';
  t.style.top = y + 'px';
}
function _ocultarTooltip() { var t = $('tablero-tooltip'); if (t) t.hidden = true; }

function _filaTooltip(clase, texto, valor) {
  return '<div class="tt-fila"><i class="' + clase + '"></i><span>' + escHtml(texto) + '</span><b>' + valor + '</b></div>';
}

/* ── Columnas apiladas por día ───────────────────────────────────────── */
// series: [{nombre, valores, clase}] de abajo hacia arriba.
function _columnas(el, dias, series) {
  var ancho = Math.max(260, el.clientWidth), alto = 190;
  var izq = 34, der = 6, arriba = 10, abajo = 24;
  var n = dias.length, banda = (ancho - izq - der) / n;
  var grosor = Math.min(24, Math.max(4, banda * 0.62));
  var totales = dias.map(function(_, i) { return _suma(series.map(function(s) { return s.valores[i]; })); });
  var tope = _topeEje(Math.max.apply(null, totales.concat([1])));
  var y = function(v) { return arriba + (alto - arriba - abajo) * (1 - v / tope); };
  var svg = '<svg width="' + ancho + '" height="' + alto + '" role="img" aria-hidden="true">';

  // Grilla: 0, mitad y tope.
  [0, tope / 2, tope].forEach(function(v) {
    svg += '<line class="grilla" x1="' + izq + '" x2="' + (ancho - der) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>';
    svg += '<text class="eje" x="' + (izq - 6) + '" y="' + (y(v) + 3.5) + '" text-anchor="end">' + (v >= 10000 ? _COMPACTO.format(v) : _NUM.format(v)) + '</text>';
  });
  // Etiquetas de días: todas si entran, si no una de cada k (siempre la última).
  var k = Math.ceil(36 / banda);
  dias.forEach(function(d, i) {
    if ((n - 1 - i) % k) return;
    svg += '<text class="eje" x="' + (izq + banda * (i + 0.5)) + '" y="' + (alto - 6) + '" text-anchor="middle">' + _diaCorto(d) + '</text>';
  });

  dias.forEach(function(d, i) {
    var x = izq + banda * (i + 0.5) - grosor / 2, base = y(0);
    var visibles = series.filter(function(s) { return s.valores[i] > 0; });
    visibles.forEach(function(s, j) {
      var h = (alto - arriba - abajo) * s.valores[i] / tope;
      var gap = j > 0 ? 2 : 0;   // 2px del color de la superficie entre segmentos
      var arribaSeg = base - h, alturaSeg = Math.max(1, h - gap);
      if (j === visibles.length - 1) {
        var r = Math.min(4, alturaSeg, grosor / 2);   // solo la punta de arriba va redondeada
        svg += '<path class="' + s.clase + '" style="--i:' + i + ';--base:' + y(0) + 'px" d="M' + x + ',' + (base - gap) + 'V' + (arribaSeg + r) +
          'Q' + x + ',' + arribaSeg + ' ' + (x + r) + ',' + arribaSeg + 'H' + (x + grosor - r) +
          'Q' + (x + grosor) + ',' + arribaSeg + ' ' + (x + grosor) + ',' + (arribaSeg + r) + 'V' + (base - gap) + 'Z"/>';
      } else {
        svg += '<rect class="' + s.clase + '" style="--i:' + i + ';--base:' + y(0) + 'px" x="' + x + '" y="' + arribaSeg + '" width="' + grosor + '" height="' + alturaSeg + '"/>';
      }
      base = arribaSeg;
    });
    // Zona de hover: toda la banda, más grande que la barra.
    svg += '<rect class="hit" data-i="' + i + '" x="' + (izq + banda * i) + '" y="' + arriba + '" width="' + banda + '" height="' + (alto - arriba - abajo) + '"/>';
  });
  svg += '</svg>';

  var tabla = '<table class="sr-only"><caption>' + escHtml(series.map(function(s) { return s.nombre; }).join(' y ')) + ' por día</caption>' +
    '<tr><th>Día</th>' + series.map(function(s) { return '<th>' + escHtml(s.nombre) + '</th>'; }).join('') + '</tr>' +
    dias.map(function(d, i) {
      return '<tr><td>' + _diaLargo(d) + '</td>' + series.map(function(s) { return '<td>' + s.valores[i] + '</td>'; }).join('') + '</tr>';
    }).join('') + '</table>';
  el.innerHTML = svg + tabla;

  el.querySelectorAll('.hit').forEach(function(h) {
    h.addEventListener('mousemove', function(ev) {
      var i = +h.dataset.i;
      el.querySelectorAll('.hit').forEach(function(o) { o.classList.toggle('activo', o === h); });
      _mostrarTooltip(ev, '<div class="tt-titulo">' + _diaLargo(dias[i]) + '</div>' +
        series.slice().reverse().map(function(s) { return _filaTooltip(s.clase, s.nombre, _NUM.format(s.valores[i])); }).join(''));
    });
    h.addEventListener('mouseleave', function() { h.classList.remove('activo'); _ocultarTooltip(); });
  });
}

/* ── Indicadores (fila de arriba) ────────────────────────────────────── */
// Línea fina por día, con el último punto marcado y un tooltip por día.
function _sparkline(el, dias, valores, formato) {
  var ancho = Math.max(120, el.clientWidth), alto = 40, pad = 4;
  var max = Math.max.apply(null, valores.concat([1])), n = valores.length;
  var x = function(i) { return pad + (ancho - 2 * pad) * (n > 1 ? i / (n - 1) : 0.5); };
  var y = function(v) { return pad + (alto - 2 * pad) * (1 - v / max); };
  var linea = valores.map(function(v, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1); }).join('');
  var banda = (ancho - 2 * pad) / Math.max(1, n - 1);
  el.innerHTML = '<svg width="' + ancho + '" height="' + alto + '" aria-hidden="true">' +
    '<path class="spark-area" d="' + linea + 'L' + x(n - 1) + ',' + (alto - pad) + 'L' + x(0) + ',' + (alto - pad) + 'Z"/>' +
    '<path class="spark-linea" pathLength="1" d="' + linea + '"/>' +
    '<circle class="spark-punto" cx="' + x(n - 1) + '" cy="' + y(valores[n - 1]) + '" r="3.5"/>' +
    '<line class="spark-guia" y1="' + pad + '" y2="' + (alto - pad) + '" x1="-9" x2="-9"/>' +
    valores.map(function(_, i) {
      return '<rect class="hit" data-i="' + i + '" x="' + (x(i) - banda / 2) + '" y="0" width="' + banda + '" height="' + alto + '"/>';
    }).join('') + '</svg>';
  var guia = el.querySelector('.spark-guia');
  el.querySelectorAll('.hit').forEach(function(h) {
    h.addEventListener('mousemove', function(ev) {
      var i = +h.dataset.i;
      guia.setAttribute('x1', x(i)); guia.setAttribute('x2', x(i));
      _mostrarTooltip(ev, '<div class="tt-titulo">' + _diaLargo(dias[i]) + '</div><div class="tt-fila"><span>' + formato(valores[i]) + '</span></div>');
    });
    h.addEventListener('mouseleave', function() { guia.setAttribute('x1', -9); guia.setAttribute('x2', -9); _ocultarTooltip(); });
  });
}

// Variación contra el período anterior del mismo largo. bueno: 'sube', 'baja' o null (neutral).
function _variacion(actual, anterior, bueno, dias) {
  var contra = '<span class="var-contra">vs ' + dias + ' días previos</span>';
  if (!anterior && !actual) return '<p class="indicador-var var-igual">Sin datos ' + contra + '</p>';
  if (!anterior) return '<p class="indicador-var var-igual"><span aria-hidden="true">●</span> Nuevo ' + contra + '</p>';
  var pct = Math.round((actual - anterior) * 100 / anterior);
  if (!pct) return '<p class="indicador-var var-igual"><span aria-hidden="true">=</span> Igual ' + contra + '</p>';
  var sube = pct > 0, clase = !bueno ? 'var-igual' : (sube === (bueno === 'sube') ? 'var-bien' : 'var-mal');
  return '<p class="indicador-var ' + clase + '"><span aria-hidden="true">' + (sube ? '▲' : '▼') + '</span> ' +
    '<span class="sr-only">' + (sube ? 'Subió' : 'Bajó') + ' </span>' + _NUM.format(Math.abs(pct)) + '% ' + contra + '</p>';
}

function _pastilla(nv) {
  return '<span class="pastilla ' + nv.clase + '"><span aria-hidden="true">' + nv.icono + '</span> ' + nv.texto + '</span>';
}

function _indicador(o) {
  return '<article class="indicador' + (o.destacado ? ' indicador-destacado' : '') + '">' +
    '<header class="indicador-cabeza"><h3>' + o.titulo + '</h3></header>' +
    '<p class="indicador-valor">' + o.valor + (o.unidad ? '<small>' + o.unidad + '</small>' : '') + '</p>' +
    // El estado va en la misma línea que la variación de los otros: así las cifras quedan alineadas.
    (o.variacion || '<p class="indicador-var">' + o.pastilla + '</p>') +
    (o.medidor !== undefined
      ? '<div class="medidor ' + (o.nivel || '') + '" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(o.medidor) +
        '" aria-label="' + o.titulo + '"><span style="width:' + Math.min(100, o.medidor) + '%"></span></div>'
      : '<div class="indicador-spark" data-spark="' + o.spark + '"></div>') +
    '<p class="indicador-pie">' + o.pie + '</p>' +
  '</article>';
}

function _pintarIndicadores(d) {
  var a = d.articulos, n = d.notas, t = d.tokens, g = d.gasto, ant = d.anterior || {}, nd = d.dias.length;
  var guardados = _suma(a.guardados), descartados = _suma(a.descartados), escritas = _suma(n.escritas);
  var tokens = t.entrada + t.salida;
  var tokensDia = t.entrada_por_dia.map(function(e, i) { return e + t.salida_por_dia[i]; });
  var corr = d.corridas, totalCorr = _suma(corr.map(function(c) { return c.total; })), okCorr = _suma(corr.map(function(c) { return c.ok; }));
  var exito = totalCorr ? okCorr / totalCorr : null, nvCorr = _nivel(exito);
  var usado = g.tope_usd ? g.mes_usd / g.tope_usd : 0;
  var nvGasto = usado >= 1 ? { clase: 'nivel-err', icono: '✕', texto: 'tope alcanzado' }
              : usado >= 0.7 ? { clase: 'nivel-warn', icono: '!', texto: 'atención' }
              : { clase: 'nivel-ok', icono: '✓', texto: 'en orden' };
  var tasa = guardados + descartados ? descartados / (guardados + descartados) : 0;
  var tasaAnt = (ant.guardados || 0) + (ant.descartados || 0) ? ant.descartados / (ant.guardados + ant.descartados) : 0;
  var pp = Math.round((tasa - tasaAnt) * 100);

  var series = [a.guardados, n.escritas, a.descartados, tokensDia];
  var formatos = [
    function(v) { return _plural(v, 'artículo guardado', 'artículos guardados'); },
    function(v) { return _plural(v, 'nota escrita', 'notas escritas'); },
    function(v) { return _plural(v, 'descartado', 'descartados'); },
    function(v) { return _NUM.format(v) + ' tokens'; },
  ];
  var el = $('indicadores');
  el.innerHTML = [
    _indicador({ titulo: 'Artículos guardados', valor: _NUM.format(guardados), destacado: true,
      variacion: _variacion(guardados, ant.guardados, 'sube', nd), spark: 0,
      pie: _NUM1.format(guardados / nd) + ' por día en promedio' }),
    _indicador({ titulo: 'Notas escritas', valor: _NUM.format(escritas),
      variacion: _variacion(escritas, ant.escritas, 'sube', nd), spark: 1,
      pie: _plural(_suma(n.descartadas), 'versión descartada', 'versiones descartadas') }),
    _indicador({ titulo: 'Descarte del filtro', valor: _NUM.format(Math.round(tasa * 100)), unidad: '%',
      variacion: '<p class="indicador-var var-igual"><span aria-hidden="true">' + (pp > 0 ? '▲' : pp < 0 ? '▼' : '=') + '</span> ' +
        (pp ? _NUM.format(Math.abs(pp)) + ' pts' : 'Igual') + ' <span class="var-contra">vs ' + nd + ' días previos</span></p>',
      spark: 2, pie: _plural(descartados, 'artículo descartado', 'artículos descartados') }),
    _indicador({ titulo: 'Corridas que terminaron bien', valor: exito === null ? '—' : _NUM.format(Math.round(exito * 100)), unidad: exito === null ? '' : '%',
      pastilla: _pastilla(nvCorr), medidor: exito === null ? 0 : exito * 100, nivel: nvCorr.clase,
      pie: _plural(totalCorr, 'corrida', 'corridas') + ' en ' + d.ventana_larga + ' días' }),
    _indicador({ titulo: 'API paga este mes', valor: _USD.format(g.mes_usd),
      pastilla: _pastilla(nvGasto), medidor: usado * 100, nivel: nvGasto.clase,
      pie: Math.round(usado * 100) + '% del tope de ' + _USD.format(g.tope_usd) }),
    _indicador({ titulo: 'Tokens de la IA', valor: (t.estimadas ? '≈ ' : '') + _COMPACTO.format(tokens),
      variacion: _variacion(tokens, ant.tokens, null, nd), spark: 3,
      pie: _plural(t.llamadas, 'llamada', 'llamadas') + ' · ' + _plural(t.cortadas, 'cortada', 'cortadas') }),
  ].join('');
  el.querySelectorAll('[data-spark]').forEach(function(s) {
    var i = +s.dataset.spark;
    _sparkline(s, d.dias, series[i], formatos[i]);
  });
}

/* ── Bloques ─────────────────────────────────────────────────────────── */
function _pintarArticulos(d) {
  var a = d.articulos, g = _suma(a.guardados), x = _suma(a.descartados);
  $('tc-art-cifra').innerHTML = '<b>' + _NUM.format(g) + '</b> guardados · ' + _pct(x, g + x) + ' descartados';
  _columnas($('g-articulos'), d.dias, [
    { nombre: 'Guardados', valores: a.guardados, clase: 'serie-1' },
    { nombre: 'Descartados', valores: a.descartados, clase: 'serie-2' },
  ]);
}

function _pintarNotas(d) {
  var n = d.notas, e = _suma(n.escritas), x = _suma(n.descartadas);
  $('tc-notas-cifra').innerHTML = '<b>' + _NUM.format(e) + '</b> ' + (e === 1 ? 'escrita' : 'escritas') + ' · ' + _plural(x, 'versión descartada', 'versiones descartadas');
  _columnas($('g-notas'), d.dias, [
    { nombre: 'Escritas', valores: n.escritas, clase: 'serie-1' },
    { nombre: 'Descartadas', valores: n.descartadas, clase: 'serie-2' },
  ]);
}

function _pintarFuentes(d) {
  var f = d.articulos.fuentes, el = $('g-fuentes');
  $('tc-fuentes-cifra').textContent = 'Últimos ' + d.ventana_larga + ' días';
  if (!f.length) { el.innerHTML = '<p class="tablero-vacio">Todavía no hay artículos en este período.</p>'; return; }
  var max = Math.max.apply(null, f.map(function(s) { return s.guardados + s.descartados; }));
  el.innerHTML = f.map(function(s, i) {
    var total = s.guardados + s.descartados;
    return '<div class="barra-fila" data-i="' + i + '">' +
      '<span class="barra-nombre" title="' + escHtml(s.sitio) + '">' + escHtml(s.sitio) + '</span>' +
      '<span class="barra-pista"><span class="barra-largo" style="width:' + (total * 100 / max) + '%">' +
        (s.guardados ? '<i class="serie-1" style="flex:' + s.guardados + '"></i>' : '') +
        (s.descartados ? '<i class="serie-2" style="flex:' + s.descartados + '"></i>' : '') +
      '</span></span>' +
      '<span class="barra-valor"><b>' + _NUM.format(s.guardados) + '</b>' + (s.descartados ? ' · ' + _NUM.format(s.descartados) + ' desc.' : '') + '</span>' +
    '</div>';
  }).join('');
  el.querySelectorAll('.barra-fila').forEach(function(fila) {
    var s = f[+fila.dataset.i];
    fila.addEventListener('mousemove', function(ev) {
      _mostrarTooltip(ev, '<div class="tt-titulo">' + escHtml(s.sitio) + '</div>' +
        _filaTooltip('serie-1', 'Guardados', _NUM.format(s.guardados)) +
        _filaTooltip('serie-2', 'Descartados', _NUM.format(s.descartados)) +
        '<div class="tt-pie">' + _pct(s.descartados, s.guardados + s.descartados) + ' descartado por el filtro</div>');
    });
    fila.addEventListener('mouseleave', _ocultarTooltip);
  });
}

function _nivel(exito) {
  if (exito === null) return { clase: 'nivel-nada', icono: '–', texto: 'sin corridas' };
  if (exito >= 0.9) return { clase: 'nivel-ok', icono: '✓', texto: 'estable' };
  if (exito >= 0.7) return { clase: 'nivel-warn', icono: '!', texto: 'con fallas' };
  return { clase: 'nivel-err', icono: '✕', texto: 'fallando seguido' };
}

function _pintarCorridas(d) {
  var c = d.corridas, total = _suma(c.map(function(t) { return t.total; }));
  var ok = _suma(c.map(function(t) { return t.ok; }));
  $('tc-corridas-cifra').innerHTML = total ? '<b>' + _pct(ok, total) + '</b> terminaron bien · ' + d.ventana_larga + ' días'
                                           : 'Sin corridas en ' + d.ventana_larga + ' días';
  $('g-corridas').innerHTML = c.map(function(t) {
    var nv = _nivel(t.exito), pct = t.exito === null ? 0 : Math.round(t.exito * 100);
    var otros = t.cancelada + t.interrumpida;
    return '<div class="corrida-metrica">' +
      '<div class="cm-cabeza"><span class="cm-nombre">' + escHtml(t.etiqueta) + '</span>' +
        '<span class="cm-nivel ' + nv.clase + '"><span aria-hidden="true">' + nv.icono + '</span> ' + nv.texto + '</span></div>' +
      '<div class="medidor ' + nv.clase + '" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct + '" aria-label="Éxito de ' + escHtml(t.etiqueta) + '">' +
        '<span style="width:' + pct + '%"></span></div>' +
      '<ul class="cm-cuentas">' +
        '<li><span aria-hidden="true">✓</span> ' + _NUM.format(t.ok) + ' bien</li>' +
        '<li><span aria-hidden="true">✕</span> ' + _NUM.format(t.error) + ' con error</li>' +
        '<li><span aria-hidden="true">–</span> ' + _plural(otros, 'cortada', 'cortadas') + '</li>' +
        '<li class="cm-dur">Mediana ' + _duracion(t.duracion_mediana_s) + '</li>' +
      '</ul></div>';
  }).join('');
}

function _pintarCalidad(d) {
  var n = d.notas;
  var totalEstados = _suma(Object.values(n.estados));
  $('tc-calidad-cifra').textContent = 'Notas de los últimos ' + d.ventana_larga + ' días';
  var nombres = { borrador: 'Para revisar', aprobada: 'Aprobadas', publicado: 'Publicadas', rechazada: 'Rechazadas' };
  $('g-calidad').innerHTML =
    '<div class="cifras-fila">' +
      '<div class="cifra-grande"><strong>' + (n.puntaje_promedio === null ? '—' : _NUM1.format(n.puntaje_promedio)) +
        '<small> / 9</small></strong><span>lineamientos cumplidos en promedio</span></div>' +
      '<div class="cifra-grande"><strong>' + (n.calificacion_promedio === null ? '—' : _NUM1.format(n.calificacion_promedio)) +
        '<small> / 5</small></strong><span>calificación del equipo' + (n.calificadas ? ' (' + _plural(n.calificadas, 'nota', 'notas') + ')' : '') + '</span></div>' +
      '<div class="cifra-grande"><strong>' + (n.intentos_promedio === null ? '—' : _NUM1.format(n.intentos_promedio)) +
        '</strong><span>intentos por nota (reescrituras)</span></div>' +
    '</div>' +
    (totalEstados ? '<ul class="estados-notas">' + Object.keys(nombres).map(function(k) {
      return '<li><span>' + nombres[k] + '</span><b>' + _NUM.format(n.estados[k] || 0) + '</b></li>';
    }).join('') + '</ul>' : '<p class="tablero-vacio">Todavía no hay notas en este período.</p>');
}

function _pintarGasto(d) {
  var g = d.gasto, usado = g.tope_usd ? g.mes_usd / g.tope_usd : 0;
  var nv = usado >= 0.9 ? 'nivel-err' : usado >= 0.7 ? 'nivel-warn' : 'nivel-ok';
  $('tc-gasto-cifra').innerHTML = '<b>' + _USD.format(g.mes_usd) + '</b> de ' + _USD.format(g.tope_usd);
  var tareas = Object.keys(g.por_tarea);
  var nombres = { redaccion: 'Redacción', clasificacion: 'Clasificación', evaluacion: 'Evaluación', planificacion: 'Plan', general: 'Otras' };
  $('g-gasto').innerHTML =
    '<div class="medidor medidor-alto ' + nv + '" role="meter" aria-valuemin="0" aria-valuemax="' + g.tope_usd + '" aria-valuenow="' + g.mes_usd + '" aria-label="Gasto del mes">' +
      '<span style="width:' + Math.min(100, usado * 100) + '%"></span></div>' +
    '<p class="gasto-nota">' + Math.round(usado * 100) + '% del tope mensual' + (usado >= 1 ? ' · se usa NVIDIA hasta el mes que viene' : '') + '</p>' +
    (tareas.length ? '<ul class="gasto-tareas">' + tareas.map(function(t) {
      return '<li><span>' + escHtml(nombres[t] || t) + '</span><b>' + _USD.format(g.por_tarea[t]) + '</b></li>';
    }).join('') + '</ul>' : '<p class="tablero-vacio">Este mes todavía no se usó la API paga.</p>');
}

var _NOMBRE_TAREA = { redaccion: 'Redacción', clasificacion: 'Clasificación', evaluacion: 'Evaluación',
  planificacion: 'Plan', correccion: 'Corrección', embeddings: 'Embeddings', general: 'Otras' };

// Los modelos de Bedrock son ARNs: se muestra solo el id del final.
function _modeloCorto(m) { return String(m || '').split('/').pop(); }

function _tabla(columnas, filas, vacio) {
  if (!filas.length) return '<p class="tablero-vacio">' + vacio + '</p>';
  return '<table class="tabla-metricas"><thead><tr>' + columnas.map(function(c) {
    return '<th scope="col"' + (c.num ? ' class="num"' : '') + '>' + c.t + '</th>';
  }).join('') + '</tr></thead><tbody>' + filas.join('') + '</tbody></table>';
}

function _pintarTokens(d) {
  var t = d.tokens;
  var aprox = t.estimadas ? '≈ ' : '';
  $('tc-tokens-cifra').innerHTML = '<b>' + _NUM.format(t.llamadas) + '</b> llamadas · ' + aprox + _COMPACTO.format(t.entrada + t.salida) +
    ' tokens · ' + _plural(t.cortadas, 'cortada', 'cortadas') + ' por el límite';
  _columnas($('g-tokens'), d.dias, [
    { nombre: 'Entrada', valores: t.entrada_por_dia, clase: 'serie-1' },
    { nombre: 'Salida', valores: t.salida_por_dia, clase: 'serie-2' },
  ]);
  $('t-tokens-tareas').innerHTML = _tabla(
    [{ t: 'Tarea' }, { t: 'Llamadas', num: true }, { t: 'Entrada', num: true }, { t: 'Salida', num: true },
     { t: 'Salida por llamada', num: true }, { t: 'Límite', num: true }, { t: 'Cortadas', num: true }],
    t.por_tarea.map(function(x) {
      return '<tr><th scope="row">' + escHtml(_NOMBRE_TAREA[x.tarea] || x.tarea) + '</th>' +
        '<td class="num">' + _NUM.format(x.llamadas) + '</td><td class="num">' + _NUM.format(x.entrada) + '</td>' +
        '<td class="num">' + _NUM.format(x.salida) + '</td><td class="num">' + _NUM.format(Math.round(x.salida / x.llamadas)) + '</td>' +
        '<td class="num">' + (x.limite ? _NUM.format(x.limite) : '—') + '</td>' +
        '<td class="num' + (x.cortadas ? ' es-cortada' : '') + '">' + _NUM.format(x.cortadas) + '</td></tr>';
    }), 'Sin llamadas a la IA en este período.');
  $('t-tokens-recientes').innerHTML = _tabla(
    [{ t: 'Cuándo' }, { t: 'Tarea' }, { t: 'Proveedor y modelo' }, { t: 'Entrada', num: true }, { t: 'Salida', num: true },
     { t: 'Límite', num: true }, { t: '' }],
    t.recientes.map(function(r) {
      var cuando = new Date(r.fecha).toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
      var marcas = (r.truncado ? '<span class="marca es-cortada">Cortada</span>' : '') +
                   (r.estimado ? '<span class="marca" title="El proveedor no informó los tokens: se estimaron.">Estimado</span>' : '');
      var a = r.estimado ? '≈ ' : '';
      return '<tr><td class="mono">' + cuando + '</td><th scope="row">' + escHtml(_NOMBRE_TAREA[r.tarea] || r.tarea || '—') + '</th>' +
        '<td class="mono" title="' + escHtml(r.modelo || '') + '">' + escHtml(r.proveedor + ' · ' + _modeloCorto(r.modelo)) + '</td>' +
        '<td class="num">' + a + _NUM.format(r.tokens_entrada || 0) + '</td><td class="num">' + a + _NUM.format(r.tokens_salida || 0) + '</td>' +
        '<td class="num">' + (r.max_tokens ? _NUM.format(r.max_tokens) : '—') + '</td><td>' + marcas + '</td></tr>';
    }), 'Todavía no hay llamadas registradas.');
}

function _pintarTablero() {
  var d = _tablero.datos;
  if (!d) return;
  _pintarIndicadores(d);
  _pintarArticulos(d);
  _pintarNotas(d);
  _pintarFuentes(d);
  _pintarCorridas(d);
  _pintarCalidad(d);
  _pintarGasto(d);
  _pintarTokens(d);
}

async function cargarTablero() {
  if (document.documentElement.getAttribute('data-modo') !== 'dev') return;
  var pedido = ++_tablero.pedido, estado = $('tablero-estado'), grilla = document.querySelector('.tablero-grid');
  estado.textContent = _tablero.datos ? '' : 'Cargando métricas…';
  grilla.classList.add('cargando');
  try {
    var d = await pedir('/api/metricas?dias=' + _tablero.dias);
    if (pedido !== _tablero.pedido) return;
    _tablero.datos = d;
    estado.textContent = '';
    $('tablero-sub').textContent = 'Del ' + _diaLargo(d.dias[0]) + ' al ' + _diaLargo(d.dias[d.dias.length - 1]) + ' · hora de Argentina.';
    // Datos nuevos: las barras crecen y los números cuentan. Al repintar por
    // un cambio de tamaño de la ventana, no se vuelve a animar.
    grilla.classList.remove('cargando');
    grilla.classList.add('animar');
    _pintarTablero();
    grilla.querySelectorAll('.indicador-valor, .tablero-cifra b, .cifra-grande strong').forEach(function(el) { contarHasta(el, 900); });
    clearTimeout(_tablero.reloj);
    _tablero.reloj = setTimeout(function() { grilla.classList.remove('animar'); }, 1400);
  } catch (e) {
    grilla.classList.remove('cargando');
    if (pedido === _tablero.pedido) estado.textContent = 'No se pudieron cargar las métricas: ' + e.message;
  }
}

function initTablero() {
  var periodo = $('tablero-periodo');
  if (!periodo) return;
  periodo.addEventListener('click', function(ev) {
    var b = ev.target.closest('button[data-dias]');
    if (!b) return;
    _tablero.dias = +b.dataset.dias;
    periodo.querySelectorAll('button').forEach(function(o) { o.setAttribute('aria-checked', o === b); });
    cargarTablero();
  });
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'inicio') cargarTablero(); });
  // Pasar a Desarrollador estando en Inicio también lo carga.
  new MutationObserver(function() {
    if (_seccion === 'inicio') cargarTablero();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-modo'] });
  // Los gráficos se arman al ancho real: se repintan si cambia.
  var reloj = null;
  window.addEventListener('resize', function() { clearTimeout(reloj); reloj = setTimeout(_pintarTablero, 150); });
  if (_seccion === 'inicio') cargarTablero();
}

initTablero();
