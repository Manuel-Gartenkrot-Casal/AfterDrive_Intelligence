"""Tests de las versiones de una nota en los otros idiomas del blog (traducciones.py y hubspot.enviar_traduccion)."""

import mongomock
import pytest
from bson import ObjectId

from afterdrive import db as db_module
from afterdrive import hubspot, traducciones
from afterdrive.ia import llm

NOTA = """# Frenos: la demanda sube en Argentina

## Qué pasó
El mercado de **pastillas de freno** creció un 12 % según [la cámara](https://camara.com/nota).

## Qué significa para tu negocio
- Reponé stock de alta rotación.

*La demanda de frenos crece y el distribuidor necesita stock.*"""

NOTA_PT = """# Freios: a demanda cresce na Argentina

## O que aconteceu
O mercado de **pastilhas de freio** cresceu 12 % segundo [a câmara](https://camara.com/nota).

## O que isso significa para o seu negócio
- Reponha estoque de alto giro.

*A demanda por freios cresce e o distribuidor precisa de estoque.*"""


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


# ── Traducir ──────────────────────────────────────────────────────────────────


def test_idiomas_destino_son_los_otros_dos_blogs():
    assert traducciones.idiomas_destino({"regiones": ["argentina"]}) == ["pt", "en"]
    assert traducciones.idiomas_destino({"regiones": ["brasil"]}) == ["es", "en"]
    assert traducciones.idiomas_destino({"regiones": ["asia"]}) == ["es", "pt"]
    assert traducciones.idiomas_destino({"regiones": ["china"]}) == []


def test_traducir_limpia_la_respuesta_y_quita_enlaces_agregados(monkeypatch):
    pedidos = []
    respuesta = ("Aquí está la traducción:\n```markdown\n"
                 + NOTA_PT.replace("Reponha estoque", "Reponha [estoque](https://inventado.com) estoque") + "\n```")
    monkeypatch.setattr(llm, "completar", lambda system, user, **kw: pedidos.append((system, user, kw)) or respuesta)
    texto = traducciones.traducir(NOTA, "es", "pt")
    assert texto.startswith("# Freios") and "inventado.com" not in texto and "](https://camara.com/nota)" in texto
    system, user, kw = pedidos[0]
    assert user == NOTA and kw["tarea"] == "traduccion"
    assert "portugués de Brasil" in system and '"Qué significa para tu negocio" -> "O que isso significa para o seu negócio"' in system


@pytest.mark.parametrize("respuesta, motivo", [("Sin título, solo texto " * 20, "título"), ("# Corta", "cortada")])
def test_una_traduccion_inservible_da_error(monkeypatch, respuesta, motivo):
    monkeypatch.setattr(llm, "completar", lambda *a, **k: respuesta)
    with pytest.raises(traducciones.ErrorTraduccion, match=motivo):
        traducciones.traducir(NOTA, "es", "en")


# ── Subir ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def base():
    return mongomock.MongoClient().db


@pytest.fixture
def nota(base):
    return str(base.notas_fase2.insert_one({
        "contenido": NOTA, "estado": "aprobada", "regiones": ["argentina"], "categorias": ["autopartes"],
        "hubspot": {"id": "111", "url": "https://blog/es/x", "estado": "DRAFT"},
        "costo": {"total_usd": 0.2, "por_tarea": {"redaccion": 0.2}, "llamadas": 4},
    }).inserted_id)


@pytest.fixture
def falsos(monkeypatch):
    traducidas, enviadas = [], []

    def traducir(contenido, origen, destino):
        traducidas.append(destino)
        return f"# Versión {destino}\n\nTexto."

    def enviar(doc, cod, texto, primario, previo=None):
        enviadas.append({"cod": cod, "texto": texto, "primario": primario, "previo": previo})
        return {"id": f"post-{cod}", "url": f"https://blog/{cod}/x", "estado": "DRAFT", "slug": "x", "vinculada": True,
                "aviso": ""}
    monkeypatch.setattr(traducciones, "traducir", traducir)
    monkeypatch.setattr(hubspot, "enviar_traduccion", enviar)
    return traducidas, enviadas


