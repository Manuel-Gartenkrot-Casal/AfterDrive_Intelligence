/* recorrido.js — Revisión de una nota en tres pasos: Revisar → Calificar → Publicar.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Cada paso es un panel del lateral del modal. Revisar resume lo que la IA
   chequeó al generarla: arriba lo que necesita atención (con un titular de una
   línea y el detalle a pedido), después lo que está bien y al final cómo se
   generó. Calificar junta la calificación de la IA y la de una persona.
   Publicar muestra la imagen, el destino en HubSpot y los otros idiomas.
   La acción principal del pie cambia según el paso (ver pintarAccionesNota). */

var PASOS = [
  { id: 'revisar', nombre: 'Revisar' },
  { id: 'calificar', nombre: 'Calificar' },
  { id: 'publicar', nombre: 'Publicar' }
];
var _recorrido = { activo: false, paso: 'publicar', nota: null };

/* ── Armado ─────────────────────────────────────────────────────────────── */

function armarRecorrido(nota, cont) {
  _recorrido = { activo: true, paso: pasoInicial(nota), nota: nota };
  $('modal-caja').classList.remove('sin-panel');
  cont.classList.add('recorrido');
  cont.innerHTML = '<div class="pasos" role="tablist" aria-label="Pasos de la revisión">'
    + PASOS.map(function(p, i) {
        return '<button type="button" role="tab" class="paso" id="tab-' + p.id + '" data-paso="' + p.id + '" aria-controls="paso-' + p.id + '"'
          + ' onclick="irAPaso(\'' + p.id + '\')"><span class="paso-num" aria-hidden="true">' + (i + 1) + '</span>'
          + '<span class="paso-nombre">' + p.nombre + '</span><span class="paso-estado"></span></button>';
      }).join('') + '</div>'
    + PASOS.map(function(p) {
        return '<section class="paso-panel" role="tabpanel" id="paso-' + p.id + '" aria-labelledby="tab-' + p.id + '" tabindex="-1" hidden></section>';
      }).join('');
  pintarPasoRevisar(nota, $('paso-revisar'));
  pintarPasoCalificar(nota, $('paso-calificar'));
  pintarPasoPublicar(nota, $('paso-publicar'));
  irAPaso(_recorrido.paso, { sinFoco: true, sinVista: true });
}

// Sin recorrido (noticias, otras colecciones): el modal es una sola columna.
function sinRecorrido() {
  _recorrido = { activo: false, paso: 'publicar', nota: null };
  $('modal-caja').classList.add('sin-panel');
  $('check-list').classList.remove('recorrido');
  $('check-list').innerHTML = '';
}

// Abre en el primer paso con algo pendiente.
function pasoInicial(nota) {
  var e = nota.estado || 'borrador';
  if (e === 'borrador' || e === 'rechazada') return 'revisar';
  return nota.calificacion ? 'publicar' : 'calificar';
}

function irAPaso(id, opts) {
  opts = opts || {};
  _recorrido.paso = id;
  PASOS.forEach(function(p) {
    var tab = $('tab-' + p.id), panel = $('paso-' + p.id);
    if (!tab) return;
    tab.setAttribute('aria-selected', p.id === id);
    tab.tabIndex = p.id === id ? 0 : -1;
    panel.hidden = p.id !== id;
  });
  actualizarPasos();
  if (!opts.sinVista) verPanelModal('revision');
  pintarAccionesNota();
  var panel = $('paso-' + id);
  if (panel) { panel.scrollTop = 0; if (!opts.sinFoco) panel.focus({ preventScroll: true }); }
}

