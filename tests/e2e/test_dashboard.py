"""
Tests del dashboard en un navegador real (Playwright + Chromium).

Prueban lo que los tests de la API no ven: que el JS cargue sin errores y que
los flujos principales funcionen de punta a punta. Corren aparte:

    python -m pytest -m e2e tests/e2e

El servidor comparte datos entre tests (una sola base en memoria), así que
cada test usa datos distintos de la semilla de tests/e2e/servidor.py.
"""

import re

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

    acciones.get_by_role("button", name="Más").click()
    acciones.get_by_role("menuitem", name="Rechazar").click()
    pagina.locator("#confirmar").wait_for(state="visible")
    assert pagina.locator("#confirmar-valor").is_visible()
    assert pagina.is_disabled("#confirmar-si")
    pagina.fill("#confirmar-valor", "ok")
    assert pagina.is_disabled("#confirmar-si")
    pagina.click("#confirmar-no")
    pagina.locator("#confirmar").wait_for(state="hidden")

    # Con HubSpot configurado, aprobar también sube el borrador, firmado por el autor elegido.
    pagina.click("#tab-publicar")
    autor = pagina.locator("#hubspot-autor")
    autor.wait_for()
    assert autor.locator("option:checked").inner_text() == "Gaston Zelerteins"
    assert "Ana Dias" in autor.inner_text() and autor.locator("option").count() == 2   # solo los del idioma
    autor.select_option("191488460449")
    envios = []
    pagina.on("request", lambda r: envios.append(r) if r.url.endswith("/api/hubspot/enviar") else None)
    acciones.get_by_role("button", name="Aprobar y subir a HubSpot").dblclick()   # un doble clic no duplica el post
    pagina.locator("#modal-estado.aprobada").wait_for()
    expect(acciones.get_by_role("button", name="Publicar en HubSpot")).to_be_visible()
    acciones.get_by_role("button", name="Más").click()
    expect(acciones.get_by_role("menuitem", name="Actualizar borrador en HubSpot")).to_be_visible()
    id_nota = pagina.evaluate("_notaActual.id")
    destino = pagina.evaluate("id => fetch('/api/hubspot/destino/notas_fase2/' + id).then(r => r.json())", id_nota)
    assert destino["autor_id"] == "191488460449"
    assert len(envios) == 1


def _volver_a_revisar(pg, titulo):
    """Los tests comparten servidor: otro pudo haber aprobado la nota."""
    pg.evaluate("""async t => {
        const d = await (await fetch('/api/historial/generados_aprobados?q=' + encodeURIComponent(t))).json();
        const it = d.items[0];
        await fetch('/api/historial/estado', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                              body: JSON.stringify({coleccion: it.coleccion, id: it.id, estado: 'borrador'})});
    }""", titulo)


def test_recorrido_de_revision(pagina):
    # Para revisar: abre en Revisar, con lo que necesita atención primero.
    _volver_a_revisar(pagina, "Frenos")
    _abrir_nota(pagina, "Frenos")
    lateral, acciones = pagina.locator(".modal-sidebar"), pagina.locator("#nota-acciones")
    expect(pagina.locator("#modal-titulo")).to_have_text("Frenos: la demanda sube")
    expect(pagina.locator("#modal-estado")).to_have_text("Para revisar")
    expect(lateral.locator("#tab-revisar")).to_have_attribute("aria-selected", "true")
    expect(lateral.locator("#chequeos-atencion .chequeo").first).to_contain_text("Falta la imagen destacada")
    expect(lateral.locator("#tab-revisar .paso-estado")).to_have_text("1 aviso")
    expect(lateral.locator(".paso-resumen")).to_have_text("1 punto a revisar · 1 en orden")
    # La acción principal sigue el recorrido.
    acciones.get_by_role("button", name="Siguiente: calificar →").click()
    expect(lateral.locator("#paso-calificar")).to_be_visible()
    acciones.get_by_role("button", name="Siguiente: publicar →").click()
    expect(lateral.locator("#paso-publicar")).to_be_visible()
    expect(acciones.get_by_role("button", name="Aprobar y subir a HubSpot")).to_be_visible()
    # Flechas entre pasos, como en cualquier lista de pestañas.
    lateral.locator("#tab-publicar").focus()
    pagina.keyboard.press("ArrowLeft")
    expect(lateral.locator("#tab-calificar")).to_have_attribute("aria-selected", "true")
    # "Más": Escape cierra el menú, no la nota.
    acciones.get_by_role("button", name="Más").click()
    expect(acciones.get_by_role("menuitem", name="Copiar texto")).to_be_visible()
    pagina.keyboard.press("Escape")
    expect(acciones.get_by_role("menu")).to_be_hidden()
    expect(pagina.locator("#modal-art.open")).to_be_visible()


