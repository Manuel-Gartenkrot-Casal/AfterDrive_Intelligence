"""Regresiones del optimizador con proveedor simulado y evaluación real del pipeline."""
import json
from dataclasses import replace

import mongomock
import pytest

from afterdrive import prompts_evaluacion as prueba
from afterdrive import prompts_ia as pi
from afterdrive.generacion import critica, juez
from afterdrive.ia import llm, redaccion
from tests.test_generacion import NOTA

MARCA = "REGLA_NUEVA: vinculá el dato de la fuente al efecto concreto para el lector."
SEO = redaccion.PIEZAS["seo"] + "\n- " + MARCA
NUEVA = NOTA.replace("llega al mostrador", "llega al taller")


@pytest.fixture
def entorno(monkeypatch):
    base = mongomock.MongoClient().db
    monkeypatch.setattr(pi, "_base", lambda b=None: base if b is None else b)
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "ajustes_redaccion", lambda: llm.Redaccion())
    for i in range(3):
        base.notas_fase2.insert_one({
            "persona": "comercial", "contenido": NOTA, "critica": {"puntaje": 8},
            "prompts_prueba": {
                "user": f"Fuente original {i}: Frasle amplió su planta y la feria abrió acreditaciones.",
                "contexto": f"Fuente original {i}: Frasle amplió su planta y la feria abrió acreditaciones.",
                "opciones": {"categorias": ["autopartes"], "clientes": [], "persona": "comercial",
                             "puntapie_url": None, "regiones": ["argentina"], "idioma": "es"},
            },
        })
    return base


def proveedor(monkeypatch, *, antes=8, despues=9, juez_pasa=True, roto=False, cambios=None):
    llamadas = []
    def completar(system, user, **kw):
        llamadas.append((system, user, kw))
        if system == pi._SYSTEM_ANALISIS:
            return json.dumps({"resumen": "Falta conectar el dato con el efecto.", "problemas": [
                {"titulo": "Efecto concreto", "pieza": "seo", "evidencia": "3 ejemplos de frases genéricas",
                 "pedido": "Conectar la fuente con su efecto."}]})
        if system == pi._SYSTEM_MEJORA:
            return json.dumps({"cambios": cambios or [{"clave": "seo", "contenido": SEO}]})
        if system == critica._SYSTEM:
            if roto:
                return '{"puntaje": true}'
            score = despues if "llega al taller" in user else antes
            return json.dumps({"puntaje": score, "aspectos": dict.fromkeys(
                ("gramatica", "redaccion", "tono", "estructura"), score), "errores": []})
        if system == juez._SYSTEM:
            return json.dumps({"pasa": juez_pasa, "confianza": .95, "calificacion": 4,
                               "alephee": dict.fromkeys(juez.CHECKLIST_ALEPHEE, True)})
        assert kw["tarea"] == "redaccion"
        return NUEVA if MARCA in system else NOTA
    monkeypatch.setattr(llm, "completar", completar)
    return llamadas


@pytest.mark.parametrize("antes,despues,estado", [(8, 6, "rechazada"), (8, 8, "rechazada"), (8, 9, "aprobada")])
def test_automatico_compara_mismas_fuentes_y_no_publica_pruebas(monkeypatch, entorno, antes, despues, estado):
    llamadas = proveedor(monkeypatch, antes=antes, despues=despues)
    m = pi.mejorar(base=entorno)
    assert m["evaluacion"]["estado"] == estado
    assert m["evaluacion"]["antes"] == antes and m["evaluacion"]["despues"] == despues
    assert len(m["evaluacion"]["casos"]) == 3
    redacciones = [u for _, u, k in llamadas if k["tarea"] == "redaccion"]
    assert len(redacciones) == 6 and all(redacciones.count(u) == 2 for u in set(redacciones))
    assert entorno.notas_fase2.count_documents({}) == 3
    assert entorno.articulos.count_documents({}) == 0
    if estado == "aprobada":
        pi.usar("ia", entorno)
        assert pi.en_uso(entorno)["seo"] == SEO
    else:
        assert not m["cambios"][0]["aplicado"] and entorno.prompts_ia.count_documents({}) == 0
        with pytest.raises(pi.ErrorPromptIA):
            pi.usar("ia", entorno)


