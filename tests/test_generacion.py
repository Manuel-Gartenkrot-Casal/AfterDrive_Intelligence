"""Tests del recorrido de generación de una nota (generar_nota) con dobles."""

import datetime

import pytest

from afterdrive.generacion import contexto_noticias
from afterdrive.generacion import generar_nota_fase2 as g
from afterdrive.generacion.contexto_noticias import Noticia
from afterdrive.ia import llm

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

## Qué significa para tu negocio
- Revisá qué líneas de pastillas podés reponer con proveedores locales.
- Completá la compatibilidad por año y motor en tus fichas.

## Preguntas frecuentes

### ¿Por qué importa la planta de Frasle?
Porque acorta los plazos de reposición para los distribuidores de la región.

### ¿Qué conviene mejorar primero en el catálogo?
La compatibilidad por año, motor y versión, que evita devoluciones.

Descubrí cómo [Alephee](https://alephee.com) conecta tu catálogo con los principales marketplaces.

*Frasle amplía su planta y el catálogo digital se vuelve clave para la rotación de repuestos.*"""

PLAN = (
    '{"angulo": "La planta de Frasle cambia la reposición", "titulo": "Frasle acorta la reposición", '
    '"palabra_clave": "pastillas de freno", "secciones": [{"titulo": "Qué pasó", "idea": "La inversión", '
    '"noticias": [1]}, {"titulo": "Qué cambia", "idea": "El catálogo", "noticias": []}], '
    '"implicancias": ["Revisar proveedores"]}'
)


class ColFake:
    def __init__(self):
        self.docs = []

    def insert_one(self, d):
        self.docs.append(d)

    def find_one(self, *a, **k):
        return None

    def find(self, *a, **k):
        docs = self.docs

        class Cursor:
            def sort(self, *a):
                return self

            def limit(self, n):
                return list(reversed(docs))[:n]

        return Cursor()


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
    from afterdrive import calibracion
    monkeypatch.setattr(g, "_calibracion", lambda persona: calibracion.Calibracion())
    descartadas = []
    monkeypatch.setattr(g, "registrar_nota_descartada", lambda origen, crudo, motivo, **meta: descartadas.append(motivo))
    llamadas["descartadas"] = descartadas

    def completar(system, user, **kw):
        if system.startswith("Sos el editor"):
            llamadas["plan_user"] = user
            return PLAN
        llamadas.update(system=system, user=user, **kw)
        return NOTA

    monkeypatch.setattr(llm, "completar", completar)
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [[0.1, 0.2]])
    monkeypatch.setattr(llm, "ajustes_redaccion", lambda: llm.Redaccion(temperatura=0.55, max_ejemplos=3, chars_ejemplo=400, directiva="DIRECTIVA-X"))
    from afterdrive.ia import lm_studio
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


def test_la_recencia_usa_la_fecha_de_publicacion():
    import datetime

    from bson import ObjectId

    from afterdrive.generacion import contexto_noticias as cn
    guardado_hoy = ObjectId.from_datetime(datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC))
    vieja = cn._desde_doc({"_id": guardado_hoy, "titulo": "t", "fecha": "2025-03-01"})
    assert vieja.fecha == datetime.datetime(2025, 3, 1, tzinfo=datetime.UTC)
    # Sin fecha, con basura o con una fecha futura: la de guardado.
    for fecha in (None, "ayer", "2031-01-01"):
        assert cn._desde_doc({"_id": guardado_hoy, "titulo": "t", "fecha": fecha}).fecha == guardado_hoy.generation_time


# ── Evaluación que actúa ──────────────────────────────────────────────────────


def _evaluaciones(monkeypatch, *resultados):
    """Cada llamada a la evaluación devuelve el siguiente resultado de la lista."""
    from afterdrive.ia import lm_studio
    cola = list(resultados)
    monkeypatch.setattr(lm_studio, "evaluar_lineamientos", lambda texto: cola.pop(0))


BUENA = {"lineamientos": {"sin_alucinaciones": True, "estructura_correcta": True, "tono_b2b": True}}
INVENTA = {"lineamientos": {"sin_alucinaciones": False, "estructura_correcta": True, "tono_b2b": True}}


def test_nota_que_pasa_no_se_reescribe(entorno, monkeypatch):
    llamadas, col, _ = entorno
    _evaluaciones(monkeypatch, BUENA)
    assert g.generar_nota(["autopartes"])["success"]
    assert col.docs[0]["calidad"] == {"puntaje": 3, "fallas_criticas": [], "intentos": 1, "reescrita_por": [],
                                      "problemas": [], "segundo_intento": None}


def test_nota_que_inventa_se_reescribe_una_vez_diciendo_por_que(entorno, monkeypatch):
    llamadas, col, _ = entorno
    _evaluaciones(monkeypatch, INVENTA, BUENA)
    assert g.generar_nota(["autopartes"])["success"]
    assert "inventaba datos" in llamadas["user"]          # el segundo pedido explica la falla
    assert col.docs[0]["calidad"]["intentos"] == 2
    assert col.docs[0]["calidad"]["reescrita_por"] == ["sin_alucinaciones"]
    assert col.docs[0]["evaluacion"] == BUENA


def test_si_las_dos_fallan_queda_la_mejor_y_no_hay_tercer_intento(entorno, monkeypatch):
    _, col, _ = entorno
    peor = {"lineamientos": {"sin_alucinaciones": False, "estructura_correcta": False}}
    _evaluaciones(monkeypatch, INVENTA, peor)
    assert g.generar_nota(["autopartes"])["success"]
    assert len(col.docs) == 1 and col.docs[0]["evaluacion"] == INVENTA
    assert col.docs[0]["calidad"]["fallas_criticas"] == ["sin_alucinaciones"]


def test_si_el_saneo_rechaza_la_primera_se_reintenta(entorno, monkeypatch):
    _, col, _ = entorno
    respuestas = ["Primero voy a pensar el plan de la nota...", NOTA]
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: PLAN if system.startswith("Sos el editor")
                        else respuestas.pop(0))
    _evaluaciones(monkeypatch, BUENA)
    monkeypatch.setattr(g, "sanear", lambda crudo: type("S", (), {
        "ok": crudo == NOTA, "texto": crudo, "motivo": "el modelo escribió su razonamiento"})())
    assert g.generar_nota(["autopartes"])["success"] and col.docs[0]["calidad"]["intentos"] == 2
    assert entorno[0]["descartadas"] == ["el modelo escribió su razonamiento"]
    assert col.docs[0]["estado"] == "borrador"


def test_sin_evaluacion_disponible_no_se_reescribe(entorno, monkeypatch):
    _, col, _ = entorno
    _evaluaciones(monkeypatch, {"error": "proveedor caído", "lineamientos": {}})
    assert g.generar_nota(["autopartes"])["success"]
    assert col.docs[0]["evaluacion"] is None and col.docs[0]["calidad"]["intentos"] == 1


# ── Atlas Vector Search (opcional) ────────────────────────────────────────────


class ColConVector:
    """Colección falsa: find() da las recientes y aggregate() las 'parecidas' de Atlas."""

    def __init__(self, recientes, parecidas, falla=False):
        self.recientes, self.parecidas, self.falla, self.pipelines = recientes, parecidas, falla, []

    def find(self, *a, **k):
        recientes = self.recientes

        class Cursor:
            def sort(self, *a):
                return self

            def limit(self, n):
                return recientes[:n]

        return Cursor()

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        if self.falla:
            raise RuntimeError("índice inexistente")
        return self.parecidas


def _doc(i, emb, **extra):
    from bson import ObjectId
    return {"_id": ObjectId(), "titulo": f"N{i}", "cuerpo": "texto", "embedding": emb, **extra}


@pytest.fixture
def vectorial(monkeypatch):
    from afterdrive import db
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [[1.0, 0.0]])

    def instalar(col):
        monkeypatch.setattr(db, "col_articulos", col)
        return col
    return instalar


def test_sin_indice_vectorial_no_se_consulta_atlas(vectorial, monkeypatch):
    monkeypatch.delenv("ATLAS_VECTOR_INDEX", raising=False)
    col = vectorial(ColConVector([_doc(1, [0.0, 1.0])], [_doc(2, [1.0, 0.0])]))
    assert [n.titulo for n in contexto_noticias.seleccionar("frenos")] == ["N1"] and col.pipelines == []


def test_con_indice_suma_las_parecidas_de_toda_la_base(vectorial, monkeypatch):
    monkeypatch.setenv("ATLAS_VECTOR_INDEX", "vector_articulos")
    col = vectorial(ColConVector([_doc(1, [0.0, 1.0])], [_doc(2, [1.0, 0.0])]))
    titulos = [n.titulo for n in contexto_noticias.seleccionar("frenos")]
    assert titulos[0] == "N2"                     # la parecida (vieja) le gana a la reciente que no tiene que ver
    etapa = col.pipelines[0][0]["$vectorSearch"]
    assert etapa["index"] == "vector_articulos" and etapa["path"] == "embedding" and etapa["queryVector"] == [1.0, 0.0]


def test_si_atlas_falla_se_sigue_con_las_recientes(vectorial, monkeypatch):
    monkeypatch.setenv("ATLAS_VECTOR_INDEX", "no-existe")
    vectorial(ColConVector([_doc(1, [0.0, 1.0])], [], falla=True))
    assert [n.titulo for n in contexto_noticias.seleccionar("frenos")] == ["N1"]


def test_las_correcciones_de_rechazos_llegan_al_pedido(entorno, monkeypatch):
    llamadas, col, _ = entorno
    from afterdrive import calibracion
    monkeypatch.setattr(g, "_calibracion", lambda persona: calibracion.Calibracion(reglas=["Inventa cifras", "Muy comercial"]))
    g.generar_nota(["autopartes"])
    assert "- Inventa cifras\n- Muy comercial" in llamadas["user"]
    assert llamadas["user"].index("Correcciones") < llamadas["user"].index("## Pedido")
    assert col.docs[0]["correcciones_usadas"] == ["Inventa cifras", "Muy comercial"]


def test_sin_correcciones_no_aparece_la_seccion(entorno):
    llamadas, _, _ = entorno
    g.generar_nota(["autopartes"])
    assert "Correcciones" not in llamadas["user"]


def test_cancelada_mientras_evalua_no_guarda_la_nota(entorno, monkeypatch):
    _, col, usadas = entorno
    cancelada = {"si": False}
    from afterdrive.ia import lm_studio

    def evaluar(texto):
        cancelada["si"] = True  # el usuario cancela mientras se evalúa
        return {"error": "Cancelada desde el dashboard."}

    monkeypatch.setattr(lm_studio, "evaluar_lineamientos", evaluar)
    monkeypatch.setattr(llm, "_cancelada", lambda: cancelada["si"])
    with pytest.raises(llm.Cancelada):
        g.generar_nota(["autopartes"])
    assert col.docs == [] and usadas == []


def test_cancelada_durante_la_reescritura_no_guarda_la_primera_version(entorno, monkeypatch):
    _, col, _ = entorno
    _evaluaciones(monkeypatch, INVENTA, BUENA)
    respuestas = iter([NOTA])

    def completar(system, user, **kw):
        try:
            return next(respuestas)
        except StopIteration:
            raise llm.Cancelada("Cancelada desde el dashboard.") from None

    monkeypatch.setattr(llm, "completar", completar)
    with pytest.raises(llm.Cancelada):
        g.generar_nota(["autopartes"])
    assert col.docs == []


# ── Plan, verificación, secciones fijas, repetición y calibración ─────────────


def test_el_plan_llega_a_la_redaccion_con_las_notas_recientes(entorno):
    llamadas, col, _ = entorno
    col.docs.append({"contenido": "# Una nota de la semana pasada\n\nTexto."})
    g.generar_nota(["autopartes"])
    assert "Una nota de la semana pasada" in llamadas["plan_user"]          # el plan evita su ángulo
    assert "## Plan de la nota (seguilo)" in llamadas["user"]
    assert "Palabra clave: pastillas de freno" in llamadas["user"]
    assert col.docs[-1]["plan"]["titulo"] == "Frasle acorta la reposición"


def test_sin_plan_valido_la_nota_se_escribe_igual(entorno, monkeypatch):
    llamadas, col, _ = entorno
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: "no es json" if system.startswith("Sos el editor")
                        else llamadas.update(user=user) or NOTA)
    assert g.generar_nota(["autopartes"])["success"]
    assert "Plan de la nota" not in llamadas["user"] and col.docs[0]["plan"] is None


def test_la_nota_termina_con_sus_fuentes_antes_de_la_meta(entorno):
    _, col, _ = entorno
    contenido = col.docs[0]["contenido"] if g.generar_nota(["autopartes"])["success"] else ""
    lineas = contenido.rstrip().splitlines()
    assert lineas[-1].startswith("*Frasle amplía")
    assert "## Fuentes" in contenido
    # El plan asignó la noticia 1 a una sección: entra. La 2 no se usó en nada: no.
    assert "- [Frasle amplía su planta de pastillas de freno](https://n/1)" in contenido
    assert "https://n/2" not in contenido.split("## Fuentes")[1]


def test_datos_sin_respaldo_hacen_reescribir_y_se_guardan(entorno, monkeypatch):
    llamadas, col, _ = entorno
    inventada = NOTA.replace("invirtió en ampliar", "invirtió **US$ 80 millones** en ampliar")
    respuestas = [inventada, NOTA]

    def completar(system, user, **kw):
        if system.startswith("Sos el editor"):
            return PLAN
        if system.startswith("Sos un verificador"):
            return '{"datos": [{"dato": "US$ 80 millones", "respaldado": false}]}'
        llamadas.update(user=user)
        return respuestas.pop(0)

    monkeypatch.setattr(llm, "completar", completar)
    assert g.generar_nota(["autopartes"])["success"]
    assert "US$ 80 millones" in llamadas["user"] and "no aparecen en las noticias" in llamadas["user"]
    doc = col.docs[0]
    assert doc["calidad"]["intentos"] == 2 and doc["calidad"]["reescrita_por"] == ["datos_sin_respaldo"]
    assert doc["verificacion"]["sin_respaldo"] == [] and "US$ 80" not in doc["contenido"]


def test_falta_la_seccion_de_implicancias_hace_reescribir(entorno, monkeypatch):
    llamadas, col, _ = entorno
    sin_seccion = NOTA.replace("## Qué significa para tu negocio", "## Otra cosa")
    respuestas = [sin_seccion, NOTA]
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: PLAN if system.startswith("Sos el editor")
                        else llamadas.update(user=user) or respuestas.pop(0))
    g.generar_nota(["autopartes"])
    assert "Falta la sección" in llamadas["user"]
    assert col.docs[0]["calidad"]["reescrita_por"] == ["sin_implicancias"]


def test_una_nota_igual_a_una_reciente_se_reescribe(entorno, monkeypatch):
    llamadas, col, _ = entorno
    monkeypatch.setattr(llm, "modelo_embeddings", lambda: "nvidia/x")
    col.docs.append({"contenido": "# Nota vieja igual", "embedding": [0.1, 0.2], "embedding_modelo": "nvidia/x"})
    g.generar_nota(["autopartes"])
    assert "se parecía demasiado" in llamadas["user"] and "Nota vieja igual" in llamadas["user"]
    nueva = col.docs[-1]
    assert nueva["parecida_a"]["titulo"] == "Nota vieja igual" and "repetida" in nueva["calidad"]["problemas"]


def test_los_enlaces_inventados_se_quitan(entorno, monkeypatch):
    _, col, _ = entorno
    con_link = NOTA.replace("Frasle invirtió", "[Frasle](https://inventado.example/x) invirtió")
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: PLAN if system.startswith("Sos el editor")
                        else con_link)
    g.generar_nota(["autopartes"])
    assert "inventado.example" not in col.docs[0]["contenido"]
    assert col.docs[0]["enlaces_quitados"] == ["https://inventado.example/x"]
    assert "[Alephee](https://alephee.com)" in col.docs[0]["contenido"]      # el de la casa queda


def test_la_calibracion_llega_al_pedido(entorno, monkeypatch):
    llamadas, col, _ = entorno
    from afterdrive import calibracion
    cal = calibracion.Calibracion(
        reglas=["Sé más breve"], aciertos=["El ángulo de márgenes funcionó"],
        ejemplos_propios=[{"id": "abc", "titulo": "Nota propia buena", "cuerpo": "Cuerpo de la nota propia.", "puntaje": 5}],
    )
    monkeypatch.setattr(g, "_calibracion", lambda persona: cal)
    g.generar_nota(["autopartes"])
    u = llamadas["user"]
    assert "- Sé más breve" in u and "- El ángulo de márgenes funcionó" in u
    assert "Notas propias que el equipo calificó alto" in u and "Nota propia buena" in u
    assert "Sé más breve" in llamadas["plan_user"]
    assert col.docs[0]["calibracion_usada"]["ejemplos_propios"] == [{"id": "abc", "titulo": "Nota propia buena", "puntaje": 5}]


def test_el_umbral_calibrado_hace_reescribir_notas_flojas(entorno, monkeypatch):
    llamadas, col, _ = entorno
    from afterdrive import calibracion
    monkeypatch.setattr(g, "_calibracion", lambda persona: calibracion.Calibracion(umbral=5))
    _evaluaciones(monkeypatch, BUENA, BUENA)   # 3 de 9: por debajo del umbral
    g.generar_nota(["autopartes"])
    assert "el equipo pide al menos 5" in llamadas["user"]
    assert col.docs[0]["calidad"]["intentos"] == 2


def test_se_guardan_estilo_y_seo(entorno):
    _, col, _ = entorno
    g.generar_nota(["autopartes"])
    doc = col.docs[0]
    assert doc["seo"]["palabra_clave"] == "pastillas de freno" and doc["seo"]["preguntas_frecuentes"] == 2
    assert isinstance(doc["estilo"], list)


def test_las_noticias_usadas_hace_poco_quedan_al_final():
    ns = [Noticia(1, "a", "", usada_reciente=True), Noticia(2, "b", ""), Noticia(3, "c", "")]
    assert [n.id for n in contexto_noticias.elegir(ns, 2)] == [2, 3]
    assert [n.id for n in contexto_noticias.elegir(ns, 3)] == [2, 3, 1]


def test_usada_reciente_mira_la_fecha():
    from afterdrive.generacion import contexto_noticias as cn
    ahora = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)
    assert cn._usada_reciente({"usado_en": "2026-10-10T00:00:00+00:00"}, ahora)
    assert not cn._usada_reciente({"usado_en": "2026-08-01T00:00:00+00:00"}, ahora)
    assert not cn._usada_reciente({"usado_para_articulo": True}, ahora)   # marcadas antes de guardar la fecha


def test_formatear_usa_la_ficha_y_un_extracto():
    n = Noticia(1, "Frasle amplía", "Cuerpo largo. " * 300, url="https://n/1",
                ficha={"resumen": "Frasle amplía su planta.", "cifras": ["US$ 20 millones de inversión"],
                       "empresas": ["Frasle"], "hechos": [], "fecha": "2026-10-01"})
    txt = contexto_noticias.formatear([n], max_chars=1200)
    assert "Resumen: Frasle amplía su planta." in txt and "- US$ 20 millones de inversión" in txt
    assert "Fecha: 2026-10-01" in txt and "Extracto: Cuerpo largo." in txt and len(txt) < 1600


# ── Corrección barata, largo y costo por nota ─────────────────────────────────


def _con_tareas(monkeypatch, respuestas_redaccion, correccion=None):
    """llm.completar falso que registra (tarea, system) y responde según la tarea."""
    tareas = []

    def completar(system, user, **kw):
        tareas.append(kw.get("tarea"))
        if kw.get("tarea") == "planificacion":
            return PLAN
        if kw.get("tarea") == "correccion":
            tareas.append(("correccion_user", user))
            return correccion if correccion is not None else NOTA
        return respuestas_redaccion.pop(0)

    monkeypatch.setattr(llm, "completar", completar)
    return tareas


def test_un_problema_se_corrige_con_el_modelo_barato_sin_redactar_de_nuevo(entorno, monkeypatch):
    _, col, _ = entorno
    sin_seccion = NOTA.replace("## Qué significa para tu negocio", "## Otra cosa")
    tareas = _con_tareas(monkeypatch, [sin_seccion])
    assert g.generar_nota(["autopartes"])["success"]
    assert tareas.count("redaccion") == 1 and tareas.count("correccion") == 1
    pedido = next(t[1] for t in tareas if isinstance(t, tuple))
    assert "Falta la sección" in pedido and "## Otra cosa" in pedido      # la nota y el problema
    doc = col.docs[0]
    assert doc["calidad"]["segundo_intento"] == "correccion" and doc["calidad"]["problemas"] == []
    assert "## Qué significa para tu negocio" in doc["contenido"]


def test_una_nota_repetida_si_se_redacta_de_nuevo(entorno, monkeypatch):
    _, col, _ = entorno
    monkeypatch.setattr(llm, "modelo_embeddings", lambda: "nvidia/x")
    col.docs.append({"contenido": "# Nota vieja igual", "embedding": [0.1, 0.2], "embedding_modelo": "nvidia/x"})
    tareas = _con_tareas(monkeypatch, [NOTA, NOTA])
    g.generar_nota(["autopartes"])
    assert tareas.count("redaccion") == 2 and "correccion" not in tareas
    assert col.docs[-1]["calidad"]["segundo_intento"] == "reescritura"


def test_si_la_correccion_falla_queda_la_primera_version(entorno, monkeypatch):
    _, col, _ = entorno
    sin_seccion = NOTA.replace("## Qué significa para tu negocio", "## Otra cosa")
    _con_tareas(monkeypatch, [sin_seccion], correccion="")
    assert g.generar_nota(["autopartes"])["success"]
    assert "## Otra cosa" in col.docs[0]["contenido"] and col.docs[0]["calidad"]["problemas"] == ["sin_implicancias"]


def test_el_largo_elegido_llega_al_prompt(entorno):
    llamadas, col, _ = entorno
    g.generar_nota(["autopartes"], largo="corto")
    assert "entre 500 y 700 palabras" in llamadas["system"] and col.docs[0]["largo"] == "corto"
    g.generar_nota(["autopartes"], puntapie_url="https://alephee.com/x")
    assert "entre 700 y 1000 palabras" in llamadas["system"]          # medio por defecto, también con puntapié


def test_la_nota_guarda_lo_que_costo(entorno, monkeypatch):
    from afterdrive.ia import consumo
    _, col, _ = entorno

    def completar(system, user, **kw):
        consumo.registrar(kw.get("tarea", ""), "modelo-x", 1000, 1000)
        return PLAN if kw.get("tarea") == "planificacion" else NOTA

    monkeypatch.setattr(llm, "completar", completar)
    g.generar_nota(["autopartes"])
    costo = col.docs[0]["costo"]
    assert costo["llamadas"] == 2 and set(costo["por_tarea"]) == {"planificacion", "redaccion"}
    assert costo["total_usd"] > 0
    # Lo que se gasta fuera de la nota no se le suma.
    consumo.registrar("clasificacion", "modelo-x", 1000, 1000)
    assert col.docs[0]["costo"]["llamadas"] == 2


def test_el_script_sale_con_error_si_la_nota_no_se_genero(monkeypatch):
    """Si no, la Corrida del dashboard queda como 'Terminó bien' sin haber guardado nada."""
    monkeypatch.setattr(g, "_validar_entorno", lambda: None)
    monkeypatch.setattr(g, "generar_nota", lambda **kw: {"success": False, "error": "sin noticias"})
    assert g.main(["--categorias", "autopartes"]) == 1


def test_el_script_sale_bien_si_la_nota_se_genero(monkeypatch):
    monkeypatch.setattr(g, "_validar_entorno", lambda: None)
    monkeypatch.setattr(g, "generar_nota", lambda **kw: {"success": True, "contenido": "# Nota"})
    assert g.main(["--categorias", "autopartes"]) == 0


def test_la_imagen_destacada_es_la_foto_de_una_noticia_usada(entorno, monkeypatch):
    _, col, _ = entorno
    noticias = [
        Noticia(id=1, titulo="Frasle amplía su planta", cuerpo="Frasle invirtió en su planta de Caxias.", url="https://n/1",
                imagen={"url": "https://n/1.jpg", "alt": "Planta"}, imagen_buscada=True),
        Noticia(id=2, titulo="Automechanika abre acreditaciones", cuerpo="La feria vuelve a La Rural.", url="https://n/2",
                imagen={"url": "https://n/2.jpg", "alt": ""}, imagen_buscada=True),
    ]
    monkeypatch.setattr(contexto_noticias, "seleccionar", lambda consulta, limite=5: noticias)
    assert g.generar_nota(["autopartes"], persona="comercial")["success"]
    guardada = col.docs[0]
    # La 1 la asigna el plan a una sección: va primero.
    assert guardada["imagen"] == {"url": "https://n/1.jpg", "alt": "El catálogo digital llega al mostrador",
                                  "origen": {"titulo": "Frasle amplía su planta", "url": "https://n/1"}}
    assert [f.get("imagen") for f in guardada["fuentes"]] == ["https://n/1.jpg", "https://n/2.jpg"]


def test_sin_fotos_la_nota_se_guarda_sin_imagen(entorno):
    _, col, _ = entorno
    assert g.generar_nota(["autopartes"], persona="comercial")["success"]
    assert "imagen" not in col.docs[0] and "imagen_error" not in col.docs[0]
