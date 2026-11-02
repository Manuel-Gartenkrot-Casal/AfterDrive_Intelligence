/* carrusel.js — Carruseles para redes de una nota, uno por idioma (paso Publicar de la revisión).
   3 imágenes de 1080×1350 para Instagram y un PDF para LinkedIn en español, portugués e
   inglés. Los arma la Cola (afterdrive/carrusel.py); acá se piden, se ven por idioma, se
   editan los textos y se descargan.
   No publica en redes. Parte del dashboard: ver el final de index.html. */

var IDIOMAS_CARRUSEL = ['es', 'pt', 'en'];
var _carruselVista = null;   // idioma que se está mirando

/* Los guardados por idioma; las notas de antes tenían uno solo en `carrusel`. */
function carruselesDe(nota) {
  var c = Object.assign({}, nota.carruseles || {});
  if (nota.carrusel && nota.carrusel.idioma && !c[nota.carrusel.idioma]) c[nota.carrusel.idioma] = nota.carrusel;
  return c;
}

function pintarCarrusel(nota, panel) {
  var viejo = $('bloque-carrusel');
  var bloque = bloqueRevision('Carruseles para redes', '<div id="carrusel-cuerpo"></div>', 'bloque-carrusel');
  bloque.id = 'bloque-carrusel';
  if (viejo) viejo.replaceWith(bloque); else panel.appendChild(bloque);
  llenarCarrusel(nota);
}

function llenarCarrusel(nota) {
  var cont = $('carrusel-cuerpo');
  if (!cont) return;
  var todos = carruselesDe(nota), hechos = IDIOMAS_CARRUSEL.filter(function(cod) { return todos[cod]; });
  if (!_carruselVista || hechos.indexOf(_carruselVista) < 0) _carruselVista = hechos.indexOf(nota.idioma) >= 0 ? nota.idioma : hechos[0];
  var faltan = IDIOMAS_CARRUSEL.filter(function(cod) { return !todos[cod]; });
  var html = '<p class="revision-sub">Un carrusel por idioma: 3 imágenes de 1080×1350 para Instagram y un PDF para LinkedIn. '
    + 'Las diapositivas se dibujan con el diseño de AfterDrive; la portada usa la imagen destacada de la nota y los textos los escribe la IA a partir de la nota. Se descargan para publicarlas: no se suben solas a las redes.</p>'
    + '<div class="carrusel-fila">'
    + '<button type="button" class="btn' + (hechos.length ? '' : ' btn-primary') + '" id="btn-carrusel-crear" onclick="crearCarrusel()">'
    + (hechos.length ? 'Volver a crear los 3 con IA' : 'Crear carruseles (español, portugués e inglés)') + '</button>'
    + (hechos.length && faltan.length
        ? '<button type="button" class="btn btn-primary" id="btn-carrusel-faltan" onclick="crearCarrusel(' + escHtml(JSON.stringify(faltan)) + ')">Crear los que faltan</button>' : '')
    + '</div><p class="feedback" id="carrusel-estado" role="status" aria-live="polite"></p>';
  if (hechos.length) {
    html += '<div class="modo-switch carrusel-idiomas" role="radiogroup" aria-label="Idioma del carrusel">'
      + IDIOMAS_CARRUSEL.map(function(cod) {
          var hay = !!todos[cod];
          return '<button type="button" role="radio" aria-checked="' + (cod === _carruselVista) + '"'
            + (hay ? '' : ' disabled title="Todavía no se creó"') + ' onclick="verCarrusel(\'' + cod + '\')">'
            + escHtml(NOMBRE_IDIOMA[cod] || cod) + '</button>';
        }).join('') + '</div>';
    html += carruselIdiomaHtml(nota, todos[_carruselVista], _carruselVista);
  }
  cont.innerHTML = html;
  cont._nota = nota;
  if (_carruselIr) { var ir = _carruselIr; _carruselIr = 0; requestAnimationFrame(function() { igIr(ir, false); igAlDeslizar(); }); }
}

var _carruselIr = 0;   // diapositiva a mostrar al redibujar (la que se corrigió)

/* Vista previa como un post de Instagram: una imagen por vez que se desliza (o con las
   flechas y el teclado), el contador 1/3, los puntitos y el pie del post. Debajo, las descargas. */
