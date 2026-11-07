"""Fixtures e2e: servidor real en otro proceso y un navegador con sesión iniciada."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

from tests.e2e.credenciales import CLAVE, USUARIO

playwright = pytest.importorskip("playwright.sync_api")

# Si el CDN de marked/DOMPurify no responde (sin internet), versiones mínimas.
# Cuando el CDN carga, sus scripts las reemplazan.
_SIN_CDN = ("if(!window.marked)window.marked={parse:s=>'<pre>'+String(s).replace(/</g,'&lt;')+'</pre>'};"
            "if(!window.DOMPurify)window.DOMPurify={sanitize:s=>s};")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    puerto = _puerto_libre()
    # El polling llena un PIPE sin lector en Windows y bloquea los logs de Flask.
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as salida:
        proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "tests.e2e.servidor", str(puerto)],
                                stdout=salida, stderr=subprocess.STDOUT, text=True)
        url = f"http://127.0.0.1:{puerto}"
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(url + "/health", timeout=1)
                    break
                except Exception:
                    if proc.poll() is not None:
                        salida.seek(0)
                        pytest.fail("El servidor e2e no arrancó:\n" + salida.read())
                    time.sleep(0.5)
            else:
                pytest.fail("El servidor e2e no respondió a tiempo.")
            yield url
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def e2e_obligatorio() -> bool:
    """En el CI (GitHub define CI=true) o con E2E_OBLIGATORIO=1, los e2e tienen que correr."""
    return any(os.getenv(v, "").strip().lower() in ("1", "true", "yes") for v in ("E2E_OBLIGATORIO", "CI"))


def sin_navegador(motivo: str):
    """Sin Chromium: localmente se saltean; en el CI fallan. Si se salteaban ahí, el job
    quedaba en verde sin haber probado nada del dashboard."""
    if e2e_obligatorio():
        pytest.fail(f"{motivo} En el CI los e2e no se saltean.", pytrace=False)
    pytest.skip(motivo)


@pytest.fixture(scope="session")
def navegador():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=os.getenv("E2E_CHROMIUM") or None)
        except Exception as e:
            sin_navegador(f"Sin Chromium para los tests e2e ({e}). Apuntalo con E2E_CHROMIUM=/ruta/a/chromium.")
        yield b
        b.close()


def abrir(navegador, base_url, modo="cliente", ancho=1366, alto=900):
    ctx = navegador.new_context(viewport={"width": ancho, "height": alto})
    # El recorrido guiado se abre solo la primera vez: en los tests, ya visto (tiene su propio test).
    # Interfaz en español salvo que el test elija otro idioma (Chromium dice en-US y se usaría inglés).
    ctx.add_init_script(f"sessionStorage.setItem('ad-modo','{modo}');localStorage.setItem('ad-tour-visto','1');"
                        f"if(!localStorage.getItem('ad-idioma'))localStorage.setItem('ad-idioma','es');{_SIN_CDN}")
    pg = ctx.new_page()
    pg.errores = []
    pg.fallidos = []
    pg.on("pageerror", lambda e: pg.errores.append(str(e)))
    pg.on("response", lambda r: pg.fallidos.append(r.url) if r.status >= 400 and "/assets/" in r.url else None)
    pg.goto(base_url + "/")
    pg.fill("#usuario", USUARIO)
    pg.fill("#password", CLAVE)
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#contenido")
    pg.wait_for_selector('.fase2-section[aria-busy="false"]', state='attached')
    return pg


@pytest.fixture
def pagina(navegador, base_url, request):
    """El dashboard abierto, en la vista Cliente salvo que el test pida otra (parametrize indirecto)."""
    pg = abrir(navegador, base_url, modo=getattr(request, "param", "cliente"))
    yield pg
    assert pg.errores == [], f"Errores de JavaScript: {pg.errores}"
    pg.context.close()


def pasar_a_dev(pg):
    """Toca el control para pasar a Desarrollador (no confirma). En la vista Cliente de
    escritorio está en el menú de Ayuda; en el celular, en el selector de la barra."""
    visible = pg.locator('.modo-switch button[data-modo="dev"]')
    if visible.is_visible():
        visible.click()
        return
    pg.click("#ayuda-btn")
    pg.click('#ayuda-menu button[data-modo="dev"]')


def elegir_idioma(pg, cod):
    """Elige el idioma de la interfaz. En la barra de íconos se despliega tocando el elegido."""
    boton = pg.locator(f'.selector-idioma [data-idioma="{cod}"]')
    if not boton.is_visible():
        pg.click('.selector-idioma button[aria-pressed="true"]')
    boton.click()
