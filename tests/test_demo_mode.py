"""scripts/demo_mode.py: datos de ejemplo y que la demo nunca suba al blog real."""

import json

import mongomock

from scripts import demo_mode


def test_los_datos_de_ejemplo_estan_marcados_como_ejemplo():
    items = json.loads(demo_mode.DATOS_EJEMPLO.read_text(encoding="utf-8"))
    assert len(items) >= 3
    for i in items:
        assert i["cuerpo"].startswith("Ejemplo para la demo.") and i["url"].startswith("https://demo.afterdrive.invalid/")
        assert len(i["cuerpo"]) > 100 and i["titulo"]


def test_cargar_y_limpiar_ejemplos():
    base = mongomock.MongoClient().db
    base.articulos.insert_one({"url": "https://real.com/nota", "titulo": "Real", "cuerpo": "x"})
    n = demo_mode.cargar_ejemplos(base, embeber=False)
    assert base.articulos.count_documents({"demo": True}) == n
    assert demo_mode.cargar_ejemplos(base, embeber=False) == n and base.articulos.count_documents({}) == n + 1
    assert demo_mode.limpiar_ejemplos(base) == n
    assert base.articulos.count_documents({}) == 1   # la noticia real queda


def test_sin_blog_de_pruebas_no_sube_a_hubspot(monkeypatch):
    from afterdrive import historial, hubspot
    monkeypatch.setattr(hubspot, "configurado", lambda: True)
    monkeypatch.setattr(hubspot, "blog_pruebas", lambda: "")
    llamadas = []
    monkeypatch.setattr(historial, "cambiar_estado", lambda *a, **k: llamadas.append(a))
    monkeypatch.setattr(historial, "enviar_a_hubspot", lambda *a, **k: llamadas.append(a))
    assert demo_mode.subir_a_pruebas("0" * 24) is None and llamadas == []


def test_con_blog_de_pruebas_sube_como_borrador(monkeypatch):
    from afterdrive import historial, hubspot
    monkeypatch.setattr(hubspot, "configurado", lambda: True)
    monkeypatch.setattr(hubspot, "blog_pruebas", lambda: "123")
    llamadas = []
    monkeypatch.setattr(historial, "cambiar_estado", lambda col, i, estado: llamadas.append(estado))

    def enviar(col, i, publicar):
        llamadas.append(publicar)
        return {"hubspot": {"id": "9"}}
    monkeypatch.setattr(historial, "enviar_a_hubspot", enviar)
    assert demo_mode.subir_a_pruebas("0" * 24) == {"hubspot": {"id": "9"}}
    assert llamadas == ["aprobada", False]
