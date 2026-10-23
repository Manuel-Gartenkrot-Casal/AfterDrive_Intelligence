"""Tests de la imagen destacada: la foto del artículo scrapeado, elegida para la nota y copiada a HubSpot."""

import json

import mongomock
import pytest
from bson import ObjectId

from afterdrive import historial, hubspot, imagen_web
from afterdrive.generacion import contexto_noticias
from afterdrive.generacion.contexto_noticias import Noticia
from afterdrive.ingesta import imagen_articulo

# Capturada al importar, antes de que conftest la reemplace para que los tests no descarguen páginas.
_BUSCAR_IMAGEN = contexto_noticias._buscar_imagen
JPG = b"\xff\xd8\xff\xe0falso"


# ── Extracción desde el HTML ──────────────────────────────────────────────────


def _html(cabeza="", cuerpo=""):
    return f"<html><head>{cabeza}</head><body>{cuerpo}</body></html>"


def test_toma_og_image_con_su_alt():
    html = _html('<meta property="og:image" content="https://cdn.sitio.com/fotos/frenos.jpg">'
                 '<meta property="og:image:alt" content="Pastillas de freno">')
    assert imagen_articulo.extraer(html, "https://sitio.com/nota") == {
        "url": "https://cdn.sitio.com/fotos/frenos.jpg", "alt": "Pastillas de freno"}


def test_rutas_relativas_y_sin_esquema_se_completan():
    assert imagen_articulo.extraer(_html('<meta property="og:image" content="/img/a.jpg">'),
                                   "https://sitio.com/2026/nota")["url"] == "https://sitio.com/img/a.jpg"
    assert imagen_articulo.extraer(_html('<meta name="twitter:image" content="//cdn.sitio.com/b.png">'),
                                   "https://sitio.com/nota")["url"] == "https://cdn.sitio.com/b.png"


def test_salta_logos_e_iconos_y_sigue_con_la_siguiente():
    html = _html('<meta property="og:image" content="https://sitio.com/wp-content/logo.png">'
                 '<meta name="twitter:image" content="https://sitio.com/favicon-192.png">',
                 '<article><img src="data:image/gif;base64,R0lG"><img src="https://sitio.com/up/silicone-hose.jpg"></article>')
    assert imagen_articulo.extraer(html, "https://sitio.com/nota")["url"] == "https://sitio.com/up/silicone-hose.jpg"


def test_json_ld_con_graph_e_imagen_objeto():
    ld = {"@graph": [{"@type": "WebPage"}, {"@type": "NewsArticle", "image": {"url": "https://s.com/ld.webp"}}]}
    html = _html(f'<script type="application/ld+json">{json.dumps(ld)}</script>')
    assert imagen_articulo.extraer(html, "https://s.com/n")["url"] == "https://s.com/ld.webp"


@pytest.mark.parametrize("mala", ["http://s.com/a.jpg", "https://s.com/a.svg", "https://s.com/anim.gif",
                                  "https://s.com/images/default.jpg", "javascript:alert(1)"])
def test_sin_imagen_usable_devuelve_none(mala):
    assert imagen_articulo.extraer(_html(f'<meta property="og:image" content="{mala}">'), "https://s.com/n") is None
    assert imagen_articulo.extraer("", "https://s.com/n") is None


def test_el_scraper_guarda_la_imagen_con_el_articulo():
    from afterdrive.ingesta import scraper
    cuerpo = "<article><h1>Frenos</h1>" + "".join(
        f"<p>Párrafo {i}: el mercado de pastillas de freno crece en la región y los distribuidores ajustan stock.</p>"
        for i in range(8)) + "</article>"
    html = _html('<title>Frenos</title><meta property="og:image" content="https://s.com/f.jpg">', cuerpo)
    art = scraper._extraer_articulo(html, "https://s.com/nota")
    assert art and art["imagen"]["url"] == "https://s.com/f.jpg"


# ── Elección para la nota ─────────────────────────────────────────────────────


def _noticia(i, imagen=None, buscada=None):
    return Noticia(id=i, titulo=f"Noticia {i}", cuerpo="x", url=f"https://n.com/{i}",
                   imagen={"url": imagen, "alt": ""} if imagen else None,
                   imagen_buscada=buscada if buscada is not None else imagen is not None)


def test_las_candidatas_son_las_noticias_con_foto_en_orden():
    con = contexto_noticias.con_foto([_noticia(1, buscada=True), _noticia(2, "https://n.com/2.jpg"),
                                      _noticia(3, "https://n.com/3.jpg")])
    assert [n.id for n in con] == [2, 3]
    assert contexto_noticias.imagen_de(con[0]) == {"url": "https://n.com/2.jpg", "alt": "",
                                                   "origen": {"titulo": "Noticia 2", "url": "https://n.com/2"}}
    assert contexto_noticias.con_foto([_noticia(1, buscada=True)]) == []
    assert len(contexto_noticias.con_foto([_noticia(i, f"https://n.com/{i}.jpg") for i in range(9)], limite=4)) == 4