def test_recorrido_en_el_celular(navegador, base_url):
    pg = abrir(navegador, base_url, ancho=390, alto=844)
    try:
        pg.click("#menu-movil")
        _abrir_nota(pg, "Frenos")
        # Se ve la nota; el botón principal lleva a la revisión.
        expect(pg.locator("#art-body")).to_be_visible()
        expect(pg.locator(".modal-sidebar")).to_be_hidden()
        pg.locator("#nota-acciones").get_by_role("button", name="Revisar y publicar →").click()
        expect(pg.locator(".paso-panel:visible")).to_have_count(1)
        expect(pg.locator("#art-body")).to_be_hidden()
        pg.locator(".modal-vista").get_by_role("button", name="Nota").click()
        expect(pg.locator("#art-body")).to_be_visible()
        assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert pg.errores == []
    finally:
        pg.context.close()


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
    pagina.click("#confirmar-si")
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
    pedidos = []

    def generar(ruta):
        pedidos.append(ruta.request.post_data_json)
        ruta.fulfill(json={"success": True, "id": "g1", "estado": "pendiente"})

    pagina.route("**/api/corridas/generacion", generar)
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
    assert 'idioma' not in pedidos[0]  # Se conserva el contrato de generación existente.
    assert pagina.locator('#f2-pasos .fallo, #f2-pasos .actual').count() == 0
    expect(pagina.locator('#f2-pasos [data-paso="6"]')).to_be_hidden()


def test_calificar_una_nota_alimenta_la_calibracion(pagina):
    _abrir_nota(pagina, "Rotación de stock")
    lateral = pagina.locator(".modal-sidebar")
    # Aprobada y sin calificar: abre en el paso Calificar.
    expect(lateral.locator("#tab-calificar")).to_have_attribute("aria-selected", "true")
    # Lo que se revisó al generarla, en el paso Revisar: titular a la vista, detalle a pedido.
    lateral.locator("#tab-revisar").click()
    datos = lateral.locator("#chequeo-datos")
    expect(datos).to_contain_text("2 de 3 datos aparecen en las noticias")
    datos.get_by_role("button", name="Ver detalle").click()
    expect(datos.locator(".revision-lista.mal")).to_contain_text("US$ 80 millones")
    estilo = lateral.locator("#chequeo-estilo")
    estilo.get_by_role("button", name="Ver detalle").click()
    expect(estilo.locator(".tabla-revision")).to_contain_text("rotación de stock")
    lineamientos = lateral.locator("#chequeo-lineamientos")
    lineamientos.get_by_role("button", name="Ver detalle").click()
    expect(lineamientos).to_contain_text("Se corrigió porque falló en")
    expect(lateral.locator("#chequeo-imagen")).to_contain_text("1 no servía para la nota")
    lateral.locator(".como-se-genero summary").click()
    costo = lateral.locator(".revision-bloque", has_text="Costo de esta nota")
    expect(costo).to_contain_text("USD 0,231")
    expect(costo).to_contain_text("redacción: USD 0,18")
    expect(lateral.locator(".revision-bloque", has_text="Plan de la nota")).to_contain_text("Qué pasó")

    lateral.locator("#tab-calificar").click()
    calificar = lateral.locator(".calificar")
    calificar.wait_for()
    assert calificar.get_by_role("button", name="Guardar calificación").is_disabled()
    calificar.locator('.estrella[data-n="2"]').click()
    calificar.locator('[data-etiqueta="muy_larga"]').click()
    pagina.fill("#calificar-comentario", "El cierre repite la introducción")
    calificar.get_by_role("button", name="Guardar calificación").click()
    pagina.locator("#calificar-estado", has_text="Guardada").wait_for()
    # Guardada: el formulario queda vacío y el recuadro marca el éxito.
    expect(calificar).to_have_class(re.compile(r"\bexito\b"))
    expect(pagina.locator("#calificar-comentario")).to_have_value("")
    expect(calificar.locator(".estrella.on")).to_have_count(0)
    expect(calificar.locator('[data-etiqueta][aria-pressed="true"]')).to_have_count(0)

    pagina.keyboard.press("Escape")
    pagina.locator(".hist-item", has_text="Rotación de stock").locator(".badge-estrellas:not(.badge-ia)").wait_for()
    panel = pagina.locator("#calibracion-panel")
    expect(panel.locator("#calibracion-resumen")).to_contain_text("1 nota calificada")
    panel.locator("summary").click()
    expect(panel.locator("#calibracion-cuerpo")).to_contain_text("El cierre repite la introducción")


