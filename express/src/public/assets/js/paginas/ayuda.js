/* ayuda.js — Página de Ayuda (/ayuda): guía de uso y documentación técnica.
   Los documentos son Markdown del repo (lista blanca en flask_api.DOCUMENTOS);
   se renderizan con marked y se limpian con DOMPurify, como las notas. */

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

async function mostrar(slug) {
  var doc = document.getElementById('ayuda-doc');
  if (!_docs.some(function(d) { return d.slug === slug; })) slug = _docs.length ? _docs[0].slug : '';
  pintarIndice(slug);
  if (!slug) { doc.textContent = 'No hay documentación disponible en este servidor.'; return; }
  try {
    var r = await fetch('/api/docs/' + encodeURIComponent(slug));
    if (r.status === 401) { location.href = '/'; return; }
    var d = await r.json();
    if (!d.success) throw new Error(d.error);
    doc.innerHTML = DOMPurify.sanitize(marked.parse(d.markdown));
    document.title = d.titulo + ' · Ayuda · AfterDrive Intelligence';
  } catch (e) {
    doc.textContent = 'No se pudo cargar el documento: ' + e.message;
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
  doc.focus({ preventScroll: true });
}

async function iniciar() {
  try {
    var r = await fetch('/api/docs');
    if (r.status === 401) { location.href = '/'; return; }
    _docs = (await r.json()).documentos || [];
  } catch (e) { _docs = []; }
  window.addEventListener('hashchange', function() { mostrar(location.hash.slice(1)); });
  mostrar(location.hash.slice(1));
}

// Sin el CDN (marked o DOMPurify), el documento se muestra como texto: nunca HTML sin limpiar.
if (!window.marked || !window.DOMPurify) {
  window.marked = { parse: function(s) { return '<pre>' + escHtml(s) + '</pre>'; } };
  window.DOMPurify = { sanitize: function(s) { return s; } };
}
iniciar();