def test_articulos_viejos_se_buscan_una_vez_y_queda_guardado(monkeypatch):
    from afterdrive import db
    from afterdrive.ingesta import scraper
    col = mongomock.MongoClient().db.articulos
    col.insert_many([{"_id": 1}, {"_id": 2}])
    monkeypatch.setattr(db, "col_articulos", col)
    monkeypatch.setattr(contexto_noticias, "_buscar_imagen", _BUSCAR_IMAGEN)
    paginas = {"https://n.com/1": _html(), "https://n.com/2": _html('<meta property="og:image" content="https://n.com/2.jpg">')}
    pedidas = []
    monkeypatch.setattr(scraper, "descargar", lambda url: pedidas.append(url) or paginas[url])
    con = contexto_noticias.con_foto([_noticia(1), _noticia(2)])
    assert con[0].imagen["url"] == "https://n.com/2.jpg" and pedidas == ["https://n.com/1", "https://n.com/2"]
    assert col.find_one({"_id": 1})["imagen"] is None   # buscada y sin foto: no se vuelve a descargar
    assert col.find_one({"_id": 2})["imagen"]["url"] == "https://n.com/2.jpg"


def test_como_mucho_tres_descargas_por_nota_y_si_la_pagina_no_responde_no_se_marca(monkeypatch):
    from afterdrive import db
    from afterdrive.ingesta import scraper
    col = mongomock.MongoClient().db.articulos
    monkeypatch.setattr(db, "col_articulos", col)
    monkeypatch.setattr(contexto_noticias, "_buscar_imagen", _BUSCAR_IMAGEN)
    pedidas = []
    monkeypatch.setattr(scraper, "descargar", lambda url: pedidas.append(url))
    assert contexto_noticias.con_foto([_noticia(i) for i in range(5)]) == []
    assert len(pedidas) == 3 and col.count_documents({"imagen": {"$exists": True}}) == 0


def test_desde_doc_distingue_sin_buscar_de_buscada_sin_foto():
    assert contexto_noticias._desde_doc({"_id": 1}).imagen_buscada is False
    n = contexto_noticias._desde_doc({"_id": 1, "imagen": None})
    assert n.imagen_buscada is True and n.imagen is None
    assert contexto_noticias._desde_doc({"_id": 1, "imagen": {"url": "https://a.com/x.jpg"}}).imagen["url"] == "https://a.com/x.jpg"


# ── Revisión y HubSpot ────────────────────────────────────────────────────────


@pytest.fixture
def base():
    return mongomock.MongoClient().db


@pytest.fixture
def nota(base):
    return str(base.notas_fase2.insert_one({
        "contenido": "# Frenos en el mostrador\n\nTexto.", "estado": "aprobada", "categorias": ["frenos"],
        "fuentes": [{"titulo": "Frasle amplía", "url": "https://n.com/1", "imagen": "https://n.com/1.jpg"},
                    {"titulo": "Sin foto", "url": "https://n.com/2"}],
        "imagen": {"url": "https://n.com/1.jpg", "alt": "Frenos", "origen": {"titulo": "Frasle amplía", "url": "https://n.com/1"}},
    }).inserted_id)


def test_la_vista_previa_ofrece_las_fotos_de_las_noticias(base, nota):
    previa = historial.vista_previa("notas_fase2", nota, base=base)
    assert previa["imagen"]["url"] == "https://n.com/1.jpg"
    assert previa["imagenes_noticias"] == [{"url": "https://n.com/1.jpg", "titulo": "Frasle amplía", "noticia": "https://n.com/1"}]


def test_elegir_la_foto_de_una_noticia_recuerda_de_cual_es(base, nota):
    historial.cambiar_imagen("notas_fase2", nota, "https://otra.com/x.jpg", "x", base=base)
    assert base.notas_fase2.find_one({"_id": ObjectId(nota)})["imagen"] == {"url": "https://otra.com/x.jpg", "alt": "x"}
    historial.cambiar_imagen("notas_fase2", nota, "https://n.com/1.jpg", "Frenos", base=base)
    assert base.notas_fase2.find_one({"_id": ObjectId(nota)})["imagen"]["origen"]["url"] == "https://n.com/1"


class RespImg:
    def __init__(self, status=200, contenido=JPG, tipo="image/jpeg", location=None):
        self.status_code, self._contenido = status, contenido
        self.headers = {"Content-Type": tipo, **({"Location": location} if location else {})}

    def iter_content(self, n):
        yield self._contenido


