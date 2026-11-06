/* lectura.js — Revisión de una nota en la vista Cliente: la nota como documento.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Solo en la vista Cliente (la de Desarrollador sigue con el recorrido de
   recorrido.js). La misma ventana de la nota se ordena así:
   - Arriba: "Notas / título", el estado y las acciones (Rechazar, Aprobar y subir).
   - Centro: la nota para leer, con letra serif. Los datos que se verificaron se
     marcan en el texto (verde con respaldo, amarillo dudoso, rojo sin respaldo) y
     debajo del párrafo aparece el aviso. Lo demás que hay que mirar (imagen,
     estilo, empresas que no se nombran…) va arriba; "Cómo se generó", al final.
   - Derecha: un panel con la vista previa (switch Blog / Instagram / LinkedIn) o
     con la calificación. Se cierra con la ✕ y la nota ocupa todo el ancho.
   - Abajo: una barra flotante con Editar, Calificar, Vista previa y Más.
   Todo lo que hace cada botón es lo mismo de siempre (historial.js, revision.js,
   carrusel.js): acá solo cambia cómo se muestra. */

var _lectura = { id: null, panel: 'previa', red: 'blog', pagina: 0, ocultos: {} };

function vistaCliente() { return document.documentElement.getAttribute('data-modo') !== 'dev'; }

/* ── Armado ─────────────────────────────────────────────────────────────── */

function armarLectura(nota, cont) {
  // En el celular la nota abre sola, sin el panel encima.
  if (_lectura.id !== nota._id) _lectura = { id: nota._id, panel: enCelular() ? null : 'previa', red: 'blog', pagina: 0, ocultos: {} };
  _recorrido = { activo: true, paso: 'publicar', nota: nota, lectura: true };
  var modal = $('modal-caja');
  modal.classList.add('lectura');
  modal.classList.remove('sin-panel');
  cont.classList.remove('recorrido');
  cont.classList.add('lectura-panel');
  var cuerpo = $('art-body'), scroll = cuerpo.scrollTop;
  pintarCuerpoNota();   // vuelve a pintar el texto y lo decora (decorarLectura)
  cuerpo.scrollTop = scroll;
  pintarPanelLectura();
}

// Al salir de la lectura (vista Desarrollador, o un ítem que no es nota).
function salirDeLectura() {
  $('modal-caja').classList.remove('lectura', 'panel-cerrado');
  $('check-list').classList.remove('lectura-panel');
  if (_recorrido) _recorrido.lectura = false;
}

function abrirPanelLectura(panel, red) {
  _lectura.panel = panel;
  if (red) _lectura.red = red;
  pintarPanelLectura();
  if (enCelular()) verPanelModal('revision');
}

function cerrarPanelLectura() {
  _lectura.panel = null;
  pintarPanelLectura();
  verPanelModal('nota');
}

// Los pasos del recorrido, llevados a la lectura: Revisar = el texto, Calificar y Publicar = el panel.
function irAPasoLectura(id, opts) {
  if (opts && opts.sinVista) return;   // una actualización: se deja el panel como estaba
  if (id === 'calificar') abrirPanelLectura('calificar');
  else if (id === 'publicar') abrirPanelLectura('previa', 'blog');
  else cerrarPanelLectura();
}

/* ── Acciones: arriba las principales, abajo la barra flotante ──────────── */