def test_subir_traduce_y_guarda_cada_version(base, nota, falsos):
    traducidas, enviadas = falsos
    r = traducciones.subir("notas_fase2", nota, base=base)
    assert r["subidas"] == ["pt", "en"] and not r["errores"]
    assert [e["primario"] for e in enviadas] == ["111", "111"]
    doc = base.notas_fase2.find_one({"_id": ObjectId(nota)})
    assert doc["traducciones"]["pt"]["contenido"] == "# Versión pt\n\nTexto."
    assert doc["traducciones"]["pt"]["huella"] == traducciones.huella(NOTA)
    assert doc["hubspot_traducciones"]["en"]["id"] == "post-en" and doc["hubspot_traducciones"]["en"]["enviado_en"]


def test_reenviar_sin_editar_no_vuelve_a_traducir_y_actualiza_el_borrador(base, nota, falsos):
    traducidas, enviadas = falsos
    traducciones.subir("notas_fase2", nota, base=base)
    traducciones.subir("notas_fase2", nota, base=base)
    assert traducidas == ["pt", "en"]                                   # una sola vez
    assert enviadas[2]["previo"]["id"] == "post-pt"                     # el segundo envío actualiza
    base.notas_fase2.update_one({"_id": ObjectId(nota)}, {"$set": {"contenido": NOTA + "\nEditada."}})
    traducciones.subir("notas_fase2", nota, base=base)
    assert traducidas == ["pt", "en", "pt", "en"]                       # editada: se traduce de nuevo


def test_si_un_idioma_falla_el_otro_se_sube_igual(base, nota, falsos, monkeypatch):
    def traducir(contenido, origen, destino):
        if destino == "pt":
            raise llm.ErrorLLM("Bedrock caído")
        return "# Version en\n\nText."
    monkeypatch.setattr(traducciones, "traducir", traducir)
    r = traducciones.subir("notas_fase2", nota, base=base)
    assert r["subidas"] == ["en"] and "portugués: Bedrock caído" in r["errores"][0]
    doc = base.notas_fase2.find_one({"_id": ObjectId(nota)})
    assert doc["hubspot_traducciones"]["pt"]["error"] == "Bedrock caído"


def test_si_hubspot_creo_el_post_a_medias_se_guarda_su_id(base, nota, falsos, monkeypatch):
    def enviar(doc, cod, texto, primario, previo=None):
        raise hubspot.ErrorHubSpotParcial("HubSpot respondió 500", f"post-{cod}")
    monkeypatch.setattr(hubspot, "enviar_traduccion", enviar)
    r = traducciones.subir("notas_fase2", nota, base=base)
    assert len(r["errores"]) == 2
    assert base.notas_fase2.find_one({"_id": ObjectId(nota)})["hubspot_traducciones"]["pt"]["id"] == "post-pt"


def test_sin_subir_la_original_no_hay_traducciones(base, falsos):
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "regiones": ["argentina"]}).inserted_id)
    with pytest.raises(traducciones.ErrorTraduccion, match="subila primero"):
        traducciones.subir("notas_fase2", oid, base=base)


def test_main_sale_con_error_si_falta_un_idioma(base, nota, falsos, monkeypatch, capsys):
    monkeypatch.setattr(db_module, "db", base)
    assert traducciones.main(["notas_fase2", nota]) == 0
    assert "[OK] Versiones subidas como borrador: portugués, inglés." in capsys.readouterr().out
    monkeypatch.setattr(traducciones, "traducir", lambda *a: (_ for _ in ()).throw(traducciones.ErrorTraduccion("cortada")))
    base.notas_fase2.update_one({"_id": ObjectId(nota)}, {"$set": {"contenido": NOTA + "\nOtra."}})
    assert traducciones.main(["notas_fase2", nota]) == 1


# ── HubSpot ───────────────────────────────────────────────────────────────────


@pytest.fixture
def hs(monkeypatch):
    """HubSpot falso: respuestas por (método, final de la URL)."""
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.delenv("HUBSPOT_BLOG_PRUEBAS", raising=False)
    monkeypatch.delenv("HUBSPOT_LENGUAJES", raising=False)
    monkeypatch.delenv("HUBSPOT_IMAGEN_DEFAULT", raising=False)
    llamadas, respuestas = [], {}

    def fake(metodo):
        def f(url, json=None, headers=None, timeout=None, params=None):
            llamadas.append({"metodo": metodo, "url": url, "json": json})
            for (m, fin), resp in respuestas.items():
                if m == metodo and url.endswith(fin):
                    return resp
            return Resp(200, {"id": "nuevo", "url": "https://blog/pt/frenos", "state": "DRAFT"})
        return f
    monkeypatch.setattr(hubspot, "_transporte", {"post": fake("post"), "patch": fake("patch"), "get": fake("get")})
    return llamadas, respuestas


