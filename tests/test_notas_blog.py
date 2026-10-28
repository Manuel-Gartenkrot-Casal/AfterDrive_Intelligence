"""Tests de las notas de AfterDrive by Alephee que una nota nueva cita y enlaza (notas_blog.py)."""

import mongomock
import pytest

from afterdrive.generacion import notas_blog, plan
from afterdrive.ia import llm

# Capturada al importar, antes de que conftest la reemplace.
_RELACIONADAS = notas_blog.relacionadas

NOTA_PT = "# Catálogo no Brasil\n\nO catálogo digital reduz devoluções por fitment em toda a rede de distribuidores.\n\n*Meta pt.*"
NOTA_ES = ("# Fitment y devoluciones\n\nLa compatibilidad por año y motor baja las devoluciones en el mostrador y online.\n\n"
           "*Las devoluciones por fitment caen con un catálogo completo.*")


@pytest.fixture
def base(monkeypatch):
    db = mongomock.MongoClient().db
    db.afterdrive_ejemplos.insert_many([
        {"url": "https://afterdrive.alephee.com/es/blog/logistica", "titulo": "Logística de última milla", "tag_slug": "logistica",
         "cuerpo": "## Intro\n\nLa última milla define el costo de entregar repuestos a talleres en el día, sobre todo en el interior.",
         "embedding": [0.0, 1.0], "embedding_modelo": "emb", "scrapeado_en": "2026-10-01"},
        {"url": "https://afterdrive.alephee.com/es/blog/catalogo", "titulo": "Catálogo y fitment", "tag_slug": "catalogacion",
         "cuerpo": "Un catálogo con compatibilidad por año, motor y versión evita devoluciones y mejora la conversión online.",
         "embedding": [1.0, 0.0], "embedding_modelo": "emb", "scrapeado_en": "2026-10-02"},
    ])
    db.notas_fase2.insert_many([
        {"contenido": NOTA_ES, "estado": "publicado", "regiones": ["argentina"], "categorias": ["catalogacion"],
         "hubspot": {"url": "https://afterdrive.alephee.com/es/blog/fitment-propia"}, "embedding": [0.9, 0.1],
         "embedding_modelo": "emb"},
        {"contenido": NOTA_PT, "estado": "publicado", "regiones": ["brasil"], "hubspot": {"url": "https://afterdrive.alephee.com/pt/blog/x"}},
        {"contenido": NOTA_ES, "estado": "aprobada", "regiones": ["argentina"], "hubspot": {"url": "https://borrador/no"}},
    ])
    monkeypatch.setattr(notas_blog, "relacionadas", _RELACIONADAS)
    monkeypatch.setattr(llm, "modelo_embeddings", lambda: "emb")
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [[1.0, 0.0]])
    return db


def test_elige_las_mas_parecidas_en_el_idioma_de_la_nota(base):
    notas = notas_blog.relacionadas("catálogo y devoluciones", ["catalogacion"], "es", base=base)
    assert [n.url.rsplit("/", 1)[-1] for n in notas] == ["catalogo", "fitment-propia", "logistica"]
    propia = notas[1]
    assert propia.origen == "propia" and propia.titulo == "Fitment y devoluciones"
    assert propia.resumen == "Las devoluciones por fitment caen con un catálogo completo."   # la meta
    assert notas[0].resumen.startswith("Un catálogo con compatibilidad")
    assert notas[2].resumen.startswith("La última milla")                                   # salta el "## Intro"


def test_en_portugues_solo_las_propias_publicadas_en_portugues(base):
    notas = notas_blog.relacionadas("catálogo", [], "pt", base=base)
    assert [n.url for n in notas] == ["https://afterdrive.alephee.com/pt/blog/x"]
    assert notas_blog.relacionadas("x", [], None, base=base) == []
    assert notas_blog.relacionadas("x", [], "en", base=base) == []


def test_sin_embeddings_manda_la_categoria(base, monkeypatch):
    def falla(textos, tipo="passage"):
        raise llm.ErrorLLM("caído")
    monkeypatch.setattr(llm, "embeber", falla)
    notas = notas_blog.relacionadas("x", ["logistica"], "es", base=base, limite=1)
    assert notas[0].url.endswith("/logistica")


def test_formatear_y_citadas():
    notas = [notas_blog.NotaBlog("Catálogo y fitment", "https://a.com/catalogo", "Resumen corto."),
             notas_blog.NotaBlog("Logística", "https://a.com/logistica")]
    bloque = notas_blog.formatear(notas)
    assert "AfterDrive by Alephee" in bloque and "[B1] Catálogo y fitment — https://a.com/catalogo" in bloque
    assert "Resumen: Resumen corto." in bloque and "no cites ninguna" in bloque
    assert "Resumen:" not in notas_blog.formatear(notas, compacto=True)
    assert notas_blog.formatear([]) == ""
    texto = "Como analizamos en AfterDrive by Alephee, [el catálogo importa](https://a.com/catalogo/)."
    assert [n.titulo for n in notas_blog.citadas(texto, notas)] == ["Catálogo y fitment"]


def test_el_plan_puede_asignar_una_nota_del_blog_a_una_seccion():
    data = {"titulo": "T", "secciones": [{"titulo": "A", "noticias": [1], "blog": [1, 7]}, {"titulo": "B", "blog": "x"}]}
    p = plan._normalizar(data, 2, n_blog=2)
    assert p["secciones"][0]["blog"] == [1] and p["secciones"][1]["blog"] == []
    texto = plan.formatear(p)
    assert "Citá la nota de AfterDrive by Alephee [B1]." in texto
    assert plan._normalizar(data, 2)["secciones"][0]["blog"] == []   # sin notas del blog, nada que citar
