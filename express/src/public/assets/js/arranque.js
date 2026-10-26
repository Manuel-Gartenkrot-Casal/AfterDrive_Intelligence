/* arranque.js — Arranque del dashboard.
   Parte del dashboard (index.html): scripts clásicos que comparten el ámbito
   global y se cargan en orden; ver el final de index.html. */

/* ═══════════════════════════════════════════════════════════════════════
   BOOT SEQUENCE
   ═══════════════════════════════════════════════════════════════════════ */
window.onload = function() {
  initIdioma();   // primero: lo que pinta el resto se traduce al aparecer
  $('statusText').textContent = 'Conectando...';
  initParticles();

  setTimeout(function() { log('Inicializando agentes...', 'info'); }, 200);
  setTimeout(function() { log('Handshake con backend...', 'info'); }, 600);

  updateStats();
  checkProviders();
  checkBlogPruebas();
  checkAprobacionAuto();
  setModo(document.documentElement.getAttribute('data-modo'));
  initFormularios();
  initSecciones();
  initCorridas();
  initHistorial();
  cargarEstadoHubspot();
  initAgenda();
  fase2Init();
  cargarUltimaNota();
  loadTrustedUrls();
  loadSugerencias();

  setTimeout(function() {
    log('Sistema operativo. Command Center activo.', 'success');
  }, 1200);

  setInterval(updateStats, 15000);
  initVivo();   // lo que se mira se actualiza solo (vivo.js)
  initAyuda();   // y, la primera vez, el recorrido guiado
};
