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
    {"titulo": "Dos CTA", "evidencia": "3 notas con CTA duplicada", "pieza": "formato", "pedido": "Una sola llamada a la acción"},
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
    # Estos tests ejercitan edición/historial. La comparación real y sus rechazos
    # se prueban de extremo a extremo (LLM simulado) en test_prompts_evaluacion.
    monkeypatch.setattr(prompts_ia.prueba, "comparar", lambda *a, **kw: {
        "estado": "aprobada", "tipo": "redaccion", "antes": 8, "despues": 9, "casos": [], "motivo": "Prueba"})
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
                               "ejemplos": [{"problema": p, "fragmento": "", "sugerencia": ""}
                                             for p in ["Tutea en una nota con voseo.", "Mezcla usted y vos."]]}
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


def test_mejorar_solo_cambia_piezas_con_evidencia_y_prueba_sin_tocar_actuales(monkeypatch, base, prompts_ia_en_memoria):
    base.notas_fase2.insert_many([_nota(7, 4), _nota(8, 3)])
    pedidos = _ia(monkeypatch, DIAGNOSTICO, {"comentario": "Dos reglas nuevas.", "cambios": [
        {"clave": "seo", "explicacion": "Palabra clave en un subtítulo.", "contenido": SEO_IA},
        {"clave": "formato", "explicacion": "Una sola CTA.", "contenido": FORMATO_IA},
        {"clave": "identidad", "contenido": "Sos un redactor B2B. También fuera del diagnóstico: se aplica."}]})
    m = prompts_ia.mejorar(base=base)
    assert m["origen"] == "manual" and m["resumen"].startswith("Pierden puntos") and not m.get("error")
    # Se excluyen cambios ajenos al diagnóstico aunque el modelo los proponga.
    assert [(c["clave"], c["aplicado"]) for c in m["cambios"]] == [("seo", True), ("formato", True)]
    assert "Pedir la palabra clave en un subtítulo" in pedidos[1][1]
    assert pedidos[1][2]["tarea"] == "correccion"
    assert prompts_ia.pieza("seo", base=base)["ia"] == SEO_IA
    assert base.prompts.count_documents({}) == 0                     # los actuales siguen intactos
    assert pe.activos(base=base) == {}                               # y la redacción los usa
    prompts_ia.usar("ia", base=base)
    assert prompts_ia_en_memoria["usar"] == "ia"
    assert pe.activos(base=base)["seo"] == SEO_IA and pe.activos(base=base)["formato"] == FORMATO_IA
    e = prompts_ia.estado(base)
    assert e["cambiadas"] == 2 and e["mejoras"][0]["id"] == m["id"]
    # Cada juego se puede ver entero, sea cual sea el que está en uso.
    assert prompts_ia.textos("actuales", base)["seo"] == redaccion.PIEZAS["seo"]
    assert prompts_ia.textos("ia", base)["seo"] == SEO_IA and prompts_ia.textos("ia", base)["oficio"] == redaccion.PIEZAS["oficio"]


def test_una_pieza_invalida_se_le_devuelve_a_la_ia_para_corregirla(monkeypatch, base):
    persona = redaccion.PIEZAS["persona_comercial"] + "\n- Voseo siempre."
    pedidos = _ia(monkeypatch, {"cambios": [{"clave": "persona_comercial", "contenido": "Solo un rol, sin secciones."}]},
                  {"cambios": [{"clave": "persona_comercial", "contenido": persona}]})
    m = prompts_ia.mejorar("Que la persona Comercial use voseo siempre", base=base)
    assert m["cambios"][0]["aplicado"] and m["cambios"][0]["despues"] == persona and not m.get("error")
    assert "## Errores" in pedidos[1][1]                                # la corrección recibió los errores


def test_un_pedido_se_aplica_y_se_puede_deshacer(monkeypatch, base):
    _ia(monkeypatch, {"cambios": [
        {"clave": "seo", "explicacion": "Subtítulos.", "contenido": SEO_IA},
        {"clave": "persona_comercial", "contenido": "Solo un rol, sin secciones."}]})   # inválida aunque se corrija: no se aplica
    m = prompts_ia.mejorar("Que las notas usen la palabra clave en un subtítulo", base=base)
    assert m["origen"] == "pedido" and [(c["clave"], c["aplicado"]) for c in m["cambios"]] == [
        ("seo", False), ("persona_comercial", False)]
    assert m["cambios"][1]["errores"] and not prompts_ia.pieza("persona_comercial", base=base)["cambiada"]
    assert base.prompts_ia.count_documents({}) == 0
    _ia(monkeypatch, {"cambios": [{"clave": "seo", "contenido": SEO_IA}]})
    prompts_ia.mejorar("Agregá SEO en los subtítulos", base=base)
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


