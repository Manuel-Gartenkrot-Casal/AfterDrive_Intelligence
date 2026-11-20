/* programacion.js — Reloj y programación automática.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   RELOJ ANALÓGICO INTERACTIVO
   Arrastrar la aguja corta mueve la hora; la larga, los minutos (de a 5).
   Con teclado: flechas = ±5 min, Shift + flechas = ±1 h.
   ═══════════════════════════════════════════════════════════════════════ */
function crearReloj(host, onInput, onCommit) {
  var NS = 'http://www.w3.org/2000/svg';
  var C = 100;
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function polar(r, deg) {
    var rad = (deg - 90) * Math.PI / 180;
    return [C + r * Math.cos(rad), C + r * Math.sin(rad)];
  }

  var cara = document.createElement('div');
  cara.className = 'reloj-cara';
  var svg = el('svg', { viewBox: '0 0 200 200', role: 'slider', tabindex: '0',
                        'aria-valuemin': '0', 'aria-valuemax': '1439' });
  for (var i = 0; i < 60; i++) {
    var hora = i % 5 === 0;
    var a = polar(88, i * 6), b = polar(hora ? 78 : 83, i * 6);
    el('line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: hora ? 'tick tick-hora' : 'tick' }, svg);
  }
  for (var h = 1; h <= 12; h++) {
    var pnum = polar(66, h * 30);
    var t = el('text', { x: pnum[0], y: pnum[1] + 4, 'text-anchor': 'middle',
                         class: h % 3 === 0 ? 'num num-cardinal' : 'num' }, svg);
    t.textContent = h;
  }
  var momento = el('text', { x: C, y: 136, 'text-anchor': 'middle', class: 'momento' }, svg);
  var gH = el('g', { class: 'aguja aguja-hora' }, svg);
  el('line', { x1: C, y1: C, x2: C, y2: 56 }, gH);
  el('circle', { cx: C, cy: 56, r: 7, class: 'perilla', 'data-aguja': 'h' }, gH);
  var gM = el('g', { class: 'aguja aguja-min' }, svg);
  el('line', { x1: C, y1: C, x2: C, y2: 30 }, gM);
  el('circle', { cx: C, cy: 30, r: 6, class: 'perilla', 'data-aguja': 'm' }, gM);
  el('circle', { cx: C, cy: C, r: 6, class: 'centro' }, svg);
  cara.appendChild(svg);
  host.appendChild(cara);

  var estado = { h: 0, m: 0 };
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function texto() { return pad(estado.h) + ':' + pad(estado.m); }
  function nombreMomento(h) {
    return h < 6 ? 'madrugada' : h < 12 ? 'mañana' : h < 20 ? 'tarde' : 'noche';
  }
  function pintar() {
    gH.style.transform = 'rotate(' + ((estado.h % 12) * 30 + estado.m * 0.5) + 'deg)';
    gM.style.transform = 'rotate(' + (estado.m * 6) + 'deg)';
    momento.textContent = nombreMomento(estado.h);
    // Va arriba o abajo del centro, donde no la tape ninguna aguja.
    var angH = ((estado.h % 12) * 30 + estado.m * 0.5) % 360, angM = estado.m * 6;
    function cerca(ang, centro) { var d = Math.abs(ang - centro) % 360; return Math.min(d, 360 - d) < 55; }
    var abajoOcupado = cerca(angH, 180) || cerca(angM, 180);
    var arribaOcupado = cerca(angH, 0) || cerca(angM, 0);
    momento.setAttribute('y', abajoOcupado && !arribaOcupado ? 72 : 136);
    svg.setAttribute('aria-valuenow', estado.h * 60 + estado.m);
    svg.setAttribute('aria-valuetext', texto() + ' (' + nombreMomento(estado.h) + ')');
  }
  function fijar(h, m, emitir) {
    var total = ((h * 60 + m) % 1440 + 1440) % 1440;
    estado.h = Math.floor(total / 60);
    estado.m = total % 60;
    pintar();
    if (emitir) onInput(texto());
  }

  function angulo(ev) {
    var r = svg.getBoundingClientRect();
    var x = (ev.clientX - r.left) / r.width * 200 - C;
    var y = (ev.clientY - r.top) / r.height * 200 - C;
    return { deg: (Math.atan2(y, x) * 180 / Math.PI + 90 + 360) % 360, dist: Math.sqrt(x * x + y * y) };
  }
  var aguja = null;
  function mover(ev) {
    var a = angulo(ev);
    if (aguja === 'm') {
      var m = Math.round(a.deg / 30) * 5 % 60;
      var h = estado.h;
      if (estado.m >= 45 && m <= 15) h++;          // pasó las 12 hacia adelante
      else if (estado.m <= 15 && m >= 45) h--;     // y hacia atrás
      fijar(h, m, true);
    } else {
      var h12 = Math.round(a.deg / 30) % 12;
      fijar(h12 + (estado.h >= 12 ? 12 : 0), estado.m, true);
    }
  }
  svg.addEventListener('pointerdown', function(ev) {
    var marcada = ev.target.getAttribute && ev.target.getAttribute('data-aguja');
    aguja = marcada || (angulo(ev).dist < 52 ? 'h' : 'm');
    host.classList.add('arrastrando');
    svg.setPointerCapture(ev.pointerId);
    mover(ev);
    ev.preventDefault();
  });
  svg.addEventListener('pointermove', function(ev) { if (aguja) mover(ev); });
  function soltar() {
    if (!aguja) return;
    aguja = null;
    host.classList.remove('arrastrando');
    onCommit(texto());
  }
  svg.addEventListener('pointerup', soltar);
  svg.addEventListener('pointercancel', soltar);
  svg.addEventListener('keydown', function(ev) {
    var paso = ev.shiftKey ? 60 : 5;
    var delta = { ArrowUp: paso, ArrowRight: paso, ArrowDown: -paso, ArrowLeft: -paso }[ev.key];
    if (!delta) return;
    ev.preventDefault();
    fijar(estado.h, estado.m + delta, true);
    onCommit(texto());
  });

  return {
    set: function(hhmm) {
      var partes = (hhmm || '00:00').split(':');
      fijar(+partes[0], +partes[1], false);
    },
    get: texto
  };
}

/* ═══════════════════════════════════════════════════════════════════════
   PROGRAMACIÓN AUTOMÁTICA
   Cada tarjeta = reloj + input de hora + AM/PM + campos. Todo se guarda
   solo (con un pequeño retardo para no mandar un POST por cada paso).
   ═══════════════════════════════════════════════════════════════════════ */
var AGENDA = {
  scraping: {
    endpoint: '/api/scraping-config',
    extra: function() { return { max_articulos: parseInt($('max-scraping').value, 10) || 10 }; },
    cargarExtra: function(d) { if (d.max_articulos) $('max-scraping').value = d.max_articulos; },
    extraIds: ['max-scraping']
  },
  generacion: {
    endpoint: '/api/generacion-config',
    extra: function() { return { persona: $('persona-generacion').value, horas_extra: leerHorasExtra() }; },
    cargarExtra: function(d) {
      if (d.persona) $('persona-generacion').value = d.persona;
      pintarHorasExtra(d.horas_extra || []);
    },
    extraIds: ['persona-generacion'],
    presupuesto: null   // {costo_nota_usd, tope_usd} de /api/generacion-config
  }
};

/* ── Más notas por día: horas extra de la generación ──────────────────── */
var HORAS_EXTRA_MAX = 7;   // config_store.HORAS_EXTRA_MAX

function leerHorasExtra() {
  var vistas = {}, principal = $('hora-generacion').value;
  return Array.from(document.querySelectorAll('#horas-extra-generacion input')).map(function(i) { return i.value; })
    .filter(function(h) { if (!h || h === principal || vistas[h]) return false; vistas[h] = true; return true; })
    .sort();
}

function pintarHorasExtra(horas) {
  var cont = $('horas-extra-generacion');
  cont.innerHTML = '';
  horas.forEach(function(h) { _filaHoraExtra(cont, h); });
  _estadoBotonHoraExtra();
}

function _filaHoraExtra(cont, hhmm) {
  var fila = document.createElement('span');
  fila.className = 'hora-extra';
  fila.innerHTML = '<input type="time" step="300" required>' +
    '<button type="button" class="icon-btn" title="Quitar este horario">✕</button>';
  var input = fila.querySelector('input'), quitar = fila.querySelector('button');
  input.value = hhmm;
  var nombrar = function() {
    input.setAttribute('aria-label', 'Horario extra ' + (input.value || ''));
    quitar.setAttribute('aria-label', 'Quitar el horario de las ' + (input.value || ''));
  };
  nombrar();
  input.addEventListener('input', function() { nombrar(); marcarProgramacion(); });
  quitar.addEventListener('click', function() { fila.remove(); _estadoBotonHoraExtra(); marcarProgramacion(); });
  cont.appendChild(fila);
  return input;
}

function _estadoBotonHoraExtra() {
  var n = document.querySelectorAll('#horas-extra-generacion .hora-extra').length;
  $('btn-hora-extra').disabled = n >= HORAS_EXTRA_MAX;
  $('btn-hora-extra').title = n >= HORAS_EXTRA_MAX ? 'Como máximo ' + (HORAS_EXTRA_MAX + 1) + ' notas por día' : '';
}

/* Suma un horario 3 h después del último (sin repetir ninguno). */
function agregarHoraExtra() {
  var usadas = [$('hora-generacion').value].concat(leerHorasExtra()).map(_minutos).filter(function(m) { return m !== null && !isNaN(m); });
  var desde = usadas.length ? Math.max.apply(null, usadas) : 660, min = desde;
  for (var i = 0; i < 48; i++) {
    min = (min + 180 + (i ? 30 : 0)) % 1440;
    if (usadas.indexOf(min) < 0) break;
  }
  var hhmm = (min < 600 ? '0' : '') + Math.floor(min / 60) + ':' + (min % 60 < 10 ? '0' : '') + (min % 60);
  _filaHoraExtra($('horas-extra-generacion'), hhmm).focus();
  _estadoBotonHoraExtra();
  marcarProgramacion();
}

/* Cuántas notas entran en el presupuesto de la API paga con los horarios elegidos. */
function pintarPresupuesto() {
  var el = $('presupuesto-generacion'), p = AGENDA.generacion.presupuesto;
  if (!el) return;
  var porDia = 1 + leerHorasExtra().length;
  var dias = Math.max(1, parseInt($('dias-generacion').value, 10) || 1);
  if (!p || !p.costo_nota_usd || !p.tope_usd) {
    el.hidden = porDia === 1;
    el.classList.remove('aviso');
    el.textContent = porDia > 1 ? 'Se escriben ' + porDia + ' notas automáticas por día.' : '';
    return;
  }
  var usd = function(v) { return 'USD ' + v.toLocaleString(localeUI(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
  var notasMes = porDia * 30 / dias, mes = notasMes * p.costo_nota_usd;
  var entran = Math.floor(p.tope_usd / (p.costo_nota_usd * 30 / dias));
  el.hidden = false;
  el.classList.toggle('aviso', mes > p.tope_usd);
  el.textContent = 'Cada nota usa unos ' + usd(p.costo_nota_usd) + ' de la API paga: con ' + porDia +
    (porDia === 1 ? ' nota' : ' notas') + (dias === 1 ? ' por día' : ' cada ' + dias + ' días') + ' son unos ' + usd(mes) +
    ' por mes, de un tope de ' + usd(p.tope_usd) + '. ' +
    (mes > p.tope_usd ? 'Se pasa del tope: al llegar, el resto del mes se escribe con el proveedor gratuito.'
                      : 'Entran hasta ' + entran + (entran === 1 ? ' nota' : ' notas') + (dias === 1 ? ' por día.' : ' por tanda.'));
}
var _zona = 'America/Argentina/Buenos_Aires';

function formatearProxima(iso) {
  if (!iso) return 'Pausado';
  return new Date(iso).toLocaleString(localeUI(), {
    weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: _zona
  });
}

function proximaCorta(iso) {
  if (!iso) return '-';
  var f = new Date(iso);
  var dia = function(x) { return x.toLocaleDateString('en-CA', { timeZone: _zona }); };
  var hoy = new Date(), manana = new Date(Date.now() + 864e5);
  var hora = f.toLocaleTimeString(localeUI(), { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: _zona });
  if (dia(f) === dia(hoy)) return 'Hoy ' + hora;
  if (dia(f) === dia(manana)) return 'Mañana ' + hora;
  return f.toLocaleDateString(localeUI(), { weekday: 'short', day: 'numeric', timeZone: _zona }) + ' ' + hora;
}

function pintarAmPm(tipo, hhmm) {
  var pm = parseInt(hhmm.split(':')[0], 10) >= 12;
  $('ampm-' + tipo).querySelectorAll('button').forEach(function(b) {
    var on = (b.dataset.p === 'pm') === pm;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on);
  });
}

function pintarActivo(tipo, activo) {
  var sw = $('sw-' + tipo);
  sw.classList.toggle('active', activo);
  sw.setAttribute('aria-checked', activo);
  sw.querySelector('span').textContent = activo ? 'Activo' : 'Pausado';
  $('agenda-' + tipo).classList.toggle('pausada', !activo);
}

function leerAgenda(tipo) {
  return Object.assign({
    hora: $('hora-' + tipo).value,
    interval_days: Math.max(1, parseInt($('dias-' + tipo).value, 10) || 1),
    enabled: $('sw-' + tipo).classList.contains('active')
  }, AGENDA[tipo].extra());
}

function aplicarAgenda(tipo, c) {
  $('hora-' + tipo).value = c.hora;
  AGENDA[tipo].reloj.set(c.hora);
  pintarAmPm(tipo, c.hora);
  $('dias-' + tipo).value = c.interval_days || 1;
  AGENDA[tipo].cargarExtra(c);
  pintarActivo(tipo, c.enabled !== false);
  pintarDia();
  pintarPresupuesto();
}

function marcarProgramacion() { if (FORMULARIOS.programacion) FORMULARIOS.programacion.marcar(); pintarDia(); pintarPresupuesto(); }

/* El día de un vistazo: un eje de 24 h con la hora de cada tarea y la de ahora
   (en la zona del servidor). Sigue lo que se está editando, sin guardar. */
function _minutos(hhmm) {
  var p = String(hhmm || '').split(':');
  return p.length === 2 ? (parseInt(p[0], 10) * 60 + parseInt(p[1], 10)) : null;
}

function pintarDia() {
  var eje = $('agenda-dia-eje');
  if (!eje) return;
  var pos = function(min) { return (min / 1440 * 100).toFixed(3) + '%'; };
  var html = '';
  for (var h = 0; h <= 24; h += 3) {
    html += '<span class="dia-marca" style="left:' + pos(h * 60) + '"><i></i><b>' + (h < 10 ? '0' : '') + h + ':00</b></span>';
  }
  // Cerca de los bordes, la etiqueta se apoya hacia adentro para no salirse.
  var lado = function(min) { return min < 150 ? ' izq' : min > 1290 ? ' der' : ''; };
  var ahora = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: _zona });
  var minAhora = _minutos(ahora);
  html += '<span class="dia-ahora" style="left:' + pos(minAhora) + '"></span>';
  if ($('ley-ahora')) $('ley-ahora').textContent = ahora;
  var marcas = [];
  Object.keys(AGENDA).forEach(function(tipo) {
    var horas = [$('hora-' + tipo).value].concat(tipo === 'generacion' ? leerHorasExtra() : []);
    var activa = $('sw-' + tipo).classList.contains('active');
    var nombre = $('agenda-' + tipo).querySelector('.agenda-card-title').textContent;
    horas.forEach(function(hora) {
      var min = _minutos(hora);
      if (min !== null && !isNaN(min)) marcas.push({ tipo: tipo, hora: hora, min: min, activa: activa, nombre: nombre });
    });
  });
  marcas.sort(function(a, b) { return a.min - b.min; });
  var anterior = null, anteriorAlto = false, dosFilas = false;
  marcas.forEach(function(m) {
    // Dos tareas cerca en pantalla: la segunda sube un renglón para no pisar a la primera.
    var cerca = anterior !== null && Math.abs(m.min - anterior) / 1440 * (eje.clientWidth || 800) < 170;
    var alto = cerca && !anteriorAlto ? ' alto' : '';
    anterior = m.min;
    anteriorAlto = !!alto;
    if (alto) dosFilas = true;
    html += '<span class="dia-tarea' + (m.activa ? '' : ' pausada') + lado(m.min) + alto + '" data-tipo="' + m.tipo + '" style="left:' + pos(m.min) + '">'
      + '<b>' + escHtml(m.nombre) + ' · ' + m.hora + '</b></span>';
  });
  eje.innerHTML = html;
  eje.parentNode.classList.toggle('dos-filas', dosFilas);
  Object.keys(AGENDA).forEach(function(tipo) {
    var ley = $('ley-' + tipo);
    if (ley) ley.textContent = $('agenda-' + tipo).querySelector('.agenda-card-title').textContent;
  });
  pintarResumenDia();
}

function _lapso(min) {
  var h = Math.floor(min / 60), m = min % 60;
  return h && m ? h + ' h ' + m + ' min' : h ? h + ' h' : m + ' min';
}

// En una frase: en qué orden corren las tareas y si eso tiene sentido.
function pintarResumenDia() {
  var el = $('agenda-dia-resumen');
  if (!el) return;
  var hs = $('hora-scraping').value, hg = $('hora-generacion').value;
  var s = _minutos(hs), g = _minutos(hg);
  var activaS = $('sw-scraping').classList.contains('active'), activaG = $('sw-generacion').classList.contains('active');
  var texto, aviso = false;
  if (!activaS && !activaG) texto = 'Las dos tareas están pausadas: no corre nada solo.';
  else if (!activaS) texto = 'La búsqueda de noticias está pausada: la nota se escribe a las ' + hg + ' con las noticias que ya hay.';
  else if (!activaG) texto = 'La nota automática está pausada: solo se buscan noticias a las ' + hs + '.';
  else if (s === null || g === null || isNaN(s) || isNaN(g)) texto = '';
  else if (s < g) texto = 'Primero se buscan noticias a las ' + hs + ' y, ' + _lapso(g - s) + ' después, se escribe la nota a las ' + hg + '.';
  else if (s === g) { texto = 'Las dos tareas están a la misma hora: conviene buscar noticias antes de escribir la nota.'; aviso = true; }
  else { texto = 'La nota se escribe a las ' + hg + ', antes de buscar noticias a las ' + hs + ': va a usar las del día anterior.'; aviso = true; }
  var extra = leerHorasExtra(), masNotas = '';
  if (activaG && extra.length) {
    masNotas = extra.length === 1 ? 'También se escribe otra nota a las ' + extra[0] + '.'
      : 'También se escriben notas a las ' + extra.slice(0, -1).join(', ') + ' y ' + extra[extra.length - 1] + '.';
  }
  // Cada frase en su span: así cada una se traduce entera (textos.js).
  el.innerHTML = '<span>' + escHtml(texto) + '</span>' + (masNotas ? ' <span>' + escHtml(masNotas) + '</span>' : '');
  el.classList.toggle('aviso', aviso);
}

// "en 4 h 12 min" hasta la próxima corrida guardada.
function pintarFalta(tipo) {
  var el = $('falta-' + tipo), iso = AGENDA[tipo].proxima;
  if (!el) return;
  if (!iso) { el.textContent = ''; return; }
  var min = Math.max(0, Math.round((new Date(iso) - Date.now()) / 60000));
  var d = Math.floor(min / 1440), h = Math.floor(min % 1440 / 60), m = min % 60;
  el.textContent = min < 1 ? 'En menos de un minuto'
    : d ? 'En ' + d + (d === 1 ? ' día ' : ' días ') + h + ' h'
    : h ? 'En ' + h + ' h ' + m + ' min' : 'En ' + m + ' min';
}

/* forzar: pisar los campos aunque haya cambios sin guardar (carga inicial). */
async function cargarAgenda(tipo, forzar) {
  try {
    var r = await fetch(AGENDA[tipo].endpoint);
    var d = await r.json();
    if (!d.success) return;
    if (d.zona) _zona = d.zona;
    if (tipo === 'generacion') AGENDA.generacion.presupuesto = { costo_nota_usd: d.costo_nota_usd, tope_usd: d.tope_usd };
    var form = FORMULARIOS.programacion;
    var pisar = forzar || !form || !form.sucio();
    if (pisar) {
      aplicarAgenda(tipo, {
        hora: d.hora || (tipo === 'scraping' ? '05:30' : '11:00'),
        interval_days: d.interval_days || 1,
        enabled: d.enabled !== false,
        max_articulos: d.max_articulos,
        persona: d.persona,
        horas_extra: d.horas_extra || []
      });
      if (!forzar && form) form.tomarBase();
    }
    $('next-' + tipo).textContent = d.enabled === false ? 'Pausado' : formatearProxima(d.next_execution);
    AGENDA[tipo].proxima = d.enabled === false ? null : d.next_execution;
    pintarFalta(tipo);
    if (tipo === 'generacion') $('c-proxima').textContent = d.enabled === false ? 'Pausada' : proximaCorta(d.next_execution);
  } catch(e) {}
}

function initAgenda() {
  Object.keys(AGENDA).forEach(function(tipo) {
    var input = $('hora-' + tipo);
    AGENDA[tipo].reloj = crearReloj($('reloj-' + tipo),
      function(hhmm) { input.value = hhmm; pintarAmPm(tipo, hhmm); marcarProgramacion(); },
      marcarProgramacion);
    $('reloj-' + tipo).querySelector('svg').setAttribute('aria-label', 'Hora de ' + tipo);

    input.addEventListener('input', function() {
      if (!input.value) return;
      AGENDA[tipo].reloj.set(input.value);
      pintarAmPm(tipo, input.value);
      marcarProgramacion();
    });

    $('ampm-' + tipo).addEventListener('click', function(ev) {
      var b = ev.target.closest('button');
      if (!b || !input.value) return;
      var partes = input.value.split(':');
      var h = parseInt(partes[0], 10);
      if (b.dataset.p === 'pm' && h < 12) h += 12;
      if (b.dataset.p === 'am' && h >= 12) h -= 12;
      input.value = (h < 10 ? '0' : '') + h + ':' + partes[1];
      AGENDA[tipo].reloj.set(input.value);
      pintarAmPm(tipo, input.value);
      marcarProgramacion();
    });

    var sw = $('sw-' + tipo);
    function alternar() { pintarActivo(tipo, !sw.classList.contains('active')); marcarProgramacion(); }
    sw.addEventListener('click', alternar);
    sw.addEventListener('keydown', function(ev) {
      if (ev.key === ' ' || ev.key === 'Enter') { ev.preventDefault(); alternar(); }
    });

    ['dias-' + tipo].concat(AGENDA[tipo].extraIds).forEach(function(id) {
      $(id).addEventListener('input', marcarProgramacion);
      $(id).addEventListener('change', marcarProgramacion);
    });
  });

  var form = formulario('programacion', {
    leer: function() { return { scraping: leerAgenda('scraping'), generacion: leerAgenda('generacion') }; },
    aplicar: function(st) { aplicarAgenda('scraping', st.scraping); aplicarAgenda('generacion', st.generacion); },
    guardar: async function(st, base) {
      for (var tipo in AGENDA) {
        if (JSON.stringify(st[tipo]) === JSON.stringify(base[tipo])) continue;
        if (!st[tipo].hora) throw new Error('Falta la hora de ' + (tipo === 'scraping' ? 'scraping' : 'generación') + '.');
        await pedir(AGENDA[tipo].endpoint, {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(st[tipo])
        });
      }
    },
    despues: function() { cargarAgenda('scraping'); cargarAgenda('generacion'); updateStats(); }
  });
  Promise.all([cargarAgenda('scraping', true), cargarAgenda('generacion', true)]).then(form.tomarBase);
  setInterval(function() { pintarDia(); Object.keys(AGENDA).forEach(pintarFalta); }, 60000);
  document.addEventListener('idioma', pintarDia);   // los nombres de las tareas cambian de idioma
  // Se dibuja con el ancho real: al entrar a la sección y si cambia la ventana.
  document.addEventListener('seccion', function(ev) { if (ev.detail === 'programacion') pintarDia(); });
  window.addEventListener('resize', pintarDia);
}
