"""Tests del autor de cada idioma en HubSpot: la lista para elegir y quién firma las traducciones."""

import pytest
from bson import ObjectId

from afterdrive import hubspot

AUTORES = [
    {"id": 10, "fullName": "Ana Pérez", "language": "es-ar"},
    {"id": 11, "fullName": "Ana Pérez", "language": "pt-br", "translatedFromId": 10},
    {"id": 12, "fullName": "Ana Pérez", "language": "en", "translatedFromId": 10},
    {"id": 20, "fullName": "Bruno Lima", "language": "pt-br"},
    {"id": 21, "fullName": "Bruno Lima", "language": "es"},          # sin vincular: se encuentra por nombre
    {"id": 30, "fullName": "Carla Solo", "language": "es"},          # sin versión en otros idiomas
    {"id": 40, "fullName": "Equipo", "language": ""},               # sin idioma: sirve para todos
]


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture
def hs(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.delenv("HUBSPOT_BLOG_PRUEBAS", raising=False)
    llamadas, estado = [], {"autores": Resp(200, {"results": AUTORES})}

    def fake(metodo):
        def f(url, json=None, headers=None, timeout=None, params=None):
            llamadas.append({"metodo": metodo, "url": url, "json": json})
            if metodo == "get" and url == hubspot.API_AUTORES:
                return estado["autores"]
            if url.endswith("/create-language-variation"):
                return Resp(200, {"id": "222"})
            return Resp(200, {"id": "222", "url": "https://blog/x", "state": "DRAFT"})
        return f
    monkeypatch.setattr(hubspot, "_transporte", {"post": fake("post"), "patch": fake("patch"), "get": fake("get")})
    return llamadas, estado


def test_la_lista_de_autores_entiende_los_idiomas_con_variante(hs):
    # Antes se comparaba "pt" == "pt-br" y la lista en portugués salía vacía.
    assert [a["id"] for a in hubspot.autores("pt")] == ["11", "20"]
    assert [a["nombre"] for a in hubspot.autores("es")] == ["Ana Pérez", "Bruno Lima", "Carla Solo"]


@pytest.mark.parametrize("autor, cod, esperado", [
    ("10", "pt", "11"),     # vinculados con translatedFromId
    ("11", "en", "12"),     # desde una traducción, al resto del grupo
    ("12", "es", "10"),
    ("20", "es", "21"),     # mismo nombre
    ("30", "pt", None),     # no tiene versión en portugués
    ("40", "en", "40"),     # sin idioma
    ("99", "pt", None),     # no existe
])
def test_autor_en_idioma(autor, cod, esperado):
    assert hubspot.autor_en_idioma(autor, cod, lista=AUTORES) == esperado


NOTA_PT = "# Freios: a demanda cresce\n\n## O que aconteceu\nTexto.\n\n*Meta.*"
DOC = {"_id": ObjectId("65a1b2c3d4e5f60718293a4b"), "idioma": "es", "categorias": []}


def _autor_del_borrador(llamadas):
    return next(c["json"]["blogAuthorId"] for c in llamadas if c["metodo"] == "patch")


def test_la_traduccion_la_firma_el_mismo_autor_en_su_idioma(hs):
    llamadas, _ = hs
    hubspot.enviar_traduccion({**DOC, "hubspot_autor_id": "10"}, "pt", NOTA_PT, "111")
    assert _autor_del_borrador(llamadas) == "11"


def test_sin_version_en_ese_idioma_firma_el_autor_por_defecto(hs):
    llamadas, _ = hs
    hubspot.enviar_traduccion({**DOC, "hubspot_autor_id": "30"}, "pt", NOTA_PT, "111")
    assert _autor_del_borrador(llamadas) == hubspot.AUTOR_POR_DEFECTO["pt"]


def test_si_hubspot_no_da_los_autores_firma_el_autor_por_defecto(hs):
    llamadas, estado = hs
    estado["autores"] = Resp(500, {"message": "error"})
    hubspot.enviar_traduccion({**DOC, "hubspot_autor_id": "10"}, "en", NOTA_PT, "111")
    assert _autor_del_borrador(llamadas) == hubspot.AUTOR_POR_DEFECTO["en"]


def test_sin_autor_elegido_no_consulta_los_autores(hs):
    llamadas, _ = hs
    hubspot.enviar_traduccion(DOC, "pt", NOTA_PT, "111")
    assert _autor_del_borrador(llamadas) == hubspot.AUTOR_POR_DEFECTO["pt"]
    assert not any(c["url"] == hubspot.API_AUTORES for c in llamadas)