def test_una_pieza_que_se_infla_no_se_aplica(monkeypatch, base):
    """Apilar reglas mejora tras mejora era lo que bajaba las notas de 8 a 6: una pieza no crece más de un 25%."""
    inflada = redaccion.PIEZAS["formato"] + "\n" + "\n".join(f"- Regla extra número {i} para la nota." for i in range(30))
    pedidos = _ia(monkeypatch, {"cambios": [{"clave": "formato", "contenido": inflada}]})   # la corrección también infla
    m = prompts_ia.mejorar("Que las notas cumplan más reglas de formato", claves=["formato"], base=base)
    assert not m["cambios"][0]["aplicado"] and any("Creció de" in e for e in m["cambios"][0]["errores"])
    assert any("Creció de" in p[1] for p in pedidos)                    # se le pidió achicarla
    assert not prompts_ia.pieza("formato", base=base)["cambiada"]


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
    assert c.post("/api/prompts-ia/usar", json={"usar": "ia"}).status_code == 400
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


def test_la_vista_previa_arma_el_prompt_de_cada_juego(api, monkeypatch, base):
    from afterdrive import prompts_ia as pi
    monkeypatch.setattr(pi, "_base", lambda b=None: base)
    base.prompts_ia.insert_one({"clave": "seo", "contenido": SEO_IA, "cambios": []})
    flask_api, _ = api
    c = flask_api.app.test_client()
    c.post("/api/login", json={"usuario": "admin", "password": "secreta123"})
    # También se puede inspeccionar una copia antigua sin habilitar su uso.
    def seo(juego):
        partes = c.post("/api/prompts/vista-previa", json={"juego": juego}).get_json()["partes"]
        return next(p["texto"] for p in partes if p["clave"] == "seo")
    assert seo("actuales") == redaccion.PIEZAS["seo"] and seo("ia") == SEO_IA


def test_un_json_roto_de_la_ia_se_repara(monkeypatch, base):
    """Una comilla suelta dentro de un texto (pasó en producción: «Expecting ',' delimiter») no tira el análisis."""
    base.notas_fase2.insert_one(_nota(7, 4))
    monkeypatch.setattr(llm, "disponible", lambda: True)
    respuestas = ['{"resumen": "Usan "la tecnología" en general", "problemas": [{"titulo": "Foco", "pieza": "seo"}]}']
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: respuestas.pop(0))
    a = prompts_ia.analizar(base=base)
    assert a["diagnostico"]["resumen"] == 'Usan "la tecnología" en general' and not a.get("error")
    # Si ni así se puede leer, se le pide a la IA que lo corrija.
    pedidos = []
    respuestas[:] = ['{"resumen": "x", "problemas": [ {"titulo": "A" "pieza": "seo"} ]}',
                     '{"resumen": "x", "problemas": [{"titulo": "A", "pieza": "seo"}]}']

    def completar(system, user, **kw):
        pedidos.append(system)
        return respuestas.pop(0)
    monkeypatch.setattr(llm, "completar", completar)
    a = prompts_ia.analizar(base=base)
    assert a["diagnostico"]["problemas"][0]["titulo"] == "A" and len(pedidos) == 2 and "JSON válido" in pedidos[1]


def test_tambien_se_repara_la_coma_que_falta_entre_dos_problemas():
    roto = '{"resumen": "x",\n "problemas": [\n  {"titulo": "A", "pieza": "seo"}\n  {"titulo": "B", "pieza": "formato"}\n ]}'
    assert [p["titulo"] for p in prompts_ia._leer_json(roto)["problemas"]] == ["A", "B"]


@pytest.mark.parametrize("respuesta", [
    {"comentario": "Listo, cambié el SEO.", "cambios": []},
    {"cambios": [{"clave": "seo", "contenido": redaccion.PIEZAS["seo"]}]},
    {"cambios": [{"clave": "desconocida", "contenido": SEO_IA}]},
    {"cambios": [{"clave": "seo", "contenido": {"texto": SEO_IA}}]},
    {"cambios": "Cambié las reglas."},
])
def test_reintenta_si_la_respuesta_no_modifica_ninguna_pieza(monkeypatch, base, respuesta):
    pedidos = _ia(monkeypatch, respuesta, {"cambios": [{"clave": "seo", "contenido": SEO_IA}]})
    m = prompts_ia.mejorar("Poné la palabra clave en un subtítulo", base=base)
    assert len(pedidos) == 2 and "Corregí tu respuesta anterior" in pedidos[1][1]
    assert not m.get("error") and m["cambios"][0]["aplicado"]
    assert base.prompts_ia.find_one({"clave": "seo"})["contenido"] == SEO_IA


def test_no_oculta_el_motivo_si_el_pedido_no_se_puede_aplicar(monkeypatch, base):
    pedidos = _ia(monkeypatch, {"cambios": [], "comentario": "Este cambio necesita la pieza Imágenes."})
    m = prompts_ia.mejorar("Permití personas en portada", claves=["seo"], base=base)
    assert len(pedidos) == 2 and "necesita la pieza Imágenes" in m["error"]
    assert base.prompts_ia.count_documents({}) == 0


