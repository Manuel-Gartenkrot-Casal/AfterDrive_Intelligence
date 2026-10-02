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
 * Lo que no debe traducirse (marca, nombres de proveedores, la consola
 * técnica) lleva translate="no" en el HTML.
 */
(function () {
  'use strict';

  const DESTINO = 'pt';
  const COOKIE = 'googtrans';
  const SCRIPT = 'https://translate.google.com/translate_a/element.js?cb=__traductorListo';
  const ESPERA_MS = 10000;

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

  let cargaEnCurso = null;

  function cargarWidget() {
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
          combo.value = idioma;
          combo.dispatchEvent(new Event('change'));
          return resolver();
        }
        if (Date.now() - inicio > ESPERA_MS) return rechazar(new Error('el traductor no respondió'));
        setTimeout(intentar, 150);
      })();
    });
  }

  async function aPortugues() {
    if (enPortugues()) return;
    marcarBotones(DESTINO, true);
    escribirCookie('/es/' + DESTINO);
    try {
      await cargarWidget();
      await aplicarIdioma(DESTINO);
      marcarBotones(DESTINO);
    } catch (e) {
      borrarCookie();
      marcarBotones('es');
      window.showToast?.('No se pudo traducir la página: ' + e.message + '. Revisá la conexión a internet.', 'error');
    }
  }

  function aEspanol() {
    if (!enPortugues()) return;
    marcarBotones('es', true);
    borrarCookie();
    location.reload();
  }

  function iniciar() {
    const control = $('langToggle');
    if (!control) return;
    control.querySelector('[data-idioma="es"]').addEventListener('click', aEspanol);
    control.querySelector('[data-idioma="' + DESTINO + '"]').addEventListener('click', aPortugues);

    if (enPortugues()) {
      // Volver a abrir en portugués: con la cookie puesta, el widget traduce
      // solo al cargar.
      marcarBotones(DESTINO, true);
      cargarWidget()
        .then(() => marcarBotones(DESTINO))
        .catch(e => {
          borrarCookie();
          marcarBotones('es');
          window.showToast?.('No se pudo cargar el traductor: ' + e.message + '.', 'error');
        });
    } else {
      marcarBotones('es');
    }
  }

  iniciar();
})();
