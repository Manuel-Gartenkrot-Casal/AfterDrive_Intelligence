"""Tests del carrusel para redes (carrusel.py) y sus endpoints. Sin Chromium: el render es falso."""

import mongomock
import pytest
from bson import ObjectId

from afterdrive import carrusel
from afterdrive.ia import llm

NOTA = """# El catálogo digital llega al mostrador

## Qué pasó
Frasle invirtió en su planta. La compañía busca acortar plazos.

## Qué significa para tu negocio
- Revisá qué líneas de **pastillas** podés reponer con proveedores locales.
- Completá la compatibilidad por año y motor en tus fichas.
- Publicá primero lo de alta rotación.
- Una cuarta que no entra.

## Fuentes

- [Frasle amplía su planta](https://n/1)

*Frasle amplía su planta y el catálogo digital se vuelve clave.*"""


def test_textos_sin_ia_salen_de_la_nota():
    t = carrusel.textos_sin_ia(NOTA, "es")
    assert t["titulo"] == "El catálogo digital llega al mostrador"
    assert t["subtitulo"].startswith("Frasle amplía su planta")
    assert t["puntos"] == ["Revisá qué líneas de pastillas podés reponer con proveedores locales.",
                           "Completá la compatibilidad por año y motor en tus fichas.",
                           "Publicá primero lo de alta rotación."]                 # 3, sin markdown ni fuentes
    assert t["cta"] == carrusel.CTA_DEFAULT["es"]


def test_validar_recorta_sin_cortar_palabras_y_exige_titulo_y_puntos():
    t = carrusel.validar({"titulo": "palabra " * 30, "puntos": "uno\n\ndos\ntres\ncuatro", "cta": ""}, "en")
    assert len(t["titulo"]) <= carrusel.TITULO_MAX and t["titulo"].endswith("palabra…")
    assert t["puntos"] == ["uno", "dos", "tres"] and t["cta"] == carrusel.CTA_DEFAULT["en"]
    with pytest.raises(carrusel.ErrorCarrusel, match="título"):
        carrusel.validar({"titulo": " ", "puntos": ["a"]})
    with pytest.raises(carrusel.ErrorCarrusel, match="punto"):
        carrusel.validar({"titulo": "T", "puntos": []})


def test_textos_con_ia_usa_el_modelo_barato(monkeypatch):
    pedidos = []
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: pedidos.append((system, kw)) or
                        '{"titulo": "Gancho", "subtitulo": "Sub", "puntos": ["a", "b", "c"], "cta": "Leé más"}')
    t = carrusel.textos_con_ia(NOTA, "pt")
    assert t == {"titulo": "Gancho", "subtitulo": "Sub", "puntos": ["a", "b", "c"], "cta": "Leé más"}
    system, kw = pedidos[0]
    assert kw["tarea"] == "carrusel" and "portugués de Brasil" in system
    assert llm.RESPALDO_TAREA["carrusel"] == "evaluacion"


def test_si_la_ia_falla_devuelve_none(monkeypatch):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: "no es json")
    assert carrusel.textos_con_ia(NOTA, "es") is None


def test_el_html_escapa_los_textos_y_lleva_la_foto():
    t = carrusel.validar({"titulo": "<script>x</script>", "puntos": ["a & b"]}, "es")
    paginas = carrusel.html_diapositivas(t, "data:image/png;base64,AAA", "https://blog/x", "es")
    assert len(paginas) == 3 and "<script" not in paginas[0] and "&lt;script" in paginas[0]
    assert "data:image/png;base64,AAA" in paginas[0] and "a &amp; b" in paginas[1] and "https://blog/x" in paginas[2]


# ── Generar y guardar (un carrusel por idioma) ────────────────────────────────

NOTA_PT = NOTA.replace("El catálogo digital llega al mostrador", "O catálogo digital chega ao balcão")


@pytest.fixture
def base(monkeypatch):
    b = mongomock.MongoClient().db
    monkeypatch.setattr(llm, "completar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin IA")))
    return b


def render_falso(htmls):
    return [f"png{i}".encode() for i in range(len(htmls))], b"%PDF-falso"


def ia_por_idioma(monkeypatch):
    """La IA responde en el idioma que se le pide (lo dice el system)."""
    def completar(system, user, **kw):
        cod = "pt" if "portugués" in system else "en" if "inglés" in system else "es"
        return ('{"titulo": "Título ' + cod + '", "subtitulo": "Sub", "puntos": ["a", "b", "c"], "cta": "CTA ' + cod + '"}')
    monkeypatch.setattr(llm, "completar", completar)