def test_calificacion_de_la_ia_en_su_apartado(pagina):
    # En la lista, como las estrellas de una persona, con la marca IA (6/10 = 3 de 5).
    pagina.click('.sidebar a[data-seccion="historial"]')
    pagina.click('[data-hist="generados_aprobados"]')
    insignia = pagina.locator(".hist-item", has_text="Rotación de stock").locator(".badge-ia")
    expect(insignia).to_have_text("IA★★★☆☆")
    expect(insignia).to_have_attribute("title", "Calificación de la IA: 6/10")
    expect(pagina.locator(".hist-item", has_text="Frenos").locator(".badge-ia")).to_have_count(0)
    _abrir_nota(pagina, "Rotación de stock")
    lateral = pagina.locator(".modal-sidebar")
    # En el paso Calificar, a la vista y sin botón para pedirla.
    lateral.locator("#tab-calificar").click()
    critica = lateral.locator(".critica-ia")
    expect(critica).to_contain_text("Calificación de la IA")
    expect(critica.locator(".critica-puntaje")).to_have_text("6/10")
    expect(critica).to_contain_text("mezcla voseo y tuteo")
    expect(critica.locator(".critica-aspectos li")).to_have_count(4)
    expect(critica.locator(".btn")).to_have_count(0)
    # Los primeros errores a la vista; el resto, con un clic.
    expect(critica.locator(".critica-errores li:visible")).to_have_count(3)
    expect(critica.locator(".critica-errores li").first).to_contain_text("Descubrí cómo ordenar el stock")
    critica.get_by_role("button", name="Ver 1 más").click()
    expect(critica.locator(".critica-errores li:visible")).to_have_count(4)
    # La calificación de las personas sigue en su lugar, debajo.
    calificar = lateral.locator(".calificar")
    expect(calificar.get_by_role("button", name="Guardar calificación")).to_be_visible()
    expect(calificar.locator(".critica-ia")).to_have_count(0)
    assert critica.bounding_box()["y"] < calificar.bounding_box()["y"]
    pagina.keyboard.press("Escape")

    # Una nota sin revisión la pide sola al abrirse, una vez.
    pedidos = []

    def responder(ruta):
        pedidos.append(ruta.request.post_data_json)
        pagina.wait_for_timeout(300)
        ruta.fulfill(json={"success": True, "critica": {
            "puntaje": 9, "resumen": "Bien escrita.", "aspectos": {"gramatica": 9}, "errores": [],
            "fecha": "2026-10-20T10:00:00+00:00"}})
    pagina.route("**/api/historial/critica", responder)
    _abrir_nota(pagina, "Frenos")
    lateral.locator("#tab-calificar").click()
    critica = lateral.locator(".critica-ia")
    expect(critica.locator(".critica-puntaje")).to_have_text("9/10")
    expect(critica).to_contain_text("No encontró errores de redacción.")
    assert len(pedidos) == 1 and pedidos[0]["coleccion"] == "notas_fase2" and pedidos[0]["id"]


