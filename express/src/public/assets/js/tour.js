/* tour.js — Recorrido guiado por el dashboard y menú de Ayuda.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html.

   Se abre solo la primera vez que alguien entra desde un navegador
   (localStorage "ad-tour-visto") y se repite desde Ayuda → Repetir el tutorial.
   Cada paso lleva a su sección y resalta un elemento real de la pantalla. Un
   paso cuyo elemento no se ve (por ejemplo, lo de la vista Desarrollador
   estando en Cliente) se saltea. */

var PASOS_TOUR = [
  { titulo: 'Bienvenido a AfterDrive Intelligence',
    texto: 'El sistema busca noticias del sector autopartes, las filtra con IA y escribe notas para el blog. En un par de minutos te muestro cada parte. Podés salir cuando quieras con Esc o con "Saltar".' },
  { el: '.nav-lista', titulo: 'Las secciones',
    texto: 'Desde acá vas a Inicio, Crear nota, Historial, Programación, Fuentes y Corridas. Los números en rojo marcan lo que espera tu atención.' },
  { seccion: 'inicio', el: '.hero-kpis', titulo: 'Tu mesa editorial',
    texto: 'Las notas que esperan tu revisión, las noticias listas para usar, las fuentes activas y cuándo sale la próxima nota automática. Tocá cualquiera para ir directo.' },
  { seccion: 'inicio', el: '.inicio-trabajo', titulo: 'Para revisar y actividad',
    texto: 'A la izquierda, las notas que esperan que las leas. A la derecha, lo que el sistema está haciendo ahora.' },
  { seccion: 'crear', el: '.f2-categorias', titulo: 'Crear una nota: el tema',
    texto: 'Elegí una o más categorías: son el tema de la nota. Las noticias de contexto se eligen según lo que marques.' },
  { seccion: 'crear', el: '.f2-opciones', titulo: 'Tono, largo y tema puntual',
    texto: 'El tono (comercial, analítico, periodístico…), el largo aproximado y, si querés, un tema puntual. Con "Puntapié" la nota lleva al lector a un link tuyo.' },
  { seccion: 'crear', el: ['#btn-mas-opciones', '.f2-regiones'], titulo: 'Regiones y clientes',
    texto: 'La región define el idioma y el mercado: con Brasil la nota sale en portugués. También podés sumar clientes para mencionarlos como casos reales.' },
  { seccion: 'crear', el: '#btn-f2-generar', titulo: 'Generar la nota',
    texto: 'La nota se planifica, se escribe, se verifican sus datos contra las noticias y se revisan estilo y SEO; si algo falla, se corrige sola. Tarda unos minutos y queda en Historial para revisar. "Guardar cambios" deja esta configuración para la nota automática.' },
  { seccion: 'historial', el: '#hist-pestanas', titulo: 'Historial',
    texto: 'Las notas generadas y las descartadas, y las noticias que el sistema guardó o descartó, cada una con su motivo.' },
  { seccion: 'historial', el: '#hist-lista', titulo: 'Revisar una nota',
    texto: 'Abrí una nota para leerla y ver qué datos están respaldados por las noticias, cuánto costó y su imagen. Desde ahí la calificás, la editás, la aprobás o la rechazás, generás su imagen y la publicás en HubSpot.' },
  { seccion: 'historial', el: '#calibracion-panel', titulo: 'Cómo aprende la generación',
    texto: 'Cuando calificás, rechazás o editás una nota, las próximas lo tienen en cuenta. Acá ves qué aprendió el sistema y cómo te va por tono y por proveedor.' },
  { seccion: 'programacion', el: '.agenda-grid', titulo: 'Programación',
    texto: 'A qué hora y cada cuántos días se buscan noticias y se escribe la nota automática. Los cambios se aplican al guardar.' },
  { seccion: 'fuentes', el: '#fuentes-grupo', titulo: 'Fuentes de noticias',
    texto: 'Los sitios que se revisan. Podés pausarlos, agregar uno directo, probarlo antes de sumarlo o pedir recomendaciones de sitios del sector.' },
  { seccion: 'corridas', el: '.corridas-seccion', titulo: 'Corridas',
    texto: 'Lo que el sistema está ejecutando y lo que espera su turno, con el registro de cada paso. Corre una cosa a la vez: lo que pidas mientras tanto queda en cola.' },
  { el: '#modo-pago', titulo: 'API paga',
    texto: 'Pone todo el pipeline en el proveedor pago por 24 horas como máximo: más calidad, pero cuesta dinero. Pide confirmación y se apaga solo.' },
  { el: '.sidebar-pie .modo-switch', titulo: 'Vista Cliente o Desarrollador',
    texto: 'Cliente muestra lo esencial. Desarrollador suma la consola, las estadísticas y la elección del proveedor de IA.' },
  { el: '#providerToggle', soloDev: true, titulo: 'Proveedor de IA',
    texto: 'Qué IA escribe y revisa las notas. Lo usa todo el pipeline, salvo mientras la API paga esté prendida.' },
  { el: '.header-right', titulo: 'Estado, tema y sesión',
    texto: 'Si el sistema está en línea, el tema claro u oscuro y el botón para cerrar sesión.' },
  { el: '#ayuda-btn', titulo: 'Ayuda',
    texto: 'Cuando quieras, desde acá repetís este recorrido o abrís la documentación.' },
  { titulo: 'Listo',
    texto: 'Ya conocés todo. Un buen primer paso: andá a Crear nota, elegí una categoría y generá tu primera nota.' }
];