@pytest.fixture
def hubspot_falso(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "1")
    from afterdrive.ingesta import scraper
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    enviados = []
    monkeypatch.setattr(hubspot, "enviar", lambda doc, publicar=False: enviados.append(doc) or
                        {"id": "9", "url": "https://blog/x", "estado": "DRAFT", "slug": "x"})
    return enviados


def test_al_enviar_se_copia_la_foto_a_hubspot_una_sola_vez(base, nota, monkeypatch, hubspot_falso):
    monkeypatch.setitem(imagen_web._transporte, "get", lambda url, **kw: RespImg())
    subidas = []
    monkeypatch.setattr(hubspot, "subir_imagen", lambda c, m, n: subidas.append((c, m, n)) or "https://hs/img.jpg")
    item = historial.enviar_a_hubspot("notas_fase2", nota, publicar=False, base=base)
    assert subidas == [(JPG, "image/jpeg", f"nota-{nota}.jpg")] and "aviso" not in item
    assert hubspot_falso[0]["imagen"]["hubspot_url"] == "https://hs/img.jpg"
    guardada = base.notas_fase2.find_one({"_id": ObjectId(nota)})["imagen"]
    assert guardada["hubspot_url"] == "https://hs/img.jpg" and guardada["url"] == "https://n.com/1.jpg"
    historial.enviar_a_hubspot("notas_fase2", nota, publicar=False, base=base)
    assert len(subidas) == 1


def test_hubspot_usa_la_copia_y_si_no_hay_el_link_original(monkeypatch):
    monkeypatch.delenv("HUBSPOT_IMAGEN_DEFAULT", raising=False)
    assert hubspot._imagen({"imagen": {"url": "https://n.com/1.jpg", "hubspot_url": "https://hs/1.jpg"}}, "T")["url"] == "https://hs/1.jpg"
    assert hubspot._imagen({"imagen": {"url": "https://n.com/1.jpg"}}, "T") == {"url": "https://n.com/1.jpg", "alt": "T"}


@pytest.mark.parametrize("resp, texto", [
    (RespImg(404), "404"), (RespImg(tipo="text/html"), "no es una imagen"), (RespImg(tipo="image/svg+xml"), "no es una imagen"),
    (RespImg(contenido=b""), "vacía"), (RespImg(302, location="https://127.0.0.1/x.jpg"), "https pública"),
])
def test_si_no_se_puede_copiar_se_sube_igual_con_el_link_original(base, nota, monkeypatch, hubspot_falso, resp, texto):
    monkeypatch.setitem(imagen_web._transporte, "get", lambda url, **kw: resp)
    monkeypatch.setattr(hubspot, "subir_imagen", lambda c, m, n: pytest.fail("no debería subir"))
    item = historial.enviar_a_hubspot("notas_fase2", nota, publicar=False, base=base)
    assert texto in item["aviso"] and "link original" in item["aviso"]
    assert len(hubspot_falso) == 1 and hubspot_falso[0]["imagen"]["url"] == "https://n.com/1.jpg"


def test_la_descarga_valida_cada_redireccion_contra_la_red_interna(monkeypatch):
    from afterdrive.ingesta import scraper
    monkeypatch.setattr(scraper, "url_publica", lambda url: "interno" not in url)
    saltos = iter([RespImg(301, location="https://interno.local.com/x.jpg")])
    monkeypatch.setitem(imagen_web._transporte, "get", lambda url, **kw: next(saltos))
    with pytest.raises(imagen_web.ErrorDescarga, match="https pública"):
        imagen_web.descargar("https://n.com/1.jpg")


def test_una_imagen_demasiado_pesada_no_se_copia(monkeypatch):
    from afterdrive.ingesta import scraper
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    monkeypatch.setattr(imagen_web, "MAX_BYTES", 3)
    monkeypatch.setitem(imagen_web._transporte, "get", lambda url, **kw: RespImg())
    with pytest.raises(imagen_web.ErrorDescarga, match="MB"):
        imagen_web.descargar("https://n.com/1.jpg")


def test_subir_imagen_a_hubspot(monkeypatch):
    class Resp:
        def __init__(self, status=200, body=None):
            self.status_code, self._body, self.text = status, body or {}, ""

        def json(self):
            return self._body
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    llamadas = []
    monkeypatch.setitem(hubspot._transporte, "subir", lambda url, **kw: llamadas.append((url, kw)) or
                        Resp(body={"url": "https://f.hubspotusercontent.com/a.jpg"}))
    assert hubspot.subir_imagen(JPG, "image/jpeg", "nota.jpg") == "https://f.hubspotusercontent.com/a.jpg"
    url, kw = llamadas[0]
    assert url == hubspot.API_ARCHIVOS and kw["files"]["file"] == ("nota.jpg", JPG, "image/jpeg")
    assert json.loads(kw["data"]["options"])["access"] == "PUBLIC_INDEXABLE"
    monkeypatch.setitem(hubspot._transporte, "subir", lambda url, **kw: Resp(403))
    with pytest.raises(hubspot.ErrorHubSpot, match="files"):
        hubspot.subir_imagen(JPG, "image/jpeg", "nota.jpg")


