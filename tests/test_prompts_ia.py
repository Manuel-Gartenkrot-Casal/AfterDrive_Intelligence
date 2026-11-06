"""Prompts con IA: análisis de las calificaciones y la copia de los prompts que cambia la IA."""

import json

import mongomock
import pytest

from afterdrive import prompts_editables as pe
from afterdrive import prompts_ia
from afterdrive.ia import llm, redaccion

SEO_IA = "## SEO\n- Título de menos de 60 caracteres.\n- Palabra clave en el primer párrafo y en un subtítulo."


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def _nota(puntaje, calificacion, errores=(), alephee=None, juego="actuales", humana=None):
    n = {"critica": {"puntaje": puntaje, "aspectos": {"tono": puntaje - 1, "redaccion": puntaje},
                     "errores": [{"tipo": t, "problema": p} for t, p in errores]},
         "juicio": {"pasa": calificacion >= 4, "calificacion": calificacion, "etiquetas": ["generica"],
                    "alephee": alephee or {}},
         "prompts_juego": juego}
    if humana:
        n["calificacion"] = {"puntaje": humana, "etiquetas": [], "comentario": "le falta un dato"}
    return n


def _ia(monkeypatch, respuesta):
    pedidos = []
    monkeypatch.setattr(llm, "disponible", lambda: True)

    def completar(system, user, **kw):
        pedidos.append((system, user, kw))
        return json.dumps(respuesta)
    monkeypatch.setattr(llm, "completar", completar)
    return pedidos


def test_las_estadisticas_dicen_que_falla_y_comparan_los_juegos():
    notas = [_nota(7, 4, [("tono", "Tutea en una nota con voseo."), ("redaccion", "Repite la idea.")],
                   {"cta_unico": False}, humana=4),
             _nota(8, 4, [("tono", "Mezcla usted y vos.")], {"cta_unico": False, "nada_inventado": True}),
             _nota(9, 5, [], juego="ia")]
    e = prompts_ia.estadisticas(notas)
    assert e["notas"] == 3 and e["redaccion"] == 8.0 and e["juez"] == 4.3 and e["humana"] == 4.0
    assert e["errores"][0] == {"tipo": "tono", "nombre": "Tono", "veces": 2,
                               "ejemplos": ["Tutea en una nota con voseo.", "Mezcla usted y vos."]}
    assert e["alephee"] == [{"punto": "cta_unico", "texto": e["alephee"][0]["texto"], "veces": 2}]
    assert e["por_juego"] == {"actuales": {"notas": 2, "redaccion": 7.5, "juez": 4.0},
                              "ia": {"notas": 1, "redaccion": 9.0, "juez": 5.0}}
    assert e["aspectos"]["tono"] == 7.0 and e["comentarios"] == ["le falta un dato"]


def test_analizar_guarda_las_estadisticas_y_el_diagnostico(monkeypatch, base):
    base.notas_fase2.insert_many([_nota(7, 4, [("tono", "Tutea.")]), _nota(8, 4)])
    pedidos = _ia(monkeypatch, {"resumen": "El tono no es parejo.", "problemas": [
        {"titulo": "Tuteo", "detalle": "Mezcla tú y vos", "evidencia": "2 notas", "pieza": "identidad",
         "pedido": "Pedir voseo siempre"},
        {"titulo": "Sin pieza", "pieza": "inventada"}, {"detalle": "sin título"}]})
    a = prompts_ia.analizar(base=base)
    assert a["estadisticas"]["notas"] == 2
    assert a["diagnostico"]["resumen"] == "El tono no es parejo."
    assert [(p["titulo"], p["pieza"]) for p in a["diagnostico"]["problemas"]] == [("Tuteo", "identidad"), ("Sin pieza", "")]
    assert a["diagnostico"]["problemas"][0]["titulo_pieza"] == "Identidad"
    system, user, kw = pedidos[0]
    assert '"notas": 2' in user and '<pieza clave="seo"' in user and kw["tarea"] == "evaluacion"
    assert prompts_ia.estado(base)["analisis"]["diagnostico"]["resumen"] == "El tono no es parejo."


def test_sin_ia_el_analisis_muestra_solo_los_numeros(monkeypatch, base):
    base.notas_fase2.insert_one(_nota(7, 4))
    monkeypatch.setattr(llm, "disponible", lambda: False)
    a = prompts_ia.analizar(base=base)
    assert a["estadisticas"]["notas"] == 1 and "diagnostico" not in a and "solo los números" in a["error"]
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.analizar(base=mongomock.MongoClient().db)   # sin notas