def test_la_calificacion_de_la_ia_sigue_el_idioma_del_dashboard(pagina):
    pedidos = []

    def traducir(ruta):
        pedidos.append(ruta.request.post_data_json)
        ruta.fulfill(json={"success": True, "traduccion": {
            "resumen": "Concrete hook, but it mixes voseo and tuteo.",
            "problemas": ["Uses tú in a voseo article.", "Repeated eight times.", "Missing accent.", "Weak ending."]}})
    pagina.route("**/api/historial/critica/traduccion", traducir)
    lateral = pagina.locator(".modal-sidebar")
    critica = lateral.locator(".critica-ia")
    # En español no hace falta traducir: la crítica se escribe en español.
    _abrir_nota(pagina, "Rotación de stock")
    lateral.locator("#tab-calificar").click()
    expect(critica).to_contain_text("mezcla voseo y tuteo")
    assert pedidos == []
    pagina.keyboard.press("Escape")
    # En inglés, lo que explica la IA se traduce; la cita y su corrección quedan como en la nota.
    pagina.locator(".header").get_by_role("button", name="EN").click()
    pagina.locator(".hist-item", has_text="Rotación de stock").click()
    lateral.locator("#tab-calificar").click()
    expect(critica.locator(".critica-resumen")).to_have_text("Concrete hook, but it mixes voseo and tuteo.")
    primero = critica.locator(".critica-errores li").first
    expect(primero).to_contain_text("Uses tú in a voseo article.")
    expect(primero).to_contain_text("Descubrí cómo ordenar el stock")
    assert [p["idioma"] for p in pedidos] == ["en"]
    pagina.keyboard.press("Escape")
    pagina.locator(".header").get_by_role("button", name="ES").click()


def test_si_la_ia_no_puede_revisar_lo_dice_en_el_apartado(pagina):
    pagina.route("**/api/historial/critica", lambda r: r.fulfill(
        status=503, json={"success": False, "error": "Proveedor de IA no disponible para criticar la nota."}))
    _abrir_nota(pagina, "Frenos")
    critica = pagina.locator(".modal-sidebar .critica-ia")
    expect(critica).to_contain_text("No se pudo revisar la redacción: Proveedor de IA no disponible")
    expect(critica).to_contain_text("Se vuelve a intentar la próxima vez que abras la nota.")


def test_tablero_de_desarrollador(pagina):
    tablero = pagina.locator(".tablero-dev")
    expect(tablero).to_be_hidden()          # en la vista Cliente no aparece
    # Cambiar de vista pide confirmación; cancelar deja todo como estaba.
    pagina.click('.modo-switch button[data-modo="dev"]')
    expect(pagina.locator("#confirmar-titulo")).to_have_text("¿Pasar a la vista Desarrollador?")
    pagina.click("#confirmar-no")
    assert pagina.evaluate("document.documentElement.getAttribute('data-modo')") == "cliente"
    expect(tablero).to_be_hidden()
    pagina.click('.modo-switch button[data-modo="dev"]')
    pagina.click("#confirmar-si")
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


