"""Tests de la publicación en HubSpot: qué se manda, cuándo se permite y qué se guarda."""

import mongomock
import pytest
from bson import ObjectId

from afterdrive import db as db_module
from afterdrive import historial, hubspot

NOTA = """# Frenos: la demanda sube en Argentina

## Qué pasó
El mercado de **pastillas de freno** creció un 12 % en el último trimestre.

- Más reposición
- Menos importación

*La demanda de frenos crece y el distribuidor necesita stock de alta rotación.*"""


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture
def hs(monkeypatch):
    """HubSpot falso: anota cada llamada y responde lo que se le cargue."""
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat-test")
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "123")
    llamadas = []
    respuesta = {"status": 200, "body": {"id": "999", "url": "https://blog/frenos", "state": "DRAFT"}}

    def fake(metodo):
        def f(url, json=None, headers=None, timeout=None, params=None):
            llamadas.append({"metodo": metodo, "url": url, "json": json, "headers": headers})
            return Resp(respuesta["status"], respuesta["body"])
        return f

    monkeypatch.setattr(hubspot, "_transporte", {"post": fake("post"), "patch": fake("patch"), "get": fake("get")})
    return llamadas, respuesta


def test_preparar_separa_titulo_meta_y_pasa_a_html():
    p = hubspot.preparar(NOTA)
    assert p["titulo"] == "Frenos: la demanda sube en Argentina"
    assert p["meta"].startswith("La demanda de frenos crece")
    assert "<h1>" not in p["html"] and "<h3>Qué pasó</h3>" in p["html"]
    assert "<strong>pastillas de freno</strong>" in p["html"] and "<li>Más reposición</li>" in p["html"]
    assert "La demanda de frenos crece" not in p["html"]


def test_preparar_sin_titulo_falla_con_mensaje():
    with pytest.raises(hubspot.ErrorHubSpot):
        hubspot.preparar("Texto sin encabezado")


def test_slug_sin_acentos_ni_simbolos():
    assert hubspot._slug("Frenos: la demanda ¡sube! en Córdoba", "a1b2c3") == "frenos-la-demanda-sube-en-cordoba-a1b2c3"


def test_enviar_crea_borrador_con_el_token(hs):
    llamadas, _ = hs
    r = hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})
    assert r["id"] == "999" and r["url"] == "https://blog/frenos" and r["estado"] == "DRAFT"
    assert r["slug"].startswith("frenos-la-demanda")
    c = llamadas[0]
    assert c["metodo"] == "post" and c["url"] == hubspot.API
    assert c["headers"]["Authorization"] == "Bearer pat-test"
    assert c["json"]["contentGroupId"] == "123" and c["json"]["state"] == "DRAFT"
    assert c["json"]["name"] == "Frenos: la demanda sube en Argentina" and c["json"]["slug"].startswith("frenos-la-demanda")


def test_reenviar_actualiza_el_mismo_post_sin_cambiar_el_slug(hs):
    llamadas, _ = hs
    hubspot.enviar({"_id": ObjectId(), "contenido": NOTA, "hubspot": {"id": "999"}}, publicar=True)
    c = llamadas[0]
    assert c["metodo"] == "patch" and c["url"].endswith("/999")
    assert c["json"]["state"] == "PUBLISHED" and "slug" not in c["json"]


@pytest.mark.parametrize("status, texto", [(401, "token"), (404, "HUBSPOT_BLOG_PRUEBAS"), (429, "limitando"), (500, "500")])
def test_errores_de_hubspot_se_explican(hs, status, texto):
    _, respuesta = hs
    respuesta.update(status=status, body={"message": "x"})
    with pytest.raises(hubspot.ErrorHubSpot, match=texto):
        hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})


def test_sin_configurar_no_llama(monkeypatch):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.setattr(hubspot, "_transporte", {"post": None, "patch": None})
    assert not hubspot.configurado()
    with pytest.raises(hubspot.ErrorHubSpot, match="no está configurado"):
        hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})


# ── Flujo completo desde el historial ─────────────────────────────────────────


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def test_solo_las_notas_aprobadas_van_a_hubspot(hs, base):
    llamadas, _ = hs
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "borrador"}).inserted_id
    with pytest.raises(historial.ErrorHistorial, match="Aprobá"):
        historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert llamadas == []


