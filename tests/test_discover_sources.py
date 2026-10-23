"""Tests de "Buscar recomendaciones" (discover_sources.py), sin red."""

import mongomock
import pytest

from afterdrive.ia import llm
from afterdrive.ingesta import discover_sources as ds
from afterdrive.ingesta import scraper


class Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text = status, text


DDG_OK = """<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.revistarepuestos.com.ar%2Fnota%2F1">
Revista Repuestos: novedades del aftermarket</a><a class="result__snippet">Noticias de autopartes y talleres</a></div>
<div class="result"><a class="result__a" href="https://www.youtube.com/watch?v=1">Video de repuestos</a></div>
<div class="result"><a class="result__a" href="https://cocina.com/receta">Recetas</a><a class="result__snippet">Tortas</a></div>"""

BING_OK = """<li class="b_algo"><h2><a href="https://autopecas.com.br/noticias/x">Autopeças hoje</a></h2>
<div class="b_caption"><p>Notícias do mercado de reposição automotiva e autopeças</p></div></li>"""

PORTADA = "<html><head><title>Diario del Repuesto</title></head><body>Noticias de repuestos y autopartes" + "".join(
    f'<a href="https://diariorepuesto.com/nota/{i}">Una nota larga sobre el mercado de repuestos {i}</a>' for i in range(5)
) + "</body></html>"


@pytest.fixture
def base(monkeypatch):
    db = mongomock.MongoClient().db
    db.trusted_urls.insert_one({"url": "https://ya-confiable.com/"})
    monkeypatch.setattr(ds, "_dormir", lambda s: None)
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    return db


def _sin_ia(monkeypatch):
    def falla(*a, **k):
        raise llm.ErrorLLM("sin proveedor")
    monkeypatch.setattr(llm, "completar", falla)


def test_guarda_los_sitios_del_sector_que_encuentra_duckduckgo(base, monkeypatch):
    _sin_ia(monkeypatch)
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(text=DDG_OK), "get": lambda url, **k: Resp(404)})
    r = ds.discover(base)
    doms = [d["dominio"] for d in base.suggested_urls.find()]
    assert doms == ["revistarepuestos.com.ar"] and r["guardadas"] == 1   # sin youtube ni recetas
    guardada = base.suggested_urls.find_one()
    assert guardada["url"] == "https://www.revistarepuestos.com.ar/" and guardada["origen"] == "buscador"


def test_si_duckduckgo_bloquea_pasa_a_bing(base, monkeypatch):
    _sin_ia(monkeypatch)
    pedidos = []

    def post(url, **k):
        pedidos.append(url)
        return Resp(202, "<html>anomaly-modal</html>") if "html.duck" in url else Resp(200, "<div id='anomaly-modal'>")
    monkeypatch.setattr(ds, "_transporte", {"post": post, "get": lambda url, **k: Resp(text=BING_OK)})
    r = ds.discover(base)
    assert [d["dominio"] for d in base.suggested_urls.find()] == ["autopecas.com.br"]
    assert len(r["motores_bloqueados"]) == 2
    # Los buscadores bloqueados no se vuelven a probar en cada búsqueda.
    assert pedidos.count("https://html.duckduckgo.com/html/") == 1


def test_si_todos_bloquean_la_ia_sugiere_y_solo_quedan_los_verificados(base, monkeypatch):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: (
        '{"sitios": [{"url": "https://diariorepuesto.com", "nombre": "Diario del Repuesto", "pais": "AR"},'
        ' {"url": "https://inventado-no-existe.com/", "nombre": "X"}, {"url": "https://ya-confiable.com/"}]}'))

    def get(url, **k):
        if "bing" in url:
            return Resp(429)
        return Resp(text=PORTADA) if "diariorepuesto" in url else Resp(404)
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(403), "get": get})
    r = ds.discover(base)
    guardadas = list(base.suggested_urls.find())
    assert [g["dominio"] for g in guardadas] == ["diariorepuesto.com"] and guardadas[0]["origen"] == "ia"
    assert guardadas[0]["titulo"] == "Diario del Repuesto" and r["guardadas"] == 1


def test_un_sitio_que_no_habla_del_sector_no_se_sugiere(monkeypatch):
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    monkeypatch.setattr(ds, "_transporte", {"get": lambda url, **k: Resp(text="<title>Recetas</title><p>Tortas</p>")})
    ok, _, motivo = ds._verificar_sitio("https://cocina.com/")
    assert not ok and motivo == "no habla del sector"


def test_sin_buscadores_ni_ia_termina_con_error_claro(base, monkeypatch, capsys):
    _sin_ia(monkeypatch)
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(202), "get": lambda url, **k: Resp(429)})
    monkeypatch.setattr(ds, "discover", lambda base=None, _d=ds.discover: _d(base_falsa))
    base_falsa = base
    assert ds.main() == 1
    assert "[ERROR] No se pudo buscar" in capsys.readouterr().out