# ── Elección con IA ───────────────────────────────────────────────────────────


@pytest.fixture
def ia_fotos(monkeypatch):
    """IA paga con visión, descargas falsas y la respuesta del modelo a elección."""
    from afterdrive.generacion import imagen_destacada  # noqa: F401
    from afterdrive.ia import llm
    monkeypatch.setattr(llm, "ve_imagenes", lambda: True)
    descargas, pedidos = {}, []

    def descargar(url, max_bytes=None):
        if url in descargas:
            raise descargas[url]
        return JPG, "image/jpeg"
    monkeypatch.setattr(imagen_web, "descargar", descargar)

    def responder(texto):
        def completar(system, user, **kw):
            pedidos.append({"user": user, **kw})
            if isinstance(texto, Exception):
                raise texto
            return texto
        monkeypatch.setattr(llm, "completar", completar)
    return responder, descargas, pedidos


def _con_fotos(n):
    return [_noticia(i, f"https://n.com/{i}.jpg") for i in range(1, n + 1)]


def test_la_ia_elige_la_foto_mas_apta(ia_fotos):
    from afterdrive.generacion import imagen_destacada
    responder, _, pedidos = ia_fotos
    responder('{"fotos": [{"n": 1, "apta": false, "motivo": "Es un logo."}, {"n": 2, "apta": true, "motivo": "Un depósito."}],'
              ' "elegida": 2}')
    e = imagen_destacada.elegir(_con_fotos(2), "Stock en el depósito", "La rotación manda")
    assert e.metodo == "ia" and e.imagen["url"] == "https://n.com/2.jpg"
    assert e.veredictos["https://n.com/1.jpg"] == {"apta": False, "motivo": "Es un logo."}
    assert pedidos[0]["tarea"] == "clasificacion" and len(pedidos[0]["imagenes"]) == 2
    assert "Stock en el depósito" in pedidos[0]["user"] and "Noticia 2" in pedidos[0]["user"]


def test_si_la_ia_las_descarta_todas_la_nota_queda_sin_imagen(ia_fotos):
    from afterdrive.generacion import imagen_destacada
    responder, _, _ = ia_fotos
    responder('{"fotos": [{"n": 1, "apta": false, "motivo": "Banner publicitario."}], "elegida": null}')
    e = imagen_destacada.elegir(_con_fotos(1), "T")
    assert e.imagen is None and e.metodo == "ia" and "Banner publicitario" in e.motivo


def test_una_elegida_marcada_como_no_apta_no_se_usa(ia_fotos):
    from afterdrive.generacion import imagen_destacada
    responder, _, _ = ia_fotos
    responder('{"fotos": [{"n": 1, "apta": false, "motivo": "Gráfico."}], "elegida": 1}')
    assert imagen_destacada.elegir(_con_fotos(1), "T").imagen is None


@pytest.mark.parametrize("falla", ["no es json", RuntimeError("Bedrock caído")])
def test_si_la_ia_falla_va_la_primera(ia_fotos, falla):
    from afterdrive.generacion import imagen_destacada
    responder, _, _ = ia_fotos
    responder(falla)
    e = imagen_destacada.elegir(_con_fotos(2), "T")
    assert e.metodo == "primera" and e.imagen["url"] == "https://n.com/1.jpg" and e.motivo


def test_las_que_no_se_descargan_no_van_a_la_ia(ia_fotos):
    from afterdrive.generacion import imagen_destacada
    responder, descargas, pedidos = ia_fotos
    descargas["https://n.com/1.jpg"] = imagen_web.ErrorDescarga("el sitio respondió 403")
    responder('{"fotos": [{"n": 1, "apta": true, "motivo": "Taller."}], "elegida": 1}')
    e = imagen_destacada.elegir(_con_fotos(2), "T")
    assert e.imagen["url"] == "https://n.com/2.jpg" and len(pedidos[0]["imagenes"]) == 1
    assert "403" in e.veredictos["https://n.com/1.jpg"]["motivo"]


def test_sin_api_paga_no_se_llama_a_la_ia(monkeypatch):
    from afterdrive.generacion import imagen_destacada
    from afterdrive.ia import llm
    monkeypatch.setattr(llm, "ve_imagenes", lambda: False)
    monkeypatch.setattr(llm, "completar", lambda *a, **k: pytest.fail("no debería llamar a la IA"))
    e = imagen_destacada.elegir(_con_fotos(2), "T")
    assert e.metodo == "primera" and e.imagen["url"] == "https://n.com/1.jpg"
    assert imagen_destacada.elegir([], "T").metodo == "ninguna"