function pintarAccionesLectura() {
  var n = _notaActual, e = n.estado, cont = $('nota-acciones'), arriba = $('lectura-acciones');
  var subible = !n.sinDestino, yaEnviada = n.hubspot && n.hubspot.id;
  var boton = function(onclick, texto, clase, extra) {
    return '<button type="button" class="btn btn-xs' + (clase || '') + '" onclick="' + onclick + '"' + (extra || '') + '>' + texto + '</button>';
  };
  var principal = '';
  if (e === 'borrador') principal = subible ? boton('aprobarYSubir()', 'Aprobar y subir', ' btn-primary') : boton("cambiarEstadoNota('aprobada')", 'Aprobar', ' btn-primary');
  else if (e === 'aprobada' && subible) principal = boton('enviarAHubspot(false)', yaEnviada ? 'Actualizar borrador en HubSpot' : 'Subir borrador a HubSpot', ' btn-primary');
  else if (e === 'rechazada') principal = boton("cambiarEstadoNota('borrador')", 'Volver a revisar', ' btn-primary');
  arriba.innerHTML = (e === 'borrador' ? boton("cambiarEstadoNota('rechazada')", 'Rechazar') : '')
    + (n.hubspot && n.hubspot.url ? '<a class="btn btn-xs" href="' + urlSegura(n.hubspot.url) + '" target="_blank" rel="noopener">Ver en HubSpot</a>' : '')
    + principal;

  var item = function(onclick, texto, clase) {
    return '<button type="button" role="menuitem" class="' + (clase || '') + '" onclick="' + onclick + '">' + texto + '</button>';
  };
  var menu = item('copiar()', 'Copiar texto') + item('verComoSeGenero()', 'Cómo se generó');
  if (e === 'aprobada' || e === 'rechazada') menu += item("cambiarEstadoNota('borrador')", 'Volver a revisar');
  if (e === 'publicado') menu += item("cambiarEstadoNota('aprobada')", 'Despublicar', 'peligro');
  var activo = function(p) { return _lectura.panel === p ? ' activo' : ''; };
  cont.innerHTML = '<div class="lectura-barra" role="toolbar" aria-label="Acciones de la nota">'
    + (e !== 'publicado' ? boton('editarNota()', '✎ Editar') : '')
    + boton("abrirPanelLectura('calificar')", '★ Calificar', activo('calificar'), ' aria-pressed="' + (_lectura.panel === 'calificar') + '"')
    + boton("abrirPanelLectura('previa')", 'Vista previa', activo('previa'), ' aria-pressed="' + (_lectura.panel === 'previa') + '"')
    + '<div class="menu-nota"><button type="button" class="btn btn-xs" id="nota-mas" aria-haspopup="menu" aria-expanded="false"'
    + ' aria-controls="nota-menu" onclick="alternarMenuNota()">Más ▾</button>'
    + '<div class="menu-nota-lista" id="nota-menu" role="menu" aria-label="Más acciones" hidden>' + menu + '</div></div>'
    + '</div>';
}

function verComoSeGenero() {
  alternarMenuNota(false);
  var d = $('lectura-generacion');
  if (!d) return;
  d.open = true;
  d.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ── El texto: datos marcados, avisos y cómo se generó ──────────────────── */

function decorarLectura() {
  var n = _notaActual, nota = _recorrido && _recorrido.nota;
  if (!n || !vistaCliente() || !_recorrido.lectura || !nota || nota._id !== n.id) return;
  var cuerpo = $('art-body'), texto = $('nota-texto');
  cuerpo.classList.add('lectura-doc');
  if (!texto) return;
  var principal = _vistaEsPrincipal(n);

  // Junto a los idiomas, cuántos lineamientos cumple.
  var cal = nota.calidad || {}, chips = cuerpo.querySelector('.idiomas-nota');
  if (chips && cal.puntaje !== null && cal.puntaje !== undefined) {
    var fallas = (cal.fallas_criticas || []).length;
    chips.insertAdjacentHTML('beforeend', '<span class="chip lectura-lineamientos' + (fallas ? ' mal' : '') + '">'
      + escHtml(cal.puntaje + '/9 ' + tr('lineamientos')) + '</span>');
  }

  // Debajo del título: tono, largo y fuentes.
  var h1 = texto.querySelector('h1'), palabras = (texto.textContent.match(/\S+/g) || []).length;
  var meta = [nota.persona ? nota.persona.charAt(0).toUpperCase() + nota.persona.slice(1) : '',
              palabras + ' ' + tr('palabras'), (nota.fuentes || []).length ? (nota.fuentes.length + ' ' + tr((nota.fuentes.length === 1 ? 'fuente' : 'fuentes'))) : ''];
  var lineaMeta = document.createElement('p');
  lineaMeta.className = 'lectura-meta';
  lineaMeta.innerHTML = meta.filter(Boolean).map(function(x) { return '<span>' + escHtml(x) + '</span>'; }).join('');
  if (h1) h1.after(lineaMeta); else texto.prepend(lineaMeta);

  // Los datos se verificaron en el texto original; en una traducción se marcan donde
  // aparecen (las cifras se reconocen aunque cambien los separadores: 2,65 = 2.65).
  var v = nota.verificacion || {}, sirve = function(d) { return esDatoVerificable(d) && noOculto(d); };
  marcarDatos(texto, (v.respaldados || []).filter(esDatoVerificable), 'ok');
  marcarDatos(texto, (v.dudosos || []).filter(sirve), 'duda');
  marcarDatos(texto, (v.sin_respaldo || []).filter(sirve), 'sin');
  avisosDeDatos(texto, (v.sin_respaldo || []).filter(sirve), 'sin');
  avisosDeDatos(texto, (v.dudosos || []).filter(sirve), 'duda');
  if (!principal) return;   // los demás avisos y "Cómo se generó" son de la nota original

  // Lo demás que necesita atención, arriba del texto.
  var otros = chequeosDeNota(nota).filter(function(c) { return c.c !== 'ok' && c.id !== 'datos'; });
  var ancla = lineaMeta;
  otros.forEach(function(c) {
    var aviso = document.createElement('div');
    aviso.className = 'lectura-aviso' + (c.c === 'err' ? ' err' : '');
    aviso.setAttribute('role', 'note');
    aviso.innerHTML = '<span class="lectura-aviso-icono" aria-hidden="true">' + (c.c === 'err' ? '!' : '⚠') + '</span>'
      + '<div><b>' + escHtml(c.titulo) + '</b><span>' + escHtml(c.linea || '') + '</span></div>'
      + (c.accion ? '<button type="button" class="btn btn-xs" onclick="' + escHtml(c.accion.onclick) + '">' + escHtml(c.accion.texto) + '</button>' : '');
    ancla.after(aviso);
    ancla = aviso;
  });

  // Al final, cómo se generó (noticias, plan, costo, criterios).
  var gen = document.createElement('details');
  gen.className = 'lectura-generacion';
  gen.id = 'lectura-generacion';
  gen.innerHTML = '<summary>Cómo se generó</summary><div class="acordeon" id="recorrido-generacion"></div>';
  texto.after(gen);
  pintarGeneracion(nota, gen.querySelector('.acordeon'));
}

function noOculto(dato) { return !_lectura.ocultos[dato]; }

/* Un dato es una cifra o un nombre propio. Las notas viejas guardaron como "dato"
   frases en negrita que abren un paso ("1. Elegí las aplicaciones con más
   circulación."): no se marcan. Misma regla que extraer_datos (verificacion.py). */
function esDatoVerificable(dato) {
  var d = String(dato || '').trim();
  if (d.length < 2) return false;
  if (/\d/.test(d.replace(/^\d+[.)]\s+/, ''))) return true;
  d = d.replace(/^\d+[.)]\s*/, '');
  var palabras = d.split(/\s+/);
  if (palabras.length === 1) return true;
  if (/[.:!?]$/.test(d) && !/\b[A-Z]\.[A-Z]?\.?$|Ltda\.$|Inc\.$|Corp\.$/.test(d)) return false;   // termina como una oración
  // Un nombre lleva mayúscula más allá de la primera palabra ("Mercado Libre"); una frase, no.
  return palabras.length <= 3 || palabras.slice(1).some(function(p) { return /^[A-ZÁÉÍÓÚÂÊÔÃÕÇÑ]/.test(p); });
}