function carruselIdiomaHtml(nota, c, cod) {
  var t0 = c.textos || {}, v = encodeURIComponent(c.generado_en || '');
  var diapositivas = c.diapositivas || [];
  var html = '<div class="ig-post" aria-label="Vista previa del carrusel como post de Instagram">'
    + '<div class="ig-cabeza"><span class="ig-avatar" aria-hidden="true">' + (((document.querySelector('#logoEl svg') || {}).outerHTML) || 'A') + '</span>'
    + '<span class="ig-cuenta"><strong translate="no">AfterDrive</strong><small>' + escHtml(NOMBRE_IDIOMA[cod] || cod) + '</small></span>'
    + '<span class="ig-mas" aria-hidden="true">•••</span></div>'
    + '<div class="ig-marco">'
    + '<div class="ig-pista" id="ig-pista" tabindex="0" role="group" aria-roledescription="carrusel" aria-label="Diapositivas" onscroll="igAlDeslizar()" onkeydown="igTecla(event)">'
    + diapositivas.map(function(url, i) {
        return '<img src="' + urlSegura(url) + '?v=' + v + '" alt="Diapositiva ' + (i + 1) + ' de ' + diapositivas.length + '" draggable="false">';
      }).join('')
    + '</div>'
    + '<span class="ig-contador" id="ig-contador" aria-live="polite">1/' + diapositivas.length + '</span>'
    + '<button type="button" class="ig-flecha ig-ant" id="ig-ant" aria-label="Diapositiva anterior" onclick="igMover(-1)" hidden>‹</button>'
    + '<button type="button" class="ig-flecha ig-sig" id="ig-sig" aria-label="Diapositiva siguiente" onclick="igMover(1)">›</button>'
    + '</div>'
    + '<div class="ig-acciones" aria-hidden="true">'
    + '<span class="ig-iconos"><svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.3C1 8.4 3.2 5 6.6 5c2 0 3.4 1.1 4.4 2.6C12 6.1 13.4 5 15.4 5 18.8 5 21 8.4 19.6 11.7 17.5 16.4 12 21 12 21z"/></svg>'
    + '<svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-3.1-6.3L21 4l-1.2 4.4A8 8 0 0 1 20 12z"/></svg>'
    + '<svg viewBox="0 0 24 24"><path d="M21 3 10 14M21 3l-7 18-4-7-7-4z"/></svg></span>'
    + '<span class="ig-puntos" id="ig-puntos">' + diapositivas.map(function(_, i) { return '<i' + (i ? '' : ' class="activo"') + '></i>'; }).join('') + '</span>'
    + '<span class="ig-guardar"><svg viewBox="0 0 24 24"><path d="M6 3h12v18l-6-4-6 4z"/></svg></span></div>'
    + '<p class="ig-pie"><strong translate="no">AfterDrive</strong> ' + escHtml(t0.titulo || '') + (t0.subtitulo ? ' — ' + escHtml(t0.subtitulo) : '') + '</p>'
    + '</div>'
    + '<p class="carrusel-descargas">Descargar: '
    + diapositivas.map(function(url, i) {
        return '<a href="' + urlSegura(url) + '?v=' + v + '" download="carrusel-' + cod + '-' + (i + 1) + '.png">imagen ' + (i + 1) + '</a>';
      }).join(' · ')
    + ' · <a href="/api/carrusel/' + encodeURIComponent(nota._id) + '/pdf?idioma=' + cod + '">PDF para LinkedIn</a></p>';
  var t = c.textos || {};
  var puntos = (t.puntos || []).concat(['', '', '']).slice(0, 3);
  return html + '<details class="carrusel-textos"><summary>Editar los textos</summary>'
    + '<label class="control-label" for="carrusel-titulo">Título (diapositiva 1)</label>'
    + '<input id="carrusel-titulo" class="input-field" maxlength="90" value="' + escHtml(t.titulo || '') + '">'
    + '<label class="control-label" for="carrusel-subtitulo">Subtítulo</label>'
    + '<textarea id="carrusel-subtitulo" class="input-field" rows="2" maxlength="140">' + escHtml(t.subtitulo || '') + '</textarea>'
    + puntos.map(function(p, i) {
        return '<label class="control-label" for="carrusel-punto-' + i + '">Punto ' + (i + 1) + ' (diapositiva 2)</label>'
          + '<textarea id="carrusel-punto-' + i + '" class="input-field" rows="2" maxlength="110">' + escHtml(p) + '</textarea>';
      }).join('')
    + '<label class="control-label" for="carrusel-cta">Llamada a la acción (diapositiva 3)</label>'
    + '<input id="carrusel-cta" class="input-field" maxlength="70" value="' + escHtml(t.cta || '') + '">'
    + '<p class="revision-sub">Al guardar se redibuja solo la diapositiva cuyo texto cambiaste.</p>'
    + '<button type="button" class="btn btn-primary" id="btn-carrusel-guardar" onclick="guardarTextosCarrusel()">Guardar y redibujar</button>'
    + '</details>';
}

function igActual() {
  var p = $('ig-pista');
  return p ? Math.round(p.scrollLeft / Math.max(1, p.clientWidth)) : 0;
}

function igIr(i, suave) {
  var p = $('ig-pista');
  if (!p) return;
  var total = p.children.length;
  i = Math.max(0, Math.min(total - 1, i));
  p.scrollTo({ left: i * p.clientWidth, behavior: suave === false ? 'auto' : 'smooth' });
}

function igMover(paso) { igIr(igActual() + paso); }

