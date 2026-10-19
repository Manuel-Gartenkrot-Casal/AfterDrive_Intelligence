/* idioma.js — Interfaz en español, portugués o inglés.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   El texto base es el español que ya está en el HTML y en el JS. En lugar de
   reescribir cada archivo con claves, este módulo traduce lo que se ve: recorre
   los textos y los atributos (placeholder, title, aria-label, alt), los busca
   en los diccionarios de i18n/textos.js (clave = el texto en español) y, si no
   están, en sus patrones (textos con números o nombres). Un MutationObserver
   traduce lo que el JS pinta después. Lo que no está en el diccionario queda
   en español: nunca se rompe nada, a lo sumo queda sin traducir.

   El contenido (notas, noticias, URLs) no se traduce: va dentro de un
   elemento con translate="no" o de un input. Para agregar un texto nuevo de la
   interfaz: sumalo a _FILAS_TEXTOS en i18n/textos.js (español, portugués,
   inglés). Para un mensaje armado en JS con datos variables, un patrón en
   PATRONES. tr(texto) devuelve la traducción para usarla desde el JS. */

var IDIOMAS = { es: 'Español', pt: 'Português', en: 'English' };
var LOCALES = { es: 'es-AR', pt: 'pt-BR', en: 'en-US' };
var _ATRIBUTOS = ['placeholder', 'title', 'aria-label', 'alt'];
var _originales = new WeakMap();           // nodo de texto -> {original (español), puesto}
var _atributosOriginales = new WeakMap();  // elemento -> {atributo: {original, puesto}}
var _observador = null;
var _traduciendo = false;

function idiomaUI() {
  var cod = null;
  try { cod = localStorage.getItem('ad-idioma'); } catch (e) {}
  if (IDIOMAS[cod]) return cod;
  var nav = (navigator.language || 'es').slice(0, 2).toLowerCase();
  return IDIOMAS[nav] ? nav : 'es';
}

function localeUI() { return LOCALES[idiomaUI()]; }

function _normal(s) { return s.replace(/\s+/g, ' ').trim(); }

/* Traducción de un texto en español al idioma de la interfaz (o a `cod`).
   Sin traducción, devuelve el mismo texto. */
function tr(texto, cod) {
  cod = cod || idiomaUI();
  if (cod === 'es' || !texto || typeof texto !== 'string') return texto;
  var trad = _traducirCompuesto(texto, cod, 0);
  return trad === undefined ? texto : trad;
}

/* Un texto entero: diccionario, patrones o "Prefijo: resto". */
function _traducirClave(clave, cod) {
  var dic = (window.TEXTOS || {})[cod] || {};
  if (Object.prototype.hasOwnProperty.call(dic, clave)) return dic[clave];
  var patrones = (window.PATRONES || {})[cod] || [];
  for (var i = 0; i < patrones.length; i++) {
    if (patrones[i][0].test(clave)) return clave.replace(patrones[i][0], patrones[i][1]);
  }
  // "Fuente agregada: https://…": se traduce el prefijo y el resto si se puede.
  var m = /^([^:]{2,60}:)\s+(.+)$/.exec(clave);
  if (m && Object.prototype.hasOwnProperty.call(dic, m[1])) {
    var resto = _traducirClave(m[2], cod);
    return dic[m[1]] + ' ' + (resto === undefined ? m[2] : resto);
  }
  return undefined;
}

/* Textos armados por partes (párrafos, oraciones, "a · b"): se prueba el
   texto entero y, si no está, cada parte por separado. */
