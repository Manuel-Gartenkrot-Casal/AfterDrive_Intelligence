"""Regresiones de distribución, teclado y seguimiento de tareas sin servicios reales."""

from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import abrir

pytestmark = pytest.mark.e2e
SECCIONES = ["inicio", "crear", "historial", "programacion", "fuentes", "corridas"]


def test_idioma_informativo_segun_region(pagina):
    pagina.click('.nav-link[data-seccion="crear"]')
    pagina.click('#btn-mas-opciones')
    pagina.locator('#f2-regiones-grid button[data-slug="brasil"]').click()
    expect(pagina.locator('#idioma-nota-valor')).to_have_text('Português do Brasil')
    pagina.locator('.header-right [data-idioma="en"]').click()
    expect(pagina.locator('#idioma-nota-valor')).to_have_text('Português do Brasil')
    expect(pagina.locator('#crear-resumen')).to_contain_text('Português do Brasil')


def test_menu_movil_con_teclado_y_foco(navegador, base_url):
    pg = abrir(navegador, base_url, ancho=390, alto=844)
    try:
        expect(pg.locator('.sidebar')).to_be_hidden()
        pg.get_by_role('button', name='Crear una nota', exact=True).click()
        pg.wait_for_url('**/#crear')
        pg.reload()
        pg.wait_for_url('**/#inicio')   # al abrir la app siempre arranca en Inicio
        pg.get_by_role('button', name='Crear una nota', exact=True).click()
        pg.wait_for_url('**/#crear')
        expect(pg.locator('#btn-f2-generar')).to_be_visible()
        pg.locator('#menu-movil').press('Enter')
        expect(pg.locator('.sidebar')).to_be_visible()
        pg.keyboard.press('Escape')
        expect(pg.locator('.sidebar')).to_be_hidden()
        expect(pg.locator('#menu-movil')).to_be_focused()
        pg.locator('#menu-movil').press('Enter')
        pg.locator('.nav-link[data-seccion="historial"]').press('Enter')
        expect(pg.locator('.sidebar')).to_be_hidden()
        expect(pg.locator('#contenido')).to_be_focused()
        assert pg.errores == []
    finally:
        pg.context.close()


@pytest.mark.parametrize("ancho", [320, 390, 768, 1024, 1440, 1920])
def test_espacio_y_adaptacion(navegador, base_url, ancho):
    pg = abrir(navegador, base_url, ancho=ancho, alto=900)
    try:
        for modo in ["cliente", "dev"]:
            if ancho <= 640 and not pg.locator(".sidebar").is_visible():
                pg.click("#menu-movil")
            pg.locator(f'button[data-modo="{modo}"]').click()
            if modo == "dev":                     # cambiar de vista pide confirmación
                pg.click("#confirmar-si")
            for seccion in SECCIONES:
                if ancho <= 640 and not pg.locator(".sidebar").is_visible():
                    pg.click("#menu-movil")
                pg.locator(f'.nav-link[data-seccion="{seccion}"]').click()
                pg.wait_for_url("**/#" + seccion)
                assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth"), (ancho, modo, seccion)
        caja = pg.locator(".app-container").bounding_box()
        assert caja["width"] >= ancho - 20
        if ancho <= 640:
            pg.click("#menu-movil")
        pg.locator('.nav-link[data-seccion="crear"]').click()
        accion = pg.locator("#btn-f2-generar").bounding_box()
        assert accion["y"] + accion["height"] < 900
        if ancho <= 640:
            assert pg.locator("#f2-persona").bounding_box()["y"] < pg.locator("#f2-categorias-grid").bounding_box()["y"]
        assert pg.errores == []
    finally:
        pg.context.close()


def test_categorias_con_teclado_y_descartar(pagina):
    pagina.locator('.nav-link[data-seccion="crear"]').click()
    categoria = pagina.locator("#f2-categorias-grid button").first
    expect(categoria).to_have_attribute("aria-pressed", "false")
    categoria.press("Space")
    expect(categoria).to_have_attribute("aria-pressed", "true")
    expect(pagina.locator("#crear-resumen")).to_contain_text("1 categoría")
    pagina.locator('#barra-crear [data-accion="descartar"]').click()
    expect(categoria).to_have_attribute("aria-pressed", "false")


def test_saltar_al_contenido_conserva_seccion(pagina):
    pagina.locator('.nav-link[data-seccion="crear"]').click()
    pagina.locator('.skip-link').focus()
    pagina.keyboard.press('Enter')
    expect(pagina.locator('#contenido')).to_be_focused()
    assert pagina.url.endswith('#crear')


def test_modal_atrapa_foco_y_lo_devuelve(pagina):
    abrir_nota = pagina.locator("#c-ultima-btn")
    expect(abrir_nota).to_be_enabled()
    abrir_nota.click()
    expect(pagina.locator(".modal-close")).to_be_focused()
    for _ in range(16):
        pagina.keyboard.press("Tab")
        assert pagina.evaluate("!!document.activeElement.closest('#modal-art')")
    pagina.keyboard.press("Escape")
    expect(pagina.locator("#modal-art")).to_be_hidden()
    expect(abrir_nota).to_be_focused()


def test_historial_filtra_y_navega_con_flechas(pagina):
    pagina.locator('.nav-link[data-seccion="historial"]').click()
    tabs = pagina.locator('#hist-pestanas [role="tab"]')
    tabs.first.press("ArrowRight")
    expect(tabs.nth(1)).to_be_focused()
    expect(pagina.locator("#hist-estados")).to_be_hidden()
    tabs.nth(1).press("Home")
    expect(tabs.first).to_be_focused()
    expect(pagina.locator("#hist-estados")).to_be_visible()


