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


# ── Generar y guardar ─────────────────────────────────────────────────────────


@pytest.fixture
def base(monkeypatch):
    b = mongomock.MongoClient().db
    monkeypatch.setattr(llm, "completar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin IA")))
    return b


def render_falso(htmls):
    return [f"png{i}".encode() for i in range(len(htmls))], b"%PDF-falso"


def test_generar_guarda_imagenes_pdf_y_textos(base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es"}).inserted_id
    c = carrusel.generar(str(oid), base=base, render=render_falso)
    assert c["origen_textos"] == "nota" and c["idioma"] == "es" and len(c["diapositivas"]) == 3
    assert c["url"] == "https://afterdrive.alephee.com/es/blog/"
    guardado = base.notas_fase2.find_one({"_id": oid})["carrusel"]
    assert guardado["textos"]["titulo"] == "El catálogo digital llega al mostrador"
    pdf = base.imagenes_subidas.find_one({"_id": ObjectId(c["pdf_id"])})
    assert pdf["mime"] == "application/pdf" and pdf["contenido"] == b"%PDF-falso"
    assert base.imagenes_subidas.count_documents({"carrusel": True}) == 4


def test_regenerar_borra_las_imagenes_viejas_y_usa_los_textos_editados(base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es",
                                       "hubspot": {"url": "https://blog/es/frenos"}}).inserted_id
    carrusel.generar(str(oid), base=base, render=render_falso)
    carrusel.guardar_textos(str(oid), {"titulo": "Mi título", "puntos": ["uno"], "cta": "Vamos"}, base=base)
    c = carrusel.generar(str(oid), solo_imagenes=True, base=base, render=render_falso)
    assert c["textos"]["titulo"] == "Mi título" and c["origen_textos"] == "editado"
    assert c["url"] == "https://blog/es/frenos"                     # el post en HubSpot, si ya se subió
    assert base.imagenes_subidas.count_documents({"carrusel": True}) == 4   # las primeras 4 se borraron


def test_en_otro_idioma_usa_la_traduccion_o_pide_traducir(base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es",
                                       "traducciones": {"pt": {"contenido": NOTA.replace("El catálogo", "O catálogo")}}}
                                      ).inserted_id
    assert carrusel.generar(str(oid), "pt", base=base, render=render_falso)["textos"]["titulo"].startswith("O catálogo")
    with pytest.raises(carrusel.ErrorCarrusel, match="traducila"):
        carrusel.generar(str(oid), "en", base=base, render=render_falso)


def test_nota_inexistente_o_invalida(base):
    with pytest.raises(carrusel.ErrorCarrusel, match="no encontrada"):
        carrusel.generar(str(ObjectId()), base=base, render=render_falso)
    with pytest.raises(carrusel.ErrorCarrusel, match="inválida"):
        carrusel.generar("xx", base=base, render=render_falso)


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


def test_crear_encola_el_modulo_con_la_nota_y_el_idioma(cliente, base):
    c, encoladas = cliente
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA}).inserted_id)
    assert c.post(f"/api/carrusel/{oid}", json={"idioma": "en"}).status_code == 202
    assert encoladas[-1] == ("script", {"modulo": "afterdrive.carrusel", "argv": [f"--nota={oid}", "--idioma=en"]},
                             "Crear carrusel")
    assert c.post(f"/api/carrusel/{oid}", json={"idioma": "fr"}).status_code == 400
    assert c.post("/api/carrusel/--nota=x", json={}).status_code == 400


def test_editar_textos_guarda_y_encola_solo_imagenes(cliente, base):
    c, encoladas = cliente
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "carrusel": {"idioma": "es"}}).inserted_id)
    r = c.post(f"/api/carrusel/{oid}/textos", json={"titulo": "Nuevo", "puntos": ["a", "b"]})
    assert r.status_code == 202 and r.json["textos"]["titulo"] == "Nuevo"
    assert encoladas[-1][1]["argv"] == [f"--nota={oid}", "--solo-imagenes"]
    assert c.post(f"/api/carrusel/{oid}/textos", json={"titulo": "", "puntos": ["a"]}).status_code == 400
    assert c.post(f"/api/carrusel/{ObjectId()}/textos", json={"titulo": "T", "puntos": ["a"]}).status_code == 404


def test_descargar_el_pdf(cliente, base):
    c, _ = cliente
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "es"}).inserted_id
    assert c.get(f"/api/carrusel/{oid}/pdf").status_code == 404
    carrusel.generar(str(oid), base=base, render=render_falso)
    r = c.get(f"/api/carrusel/{oid}/pdf")
    assert r.status_code == 200 and r.data == b"%PDF-falso" and r.mimetype == "application/pdf"
    assert "attachment" in r.headers["Content-Disposition"]