def test_por_defecto_arma_los_3_idiomas(base, monkeypatch):
    ia_por_idioma(monkeypatch)
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es"}).inserted_id
    hechos = carrusel.generar(str(oid), base=base, render=render_falso)
    assert set(hechos) == {"es", "pt", "en"}
    guardados = base.notas_fase2.find_one({"_id": oid})["carruseles"]
    assert {c: guardados[c]["textos"]["titulo"] for c in guardados} == {"es": "Título es", "pt": "Título pt", "en": "Título en"}
    assert guardados["pt"]["url"] == "https://afterdrive.alephee.com/pt/blog/" and len(guardados["en"]["diapositivas"]) == 3
    pdf = base.imagenes_subidas.find_one({"_id": ObjectId(guardados["pt"]["pdf_id"])})
    assert pdf["mime"] == "application/pdf" and pdf["idioma"] == "pt"
    assert base.imagenes_subidas.count_documents({"carrusel": True}) == 12   # 3 PNG + 1 PDF por idioma


def test_sin_ia_usa_la_traduccion_y_avisa_del_idioma_sin_version(base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es",
                                       "traducciones": {"pt": {"contenido": NOTA_PT}}}).inserted_id
    hechos = carrusel.generar(str(oid), base=base, render=render_falso)
    assert set(hechos) == {"es", "pt"}                                         # en: sin IA ni traducción
    assert hechos["pt"]["textos"]["titulo"] == "O catálogo digital chega ao balcão" and hechos["pt"]["origen_textos"] == "nota"
    assert hechos["pt"]["textos"]["cta"] == carrusel.CTA_DEFAULT["pt"]


def test_si_no_sale_ninguno_falla(base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es"}).inserted_id
    with pytest.raises(carrusel.ErrorCarrusel, match="ningún carrusel"):
        carrusel.generar(str(oid), ["en"], base=base, render=render_falso)


def test_editar_un_idioma_lo_redibuja_sin_ia_y_borra_sus_imagenes_viejas(base, monkeypatch):
    ia_por_idioma(monkeypatch)
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es",
                                       "hubspot": {"url": "https://blog/es/frenos"}}).inserted_id
    carrusel.generar(str(oid), base=base, render=render_falso)
    monkeypatch.setattr(llm, "completar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe llamar a la IA")))
    carrusel.guardar_textos(str(oid), "es", {"titulo": "Mi título", "puntos": ["uno"], "cta": "Vamos"}, base=base)
    hechos = carrusel.generar(str(oid), ["es"], solo_imagenes=True, base=base, render=render_falso)
    assert hechos["es"]["textos"]["titulo"] == "Mi título" and hechos["es"]["origen_textos"] == "editado"
    assert hechos["es"]["url"] == "https://blog/es/frenos"                     # el post en HubSpot, si ya se subió
    assert base.imagenes_subidas.count_documents({"carrusel": True}) == 12
    assert base.notas_fase2.find_one({"_id": oid})["carruseles"]["pt"]["textos"]["titulo"] == "Título pt"


def test_el_formato_viejo_se_migra(base, monkeypatch):
    ia_por_idioma(monkeypatch)
    viejo = {"idioma": "pt", "textos": {"titulo": "Viejo", "puntos": ["x"]}, "diapositivas": ["/api/imagenes/a"],
             "en_post": False, "generado_en": "t0"}
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es", "carrusel": viejo}).inserted_id
    carrusel.generar(str(oid), ["es"], base=base, render=render_falso)
    doc = base.notas_fase2.find_one({"_id": oid})
    assert "carrusel" not in doc and doc["carrusel_en_post"] is False
    assert set(doc["carruseles"]) == {"es", "pt"} and doc["carruseles"]["pt"]["textos"]["titulo"] == "Viejo"


def test_nota_inexistente_o_invalida(base):
    with pytest.raises(carrusel.ErrorCarrusel, match="no encontrada"):
        carrusel.generar(str(ObjectId()), base=base, render=render_falso)
    with pytest.raises(carrusel.ErrorCarrusel, match="inválida"):
        carrusel.generar("xx", base=base, render=render_falso)
    oid = base.notas_fase2.insert_one({"contenido": NOTA}).inserted_id
    with pytest.raises(carrusel.ErrorCarrusel, match="Idioma"):
        carrusel.generar(str(oid), ["fr"], base=base, render=render_falso)


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def cliente(api, monkeypatch, base):
    flask_api, _ = api
    from afterdrive import db as db_module
    from afterdrive.generacion import generar_nota_fase2 as g
    monkeypatch.setattr(db_module, "db", base)
    monkeypatch.setattr(g, "col_notas_fase2", base.notas_fase2)
    encoladas = []
    monkeypatch.setattr(flask_api.cola, "encolar",
                        lambda tipo, params=None, origen="manual", etiqueta=None:
                        encoladas.append((tipo, params, etiqueta)) or {"id": "c1", "posicion": 0})
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c, encoladas


