"""Tests de la imagen destacada generada con NVIDIA (imagenes.py) y su paso por el historial y HubSpot."""

import base64
import json

import mongomock
import pytest
from bson import ObjectId

from afterdrive import historial, hubspot, imagenes

PNG = b"\x89PNG\r\n\x1a\nfalso"
JPG = b"\xff\xd8\xff\xe0falso"


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


@pytest.fixture
def nvidia(monkeypatch):
    """Transporte falso de NVIDIA: responde en orden y guarda lo que se pidió."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.delenv("NVIDIA_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("NVIDIA_IMAGE_SIZE", raising=False)
    pedidos = []

    def instalar(*respuestas):
        cola = list(respuestas)

        def post(url, json=None, headers=None, timeout=None):
            pedidos.append({"url": url, "json": json, "headers": headers})
            return cola.pop(0)
        monkeypatch.setattr(imagenes, "_transporte", {"post": post})
        return pedidos
    return instalar


def _artefacto(contenido=JPG, fin="SUCCESS"):
    return Resp(body={"artifacts": [{"base64": base64.b64encode(contenido).decode(), "finishReason": fin}]})


def test_describir_prioriza_lo_pedido_despues_el_plan_y_si_no_la_categoria():
    plan = {"imagen": "A distributor warehouse at dawn."}
    assert imagenes.describir(plan, ["frenos"], "brake pads on a counter").startswith("brake pads on a counter. ")
    assert imagenes.describir(plan, ["frenos"]).startswith("A distributor warehouse at dawn. ")
    assert imagenes.describir(None, ["frenos"]).startswith("close-up of new brake discs")
    assert imagenes.describir(None, ["otra"]).startswith("the counter of a modern auto parts store")
    assert "No text" in imagenes.describir(None, [])


def test_generar_con_flux_dev(nvidia):
    pedidos = nvidia(_artefacto(JPG))
    contenido, mime = imagenes.generar("una escena")
    assert contenido == JPG and mime == "image/jpeg"
    p = pedidos[0]
    assert p["url"] == "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
    assert p["headers"]["Authorization"] == "Bearer nvapi-test"
    assert p["json"] == {"prompt": "una escena", "width": 1344, "height": 768, "seed": 0,
                         "mode": "base", "cfg_scale": 3.5, "steps": 30}


def test_el_modelo_es_fijo_y_configurable_aparte_de_la_redaccion(nvidia, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "paga")
    monkeypatch.setenv("NVIDIA_IMAGE_MODEL", "black-forest-labs/flux.1-schnell")
    pedidos = nvidia(Resp(body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]}))
    assert imagenes.generar("x") == (PNG, "image/png")
    assert pedidos[0]["url"].endswith("/flux.1-schnell") and pedidos[0]["json"]["steps"] == 4
    assert "cfg_scale" not in pedidos[0]["json"]


def test_si_no_acepta_el_tamano_apaisado_reintenta_cuadrada(nvidia):
    pedidos = nvidia(Resp(422, {"detail": "invalid width"}), _artefacto())
    imagenes.generar("x")
    assert (pedidos[1]["json"]["width"], pedidos[1]["json"]["height"]) == (1024, 1024)


@pytest.mark.parametrize("resp,texto", [
    (Resp(401), "NVIDIA_API_KEY"), (Resp(404), "NVIDIA_IMAGE_MODEL"), (Resp(429), "limitando"),
    (Resp(500, {"x": 1}), "500"), (_artefacto(fin="CONTENT_FILTERED"), "CONTENT_FILTERED"), (Resp(body={}), "sin imagen"),
])
def test_errores_con_mensaje_claro(nvidia, resp, texto):
    nvidia(resp, resp)   # un 5xx se reintenta una vez con el modelo rápido
    with pytest.raises(imagenes.ErrorImagen, match=texto):
        imagenes.generar("x")


def test_sin_key_no_se_llama(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert not imagenes.configurado() and not imagenes.automaticas()
    with pytest.raises(imagenes.ErrorImagen, match="NVIDIA_API_KEY"):
        imagenes.generar("x")


# ── Historial ─────────────────────────────────────────────────────────────────


@pytest.fixture
def base():
    return mongomock.MongoClient().db


@pytest.fixture
def nota(base):
    return str(base.notas_fase2.insert_one({
        "contenido": "# Frenos en el mostrador\n\nTexto.", "estado": "aprobada", "categorias": ["frenos"],
        "plan": {"imagen": "Brake pads on a workbench."},
    }).inserted_id)


def test_generar_imagen_la_guarda_y_regenerar_borra_la_anterior(base, nota, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    prompts = []
    monkeypatch.setattr(imagenes, "generar_con_modelo", lambda p: prompts.append(p) or (JPG, "image/jpeg", imagenes.modelo()))
    item = historial.generar_imagen("notas_fase2", nota, base=base)
    assert item and prompts[0].startswith("Brake pads on a workbench.")
    imagen = base.notas_fase2.find_one({"_id": ObjectId(nota)})["imagen"]
    primera = imagen["generada"]["id"]
    assert imagen["url"] == "" and imagen["alt"] == "Frenos en el mostrador"
    assert imagenes.leer(primera, base=base) == (JPG, "image/jpeg")

    historial.generar_imagen("notas_fase2", nota, descripcion="a tire shop", base=base)
    assert prompts[1].startswith("a tire shop.")
    assert imagenes.leer(primera, base=base) is None and base.imagenes.count_documents({}) == 1


def test_error_de_nvidia_llega_como_error_del_historial(base, nota, monkeypatch):
    def falla(p):
        raise imagenes.ErrorImagen("NVIDIA caído")
    monkeypatch.setattr(imagenes, "generar_con_modelo", falla)
    with pytest.raises(historial.ErrorHistorial, match="NVIDIA caído"):
        historial.generar_imagen("notas_fase2", nota, base=base)


def test_quitar_o_reemplazar_por_url_borra_la_generada(base, nota, monkeypatch):
    monkeypatch.setattr(imagenes, "generar_con_modelo", lambda p: (JPG, "image/jpeg", imagenes.modelo()))
    historial.generar_imagen("notas_fase2", nota, base=base)
    historial.cambiar_imagen("notas_fase2", nota, "https://cdn.example.com/a.jpg", base=base)
    assert base.imagenes.count_documents({}) == 0


def test_la_vista_previa_muestra_la_generada_desde_el_servidor(base, nota, monkeypatch):
    monkeypatch.setattr(imagenes, "generar_con_modelo", lambda p: (JPG, "image/jpeg", imagenes.modelo()))
    historial.generar_imagen("notas_fase2", nota, base=base)
    imagen_id = base.notas_fase2.find_one({"_id": ObjectId(nota)})["imagen"]["generada"]["id"]
    previa = historial.vista_previa("notas_fase2", nota, base=base)
    assert previa["imagen"]["url"] == f"/api/imagenes/{imagen_id}"


@pytest.fixture
def hubspot_falso(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "1")
    enviados = []
    monkeypatch.setattr(hubspot, "enviar", lambda doc, publicar=False: enviados.append(doc) or
                        {"id": "9", "url": "https://blog/x", "estado": "DRAFT", "slug": "x"})
    return enviados


def test_al_enviar_a_hubspot_se_sube_la_imagen_generada(base, nota, monkeypatch, hubspot_falso):
    monkeypatch.setattr(imagenes, "generar_con_modelo", lambda p: (JPG, "image/jpeg", imagenes.modelo()))
    historial.generar_imagen("notas_fase2", nota, base=base)
    subidas = []
    monkeypatch.setattr(hubspot, "subir_imagen", lambda c, m, n: subidas.append((c, m, n)) or "https://hs/img.jpg")
    item = historial.enviar_a_hubspot("notas_fase2", nota, publicar=False, base=base)
    assert subidas[0][0] == JPG and subidas[0][2].endswith(".jpg") and "aviso" not in item
    assert hubspot_falso[0]["imagen"]["url"] == "https://hs/img.jpg"
    assert base.notas_fase2.find_one({"_id": ObjectId(nota)})["imagen"]["url"] == "https://hs/img.jpg"
    # Ya subida: la segunda vez no se sube de nuevo.
    historial.enviar_a_hubspot("notas_fase2", nota, publicar=False, base=base)
    assert len(subidas) == 1


def test_si_no_se_puede_subir_la_imagen_se_publica_igual_con_aviso(base, nota, monkeypatch, hubspot_falso):
    monkeypatch.setattr(imagenes, "generar_con_modelo", lambda p: (JPG, "image/jpeg", imagenes.modelo()))
    historial.generar_imagen("notas_fase2", nota, base=base)

    def sin_scope(c, m, n):
        raise hubspot.ErrorHubSpot("la app privada necesita el scope 'files'")
    monkeypatch.setattr(hubspot, "subir_imagen", sin_scope)
    item = historial.enviar_a_hubspot("notas_fase2", nota, publicar=False, base=base)
    assert "scope 'files'" in item["aviso"] and len(hubspot_falso) == 1


def test_subir_imagen_a_hubspot(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "1")
    llamadas = []
    monkeypatch.setitem(hubspot._transporte, "subir", lambda url, **kw: llamadas.append((url, kw)) or
                        Resp(body={"url": "https://f.hubspotusercontent.com/a.jpg"}))
    assert hubspot.subir_imagen(JPG, "image/jpeg", "nota.jpg") == "https://f.hubspotusercontent.com/a.jpg"
    url, kw = llamadas[0]
    assert url == hubspot.API_ARCHIVOS and kw["files"]["file"] == ("nota.jpg", JPG, "image/jpeg")
    assert json.loads(kw["data"]["options"])["access"] == "PUBLIC_INDEXABLE"
    monkeypatch.setitem(hubspot._transporte, "subir", lambda url, **kw: Resp(403))
    with pytest.raises(hubspot.ErrorHubSpot, match="scope 'files'"):
        hubspot.subir_imagen(JPG, "image/jpeg", "nota.jpg")


# ── API y generación ──────────────────────────────────────────────────────────


def test_endpoint_de_imagen(api, base, monkeypatch):
    from afterdrive import db as db_module
    monkeypatch.setattr(db_module, "db", base)
    flask_api, _ = api
    imagen_id = imagenes.guardar(PNG, "image/png", "p", base=base)
    anonimo = flask_api.app.test_client()
    assert anonimo.get(f"/api/imagenes/{imagen_id}").status_code == 401
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    r = c.get(f"/api/imagenes/{imagen_id}")
    assert r.status_code == 200 and r.data == PNG and r.mimetype == "image/png"
    assert c.get("/api/imagenes/nada").status_code == 404


def test_la_nota_nueva_trae_su_imagen_y_un_fallo_no_la_frena(monkeypatch):
    from afterdrive import calibracion
    from afterdrive.generacion import contexto_noticias
    from afterdrive.generacion import generar_nota_fase2 as g
    from afterdrive.ia import llm
    from tests.test_generacion import NOTA, PLAN, ColFake

    monkeypatch.setenv("IMAGENES_AUTOMATICAS", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    col = ColFake()
    monkeypatch.setattr(g, "col_notas_fase2", col)
    monkeypatch.setattr(g, "col_clientes", ColFake())
    monkeypatch.setattr(g, "_calibracion", lambda persona: calibracion.Calibracion())
    monkeypatch.setattr(g, "get_ejemplos_por_tags", lambda *a, **k: [])
    monkeypatch.setattr(contexto_noticias, "seleccionar", lambda consulta, limite=5: [])
    monkeypatch.setattr(contexto_noticias, "marcar_usadas", lambda ns: None)
    monkeypatch.setattr(llm, "completar", lambda s, u, **k: PLAN if k.get("tarea") == "planificacion" else NOTA)
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [None])
    from afterdrive.ia import lm_studio
    monkeypatch.setattr(lm_studio, "evaluar_lineamientos", lambda t: {"lineamientos": {}})
    monkeypatch.setattr(imagenes, "generar_con_modelo", lambda p: (JPG, "image/jpeg", imagenes.modelo()))
    monkeypatch.setattr(imagenes, "guardar", lambda c, m, p, base=None, nombre_modelo=None: "a" * 24)

    assert g.generar_nota(["frenos"])["success"]
    assert col.docs[0]["imagen"]["generada"]["id"] == "a" * 24
    assert col.docs[0]["imagen"]["alt"] == "El catálogo digital llega al mostrador"

    def falla(p):
        raise imagenes.ErrorImagen("NVIDIA caído")
    monkeypatch.setattr(imagenes, "generar_con_modelo", falla)
    assert g.generar_nota(["frenos"])["success"] and "imagen" not in col.docs[1]
    assert col.docs[1]["imagen_error"] == "NVIDIA caído"


def test_el_plan_propone_la_escena_de_la_imagen(monkeypatch):
    from afterdrive.generacion import plan
    from afterdrive.ia import llm
    monkeypatch.setattr(llm, "completar", lambda *a, **k: (
        '{"titulo": "T", "secciones": [{"titulo": "a"}, {"titulo": "b"}], "imagen": "A  parts counter."}'))
    assert plan.planificar([], "x", [])["imagen"] == "A parts counter."


def test_si_nvidia_deja_la_imagen_en_proceso_se_espera(nvidia, monkeypatch):
    # 202 + NVCF-REQID: hay que consultar el estado hasta que termine.
    nvidia(Resp(202, headers={"NVCF-REQID": "req-1"}))
    consultas = []
    respuestas = [Resp(202, headers={"NVCF-REQID": "req-1"}), _artefacto(PNG)]
    monkeypatch.setitem(imagenes._transporte, "get", lambda url, **kw: consultas.append(url) or respuestas.pop(0))
    monkeypatch.setattr(imagenes, "_dormir", lambda s: None)
    assert imagenes.generar("x") == (PNG, "image/png")
    assert consultas == ["https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/req-1"] * 2


def test_202_sin_id_es_un_error_claro(nvidia):
    nvidia(Resp(202))
    with pytest.raises(imagenes.ErrorImagen, match="NVCF-REQID"):
        imagenes.generar("x")


def test_regenerar_limpia_el_error_anterior(base, nota, monkeypatch):
    base.notas_fase2.update_one({"_id": ObjectId(nota)}, {"$set": {"imagen_error": "NVIDIA caído"}})
    monkeypatch.setattr(imagenes, "generar_con_modelo", lambda p: (JPG, "image/jpeg", imagenes.modelo()))
    historial.generar_imagen("notas_fase2", nota, base=base)
    assert "imagen_error" not in base.notas_fase2.find_one({"_id": ObjectId(nota)})


def test_el_script_de_imagen_sale_con_error_si_falla(monkeypatch):
    from afterdrive import imagen_nota

    def falla(*a, **k):
        raise historial.ErrorHistorial("NVIDIA está limitando las llamadas (429)")

    monkeypatch.setattr(historial, "generar_imagen", falla)
    assert imagen_nota.main(["notas_fase2", "65a1b2c3d4e5f60718293a4b"]) == 1
    monkeypatch.setattr(historial, "generar_imagen", lambda *a, **k: None)
    assert imagen_nota.main(["notas_fase2", "65a1b2c3d4e5f60718293a4b"]) == 1
    monkeypatch.setattr(historial, "generar_imagen", lambda *a, **k: {"id": "x"})
    assert imagen_nota.main(["notas_fase2", "65a1b2c3d4e5f60718293a4b", "a tire shop"]) == 0


def test_no_pide_nvcf_poll_seconds(nvidia):
    """Con ese header el gateway de NVIDIA respondía 504 a los 20 s en vez de 202."""
    pedidos = nvidia(_artefacto())
    imagenes.generar("a parts store")
    assert "NVCF-POLL-SECONDS" not in pedidos[0]["headers"]


def test_si_flux_dev_esta_saturado_prueba_con_schnell(nvidia):
    pedidos = nvidia(Resp(504, body={}), _artefacto(PNG))
    contenido, mime, usado = imagenes.generar_con_modelo("x")
    assert contenido == PNG and usado == imagenes.MODELO_RAPIDO
    assert pedidos[1]["url"].endswith("flux.1-schnell") and pedidos[1]["json"]["steps"] == 4


def test_si_tambien_schnell_falla_el_error_es_claro(nvidia):
    nvidia(Resp(504, body={}), Resp(503, body={}))
    with pytest.raises(imagenes.ErrorImagen, match="saturado"):
        imagenes.generar("x")


def test_timeout_de_nvidia_da_un_mensaje_claro(monkeypatch):
    import requests
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")

    def post(url, **kw):
        raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=180)")   # dev y schnell

    monkeypatch.setattr(imagenes, "_transporte", {"post": post})
    with pytest.raises(imagenes.ErrorImagen, match="tardó demasiado"):
        imagenes.generar("a parts store")
