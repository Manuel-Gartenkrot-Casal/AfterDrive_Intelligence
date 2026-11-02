/* carrusel.js — Carruseles para redes de una nota, uno por idioma (paso Publicar de la revisión).
   3 imágenes de 1080×1350 para Instagram y un PDF para LinkedIn en español, portugués e
   inglés. Los arma la Cola (afterdrive/carrusel.py); acá se piden, se ven por idioma, se
   editan los textos y se descargan. Cada post de HubSpot lleva la galería de su idioma.
   No publica en redes. Parte del dashboard: ver el final de index.html. */

var IDIOMAS_CARRUSEL = ['es', 'pt', 'en'];
var _carruselVista = null;   // idioma que se está mirando

/* Los guardados por idioma; las notas de antes tenían uno solo en `carrusel`. */
function carruselesDe(nota) {
  var c = Object.assign({}, nota.carruseles || {});
  if (nota.carrusel && nota.carrusel.idioma && !c[nota.carrusel.idioma]) c[nota.carrusel.idioma] = nota.carrusel;
  return c;
}

function carruselEnPostActivo(nota) {
  if (nota.carrusel_en_post !== undefined) return nota.carrusel_en_post !== false;
  return !(nota.carrusel && nota.carrusel.en_post === false);
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
    html += '<label class="carrusel-en-post"><input type="checkbox" id="carrusel-en-post"' + (carruselEnPostActivo(nota) ? ' checked' : '')
      + ' onchange="carruselEnPost(this)"> Sumar la galería a los posts de HubSpot</label>'
      + '<p class="revision-sub">Cada post (el original y sus traducciones) lleva el carrusel de su idioma, antes de las fuentes. Se aplica al subir la nota a HubSpot (si ya está subida, volvé a subirla).</p>';
  }
  cont.innerHTML = html;
  cont._nota = nota;
}

function carruselIdiomaHtml(nota, c, cod) {
  var html = '<div class="carrusel-tira">' + (c.diapositivas || []).map(function(url, i) {
      var src = urlSegura(url) + '?v=' + encodeURIComponent(c.generado_en || '');
      return '<figure><a href="' + src + '" target="_blank" rel="noopener"><img src="' + src + '" alt="Diapositiva ' + (i + 1) + ' del carrusel" loading="lazy"></a>'
        + '<figcaption><a href="' + src + '" download="carrusel-' + cod + '-' + (i + 1) + '.png">Descargar ' + (i + 1) + '</a></figcaption></figure>';
    }).join('') + '</div>'
    + '<p><a class="btn btn-sm" href="/api/carrusel/' + encodeURIComponent(nota._id) + '/pdf?idioma=' + cod + '">Descargar PDF para LinkedIn</a></p>';
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
    + '<button type="button" class="btn btn-primary" id="btn-carrusel-guardar" onclick="guardarTextosCarrusel()">Guardar y redibujar</button>'
    + '</details>';
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
  if (!body.titulo || !body.puntos.length) {
    $('carrusel-estado').className = 'feedback err';
    $('carrusel-estado').textContent = 'Hacen falta el título y al menos un punto.';
    return;
  }
  await _seguirCarrusel('/api/carrusel/' + encodeURIComponent(_notaActual.id) + '/textos', body,
                        $('btn-carrusel-guardar'), 'Redibujando las imágenes…');
}

async function carruselEnPost(caja) {
  var activo = caja.checked;
  caja.disabled = true;
  try {
    await pedir('/api/carrusel/' + encodeURIComponent(_notaActual.id) + '/en-post', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ activo: activo })
    });
    var cont = $('carrusel-cuerpo');
    if (cont && cont._nota) cont._nota.carrusel_en_post = activo;
    showToast(activo ? 'La galería va en los posts de HubSpot' : 'Los posts de HubSpot van sin la galería', 'success');
  } catch (e) {
    caja.checked = !activo;
    showToast('No se pudo cambiar: ' + e.message, 'error');
  } finally {
    caja.disabled = false;
  }
}
