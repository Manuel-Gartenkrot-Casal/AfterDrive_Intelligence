/* Traductor de la página completa (español <-> portugués).
 *
 * Usa el widget de Google Translate: traduce también el contenido que llega
 * de la base (artículos, notas), no solo los textos fijos, y sigue
 * traduciendo lo que se agrega después (listas que cargan por fetch).
 *
 * Cómo funciona:
 *   - La elección vive en la cookie 'googtrans' (=/es/pt), que es la que lee
 *     el widget de Google: al recargar, la página vuelve a abrir en portugués.
 *   - Pasar a portugués no recarga: se carga el script y se aplica.
 *   - Volver a español sí recarga: la traducción reescribe el DOM y la única
 *     forma confiable de recuperar el texto original es volver a pedirlo.
 *
 * Mientras Google traduce, la página queda tapada (clase html.traduciendo)
 * para que no se vea un instante en español. Si la página abre ya en
 * portugués, el script del <head> la tapa antes de dibujarla. Siempre hay un
 * tope de tiempo: nunca puede quedar tapada si Google tarda o no responde.
 *
 * Lo que no debe traducirse (marca, proveedores, consola, contadores) lleva
 * translate="no" en el HTML.
 */
(function () {
  'use strict';

  const DESTINO = 'pt';
  const COOKIE = 'googtrans';
  const SCRIPT = 'https://translate.google.com/translate_a/element.js?cb=__traductorListo';
  const ESPERA_MS = 10000;      // carga del script de Google
  const TAPADO_MAX_MS = 6000;   // nunca tapar la página más que esto
  const ASENTAR_MS = 350;       // Google traduce por tandas: margen tras la primera

  const html = document.documentElement;
  const $ = id => document.getElementById(id);

  function leerCookie() {
    const m = document.cookie.match(/(?:^|;\s*)googtrans=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function escribirCookie(valor) {
    document.cookie = `${COOKIE}=${valor}; path=/; SameSite=Lax`;
  }

  function borrarCookie() {
    // Google la puede escribir con y sin dominio explícito: hay que borrar ambas.
    const vencida = 'expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
    document.cookie = `${COOKIE}=; ${vencida}`;
    document.cookie = `${COOKIE}=; ${vencida}; domain=${location.hostname}`;
    document.cookie = `${COOKIE}=; ${vencida}; domain=.${location.hostname}`;
  }

  const enPortugues = () => leerCookie().endsWith('/' + DESTINO);

  function marcarBotones(idioma, cargando = false) {
    document.querySelectorAll('[data-idioma]').forEach(b => {
      const activo = b.dataset.idioma === idioma;
      b.classList.toggle('active', activo);
      b.setAttribute('aria-pressed', String(activo));
      b.disabled = cargando;
    });
    $('langToggle')?.setAttribute('aria-busy', String(cargando));
  }

  // ── Tapar / destapar ──────────────────────────────────────────────────────
  const tapar = () => html.classList.add('traduciendo');
  const destapar = () => html.classList.remove('traduciendo');
  const traducida = () => html.classList.contains('translated-ltr') || html.classList.contains('translated-rtl');

  // Google marca el <html> con 'translated-ltr' cuando aplica una traducción.
  // Se espera esa marca (más un margen para las tandas siguientes) o el tope.
  function esperarTraduccion() {
    return new Promise(resolver => {
      let listo = false;
      const terminar = () => {
        if (listo) return;
        listo = true;
        observador.disconnect();
        clearTimeout(tope);
        setTimeout(resolver, ASENTAR_MS);
      };
      const observador = new MutationObserver(() => { if (traducida()) terminar(); });
      observador.observe(html, {attributes: true, attributeFilter: ['class']});
      const tope = setTimeout(() => { listo = true; observador.disconnect(); resolver(); }, TAPADO_MAX_MS);
      if (traducida()) terminar();
    });
  }

  // ── UI propia de Google ─────────────────────────────────────────────────
  // Google agrega al <body> su barra, un spinner (que reaparece cada vez que
  // retraduce algo, o sea seguido en un dashboard que se actualiza solo) y un
  // tooltip. Sus clases son ofuscadas y cambian: se ocultan por estructura.
  function esUiDeGoogle(nodo) {
    if (nodo.nodeType !== 1 || nodo.id === 'google_translate_element') return false;
    if (!['DIV', 'IFRAME'].includes(nodo.tagName)) return false;
    const clase = typeof nodo.className === 'string' ? nodo.className : '';
    return /(^|\s)(VIpgJd-|goog-te|skiptranslate)/.test(clase) || nodo.id === 'goog-gt-tt';
  }
  const ocultar = nodo => nodo.style.setProperty('display', 'none', 'important');

  let vigilandoGoogle = false;
  function vigilarUiDeGoogle() {
    if (vigilandoGoogle) return;
    vigilandoGoogle = true;
    [...document.body.children].filter(esUiDeGoogle).forEach(ocultar);
    new MutationObserver(cambios => {
      for (const c of cambios) c.addedNodes.forEach(n => { if (esUiDeGoogle(n)) ocultar(n); });
    }).observe(document.body, {childList: true});
  }

  // ── Carga del widget ──────────────────────────────────────────────────────
  let cargaEnCurso = null;

  function cargarWidget() {
    vigilarUiDeGoogle();
    if (window.google?.translate?.TranslateElement) return Promise.resolve();
    if (cargaEnCurso) return cargaEnCurso;
    cargaEnCurso = new Promise((resolver, rechazar) => {
      const vencimiento = setTimeout(() => rechazar(new Error('tiempo de espera agotado')), ESPERA_MS);
      window.__traductorListo = () => {
        clearTimeout(vencimiento);
        try {
          new window.google.translate.TranslateElement(
            {pageLanguage: 'es', includedLanguages: DESTINO, autoDisplay: false},
            'google_translate_element');
          resolver();
        } catch (e) {
          rechazar(e);
        }
      };
      const s = document.createElement('script');
      s.src = SCRIPT;
      s.async = true;
      s.onerror = () => { clearTimeout(vencimiento); rechazar(new Error('no se pudo descargar el traductor')); };
      document.head.append(s);
    }).catch(e => { cargaEnCurso = null; throw e; });
    return cargaEnCurso;
  }

  // El widget crea un <select class="goog-te-combo"> de forma asíncrona;
  // elegir el idioma ahí es lo que dispara la traducción sin recargar.
  function aplicarIdioma(idioma) {
    return new Promise((resolver, rechazar) => {
      const inicio = Date.now();
      (function intentar() {
        const combo = document.querySelector('.goog-te-combo');
        if (combo) {
          if (combo.value !== idioma) {
            combo.value = idioma;
            combo.dispatchEvent(new Event('change'));
          }
          return resolver();
        }
        if (Date.now() - inicio > ESPERA_MS) return rechazar(new Error('el traductor no respondió'));
        setTimeout(intentar, 150);
      })();
    });
  }

  function fallo(prefijo, e) {
    borrarCookie();
    destapar();
    marcarBotones('es');
    window.showToast?.(`${prefijo}: ${e.message}. Revisá la conexión a internet.`, 'error');
  }

  async function aPortugues() {
    if (enPortugues()) return;
    marcarBotones(DESTINO, true);
    escribirCookie('/es/' + DESTINO);
    tapar();
    try {
      await cargarWidget();
      await aplicarIdioma(DESTINO);
      await esperarTraduccion();
      destapar();
      marcarBotones(DESTINO);
    } catch (e) {
      fallo('No se pudo traducir la página', e);
    }
  }

  function aEspanol() {
    if (!enPortugues()) return;
    marcarBotones('es', true);
    borrarCookie();
    location.reload();
  }

  async function reabrirEnPortugues() {
    // El <head> ya tapó la página. Con la cookie puesta Google traduce solo al
    // iniciar; se elige el idioma igual por si no lo hiciera.
    marcarBotones(DESTINO, true);
    try {
      await cargarWidget();
      await aplicarIdioma(DESTINO).catch(() => {});
      await esperarTraduccion();
      destapar();
      marcarBotones(DESTINO);
    } catch (e) {
      fallo('No se pudo cargar el traductor', e);
    }
  }

  function iniciar() {
    const control = $('langToggle');
    if (!control) { destapar(); return; }
    control.querySelector('[data-idioma="es"]').addEventListener('click', aEspanol);
    control.querySelector('[data-idioma="' + DESTINO + '"]').addEventListener('click', aPortugues);

    if (enPortugues()) reabrirEnPortugues();
    else { destapar(); marcarBotones('es'); }
  }

  iniciar();
})();