function igTecla(ev) {
  if (ev.key === 'ArrowRight') { ev.preventDefault(); igMover(1); }
  if (ev.key === 'ArrowLeft') { ev.preventDefault(); igMover(-1); }
}

function igAlDeslizar() {
  var p = $('ig-pista');
  if (!p) return;
  var i = igActual(), total = p.children.length;
  $('ig-contador').textContent = (i + 1) + '/' + total;
  Array.from($('ig-puntos').children).forEach(function(el, k) { el.classList.toggle('activo', k === i); });
  $('ig-ant').hidden = i === 0;
  $('ig-sig').hidden = i === total - 1;
}

function verCarrusel(cod) {
  _carruselVista = cod;
  var cont = $('carrusel-cuerpo');
  if (cont && cont._nota) llenarCarrusel(cont._nota);
}

async function _seguirCarrusel(ruta, body, btn, enCurso) {
  var st = $('carrusel-estado'), id = _notaActual && _notaActual.id;
  if (!id) return;
  setBtnLoading(btn, true);
  st.className = 'feedback info';
  st.textContent = enCurso;
  var errores = [];
  try {
    var fin = await correrEnCola(ruta, body, function(l) {
      if (l.indexOf('[ERROR]') >= 0 || l.indexOf('[AVISO]') >= 0) errores.push(l.replace(/.*\[(ERROR|AVISO)\]\s*/, '').trim());
      else if (/Escribiendo|Dibujando/.test(l)) st.textContent = l.trim();
    }, function(d) {
      var t = textoEnCola(d);
      if (t) st.textContent = 'Hay otra tarea en curso: el carrusel quedó ' + t.toLowerCase().replace('…', '') + '.';
    });
    var d = await pedir('/api/fase2/notas/' + id);
    if (!_notaActual || _notaActual.id !== id) return;
    llenarCarrusel(d.nota);
    st = $('carrusel-estado');
    if (fin.estado !== 'ok') { st.className = 'feedback err'; st.textContent = errores.join(' ') || 'No se pudo armar el carrusel.'; return; }
    st.className = errores.length ? 'feedback info' : 'feedback ok';
    st.textContent = errores.length ? 'Listo, con avisos: ' + errores.join(' ') : 'Listo.';
    showToast('Carrusel listo', 'success');
  } catch (e) {
    if ($('carrusel-estado')) { $('carrusel-estado').className = 'feedback err'; $('carrusel-estado').textContent = e.message; }
  } finally {
    if (btn && btn.isConnected) setBtnLoading(btn, false);
  }
}

async function crearCarrusel(idiomas) {
  var btn = idiomas ? $('btn-carrusel-faltan') : $('btn-carrusel-crear');
  if (!idiomas && $('carrusel-titulo')) {
    var ok = await confirmar({ titulo: '¿Volver a crear los 3 carruseles?', mensaje: 'La IA escribe textos nuevos en los 3 idiomas y se pierden los que editaste.', accion: 'Crear de nuevo' });
    if (!ok) return;
  }
  await _seguirCarrusel('/api/carrusel/' + encodeURIComponent(_notaActual.id), idiomas ? { idiomas: idiomas } : {},
                        btn, 'Armando los carruseles…');
}

async function guardarTextosCarrusel() {
  var body = {
    idioma: _carruselVista,
    titulo: $('carrusel-titulo').value.trim(),
    subtitulo: $('carrusel-subtitulo').value.trim(),
    puntos: [0, 1, 2].map(function(i) { return $('carrusel-punto-' + i).value.trim(); }).filter(Boolean),
    cta: $('carrusel-cta').value.trim()
  };
  var st = $('carrusel-estado');
  if (!body.titulo || !body.puntos.length) {
    st.className = 'feedback err';
    st.textContent = 'Hacen falta el título y al menos un punto.';
    return;
  }
  // Cuáles cambian (igual que carrusel.diapositivas_cambiadas en el servidor): 1 título y subtítulo, 2 puntos, 3 llamada a la acción.
  var cont = $('carrusel-cuerpo'), antes = ((carruselesDe(cont._nota)[_carruselVista] || {}).textos) || {};
  var cambian = [];
  if ((antes.titulo || '') !== body.titulo || (antes.subtitulo || '') !== body.subtitulo) cambian.push(1);
  if (JSON.stringify(antes.puntos || []) !== JSON.stringify(body.puntos)) cambian.push(2);
  if ((antes.cta || '') !== body.cta) cambian.push(3);
  if (!cambian.length) { st.className = 'feedback info'; st.textContent = 'No cambiaste ningún texto.'; return; }
  _carruselIr = cambian[0] - 1;
  await _seguirCarrusel('/api/carrusel/' + encodeURIComponent(_notaActual.id) + '/textos', body, $('btn-carrusel-guardar'),
                        cambian.length === 1 ? 'Redibujando la diapositiva ' + cambian[0] + '…'
                                             : 'Redibujando las diapositivas ' + cambian.join(' y ') + '…');
}