DOC = {"_id": ObjectId("65a1b2c3d4e5f60718293a4b"), "regiones": ["argentina"], "categorias": ["autopartes"],
       "imagen": {"url": "https://n.com/f.jpg", "hubspot_url": "https://hs/f.jpg"}}


def test_crea_la_variacion_de_idioma_y_le_pone_el_texto_traducido(hs):
    llamadas, respuestas = hs
    respuestas[("post", "/create-language-variation")] = Resp(200, {"id": "222"})
    r = hubspot.enviar_traduccion(DOC, "pt", NOTA_PT, "111")
    assert r["id"] == "222" and r["vinculada"] is True and not r["aviso"]
    variacion, contenido = llamadas
    assert variacion["json"] == {"id": "111", "language": "pt-br", "primaryLanguage": "es"}
    c = contenido["json"]
    assert contenido["metodo"] == "patch" and contenido["url"].endswith("/posts/222")
    assert c["name"] == "Freios: a demanda cresce na Argentina" and c["state"] == "DRAFT"
    assert c["blogAuthorId"] == hubspot.AUTOR_POR_DEFECTO["pt"] and c["tagIds"] == [hubspot.ETIQUETAS["autopartes"][1]]
    assert c["slug"].endswith("293a4b-pt") and c["featuredImage"] == "https://hs/f.jpg"


def test_si_no_hay_variacion_crea_un_borrador_en_el_blog_del_idioma_y_lo_vincula(hs):
    llamadas, respuestas = hs
    respuestas[("post", "/create-language-variation")] = Resp(400, {"message": "not multi-language"})
    r = hubspot.enviar_traduccion(DOC, "en", NOTA_PT, "111")
    assert r["vinculada"] is True
    _, creado, vinculo = llamadas
    assert creado["json"]["contentGroupId"] == hubspot.BLOGS["en"][0]
    assert vinculo["url"].endswith("/attach-to-lang-group")
    assert vinculo["json"] == {"id": "nuevo", "language": "en", "primaryId": "111", "primaryLanguage": "es"}


def test_si_tampoco_se_puede_vincular_queda_suelta_con_aviso(hs):
    _, respuestas = hs
    respuestas[("post", "/create-language-variation")] = Resp(400, {"message": "x"})
    respuestas[("post", "/attach-to-lang-group")] = Resp(400, {"message": "y"})
    r = hubspot.enviar_traduccion(DOC, "en", NOTA_PT, "111")
    assert r["vinculada"] is False and "borrador suelto" in r["aviso"] and r["id"] == "nuevo"


def test_si_el_texto_no_se_pudo_poner_en_la_variacion_devuelve_su_id(hs):
    _, respuestas = hs
    respuestas[("post", "/create-language-variation")] = Resp(200, {"id": "222"})
    respuestas[("patch", "/posts/222")] = Resp(500, {"message": "boom"})
    with pytest.raises(hubspot.ErrorHubSpotParcial) as e:
        hubspot.enviar_traduccion(DOC, "pt", NOTA_PT, "111")
    assert e.value.post_id == "222"


def test_reenviar_actualiza_el_borrador_sin_pisar_autor_ni_etiquetas(hs):
    llamadas, _ = hs
    r = hubspot.enviar_traduccion(DOC, "pt", NOTA_PT, "111", previo={"id": "222", "vinculada": True})
    assert len(llamadas) == 1 and llamadas[0]["metodo"] == "patch" and llamadas[0]["url"].endswith("/posts/222")
    assert "blogAuthorId" not in llamadas[0]["json"] and "tagIds" not in llamadas[0]["json"] and r["vinculada"]


def test_con_blog_de_pruebas_va_todo_ahi_sin_vincular(hs, monkeypatch):
    llamadas, _ = hs
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "999")
    r = hubspot.enviar_traduccion(DOC, "pt", NOTA_PT, "111")
    assert len(llamadas) == 1 and llamadas[0]["json"]["contentGroupId"] == "999" and r["vinculada"] is False


def test_codigos_de_idioma_configurables(monkeypatch):
    monkeypatch.setenv("HUBSPOT_LENGUAJES", "es=es-ar, pt=pt-BR")
    assert (hubspot.lenguaje("es"), hubspot.lenguaje("pt"), hubspot.lenguaje("en")) == ("es-ar", "pt-br", "en")


# ── Endpoints ─────────────────────────────────────────────────────────────────