def test_elegir_la_foto_de_una_noticia_como_imagen_destacada(pagina):
    from tests.e2e.servidor import FOTO_E2E
    _abrir_nota(pagina, "Marketplaces")
    pagina.locator("#nota-acciones").get_by_role("button", name="Vista previa").click()
    pagina.locator(".previa").wait_for()
    expect(pagina.locator(".previa-sin-imagen")).to_be_visible()
    pagina.get_by_role("button", name="Mercado Libre suma catálogo").click()
    imagen = pagina.locator("img.previa-imagen")
    imagen.wait_for()
    assert imagen.get_attribute("src") == FOTO_E2E
    expect(pagina.locator(".previa-foto.elegida")).to_have_count(1)
    expect(pagina.locator(".previa-fotos-bloque")).to_contain_text("Mercado Libre suma catálogo")
    # También se ve en el panel lateral al abrir la nota, con la noticia de donde sale.
    pagina.keyboard.press("Escape")
    _abrir_nota(pagina, "Marketplaces")
    expect(pagina.locator(".revision-imagen")).to_have_attribute("src", FOTO_E2E)
    pagina.locator("#nota-acciones").get_by_role("button", name="Vista previa").click()
    pagina.locator(".previa").wait_for()
    pagina.get_by_role("button", name="Quitar imagen").click()
    pagina.locator(".previa-sin-imagen").wait_for()


def test_la_revision_muestra_idiomas_citas_y_la_foto_descartada_por_la_ia(pagina):
    _abrir_nota(pagina, "Rotación de stock")
    lateral = pagina.locator(".modal-sidebar")
    lateral.locator("#tab-revisar").click()
    lateral.locator(".como-se-genero summary").click()
    expect(lateral).to_contain_text("Cita 1 nota(s) de AfterDrive by Alephee:")
    expect(lateral.get_by_role("link", name="Catálogo y fitment")).to_have_attribute(
        "href", "https://afterdrive.alephee.com/es/blog/catalogo")
    lateral.locator("#tab-publicar").click()
    expect(lateral).to_contain_text("Sin imagen: la IA descartó las fotos de las noticias.")
    otros = lateral.locator(".revision-bloque", has_text="Otros idiomas")
    expect(otros).to_contain_text("Borrador en HubSpot, vinculado al original")
    expect(otros).to_contain_text("la traducción al inglés vino cortada")
    otros.get_by_role("button", name="Ver traducción").click()
    expect(otros.locator(".revision-traduccion-texto")).to_contain_text("Texto em português")
    expect(otros.get_by_role("button", name="Volver a subir las traducciones")).to_be_visible()


def test_imagen_desde_la_computadora(pagina):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    _abrir_nota(pagina, "Frenos")
    pagina.locator("#nota-acciones").get_by_role("button", name="Vista previa").click()
    zona = pagina.locator("#zona-imagen")
    expect(zona).to_contain_text("Arrastrá una imagen acá")
    # Un archivo que no es imagen no se manda.
    pagina.set_input_files("#archivo-imagen", files=[{"name": "nota.txt", "mimeType": "text/plain", "buffer": b"hola"}])
    expect(pagina.locator(".toast", has_text="JPG, PNG, WebP o GIF")).to_be_visible()
    # Una imagen elegida desde la computadora queda como destacada en la vista previa.
    pagina.set_input_files("#archivo-imagen", files=[{"name": "frenos.png", "mimeType": "image/png", "buffer": png}])
    expect(pagina.locator(".previa-imagen")).to_have_attribute("src", re.compile(r"^/api/imagenes/[0-9a-f]{24}$"))
    src = pagina.locator(".previa-imagen").get_attribute("src")
    assert pagina.evaluate("u => fetch(u).then(r => r.status)", src) == 200
    # Y el recorrido ya no la marca como faltante.
    pagina.get_by_role("button", name="Volver al texto").click()
    pagina.locator("#tab-revisar").click()
    expect(pagina.locator("#chequeo-imagen")).to_contain_text("Tiene imagen destacada.")
    # Arrastrar también funciona.
    pagina.locator("#nota-acciones").get_by_role("button", name="Vista previa").click()
    expect(zona).to_be_visible()
    pagina.evaluate("""png => {
        const dt = new DataTransfer();
        dt.items.add(new File([new Uint8Array(png)], 'otra.png', {type: 'image/png'}));
        const zona = document.getElementById('zona-imagen');
        zona.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
    }""", list(png))
    expect(pagina.locator(".previa-imagen")).not_to_have_attribute("src", src)


