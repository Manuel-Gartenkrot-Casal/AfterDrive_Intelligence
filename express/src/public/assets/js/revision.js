/* revision.js — Calificación de notas, lo que se revisó al generarlas y el panel de calibración.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   CALIFICACIÓN
   Estrellas (1 a 5), etiquetas y un comentario. Lo que se califica entra en
   la próxima nota: ver afterdrive/calibracion.py.
   ═══════════════════════════════════════════════════════════════════════ */
var _cal = { catalogo: null, puntaje: 0, etiquetas: [] };

async function catalogoEtiquetas() {
  if (_cal.catalogo) return _cal.catalogo;
  try { _cal.catalogo = (await pedir('/api/calibracion')).catalogo_etiquetas; }
  catch (e) { _cal.catalogo = []; }
  return _cal.catalogo;
}

function estrellas(n) {
  return '★★★★★'.slice(0, n) + '☆☆☆☆☆'.slice(0, 5 - n);
}

async function pintarCalificacion(nota, contenedor) {
  var previa = nota.calificacion || {};
  _cal.puntaje = previa.puntaje || 0;
  _cal.etiquetas = (previa.etiquetas || []).slice();
  var catalogo = await catalogoEtiquetas();
  var caja = document.createElement('section');
  caja.className = 'calificar';
  caja.setAttribute('aria-labelledby', 'calificar-titulo');
  caja.innerHTML = '<h4 id="calificar-titulo">Tu calificación</h4>'
    + '<p class="calificar-ayuda">Enseña a la generación qué funciona y qué no.</p>'
    + '<div class="estrellas" role="radiogroup" aria-label="Calificación de 1 a 5">'
    + [1, 2, 3, 4, 5].map(function(i) {
        return '<button type="button" role="radio" class="estrella" data-n="' + i + '" aria-label="' + i + ' de 5">★</button>';
      }).join('') + '</div>'
    + '<div class="chips calificar-etiquetas" role="group" aria-label="Qué tiene">'
    + catalogo.map(function(e) {
        return '<button type="button" class="chip' + (e.negativa ? ' negativa' : '') + '" data-etiqueta="' + e.clave + '">'
          + escHtml(e.nombre) + '</button>';
      }).join('') + '</div>'
    + '<label class="sr-only" for="calificar-comentario">Comentario</label>'
    + '<textarea id="calificar-comentario" class="input-field" rows="2" maxlength="300" placeholder="Comentario (opcional): qué cambiarías o qué estuvo bien"></textarea>'
    + '<div class="calificar-pie"><button type="button" class="btn btn-xs btn-primary" id="calificar-guardar">Guardar calificación</button>'
    + '<span class="calificar-estado" id="calificar-estado" aria-live="polite"></span></div>';
  contenedor.appendChild(caja);
  $('calificar-comentario').value = previa.comentario || '';
  caja.querySelectorAll('.estrella').forEach(function(b) {
    b.onclick = function() { _cal.puntaje = +b.dataset.n; marcarCalificacion(); };
  });
  caja.querySelectorAll('[data-etiqueta]').forEach(function(b) {
    b.onclick = function() {
      var k = b.dataset.etiqueta, i = _cal.etiquetas.indexOf(k);
      if (i >= 0) _cal.etiquetas.splice(i, 1); else _cal.etiquetas.push(k);
      marcarCalificacion();
    };
  });
  $('calificar-guardar').onclick = function() { guardarCalificacion(nota); };
  if (previa.calificado_en) $('calificar-estado').textContent = 'Calificada el ' + fechaCorta(previa.calificado_en);
  marcarCalificacion();
}

function marcarCalificacion() {
  document.querySelectorAll('.calificar .estrella').forEach(function(b) {
    var n = +b.dataset.n;
    b.classList.toggle('on', n <= _cal.puntaje);
    b.setAttribute('aria-checked', n === _cal.puntaje);
  });
  document.querySelectorAll('.calificar [data-etiqueta]').forEach(function(b) {
    b.setAttribute('aria-pressed', _cal.etiquetas.indexOf(b.dataset.etiqueta) >= 0);
  });
  var g = $('calificar-guardar');
  if (g) g.disabled = !_cal.puntaje;
}

