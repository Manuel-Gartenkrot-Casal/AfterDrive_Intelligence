/* ayuda.js — Página de Ayuda (/ayuda): guía de uso y documentación técnica.
   Los documentos son Markdown del repo (lista blanca en flask_api.DOCUMENTOS);
   se renderizan con marked y se limpian con DOMPurify, como las notas.
   Idioma: la interfaz se traduce con idioma.js; la guía se pide en el idioma
   elegido (?idioma=pt|en) y, si no hay traducción, llega en español. */

var _docs = [];

function escHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// Archivo .md del repo -> slug de la lista blanca ("../CONTEXT.md" -> "glosario").
function slugDeArchivo(href) {
  var nombre = (href.split('#')[0].split('/').pop() || '').replace(/\.md$/i, '');
  if (nombre === 'CONTEXT') return 'glosario';
  if (nombre === 'README') return 'indice';
  return _docs.some(function(d) { return d.slug === nombre; }) ? nombre : null;
}

function pintarIndice(actual) {
  var html = '', grupo = '';
  _docs.forEach(function(d) {
    if (d.grupo !== grupo) { grupo = d.grupo; html += '<div class="ayuda-grupo">' + escHtml(grupo) + '</div>'; }
    html += '<a href="#' + d.slug + '"' + (d.slug === actual ? ' aria-current="page"' : '') + '>' + escHtml(d.titulo) + '</a>';
  });
  document.getElementById('ayuda-indice').innerHTML = html;
}

var _actual = '';

async function mostrar(slug) {
  var doc = document.getElementById('ayuda-contenido');
  var estado = document.getElementById('ayuda-estado');
  if (!_docs.some(function(d) { return d.slug === slug; })) slug = _docs.length ? _docs[0].slug : '';
  _actual = slug;
  pintarIndice(slug);
  doc.innerHTML = '';
  estado.hidden = false;
  if (!slug) { estado.textContent = 'No hay documentación disponible en este servidor.'; return; }
  estado.textContent = 'Cargando…';
  try {
    var r = await fetch('/api/docs/' + encodeURIComponent(slug) + '?idioma=' + idiomaUI());
    if (r.status === 401) { location.href = '/'; return; }
    var d = await r.json();
    if (!d.success) throw new Error(d.error);
    if (slug !== _actual) return;   // mientras cargaba, se pidió otro
    doc.innerHTML = DOMPurify.sanitize(marked.parse(d.markdown));
    doc.lang = d.idioma || 'es';
    estado.hidden = true;
    var titulo = d.titulo + ' · Ayuda · AfterDrive Intelligence';
    document.documentElement.dataset.tituloEs = titulo;
    document.title = tr(titulo);
  } catch (e) {
    estado.textContent = 'No se pudo cargar el documento: ' + e.message;
    return;
  }
  // Links entre documentos: se quedan en esta página. Los externos, en otra pestaña.
  doc.querySelectorAll('a[href]').forEach(function(a) {
    var href = a.getAttribute('href');
    if (/^https?:\/\//i.test(href)) { a.target = '_blank'; a.rel = 'noopener'; return; }
    if (href.charAt(0) === '#') return;
    var destino = /\.md(#.*)?$/i.test(href) ? slugDeArchivo(href) : null;
    if (destino) a.setAttribute('href', '#' + destino);
    else { a.removeAttribute('href'); a.title = 'Disponible en el repositorio'; }
  });
  window.scrollTo(0, 0);
  document.getElementById('ayuda-doc').focus({ preventScroll: true });
}

async function iniciar() {
  try {
    var r = await fetch('/api/docs');
    if (r.status === 401) { location.href = '/'; return; }
    _docs = (await r.json()).documentos || [];
  } catch (e) { _docs = []; }
  window.addEventListener('hashchange', function() { mostrar(location.hash.slice(1)); });
  document.addEventListener('idioma', function() { if (_actual) mostrar(_actual); });
  mostrar(location.hash.slice(1));
}

// Sin el CDN (marked o DOMPurify), el documento se muestra como texto: nunca HTML sin limpiar.
if (!window.marked || !window.DOMPurify) {
  window.marked = { parse: function(s) { return '<pre>' + escHtml(s) + '</pre>'; } };
  window.DOMPurify = { sanitize: function(s) { return s; } };
}
initIdioma();
iniciar();