def test_proponer_aplicar_y_usar_la_copia_sin_tocar_los_actuales(monkeypatch, base, prompts_ia_en_memoria):
    _ia(monkeypatch, {"comentario": "Más precisa.", "cambios": [
        {"clave": "seo", "explicacion": "Pide la palabra clave en un subtítulo.", "contenido": SEO_IA},
        {"clave": "persona_comercial", "explicacion": "Rota", "contenido": "Solo un rol, sin secciones."},
        {"clave": "inventada", "contenido": "x"},
        {"clave": "formato", "contenido": redaccion.PIEZAS["formato"]}]})   # igual: no es un cambio
    p = prompts_ia.proponer("Que las notas usen la palabra clave en un subtítulo", base=base)
    assert [c["clave"] for c in p["cambios"]] == ["seo", "persona_comercial"]
    seo, persona = p["cambios"]
    assert seo["antes"] == redaccion.PIEZAS["seo"] and seo["despues"] == SEO_IA and not seo["errores"]
    assert persona["errores"]                                           # una persona sin secciones no se aplica
    # Pendiente: todavía nada cambió.
    assert prompts_ia.estado(base)["propuestas"][0]["id"] == p["id"] and prompts_ia.estado(base)["cambiadas"] == 0

    e = prompts_ia.aplicar(p["id"], base=base)
    assert e["cambiadas"] == 1 and e["propuestas"] == []
    pieza = prompts_ia.pieza("seo", base=base)
    assert pieza["ia"] == SEO_IA and pieza["actual"] == redaccion.PIEZAS["seo"] and pieza["cambiada"]
    assert pieza["cambios"][0]["pedido"].startswith("Que las notas")
    # Con los actuales elegidos, la redacción no ve la copia.
    assert pe.activos(base=base) == {} and prompts_ia.en_uso(base) == {}
    prompts_ia.usar("ia", base=base)
    assert prompts_ia_en_memoria["usar"] == "ia"
    assert pe.activos(base=base) == {"seo": SEO_IA}
    assert base.prompts.count_documents({}) == 0                        # los actuales siguen intactos
    prompts_ia.usar("actuales", base=base)
    assert pe.activos(base=base) == {}
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.aplicar(p["id"], base=base)                           # ya aplicada


def test_la_copia_se_marca_desactualizada_si_cambian_los_actuales(monkeypatch, base):
    _ia(monkeypatch, {"cambios": [{"clave": "seo", "contenido": SEO_IA}]})
    prompts_ia.aplicar(prompts_ia.proponer("Más SEO en los subtítulos", base=base)["id"], base=base)
    assert not prompts_ia.pieza("seo", base=base)["desactualizada"]
    pe.guardar_borrador("seo", "## SEO\n- Otra regla.", base=base)
    pe.enviar("seo", base=base)
    pe.aprobar("seo", 1, base=base)
    assert prompts_ia.pieza("seo", base=base)["desactualizada"]
    assert [c["desactualizada"] for c in prompts_ia.estado(base)["copia"] if c["clave"] == "seo"] == [True]
    assert prompts_ia.restablecer("seo", base=base) == 1 and not prompts_ia.pieza("seo", base=base)["cambiada"]


def test_descartar_y_pedidos_invalidos(monkeypatch, base):
    _ia(monkeypatch, {"cambios": [{"clave": "seo", "contenido": SEO_IA}]})
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.proponer("corto", base=base)
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.proponer("Cambiá solo la identidad", claves=["identidad"], base=base)   # propuso otra pieza
    p = prompts_ia.proponer("Más SEO en los subtítulos", base=base)
    prompts_ia.descartar(p["id"], base=base)
    assert prompts_ia.estado(base)["propuestas"] == []
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.descartar("no-es-un-id", base=base)
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.usar("otro", base=base)


def test_api_de_prompts_con_ia(api, monkeypatch):
    flask_api, _ = api
    c = flask_api.app.test_client()
    c.post("/api/login", json={"usuario": "admin", "password": "secreta123"})
    assert c.get("/api/prompts-ia").get_json()["usar"] == "actuales"
    assert c.post("/api/prompts-ia/usar", json={"usar": "ia"}).get_json()["usar"] == "ia"
    assert c.post("/api/prompts-ia/usar", json={"usar": "x"}).status_code == 400
    assert c.post("/api/prompts-ia/proponer", json={"pedido": "x"}).status_code == 400
    assert c.get("/api/prompts-ia/pieza/seo").get_json()["actual"] == redaccion.PIEZAS["seo"]
    assert c.post("/api/prompts-ia/restablecer", json={}).get_json()["restablecidas"] == 0