@pytest.mark.parametrize("opciones", [{"roto": True}, {"juez_pasa": False}])
def test_critica_invalida_o_juez_rechazado_no_habilitan_copia(monkeypatch, entorno, opciones):
    proveedor(monkeypatch, **opciones)
    m = pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    assert m["error"] and not pi.en_uso(entorno)
    assert entorno.prompts_ia.count_documents({}) == 0


def test_sin_fuentes_no_hay_activacion_ni_llamadas_para_notas_inventadas(monkeypatch, entorno):
    entorno.notas_fase2.update_many({}, {"$unset": {"prompts_prueba": ""}})
    llamadas = proveedor(monkeypatch)
    m = pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    assert m["evaluacion"]["estado"] == "no_evaluable" and "3 notas" in m["error"]
    assert not any(k["tarea"] == "redaccion" for _, _, k in llamadas)


def test_recupera_fuentes_reales_de_notas_anteriores(monkeypatch, entorno):
    for i, nota in enumerate(entorno.notas_fase2.find()):
        url = f"https://fuente.test/{i}"
        entorno.articulos.insert_one({"url": url, "titulo": f"Planta {i}", "cuerpo": (f"Hecho de la fuente {i}. " * 40)})
        entorno.notas_fase2.update_one({"_id": nota["_id"]}, {
            "$unset": {"prompts_prueba": ""}, "$set": {"fuentes": [{"url": url}], "idioma": "es"}})
    proveedor(monkeypatch)
    m = pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    assert m["evaluacion"]["estado"] == "aprobada"
    assert all(c["reconstruida"] for c in m["evaluacion"]["casos"])
    assert not any(n.get("usado_para_articulo") for n in entorno.articulos.find())


def test_sin_caras_aisla_imagenes_incluso_si_modelo_quiere_tocar_redaccion(monkeypatch, entorno):
    texto = redaccion.PIEZAS["imagenes"] + "\n- Excluí también cualquier rostro reflejado en espejos."
    llamadas = proveedor(monkeypatch, cambios=[{"clave": "imagenes", "contenido": texto},
                                               {"clave": "seo", "contenido": SEO}])
    antes = pi.textos("actuales", entorno)
    m = pi.mejorar("Que las imágenes no tengan caras, tampoco reflejadas", base=entorno)
    assert m["evaluacion"]["tipo"] == "imagenes" and not m.get("error")
    assert [c["clave"] for c in m["cambios"]] == ["imagenes"]
    pi.usar("ia", entorno)
    assert pi.en_uso(entorno) == {"imagenes": texto}
    for compacto in (False, True):
        for persona in redaccion.PERSONAS:
            assert redaccion.system_prompt(persona, compacto=compacto, piezas=antes) == redaccion.system_prompt(
                persona, compacto=compacto, piezas=pi.textos("ia", entorno))
    assert len(llamadas) == 1  # no gastar generaciones de texto para un cambio aislado de fotos


def test_copia_antigua_no_contamina_nueva_propuesta(monkeypatch, entorno, prompts_ia_en_memoria):
    entorno.prompts_ia.insert_one({"clave": "seo", "contenido": "## SEO\n- Escribí mal.", "cambios": []})
    prompts_ia_en_memoria["usar"] = "ia"
    assert pi.juego(entorno) == "actuales" and pi.en_uso(entorno) == {}
    proveedor(monkeypatch, cambios=[{"clave": "imagenes", "contenido": "## Imágenes\n- Solo piezas sin personas."}])
    m = pi.mejorar("Solo imágenes sin caras", base=entorno)
    assert not m.get("error")
    assert pi.textos("ia", entorno)["seo"] == redaccion.PIEZAS["seo"]
    assert pi.en_uso(entorno) == {"imagenes": "## Imágenes\n- Solo piezas sin personas."}


def test_caida_real_retira_version_aunque_mejora_automatica_este_apagada(monkeypatch, entorno):
    proveedor(monkeypatch)
    pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    pi.usar("ia", entorno)
    firma = pi.instantanea(entorno)["huella"]
    pi.set_auto(False, entorno)
    entorno.notas_fase2.insert_many([{"prompts_huella": firma, "critica": {"puntaje": 6}} for _ in range(3)])
    m = pi.mejora_automatica(entorno)
    assert m["origen"] == "proteccion" and m["evaluacion"]["despues"] == 6
    assert pi.juego(entorno) == "actuales" and pi.en_uso(entorno) == {}