var _SEPARADORES = [/(\n\s*\n)/, /((?<=[.!?…:])\s+(?=[A-ZÁÉÍÓÚ¿¡"“]))/, /(\s+·\s+)/];

function _traducirCompuesto(texto, cod, nivel) {
  var clave = _normal(texto);
  if (!clave) return undefined;
  var trad = _traducirClave(clave, cod);
  if (trad !== undefined) {
    // Conserva los espacios de los bordes: separan el texto de sus vecinos.
    return texto.match(/^\s*/)[0] + trad + texto.match(/\s*$/)[0];
  }
  for (var n = nivel; n < _SEPARADORES.length; n++) {
    var partes = texto.split(_SEPARADORES[n]);
    if (partes.length < 2) continue;
    var alguna = false;
    var salida = partes.map(function(p, i) {
      if (i % 2) return p;   // el separador queda igual
      var r = _traducirCompuesto(p, cod, n + 1);
      if (r === undefined) return p;
      alguna = true;
      return r;
    });
    if (alguna) return salida.join('');
  }
  return undefined;
}

// Texto que no se toca: contenido (translate="no"), código y lo que se escribe.
function _excluido(el) {
  return !el || !!el.closest('[translate="no"], script, style, textarea, code, pre');
}

// Los atributos (placeholder, aria-label…) de un textarea o un pre sí se traducen.
function _atributosExcluidos(el) {
  return !el || !!el.closest('[translate="no"], script, style');
}

function _traducido(original) { return idiomaUI() === 'es' ? original : tr(original); }

/* Por nodo se guarda el original (español) y lo último que escribimos. Si el
   texto actual no es lo que escribimos, lo cambió el JS: ese es el nuevo original. */
function _traducirTexto(nodo) {
  var r = _originales.get(nodo), actual = nodo.nodeValue;
  if (!r || actual !== r.puesto) {
    if (!/[A-Za-zÀ-ÿ]/.test(actual)) return;
    r = { original: actual };
  }
  r.puesto = _traducido(r.original);
  _originales.set(nodo, r);
  if (actual !== r.puesto) nodo.nodeValue = r.puesto;
}

function _traducirAtributos(el) {
  var guardados = _atributosOriginales.get(el) || {};
  _ATRIBUTOS.forEach(function(a) {
    if (!el.hasAttribute(a)) return;
    var actual = el.getAttribute(a), r = guardados[a];
    if (!r || actual !== r.puesto) r = { original: actual };
    r.puesto = _traducido(r.original);
    guardados[a] = r;
    if (actual !== r.puesto) el.setAttribute(a, r.puesto);
  });
  _atributosOriginales.set(el, guardados);
}

function traducirArbol(raiz) {
  raiz = raiz || document.body;
  if (!raiz) return;
  _traduciendo = true;
  try {
    if (raiz.nodeType === Node.TEXT_NODE) {
      if (!_excluido(raiz.parentElement)) _traducirTexto(raiz);
      return;
    }
    if (raiz.nodeType !== Node.ELEMENT_NODE) return;
    if (_excluido(raiz)) {
      if (!_atributosExcluidos(raiz)) _traducirAtributos(raiz);
      return;
    }
    var recorrido = document.createTreeWalker(raiz, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: function(n) {
        var el = n.nodeType === Node.TEXT_NODE ? n.parentElement : n;
        if (!_excluido(el)) return NodeFilter.FILTER_ACCEPT;
        if (n.nodeType === Node.ELEMENT_NODE && !_atributosExcluidos(n)) _traducirAtributos(n);
        return NodeFilter.FILTER_REJECT;
      }
    });
    var n = raiz;
    do {
      if (n.nodeType === Node.TEXT_NODE) _traducirTexto(n);
      else _traducirAtributos(n);
    } while ((n = recorrido.nextNode()));
  } finally {
    _traduciendo = false;
  }
}

function _observar() {
  if (_observador || !window.MutationObserver) return;
  _observador = new MutationObserver(function(cambios) {
    if (_traduciendo) return;
    cambios.forEach(function(c) {
      if (c.type === 'childList') c.addedNodes.forEach(function(n) { traducirArbol(n); });
      else if (c.type === 'characterData') traducirArbol(c.target);
      else if (c.type === 'attributes' && !_atributosExcluidos(c.target)) { _traduciendo = true; try { _traducirAtributos(c.target); } finally { _traduciendo = false; } }
    });
  });
  _observador.observe(document.body, { childList: true, subtree: true, characterData: true,
                                       attributes: true, attributeFilter: _ATRIBUTOS });
}

function setIdioma(cod) {
  if (!IDIOMAS[cod]) return;
  try { localStorage.setItem('ad-idioma', cod); } catch (e) {}
  document.documentElement.lang = cod;
  traducirArbol(document.body);
  if (document.title && window.TEXTOS) {
    var base = document.documentElement.dataset.tituloEs || document.title;
    document.documentElement.dataset.tituloEs = base;
    document.title = _traducido(base);
  }
  pintarSelectorIdioma();
  document.dispatchEvent(new CustomEvent('idioma', { detail: cod }));
}

/* Selectores de idioma: cualquier .selector-idioma con botones [data-idioma]. */
function pintarSelectorIdioma() {
  var cod = idiomaUI();
  document.querySelectorAll('.selector-idioma [data-idioma]').forEach(function(b) {
    b.setAttribute('aria-pressed', b.dataset.idioma === cod);
  });
}

function htmlSelectorIdioma() {
  return '<div class="selector-idioma" role="group" aria-label="Idioma">'
    + Object.keys(IDIOMAS).map(function(c) {
        return '<button type="button" data-idioma="' + c + '" title="' + IDIOMAS[c] + '" onclick="setIdioma(\'' + c + '\')">'
          + c.toUpperCase() + '</button>';
      }).join('') + '</div>';
}

function initIdioma() {
  document.documentElement.lang = idiomaUI();
  traducirArbol(document.body);
  setIdioma(idiomaUI());
  _observar();
}
