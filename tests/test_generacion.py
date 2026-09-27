"""Tests del recorrido de generación de una nota (generar_nota) con dobles."""

import datetime

import pytest

import contexto_noticias
import generar_nota_fase2 as g
import llm
from contexto_noticias import Noticia

NOTA = """# El catálogo digital llega al mostrador

## Qué pasó
Frasle invirtió en ampliar su planta de pastillas de freno en Caxias do Sul y apunta a abastecer
a distribuidores de toda la región. La compañía busca acortar los plazos de reposición, que hoy
pesan sobre la rotación de los mayoristas. Automechanika Buenos Aires, por su parte, abrió las
acreditaciones para su edición 2026 en La Rural.

## Qué cambia para el distribuidor
Con más oferta local, el distribuidor puede sostener stock de alta rotación sin inmovilizar capital
en importaciones. El desafío pasa a ser el catálogo: publicar fichas con compatibilidad por año,
motor y versión evita devoluciones por fitment incorrecto y mejora la conversión en Mercado Libre.

Descubrí cómo Alephee conecta tu catálogo con los principales marketplaces.

*Frasle amplía su planta y el catálogo digital se vuelve clave para la rotación de repuestos.*"""


class ColFake:
    def __init__(self):
        self.docs = []

    def insert_one(self, d):
        self.docs.append(d)

    def find_one(self, *a, **k):
        return None


@pytest.fixture
def entorno(monkeypatch):
    llamadas = {}
    noticias = [
        Noticia(id=1, titulo="Frasle amplía su planta de pastillas de freno", cuerpo="Frasle invirtió en su planta de Caxias.", url="https://n/1", fuente="Aftermarket Intl"),
        Noticia(id=2, titulo="Automechanika Buenos Aires 2026 abre acreditaciones", cuerpo="La feria vuelve a La Rural.", url="https://n/2"),
    ]
    usadas = []
    col = ColFake()

    monkeypatch.setattr(contexto_noticias, "seleccionar", lambda consulta, limite=5: llamadas.setdefault("consulta", consulta) and noticias)
    monkeypatch.setattr(contexto_noticias, "marcar_usadas", lambda ns: usadas.extend(n.id for n in ns))
    monkeypatch.setattr(g, "get_ejemplos_por_tags", lambda cats, regiones=None, limit=2: [
        {"titulo": f"Referencia {i}", "cuerpo": "Párrafo de referencia.\n" * 200, "url": f"https://ej/{i}"} for i in range(5)
    ])
    monkeypatch.setattr(g, "col_notas_fase2", col)
    monkeypatch.setattr(g, "col_clientes", ColFake())

    def completar(system, user, **kw):
        llamadas.update(system=system, user=user, **kw)
        return NOTA

    monkeypatch.setattr(llm, "completar", completar)
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [[0.1, 0.2]])
    monkeypatch.setattr(llm, "ajustes_redaccion", lambda: llm.Redaccion(temperatura=0.55, max_ejemplos=3, chars_ejemplo=400, directiva="DIRECTIVA-X"))
    import lm_studio
    monkeypatch.setattr(lm_studio, "evaluar_lineamientos", lambda texto: {"lineamientos": {"tono_b2b": True}, "comentarios": "ok"})
    return llamadas, col, usadas


def test_la_nota_se_escribe_con_las_noticias_scrapeadas(entorno):
    llamadas, col, usadas = entorno
    r = g.generar_nota(["autopartes"], persona="comercial", regiones=["argentina"])
    assert r["success"]
    assert "Frasle amplía su planta" in llamadas["user"]
    assert "única fuente de hechos concretos" in llamadas["user"]
    assert "Argentina" in llamadas["consulta"]
    assert usadas == [1, 2]
    guardada = col.docs[0]
    assert guardada["fuentes"] == [
        {"titulo": "Frasle amplía su planta de pastillas de freno", "url": "https://n/1"},
        {"titulo": "Automechanika Buenos Aires 2026 abre acreditaciones", "url": "https://n/2"},
    ]


def test_usa_los_ajustes_del_proveedor(entorno):
    llamadas, _, _ = entorno
    g.generar_nota(["autopartes"], persona="comercial")
    assert llamadas["temperature"] == 0.55
    assert llamadas["system"].rstrip().endswith("DIRECTIVA-X")
    assert llamadas["user"].count("--- Referencia") == 3                 # max_ejemplos
    # Las referencias se cortan en un párrafo completo, no a mitad de frase.
    referencia = llamadas["user"].split("--- Referencia 1 ---")[1].split("--- Referencia 2")[0]
    assert referencia.rstrip().endswith("Párrafo de referencia.")


def test_la_evaluacion_se_guarda_con_la_nota(entorno):
    _, col, _ = entorno
    g.generar_nota(["autopartes"])
    assert col.docs[0]["evaluacion"] == {"lineamientos": {"tono_b2b": True}, "comentarios": "ok"}


def test_sin_noticias_se_pide_no_inventar(entorno, monkeypatch):
    llamadas, _, _ = entorno
    monkeypatch.setattr(contexto_noticias, "seleccionar", lambda consulta, limite=5: [])
    g.generar_nota(["autopartes"])
    assert "No hay noticias recientes" in llamadas["user"]
    assert "sin cifras" in llamadas["user"]


def test_region_mexico_pide_tuteo(entorno):
    llamadas, _, _ = entorno
    g.generar_nota(["autopartes"], regiones=["mexico"])
    assert "tuteo" in llamadas["system"]


# ── Ranking de noticias (puro) ────────────────────────────────────────────────

def test_rankear_prefiere_parecidas_recientes_y_no_usadas():
    ahora = datetime.datetime(2026, 9, 27, tzinfo=datetime.UTC)
    hace = lambda d: ahora - datetime.timedelta(days=d)  # noqa: E731
    ns = [
        Noticia(1, "vieja parecida", "", fecha=hace(40), embedding=[1, 0]),
        Noticia(2, "nueva parecida", "", fecha=hace(1), embedding=[1, 0]),
        Noticia(3, "nueva distinta", "", fecha=hace(1), embedding=[0, 1]),
        Noticia(4, "nueva parecida usada", "", fecha=hace(1), embedding=[1, 0], usada=True),
    ]
    orden = [n.id for n in contexto_noticias.rankear(ns, [1, 0], ahora)]
    assert orden[0] == 2 and orden.index(4) == 1 and orden[-1] in (1, 3)


def test_rankear_sin_embeddings_usa_recencia():
    ahora = datetime.datetime(2026, 9, 27, tzinfo=datetime.UTC)
    ns = [Noticia(1, "a", "", fecha=ahora - datetime.timedelta(days=9)),
          Noticia(2, "b", "", fecha=ahora - datetime.timedelta(days=1))]
    assert [n.id for n in contexto_noticias.rankear(ns, None, ahora)] == [2, 1]


def test_formatear_respeta_presupuesto_y_no_corta_frases():
    ns = [Noticia(i, f"T{i}", "Una frase completa. " * 200, url=f"https://n/{i}") for i in range(3)]
    txt = contexto_noticias.formatear(ns, max_chars=1500)
    assert len(txt) < 1500 + 300
    assert txt.count("[") == 3 and "https://n/2" in txt
    assert "completa. " in txt and not txt.rstrip().endswith("Una")