def test_cambio_de_modelo_invalida_la_prueba(monkeypatch, entorno):
    proveedor(monkeypatch)
    pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    pi.usar("ia", entorno)
    perfil = llm._perfil_chat()
    monkeypatch.setattr(llm, "_perfil_chat", lambda: replace(perfil, modelo="otro"))
    assert pi.en_uso(entorno) == {} and pi.juego(entorno) == "actuales"


def test_un_cambio_durante_la_prueba_no_se_pisa(monkeypatch, entorno):
    proveedor(monkeypatch)
    comparar = prueba.comparar
    def concurrente(*a, **kw):
        resultado = comparar(*a, **kw)
        entorno.prompts_ia.insert_one({"clave": "identidad", "contenido": "Edición concurrente."})
        return resultado
    monkeypatch.setattr(prueba, "comparar", concurrente)
    m = pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    assert "cambiaron durante" in m["error"]
    assert entorno.prompts_ia.count_documents({}) == 1
    assert not entorno.prompts_ia_estado.find_one({"_id": "validada"})


def test_cancelar_no_aplica_ni_guarda_un_exito(monkeypatch, entorno):
    proveedor(monkeypatch)
    monkeypatch.setattr(llm, "verificar_cancelacion", lambda: (_ for _ in ()).throw(llm.Cancelada("Cancelado")))
    with pytest.raises(llm.Cancelada):
        pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    assert not entorno.prompts_ia.count_documents({})
    assert not entorno.prompts_ia_mejoras.count_documents({})


def test_persona_sin_casos_no_se_valida_con_otras(monkeypatch, entorno):
    proveedor(monkeypatch, cambios=[{"clave": "persona_ejecutivo", "contenido": redaccion.PIEZAS["persona_ejecutivo"] + "\n- " + MARCA}])
    m = pi.mejorar("Mejorá las notas de la persona Ejecutivo", base=entorno)
    assert m["evaluacion"]["estado"] == "no_evaluable"


def test_criterios_del_critico_no_cambian_con_la_propuesta(monkeypatch, entorno):
    llamadas = proveedor(monkeypatch, cambios=[{"clave": "persona_comercial", "contenido": redaccion.PIEZAS["persona_comercial"] + "\n- " + MARCA}])
    m = pi.mejorar("Mejorá el estilo comercial", base=entorno)
    assert not m.get("error")
    assert all(MARCA not in u for s, u, _ in llamadas if s == critica._SYSTEM)


def test_compacto_respeta_las_piezas_editadas_sin_reglas_duplicadas():
    piezas = dict(redaccion.PIEZAS, seo=SEO)
    partes = dict(redaccion.system_prompt_partes(compacto=True, piezas=piezas))
    assert MARCA in partes["seo"] and "reglas_compactas" not in partes


def test_cambiar_fotos_conserva_la_proteccion_de_redaccion(monkeypatch, entorno):
    proveedor(monkeypatch)
    pi.mejorar("Mejorá el SEO con efectos concretos", base=entorno)
    pi.usar("ia", entorno)
    proveedor(monkeypatch, cambios=[{"clave": "imagenes", "contenido": "## Imágenes\n- Solo repuestos sin rostros."}])
    m = pi.mejorar("Usá imágenes sin caras", base=entorno)
    assert m["evaluacion"]["tipo"] == "imagenes"
    firma = pi.instantanea(entorno)["huella"]
    entorno.notas_fase2.insert_many([{"prompts_huella": firma, "critica": {"puntaje": 6}} for _ in range(3)])
    assert pi.vigilar_calidad(entorno)["origen"] == "proteccion"
    assert pi.juego(entorno) == "actuales"


def test_regresion_en_un_caso_no_se_oculta_con_promedio_alto(monkeypatch, entorno):
    llamadas = proveedor(monkeypatch)
    completar = llm.completar
    scores = iter([7, 10, 10])
    def responder(system, user, **kw):
        if system == critica._SYSTEM and "llega al taller" in user:
            return json.dumps({"puntaje": next(scores), "aspectos": dict.fromkeys(
                ("gramatica", "redaccion", "tono", "estructura"), 8), "errores": []})
        return completar(system, user, **kw)
    monkeypatch.setattr(llm, "completar", responder)
    m = pi.mejorar(base=entorno)
    assert m["evaluacion"]["despues"] == 9 and m["evaluacion"]["estado"] == "rechazada"
    assert not entorno.prompts_ia.count_documents({}) and llamadas
