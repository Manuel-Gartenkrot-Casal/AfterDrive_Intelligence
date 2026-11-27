"""Epígrafes de las fotos del texto: se escriben en los tres idiomas y van debajo de cada foto en HubSpot."""

import json

import mongomock
import pytest
from bson import ObjectId

from afterdrive import historial, hubspot
from afterdrive.generacion import epigrafes
from afterdrive.ia import llm

# conftest los apaga en todos los tests (sin_epigrafes): acá se prueba el original.
completar = epigrafes.completar

NOTA = {
    "contenido": "# Frenos: la demanda sube\n\nTexto.", "idioma": "pt", "plan": {"angulo": "El stock manda"},
    "fuentes": [{"titulo": "Depósitos llenos", "url": "https://s.com/dep", "imagen": "https://s.com/deposito.jpg",
                 "imagen_motivo": "Estanterías con cajas de pastillas de freno."}],
    "imagenes_cuerpo": [
        {"url": "https://s.com/deposito.jpg", "alt": "Depósitos llenos", "origen": {"titulo": "Depósitos llenos", "url": "https://s.com/dep"}},
        {"url": "https://s.com/mostrador.jpg", "alt": "Mostrador", "origen": {"titulo": "El mostrador vende más", "url": "https://s.com/mos"}},
    ],
}

RESPUESTA = {"epigrafes": [
    {"n": 1, "pt": "Estoque de pastilhas de freio pronto para reposição", "es": "Stock de pastillas de freno listo para reponer",
     "en": "Brake pad stock ready for replenishment"},
    {"n": 2, "pt": "O balcão concentra a venda de peças", "es": "El mostrador concentra la venta de repuestos",
     "en": "The counter drives parts sales"},
]}


def _nota():
    return json.loads(json.dumps(NOTA))


@pytest.fixture
def ia(monkeypatch):
    pedidos = []

    def falsa(system, user, **kw):
        pedidos.append((system, user, kw))
        return json.dumps(RESPUESTA)
    monkeypatch.setattr(llm, "completar", falsa)
    return pedidos


def test_escribe_el_epigrafe_de_cada_foto_en_los_tres_idiomas(ia):
    nota = _nota()
    assert completar(nota) == 2
    assert nota["imagenes_cuerpo"][0]["epigrafe"]["es"] == "Stock de pastillas de freno listo para reponer"
    assert set(nota["imagenes_cuerpo"][1]["epigrafe"]) == {"pt", "es", "en"}
    system, user, kw = ia[0]
    # Le pasa lo que vio el editor de fotografía, la noticia de cada foto, el título y el ángulo.
    assert "Estanterías con cajas" in user and "El mostrador vende más" in user
    assert "Frenos: la demanda sube" in user and "El stock manda" in user
    assert kw["tarea"] == "traduccion" and "No inventes" in system


def test_los_veredictos_de_la_eleccion_mandan_sobre_lo_guardado(ia):
    completar(_nota(), {"https://s.com/mostrador.jpg": {"apta": True, "motivo": "Un mostrador con clientes."}})
    assert "Un mostrador con clientes." in ia[0][1]


def test_no_vuelve_a_escribir_los_que_ya_estan(ia):
    nota = _nota()
    nota["imagenes_cuerpo"][0]["epigrafe"] = {"pt": "a", "es": "b", "en": "c"}
    nota["imagenes_cuerpo"][1]["epigrafe"] = {"pt": "a", "es": "b", "en": "c"}
    assert completar(nota) == 0 and ia == []


@pytest.mark.parametrize("respuesta", ["no es json", json.dumps({"epigrafes": [{"n": 1, "pt": "solo pt"}]}),
                                       json.dumps({"epigrafes": [{"n": 9, "pt": "a", "es": "b", "en": "c"}]})])
def test_una_respuesta_mala_deja_la_foto_sin_epigrafe_y_no_lanza(monkeypatch, respuesta):
    monkeypatch.setattr(llm, "completar", lambda *a, **kw: respuesta)
    nota = _nota()
    assert completar(nota) == 0
    assert all("epigrafe" not in im for im in nota["imagenes_cuerpo"])


def test_si_la_ia_falla_no_frena_pero_una_cancelacion_si(monkeypatch):
    def falla(*a, **kw):
        raise llm.ErrorLLM("sin respuesta")
    monkeypatch.setattr(llm, "completar", falla)
    assert completar(_nota()) == 0

    def cancela(*a, **kw):
        raise llm.Cancelada("cancelada")
    monkeypatch.setattr(llm, "completar", cancela)
    with pytest.raises(llm.Cancelada):
        completar(_nota())


def test_en_hubspot_cada_version_lleva_el_epigrafe_en_su_idioma():
    nota = _nota()
    for im, e in zip(nota["imagenes_cuerpo"], RESPUESTA["epigrafes"], strict=True):
        im["epigrafe"] = {c: e[c] for c in ("pt", "es", "en")}
    html = "<p>Intro</p><h3>Uno</h3><p>a</p><h3>Dos</h3><p>b</p><h3>Tres</h3><p>c</p>"
    original = hubspot.con_imagenes(html, hubspot.imagenes_cuerpo(nota))
    espanol = hubspot.con_imagenes(html, hubspot.imagenes_cuerpo(nota, "es"))
    assert "Estoque de pastilhas de freio pronto para reposição</small>" in original
    assert "Stock de pastillas de freno listo para reponer</small>" in espanol and "Estoque" not in espanol


def test_el_epigrafe_y_el_credito_van_juntos_y_se_escapan():
    html = hubspot.con_imagenes("<p>x</p>", [{"url": "https://a/1.jpg", "alt": "a", "epigrafe": "Taller <b>", "credito": "Foto: Ana / CC BY"}])
    assert "Taller &lt;b&gt; · Foto: Ana / CC BY</small>" in html
    assert "<small" not in hubspot.con_imagenes("<p>x</p>", [{"url": "https://a/1.jpg", "alt": "a"}])


def test_al_subir_una_nota_vieja_se_le_escriben_y_se_guardan(ia, monkeypatch):
    monkeypatch.setattr(epigrafes, "completar", completar)
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "1")
    monkeypatch.setattr(historial, "_copiar_imagen_a_hubspot", lambda col, doc: "")
    enviados = []
    monkeypatch.setattr(hubspot, "enviar", lambda doc, publicar=False: enviados.append(doc) or
                        {"id": "9", "url": "https://blog/x", "estado": "DRAFT", "slug": "x"})
    base = mongomock.MongoClient().db
    oid = base.notas_fase2.insert_one({**_nota(), "estado": "aprobada", "categorias": ["frenos"]}).inserted_id
    historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    guardada = base.notas_fase2.find_one({"_id": ObjectId(oid)})
    assert guardada["imagenes_cuerpo"][1]["epigrafe"]["en"] == "The counter drives parts sales"
    assert hubspot.imagenes_cuerpo(enviados[0])[0]["epigrafe"].startswith("Estoque")
