"""Tests e2e de la revisión de una nota en la vista Cliente: la nota como documento (lectura.js)."""

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import abrir

pytestmark = pytest.mark.e2e

NOTA = "Peças para elétricos"


def _abrir(pg, titulo):
    pg.click('.sidebar a[data-seccion="historial"]')
    pg.click('[data-hist="generados_aprobados"]')
    pg.locator(".hist-item", has_text=titulo).click()
    pg.locator("#modal-art.open").wait_for()


def test_la_nota_se_lee_como_documento_con_los_datos_marcados(pagina):
    _abrir(pagina, NOTA)
    assert pagina.evaluate("document.getElementById('modal-caja').classList.contains('lectura')")
    texto = pagina.locator("#nota-texto")
    expect(texto.locator("h1")).to_have_text("Peças para elétricos: o canal independente")
    assert "Source Serif" in pagina.evaluate("getComputedStyle(document.querySelector('#nota-texto')).fontFamily")
    expect(pagina.locator(".lectura-meta")).to_contain_text("Divulgativo")
    expect(pagina.locator(".lectura-lineamientos")).to_have_text("8/9 lineamientos")
    expect(texto.locator("mark.dato.ok")).to_have_count(2)
    expect(texto.locator("mark.dato.duda")).to_have_text("US$ 2,65 trilhões")
    aviso = pagina.locator(".lectura-aviso", has_text="Dato dudoso")
    expect(aviso).to_contain_text("US$ 2,65 trilhões")
    aviso.get_by_role("button", name="Dejar así").click()
    expect(pagina.locator(".lectura-aviso", has_text="Dato dudoso")).to_have_count(0)
    expect(texto.locator("mark.dato.duda")).to_have_count(0)
    # Arriba la acción principal de su estado; abajo la barra flotante.
    expect(pagina.locator("#lectura-acciones").get_by_role("button", name="Subir borrador a HubSpot")).to_be_visible()
    barra = pagina.locator(".lectura-barra")
    for nombre in ("✎ Editar", "★ Calificar", "Vista previa", "Más ▾"):
        expect(barra.get_by_role("button", name=nombre)).to_be_visible()
    barra.get_by_role("button", name="Más ▾").click()
    barra.get_by_role("menuitem", name="Cómo se generó").click()
    assert pagina.evaluate("document.getElementById('lectura-generacion').open")


def test_la_vista_previa_cambia_de_red_con_el_switch(pagina):
    _abrir(pagina, NOTA)
    panel = pagina.locator(".modal-sidebar")
    redes = panel.locator(".lp-redes")
    expect(redes.get_by_role("radio", name="Blog")).to_have_attribute("aria-checked", "true")
    expect(panel.locator("#lp-blog h2")).to_have_text("Peças para elétricos: o canal independente")
    expect(panel.locator("#hubspot-autor")).to_be_visible()   # quién firma, el mismo select que lee enviarAHubspot
    redes.get_by_role("radio", name="Instagram").click()
    expect(panel.locator(".lp-telefono .ig-post img")).to_have_count(3)
    panel.locator("#ig-sig").click()
    expect(panel.locator("#ig-contador")).to_have_text("2/3")
    redes.get_by_role("radio", name="LinkedIn").click()
    expect(panel.locator(".lp-li-texto")).to_have_text("A oficina independente concentra o reparo.")
    expect(panel.locator(".lp-li-pager i.on")).to_have_count(1)
    panel.get_by_role("button", name="Página siguiente").click()
    expect(panel.locator(".lp-li-pager i").nth(1)).to_have_class("on")
    expect(panel.get_by_role("link", name="Descargar el PDF para LinkedIn")).to_be_visible()
    # La ✕ cierra el panel y la nota ocupa todo el ancho.
    panel.locator(".lp-cerrar").click()
    assert pagina.evaluate("document.getElementById('modal-caja').classList.contains('panel-cerrado')")


def test_calificar_se_abre_en_el_panel(pagina):
    _abrir(pagina, NOTA)
    pagina.locator(".lectura-barra").get_by_role("button", name="★ Calificar").click()
    panel = pagina.locator(".modal-sidebar")
    expect(panel.locator(".lp-cab")).to_contain_text("Calificar la nota")
    expect(panel.locator(".estrella")).to_have_count(5)
    expect(pagina.locator(".lectura-barra").get_by_role("button", name="★ Calificar")).to_have_attribute("aria-pressed", "true")