var _tour = { i: 0, activo: false, previo: null, capa: null, foco: null, globo: null, pasos: [] };
var CLAVE_TOUR = 'ad-tour-visto';

function tourVisto() {
  try { return localStorage.getItem(CLAVE_TOUR) === '1'; } catch (e) { return true; }
}

function _visible(el) {
  if (!el) return false;
  var r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
}

function _elementoDe(paso) {
  var sels = Array.isArray(paso.el) ? paso.el : [paso.el];
  for (var i = 0; i < sels.length; i++) {
    var el = document.querySelector(sels[i]);
    if (_visible(el)) return el;
  }
  return null;
}

function iniciarTour() {
  cerrarMenuAyuda();
  if (_tour.activo) return;
  _tour.activo = true;
  _tour.previo = document.activeElement;
  // Los pasos de la vista Desarrollador no cuentan en la vista Cliente (ni en el "Paso N de M").
  var dev = document.documentElement.getAttribute('data-modo') === 'dev';
  _tour.pasos = PASOS_TOUR.filter(function(p) { return dev || !p.soloDev; });
  var capa = document.createElement('div');
  capa.className = 'tour-capa';
  var foco = document.createElement('div');
  foco.className = 'tour-foco';
  var globo = document.createElement('div');
  globo.className = 'tour-globo';
  globo.setAttribute('role', 'dialog');
  globo.setAttribute('aria-modal', 'true');
  globo.setAttribute('aria-labelledby', 'tour-titulo');
  globo.setAttribute('aria-describedby', 'tour-texto');
  globo.innerHTML = '<div class="tour-paso" id="tour-paso"></div>'
    + '<h2 class="tour-titulo" id="tour-titulo"></h2>'
    + '<p class="tour-texto" id="tour-texto"></p>'
    + '<div class="tour-idioma" id="tour-idioma"><span>Idioma</span>' + htmlSelectorIdioma() + '</div>'
    + '<div class="tour-progreso" aria-hidden="true"><i id="tour-barra"></i></div>'
    + '<div class="tour-acciones">'
    + '<button type="button" class="btn btn-xs tour-saltar" id="tour-saltar">Saltar</button>'
    + '<span class="tour-espacio"></span>'
    + '<button type="button" class="btn btn-xs" id="tour-anterior">Anterior</button>'
    + '<button type="button" class="btn btn-xs btn-primary" id="tour-siguiente">Siguiente</button>'
    + '</div>';
  document.body.append(capa, foco, globo);
  _tour.capa = capa; _tour.foco = foco; _tour.globo = globo;
  $('tour-saltar').onclick = function() { terminarTour(); };
  $('tour-anterior').onclick = function() { irAPasoTour(_tour.i - 1, -1); };
  $('tour-siguiente').onclick = function() { irAPasoTour(_tour.i + 1, 1); };
  capa.onclick = function() { $('tour-siguiente').focus(); };   // el click afuera no hace nada raro
  document.addEventListener('keydown', _teclaTour, true);
  window.addEventListener('resize', _ubicarTour);
  window.addEventListener('scroll', _ubicarTour, true);
  document.body.classList.add('tour-abierto');
  irAPasoTour(0, 1);
}

async function irAPasoTour(i, sentido) {
  if (i < 0) i = 0;
  if (i >= _tour.pasos.length) { terminarTour(); return; }
  var paso = _tour.pasos[i];
  if (paso.seccion && typeof irASeccion === 'function') await irASeccion(paso.seccion);
  if (!_tour.activo) return;
  var el = paso.el ? _elementoDe(paso) : null;
  if (paso.el && !el) {   // no está en esta vista: el siguiente en la misma dirección
    if (i + sentido < 0) return irAPasoTour(i + 1, 1);
    return irAPasoTour(i + sentido, sentido);
  }
  _tour.i = i;
  _tour.el = el;
  $('tour-paso').textContent = 'Paso ' + (i + 1) + ' de ' + _tour.pasos.length;
  $('tour-titulo').textContent = paso.titulo;
  $('tour-texto').textContent = paso.texto;
  $('tour-barra').style.width = ((i + 1) / _tour.pasos.length * 100) + '%';
  $('tour-anterior').disabled = i === 0;
  // El idioma se elige en la bienvenida, antes de que empiece el recorrido.
  $('tour-idioma').hidden = i !== 0;
  pintarSelectorIdioma();
  $('tour-siguiente').textContent = i === _tour.pasos.length - 1 ? 'Terminar' : 'Siguiente';
  // En el celular el globo va abajo de todo: el elemento, arriba, para que no lo tape.
  if (el) el.scrollIntoView({ block: window.innerWidth <= 640 ? 'start' : 'center', behavior: 'auto' });
  _ubicarTour();
  $('tour-siguiente').focus();
}

