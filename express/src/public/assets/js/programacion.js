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
    extra: function() { return { persona: $('persona-generacion').value }; },
    cargarExtra: function(d) { if (d.persona) $('persona-generacion').value = d.persona; },
    extraIds: ['persona-generacion']
  }
};
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
}

function marcarProgramacion() { if (FORMULARIOS.programacion) FORMULARIOS.programacion.marcar(); }

/* forzar: pisar los campos aunque haya cambios sin guardar (carga inicial). */
async function cargarAgenda(tipo, forzar) {
  try {
    var r = await fetch(AGENDA[tipo].endpoint);
    var d = await r.json();
    if (!d.success) return;
    if (d.zona) _zona = d.zona;
    var form = FORMULARIOS.programacion;
    var pisar = forzar || !form || !form.sucio();
    if (pisar) {
      aplicarAgenda(tipo, {
        hora: d.hora || (tipo === 'scraping' ? '05:30' : '11:00'),
        interval_days: d.interval_days || 1,
        enabled: d.enabled !== false,
        max_articulos: d.max_articulos,
        persona: d.persona
      });
      if (!forzar && form) form.tomarBase();
    }
    $('next-' + tipo).textContent = d.enabled === false ? 'Pausado' : formatearProxima(d.next_execution);
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
}
