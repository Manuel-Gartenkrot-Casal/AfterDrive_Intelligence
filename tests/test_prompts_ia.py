"""Prompts con IA: la IA analiza las calificaciones y mejora sola una copia de los prompts."""

import json

import mongomock
import pytest

from afterdrive import prompts_editables as pe
from afterdrive import prompts_ia
from afterdrive.ia import llm, redaccion

SEO_IA = "## SEO\n- Título de menos de 60 caracteres.\n- Palabra clave en el primer párrafo y en un subtítulo."
FORMATO_IA = redaccion.PIEZAS["formato"] + "\n- Una sola llamada a la acción, en el último párrafo."
DIAGNOSTICO = {"resumen": "Pierden puntos por el SEO y la llamada a la acción.", "problemas": [
    {"titulo": "Palabra clave", "detalle": "No aparece en subtítulos", "evidencia": "5 notas", "pieza": "seo",
     "pedido": "Pedir la palabra clave en un subtítulo"},
    {"titulo": "Dos CTA", "pieza": "formato", "pedido": "Una sola llamada a la acción"},
    {"titulo": "Sin pieza", "pieza": "inventada"}, {"detalle": "sin título"}]}


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


def _ia(monkeypatch, *respuestas):
    """La IA responde en orden (la última se repite). Devuelve los pedidos que recibió."""
    pedidos, cola = [], list(respuestas)
    monkeypatch.setattr(llm, "disponible", lambda: True)

    def completar(system, user, **kw):
        pedidos.append((system, user, kw))
        return json.dumps(cola.pop(0) if len(cola) > 1 else cola[0])
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
    pedidos = _ia(monkeypatch, DIAGNOSTICO)
    a = prompts_ia.analizar(base=base)
    assert a["estadisticas"]["notas"] == 2 and a["diagnostico"]["resumen"].startswith("Pierden puntos")
    assert [(p["titulo"], p["pieza"]) for p in a["diagnostico"]["problemas"]] == [
        ("Palabra clave", "seo"), ("Dos CTA", "formato"), ("Sin pieza", "")]
    system, user, kw = pedidos[0]
    assert '"notas": 2' in user and '<pieza clave="seo"' in user and kw["tarea"] == "evaluacion"
    assert prompts_ia.estado(base)["analisis"]["diagnostico"]["problemas"][0]["titulo_pieza"] == "SEO"


def test_sin_ia_el_analisis_muestra_solo_los_numeros(monkeypatch, base):
    base.notas_fase2.insert_one(_nota(7, 4))
    monkeypatch.setattr(llm, "disponible", lambda: False)
    a = prompts_ia.analizar(base=base)
    assert a["estadisticas"]["notas"] == 1 and "diagnostico" not in a and "solo los números" in a["error"]
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.analizar(base=mongomock.MongoClient().db)   # sin notas
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.mejorar(base=base)                          # sin IA no se mejora


def test_mejorar_analiza_y_aplica_directo_a_la_copia_sin_tocar_los_actuales(monkeypatch, base, prompts_ia_en_memoria):
    base.notas_fase2.insert_many([_nota(7, 4), _nota(8, 3)])
    pedidos = _ia(monkeypatch, DIAGNOSTICO, {"comentario": "Dos reglas nuevas.", "cambios": [
        {"clave": "seo", "explicacion": "Palabra clave en un subtítulo.", "contenido": SEO_IA},
        {"clave": "formato", "explicacion": "Una sola CTA.", "contenido": FORMATO_IA},
        {"clave": "identidad", "contenido": "No estaba en el diagnóstico."}]})
    m = prompts_ia.mejorar(base=base)
    assert m["origen"] == "manual" and m["resumen"].startswith("Pierden puntos") and not m.get("error")
    assert [(c["clave"], c["aplicado"]) for c in m["cambios"]] == [("seo", True), ("formato", True)]
    # La reescritura recibe el pedido armado con el diagnóstico y solo las piezas diagnosticadas.
    assert "Pedir la palabra clave en un subtítulo" in pedidos[1][1] and "formato, seo" in pedidos[1][1]
    assert pedidos[1][2]["tarea"] == "correccion"
    assert prompts_ia.pieza("seo", base=base)["ia"] == SEO_IA
    assert base.prompts.count_documents({}) == 0                     # los actuales siguen intactos
    assert pe.activos(base=base) == {}                               # y la redacción los usa
    prompts_ia.usar("ia", base=base)
    assert prompts_ia_en_memoria["usar"] == "ia"
    assert pe.activos(base=base) == {"seo": SEO_IA, "formato": FORMATO_IA}
    e = prompts_ia.estado(base)
    assert e["cambiadas"] == 2 and e["mejoras"][0]["id"] == m["id"]


