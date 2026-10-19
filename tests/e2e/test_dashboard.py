"""
Tests del dashboard en un navegador real (Playwright + Chromium).

Prueban lo que los tests de la API no ven: que el JS cargue sin errores y que
los flujos principales funcionen de punta a punta. Corren aparte:

    python -m pytest -m e2e tests/e2e

El servidor comparte datos entre tests (una sola base en memoria), así que
cada test usa datos distintos de la semilla de tests/e2e/servidor.py.
"""

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import abrir

pytestmark = pytest.mark.e2e

SECCIONES = ["inicio", "crear", "historial", "programacion", "fuentes", "corridas"]


def _visible(pg, seccion):
    """Si algún bloque de la sección se ve (en modo cliente hay bloques solo-dev ocultos)."""
    return pg.evaluate("""s => [...document.querySelectorAll('main [data-seccion="' + s + '"]')]
        .some(el => el.offsetParent !== null)""", seccion)


def test_login_carga_el_dashboard_sin_errores(pagina):
    pagina.wait_for_load_state("networkidle")
    assert pagina.fallidos == []
    assert pagina.evaluate("typeof irASeccion === 'function' && typeof confirmar === 'function'")
    assert pagina.locator("#trusted-urls-count").inner_text() != ""


def test_navegar_por_todas_las_secciones(pagina):
    for s in SECCIONES:
        pagina.click(f'.sidebar a[data-seccion="{s}"]')
        assert pagina.url.endswith("#" + s)
        assert _visible(pagina, s), s
        otras = [o for o in SECCIONES if o != s]
        assert not any(_visible(pagina, o) for o in otras), s
    pagina.go_back()
    pagina.wait_for_function("location.hash === '#fuentes'")
    assert _visible(pagina, "fuentes")


def test_programacion_guarda_con_boton_aparte(pagina):
    pagina.click('.sidebar a[data-seccion="programacion"]')
    barra = pagina.locator("#barra-programacion")
    assert barra.is_hidden()
    pagina.fill("#dias-scraping", "3")
    pagina.dispatch_event("#dias-scraping", "input")
    barra.wait_for(state="visible")
    barra.locator('[data-accion="descartar"]').click()
    barra.wait_for(state="hidden")
    assert pagina.input_value("#dias-scraping") == "1"

    pagina.fill("#dias-scraping", "2")
    pagina.dispatch_event("#dias-scraping", "input")
    barra.locator('[data-accion="guardar"]').click()
    barra.wait_for(state="hidden")
    pagina.reload()
    pagina.wait_for_selector(".sidebar")
    pagina.wait_for_function("document.getElementById('dias-scraping').value === '2'")


def test_borrar_fuente_pide_confirmacion(pagina):
    pagina.click('.sidebar a[data-seccion="fuentes"]')
    fila = pagina.locator(".fuente-fila", has_text="fuente-dos.com")
    fila.wait_for()
    dialogo = pagina.locator("#confirmar")

    fila.locator(".icon-btn").click()
    dialogo.wait_for(state="visible")
    pagina.click("#confirmar-no")
    dialogo.wait_for(state="hidden")
    assert fila.count() == 1

    fila.locator(".icon-btn").click()
    dialogo.wait_for(state="visible")
    pagina.click("#confirmar-si")
    fila.wait_for(state="detached")


def test_pausar_y_activar_fuente(pagina):
    pagina.click('.sidebar a[data-seccion="fuentes"]')
    fila = pagina.locator(".fuente-fila", has_text="fuente-uno.com")
    fila.get_by_role("button", name="Pausar").click()
    pagina.locator(".fuente-fila.pausada", has_text="fuente-uno.com").wait_for()
    fila.get_by_role("button", name="Activar").click()
    pagina.locator(".fuente-fila:not(.pausada)", has_text="fuente-uno.com").wait_for()


def _abrir_nota(pg, titulo):
    pg.click('.sidebar a[data-seccion="historial"]')
    pg.click('[data-hist="generados_aprobados"]')
    pg.locator(".hist-item", has_text=titulo).click()
    pg.locator("#modal-art.open").wait_for()


