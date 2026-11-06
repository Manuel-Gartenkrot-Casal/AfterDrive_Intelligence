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

def portada(dominio, titulo="Diario del Repuesto", sector=5, otras=0, extra=""):
    """La portada de un medio con `sector` titulares del rubro y `otras` notas de cualquier tema."""
    notas = [f"Una nota larga sobre el mercado de repuestos {i}" for i in range(sector)]
    notas += [f"El dólar volvió a subir en la apertura de hoy {i}" for i in range(otras)]
    links = "".join(f'<a href="https://{dominio}/nota/{i}">{t}</a>' for i, t in enumerate(notas))
    return f"<html><head><title>{titulo}</title></head><body>{extra}{links}</body></html>"


PORTADA = portada("diariorepuesto.com")


def sitios(**portadas):
    """get() que sirve la portada de cada dominio (dominio con _ en vez de .) y 404 al resto."""
    def get(url, **k):
        for dom, html in portadas.items():
            if dom.replace("_", ".") in url:
                return Resp(text=html)
        return Resp(404)
    return get


@pytest.fixture(autouse=True)
def sin_embeddings(monkeypatch):
    """Sin embeddings la relevancia se mide solo por palabras (los tests de relevancia instalan unos falsos)."""
    monkeypatch.setattr(ds, "_embeber", lambda textos: None)


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
    get = sitios(revistarepuestos_com_ar=portada("www.revistarepuestos.com.ar"))
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(text=DDG_OK), "get": get})
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
    sitio = sitios(autopecas_com_br=portada("autopecas.com.br"))
    monkeypatch.setattr(ds, "_transporte", {"post": post,
                                            "get": lambda url, **k: Resp(text=BING_OK) if "bing" in url or "news.google" in url
                                            else sitio(url)})
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
    recetas = "".join(f'<a href="https://cocina.com/receta/{i}">Torta de chocolate fácil y rápida {i}</a>'
                      for i in range(5))
    monkeypatch.setattr(ds, "_transporte", {"get": lambda url, **k: Resp(text=f"<title>Recetas</title>{recetas}")})
    ok, _, motivo, _ = ds._verificar_sitio("https://cocina.com/")
    assert not ok and motivo == "no habla del sector"


def test_un_diario_general_con_alguna_nota_del_sector_no_se_sugiere(monkeypatch):
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    monkeypatch.setattr(ds, "_transporte", {"get": sitios(diario_com=portada("diario.com", sector=3, otras=30))})
    ok, _, motivo, _ = ds._verificar_sitio("https://diario.com/")
    assert not ok and "medio general" in motivo


def test_de_un_diario_general_se_sugiere_su_seccion_del_sector(monkeypatch):
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    general = portada("diario.com", sector=1, otras=30, extra='<a href="/autos/">Autos</a><a href="/deportes/">Dep</a>')

    def get(url, **k):
        return Resp(text=portada("diario.com") if url.endswith("/autos/") else general)
    monkeypatch.setattr(ds, "_transporte", {"get": get})
    ok, _, _, fuente = ds._verificar_sitio("https://diario.com/")
    assert ok and fuente == "https://diario.com/autos/"


@pytest.mark.parametrize("texto", ["Se filtró el audio del ministro", "Una batería de medidas económicas",
                                   "Suspensión de clases por el paro", "Talleres de arte para chicos"])
def test_palabras_ambiguas_no_cuentan_como_del_sector(texto):
    assert ds._keywords_en_texto(texto) == []


def test_las_palabras_del_sector_cuentan_aunque_esten_en_plural_o_con_tildes():
    assert ds._keywords_en_texto("Suben los neumáticos y los lubricantes") == ["neumaticos", "lubricantes"]


def test_un_resultado_del_buscador_que_es_un_diario_general_no_se_sugiere(base, monkeypatch):
    _sin_ia(monkeypatch)
    rss = ('<rss><channel><item><title>Crece el mercado de autopartes</title>'
           '<source url="https://www.diariogeneral.com">Diario General</source></item></channel></rss>')
    sitio = sitios(diariogeneral_com=portada("www.diariogeneral.com", sector=1, otras=40))
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(202),
                                            "get": lambda url, **k: Resp(text=rss) if "news.google" in url else sitio(url)})
    assert ds.discover(base)["guardadas"] == 0


def test_sin_buscadores_ni_ia_termina_con_error_claro(base, monkeypatch, capsys):
    _sin_ia(monkeypatch)
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(202), "get": lambda url, **k: Resp(429)})
    monkeypatch.setattr(ds, "discover", lambda base=None, _d=ds.discover: _d(base_falsa))
    base_falsa = base
    assert ds.main() == 1
    assert "[ERROR] No se pudo buscar" in capsys.readouterr().out


RSS_OK = """<rss><channel>
<item><title>Crece el mercado de autopartes en la región</title><source url="https://www.diarioautopartes.com">Diario Autopartes</source></item>
<item><title>Receta de tortas</title><source url="https://cocina.com">Cocina</source></item>
<item><title>Repuestos: suben las ventas</title><source url="https://ya-confiable.com">Ya</source></item>
</channel></rss>"""