def test_publicar_esta_desactivado_por_ahora(hs, base):
    llamadas, _ = hs
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    with pytest.raises(historial.ErrorHistorial, match="borrador"):
        historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=True, base=base)
    assert llamadas == [] and base.notas_fase2.find_one({"_id": oid})["estado"] == "aprobada"


@pytest.fixture
def publicar_habilitado(monkeypatch):
    monkeypatch.setattr(historial, "PUBLICAR_DESDE_DASHBOARD", True)


def test_publicar_marca_la_nota_y_guarda_el_post(hs, base, publicar_habilitado):
    _, respuesta = hs
    respuesta["body"] = {"id": "777", "url": "https://blog/x", "state": "PUBLISHED"}
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    item = historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=True, base=base)
    assert item["estado"] == "publicado" and item["publicado_en"]
    assert item["hubspot"]["id"] == "777" and item["hubspot"]["url"] == "https://blog/x"


def test_borrador_en_hubspot_no_cambia_el_estado(hs, base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    item = historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert item["estado"] == "aprobada" and item["hubspot"]["estado"] == "DRAFT"


def test_endpoint_enviar(hs, api, monkeypatch, base, publicar_habilitado):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    assert c.get("/api/hubspot/estado").json["configurado"] is True
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    r = c.post("/api/hubspot/enviar", json={"coleccion": "notas_fase2", "id": str(oid), "publicar": True})
    assert r.status_code == 200 and r.json["item"]["estado"] == "publicado"
    hs[1].update(status=401)
    r = c.post("/api/hubspot/enviar", json={"coleccion": "notas_fase2", "id": str(oid), "publicar": True})
    assert r.status_code == 502 and "token" in r.json["error"]


def test_despublicar_tambien_la_saca_del_blog(hs, base):
    llamadas, _ = hs
    oid = base.notas_fase2.insert_one(
        {"contenido": NOTA, "estado": "publicado", "hubspot": {"id": "777", "estado": "PUBLISHED"}}).inserted_id
    item = historial.cambiar_estado("notas_fase2", str(oid), "aprobada", base=base)
    assert item["estado"] == "aprobada" and item["hubspot"]["estado"] == "DRAFT"
    assert llamadas[-1]["metodo"] == "patch" and llamadas[-1]["url"].endswith("/777")
    assert llamadas[-1]["json"] == {"state": "DRAFT"}


def test_si_hubspot_falla_al_despublicar_no_cambia_nada(hs, base):
    _, respuesta = hs
    respuesta.update(status=500)
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "publicado", "hubspot": {"id": "777"}}).inserted_id
    with pytest.raises(hubspot.ErrorHubSpot):
        historial.cambiar_estado("notas_fase2", str(oid), "aprobada", base=base)
    assert base.notas_fase2.find_one({"_id": oid})["estado"] == "publicado"


# ── Notas completas: imagen, etiquetas, vista previa ──────────────────────────


def test_el_html_crudo_del_modelo_no_llega_al_blog():
    p = hubspot.preparar("# Título\n\nTexto <script>alert(1)</script> y <iframe src=x>\n")
    assert "<script>" not in p["html"] and "<iframe" not in p["html"]
    assert "&lt;script&gt;" in p["html"]


def test_imagen_propia_o_por_defecto(hs, monkeypatch):
    llamadas, _ = hs
    hubspot.enviar({"_id": ObjectId(), "contenido": NOTA, "imagen": {"url": "https://img/a.jpg", "alt": "Frenos"}})
    c = llamadas[-1]["json"]
    assert c["useFeaturedImage"] is True and c["featuredImage"] == "https://img/a.jpg" and c["featuredImageAltText"] == "Frenos"
    monkeypatch.setenv("HUBSPOT_IMAGEN_DEFAULT", "https://img/default.jpg")
    hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})
    c = llamadas[-1]["json"]
    assert c["featuredImage"] == "https://img/default.jpg" and c["featuredImageAltText"].startswith("Frenos: la demanda")


def test_sin_imagen_no_se_manda_el_campo(hs, monkeypatch):
    llamadas, _ = hs
    monkeypatch.delenv("HUBSPOT_IMAGEN_DEFAULT", raising=False)
    hubspot.enviar({"_id": ObjectId(), "contenido": NOTA})
    assert "featuredImage" not in llamadas[-1]["json"]


