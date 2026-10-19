"""Tests de la revisión de una Nota sin IA: estilo y SEO (calidad.py), datos y fuentes (verificacion.py), plan."""

import pytest

from afterdrive.generacion import calidad, plan, verificacion
from afterdrive.generacion.contexto_noticias import Noticia
from afterdrive.ia import llm, redaccion

AR = redaccion.voz(["argentina"])

BIEN = """# Frasle acorta la reposición de pastillas de freno

Las pastillas de freno se reponen más rápido desde que Frasle amplió su planta.

## Qué pasó
Frasle invirtió en su planta de Caxias do Sul.

## Qué significa para tu negocio
- Revisá tus proveedores de pastillas de freno.

## Preguntas frecuentes

### ¿Qué hizo Frasle?
Amplió su planta.

### ¿Qué cambia?
La reposición.

*Las pastillas de freno se reponen más rápido con la planta nueva de Frasle.*"""


def _codigos(texto, **kw):
    return [h.codigo for h in calidad.revisar(texto, AR, **kw).hallazgos]


def test_una_nota_completa_no_tiene_hallazgos_y_mide_seo():
    r = calidad.revisar(BIEN, AR, palabra_clave="pastillas de freno")
    assert r.hallazgos == []
    assert r.seo["preguntas_frecuentes"] == 2 and r.seo["palabra_clave_en"] == {
        "titulo": True, "meta": True, "primer_parrafo": True}


def test_faltantes_graves():
    sin_nada = "Texto sin título ni secciones. " * 20
    graves = [h.codigo for h in calidad.revisar(sin_nada, AR).graves]
    assert graves == ["sin_titulo", "sin_meta", "sin_implicancias"]


def test_titulo_largo_y_meta_larga():
    texto = BIEN.replace("# Frasle acorta la reposición de pastillas de freno", "# " + "Título muy largo " * 4)
    texto = texto.replace("*Las pastillas", "*" + "x" * 160 + " Las pastillas")
    assert {"titulo_largo", "meta_larga"} <= set(_codigos(texto))


def test_sin_faq_solo_si_se_espera():
    texto = BIEN.split("## Preguntas frecuentes")[0] + "*Meta corta.*"
    assert "sin_faq" in _codigos(texto)
    assert "sin_faq" not in _codigos(texto, faq=False)


def test_frases_de_ia_anglicismos_y_terminos():
    texto = BIEN.replace("Frasle invirtió", "En el dinámico mundo del aftermarket, cabe destacar que el feedback "
                                            "sobre las balatas importa. Sin lugar a dudas Frasle invirtió")
    r = calidad.revisar(texto, AR)
    por = {h.codigo: h for h in r.hallazgos}
    assert por["frases_ia"].grave                      # tres muletillas distintas
    assert "feedback" in por["anglicismos"].detalle
    assert "balatas" in por["termino"].detalle


def test_huecos_sin_dato_son_graves():
    texto = BIEN.replace("Frasle invirtió", "Las ventas crecieron un X% y Frasle invirtió")
    assert "huecos" in [h.codigo for h in calidad.revisar(texto, AR).graves]


def test_la_seccion_fija_se_busca_en_el_idioma_de_la_nota():
    br = redaccion.voz(["brasil"])
    texto = BIEN.replace("Qué significa para tu negocio", br.titulo_implicancias)
    assert "sin_implicancias" in _codigos(texto)          # con la voz argentina se busca el título en español
    assert "sin_implicancias" not in [h.codigo for h in calidad.revisar(texto, br, faq=False).hallazgos]


def test_palabra_clave_ausente():
    assert "palabra_clave" in _codigos(BIEN, palabra_clave="catálogo digital")


# ── Verificación ──────────────────────────────────────────────────────────────

NOTICIAS = [Noticia(1, "Frasle amplía su planta", "Frasle invirtió USD 20 millones en Caxias do Sul. Ventas +15 %.",
                    url="https://n/1"),
            Noticia(2, "Feria en Buenos Aires", "Automechanika vuelve a La Rural.", url="https://n/2")]


def test_extraer_datos_toma_cifras_y_nombres_en_negrita():
    nota = ("**Frasle** creció **15%** y facturó **US$ 1.500 millones** en 2026. El **catálogo digital** importa. "
            "Mirá [la nota 2025](https://n/9).")
    datos = verificacion.extraer_datos(nota)
    assert ("Frasle", "nombre") in datos and ("15%", "cifra") in datos and ("US$ 1.500 millones", "cifra") in datos
    assert all(d != "catálogo digital" for d, _ in datos)        # concepto en minúscula: no es un nombre
    assert all("2025" not in d for d, _ in datos)                # lo que está en un link no cuenta
    assert all(d != "2026" for d, _ in datos)                    # el año en curso no es un dato a verificar


def test_verificar_literal_sin_llamar_al_modelo(monkeypatch):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: pytest.fail("no hacía falta el modelo"))
    v = verificacion.verificar("**Frasle** invirtió **US$ 20 millones** y vendió 15 por ciento más.", NOTICIAS)
    assert v.sin_respaldo == [] and v.noticias_citadas == [0]