def test_al_subir_a_hubspot_se_encolan_las_traducciones(api, monkeypatch, base):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat")
    monkeypatch.setenv("HUBSPOT_BLOG_PRUEBAS", "1")
    monkeypatch.setattr(hubspot, "enviar", lambda doc, publicar=False: {"id": "9", "url": "https://b/x", "estado": "DRAFT",
                                                                        "slug": "x"})
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "estado": "aprobada", "regiones": ["brasil"]}).inserted_id)
    r = c.post("/api/hubspot/enviar", json={"coleccion": "notas_fase2", "id": oid})
    assert r.status_code == 200 and r.json["traducciones"]["idiomas"] == ["es", "en"]
    corrida = base.corridas.find_one()
    assert corrida["params"] == {"modulo": "afterdrive.traducciones", "argv": ["notas_fase2", oid]}
    assert corrida["etiqueta"] == "Traducir al español y inglés y subir a HubSpot"
    # Reintento a mano: misma corrida (todavía pendiente), no se duplica.
    r = c.post("/api/hubspot/traducciones", json={"coleccion": "notas_fase2", "id": oid})
    assert r.status_code == 202 and base.corridas.count_documents({}) == 1
    monkeypatch.setenv("HUBSPOT_TRADUCCIONES", "0")
    assert c.post("/api/hubspot/traducciones", json={"coleccion": "notas_fase2", "id": oid}).status_code == 400


def test_sin_subir_la_original_el_reintento_explica_por_que(api, monkeypatch, base):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "regiones": ["argentina"]}).inserted_id)
    r = c.post("/api/hubspot/traducciones", json={"coleccion": "notas_fase2", "id": oid})
    assert r.status_code == 400 and "subila primero" in r.json["error"]
    assert c.post("/api/hubspot/traducciones", json={"coleccion": "articulos", "id": oid}).status_code == 400


def test_editar_una_traduccion_y_quedar_desactualizada(base):
    from afterdrive import historial
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "pt", "estado": "borrador"}).inserted_id)
    texto = "# Título en español\n\n" + "Texto editado a mano. " * 10
    t = historial.editar_traduccion("notas_fase2", oid, "es", texto, base=base)
    assert t["editada"] and traducciones.al_dia(t, NOTA)
    with pytest.raises(historial.ErrorHistorial):
        historial.editar_traduccion("notas_fase2", oid, "pt", texto, base=base)   # pt es el original
    with pytest.raises(historial.ErrorHistorial):
        historial.editar_traduccion("notas_fase2", oid, "es", "sin título " * 20, base=base)
    historial.editar("notas_fase2", oid, NOTA + "\n\nUn párrafo más.", base=base)
    doc = base.notas_fase2.find_one()
    assert not traducciones.al_dia(doc["traducciones"]["es"], doc["contenido"])


def test_retraducir_guarda_sin_subir(base, monkeypatch):
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "pt"}).inserted_id)
    monkeypatch.setattr(traducciones, "traducir", lambda c, o, d: f"# En {d}\n\nTexto.")
    traducciones.retraducir("notas_fase2", oid, "en", base=base)
    t = base.notas_fase2.find_one()["traducciones"]["en"]
    assert t["contenido"].startswith("# En en") and not t["editada"]
    with pytest.raises(traducciones.ErrorTraduccion):
        traducciones.retraducir("notas_fase2", oid, "pt", base=base)


def test_la_nota_del_dashboard_trae_idioma_y_estado_de_traducciones(api, monkeypatch, base):
    flask_api, _ = api
    monkeypatch.setattr(db_module, "db", base)
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    oid = str(base.notas_fase2.insert_one({"contenido": NOTA, "idioma": "pt", "generado_en": "2026-10-26",
        "traducciones": {"es": traducciones.entrada("# ES\n\nx", "otro texto")}}).inserted_id)
    from afterdrive.generacion import generar_nota_fase2 as g
    monkeypatch.setattr(g, "col_notas_fase2", base.notas_fase2)
    nota = c.get(f"/api/fase2/notas/{oid}").get_json()["nota"]
    assert nota["idioma"] == "pt" and nota["traducciones"]["es"]["al_dia"] is False
    r = c.post("/api/historial/retraducir", json={"coleccion": "notas_fase2", "id": oid, "idioma": "es"})
    assert r.status_code == 202
    assert base.corridas.find_one()["params"]["argv"] == ["notas_fase2", oid, "--traducir", "es"]
    assert c.post("/api/historial/retraducir", json={"coleccion": "x", "id": oid, "idioma": "es"}).status_code == 400
