/* carrusel.js — Carrusel para redes de una nota (paso Publicar de la revisión).
   3 imágenes de 1080×1350 para Instagram y un PDF para LinkedIn. Los arma la Cola
   (afterdrive/carrusel.py); acá se piden, se editan los textos y se descargan.
   No publica en ninguna red. Parte del dashboard: ver el final de index.html. */

function idiomasCarrusel(nota) {
  var lista = [nota.idioma || 'pt'];
  Object.keys(nota.traducciones || {}).forEach(function(cod) {
    var t = nota.traducciones[cod];
    if (t && t.contenido && lista.indexOf(cod) < 0) lista.push(cod);
  });
  return lista;
}

function pintarCarrusel(nota, panel) {
  var viejo = $('bloque-carrusel');
  var bloque = bloqueRevision('Carrusel para redes', '<div id="carrusel-cuerpo"></div>', 'bloque-carrusel');
  bloque.id = 'bloque-carrusel';
  if (viejo) viejo.replaceWith(bloque); else panel.appendChild(bloque);
  llenarCarrusel(nota);
}

function llenarCarrusel(nota) {
  var cont = $('carrusel-cuerpo');
  if (!cont) return;
  var c = nota.carrusel || null, idiomas = idiomasCarrusel(nota);
  var actual = (c && c.idioma) || nota.idioma || 'pt';
  var html = '<p class="revision-sub">Tres imágenes de 1080×1350 para Instagram y un PDF para LinkedIn, con los textos que arma la IA a partir de la nota. Se descargan para publicarlas: no se suben solas.</p>'
    + '<div class="carrusel-fila">'
    + '<label class="control-label" for="carrusel-idioma">Idioma</label>'
    + '<select id="carrusel-idioma" class="select-field">'
    + idiomas.map(function(cod) {
        return '<option value="' + cod + '"' + (cod === actual ? ' selected' : '') + '>' + escHtml(NOMBRE_IDIOMA[cod] || cod) + '</option>';
      }).join('')
    + '</select>'
    + '<button type="button" class="btn' + (c ? '' : ' btn-primary') + '" id="btn-carrusel-crear" onclick="crearCarrusel()">'
    + (c ? 'Volver a crear con IA' : 'Crear carrusel') + '</button></div>'
    + '<p class="feedback" id="carrusel-estado" role="status" aria-live="polite"></p>';
  if (c && (c.diapositivas || []).length) {
    html += '<div class="carrusel-tira">' + c.diapositivas.map(function(url, i) {
        var src = urlSegura(url) + '?v=' + encodeURIComponent(c.generado_en || '');
        return '<figure><a href="' + src + '" target="_blank" rel="noopener"><img src="' + src + '" alt="Diapositiva ' + (i + 1) + ' del carrusel" loading="lazy"></a>'
          + '<figcaption><a href="' + src + '" download="carrusel-' + (i + 1) + '.png">Descargar ' + (i + 1) + '</a></figcaption></figure>';
      }).join('') + '</div>'
      + '<p><a class="btn btn-sm" href="/api/carrusel/' + encodeURIComponent(nota._id) + '/pdf">Descargar PDF para LinkedIn</a></p>';
    var t = c.textos || {};
    var puntos = (t.puntos || []).concat(['', '', '']).slice(0, 3);
    html += '<details class="carrusel-textos"><summary>Editar los textos</summary>'
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
  cont.innerHTML = html;
}

async function _seguirCarrusel(ruta, body, btn, enCurso) {
  var st = $('carrusel-estado'), id = _notaActual && _notaActual.id;
  if (!id) return;
  setBtnLoading(btn, true);
  st.className = 'feedback info';
  st.textContent = enCurso;
  var error = '';
  try {
    var fin = await correrEnCola(ruta, body, function(l) {
      if (l.indexOf('[ERROR]') >= 0) error = l.replace(/.*\[ERROR\]\s*/, '').trim();
      else if (/Escribiendo|Dibujando/.test(l)) st.textContent = l.trim();
    }, function(d) {
      var t = textoEnCola(d);
      if (t) st.textContent = 'Hay otra tarea en curso: el carrusel quedó ' + t.toLowerCase().replace('…', '') + '.';
    });
    if (fin.estado !== 'ok') throw new Error(error || 'No se pudo armar el carrusel.');
    var d = await pedir('/api/fase2/notas/' + id);
    if (!_notaActual || _notaActual.id !== id) return;
    llenarCarrusel(d.nota);
    $('carrusel-estado').className = 'feedback ok';
    $('carrusel-estado').textContent = 'Carrusel listo.';
    showToast('Carrusel listo', 'success');
  } catch (e) {
    if ($('carrusel-estado')) { $('carrusel-estado').className = 'feedback err'; $('carrusel-estado').textContent = e.message; }
  } finally {
    if (btn && btn.isConnected) setBtnLoading(btn, false);
  }
}

async function crearCarrusel() {
  var btn = $('btn-carrusel-crear');
  if ($('carrusel-titulo')) {
    var ok = await confirmar({ titulo: '¿Volver a crear el carrusel?', mensaje: 'La IA escribe textos nuevos y se pierden los que editaste.', accion: 'Crear de nuevo' });
    if (!ok) return;
  }
  await _seguirCarrusel('/api/carrusel/' + encodeURIComponent(_notaActual.id), { idioma: $('carrusel-idioma').value },
                        btn, 'Armando el carrusel…');
}

async function guardarTextosCarrusel() {
  var body = {
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