/* Dónde está el dato en un texto: [inicio, largo] o null. Primero tal cual; si es
   una cifra, por sus dígitos (en una traducción "US$ 2,65 trilhões" es "US$ 2.65 trillion"). */
var _MONEDA = '(?:US\\$|USD|U\\$S|R\\$|€|\\$)';
var _MAGNITUD = '(?:mil millones|millones|millón|milhões|milhão|millions?|bilhões|bilhão|billones|billón|billions?|trilhões|trilhão|trillions?|mil|mi|bi|tri|M|B)';
function patronDeDato(dato) {
  var d = String(dato).trim(), digitos = d.replace(/\D/g, '');
  if (!digitos || (digitos.length < 2 && !/%/.test(d))) return null;
  var moneda = new RegExp('^' + _MONEDA, 'i').test(d), magnitud = new RegExp('\\d\\s?' + _MAGNITUD + '\\b', 'i').test(d);
  return new RegExp((moneda ? _MONEDA + '\\s?' : '') + '(?<![\\d.,])' + digitos.split('').join('[.,\\s\\u00a0\\u202f]?') + '(?![\\d]|[.,]\\d)'
    + (/%|por ciento/i.test(d) ? '\\s?(?:%|por ciento|percent)' : '') + (magnitud ? '(?:\\s?' + _MAGNITUD + '\\b)?' : ''), 'i');
}
function buscarDato(texto, dato, patron) {
  var i = texto.toLocaleLowerCase().indexOf(dato.toLocaleLowerCase());
  if (i >= 0) return [i, dato.length];
  var m = patron && patron.exec(texto);
  return m ? [m.index, m[0].length] : null;
}