def test_actividad_acompana_sin_abrirse_de_nuevo(pagina):
    # Fixture HTTP: no se inicia scraping ni se escribe en Mongo.
    tarea = {"id": "prueba-diseno", "etiqueta": "Preparando nota", "estado": "en_curso", "origen": "manual"}
    estado = {"en_curso": tarea, "pendientes": [], "recientes": []}
    lineas = ["Leyendo noticias", "Generando nota..."]
    pagina.route("**/api/corridas", lambda ruta: ruta.fulfill(json=estado))

    def registro(ruta):
        desde = int(parse_qs(urlparse(ruta.request.url).query).get("desde", [0])[0])
        ruta.fulfill(json={"lineas": lineas[desde:], "siguiente": len(lineas), "estado": tarea["estado"]})

    pagina.route("**/api/corridas/prueba-diseno/log?*", registro)
    pagina.locator('.nav-link[data-seccion="corridas"]').click()
    dock = pagina.locator("#actividad-dock")
    expect(dock).to_be_visible()
    expect(dock).to_have_attribute("open", "")
    expect(pagina.locator("#actividad-log")).to_contain_text("Generando nota")
    pagina.locator('.nav-link[data-seccion="fuentes"]').click()
    expect(dock).to_be_visible()
    dock.locator("summary").click()
    expect(dock).not_to_have_attribute("open", "")
    tarea["estado"] = "ok"
    estado.update(en_curso=None, recientes=[tarea])
    expect(dock).to_have_attribute("data-estado", "ok", timeout=10000)
    expect(dock).not_to_have_attribute("open", "")
    dock.locator("summary").click()
    expect(pagina.locator("#actividad-log")).to_have_text("\n".join(lineas))


@pytest.mark.parametrize('ancho', [390, 1440])
def test_consola_no_tapa_guardar_configuracion(navegador, base_url, ancho):
    pg = abrir(navegador, base_url, ancho=ancho, alto=900)
    try:
        tarea = {'id':'prueba-espacio', 'etiqueta':'Generar nota', 'estado':'en_curso', 'origen':'manual'}
        pg.route('**/api/corridas', lambda r: r.fulfill(json={'en_curso':tarea,'pendientes':[],'recientes':[]}))
        pg.route('**/api/corridas/prueba-espacio/log?*', lambda r: r.fulfill(json={'estado':'en_curso','lineas':['Procesando una noticia']*12,'siguiente':12}))
        if ancho <= 640:
            pg.click('#menu-movil')
        pg.click('.nav-link[data-seccion="corridas"]')
        expect(pg.locator('#actividad-dock')).to_be_visible()
        if ancho <= 640:
            pg.click('#menu-movil')
        pg.click('.nav-link[data-seccion="crear"]')
        pg.select_option('#f2-largo','largo')
        barra = pg.locator('#barra-crear')
        expect(barra).to_be_visible()
        # En escritorio scrollea el área de contenido; en el celular, la página.
        pg.evaluate('window.scrollTo(0, document.body.scrollHeight); $("contenido").scrollTo(0, 1e6)')
        pg.wait_for_timeout(300)
        a,b=barra.bounding_box(), pg.locator('#actividad-dock').bounding_box()
        assert a['y']+a['height'] <= b['y']+1
        barra.locator('[data-accion="descartar"]').click()
        expect(barra).to_be_hidden()
        assert pg.errores == []
    finally:
        pg.context.close()


@pytest.mark.parametrize("modo", ["cliente", "dev"])
def test_header_y_barra_quietos_al_scrollear(navegador, base_url, modo):
    """En escritorio solo se desplaza el contenido: el header y la barra lateral no se mueven."""
    pg = abrir(navegador, base_url, modo=modo, ancho=1366, alto=560)
    try:
        pg.click('.nav-link[data-seccion="crear"]')
        antes = [pg.locator(s).bounding_box() for s in ("#appHeader", ".sidebar")]
        pg.mouse.move(900, 400)
        for _ in range(6):
            pg.mouse.wheel(0, 200)
            pg.wait_for_timeout(60)
        pg.wait_for_timeout(200)
        assert pg.evaluate("$('contenido').scrollTop") > 0
        assert pg.evaluate("scrollY") == 0
        assert [pg.locator(s).bounding_box() for s in ("#appHeader", ".sidebar")] == antes
        assert pg.errores == []
    finally:
        pg.context.close()


@pytest.mark.parametrize("ancho", [390, 768, 1024, 1440])
@pytest.mark.parametrize("tema", ["light", "dark"])
def test_revision_visible_en_ambos_temas(pagina, ancho, tema):
    pagina.set_viewport_size({"width": ancho, "height": 900})
    if pagina.locator("html").get_attribute("data-theme") != tema:
        pagina.locator("#themeBtn").click()
    expect(pagina.locator("#c-ultima-btn")).to_be_enabled()
    pagina.locator("#c-ultima-btn").click()
    expect(pagina.locator("#modal-art.open")).to_be_visible()
    cuerpo = pagina.locator("#art-body").bounding_box()
    acciones = pagina.locator(".modal-footer").bounding_box()
    assert cuerpo["height"] > 120
    assert acciones["y"] + acciones["height"] <= 900
    assert pagina.evaluate("document.documentElement.scrollWidth <= innerWidth")