// Flechas entre las pestañas de los pasos, como en cualquier tablist.
document.addEventListener('keydown', function(ev) {
  var tab = ev.target.closest && ev.target.closest('.paso');
  if (!tab || (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft')) return;
  var i = PASOS.findIndex(function(p) { return p.id === tab.dataset.paso; });
  var sig = PASOS[(i + (ev.key === 'ArrowRight' ? 1 : PASOS.length - 1)) % PASOS.length];
  irAPaso(sig.id, { sinFoco: true });
  $('tab-' + sig.id).focus();
  ev.preventDefault();
});

// Debajo de cada paso, en una palabra, cómo está. Hecho = ya no hace falta volver.
function actualizarPasos() {
  if (!_recorrido.activo || !$('tab-revisar')) return;
  var nota = _recorrido.nota, n = _notaActual || {}, e = n.estado || nota.estado || 'borrador';
  var avisos = chequeosDeNota(nota).filter(function(c) { return c.c !== 'ok'; }).length;
  var critica = nota.critica && !nota.critica.error ? nota.critica : null;
  var hs = n.hubspot || nota.hubspot;
  var estados = {
    revisar: { texto: avisos ? (avisos === 1 ? '1 aviso' : avisos + ' avisos') : 'Todo bien', nivel: avisos ? 'atencion' : '',
               hecho: e !== 'borrador' && e !== 'rechazada' },
    calificar: { texto: nota.calificacion ? 'Calificada' : critica ? 'IA: ' + critica.puntaje + '/10' : 'Sin calificar',
                 hecho: !!nota.calificacion },
    publicar: { texto: e === 'publicado' ? 'Publicada' : hs && hs.id ? 'Borrador en HubSpot' : e === 'aprobada' ? 'Aprobada' : 'HubSpot',
                hecho: e === 'publicado' || !!(hs && hs.id) }
  };
  PASOS.forEach(function(p, i) {
    var tab = $('tab-' + p.id), est = estados[p.id];
    tab.classList.toggle('hecho', est.hecho);
    tab.classList.toggle('atencion', !!est.nivel);
    tab.querySelector('.paso-num').textContent = est.hecho ? '✓' : String(i + 1);
    tab.querySelector('.paso-estado').textContent = est.texto;
  });
}

// Celular: se ve la nota o la revisión, no las dos.
function verPanelModal(vista) {
  var modal = $('modal-caja');
  modal.dataset.vista = vista;
  modal.querySelectorAll('.modal-vista [data-vista]').forEach(function(b) {
    b.setAttribute('aria-pressed', b.dataset.vista === vista);
  });
  if (_recorrido.activo && _notaActual) pintarAccionesNota();   // en el celular, la acción principal depende de lo que se ve
}

function enCelular() { return window.matchMedia('(max-width: 900px)').matches; }

/* ── Paso 1: Revisar ────────────────────────────────────────────────────── */

/* Lo que se chequeó, como filas: c = ok | warn | err, un titular, una línea,
   el detalle (HTML) y, si hay, una acción. luz = el texto corto del semáforo. */
function chequeosDeNota(nota) {
  var out = [];
  var v = nota.verificacion;
  if (v && v.total !== undefined) {
    var ok = (v.respaldados || []).length, sin = v.sin_respaldo || [], dud = v.dudosos || [];
    var det = (sin.length ? '<p class="revision-sub">Sin respaldo: revisalos antes de publicar.</p>' + lista(sin, 'mal') : '')
      + (dud.length ? '<p class="revision-sub">No se pudieron confirmar:</p>' + lista(dud, 'dudoso') : '');
    out.push(!v.total
      ? { c: 'ok', id: 'datos', titulo: 'Datos', linea: 'La nota no tiene cifras ni nombres para verificar.', luz: 'Datos' }
      : { c: sin.length ? 'err' : dud.length ? 'warn' : 'ok', id: 'datos',
          titulo: sin.length ? 'Datos sin respaldo' : 'Datos contra las noticias',
          linea: ok + ' de ' + v.total + ' datos aparecen en las noticias.', detalle: det, luz: 'Datos ' + ok + '/' + v.total });
  }
  if (nota.parecida_a) {
    out.push({ c: 'err', id: 'parecida', titulo: 'Parecida a una nota reciente', luz: 'Repetida',
               linea: 'Se parece a “' + nota.parecida_a.titulo + '” (' + Math.round(nota.parecida_a.similitud * 100) + '%).' });
  }
  var estilo = nota.estilo || [];
  if (nota.seo || estilo.length) {
    var s = nota.seo || {}, filas = [];
    if (s.palabra_clave) filas.push(['Palabra clave', s.palabra_clave]);
    if (s.titulo_caracteres !== undefined) filas.push(['Título', s.titulo_caracteres + ' de 60 caracteres']);
    if (s.meta_caracteres !== undefined) filas.push(['Meta description', s.meta_caracteres + ' de 155 caracteres']);
    if (s.preguntas_frecuentes !== undefined) filas.push(['Preguntas frecuentes', String(s.preguntas_frecuentes)]);
    if (s.enlaces_internos !== undefined) filas.push(['Enlaces a otras notas del blog', String(s.enlaces_internos)]);
    var grave = estilo.some(function(h) { return h.grave; });
    out.push({ c: grave ? 'err' : estilo.length ? 'warn' : 'ok', id: 'estilo', titulo: 'Estilo y SEO',
               luz: estilo.length ? (estilo.length === 1 ? 'Estilo: 1 aviso' : 'Estilo: ' + estilo.length + ' avisos') : 'Estilo y SEO',
               linea: estilo.length ? estilo[0].detalle + (estilo.length > 1 ? ' (y ' + (estilo.length - 1) + ' más)' : '') : 'Sin problemas de estilo detectados.',
               detalle: (estilo.length > 1 ? lista(estilo.map(function(h) { return h.detalle; }), 'dudoso') : '') + tablaRevision(filas),
               accion: estilo.length ? { texto: 'Editar', onclick: 'editarNota()' } : null });
  }
  var cal = nota.calidad;
  if (cal && cal.puntaje !== null && cal.puntaje !== undefined) {
    var fallas = cal.fallas_criticas || [], reesc = cal.reescrita_por || [];
    var nombres = function(a) { return a.join(', ').replace(/_/g, ' '); };
    out.push({ c: fallas.length ? 'err' : 'ok', id: 'lineamientos', titulo: 'Lineamientos', luz: 'Lineamientos ' + cal.puntaje + '/9',
               linea: fallas.length ? 'Sigue fallando en ' + nombres(fallas) + '.' : 'Cumple ' + cal.puntaje + ' de 9 lineamientos.',
               detalle: reesc.length ? '<p>' + (cal.segundo_intento === 'correccion' ? 'Se corrigió' : 'Se reescribió') + ' porque falló en: '
                                       + escHtml(nombres(reesc)) + '.</p>' : '' });
  }
  var im = nota.imagen || {}, eleccion = nota.imagen_eleccion || {};
  out.push(im.url
    ? { c: 'ok', id: 'imagen', titulo: 'Imagen destacada', linea: 'Tiene imagen destacada.', luz: 'Con imagen' }
    : { c: 'err', id: 'imagen', titulo: 'Falta la imagen destacada', luz: 'Sin imagen',
        linea: eleccion.metodo === 'ia' ? resumenMotivoImagen(eleccion.motivo) : 'Ninguna noticia de la nota tenía foto.',
        detalle: eleccion.metodo === 'ia' && eleccion.motivo ? detalleMotivoImagen(eleccion.motivo) : '',
        accion: { texto: 'Elegir imagen', onclick: 'vistaPreviaNota()' } });
  var hs = nota.hubspot_traducciones || {};
  var fallidas = Object.keys(hs).filter(function(c) { return hs[c] && hs[c].error; });
  if (fallidas.length) {
    out.push({ c: 'warn', id: 'idiomas', titulo: 'Otros idiomas', luz: 'Idiomas con error',
               linea: 'No se pudo subir la versión en ' + fallidas.map(function(c) { return (NOMBRE_IDIOMA[c] || c).toLowerCase(); }).join(' y ') + '.',
               accion: { texto: 'Ver', onclick: "irAPaso('publicar')" } });
  }
  return out;
}

/* "La IA descartó todas las fotos. m1; m2; …" → cuántas no se pudieron
   descargar y cuántas no servían, en una línea; el detalle agrupa los motivos. */
function _motivosImagen(motivo) {
  var resto = String(motivo || '').replace(/^La IA descartó todas las fotos\.\s*/, '');
  var extra = '';
  var corte = resto.indexOf(' Tampoco sirvió');
  if (corte >= 0) { extra = resto.slice(corte + 1); resto = resto.slice(0, corte); }
  var partes = resto.split(/;\s*/).map(function(m) { return m.trim().replace(/\.$/, ''); }).filter(Boolean);
  return { partes: partes, extra: extra };
}

function resumenMotivoImagen(motivo) {
  var m = _motivosImagen(motivo);
  if (!m.partes.length) return 'La IA descartó las fotos de las noticias.';
  var bajadas = m.partes.filter(function(x) { return /^No se pudo descargar/.test(x); }).length;
  var otras = m.partes.length - bajadas, frases = [];
  if (bajadas) frases.push(bajadas === 1 ? '1 foto no se pudo descargar' : bajadas + ' fotos no se pudieron descargar');
  if (otras) frases.push(otras === 1 ? '1 no servía para la nota' : otras + ' no servían para la nota');
  return 'La IA descartó las fotos: ' + frases.join(' y ') + '.';
}

function detalleMotivoImagen(motivo) {
  var m = _motivosImagen(motivo), cuenta = {};
  m.partes.forEach(function(x) { cuenta[x] = (cuenta[x] || 0) + 1; });
  var filas = Object.keys(cuenta).map(function(x) { return [cuenta[x] === 1 ? '1 foto' : cuenta[x] + ' fotos', x]; });
  return tablaRevision(filas) + (m.extra ? '<p class="revision-sub">' + escHtml(m.extra) + '</p>' : '');
}

function tablaRevision(filas) {
  if (!filas.length) return '';
  return '<table class="tabla-revision"><tbody>' + filas.map(function(f) {
    return '<tr><th scope="row">' + escHtml(f[0]) + '</th><td>' + escHtml(f[1]) + '</td></tr>';
  }).join('') + '</tbody></table>';
}

var _detalles = 0;
function filaChequeo(ch) {
  var id = 'chequeo-det-' + (++_detalles);
  var li = document.createElement('li');
  li.className = 'chequeo';
  li.dataset.c = ch.c;
  li.id = 'chequeo-' + ch.id;
  li.innerHTML = '<span class="chequeo-icono" aria-hidden="true">' + (ch.c === 'ok' ? '✓' : ch.c === 'warn' ? '!' : '✕') + '</span>'
    + '<div class="chequeo-texto"><strong>' + escHtml(ch.titulo) + '</strong><span>' + escHtml(ch.linea) + '</span>'
    + (ch.detalle ? '<button type="button" class="enlace-detalle" aria-expanded="false" aria-controls="' + id + '">Ver detalle</button>' : '')
    + '</div>'
    + (ch.accion ? '<button type="button" class="btn btn-xs chequeo-accion" onclick="' + ch.accion.onclick + '">' + escHtml(ch.accion.texto) + '</button>' : '')
    + (ch.detalle ? '<div class="chequeo-detalle" id="' + id + '" hidden>' + ch.detalle + '</div>' : '');
  var boton = li.querySelector('.enlace-detalle');
  if (boton) boton.onclick = function() {
    var d = $(id), abrir = d.hidden;
    d.hidden = !abrir;
    boton.setAttribute('aria-expanded', abrir);
    boton.textContent = tr(abrir ? 'Ocultar detalle' : 'Ver detalle');
  };
  return li;
}

function pintarPasoRevisar(nota, panel) {
  var chequeos = chequeosDeNota(nota);
  var atencion = chequeos.filter(function(c) { return c.c !== 'ok'; })
    .sort(function(a, b) { return (a.c === 'err' ? 0 : 1) - (b.c === 'err' ? 0 : 1); });
  var bien = chequeos.filter(function(c) { return c.c === 'ok'; });
  panel.innerHTML = '<h3 class="paso-titulo">¿Está lista para publicar?</h3>'
    + '<p class="paso-ayuda">La IA la revisó al generarla. Primero aparece lo que necesita tu atención.</p>'
    + '<div class="semaforo">' + atencion.concat(bien).map(function(c) {
        return '<button type="button" class="luz" data-c="' + c.c + '" onclick="irAChequeo(\'' + c.id + '\')">' + escHtml(c.luz) + '</button>';
      }).join('') + '</div>'
    + (atencion.length ? '<p class="grupo-titulo">Necesita atención</p><ul class="chequeos" id="chequeos-atencion"></ul>'
                       : '<p class="revision-ok todo-listo">No hay nada que corregir: podés seguir a calificarla.</p>')
    + (bien.length ? '<p class="grupo-titulo">Todo bien</p><ul class="chequeos chequeos-ok" id="chequeos-ok"></ul>' : '')
    + '<p class="grupo-titulo">Cómo se generó</p>'
    + '<details class="como-se-genero"><summary><span>Plan, noticias y costo<small>' + escHtml(resumenGeneracion(nota)) + '</small></span></summary>'
    + '<div class="como-se-genero-cuerpo" id="recorrido-generacion"></div></details>';
  atencion.forEach(function(c) { $('chequeos-atencion').appendChild(filaChequeo(c)); });
  bien.forEach(function(c) { $('chequeos-ok').appendChild(filaChequeo(c)); });
  pintarGeneracion(nota, $('recorrido-generacion'));
}

function irAChequeo(id) {
  var fila = $('chequeo-' + id);
  if (!fila) return;
  fila.scrollIntoView({ block: 'center', behavior: 'smooth' });
  fila.classList.remove('destacado'); void fila.offsetWidth;
  fila.classList.add('destacado');
}

function resumenGeneracion(nota) {
  var partes = [];
  if ((nota.fuentes || []).length) partes.push(nota.fuentes.length === 1 ? '1 noticia' : nota.fuentes.length + ' noticias');
  if ((nota.categorias || []).length) partes.push(nota.categorias.join(', '));
  if (nota.costo) partes.push(nota.costo.llamadas ? 'USD ' + nota.costo.total_usd.toLocaleString(localeUI(), { maximumFractionDigits: 2 }) : 'sin costo');
  return partes.join(' · ');
}

// Lo que antes se apilaba en el lateral: plan, categorías, noticias, citas, costo y criterios.
function pintarGeneracion(nota, cont) {
  if (nota.plan) {
    var p = nota.plan;
    cont.appendChild(bloqueRevision('Plan de la nota', (p.angulo ? '<p class="revision-sub">Ángulo: ' + escHtml(p.angulo) + '</p>' : '')
      + '<ol class="revision-lista">' + (p.secciones || []).map(function(x) {
          return '<li><span translate="no">' + escHtml(x.titulo) + '</span>' + (x.noticias.length ? ' <small>(noticias ' + x.noticias.join(', ') + ')</small>' : '') + '</li>';
        }).join('') + '</ol>'));
  }
  if ((nota.categorias || []).length) {
    cont.appendChild(bloqueRevision('Categorías', '<p>' + escHtml(nota.categorias.join(', ')) + '</p>'
      + (nota.puntapie_url ? '<p class="revision-sub">Puntapié: ' + escHtml(nota.puntapie_url) + '</p>' : '')));
  }
  if ((nota.fuentes || []).length) {
    cont.appendChild(bloqueRevision('Noticias usadas', '<ul class="revision-lista noticias-usadas">' + nota.fuentes.map(function(f) {
      return '<li><a href="' + urlSegura(f.url) + '" target="_blank" rel="noopener" translate="no">' + escHtml(f.titulo) + '</a></li>';
    }).join('') + '</ul>'));
  }
  pintarCitasBlog(nota, cont);
  pintarCosto(nota, cont);
  var ev = document.createElement('div');
  ev.id = 'recorrido-evaluacion';
  cont.appendChild(ev);
}

/* ── Paso 2: Calificar ──────────────────────────────────────────────────── */

function pintarPasoCalificar(nota, panel) {
  panel.innerHTML = '<h3 class="paso-titulo">¿Qué tan buena es?</h3>'
    + '<p class="paso-ayuda">La IA ya la calificó. Tu calificación es la que enseña a la generación qué funciona.</p>';
  pintarCriticaIA(nota, panel);
  pintarCalificacion(nota, panel);
}

/* ── Paso 3: Publicar ───────────────────────────────────────────────────── */

function pintarPasoPublicar(nota, panel) {
  panel.innerHTML = '<h3 class="paso-titulo">¿Cómo sale publicada?</h3>'
    + '<p class="paso-ayuda">Revisá lo que va a HubSpot: la imagen, quién firma y los otros idiomas.</p>';
  pintarImagen(nota, panel);
  pintarDestinoHubspot(nota, panel);
  pintarTraducciones(nota, panel);
}

/* ── Menú "Más" del pie ─────────────────────────────────────────────────── */

function alternarMenuNota(abrir) {
  var menu = $('nota-menu'), btn = $('nota-mas');
  if (!menu) return;
  if (abrir === undefined) abrir = menu.hidden;
  menu.hidden = !abrir;
  btn.setAttribute('aria-expanded', abrir);
  if (abrir) { var primero = menu.querySelector('[role="menuitem"]'); if (primero) primero.focus(); }
}

document.addEventListener('click', function(ev) {
  var menu = $('nota-menu');
  if (!menu || menu.hidden) return;
  if (ev.target.closest('#nota-menu') && !ev.target.closest('[role="menuitem"]')) return;
  if (ev.target.closest('#nota-mas')) return;
  alternarMenuNota(false);
});