/* Envuelve cada aparición del dato en el texto (sin tocar los enlaces). */
function marcarDatos(raiz, datos, clase) {
  datos.slice().sort(function(a, b) { return b.length - a.length; }).forEach(function(dato) {
    var buscado = String(dato || '').trim();
    if (buscado.length < 2) return;
    var patron = patronDeDato(buscado), caminante = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT), nodos = [];
    while (caminante.nextNode()) nodos.push(caminante.currentNode);
    nodos.forEach(function(nodo) {
      if (nodo.parentNode.closest('mark.dato, a, .lectura-meta, .lectura-aviso')) return;
      var donde = buscarDato(nodo.data, buscado, patron);
      if (!donde) return;
      var medio = nodo.splitText(donde[0]);
      medio.splitText(donde[1]);
      var marca = document.createElement('mark');
      marca.className = 'dato ' + clase;
      marca.dataset.dato = dato;
      marca.title = { ok: tr('Aparece en las noticias'), duda: tr('No se pudo confirmar'), sin: tr('Sin respaldo en las noticias') }[clase];
      medio.parentNode.replaceChild(marca, medio);
      marca.appendChild(medio);
    });
  });
}

/* Un aviso debajo del párrafo donde aparece cada dato dudoso o sin respaldo (uno por párrafo). */
function avisosDeDatos(raiz, datos, clase) {
  var porBloque = new Map(), sueltos = [], visto = {};
  datos.forEach(function(dato) {
    var marca = raiz.querySelector('mark.dato[data-dato="' + CSS.escape(dato) + '"]');
    visto[dato] = marca ? marca.textContent : dato;   // en una traducción, como quedó escrito ahí
    var bloque = marca && marca.closest('p, li, h2, h3, blockquote');
    if (!bloque) { sueltos.push(dato); return; }
    if (bloque.tagName === 'LI') bloque = bloque.closest('ul, ol') || bloque;
    if (!porBloque.has(bloque)) porBloque.set(bloque, []);
    porBloque.get(bloque).push(dato);
  });
  var aviso = function(lista) {
    var div = document.createElement('div');
    div.className = 'lectura-aviso' + (clase === 'sin' ? ' err' : '');
    div.setAttribute('role', 'note');
    div.innerHTML = '<span class="lectura-aviso-icono" aria-hidden="true">' + (clase === 'sin' ? '!' : '⚠') + '</span>'
      + '<div><div class="lectura-aviso-titulo"><b>' + escHtml(tr(clase === 'sin' ? (lista.length === 1 ? 'Dato sin respaldo' : 'Datos sin respaldo') : (lista.length === 1 ? 'Dato dudoso' : 'Datos dudosos')))
      + '</b>' + lista.map(function(d) { return '<q translate="no">' + escHtml(visto[d]) + '</q>'; }).join('') + '</div><span>' + escHtml(tr(clase === 'sin' ? 'No aparece en las noticias: revisalo o quitalo antes de publicar.'
                                                                                 : 'No aparece literal en las noticias.')) + '</span></div>'
      + (_notaActual.estado !== 'publicado' ? '<button type="button" class="btn btn-xs" onclick="editarNota()">' + escHtml(tr('Editar')) + '</button>' : '')
      + '<button type="button" class="btn btn-xs" data-datos="' + escHtml(JSON.stringify(lista)) + '" onclick="dejarDatos(this)">' + escHtml(tr('Dejar así')) + '</button>';
    return div;
  };
  porBloque.forEach(function(lista, bloque) { bloque.after(aviso(lista)); });
  if (sueltos.length) {
    var meta = raiz.querySelector('.lectura-meta');
    if (meta) meta.after(aviso(sueltos));
  }
}

// "Dejar así": el aviso y la marca se van mientras la nota esté abierta (no cambia nada guardado).
function dejarDatos(btn) {
  JSON.parse(btn.dataset.datos).forEach(function(d) { _lectura.ocultos[d] = true; });
  var cuerpo = $('art-body'), scroll = cuerpo.scrollTop;
  pintarCuerpoNota();
  cuerpo.scrollTop = scroll;
}

/* ── El panel de la derecha ─────────────────────────────────────────────── */