def test_lo_que_no_aparece_lo_decide_el_modelo(monkeypatch):
    monkeypatch.setattr(llm, "completar", lambda *a, **k:
                        '{"datos": [{"dato": "Bosch", "respaldado": true}, {"dato": "40%", "respaldado": false}]}')
    v = verificacion.verificar("**Bosch** y **Frasle** crecen un **40%**.", NOTICIAS)
    assert v.metodo == "literal+modelo" and v.sin_respaldo == ["40%"] and "Bosch" in v.respaldados
    assert v.grave and "40%" in verificacion.pedido_de_correccion(v)


def test_sin_modelo_las_cifras_no_encontradas_cuentan_como_sin_respaldo(monkeypatch):
    def caido(*a, **k):
        raise llm.ErrorLLM("caído")
    monkeypatch.setattr(llm, "completar", caido)
    v = verificacion.verificar("**Bosch** crece un **40%**.", NOTICIAS)
    assert v.sin_respaldo == ["40%"] and v.dudosos == ["Bosch"]


def test_el_extra_vale_como_fuente(monkeypatch):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: pytest.fail("no hacía falta el modelo"))
    v = verificacion.verificar("**Repuestos Norte** vende online.", NOTICIAS, extra="- Repuestos Norte: distribuidora")
    assert v.respaldados == ["Repuestos Norte"]


def test_sanear_enlaces():
    nota = "[a](https://n/1/) [b](https://inventado.com) [c](https://www.alephee.com/x) [d](https://blog.alephee.com)"
    texto, quitados = verificacion.sanear_enlaces(nota, NOTICIAS, permitidas=("https://otra.com/p",),
                                                  dominios=("alephee.com",))
    assert texto == "[a](https://n/1/) b [c](https://www.alephee.com/x) [d](https://blog.alephee.com)"
    assert quitados == ["https://inventado.com"]


def test_agregar_fuentes_reemplaza_la_del_modelo_y_respeta_la_meta():
    nota = "# T\n\nTexto.\n\n## Fuentes\n- [inventada](https://x)\n\n*Meta.*"
    out = verificacion.agregar_fuentes(nota, NOTICIAS[:1])
    assert out.count("## Fuentes") == 1 and "inventada" not in out
    assert out.endswith("- [Frasle amplía su planta](https://n/1)\n\n*Meta.*")
    assert verificacion.agregar_fuentes("# T\n\nTexto.", []) == "# T\n\nTexto."


# ── Plan ──────────────────────────────────────────────────────────────────────


def test_plan_valido_y_formateado(monkeypatch):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: (
        'Plan: {"angulo": "A", "titulo": "T", "palabra_clave": "Pastillas", "secciones": ['
        '{"titulo": "S1", "idea": "I1", "noticias": [1, 9]}, {"titulo": "S2", "idea": "I2"}], "implicancias": ["x"]}'))
    p = plan.planificar(NOTICIAS, "Escribí", ["paso"])
    assert p["palabra_clave"] == "pastillas" and p["secciones"][0]["noticias"] == [1]   # el 9 no existe
    txt = plan.formatear(p)
    assert "1. S1: I1 (noticias [1])" in txt and "2. S2: I2 (análisis, sin cifras)" in txt
    assert plan.noticias_del_plan(p, NOTICIAS) == [NOTICIAS[0]]


@pytest.mark.parametrize("respuesta", ["nada", '{"titulo": "T", "secciones": [{"titulo": "una sola"}]}'])
def test_plan_invalido_es_none(monkeypatch, respuesta):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: respuesta)
    assert plan.planificar(NOTICIAS, "Escribí", []) is None


# ── Fichas ────────────────────────────────────────────────────────────────────


def test_fichar_articulo(monkeypatch):
    from afterdrive.ia import lm_studio
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "completar", lambda *a, **k: (
        '{"resumen": "Frasle amplía.", "hechos": ["a"], "cifras": ["USD 20 millones"], "empresas": ["Frasle"], '
        '"fecha": "ayer"}'))
    f = lm_studio.fichar_articulo("t", "cuerpo")
    assert f == {"resumen": "Frasle amplía.", "hechos": ["a"], "cifras": ["USD 20 millones"],
                 "empresas": ["Frasle"], "fecha": None}
    monkeypatch.setattr(llm, "completar", lambda *a, **k: "basura")
    assert lm_studio.fichar_articulo("t", "cuerpo") is None


def test_la_ingesta_guarda_la_ficha(monkeypatch):
    from afterdrive.ingesta import ingesta
    guardados = []
    monkeypatch.setattr(ingesta, "clasificar", lambda t, c: {"aprobado": True, "razon": "ok"})
    monkeypatch.setattr(ingesta.lm_studio, "fichar_articulo", lambda t, c: {"resumen": "R"})
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [None] * len(textos))
    monkeypatch.setattr(ingesta.col_articulos, "bulk_write", lambda ops: guardados.extend(ops))
    ingesta.ingerir([{"url": "https://a", "titulo": "t", "cuerpo": "c"}])
    assert guardados[0]._doc["$set"]["ficha"] == {"resumen": "R"}

    monkeypatch.setenv("FICHAS_NOTICIAS", "0")
    monkeypatch.setattr(ingesta.lm_studio, "fichar_articulo", lambda t, c: pytest.fail("fichas apagadas"))
    ingesta.ingerir([{"url": "https://b", "titulo": "t", "cuerpo": "c"}])