def test_vista_previa_no_llama_a_hubspot(monkeypatch, base):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.setattr(hubspot, "_transporte", {})
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "categorias": ["autopartes"],
                                       "imagen": {"url": "https://img/a.jpg", "alt": "x"}}).inserted_id
    p = historial.vista_previa("notas_fase2", str(oid), base=base)
    assert p["titulo"].startswith("Frenos") and p["etiquetas"] == ["Autopartes"]
    assert p["imagen"]["url"] == "https://img/a.jpg" and p["meta"] and "<h3>" in p["html"]


def test_cambiar_imagen_valida_la_url(base):
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    for mala in ("http://img.com/a.jpg", "https://127.0.0.1/a.jpg", "javascript:alert(1)", "https://localhost/a.jpg",
                 "https://[::1]/a.jpg"):
        with pytest.raises(historial.ErrorHistorial):
            historial.cambiar_imagen("notas_fase2", str(oid), mala, base=base)
    historial.cambiar_imagen("notas_fase2", str(oid), "https://cdn.afterdrive.com/a.jpg", "Frenos", base=base)
    assert base.notas_fase2.find_one({"_id": oid})["imagen"] == {"url": "https://cdn.afterdrive.com/a.jpg", "alt": "Frenos"}
    historial.cambiar_imagen("notas_fase2", str(oid), "", base=base)
    assert "imagen" not in base.notas_fase2.find_one({"_id": oid})


def test_endpoints_imagen_y_vista_previa(api, monkeypatch, base):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "estado": "borrador"}).inserted_id)
    assert c.patch("/api/historial/imagen", json={"coleccion": "notas_fase2", "id": oid, "url": "https://i.com/x.jpg"}).status_code == 200
    r = c.get(f"/api/historial/vista-previa/notas_fase2/{oid}")
    assert r.status_code == 200 and r.json["imagen"]["url"] == "https://i.com/x.jpg"
    assert c.get("/api/historial/vista-previa/articulos/" + oid).status_code == 400


def test_preparar_arregla_el_formato_de_notas_viejas():
    p = hubspot.preparar("# Sube **15%** la venta\nTexto:\n- a\n- b\n\n*Meta con **negrita**.*")
    assert p["titulo"] == "Sube 15% la venta" and p["meta"] == "Meta con negrita."
    assert "<ul>\n<li>a</li>" in p["html"]


# ── Destino: blog, etiquetas y autor según la nota ────────────────────────────


@pytest.fixture
def sin_forzar(monkeypatch):
    monkeypatch.delenv("HUBSPOT_BLOG_PRUEBAS", raising=False)


@pytest.mark.parametrize("regiones, blog, autor", [
    ([], "41065736183", "37798507784"),
    (["argentina"], "41065736183", "37798507784"),
    (["mexico", "europa"], "41065736183", "37798507784"),
    (["brasil"], "43859303259", "192904642075"),
    (["asia"], "43859745706", "194508336788"),
])
def test_el_blog_y_el_autor_salen_del_idioma(sin_forzar, regiones, blog, autor):
    d = hubspot.destino({"regiones": regiones})
    assert d["blog_id"] == blog and d["autor_id"] == autor


def test_sin_blog_en_ese_idioma_no_se_sube(sin_forzar):
    with pytest.raises(hubspot.ErrorHubSpot, match="idioma"):
        hubspot.destino({"regiones": ["china"]})


def test_hubspot_blog_pruebas_fuerza_el_blog_y_el_viejo_blog_id_no(monkeypatch):
    monkeypatch.setenv("HUBSPOT_BLOG_ID", "41065736183")   # heredado: no debe forzar nada
    monkeypatch.delenv("HUBSPOT_BLOG_PRUEBAS", raising=False)
    assert hubspot.destino({"regiones": ["brasil"]})["blog_id"] == "43859303259"
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "114283349257")
    assert hubspot.destino({"regiones": ["brasil"]})["blog_id"] == "114283349257"