async function guardarCalificacion(nota) {
  var est = $('calificar-estado');
  try {
    var d = await pedir('/api/historial/calificacion', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ coleccion: 'notas_fase2', id: nota._id, puntaje: _cal.puntaje,
                             etiquetas: _cal.etiquetas, comentario: $('calificar-comentario').value.trim() })
    });
    nota.calificacion = d.calificacion;
    est.textContent = 'Guardada. La próxima nota la tiene en cuenta.';
    showToast('Calificación guardada', 'success');
    if (_seccion === 'historial') { cargarHistorial(_hist.pagina); cargarCalibracion(); }
  } catch (e) { est.textContent = ''; showToast(e.message, 'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════
   LO QUE SE REVISÓ AL GENERAR
   Datos contra las noticias, estilo, SEO y el plan de la nota.
   ═══════════════════════════════════════════════════════════════════════ */
function bloqueRevision(titulo, html, clase) {
  var b = document.createElement('section');
  b.className = 'revision-bloque' + (clase ? ' ' + clase : '');
  b.innerHTML = '<h4>' + escHtml(titulo) + '</h4>' + html;
  return b;
}

function lista(items, clase) {
  return '<ul class="revision-lista' + (clase ? ' ' + clase : '') + '">'
    + items.map(function(x) { return '<li>' + escHtml(x) + '</li>'; }).join('') + '</ul>';
}

var NOMBRE_TAREA = { redaccion: 'redacción', correccion: 'corrección', planificacion: 'plan', evaluacion: 'evaluación',
                     clasificacion: 'fichas', embeddings: 'vectores', general: 'otras' };

function pintarCosto(nota, contenedor) {
  var c = nota.costo;
  if (!c) return;
  var usd = function(x) { return 'USD ' + x.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 3 }); };
  var html = c.llamadas
    ? '<p><strong>' + usd(c.total_usd) + '</strong>' + (c.estimado ? ' aprox.' : '') + ' en ' + c.llamadas + ' llamadas a la API paga.</p>'
      + lista(Object.entries(c.por_tarea).sort(function(a, b) { return b[1] - a[1]; })
          .map(function(e) { return (NOMBRE_TAREA[e[0]] || e[0]) + ': ' + usd(e[1]); }), 'seo')
    : '<p class="revision-ok">Sin costo: se generó con un proveedor gratuito.</p>';
  contenedor.appendChild(bloqueRevision('Costo de esta nota', html));
}

function pintarImagen(nota, contenedor) {
  var im = nota.imagen || {}, html;
  var src = im.url || (im.generada && im.generada.id ? '/api/imagenes/' + im.generada.id : '');
  if (src) {
    html = '<img class="revision-imagen" src="' + srcImagen(src) + '" alt="' + escHtml(im.alt || '') + '">'
      + (im.generada ? '<p class="revision-sub">Generada con IA. Para cambiarla: Vista previa.</p>' : '');
  } else if (nota.imagen_error) {
    html = '<p class="revision-mal">No se pudo generar: ' + escHtml(nota.imagen_error) + '</p>'
      + '<p class="revision-sub">Podés generarla desde Vista previa.</p>';
  } else {
    html = '<p class="revision-sub">Sin imagen. Generala desde Vista previa.</p>';
  }
  contenedor.appendChild(bloqueRevision('Imagen destacada', html, nota.imagen_error && !src ? 'con-fallas' : ''));
}

function pintarRevisionNota(nota, contenedor) {
  pintarImagen(nota, contenedor);
  pintarCosto(nota, contenedor);
  var v = nota.verificacion;
  if (v && v.total !== undefined) {
    var ok = (v.respaldados || []).length, html;
    if (!v.total) html = '<p class="revision-ok">La nota no tiene cifras ni nombres para verificar.</p>';
    else {
      html = '<p class="' + ((v.sin_respaldo || []).length ? 'revision-mal' : 'revision-ok') + '">'
        + ok + ' de ' + v.total + ' datos aparecen en las noticias.</p>';
      if ((v.sin_respaldo || []).length) html += '<p class="revision-sub">Sin respaldo: revisalos antes de publicar.</p>' + lista(v.sin_respaldo, 'mal');
      if ((v.dudosos || []).length) html += '<p class="revision-sub">No se pudieron confirmar:</p>' + lista(v.dudosos, 'dudoso');
    }
    contenedor.appendChild(bloqueRevision('Datos contra las noticias', html, (v.sin_respaldo || []).length ? 'con-fallas' : ''));
  }
  if (nota.parecida_a) {
    contenedor.appendChild(bloqueRevision('Parecida a una nota reciente',
      '<p class="revision-mal">Se parece a “' + escHtml(nota.parecida_a.titulo) + '” ('
      + Math.round(nota.parecida_a.similitud * 100) + '%).</p>', 'con-fallas'));
  }
  var estilo = nota.estilo || [];
  if (nota.seo || estilo.length) {
    var s = nota.seo || {}, filas = [];
    if (s.palabra_clave) filas.push('Palabra clave: ' + s.palabra_clave);
    if (s.titulo_caracteres !== undefined) filas.push('Título: ' + s.titulo_caracteres + ' caracteres (máx. 60)');
    if (s.meta_caracteres !== undefined) filas.push('Meta description: ' + s.meta_caracteres + ' caracteres (máx. 155)');
    if (s.preguntas_frecuentes !== undefined) filas.push('Preguntas frecuentes: ' + s.preguntas_frecuentes);
    if (s.enlaces_internos !== undefined) filas.push('Enlaces a otras notas del blog: ' + s.enlaces_internos);
    var html2 = (estilo.length ? lista(estilo.map(function(h) { return h.detalle; }), 'dudoso')
                               : '<p class="revision-ok">Sin problemas de estilo detectados.</p>')
      + (filas.length ? lista(filas, 'seo') : '');
    contenedor.appendChild(bloqueRevision('Estilo y SEO', html2, estilo.some(function(h) { return h.grave; }) ? 'con-fallas' : ''));
  }
  if (nota.plan) {
    var p = nota.plan, det = document.createElement('details');
    det.className = 'revision-criterios';
    det.innerHTML = '<summary>Ver el plan de la nota</summary>'
      + (p.angulo ? '<p class="revision-sub">Ángulo: ' + escHtml(p.angulo) + '</p>' : '')
      + '<ol class="revision-lista">' + p.secciones.map(function(x) {
          return '<li>' + escHtml(x.titulo) + (x.noticias.length ? ' <small>(noticias ' + x.noticias.join(', ') + ')</small>' : '') + '</li>';
        }).join('') + '</ol>';
    contenedor.appendChild(det);
  }
}