def test_la_vista_previa_marca_las_fotos_que_la_ia_descarto(pagina):
    _abrir_nota(pagina, "Marketplaces")
    pagina.locator("#nota-acciones").get_by_role("button", name="Vista previa").click()
    pagina.locator(".previa").wait_for()
    descartada = pagina.locator(".previa-foto.descartada")
    expect(descartada).to_have_count(1)
    expect(descartada).to_contain_text("IA: no apta")
    assert "Es un banner publicitario." in descartada.get_attribute("title")


def test_recorrido_guiado_la_primera_vez_y_desde_ayuda(navegador, base_url):
    # Contexto propio: abrir() marca el recorrido como visto en cada carga.
    from tests.e2e.conftest import _SIN_CDN, CLAVE, USUARIO
    ctx = navegador.new_context(viewport={"width": 1366, "height": 900}, locale="es-AR")
    ctx.add_init_script(f"localStorage.setItem('ad-modo','cliente');{_SIN_CDN}")
    pg = ctx.new_page()
    pg.errores = []
    pg.on("pageerror", lambda e: pg.errores.append(str(e)))
    pg.goto(base_url + "/")
    pg.fill("#usuario", USUARIO)
    pg.fill("#password", CLAVE)
    pg.keyboard.press("Enter")
    globo = pg.locator(".tour-globo")
    globo.wait_for()                                       # primera vez: arranca solo
    assert "Bienvenido" in globo.inner_text() and globo.get_attribute("role") == "dialog"

    # El primer paso deja elegir el idioma antes de seguir.
    selector = globo.locator(".selector-idioma")
    selector.get_by_role("button", name="PT").click()
    expect(pg.locator("#tour-titulo")).to_have_text("Bem-vindo ao AfterDrive Intelligence")
    expect(pg.locator("#tour-siguiente")).to_have_text("Próximo")
    selector.get_by_role("button", name="ES").click()
    expect(pg.locator("#tour-titulo")).to_have_text("Bienvenido a AfterDrive Intelligence")
    vistos, secciones = [], set()
    for _ in range(40):
        vistos.append(pg.locator("#tour-titulo").inner_text())
        secciones.add(pg.evaluate("location.hash"))
        if pg.locator("#tour-siguiente").inner_text() == "Terminar":
            break
        pg.click("#tour-siguiente")
        pg.wait_for_function("(t) => document.getElementById('tour-titulo').textContent !== t", arg=vistos[-1])
    assert vistos[-1] == "Listo" and "Proveedor de IA" not in vistos     # en vista Cliente se saltea
    assert {"#inicio", "#crear", "#historial"} <= secciones
    assert len(vistos) == 7
    pg.click("#tour-siguiente")
    globo.wait_for(state="detached")
    assert pg.evaluate("localStorage.getItem('ad-tour-visto')") == "1"
    pg.reload()
    pg.wait_for_selector(".sidebar")
    pg.wait_for_timeout(1000)
    assert pg.locator(".tour-globo").count() == 0        # la segunda vez no

    # Ayuda -> Repetir el tutorial; Esc lo cierra.
    pg.click("#ayuda-btn")
    pg.get_by_role("menuitem", name="Repetir el tutorial").click()
    globo.wait_for()
    pg.keyboard.press("Escape")
    globo.wait_for(state="detached")
    assert pg.errores == []
    pg.context.close()


