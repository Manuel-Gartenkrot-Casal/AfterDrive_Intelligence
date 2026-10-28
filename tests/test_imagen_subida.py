"""Imagen destacada elegida desde la computadora: se guarda en la base y se copia a HubSpot desde ahí."""

import io

import mongomock
import pytest
from bson import ObjectId

from afterdrive import db as db_module
from afterdrive import historial, hubspot, imagen_web

NOTA = "# Frenos: la demanda sube\n\n## Qué pasó\nTexto.\n\n*La demanda de frenos crece.*"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def _nota(base, **extra):
    return base.notas_fase2.insert_one({"contenido": NOTA, "estado": "borrador", **extra}).inserted_id


def test_subir_imagen_la_guarda_y_la_deja_como_destacada(base):
    oid = _nota(base)
    r = historial.subir_imagen("notas_fase2", str(oid), PNG, "  foto  frenos.png ", "Pastillas", base=base)
    url = r["imagen"]["url"]
    assert url.startswith(historial.PREFIJO_IMAGEN_SUBIDA)
    assert base.notas_fase2.find_one({"_id": oid})["imagen"] == {"url": url, "alt": "Pastillas", "subida": {"nombre": "foto frenos.png"}}
    assert historial.imagen_subida(url.rsplit("/", 1)[1], base=base) == (PNG, "image/png")
    assert historial.imagen_subida("no-es-un-id", base=base) is None


@pytest.mark.parametrize("contenido, motivo", [(b"", "vacío"), (b"<svg></svg>", "no es una imagen"),
                                                (b"GIF89a" + b"0" * historial.IMAGEN_SUBIDA_MAX, "5 MB")])
def test_subir_imagen_valida_el_archivo(base, contenido, motivo):
    with pytest.raises(historial.ErrorHistorial, match=motivo):
        historial.subir_imagen("notas_fase2", str(_nota(base)), contenido, base=base)


def test_subir_imagen_a_una_nota_que_no_existe_o_de_otra_coleccion(base):
    assert historial.subir_imagen("notas_fase2", str(ObjectId()), JPG, base=base) is None
    with pytest.raises(historial.ErrorHistorial):
        historial.subir_imagen("articulos", str(ObjectId()), JPG, base=base)


def test_la_vista_previa_muestra_la_subida_hasta_que_tenga_copia_en_hubspot(base, monkeypatch):
    monkeypatch.delenv("HUBSPOT_IMAGEN_DEFAULT", raising=False)
    oid = _nota(base)
    url = historial.subir_imagen("notas_fase2", str(oid), JPG, "a.jpg", base=base)["imagen"]["url"]
    assert historial.vista_previa("notas_fase2", str(oid), base=base)["imagen"]["url"] == url
    base.notas_fase2.update_one({"_id": oid}, {"$set": {"imagen.hubspot_url": "https://hs/a.jpg"}})
    assert historial.vista_previa("notas_fase2", str(oid), base=base)["imagen"]["url"] == "https://hs/a.jpg"


def test_al_subir_a_hubspot_se_copia_desde_la_base_sin_descargar(base, monkeypatch):
    subidas = []
    monkeypatch.setattr(imagen_web, "descargar", lambda *a, **k: pytest.fail("no tenía que descargar nada"))
    monkeypatch.setattr(hubspot, "subir_imagen", lambda contenido, mime, nombre: subidas.append((contenido, mime, nombre)) or "https://hs/f.png")
    oid = _nota(base)
    historial.subir_imagen("notas_fase2", str(oid), PNG, "f.png", base=base)
    doc = base.notas_fase2.find_one({"_id": oid})
    assert historial._copiar_imagen_a_hubspot(base.notas_fase2, doc) == ""
    assert subidas == [(PNG, "image/png", f"nota-{oid}.png")]
    assert base.notas_fase2.find_one({"_id": oid})["imagen"]["hubspot_url"] == "https://hs/f.png"


def test_una_ruta_de_este_servidor_nunca_va_a_hubspot_como_imagen(monkeypatch):
    monkeypatch.delenv("HUBSPOT_IMAGEN_DEFAULT", raising=False)
    assert hubspot._imagen({"imagen": {"url": "/api/imagenes/abc", "alt": "x"}}, "T") == {}
    assert hubspot._imagen({"imagen": {"url": "/api/imagenes/abc", "hubspot_url": "https://hs/a.jpg"}}, "T")["url"] == "https://hs/a.jpg"


@pytest.fixture
def client(api, monkeypatch, base):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c


def test_endpoints_de_subida(client, base):
    oid = str(_nota(base))
    r = client.post("/api/historial/imagen/archivo", content_type="multipart/form-data",
                    data={"coleccion": "notas_fase2", "id": oid, "alt": "Frenos", "archivo": (io.BytesIO(PNG), "f.png")})
    assert r.status_code == 200
    img = client.get(r.json["imagen"]["url"])
    assert img.status_code == 200 and img.data == PNG and img.mimetype == "image/png"
    assert client.post("/api/historial/imagen/archivo", content_type="multipart/form-data",
                       data={"coleccion": "notas_fase2", "id": oid, "archivo": (io.BytesIO(b"hola"), "x.txt")}).status_code == 400
    assert client.post("/api/historial/imagen/archivo", data={"coleccion": "notas_fase2", "id": oid}).status_code == 400
    assert client.get("/api/imagenes/" + str(ObjectId())).status_code == 404


def test_las_imagenes_subidas_piden_sesion(api, monkeypatch, base):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    assert flask_api.app.test_client().get("/api/imagenes/" + str(ObjectId())).status_code == 401