def test_crear_encola_los_3_idiomas_o_los_pedidos(cliente, base):
    c, encoladas = cliente
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA}).inserted_id)
    assert c.post(f"/api/carrusel/{oid}", json={}).status_code == 202
    assert encoladas[-1] == ("script", {"modulo": "afterdrive.carrusel", "argv": [f"--nota={oid}"]}, "Crear carruseles")
    assert c.post(f"/api/carrusel/{oid}", json={"idiomas": ["en", "pt", "en"]}).status_code == 202
    assert encoladas[-1][1]["argv"] == [f"--nota={oid}", "--idiomas", "en", "pt"]
    assert c.post(f"/api/carrusel/{oid}", json={"idiomas": ["fr"]}).status_code == 400
    assert c.post("/api/carrusel/--nota=x", json={}).status_code == 400


def test_editar_textos_de_un_idioma(cliente, base):
    c, encoladas = cliente
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "carruseles": {"pt": {"idioma": "pt"}}}).inserted_id)
    r = c.post(f"/api/carrusel/{oid}/textos", json={"idioma": "pt", "titulo": "Novo", "puntos": ["a", "b"]})
    assert r.status_code == 202 and r.json["textos"]["titulo"] == "Novo"
    assert encoladas[-1][1]["argv"] == [f"--nota={oid}", "--idiomas", "pt", "--solo-imagenes"]
    assert c.post(f"/api/carrusel/{oid}/textos", json={"idioma": "pt", "titulo": "", "puntos": ["a"]}).status_code == 400
    assert c.post(f"/api/carrusel/{oid}/textos", json={"titulo": "T", "puntos": ["a"]}).status_code == 400   # sin idioma
    assert c.post(f"/api/carrusel/{ObjectId()}/textos", json={"idioma": "es", "titulo": "T", "puntos": ["a"]}).status_code == 404


def test_descargar_el_pdf_de_cada_idioma(cliente, base, monkeypatch):
    ia_por_idioma(monkeypatch)
    c, _ = cliente
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es"}).inserted_id
    assert c.get(f"/api/carrusel/{oid}/pdf").status_code == 404
    carrusel.generar(str(oid), base=base, render=render_falso)
    r = c.get(f"/api/carrusel/{oid}/pdf?idioma=en")
    assert r.status_code == 200 and r.data == b"%PDF-falso" and r.mimetype == "application/pdf"
    assert r.headers["Content-Disposition"].endswith('-en.pdf"')


# ── Galería en el post de HubSpot ─────────────────────────────────────────────

from afterdrive import historial, hubspot  # noqa: E402

CARRUSEL = {"idioma": "es", "diapositivas": ["/api/imagenes/a", "/api/imagenes/b", "/api/imagenes/c"],
            "textos": {"titulo": "Gancho", "puntos": ["uno", "dos"], "cta": "Leé"}, "generado_en": "t1"}
HTML = "<p>Intro</p><h3>Qué pasó</h3><p>Texto</p><h3>Fuentes</h3><ul><li>x</li></ul>"
COPIAS = {"hubspot_urls": ["https://hs/1.png", "https://hs/2.png", "https://hs/3.png"]}


def test_la_galeria_va_antes_de_las_fuentes_con_las_copias_de_hubspot():
    imgs = hubspot.galeria_carrusel({"carruseles": {"es": {**CARRUSEL, **COPIAS}}}, "es")
    assert [i["url"] for i in imgs] == COPIAS["hubspot_urls"]
    assert imgs[0]["alt"] == "Gancho" and imgs[1]["alt"] == "uno · dos"
    html = hubspot.con_galeria(HTML, imgs, "es")
    assert html.index("afterdrive-carrusel") < html.index("<h3>Fuentes</h3>") and html.count("<img") == 3
    assert "La nota en 3 imágenes" in html
    assert hubspot.con_galeria("<p>Sin fuentes</p>", imgs, "pt").endswith("</div>")   # al final si no hay fuentes


@pytest.mark.parametrize("nota, cod", [
    ({"carruseles": {"es": {**CARRUSEL, **COPIAS}}}, "pt"),                              # no hay de ese idioma
    ({"carruseles": {"es": {**CARRUSEL, **COPIAS}}, "carrusel_en_post": False}, "es"),   # galerías apagadas
    ({"carruseles": {"es": CARRUSEL}}, "es"),                                             # sin copiar a HubSpot
])
def test_cuando_no_va_la_galeria(nota, cod):
    assert hubspot.galeria_carrusel(nota, cod) == []