def test_rechazar_y_aprobar_desde_arriba(pagina):
    pagina.evaluate("""async () => {
        const d = await (await fetch('/api/historial/generados_aprobados?q=Frenos')).json();
        const it = d.items[0];
        await fetch('/api/historial/estado', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                              body: JSON.stringify({coleccion: it.coleccion, id: it.id, estado: 'borrador'})});
    }""")
    _abrir(pagina, "Frenos")
    arriba = pagina.locator("#lectura-acciones")
    arriba.get_by_role("button", name="Rechazar").click()
    pagina.locator("#confirmar").wait_for(state="visible")
    assert pagina.locator("#confirmar-valor").is_visible()   # pide el motivo
    pagina.click("#confirmar-no")
    arriba.get_by_role("button", name="Aprobar y subir").click()
    pagina.locator("#modal-estado.aprobada").wait_for()
    expect(arriba.get_by_role("button", name="Actualizar borrador en HubSpot")).to_be_visible()


def test_editar_vuelve_a_la_lectura(pagina):
    _abrir(pagina, NOTA)
    pagina.locator(".lectura-barra").get_by_role("button", name="✎ Editar").click()
    expect(pagina.locator("#editor-nota")).to_be_visible()
    pagina.locator("#nota-acciones").get_by_role("button", name="Cancelar").click()
    expect(pagina.locator(".lectura-barra")).to_be_visible()
    expect(pagina.locator("#nota-texto mark.dato.ok")).to_have_count(2)


def test_en_el_celular_la_nota_abre_sin_el_panel(navegador, base_url):
    pg = abrir(navegador, base_url, ancho=390, alto=844)
    try:
        pg.click("#menu-movil")
        _abrir(pg, NOTA)
        expect(pg.locator("#nota-texto")).to_be_visible()
        expect(pg.locator(".modal-sidebar")).to_be_hidden()
        pg.locator(".lectura-barra").get_by_role("button", name="Vista previa").click()
        expect(pg.locator(".modal-sidebar")).to_be_visible()
        assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert pg.errores == []
    finally:
        pg.context.close()


@pytest.mark.parametrize("pagina", ["dev"], indirect=True)
def test_la_vista_desarrollador_sigue_con_los_pasos(pagina):
    _abrir(pagina, NOTA)
    assert not pagina.evaluate("document.getElementById('modal-caja').classList.contains('lectura')")
    expect(pagina.locator(".pasos .paso")).to_have_count(3)
    expect(pagina.locator("#nota-texto mark.dato")).to_have_count(0)


def test_marco_de_la_vista_cliente_y_buscador(pagina):
    # Arriba: el logo y "afterdrive" como siempre (no el nombre de la sección), "+ Nueva nota",
    # idioma, tema y salir; a la izquierda, la barra de íconos con Ayuda abajo.
    expect(pagina.locator(".header-title")).to_be_visible()
    expect(pagina.locator("#header-miga")).to_be_hidden()
    expect(pagina.locator(".header-nueva")).to_be_visible()
    for control in (".selector-idioma", "#themeBtn", "#btn-salir"):
        expect(pagina.locator(".header-right " + control)).to_be_visible()
    expect(pagina.locator(".rail-pie #ayuda-btn")).to_be_visible()
    assert pagina.locator(".sidebar").bounding_box()["width"] <= 57
    # Las secciones en el orden de siempre.
    orden = pagina.evaluate("[...document.querySelectorAll('.nav-link')].map(a => a.dataset.seccion)")
    assert orden == ["inicio", "crear", "historial", "programacion", "fuentes", "prompts", "corridas"]
    ys = [pagina.locator(f'.nav-link[data-seccion="{s}"]').bounding_box()["y"] for s in orden]
    assert ys == sorted(ys)
    # La barra se despliega con los nombres y se recuerda al volver a entrar.
    barra = pagina.locator(".sidebar")
    pagina.click("#rail-toggle")
    expect(pagina.locator('.nav-link[data-seccion="historial"]')).to_contain_text("Historial")
    expect(barra).to_have_css("width", "224px")
    pagina.reload()
    expect(barra).to_have_css("width", "224px")
    pagina.click("#rail-toggle")
    expect(barra).to_have_css("width", "56px")
    pagina.click('.nav-link[data-seccion="historial"]')
    expect(pagina.locator("#header-miga")).to_be_hidden()
    # Ctrl+K: buscar una nota por el título y abrirla con Enter.
    pagina.keyboard.press("Control+k")
    expect(pagina.locator("#buscador")).to_be_visible()
    pagina.keyboard.type("Peças para")
    expect(pagina.locator(".buscador-item", has_text=NOTA)).to_be_visible()
    pagina.locator(".buscador-item", has_text=NOTA).click()
    pagina.locator("#modal-art.open").wait_for()
    expect(pagina.locator("#modal-titulo")).to_contain_text(NOTA)
    pagina.keyboard.press("Escape")
    # Sin escribir, lleva a una sección.
    pagina.click("#buscador-btn")
    pagina.locator(".buscador-item", has_text="Fuentes").click()
    pagina.wait_for_function("location.hash === '#fuentes'")