def test_rechazar_pide_motivo_y_aprobar_cambia_el_estado(pagina):
    _abrir_nota(pagina, "Frenos")
    acciones = pagina.locator("#nota-acciones")

    acciones.get_by_role("button", name="Rechazar").click()
    pagina.locator("#confirmar").wait_for(state="visible")
    assert pagina.locator("#confirmar-valor").is_visible()
    assert pagina.is_disabled("#confirmar-si")
    pagina.fill("#confirmar-valor", "ok")
    assert pagina.is_disabled("#confirmar-si")
    pagina.click("#confirmar-no")
    pagina.locator("#confirmar").wait_for(state="hidden")

    acciones.get_by_role("button", name="Aprobar").click()
    acciones.locator(".estado-chip.aprobada").wait_for()


def test_vista_previa_de_la_nota(pagina):
    _abrir_nota(pagina, "Marketplaces")
    pagina.locator("#nota-acciones").get_by_role("button", name="Vista previa").click()
    previa = pagina.locator(".previa")
    previa.wait_for()
    assert "Marketplaces y catálogo" in previa.locator("h1").inner_text()
    assert pagina.locator(".previa-url").inner_text().startswith("/")
    pagina.get_by_role("button", name="Volver al texto").click()
    previa.wait_for(state="detached")


def test_buscar_ahora_encola_y_termina(pagina):
    pagina.click('.sidebar a[data-seccion="programacion"]')
    pagina.click("#btn-runnow")
    pagina.click('.sidebar a[data-seccion="corridas"]')
    pagina.locator("#corridas-recientes .estado-chip.ok").first.wait_for(timeout=20000)
    assert pagina.is_enabled("#btn-runnow")


@pytest.mark.parametrize("modo", ["cliente", "dev"])
def test_celular_sin_scroll_horizontal(navegador, base_url, modo):
    pg = abrir(navegador, base_url, modo=modo, ancho=390, alto=844)
    for s in SECCIONES:
        pg.evaluate(f"irASeccion('{s}')")
        ancho = pg.evaluate("document.documentElement.scrollWidth")
        assert ancho <= 390, f"{s} ({modo}): {ancho}px"
    assert pg.errores == []
    pg.context.close()


def test_api_paga_solo_desde_el_proveedor_de_desarrollador(pagina):
    # El interruptor de API paga ya no está en la barra lateral: se elige como
    # proveedor en la vista Desarrollador. El POST se intercepta para no dejar
    # el servidor compartido de los tests con otro proveedor.
    assert pagina.locator("#modo-pago-btn").count() == 0
    pedidos = []

    def cambiar(ruta):
        if ruta.request.method != "POST":
            return ruta.continue_()
        pedidos.append(ruta.request.post_data_json)
        ruta.fulfill(json={"success": True, "provider": "paga", "model": "modelo-e2e"})

    pagina.route("**/api/providers", cambiar)
    pagina.click('.modo-switch button[data-modo="dev"]')
    # Cuesta plata: pide confirmación, y cancelar no cambia nada.
    pagina.click("#prov-paga")
    expect(pagina.locator("#confirmar-titulo")).to_contain_text("API paga")
    pagina.click("#confirmar-no")
    assert pedidos == [] and "active" not in (pagina.locator("#prov-paga").get_attribute("class") or "")
    pagina.click("#prov-paga")
    pagina.click("#confirmar-si")
    pagina.wait_for_selector("#prov-paga.active")
    assert pedidos == [{"provider": "paga"}]
    assert "active" not in (pagina.locator("#prov-local").get_attribute("class") or "")


def test_cancelar_la_nota_en_curso(pagina):
    # Corrida simulada por HTTP: no se genera nada de verdad.
    estado = {"e": "en_curso"}
    cancelados = []
    pagina.route("**/api/corridas/generacion", lambda r: r.fulfill(json={"success": True, "id": "g1", "estado": "pendiente"}))
    pagina.route("**/api/corridas/g1/log?*", lambda r: r.fulfill(
        json={"success": True, "lineas": [], "siguiente": 0, "estado": estado["e"]}))

    def cancelar(ruta):
        cancelados.append(ruta.request.method)
        estado["e"] = "cancelada"
        ruta.fulfill(json={"success": True, "estado": "cancelando"})

    pagina.route("**/api/corridas/g1/cancelar", cancelar)
    pagina.locator('.nav-link[data-seccion="crear"]').click()
    boton = pagina.locator("#btn-f2-cancelar")
    expect(boton).to_be_hidden()
    pagina.locator("#f2-categorias-grid .toggle-item").first.click()
    pagina.click("#btn-f2-generar")
    expect(boton).to_be_enabled()
    boton.click()
    pagina.click("#confirmar-si")
    expect(pagina.locator("#f2-status")).to_contain_text("cancelada", timeout=10000)
    expect(boton).to_be_hidden()
    assert cancelados == ["POST"]