function _ubicarTour() {
  if (!_tour.activo) return;
  var globo = _tour.globo, foco = _tour.foco, el = _tour.el;
  var vw = window.innerWidth, vh = window.innerHeight, m = 12;
  globo.classList.toggle('centrado', !el);
  if (!el) {
    foco.style.display = 'none';
    _tour.capa.classList.add('oscura');
    globo.style.left = globo.style.top = '';
    return;
  }
  _tour.capa.classList.remove('oscura');
  var r = el.getBoundingClientRect(), p = 6;
  foco.style.display = 'block';
  foco.style.left = (r.left - p) + 'px';
  foco.style.top = (r.top - p) + 'px';
  foco.style.width = (r.width + 2 * p) + 'px';
  foco.style.height = (r.height + 2 * p) + 'px';
  if (vw <= 640) { globo.style.left = globo.style.top = ''; return; }   // en el celular, abajo de todo (CSS)
  var g = globo.getBoundingClientRect();
  var top = r.bottom + m + p, left = r.left;
  if (top + g.height > vh - m) top = r.top - g.height - m - p;          // no entra abajo: arriba
  if (top < m) {                                                         // tampoco arriba: al costado
    top = Math.min(Math.max(m, r.top), vh - g.height - m);
    left = r.right + m + p;
    if (left + g.width > vw - m) left = r.left - g.width - m - p;
  }
  left = Math.min(Math.max(m, left), vw - g.width - m);
  globo.style.left = left + 'px';
  globo.style.top = Math.max(m, top) + 'px';
}

function _teclaTour(ev) {
  if (!_tour.activo) return;
  if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); terminarTour(); }
  else if (ev.key === 'ArrowRight') { ev.preventDefault(); irAPasoTour(_tour.i + 1, 1); }
  else if (ev.key === 'ArrowLeft') { ev.preventDefault(); irAPasoTour(_tour.i - 1, -1); }
  else if (ev.key === 'Tab') {   // el foco no sale del globo
    var botones = Array.from(_tour.globo.querySelectorAll('button:not([disabled])'));
    var i = botones.indexOf(document.activeElement);
    ev.preventDefault();
    botones[(i + (ev.shiftKey ? -1 : 1) + botones.length) % botones.length].focus();
  }
}

function terminarTour() {
  if (!_tour.activo) return;
  _tour.activo = false;
  try { localStorage.setItem(CLAVE_TOUR, '1'); } catch (e) {}
  document.removeEventListener('keydown', _teclaTour, true);
  window.removeEventListener('resize', _ubicarTour);
  window.removeEventListener('scroll', _ubicarTour, true);
  [_tour.capa, _tour.foco, _tour.globo].forEach(function(n) { if (n) n.remove(); });
  document.body.classList.remove('tour-abierto');
  var volver = _tour.previo && document.contains(_tour.previo) ? _tour.previo : $('ayuda-btn');
  if (volver) volver.focus();
}

/* La primera vez, el recorrido arranca solo (después de que cargue el dashboard). */
function tourSiEsLaPrimeraVez() {
  if (!tourVisto()) setTimeout(iniciarTour, 600);
}

/* ═══════════════════════════════════════════════════════════════════════
   MENÚ DE AYUDA (al pie de la barra lateral)
   ═══════════════════════════════════════════════════════════════════════ */
function toggleMenuAyuda() {
  var menu = $('ayuda-menu'), abierto = menu.hidden;
  menu.hidden = !abierto;
  $('ayuda-btn').setAttribute('aria-expanded', abierto);
  if (abierto) {
    menu.querySelector('[role="menuitem"]').focus();
    setTimeout(function() { document.addEventListener('click', _clickFueraAyuda); }, 0);
  } else {
    document.removeEventListener('click', _clickFueraAyuda);
  }
}

function cerrarMenuAyuda(devolverFoco) {
  var menu = $('ayuda-menu');
  if (!menu || menu.hidden) return;
  menu.hidden = true;
  $('ayuda-btn').setAttribute('aria-expanded', 'false');
  document.removeEventListener('click', _clickFueraAyuda);
  if (devolverFoco) $('ayuda-btn').focus();
}

function _clickFueraAyuda(ev) {
  if (!ev.target.closest('.sidebar-ayuda')) cerrarMenuAyuda();
}

function initAyuda() {
  $('ayuda-menu').addEventListener('keydown', function(ev) {
    var items = Array.from(this.querySelectorAll('[role="menuitem"]')), i = items.indexOf(document.activeElement);
    if (ev.key === 'Escape') { ev.preventDefault(); cerrarMenuAyuda(true); }
    else if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      items[(i + (ev.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
    }
  });
  tourSiEsLaPrimeraVez();
}
