'use strict';
const form = document.getElementById('login-form');
const usuario = document.getElementById('usuario');
const password = document.getElementById('password');
const submit = document.getElementById('login-submit');
const error = document.getElementById('login-error');
const status = document.getElementById('login-status');
const visibility = document.getElementById('password-toggle');
let pending = false;

visibility.addEventListener('click', () => {
  const visible = password.type === 'password';
  password.type = visible ? 'text' : 'password';
  visibility.setAttribute('aria-pressed', String(visible));
  visibility.setAttribute('aria-label', visible ? 'Ocultar contraseña' : 'Mostrar contraseña');
  visibility.title = visibility.getAttribute('aria-label');
});
password.addEventListener('keyup', event => {
  document.getElementById('caps-warning').hidden = !event.getModifierState('CapsLock');
});
password.addEventListener('blur', () => { document.getElementById('caps-warning').hidden = true; });
[usuario, password].forEach(input => input.addEventListener('input', () => input.removeAttribute('aria-invalid')));
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (pending) return;
  error.hidden = true;
  const missing = [usuario, password].filter(input => !input.value || (input === usuario && !input.value.trim()));
  if (missing.length) {
    error.textContent = 'Completá tu usuario y contraseña para ingresar.';
    error.hidden = false;
    missing.forEach(input => input.setAttribute('aria-invalid', 'true'));
    missing[0].focus();
    return;
  }
  pending = true;
  submit.disabled = true;
  submit.setAttribute('aria-busy', 'true');
  submit.querySelector('span').textContent = 'Ingresando…';
  status.textContent = 'Verificando tus credenciales.';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch('/api/login', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({usuario:usuario.value.trim(), password:password.value}), signal:controller.signal
    });
    const data = await response.json();
    if (response.ok && data.success) { location.replace('/'); return; }
    error.textContent = response.status === 503
      ? 'El acceso todavía no está configurado. Contactá al administrador del equipo.'
      : data.error || 'No se pudo iniciar sesión. Intentá nuevamente.';
    if (response.status === 401) password.setAttribute('aria-invalid', 'true');
  } catch (failure) {
    error.textContent = failure.name === 'AbortError'
      ? 'El servidor tardó en responder. Volvé a intentar.'
      : 'No pudimos conectar con el servidor. Revisá tu conexión e intentá nuevamente.';
  } finally {
    clearTimeout(timeout);
    pending = false;
    submit.disabled = false;
    submit.removeAttribute('aria-busy');
    submit.querySelector('span').textContent = 'Ingresar al espacio editorial';
    status.textContent = '';
  }
  error.hidden = false;
});
