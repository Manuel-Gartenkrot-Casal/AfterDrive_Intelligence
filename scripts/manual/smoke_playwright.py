"""
Prueba de humo manual contra un Flask ya levantado (python -m afterdrive.flask_api).

Flask sirve la API y el dashboard en el mismo puerto, todo detrás del login.
Uso: python scripts/manual/smoke_playwright.py [usuario] [contraseña]
Sin credenciales solo verifica que la API esté cerrada y que aparezca el login.
"""
import sys

import requests
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5000"


def test_api_cerrada() -> bool:
    """/health responde y el resto de la API exige sesión."""
    print(f"=== API en {BASE} ===")
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        print(f"Health: {r.status_code} - {r.json()}")
        r = requests.get(f"{BASE}/api/check-volume?keyword=autopartes", timeout=10)
        print(f"Sin sesión, /api/check-volume: {r.status_code} (se espera 401)")
        return r.status_code == 401
    except Exception as e:
        print(f"API FAILED: {e}")
        return False


def test_dashboard(usuario: str | None, password: str | None) -> bool:
    """El login aparece; con credenciales, el dashboard carga sin errores de consola."""
    print("\n=== Dashboard ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errores = []
        page.on("console", lambda msg: errores.append(msg.text) if msg.type == "error" else None)
        try:
            page.goto(BASE, timeout=10000)
            print(f"Pantalla de login visible: {page.locator('#password').is_visible()}")
            if not (usuario and password):
                return page.locator("#password").is_visible()

            page.fill("#usuario", usuario)
            page.fill("#password", password)
            page.click("#entrar")
            page.wait_for_selector("#statusText", timeout=10000)
            page.wait_for_load_state("networkidle")
            page.screenshot(path="scripts/manual/screenshot.png", full_page=True)
            print("Screenshot saved: scripts/manual/screenshot.png")
            print(f"Page title: {page.title()}")
            print(f"API Status: {page.locator('#statusText').text_content()}")
            page.wait_for_timeout(2000)
            print(f"Console errors: {errores}" if errores else "No console errors detected")
            return not errores
        except Exception as e:
            print(f"Dashboard test FAILED: {e}")
            return False
        finally:
            browser.close()


if __name__ == "__main__":
    print("AfterDrive Intelligence - Pipeline Test")
    print("=" * 50)
    credenciales = (sys.argv[1:3] + [None, None])[:2]
    api_ok = test_api_cerrada()
    dash_ok = test_dashboard(*credenciales)

    print("\n" + "=" * 50)
    print(f"API cerrada sin sesión: {'PASS' if api_ok else 'FAIL'}")
    print(f"Dashboard: {'PASS' if dash_ok else 'FAIL'}")
    sys.exit(0 if api_ok and dash_ok else 1)