def test_la_vista_previa_muestra_las_originales_y_entiende_el_formato_viejo():
    assert len(hubspot.galeria_carrusel({"carruseles": {"es": CARRUSEL}}, "es", vista=True)) == 3
    assert len(hubspot.galeria_carrusel({"carrusel": {**CARRUSEL, **COPIAS}}, "es")) == 3


@pytest.fixture
def hs(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.delenv("HUBSPOT_BLOG_PRUEBAS", raising=False)
    llamadas, subidas = [], []

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "999", "url": "https://blog/x", "state": "DRAFT"}

    def fake(metodo):
        return lambda url, json=None, headers=None, timeout=None, params=None: llamadas.append((metodo, json)) or Resp()
    monkeypatch.setattr(hubspot, "_transporte", {"post": fake("post"), "patch": fake("patch"), "get": fake("get")})
    monkeypatch.setattr(hubspot, "subir_imagen", lambda contenido, mime, nombre:
                        subidas.append(nombre) or f"https://hs/{nombre}")
    return llamadas, subidas


def _nota_con_carruseles(base, monkeypatch):
    ia_por_idioma(monkeypatch)
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es", "estado": "aprobada"}).inserted_id
    carrusel.generar(str(oid), base=base, render=render_falso)
    return oid


def test_al_subir_se_copian_los_3_carruseles_y_el_post_lleva_el_de_su_idioma(base, hs, monkeypatch):
    llamadas, subidas = hs
    oid = _nota_con_carruseles(base, monkeypatch)
    item = historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert len(subidas) == 9 and sum(f"carrusel-{oid}-pt-" in n for n in subidas) == 3
    cuerpo = llamadas[-1][1]["postBody"]
    assert cuerpo.count(f"https://hs/carrusel-{oid}-es-") == 3 and "-pt-" not in cuerpo
    assert cuerpo.index("afterdrive-carrusel") < cuerpo.index("<h3>Fuentes</h3>") and "aviso" not in item
    doc = base.notas_fase2.find_one({"_id": oid})
    assert all(len(doc["carruseles"][c]["hubspot_urls"]) == 3 for c in ("es", "pt", "en"))
    historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert len(subidas) == 9                                     # reenviar no vuelve a copiarlas


def test_las_traducciones_llevan_el_carrusel_de_su_idioma(base, hs, monkeypatch):
    llamadas, _ = hs
    oid = _nota_con_carruseles(base, monkeypatch)
    historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    doc = base.notas_fase2.find_one({"_id": oid})
    llamadas.clear()
    hubspot.enviar_traduccion(doc, "pt", "# Título\n\n## Fontes\n\n- [x](https://n)\n\n*Meta.*", "111")
    cuerpo = next(j for m, j in llamadas if m == "patch")["postBody"]
    assert "O artigo em 3 imagens" in cuerpo and cuerpo.count(f"carrusel-{oid}-pt-") == 3


def test_apagadas_no_se_copian_ni_van(base, hs, monkeypatch):
    llamadas, subidas = hs
    oid = _nota_con_carruseles(base, monkeypatch)
    carrusel.en_post(str(oid), False, base=base)
    historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert subidas == [] and "afterdrive-carrusel" not in llamadas[-1][1]["postBody"]


def test_si_no_se_puede_copiar_el_post_sale_sin_galeria_y_avisa(base, hs, monkeypatch):
    llamadas, _ = hs
    oid = _nota_con_carruseles(base, monkeypatch)
    monkeypatch.setattr(hubspot, "subir_imagen", lambda *a: (_ for _ in ()).throw(hubspot.ErrorHubSpot("sin scope files")))
    item = historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert "sin la galería" in item["aviso"] and "afterdrive-carrusel" not in llamadas[-1][1]["postBody"]


def test_endpoint_en_post(cliente, base, monkeypatch):
    c, _ = cliente
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es"}).inserted_id
    assert c.post(f"/api/carrusel/{oid}/en-post", json={"activo": False}).status_code == 404   # sin carrusel
    ia_por_idioma(monkeypatch)
    carrusel.generar(str(oid), ["es"], base=base, render=render_falso)
    assert c.post(f"/api/carrusel/{oid}/en-post", json={"activo": "no"}).status_code == 400
    assert c.post(f"/api/carrusel/{oid}/en-post", json={"activo": False}).status_code == 200
    assert base.notas_fase2.find_one({"_id": oid})["carrusel_en_post"] is False