def test_etiquetas_existentes_en_el_idioma_del_blog_sin_crear_nuevas(hs, sin_forzar):
    llamadas, _ = hs
    nota = {"_id": ObjectId(), "contenido": NOTA, "regiones": ["brasil"],
            "categorias": ["autopartes", "marketplaces", "inventada"]}
    hubspot.enviar(nota)
    assert [c["metodo"] for c in llamadas] == ["post"] and llamadas[0]["url"] == hubspot.API
    c = llamadas[0]["json"]
    assert c["tagIds"] == ["192987214119", "192964709439"]   # Autopeças y Marketplaces (pt)
    assert c["contentGroupId"] == "43859303259" and c["blogAuthorId"] == "192904642075"


def test_cada_categoria_tiene_su_etiqueta_en_los_tres_idiomas():
    from afterdrive.generacion.scraper_afterdrive import CATEGORIAS
    assert set(CATEGORIAS) == set(hubspot.ETIQUETAS)
    assert all(len(ids) == 3 and all(i.isdigit() for i in ids) for ids in hubspot.ETIQUETAS.values())


def test_el_autor_elegido_manda_y_el_reenvio_no_cambia_el_blog(hs, sin_forzar):
    llamadas, _ = hs
    hubspot.enviar({"_id": ObjectId(), "contenido": NOTA, "hubspot_autor_id": "555", "hubspot": {"id": "999"}})
    c = llamadas[0]["json"]
    assert c["blogAuthorId"] == "555" and "contentGroupId" not in c and "slug" not in c


def test_meta_larga_se_recorta_sin_cortar_palabras():
    meta = "palabra " * 25   # 200 caracteres: más que META_MAX, menos que el tope de 300 de preparar
    p = hubspot.preparar(f"# Título\n\nCuerpo.\n\n*{meta.strip()}*")
    assert len(p["meta"]) <= hubspot.META_MAX and p["meta"].endswith("palabra…")


def test_enviar_guarda_el_autor_elegido(hs, base):
    llamadas, _ = hs
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada"}).inserted_id
    historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base, autor_id="555")
    assert base.notas_fase2.find_one({"_id": oid})["hubspot_autor_id"] == "555"
    assert llamadas[-1]["json"]["blogAuthorId"] == "555"
    with pytest.raises(historial.ErrorHistorial, match="Autor"):
        historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base, autor_id="1; drop")


def test_endpoint_destino_lista_los_autores_del_idioma(hs, api, monkeypatch, base, sin_forzar):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    hs[1]["body"] = {"results": [{"id": 2, "fullName": "Zoe", "language": "pt"},
                                 {"id": 1, "fullName": "Ana", "language": "pt"},
                                 {"id": 3, "fullName": "Bob", "language": "es"}]}
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "regiones": ["brasil"], "categorias": ["eventos"]}).inserted_id
    r = c.get(f"/api/hubspot/destino/notas_fase2/{oid}")
    assert r.status_code == 200
    assert r.json["blog_id"] == "43859303259" and r.json["etiquetas"] == ["Eventos"]
    assert [a["nombre"] for a in r.json["autores"]] == ["Ana", "Zoe"] and "tag_ids" not in r.json


def test_nota_sin_blog_en_su_idioma_no_llama_a_hubspot_ni_sube_la_imagen(hs, base):
    llamadas, _ = hs
    oid = base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada", "regiones": ["china"],
                                       "imagen": {"url": "https://img.com/a.jpg"}}).inserted_id
    with pytest.raises(hubspot.ErrorHubSpot, match="idioma"):
        historial.enviar_a_hubspot("notas_fase2", str(oid), publicar=False, base=base)
    assert llamadas == [] and "hubspot" not in base.notas_fase2.find_one({"_id": oid})


def test_actualizar_no_pisa_autor_ni_etiquetas_cambiados_en_hubspot(hs, sin_forzar):
    llamadas, _ = hs
    hubspot.enviar({"_id": ObjectId(), "contenido": NOTA, "hubspot": {"id": "999"}})
    c = llamadas[0]["json"]
    assert "blogAuthorId" not in c and "tagIds" not in c


def test_switch_apagado_ignora_blog_de_pruebas(monkeypatch):
    from afterdrive import config_store
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "123")
    monkeypatch.setattr(config_store, "get_blog_pruebas_config", lambda: False)
    assert hubspot.blog_pruebas() == ""
    assert hubspot.destino({"regiones": ["brasil"]})["blog_id"] == "43859303259"
    monkeypatch.setattr(config_store, "get_blog_pruebas_config", lambda: True)
    assert hubspot.destino({"regiones": ["brasil"]})["blog_id"] == "123"