/* ═══════════════════════════════════════════════════════════════════════
   PANEL DE CALIBRACIÓN (sección Historial)
   ═══════════════════════════════════════════════════════════════════════ */
async function cargarCalibracion() {
  var panel = $('calibracion-cuerpo'), resumen = $('calibracion-resumen');
  if (!panel) return;
  var d;
  try { d = await pedir('/api/calibracion'); }
  catch (e) { resumen.textContent = 'No se pudo leer la calibración.'; return; }
  _cal.catalogo = d.catalogo_etiquetas;
  resumen.textContent = d.calificadas
    ? d.calificadas + (d.calificadas === 1 ? ' nota calificada' : ' notas calificadas') + ' · promedio ' + d.promedio + ' ★'
      + (d.sin_calificar ? ' · ' + d.sin_calificar + ' sin calificar' : '')
    : 'Todavía no calificaste notas. Abrí una nota y calificala: la generación aprende de eso.';
  var html = '';
  if (d.calificadas) {
    var max = Math.max.apply(null, Object.values(d.distribucion).concat([1]));
    html += '<div class="cal-col"><h4>Calificaciones</h4><div class="cal-barras">'
      + [5, 4, 3, 2, 1].map(function(i) {
          var n = d.distribucion[i] || 0;
          return '<div class="cal-barra"><span>' + i + ' ★</span><div><i style="width:' + (n / max * 100) + '%"></i></div><b>' + n + '</b></div>';
        }).join('') + '</div>';
    var grupos = function(titulo, arr) {
      return arr.length > 1 || (arr[0] && arr[0].nombre !== '—')
        ? '<p class="revision-sub">' + titulo + '</p>' + lista(arr.map(function(g) { return g.nombre + ': ' + g.promedio + ' ★ (' + g.notas + ')'; }), 'seo') : '';
    };
    html += grupos('Por estilo', d.por_persona) + grupos('Por proveedor', d.por_proveedor) + '</div>';
  }
  html += '<div class="cal-col"><h4>Lo que la próxima nota tiene en cuenta</h4>'
    + (d.reglas.length ? lista(d.reglas) : '<p class="revision-sub">Nada todavía: aparecen correcciones cuando rechazás, calificás bajo o editás notas.</p>')
    + (d.aciertos.length ? '<p class="revision-sub">Lo que el equipo valoró:</p>' + lista(d.aciertos, 'ok') : '')
    + (d.ejemplos_propios.length ? '<p class="revision-sub">Notas propias usadas como referencia:</p>'
        + lista(d.ejemplos_propios.map(function(e) { return e.titulo + ' (' + e.puntaje + ' ★)'; }), 'ok') : '')
    + '</div>';
  var ev = d.evaluador;
  html += '<div class="cal-col"><h4>Evaluador automático</h4>'
    + (ev.umbral !== null
        ? '<p>Con tus calificaciones, una nota necesita al menos <strong>' + ev.umbral + ' de 9</strong> lineamientos o se reescribe. '
          + 'Coincide con tu criterio en el ' + Math.round(ev.coincidencia * 100) + '% de las notas.</p>'
        : '<p class="revision-sub">Se calibra cuando haya ' + ev.minimo + ' notas calificadas con evaluación automática (hay ' + ev.pares + ').</p>')
    + (d.etiquetas.length ? '<p class="revision-sub">Etiquetas que se repiten (activan una regla):</p>'
        + lista(d.etiquetas.map(function(e) { return e.nombre + ' ×' + e.veces; }), 'dudoso') : '')
    + '</div>';
  panel.innerHTML = html;
}