def test_un_pedido_se_aplica_y_se_puede_deshacer(monkeypatch, base):
    _ia(monkeypatch, {"cambios": [
        {"clave": "seo", "explicacion": "Subtítulos.", "contenido": SEO_IA},
        {"clave": "persona_comercial", "contenido": "Solo un rol, sin secciones."}]})   # inválida: no se aplica
    m = prompts_ia.mejorar("Que las notas usen la palabra clave en un subtítulo", base=base)
    assert m["origen"] == "pedido" and [(c["clave"], c["aplicado"]) for c in m["cambios"]] == [
        ("seo", True), ("persona_comercial", False)]
    assert m["cambios"][1]["errores"] and not prompts_ia.pieza("persona_comercial", base=base)["cambiada"]
    _ia(monkeypatch, {"cambios": [{"clave": "seo", "contenido": SEO_IA + "\n- Otra regla."}]})
    prompts_ia.mejorar("Sumá otra regla al SEO de la copia", base=base)
    p = prompts_ia.pieza("seo", base=base)
    assert p["ia"].endswith("Otra regla.") and len(p["cambios"]) == 2 and "antes" not in p["cambios"][0]
    assert prompts_ia.deshacer("seo", base=base)["ia"] == SEO_IA
    assert not prompts_ia.deshacer("seo", base=base)["cambiada"]      # vuelve a ser la actual
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.deshacer("seo", base=base)
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.mejorar("corto", base=base)


def test_la_mejora_automatica_corre_cada_cinco_notas_nuevas(monkeypatch, base, prompts_ia_en_memoria):
    _ia(monkeypatch, DIAGNOSTICO, {"cambios": [{"clave": "seo", "contenido": SEO_IA}]})
    base.notas_fase2.insert_many([_nota(7, 4) for _ in range(4)])
    assert prompts_ia.mejora_automatica(base=base) is None and prompts_ia.estado(base)["faltan"] == 1
    base.notas_fase2.insert_one(_nota(8, 4))
    m = prompts_ia.mejora_automatica(base=base)
    assert m["origen"] == "automatica" and m["cambios"][0]["aplicado"]
    assert prompts_ia.estado(base)["faltan"] == prompts_ia.AUTO_CADA     # cuenta de nuevo
    assert prompts_ia.mejora_automatica(base=base) is None
    base.notas_fase2.insert_many([_nota(8, 4) for _ in range(5)])
    prompts_ia.set_auto(False, base=base)
    assert prompts_ia_en_memoria["auto"] is False and prompts_ia.mejora_automatica(base=base) is None


def test_la_copia_se_marca_desactualizada_si_cambian_los_actuales(monkeypatch, base):
    _ia(monkeypatch, {"cambios": [{"clave": "seo", "contenido": SEO_IA}]})
    prompts_ia.mejorar("Más SEO en los subtítulos", base=base)
    assert not prompts_ia.pieza("seo", base=base)["desactualizada"]
    pe.guardar_borrador("seo", "## SEO\n- Otra regla.", base=base)
    pe.enviar("seo", base=base)
    pe.aprobar("seo", 1, base=base)
    assert prompts_ia.pieza("seo", base=base)["desactualizada"]
    assert [c["desactualizada"] for c in prompts_ia.estado(base)["copia"] if c["clave"] == "seo"] == [True]
    assert prompts_ia.restablecer("seo", base=base) == 1 and not prompts_ia.pieza("seo", base=base)["cambiada"]
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.usar("otro", base=base)


def test_api_de_prompts_con_ia(api, monkeypatch):
    flask_api, _ = api
    encoladas = []
    monkeypatch.setattr(flask_api.cola, "encolar", lambda tipo, params, origen="manual", etiqueta=None: encoladas.append(
        (tipo, params, etiqueta)) or {"id": "x", "posicion": 1, "duplicada": False})
    c = flask_api.app.test_client()
    c.post("/api/login", json={"usuario": "admin", "password": "secreta123"})
    e = c.get("/api/prompts-ia").get_json()
    assert e["usar"] == "actuales" and e["auto"] is True and e["faltan"] == prompts_ia.AUTO_CADA
    assert c.post("/api/prompts-ia/usar", json={"usar": "ia"}).get_json()["usar"] == "ia"
    assert c.post("/api/prompts-ia/usar", json={"usar": "x"}).status_code == 400
    assert c.post("/api/prompts-ia/auto", json={"auto": False}).get_json()["auto"] is False
    assert c.post("/api/prompts-ia/mejorar", json={}).status_code == 202
    assert c.post("/api/prompts-ia/mejorar", json={"pedido": "Que use voseo siempre", "claves": ["identidad"]}).status_code == 202
    assert c.post("/api/prompts-ia/mejorar", json={"pedido": "x"}).status_code == 400
    assert encoladas == [
        ("script", {"modulo": "afterdrive.prompts_ia", "argv": []}, "Mejorar prompts con IA"),
        ("script", {"modulo": "afterdrive.prompts_ia", "argv": ["--pedido", "Que use voseo siempre", "--claves", "identidad"]},
         "Cambiar prompts con IA")]
    assert c.post("/api/prompts-ia/deshacer", json={"clave": "seo"}).status_code == 400
    assert c.get("/api/prompts-ia/pieza/seo").get_json()["actual"] == redaccion.PIEZAS["seo"]
    assert c.post("/api/prompts-ia/restablecer", json={}).get_json()["restablecidas"] == 0


def test_la_linea_de_comandos_mejora_y_avisa(monkeypatch, capsys):
    monkeypatch.setattr(llm, "disponible", lambda: False)
    assert prompts_ia.main(["--pedido", "Que use voseo siempre"]) == 1
    assert "[ERROR]" in capsys.readouterr().out
    assert prompts_ia.main(["--auto"]) == 0