def test_calificar_una_nota_alimenta_la_calibracion(pagina):
    _abrir_nota(pagina, "Rotación de stock")
    lateral = pagina.locator(".modal-sidebar")
    # Lo que se revisó al generarla.
    assert "2 de 3 datos aparecen en las noticias" in lateral.inner_text()
    assert "US$ 80 millones" in lateral.locator(".revision-lista.mal").inner_text()
    assert "Palabra clave: rotación de stock" in lateral.inner_text()
    assert "Se corrigió porque falló en" in lateral.inner_text()
    costo = lateral.locator(".revision-bloque", has_text="Costo de esta nota")
    assert "USD 0,231" in costo.inner_text() and "redacción: USD 0,18" in costo.inner_text()
    lateral.locator("summary", has_text="Ver el plan").click()
    expect(lateral.locator(".revision-criterios ol")).to_contain_text("Qué pasó")

    calificar = lateral.locator(".calificar")
    calificar.wait_for()
    assert calificar.get_by_role("button", name="Guardar calificación").is_disabled()
    calificar.locator('.estrella[data-n="2"]').click()
    calificar.locator('[data-etiqueta="muy_larga"]').click()
    pagina.fill("#calificar-comentario", "El cierre repite la introducción")
    calificar.get_by_role("button", name="Guardar calificación").click()
    pagina.locator("#calificar-estado", has_text="Guardada").wait_for()

    pagina.keyboard.press("Escape")
    pagina.locator(".hist-item", has_text="Rotación de stock").locator(".badge-estrellas").wait_for()
    panel = pagina.locator("#calibracion-panel")
    expect(panel.locator("#calibracion-resumen")).to_contain_text("1 nota calificada")
    panel.locator("summary").click()
    expect(panel.locator("#calibracion-cuerpo")).to_contain_text("El cierre repite la introducción")


def test_tablero_de_desarrollador(pagina):
    tablero = pagina.locator(".tablero-dev")
    expect(tablero).to_be_hidden()          # en la vista Cliente no aparece
    pagina.click('.modo-switch button[data-modo="dev"]')
    expect(tablero).to_be_visible()
    expect(pagina.locator("#g-articulos svg")).to_be_visible()
    expect(pagina.locator("#g-notas svg")).to_be_visible()
    expect(pagina.locator("#tc-art-cifra")).to_contain_text("guardados")
    expect(pagina.locator("#g-corridas .corrida-metrica")).to_have_count(2)
    # Cambiar el período vuelve a pedir las métricas con esa cantidad de días.
    with pagina.expect_response(lambda r: "/api/metricas?dias=7" in r.url):
        pagina.click('#tablero-periodo button[data-dias="7"]')
    expect(pagina.locator("#tablero-periodo button[data-dias='7']")).to_have_attribute("aria-checked", "true")


def test_el_largo_de_la_nota_se_guarda(pagina):
    pagina.click('.sidebar a[data-seccion="crear"]')
    pagina.select_option("#f2-largo", "corto")
    barra = pagina.locator("#barra-crear")
    barra.wait_for(state="visible")
    barra.locator('[data-accion="guardar"]').click()
    barra.wait_for(state="hidden")
    pagina.reload()
    pagina.click('.sidebar a[data-seccion="crear"]')
    expect(pagina.locator("#f2-largo")).to_have_value("corto")
    pagina.select_option("#f2-largo", "medio")
    pagina.locator("#barra-crear").locator('[data-accion="guardar"]').click()


def test_generar_la_imagen_destacada_con_ia(pagina):
    _abrir_nota(pagina, "Marketplaces")
    pagina.locator("#nota-acciones").get_by_role("button", name="Vista previa").click()
    pagina.locator(".previa").wait_for()
    pagina.fill("#previa-img-desc", "a parts store counter")
    pagina.get_by_role("button", name="Generar imagen con IA").click()
    imagen = pagina.locator("img.previa-imagen")
    imagen.wait_for()
    assert imagen.get_attribute("src").startswith("/api/imagenes/")
    pagina.wait_for_function("() => document.querySelector('img.previa-imagen').naturalWidth > 0")
    expect(pagina.locator(".previa-generar")).to_contain_text("Imagen generada con IA")
    pagina.get_by_role("button", name="Quitar imagen").click()
    pagina.locator(".previa-sin-imagen").wait_for()
