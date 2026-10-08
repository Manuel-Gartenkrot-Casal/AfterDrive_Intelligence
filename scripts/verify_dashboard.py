"""Browser regression check with isolated API fixtures; never accesses Mongo or AI.

Run: python scripts/verify_dashboard.py --output <screenshot-directory>
Requires Playwright and its Chromium browser (already used by the project).
"""

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "express/src/public"

DATA = {
    "/api/health": {"status": "ok"},
    "/api/providers": {"success": True, "provider": "openrouter", "providers": {}},
    "/api/trusted-urls-stats": {"success": True, "activas": 3, "total": 3, "ultima_ejecucion": "2026-09-27T08:30:00Z"},
    "/api/articulos-stats": {"success": True, "total": 124},
    "/api/scraping-config": {"success": True, "interval_days": 1, "max_articulos": 10, "enabled": True, "hora": "05:30", "zona": "America/Argentina/Buenos_Aires", "next_execution": "2026-09-28T05:30:00-03:00"},
    "/api/generacion-config": {"success": True, "interval_days": 3, "persona": "periodistico", "enabled": False},
    "/api/fase2/config": {"success": True, "categorias": ["industria"], "regiones": [], "clientes": []},
    "/api/fase2/categorias": {
        "success": True,
        "categorias": [
            {"slug": s, "nombre": n, "ejemplos": i + 2}
            for i, (s, n) in enumerate(
                [
                    ("industria", "Industria"),
                    ("repuestos", "Repuestos"),
                    ("tecnologia", "Tecnología"),
                    ("negocios", "Negocios"),
                    ("talleres", "Talleres"),
                    ("movilidad", "Movilidad"),
                    ("mercado", "Mercado"),
                    ("eventos", "Eventos"),
                ]
            )
        ],
    },
    "/api/fase2/regiones": {
        "success": True,
        "regiones": [
            {"slug": s, "nombre": s, "ejemplos": 4} for s in ["Argentina", "Brasil", "México", "Latinoamérica"]
        ],
    },
    "/api/fase2/clientes": {"success": True, "clientes": []},
    "/api/trusted-urls": {"success": True, "urls": []},
    "/api/suggested-urls": {"success": True, "urls": []},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    writes = []
    failures = set()
    errors = []
    held_streams = []
    hold_stream = False
    article = {
        "contenido": "# Repuestos: una mirada al sector\n\nContenido de prueba para revisar la experiencia editorial.",
        "categorias": ["industria"],
    }

    def route(request):
        url = urlparse(request.request.url)
        if url.hostname != "afterdrive.test":
            # Only existing font and Markdown CDN dependencies may reach the network.
            if url.hostname in {"fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net"}:
                request.continue_()
            else:
                request.abort()
            return
        path = url.path
        asset = "index.html" if path == "/" else path.removeprefix("/static/")
        if asset in {"index.html", "workspace.css", "workspace.js", "session.js", "historial.js", "traductor.js"}:
            content_type = {"html": "text/html", "css": "text/css", "js": "text/javascript"}[asset.split(".")[-1]]
            request.fulfill(body=(ROOT / asset).read_text(encoding="utf-8"), content_type=content_type)
            return
        method = request.request.method
        if method != "GET":
            writes.append((path, request.request.post_data_json if request.request.post_data else None))
        if (path, method) in failures:
            request.fulfill(status=500, json={"success": False, "error": "Fallo simulado"})
        elif "stream" in path and hold_stream:
            held_streams.append(request)
        elif "stream" in path:
            request.fulfill(
                content_type="text/event-stream",
                body="data: Total artículos extraídos: 4\n\ndata: 2 nuevos artículos aprobados\n\ndata: [OK]\n\n",
            )
        elif path in {"/ultimo-articulo", "/api/fase2/ultima-nota"}:
            request.fulfill(json={"success": True, "articulo": article, "nota": article})
        elif path == "/api/evaluate-article":
            request.fulfill(json={"success": True, "evaluation": {"lineamientos": {"claridad": True, "fuentes": True}}})
        elif path == "/api/check-volume":
            request.fulfill(json={"success": True, "count": 12})
        elif method != "GET":
            request.fulfill(json={"success": True})
        elif path in DATA:
            request.fulfill(json=DATA[path])
        else:
            request.fulfill(status=404, json={"success": False, "error": "Ruta no registrada en la prueba"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, timezone_id="UTC")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", route)
        page.goto("http://afterdrive.test", wait_until="networkidle")
        expect(page.locator('#f2-categorias-grid [aria-checked="true"]')).to_have_count(1)
        page.wait_for_function("document.getElementById('statArticles').textContent === '124'")
        expect(page.locator("#next-run")).to_have_text("28/9/2026, 05:30:00")
        print("PASS: programación en hora argentina incluso con navegador en UTC")
        page.screenshot(path=str(args.output / "after-desktop.png"), full_page=True)

        # The button must keep a readable label and visibly rotate during a
        # pending response. No real operation is sent to the backend.
        page.emulate_media(reduced_motion="no-preference")
        hold_stream = True
        page.locator("#btn-f2-generar").click()
        expect(page.locator("#btn-f2-generar")).to_contain_text("Redactando nota")
        expect(page.locator("#btn-f2-generar")).to_have_attribute("aria-busy", "true")
        expect(page.locator("#btn-f2-scrapear")).to_have_text("Recopilar noticias")
        expect(page.locator("#btn-f2-scrapear")).to_be_disabled()
        expect(page.locator("#btn-addurl-direct")).to_be_enabled()
        def transform():
            return page.locator("#btn-f2-generar").evaluate("el => getComputedStyle(el, '::after').transform")

        first = transform()
        page.wait_for_timeout(130)
        assert transform() != first, "El indicador no gira"
        page.screenshot(path=str(args.output / "running.png"), full_page=True)
        page.locator("#execution-collapse").click()
        expect(page.locator("#execution-content")).to_have_attribute("inert", "")
        expect(page.locator("#execution-content")).to_be_hidden()
        expect(page.locator("#execution-toggle")).to_be_focused()
        # Repeated toggles must settle correctly, including interrupted animation.
        page.locator("#execution-toggle").click()
        page.locator("#execution-toggle").click()
        expect(page.locator("#execution-content")).to_be_hidden()
        page.locator("#execution-toggle").click()
        expect(page.locator("#execution-content")).to_be_visible()
        for pending in held_streams:
            pending.fulfill(content_type="text/event-stream", body="data: [ERROR] Fallo de prueba\n\n")
        hold_stream = False
        expect(page.locator("#btn-f2-generar")).to_be_enabled()
        expect(page.locator("#btn-f2-generar")).to_have_text("Generar nota")
        expect(page.locator("#execution-state")).to_contain_text("errores")
        expect(page.locator("#btn-f2-scrapear")).to_be_enabled()
        print("PASS: indicador en movimiento, etiquetas preservadas, bloqueo selectivo y recuperación tras error")
        print("PASS: consola animada, cierre sin foco oculto y cambios rápidos")
        # Verify the theme has actual intermediate colors, not an instant swap.
        initial_theme = page.locator("html").get_attribute("data-theme")
        before = page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor")
        page.locator("#themeBtn").click()
        page.wait_for_timeout(100)
        middle = page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor")
        page.wait_for_timeout(400)
        after = page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor")
        assert middle != before and middle != after, (before, middle, after)
        page.locator("#themeBtn").click()
        expect(page.locator("html")).to_have_attribute("data-theme", initial_theme)
        page.emulate_media(reduced_motion="reduce")
        page.locator("#execution-collapse").click()
        expect(page.locator("#execution-content")).to_be_hidden()
        print("PASS: colores intermedios durante el cambio de tema y cierre con movimiento reducido")
        page.emulate_media(reduced_motion="no-preference")

        # Real keyboard interaction must persist the expected filter payload.
        option = page.locator('#f2-categorias-grid [data-slug="repuestos"]')
        option.focus()
        page.keyboard.press("Space")
        expect(option).to_have_attribute("aria-checked", "true")
        expect(page.locator("#editorial-save-status")).to_have_text("Selecciones guardadas")
        assert any(path == "/api/fase2/config" and "repuestos" in body.get("categorias", []) for path, body in writes)
        print("PASS: teclado, selección de filtros y payload de guardado")

        page.locator("#tab-nota").focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator("#writing-articulo")).to_be_visible()
        page.locator("#gen-tema").fill("frenos")
        page.get_by_role("button", name="Consultar fuentes", exact=True).click()
        expect(page.locator("#gen-vol-res")).to_contain_text("12")
        page.get_by_role("button", name="Último artículo", exact=True).click()
        expect(page.locator("#modal-art")).to_have_class("modal-overlay open")
        expect(page.locator("#art-body")).to_contain_text("Repuestos")
        page.keyboard.press("Shift+Tab")
        assert page.evaluate('document.activeElement.closest("#modal-art") !== null')
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="Último artículo", exact=True)).to_be_focused()
        page.locator("#btn-gen").click()
        expect(page.locator("#modal-art")).to_have_class("modal-overlay open")
        expect(page.locator("#art-body")).to_contain_text("Repuestos")
        page.keyboard.press("Escape")
        print("PASS: tabs, consulta de volumen, generación simulada, resultado y foco del modal")

        page.locator("#tab-nota").click()
        page.locator("#btn-f2-generar").click()
        expect(page.locator("#modal-art")).to_have_class("modal-overlay open")
        expect(page.locator("#art-body")).to_contain_text("Repuestos")
        page.keyboard.press("Escape")
        assert any(path == "/api/fase2/stream/generar" and "industria" in body["categorias"] for path, body in writes)
        print("PASS: generación de nota simulada con categorías y revisión")

        page.locator('[data-workspace="automatizacion"]').click()
        page.locator("#auto-days").fill("7")
        page.evaluate("updateStats()")
        expect(page.locator("#auto-days")).to_have_value("7")
        failures.add(("/api/scraping-config", "POST"))
        page.locator("#btn-savecfg").click()
        expect(page.locator(".toast").filter(has_text="No se guardó la programación").last).to_be_visible()
        expect(page.locator("#btn-savecfg")).to_have_text("Guardar cambios")
        failures.clear()
        page.locator("#btn-savecfg").click()
        expect(page.locator("#btn-savecfg")).to_have_text("Guardar programación")
        assert any(path == "/api/scraping-config" and body["interval_days"] == 7 for path, body in writes)
        print("PASS: edición preservada al refrescar; error 500 y reintento de guardado")

        page.locator('[data-workspace="fuentes"]').click()
        expect(page.locator("#trusted-urls-list")).to_contain_text("Todavía no hay fuentes")
        page.locator("#url-in").fill("https://example.org/noticias")
        page.locator("#btn-addurl-direct").click()
        expect(page.locator("#url-status")).to_contain_text("guardada")
        page.locator("#btn-f2-scrapear").click()
        expect(page.locator("#pipelineTicker")).to_contain_text("2 artículos nuevos")
        # El dock sustituye al botón "Ver actividad": la consola se abre sola al
        # arrancar la operación, así que el registro se lee sin cambiar de sección.
        expect(page.locator("#execution-content")).to_be_visible()
        expect(page.locator("#logs")).to_contain_text("SCRAPING FINALIZADO")
        print("PASS: fuente vacía, alta simulada, streaming y consola visible sin navegar")

        expect(page.locator("#pipelineHud")).not_to_be_visible(timeout=10000)
        expect(page.locator(".toast")).to_have_count(0, timeout=10000)
        page.emulate_media(reduced_motion="reduce")

        # Rendering and horizontal overflow across every navigation section.
        for theme in ["light", "dark"]:
            page.evaluate("(theme) => document.documentElement.dataset.theme = theme", theme)
            # Check semantic text pairs, not just palette swatches by eye.
            contrast = page.evaluate("""() => {
              const style = getComputedStyle(document.documentElement);
              const rgb = token => style.getPropertyValue(token).trim().slice(1).match(/.{2}/g).map(x => parseInt(x,16)/255);
              const lum = token => rgb(token).map(x => x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4).reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
              return [['--text-hi','--paper'],['--text-mid','--paper'],['--text-lo','--field'],['--on-brand','--brand'],['--brand','--brand-soft']].map(([a,b])=>[a,b,(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05)]);
            }""")
            assert all(ratio >= 4.5 for _, _, ratio in contrast), (theme, contrast)
            print(f"PASS: contraste de texto {theme}, mínimo {min(r for _, _, r in contrast):.2f}:1")
            for width in [1440, 768, 390, 320]:
                page.set_viewport_size({"width": width, "height": 900})
                for section in ["redaccion", "fuentes", "automatizacion", "actividad"]:
                    page.evaluate("(section) => openWorkspace(section, false)", section)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (theme, width, section)
                page.evaluate("openWorkspace('redaccion', false); selectWriting('nota')")
                if width in {1440, 390}:
                    page.screenshot(path=str(args.output / f"{theme}-{width}.png"), full_page=True)
        page.set_viewport_size({"width":390,"height":844})
        page.evaluate("openWorkspace('redaccion', false); selectWriting('nota'); setConsoleOpen(false)")
        assert not page.locator(".nav-foot").is_visible()
        voice = page.locator("#f2-persona").bounding_box()
        category = page.locator("#f2-categorias-grid").bounding_box()
        assert voice["y"] < category["y"], "El enfoque debe preceder a las categorías en móvil"
        print("PASS: móvil compacto y enfoque antes de cobertura")
        print("PASS: 32 combinaciones de sección/tema/ancho sin desborde horizontal")

        # Loading failure is actionable; recovery restores available controls.
        page.set_viewport_size({"width": 1440, "height": 1000})
        failures.add(("/api/fase2/categorias", "GET"))
        page.reload(wait_until="networkidle")
        expect(page.locator("#f2-categorias-grid")).to_contain_text("No se pudieron cargar")
        failures.clear()
        page.locator("#f2-categorias-grid").get_by_role("button", name="Reintentar").click()
        expect(page.locator("#f2-categorias-grid .toggle-item")).to_have_count(8)
        expect(page.locator('#f2-categorias-grid [data-slug="industria"]')).to_have_attribute("aria-checked", "true")
        assert not errors, errors
        print("PASS: recuperación de categorías, sin errores JavaScript")
        browser.close()
    print(f"OK: API simulada; {len(writes)} peticiones de escritura interceptadas, ninguna enviada a servicios reales.")


if __name__ == "__main__":
    main()
