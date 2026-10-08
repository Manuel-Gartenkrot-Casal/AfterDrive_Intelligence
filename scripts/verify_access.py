"""Preview and browser checks with the real session module and isolated API data.

python scripts/verify_access.py --serve (editor / vista-previa, local demo only)
python scripts/verify_access.py (browser tests and screenshots under data/)
"""
import argparse
import os
import secrets
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import auth  # noqa: E402
from scripts.verify_dashboard import DATA  # noqa: E402


def preview_app():
    # Only this process uses demo credentials. Never load or alter .env.
    os.environ['ADMIN_USER'] = 'editor'
    os.environ['ADMIN_PASSWORD_HASH'] = generate_password_hash('vista-previa')
    os.environ['SECRET_KEY'] = secrets.token_hex(32)
    os.environ.pop('RENDER', None)
    assets = ROOT / 'express/src/public'
    app = Flask(__name__, static_folder=str(assets), static_url_path='/static')
    auth.init_app(app)

    @app.route('/')
    def root():
        response = send_from_directory(assets, 'index.html' if auth.hay_sesion() else 'login.html')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/api/<path:endpoint>', methods=['GET', 'POST'])
    def fixture(endpoint):
        if request.method != 'GET':
            return jsonify(success=False, error='Vista previa: esta operación no se ejecuta.'), 409
        return jsonify(DATA.get('/api/' + endpoint, {'success': True, 'items': [], 'total': 0, 'pagina': 1, 'paginas': 1}))

    return app


def verify(app):
    from playwright.sync_api import expect, sync_playwright
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    output = ROOT / 'data/access-design'
    output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 960})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url, wait_until='networkidle')
            page.screenshot(path=str(output / 'login-desktop.png'), full_page=True)
            page.get_by_role('button', name='Ingresar al espacio editorial').click()
            expect(page.locator('#usuario')).to_be_focused()
            expect(page.locator('#login-error')).to_contain_text('Completá')
            page.get_by_label('Usuario', exact=True).fill('editor')
            page.get_by_label('Contraseña', exact=True).fill('incorrecta')
            page.get_by_role('button', name='Mostrar contraseña').click()
            expect(page.locator('#password')).to_have_attribute('type', 'text')
            page.get_by_role('button', name='Ocultar contraseña').click()
            page.locator('#login-submit').click()
            expect(page.locator('#login-error')).to_contain_text('incorrectos')
            page.set_viewport_size({'width':390, 'height':844})
            page.screenshot(path=str(output / 'login-mobile-error.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.get_by_label('Contraseña', exact=True).fill('vista-previa')
            page.locator('#login-submit').click()
            expect(page.locator('#workspace-main')).to_be_visible()
            assert page.request.get(url + '/api/health').status == 200
            page.set_viewport_size({'width':1440, 'height':960})
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(600)
            page.screenshot(path=str(output / 'dashboard-dark.png'), full_page=True)
            page.locator('#tab-nota').focus()
            page.keyboard.press('ArrowRight')
            expect(page.locator('#tab-articulo')).to_be_focused()
            expect(page.locator('#writing-articulo')).to_be_visible()
            page.keyboard.press('ArrowLeft')
            expect(page.locator('#tab-nota')).to_be_focused()
            page.wait_for_timeout(700)
            for width in [1440, 768, 390, 320]:
                page.set_viewport_size({'width':width, 'height':900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                if width == 390:
                    page.screenshot(path=str(output / 'dashboard-mobile.png'), full_page=True)
            page.set_viewport_size({'width':1440, 'height':960})
            page.get_by_role('button', name='Cambiar tema').click()
            page.wait_for_timeout(650)
            page.screenshot(path=str(output / 'dashboard-light.png'), full_page=True)
            page.get_by_role('button', name='Cerrar sesión', exact=True).click()
            expect(page.locator('#login-form')).to_be_visible()
            assert page.request.get(url + '/api/health').status == 401
            # Expiry in another tab must return this tab to login on its next API request.
            page.get_by_label('Usuario', exact=True).fill('editor')
            page.get_by_label('Contraseña', exact=True).fill('vista-previa')
            page.locator('#login-submit').click()
            expect(page.locator('#workspace-main')).to_be_visible()
            page.context.clear_cookies()
            page.evaluate("fetch('/api/health')")
            expect(page.locator('#login-form')).to_be_visible()
            assert not errors, errors
            browser.close()
        print('PASS: login real, error de credenciales, contraseña visible, logout y sesión vencida')
        print('PASS: selector con teclado y 4 anchos sin desborde; capturas claro/oscuro y móvil')
        print('PASS: sin errores JavaScript; sin Mongo ni proveedores de IA')
    finally:
        server.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    app = preview_app()
    if args.serve:
        app.run(host='127.0.0.1', port=8768, debug=False)
    else:
        verify(app)
