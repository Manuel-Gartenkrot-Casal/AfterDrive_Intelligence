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


@pytest.fixture(scope="session")
def navegador():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=os.getenv("E2E_CHROMIUM") or None)
        except Exception as e:
            pytest.skip(f"Sin Chromium para los tests e2e ({e}).")
        yield b
        b.close()


def abrir(navegador, base_url, modo="cliente", ancho=1366, alto=900):
    ctx = navegador.new_context(viewport={"width": ancho, "height": alto})
    ctx.add_init_script(f"localStorage.setItem('ad-modo','{modo}');{_SIN_CDN}")
    pg = ctx.new_page()
    pg.errores = []
    pg.fallidos = []
    pg.on("pageerror", lambda e: pg.errores.append(str(e)))
    pg.on("response", lambda r: pg.fallidos.append(r.url) if r.status >= 400 and "/assets/" in r.url else None)
    pg.goto(base_url + "/")
    pg.fill("#usuario", USUARIO)
    pg.fill("#password", CLAVE)
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".sidebar")
    return pg


@pytest.fixture
def pagina(navegador, base_url):
    pg = abrir(navegador, base_url)
    yield pg
    assert pg.errores == [], f"Errores de JavaScript: {pg.errores}"
    pg.context.close()