def test_ayuda_abre_la_documentacion(pagina):
    pagina.click("#ayuda-btn")
    with pagina.context.expect_page() as nueva:
        pagina.get_by_role("menuitem", name="Ver la documentación").click()
    doc = nueva.value
    doc.wait_for_load_state()
    assert doc.url.endswith("/ayuda")
    expect(doc.locator("#ayuda-doc")).to_contain_text("Guía de uso")
    expect(doc.locator(".ayuda-indice")).to_contain_text("Documentación técnica")
    doc.locator(".ayuda-indice a", has_text="Pipelines").click()
    expect(doc.locator("#ayuda-doc")).to_contain_text("Pipelines")
    assert doc.url.endswith("#03-pipelines")


def test_idioma_desde_el_login_y_el_encabezado(navegador, base_url):
    from tests.e2e.conftest import _SIN_CDN, CLAVE, USUARIO
    ctx = navegador.new_context(viewport={"width": 1366, "height": 900}, locale="es-AR")
    ctx.add_init_script(f"localStorage.setItem('ad-tour-visto','1');localStorage.setItem('ad-modo','cliente');{_SIN_CDN}")
    pg = ctx.new_page()
    pg.errores = []
    pg.on("pageerror", lambda e: pg.errores.append(str(e)))
    pg.goto(base_url + "/")
    pg.locator(".idiomas").get_by_role("button", name="EN").click()      # antes de entrar
    expect(pg.locator("#entrar")).to_have_text("Sign in")
    pg.fill("#usuario", USUARIO)
    pg.fill("#password", CLAVE)
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".sidebar")
    nav = pg.locator(".nav-lista")
    expect(nav).to_contain_text("Create post")
    expect(nav).to_contain_text("History")
    assert pg.evaluate("document.documentElement.lang") == "en"

    # Desde el encabezado, a portugués; queda elegido al recargar.
    pg.locator(".header-right .selector-idioma").get_by_role("button", name="PT").click()
    expect(nav).to_contain_text("Criar post")
    pg.reload()
    pg.wait_for_selector(".sidebar")
    expect(nav).to_contain_text("Histórico")
    assert pg.locator(".header-right [data-idioma='pt']").get_attribute("aria-pressed") == "true"

    # Lo que el JS pinta después también sale traducido.
    pg.goto(base_url + "/#crear")
    expect(pg.locator("#btn-f2-generar")).to_contain_text("Gerar post")

    # La guía de uso llega en el idioma elegido.
    pg.goto(base_url + "/ayuda")
    expect(pg.locator("#ayuda-doc")).to_contain_text("Guia de uso")
    expect(pg.locator(".ayuda-cabecera")).to_contain_text("Voltar ao dashboard")
    pg.locator(".ayuda-cabecera").get_by_role("button", name="EN").click()
    expect(pg.locator("#ayuda-doc")).to_contain_text("User guide")

    # Y de vuelta a español, sin restos.
    pg.locator(".ayuda-cabecera").get_by_role("button", name="ES").click()
    expect(pg.locator("#ayuda-doc")).to_contain_text("Guía de uso")
    expect(pg.locator(".ayuda-cabecera")).to_contain_text("Volver al dashboard")
    assert pg.errores == []
    ctx.close()


def test_aprobar_y_subir_aparece_en_cada_nota_aunque_falte_el_token(navegador, base_url):
    # El botón de HubSpot está en todas las notas. Sin token, el bloque de la revisión lo dice.
    pg = abrir(navegador, base_url)
    pg.context.route("**/api/hubspot/estado", lambda r: r.fulfill(json={"success": True, "configurado": False}))
    pg.reload()
    pg.wait_for_selector(".sidebar")
    _abrir_nota(pg, "Frenos")
    pg.click("#tab-publicar")
    expect(pg.locator("#nota-acciones button", has_text="HubSpot").first).to_be_visible()
    expect(pg.locator(".revision-bloque", has_text="Publicación en HubSpot")).to_contain_text("falta HUBSPOT_TOKEN")
    assert pg.errores == []
    pg.context.close()
