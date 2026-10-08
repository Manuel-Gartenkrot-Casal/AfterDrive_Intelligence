/* Loaded before any dashboard request. The server remains the authority. */
(() => {
  const originalFetch = window.fetch.bind(window);
  let leaving = false;
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const url = new URL(args[0] instanceof Request ? args[0].url : args[0], location.href);
    if (url.origin === location.origin && response.status === 401 && !leaving) {
      leaving = true;
      location.replace('/');
    }
    return response;
  };
  // A back/forward-cache restoration must recheck the server session.
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('session-exit');
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const response = await originalFetch('/api/logout', {method:'POST'});
        if (!response.ok && response.status !== 401) throw new Error('logout');
        location.replace('/');
      } catch {
        button.disabled = false;
        window.showToast('No se pudo cerrar la sesión. Reintentá.', 'error');
      }
    });
  });
})();
