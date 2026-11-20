"""Tests de los filtros de la redacción (generacion/filtros.py)."""

import mongomock

from afterdrive.generacion import filtros, juez
from afterdrive.generacion import generar_nota_fase2 as g
from afterdrive.ia import redaccion

FRASLE = filtros.Contexto([{"nombre": "Frasle"}])


def test_las_reglas_de_cada_filtro_van_al_prompt():
    system = g._build_system_prompt(["autopartes"], [], None, "comercial", prohibidos=[{"nombre": "Frasle"}])
    assert "Nunca nombres a estas empresas, aunque aparezcan en las noticias: Frasle." in system
    assert redaccion.PIEZAS["privacidad"] in system
    # Sin empresas prohibidas no se pide nada de eso; la privacidad va siempre.
    sin = filtros.reglas(filtros.Contexto())
    assert sin == [redaccion.PIEZAS["privacidad"]]


def test_la_regla_de_privacidad_es_la_pieza_editable():
    propia = "## Privacidad\n- Nunca nombres a personas."
    assert filtros.reglas(filtros.Contexto(piezas={"privacidad": propia})) == [propia]
    system = g._build_system_prompt(["autopartes"], [], None, "comercial", piezas={"privacidad": propia})
    assert propia in system and redaccion.PIEZAS["privacidad"] not in system


def test_revisar_devuelve_un_campo_por_filtro():
    texto = "Frasle amplía su planta. Consultas: ventas@frasle.com o +54 11 4567-8901. El contrato es por USD 5.000."
    assert filtros.revisar(texto, FRASLE) == {"empresas_prohibidas": ["Frasle"], "datos_sensibles": ["email", "telefono"]}
    # Los montos no se marcan en las notas: hablar de precios del mercado es normal.
    assert filtros.revisar("Un contrato de USD 5.000 por año.", FRASLE)["datos_sensibles"] == []


def test_datos_sensibles_solo_avisa_y_empresas_prohibidas_frena():
    hallazgos = {"empresas_prohibidas": [], "datos_sensibles": ["email"]}
    assert filtros.problemas(hallazgos) == []
    assert filtros.motivos(hallazgos) == []
    hallazgos["empresas_prohibidas"] = ["Frasle"]
    assert [c for c, _ in filtros.problemas(hallazgos)] == ["empresa_prohibida"]
    assert filtros.motivos(hallazgos) == ["nombra empresas que no se pueden mencionar: Frasle"]


def test_el_juez_no_frena_por_datos_sensibles():
    doc = {"calidad": {"puntaje": 9, "fallas_criticas": []}, "imagen": {"url": "x"}, "datos_sensibles": ["telefono"]}
    assert juez.filtro_duro(doc, umbral=6) == []


PATENTES = filtros.Filtro(
    campo="patentes",
    regla=lambda ctx: "- No escribas patentes de autos.",
    revisar=lambda texto, ctx: ["AB123CD"] if "AB123CD" in texto else [],
    titulo="Tiene patentes", indicacion="Sacalas.",
    frena=True, codigo="patente",
    pedido=lambda h: "sacá las patentes",
    motivo=lambda h: "tiene patentes: " + ", ".join(h),
)


def test_sumar_un_filtro_no_toca_la_generacion_ni_el_juez(monkeypatch):
    monkeypatch.setattr(filtros, "FILTROS", [*filtros.FILTROS, PATENTES])
    assert "- No escribas patentes de autos." in g._build_system_prompt(["autopartes"], [], None, "comercial")
    hallazgos = filtros.revisar("El auto AB123CD.", filtros.Contexto())
    assert hallazgos["patentes"] == ["AB123CD"]
    assert ("patente", "sacá las patentes") in filtros.problemas(hallazgos)
    doc = {"calidad": {"puntaje": 9, "fallas_criticas": []}, "imagen": {"url": "x"}, **hallazgos}
    assert juez.filtro_duro(doc, umbral=6) == ["tiene patentes: AB123CD"]
    assert filtros.para_el_dashboard()[-1] == {"campo": "patentes", "titulo": "Tiene patentes",
                                               "indicacion": "Sacalas.", "frena": True, "nombres": {}}


def test_dos_filtros_no_pueden_guardar_en_el_mismo_campo(monkeypatch):
    import dataclasses

    import pytest
    otro = dataclasses.replace(PATENTES, campo="empresas_prohibidas")
    monkeypatch.setattr(filtros, "FILTROS", [*filtros.FILTROS, otro])
    with pytest.raises(ValueError, match="mismo campo"):
        filtros.revisar("texto", filtros.Contexto())


def test_el_dashboard_sabe_mostrar_cada_filtro(api):
    flask_api, _ = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    d = c.get("/api/filtros").json["filtros"]
    assert [f["campo"] for f in d] == ["empresas_prohibidas", "datos_sensibles"]
    assert d[0]["frena"] and not d[1]["frena"] and d[1]["nombres"]["telefono"] == "Teléfono"
    partes = c.post("/api/prompts/vista-previa", json={}).json["partes"]
    assert partes[-1]["clave"] == "privacidad" and partes[-1]["titulo"] == "Privacidad"


def test_editar_una_nota_recalcula_los_datos_sensibles():
    from afterdrive import historial
    base = mongomock.MongoClient().db
    oid = base.notas_fase2.insert_one({"contenido": "# T\n\nTexto.", "estado": "borrador"}).inserted_id
    cuerpo = "# Título\n\n" + "La demanda de repuestos crece en todo el país. " * 10
    historial.editar("notas_fase2", str(oid), cuerpo + "Pedidos: ventas@acme.com.", base=base)
    nota = base.notas_fase2.find_one({"_id": oid})
    assert nota["datos_sensibles"] == ["email"] and nota["empresas_prohibidas"] == []
    historial.editar("notas_fase2", str(oid), cuerpo, base=base)
    assert base.notas_fase2.find_one({"_id": oid})["datos_sensibles"] == []