var REDES_LECTURA = [
  { id: 'blog', nombre: 'Blog', icono: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 13h10M7 16h6"/></svg>' },
  { id: 'instagram', nombre: 'Instagram', icono: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>' },
  { id: 'linkedin', nombre: 'LinkedIn', icono: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9.5h4V21H3zM9.5 9.5h3.8v1.6h.1c.5-1 1.8-2 3.8-2 4 0 4.8 2.6 4.8 6V21h-4v-5.2c0-1.2 0-2.9-1.8-2.9s-2 1.4-2 2.8V21h-4z"/></svg>' }
];

function pintarPanelLectura() {
  var cont = $('check-list'), nota = _recorrido.nota;
  $('modal-caja').classList.toggle('panel-cerrado', !_lectura.panel);
  if (_notaActual) pintarAccionesNota();
  if (!_lectura.panel) { cont.innerHTML = ''; return; }
  var cerrar = '<button type="button" class="lp-cerrar" onclick="cerrarPanelLectura()" aria-label="' + escHtml(tr('Cerrar el panel')) + '">✕</button>';
  if (_lectura.panel === 'calificar') {
    cont.innerHTML = '<div class="lp-cab"><b>Calificar la nota</b>' + cerrar + '</div>'
      + '<p class="lp-sub">Tu calificación le enseña a la generación qué funciona. La de la IA es solo orientativa.</p>'
      + '<div class="lp-cuerpo lp-calificar" id="lp-cuerpo"><div id="lp-tu-calificacion"></div><div id="lp-critica"></div></div>';
    pintarCalificacion(nota, $('lp-tu-calificacion'));   // con la sugerencia de la IA arriba (juicioHtml)
    pintarCriticaIA(nota, $('lp-critica'));
    return;
  }
  cont.innerHTML = '<div class="lp-cab"><b>Vista previa</b>' + cerrar + '</div>'
    + '<div class="lp-redes" role="radiogroup" aria-label="' + escHtml(tr('Dónde se publica')) + '">'
    + REDES_LECTURA.map(function(r) {
        return '<button type="button" role="radio" aria-checked="' + (r.id === _lectura.red) + '" onclick="verRedLectura(\'' + r.id + '\')">'
          + r.icono + '<span>' + r.nombre + '</span></button>';
      }).join('') + '</div>'
    + '<div class="lp-cuerpo" id="lp-cuerpo"></div>';
  if (_lectura.red === 'instagram') pintarInstagramLectura(nota, $('lp-cuerpo'));
  else if (_lectura.red === 'linkedin') pintarLinkedinLectura(nota, $('lp-cuerpo'));
  else pintarBlogLectura(nota, $('lp-cuerpo'));
}

function verRedLectura(red) {
  _lectura.red = red;
  _lectura.pagina = 0;
  pintarPanelLectura();
}

/* Blog: el post como se ve en el navegador y, debajo, lo que va a HubSpot. */
function pintarBlogLectura(nota, cont) {
  var im = nota.imagen || {}, cuerpoImgs = (nota.imagenes_cuerpo || []).length;
  cont.innerHTML = '<div class="lp-navegador"><div class="lp-navegador-barra" aria-hidden="true"><i></i><i></i><i></i>'
    + '<span class="lp-url" id="lp-url">afterdrive.alephee.com/' + escHtml(nota.idioma || 'pt') + '/blog/…</span></div>'
    + '<div class="lp-blog" id="lp-blog" translate="no"><p class="lp-sub">' + escHtml(tr('Cargando la vista previa…')) + '</p></div></div>'
    + '<div class="lp-ajustes">'
    + '<div class="lp-fila"><span class="lp-k">' + escHtml(tr('Imagen destacada')) + '</span><span class="lp-v">'
    + (im.url ? '<img src="' + urlSegura(im.url) + '" alt="" referrerpolicy="no-referrer">' : '')
    + escHtml(im.url ? (im.origen ? tr('Foto de la noticia') + ': ' + (im.origen.titulo || '') : im.subida ? tr('Subida desde la computadora') : tr('Elegida a mano'))
                     : tr('Sin imagen destacada')) + '</span>'
    + '<button type="button" class="lp-link" aria-expanded="false" onclick="alternarCambioImagen(this)">' + escHtml(tr(im.url ? 'Cambiar' : 'Elegir')) + '</button></div>'
    + '<div class="lp-imagen-cambiar" id="lp-imagen-cambiar" hidden>' + zonaImagenHtml('-publicar')
    + '<button type="button" class="enlace-detalle" onclick="vistaPreviaNota()">' + escHtml(tr('Elegir entre las fotos de las noticias o pegar una URL')) + '</button></div>'
    + '<div class="lp-fila"><span class="lp-k">' + escHtml(tr('Fotos en el texto')) + '</span><span class="lp-v">'
    + escHtml(cuerpoImgs ? cuerpoImgs + ' ' + tr(cuerpoImgs === 1 ? 'foto repartida entre las secciones' : 'fotos repartidas entre las secciones') : tr('Ninguna')) + '</span><span></span></div>'
    + '<div class="lp-fila"><span class="lp-k">' + escHtml(tr('Firma')) + '</span><span class="lp-v" id="lp-firma">' + escHtml(tr('Cargando…')) + '</span><span></span></div>'
    + '<div class="lp-fila"><span class="lp-k">Blog</span><span class="lp-v" id="lp-destino">' + escHtml(tr('Cargando…')) + '</span><span></span></div>'
    + '<div class="lp-fila"><span class="lp-k">' + escHtml(tr('Otros idiomas')) + '</span><span class="lp-v">' + chipsIdiomasLectura(nota) + '</span>'
    + (nota.hubspot && nota.hubspot.id ? '<button type="button" class="lp-link" id="btn-traducciones" onclick="subirTraducciones(\'' + escHtml(nota._id) + '\')">' + escHtml(tr('Volver a subir')) + '</button>' : '<span></span>') + '</div>'
    + '<div class="lp-fila"><span class="lp-k">' + escHtml(tr('Cómo se sube')) + '</span><span class="lp-v" id="lp-subida">' + escHtml(tr('Como borrador en HubSpot. Se publica desde HubSpot.')) + '</span><span></span></div>'
    + '</div>';
  prepararZonaImagen($('zona-imagen-publicar'));
  cargarBlogLectura(nota);
}

function chipsIdiomasLectura(nota) {
  var tr_ = nota.traducciones || {}, hs = nota.hubspot_traducciones || {};
  var otros = ['pt', 'es', 'en'].filter(function(c) { return c !== nota.idioma; });
  return otros.map(function(c) {
    var t = tr_[c] || {}, h = hs[c] || {};
    var estado = h.error ? 'mal' : t.contenido ? 'ok' : '';
    var marca = h.error ? ' ✕' : t.contenido ? ' ✓' : '';
    return '<button type="button" class="chip lp-idioma ' + estado + '" onclick="verIdiomaNota(\'' + c + '\')" title="'
      + escHtml(h.error || (t.contenido ? tr('Ver esta versión') : tr('Todavía no está traducida'))) + '">' + escHtml(NOMBRE_IDIOMA[c] || c) + marca + '</button>';
  }).join('');
}

function alternarCambioImagen(btn) {
  var zona = $('lp-imagen-cambiar'), abrir = zona.hidden;
  zona.hidden = !abrir;
  btn.setAttribute('aria-expanded', abrir);
}

async function cargarBlogLectura(nota) {
  var id = nota._id, previa, destino, configurado;
  try { previa = await pedir('/api/historial/vista-previa/notas_fase2/' + id); }
  catch (e) { if ($('lp-blog')) $('lp-blog').innerHTML = '<p class="revision-mal">' + escHtml(e.message) + '</p>'; }
  if (!_notaActual || _notaActual.id !== id || !$('lp-blog')) return;
  if (previa) {
    var parrafos = (previa.html || '').length;
    $('lp-url').textContent = 'afterdrive.alephee.com/' + (nota.idioma || 'pt') + '/blog/' + previa.slug;
    $('lp-blog').innerHTML = (previa.imagen && previa.imagen.url ? '<img class="lp-blog-img" src="' + urlSegura(previa.imagen.url) + '" alt="" referrerpolicy="no-referrer">' : '')
      + (previa.etiquetas.length ? '<div class="lp-blog-cat">' + escHtml(previa.etiquetas.join(' · ')) + '</div>' : '')
      + '<h2>' + escHtml(previa.titulo) + '</h2>'
      + '<div class="lp-blog-autor" id="lp-blog-autor">' + escHtml(Math.max(1, Math.round(parrafos / 1500)) + ' ' + tr('min de lectura')) + '</div>'
      + '<div class="lp-blog-cuerpo">' + DOMPurify.sanitize(previa.html) + '</div>';
  }
  configurado = await hubspotConfigurado();
  try { destino = await pedir('/api/hubspot/destino/notas_fase2/' + id); }
  catch (e) {
    if (!_notaActual || _notaActual.id !== id) return;
    if (e.status === 422) { _notaActual.sinDestino = true; pintarAccionesNota(); }
    if ($('lp-destino')) $('lp-destino').innerHTML = '<span class="revision-mal">' + escHtml(e.message) + '</span>';
    if ($('lp-firma')) $('lp-firma').textContent = '—';
    return;
  }
  if (!_notaActual || _notaActual.id !== id || !$('lp-firma')) return;
  var opciones = destino.autores.length ? destino.autores : [{ id: destino.autor_id, nombre: tr('Autor por defecto') }];
  if (!opciones.some(function(a) { return a.id === destino.autor_id; })) opciones.unshift({ id: destino.autor_id, nombre: 'Autor ' + destino.autor_id });
  var editable = _notaActual.estado !== 'publicado';
  // Mismo id que en el recorrido: enviarAHubspot lee de acá quién firma.
  $('lp-firma').innerHTML = '<label class="sr-only" for="hubspot-autor">' + escHtml(tr('Autor')) + '</label>'
    + '<select id="hubspot-autor" class="lp-select"' + (editable ? '' : ' disabled') + ' onchange="firmaLectura(this)">'
    + opciones.map(function(a) {
        return '<option value="' + escHtml(a.id) + '"' + (a.id === destino.autor_id ? ' selected' : '') + ' translate="no">' + escHtml(a.nombre) + '</option>';
      }).join('') + '</select>';
  firmaLectura($('hubspot-autor'));
  $('lp-destino').textContent = destino.blog + (destino.etiquetas.length ? ' · ' + tr('etiquetas') + ': ' + destino.etiquetas.join(', ') : '');
  if (!configurado) {
    $('lp-subida').innerHTML = '<span class="revision-mal">' + escHtml(tr('HubSpot no está configurado en este servidor: al aprobar, la nota queda aprobada pero no se sube.')) + '</span>';
  }
}

// El nombre de quien firma, también en la vista previa del post.
function firmaLectura(select) {
  var autor = $('lp-blog-autor'), opcion = select && select.options[select.selectedIndex];
  if (!autor || !opcion) return;
  autor.textContent = tr('Por') + ' ' + opcion.textContent + ' · ' + autor.textContent.replace(/^.*·\s*/, '');
}

/* Instagram: el carrusel dentro de un celular (los mismos controles de carrusel.js). */
function pintarInstagramLectura(nota, cont) {
  var todos = carruselesDe(nota), hechos = IDIOMAS_CARRUSEL.filter(function(c) { return todos[c]; });
  if (!_carruselVista || hechos.indexOf(_carruselVista) < 0) _carruselVista = hechos.indexOf(nota.idioma) >= 0 ? nota.idioma : hechos[0];
  var faltan = IDIOMAS_CARRUSEL.filter(function(c) { return !todos[c]; });
  var crear = '<div class="lp-carrusel-acciones">'
    + '<button type="button" class="btn btn-xs' + (hechos.length ? '' : ' btn-primary') + '" id="btn-carrusel-crear" onclick="crearCarrusel()">'
    + escHtml(tr(hechos.length ? 'Volver a crear los 3 con IA' : 'Crear carruseles (español, portugués e inglés)')) + '</button>'
    + (hechos.length && faltan.length ? '<button type="button" class="btn btn-xs btn-primary" id="btn-carrusel-faltan" onclick="crearCarrusel('
      + escHtml(JSON.stringify(faltan)) + ')">' + escHtml(tr('Crear los que faltan')) + '</button>' : '')
    + '</div><p class="feedback" id="carrusel-estado" role="status" aria-live="polite"></p>';
  if (!hechos.length) {
    cont.innerHTML = '<div class="lp-vacio"><p>' + escHtml(tr('Esta nota todavía no tiene carruseles para redes.')) + '</p>'
      + '<p class="lp-sub">' + escHtml(tr('Se arman 3 imágenes por idioma con el diseño de AfterDrive: la portada usa la imagen destacada y los textos los escribe la IA a partir de la nota.')) + '</p>'
      + crear + '</div>';
    cont._nota = nota;
    return;
  }
  var tmp = document.createElement('div');
  tmp.innerHTML = carruselIdiomaHtml(nota, todos[_carruselVista], _carruselVista);
  var post = tmp.querySelector('.ig-post'), descargas = tmp.querySelector('.carrusel-descargas'), textos = tmp.querySelector('.carrusel-textos');
  cont.innerHTML = '<div class="lp-telefono"><div class="lp-pantalla"><div class="lp-isla" aria-hidden="true"></div>'
    + '<div class="lp-ig-top" aria-hidden="true"><span>Instagram</span><span>♡</span></div><div id="lp-ig"></div></div></div>'
    + idiomasCarruselLectura(todos) + crear;
  $('lp-ig').appendChild(post);
  if (descargas) cont.appendChild(descargas);
  if (textos) cont.appendChild(textos);
  cont._nota = nota;
  if (_carruselIr) { var ir = _carruselIr; _carruselIr = 0; requestAnimationFrame(function() { igIr(ir, false); igAlDeslizar(); }); }
}

function idiomasCarruselLectura(todos) {
  return '<div class="lp-idiomas" role="radiogroup" aria-label="' + escHtml(tr('Idioma del carrusel')) + '">'
    + IDIOMAS_CARRUSEL.map(function(c) {
        var hay = !!todos[c];
        return '<button type="button" role="radio" class="chip' + (c === _carruselVista ? ' on' : '') + '" aria-checked="' + (c === _carruselVista) + '"'
          + (hay ? '' : ' disabled title="' + escHtml(tr('Todavía no se creó')) + '"') + ' onclick="verCarrusel(\'' + c + '\')">' + c.toUpperCase() + '</button>';
      }).join('') + '</div>';
}

/* LinkedIn: el post con el PDF como documento del feed. El texto del post es la
   meta description de la nota en ese idioma (la IA todavía no escribe uno aparte). */
function pintarLinkedinLectura(nota, cont) {
  var todos = carruselesDe(nota), hechos = IDIOMAS_CARRUSEL.filter(function(c) { return todos[c]; });
  if (!_carruselVista || hechos.indexOf(_carruselVista) < 0) _carruselVista = hechos.indexOf(nota.idioma) >= 0 ? nota.idioma : hechos[0];
  var c = _carruselVista && todos[_carruselVista];
  if (!c) {
    cont.innerHTML = '<div class="lp-vacio"><p>' + escHtml(tr('El documento de LinkedIn sale del carrusel, y esta nota todavía no tiene.')) + '</p>'
      + '<button type="button" class="btn btn-xs btn-primary" onclick="verRedLectura(\'instagram\')">' + escHtml(tr('Ir a crear los carruseles')) + '</button></div>';
    return;
  }
  var diapositivas = c.diapositivas || [], pagina = Math.min(_lectura.pagina, diapositivas.length - 1), v = encodeURIComponent(c.generado_en || '');
  var md = _carruselVista === nota.idioma ? nota.contenido : ((nota.traducciones || {})[_carruselVista] || {}).contenido;
  var texto = metaDeNota(md) || (c.textos || {}).subtitulo || '';
  cont.innerHTML = '<article class="lp-linkedin">'
    + '<div class="lp-li-cab"><span class="lp-li-logo" aria-hidden="true">' + (((document.querySelector('#logoEl svg') || {}).outerHTML) || '') + '</span>'
    + '<div><b translate="no">AfterDrive by Alephee</b><small>' + escHtml(tr('Ahora')) + ' · 🌐</small></div></div>'
    + '<p class="lp-li-texto" translate="no">' + escHtml(texto) + '</p>'
    + '<div class="lp-li-doc"><div class="lp-li-doc-cab"><span translate="no">' + escHtml(((c.textos || {}).titulo || '').slice(0, 48)) + ' · '
    + diapositivas.length + ' ' + escHtml(tr('páginas')) + '</span></div>'
    + '<div class="lp-li-pagina"><img src="' + urlSegura(diapositivas[pagina]) + '?v=' + v + '" alt="' + escHtml(tr('Página') + ' ' + (pagina + 1)) + '">'
    + (pagina > 0 ? '<button type="button" class="lp-li-flecha ant" aria-label="' + escHtml(tr('Página anterior')) + '" onclick="paginaLinkedin(-1)">‹</button>' : '')
    + (pagina < diapositivas.length - 1 ? '<button type="button" class="lp-li-flecha sig" aria-label="' + escHtml(tr('Página siguiente')) + '" onclick="paginaLinkedin(1)">›</button>' : '')
    + '</div><div class="lp-li-pager" aria-hidden="true">' + diapositivas.map(function(_, i) { return '<i' + (i === pagina ? ' class="on"' : '') + '></i>'; }).join('') + '</div></div>'
    + '<div class="lp-li-acciones" aria-hidden="true"><span>👍 Recomendar</span><span>💬 Comentar</span><span>↗ Compartir</span></div></article>'
    + '<p class="lp-sub lp-li-nota">' + escHtml(tr('El texto del post es la descripción de la nota en ese idioma.')) + '</p>'
    + idiomasCarruselLectura(todos)
    + '<p class="carrusel-descargas"><a href="/api/carrusel/' + encodeURIComponent(nota._id) + '/pdf?idioma=' + _carruselVista + '">'
    + escHtml(tr('Descargar el PDF para LinkedIn')) + '</a></p>';
  cont._nota = nota;
}

function paginaLinkedin(paso) {
  _lectura.pagina = Math.max(0, _lectura.pagina + paso);
  pintarPanelLectura();
}

// La meta description: la última línea en cursiva de la nota.
function metaDeNota(md) {
  var lineas = String(md || '').trim().split('\n').filter(function(l) { return l.trim(); });
  var ultima = (lineas[lineas.length - 1] || '').trim(), m = ultima.match(/^[*_]{1,2}([^*_].*?)[*_]{1,2}$/);
  return m ? m[1].trim() : '';
}