def test_un_pedido_manual_no_se_desvia_al_diagnostico_anterior(monkeypatch, base):
    base.prompts_ia_analisis.insert_one({"fecha": "2026-01-01", "diagnostico": DIAGNOSTICO})
    texto = "## Imágenes\n- Descartá multitudes o grupos posando que no ilustren el tema concreto de la nota."
    pedidos = _ia(monkeypatch, {"cambios": [{"clave": "imagenes", "contenido": texto}]})
    m = prompts_ia.mejorar("Restringí las imágenes: nada de grupos de personas sin relación con la nota", base=base)
    assert m["cambios"][0]["clave"] == "imagenes" and m["cambios"][0]["aplicado"]
    assert "grupos de personas sin relación" in pedidos[0][1] and '<pieza clave="imagenes"' in pedidos[0][1]
    assert "Pierden puntos por el SEO" not in pedidos[0][1]
    assert base.prompts.count_documents({}) == 0
    assert prompts_ia.deshacer("imagenes", base=base)["ia"] == redaccion.PIEZAS["imagenes"]


def test_respeta_la_pieza_elegida_y_no_amplia_el_alcance(monkeypatch, base):
    pedidos = _ia(monkeypatch, {"cambios": [{"clave": "formato", "contenido": FORMATO_IA}]},
                  {"cambios": [{"clave": "seo", "contenido": SEO_IA},
                               {"clave": "formato", "contenido": FORMATO_IA}]})
    m = prompts_ia.mejorar("Cambiá el SEO para incluir la palabra clave", claves=["seo"], base=base)
    assert len(pedidos) == 2 and [c["clave"] for c in m["cambios"]] == ["seo"]
    assert base.prompts_ia.find_one({"clave": "formato"}) is None


def test_reparar_no_cuenta_el_texto_original_como_cambio(monkeypatch, base):
    pedidos = _ia(monkeypatch, {"cambios": [{"clave": "formato", "contenido": "## Formato\n- Texto breve."}]},
                  {"cambios": [{"clave": "formato", "contenido": redaccion.PIEZAS["formato"]}]})
    m = prompts_ia.mejorar("Escribí oraciones de diez palabras como máximo", base=base)
    assert "diez palabras" in pedidos[1][1]
    assert m["error"] and not m["cambios"][0]["aplicado"]
    assert base.prompts_ia.count_documents({}) == 0


def test_un_pedido_incompleto_falla_sin_aplicar_un_subconjunto(monkeypatch, base):
    _ia(monkeypatch, {"cambios": [{"clave": "seo", "contenido": SEO_IA},
                                {"clave": "persona_comercial", "contenido": "Un rol sin secciones."}]})
    m = prompts_ia.mejorar("Mejorá el SEO y usá voseo en la persona Comercial", base=base)
    assert "incompleta" in m["error"] and not any(c["aplicado"] for c in m["cambios"])
    monkeypatch.setattr(prompts_ia, "mejorar", lambda **kw: m)
    assert prompts_ia.main(["--pedido", m["pedido"]]) == 1


@pytest.mark.parametrize("body", [
    {"pedido": "x" * (prompts_ia.PEDIDO_MAX + 1)},
    {"pedido": {"texto": "No convertir objetos en pedidos"}},
    {"pedido": "Cambiá las imágenes", "claves": ["desconocida"]},
    {"pedido": "Cambiá las imágenes", "claves": "imagenes"},
])
def test_pedidos_invalidos_no_se_recortan_ni_se_encolan(api, monkeypatch, body):
    flask_api, _ = api
    monkeypatch.setattr(flask_api.cola, "encolar", lambda *a, **kw: pytest.fail("No debe encolarse"))
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    assert c.post("/api/prompts-ia/mejorar", json=body).status_code == 400
    with pytest.raises(prompts_ia.ErrorPromptIA):
        prompts_ia.mejorar(**body)


def test_la_vista_previa_muestra_imagenes_sin_enviarlas_al_redactor(api, monkeypatch, base):
    monkeypatch.setattr(prompts_ia, "_base", lambda b=None: base if b is None else b)
    nuevo = "## Imágenes\n- Permití personas en portada y en el cuerpo."
    base.prompts_ia.insert_one({"clave": "imagenes", "contenido": nuevo})
    flask_api, _ = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    for juego, texto in (("actuales", redaccion.PIEZAS["imagenes"]), ("ia", nuevo)):
        r = c.post("/api/prompts/vista-previa", json={"juego": juego}).get_json()
        assert r["adicionales"] == [{"clave": "imagenes", "titulo": "Imágenes", "editable": True, "texto": texto}]
        assert texto not in r["prompt"] and "imagenes" not in [p["clave"] for p in r["partes"]]
    r = c.post("/api/prompts/vista-previa", json={"juego": "actuales", "clave": "imagenes", "contenido": nuevo}).get_json()
    assert r["adicionales"][0]["texto"] == nuevo