def test_google_noticias_sugiere_el_sitio_del_medio(base, monkeypatch):
    _sin_ia(monkeypatch)
    pedidos = []

    def get(url, **k):
        pedidos.append(url)
        if "news.google.com" in url:
            return Resp(text=RSS_OK)
        return sitios(diarioautopartes_com=portada("www.diarioautopartes.com"))(url)
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(202), "get": get})
    r = ds.discover(base)
    guardadas = list(base.suggested_urls.find())
    assert [g["dominio"] for g in guardadas] == ["diarioautopartes.com"] and r["guardadas"] == 1
    assert guardadas[0]["url"] == "https://www.diarioautopartes.com/"
    assert not any("duckduckgo" in u or "bing" in u for u in pedidos)   # respondió el primero
    assert any("diarioautopartes" in u for u in pedidos)   # entró al sitio a verificarlo


# ── Relevancia por significado y popularidad ──────────────────────────────────

def _embeddings_falsos(monkeypatch):
    """Un vector por tema: lo del sector apunta a un lado y el resto a otro, sin palabras clave en común."""
    sector = ("repuesto", "bujía", "autopeça", "aftermarket", "taller", "amortiguador", "lubric", "neumát",
              "distribuidora", "parts", "frenos", "mecânica", "refaccion", "parque automotor", "Bosch", "freios",
              "caja de cambios", "aceite", "filtros de aire")
    def embeber(textos):
        return [[1.0, 0.05] if any(p.lower() in t.lower() for p in sector) else [0.05, 1.0] for t in textos]
    monkeypatch.setattr(ds, "_embeber", embeber)


def test_el_perfil_calibra_un_umbral_entre_el_sector_y_otros_temas(monkeypatch):
    _embeddings_falsos(monkeypatch)
    perfil = ds._perfil_sector(mongomock.MongoClient().db)
    assert perfil is not None and 0.1 < perfil.umbral <= 1.0
    assert perfil.parecido(ds._norma([1.0, 0.05])) >= perfil.umbral > perfil.parecido(ds._norma([0.05, 1.0]))


def test_sin_embeddings_no_hay_perfil():
    assert ds._perfil_sector(mongomock.MongoClient().db) is None


def test_un_medio_del_sector_pasa_aunque_sus_titulares_no_usen_las_palabras_clave(monkeypatch):
    _embeddings_falsos(monkeypatch)
    monkeypatch.setattr(scraper, "url_publica", lambda url: True)
    # Ninguno de estos titulares tiene una palabra del nicho, pero todos son del rubro.
    notas = ["Nueva caja de cambios para utilitarios", "Bosch amplía su planta de Campinas",
             "Cómo elegir el aceite correcto", "Ventas de filtros de aire en alza", "Freios: o que muda em 2027"]
    assert all(not ds._keywords_en_texto(t) for t in notas)
    html = "<title>Revista</title>" + "".join(f'<a href="https://revista.com/n/{i}">{t}</a>' for i, t in enumerate(notas))
    monkeypatch.setattr(ds, "_transporte", {"get": lambda url, **k: Resp(text=html)})
    perfil = ds._perfil_sector(mongomock.MongoClient().db)
    assert not ds._verificar_sitio("https://revista.com/")[0]          # solo con palabras, no pasaba
    e = ds._evaluar_sitio("https://revista.com/", perfil)
    assert e.ok and e.relevancia == 1.0


def test_la_popularidad_cuenta_busquedas_distintas_y_la_ia():
    c = ds.Candidato("https://x.com/")
    assert c.popularidad == 0
    c.busquedas.update({"a", "b"})
    c.apariciones = 2
    assert c.popularidad == pytest.approx(2 / 3)
    c.ia = True
    assert c.popularidad == 1.0
    assert ds.puntaje(0.6, 1.0) == 1.0 and ds.puntaje(0.3, 0.0) == 0.3


def test_se_verifican_primero_los_mas_populares_y_se_guarda_el_puntaje(base, monkeypatch):
    _sin_ia(monkeypatch)
    rss_por_busqueda = {}
    for i, q in enumerate(ds._BUSQUEDAS):
        items = '<item><title>Nota</title><source url="https://popular.com">Popular</source></item>'
        if i == 0:
            items += '<item><title>Otra</title><source url="https://raro.com">Raro</source></item>'
        rss_por_busqueda[q] = f"<rss><channel>{items}</channel></rss>"
    visitados = []

    def get(url, **k):
        if "news.google.com" in url:
            q = next(q for q in ds._BUSQUEDAS if ds.quote_plus(q) in url)
            return Resp(text=rss_por_busqueda[q])
        visitados.append(url)
        return sitios(popular_com=portada("popular.com"), raro_com=portada("raro.com"))(url)
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(202), "get": get})
    assert ds.discover(base)["guardadas"] == 2
    assert visitados[0].startswith("https://popular.com")
    guardadas = {g["dominio"]: g for g in base.suggested_urls.find()}
    assert guardadas["popular.com"]["busquedas"] == len(ds._BUSQUEDAS) and guardadas["raro.com"]["busquedas"] == 1
    assert guardadas["popular.com"]["puntaje"] > guardadas["raro.com"]["puntaje"]
    assert guardadas["popular.com"]["relevancia"] == 1.0


def test_un_resultado_sin_palabras_del_sector_igual_se_verifica(base, monkeypatch):
    _sin_ia(monkeypatch)
    rss = ('<rss><channel><item><title>Lanzamientos de la semana</title>'
           '<source url="https://revistadelrubro.com">Revista</source></item></channel></rss>')
    sitio = sitios(revistadelrubro_com=portada("revistadelrubro.com"))
    monkeypatch.setattr(ds, "_transporte", {"post": lambda url, **k: Resp(202),
                                            "get": lambda url, **k: Resp(text=rss) if "news.google" in url else sitio(url)})
    assert [g["dominio"] for g in (ds.discover(base), base.suggested_urls.find())[1]] == ["revistadelrubro.com"]
