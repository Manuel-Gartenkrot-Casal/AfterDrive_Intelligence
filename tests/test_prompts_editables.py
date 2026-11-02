"""Recorrido de aprobación de las piezas del prompt: Borrador → Revisión → Activa → Archivada."""

import mongomock
import pytest

from afterdrive import prompts_editables as pe
from afterdrive.ia import redaccion

SEO = "## SEO\n- Título corto.\n- Palabra clave en el primer párrafo."


@pytest.fixture
def base():
    return mongomock.MongoClient().db


def _hasta_revision(clave, contenido, base):
    pe.guardar_borrador(clave, contenido, "porque sí", base=base)
    return pe.enviar(clave, base=base)


def test_recorrido_completo_y_archivo_de_la_anterior(base):
    assert pe.detalle("seo", base=base)["activo"]["version"] == 0      # sin ediciones: el original
    b = pe.guardar_borrador("seo", SEO, "  más   corto ", base=base)
    assert (b["estado"], b["version"], b["motivo"]) == ("borrador", 1, "más corto")
    assert pe.enviar("seo", base=base)["estado"] == "en_revision"
    activo = pe.aprobar("seo", 1, base=base)
    assert activo["contenido"] == SEO and activo["aprobado"]
    assert pe.activos(base=base) == {"seo": SEO}

    _hasta_revision("seo", SEO + "\n- Otra regla.", base)
    pe.aprobar("seo", 2, base=base)
    d = pe.detalle("seo", base=base)
    assert d["activo"]["version"] == 2 and d["pendiente"] is None
    assert [h["version"] for h in d["historial"]] == [1, 0] and d["historial"][0]["archivado"]
    assert base.prompts.count_documents({"clave": "seo", "estado": "activo"}) == 1


def test_editar_lo_que_esta_en_revision_lo_vuelve_a_borrador(base):
    _hasta_revision("seo", SEO, base)
    b = pe.guardar_borrador("seo", SEO + "\n- Cambio.", base=base)
    assert b["estado"] == "borrador" and b["version"] == 1 and "enviado" not in b
    with pytest.raises(pe.ErrorPrompt, match="enviarla a revisión"):
        pe.aprobar("seo", 1, base=base)


def test_no_se_aprueba_una_version_distinta_de_la_que_se_vio(base):
    _hasta_revision("seo", SEO, base)
    with pytest.raises(pe.ErrorPrompt, match="cambió"):
        pe.aprobar("seo", 7, base=base)
    with pytest.raises(pe.ErrorPrompt, match="versión"):
        pe.aprobar("seo", None, base=base)


def test_rechazar_vuelve_a_borrador_con_el_motivo(base):
    _hasta_revision("seo", SEO, base)
    r = pe.rechazar("seo", "muy corto", base=base)
    assert r["estado"] == "borrador" and r["rechazo"]["motivo"] == "muy corto"
    assert pe.enviar("seo", base=base).get("rechazo") is None
    with pytest.raises(pe.ErrorPrompt):
        pe.rechazar("otra", base=base)


def test_restaurar_pasa_por_aprobacion(base):
    _hasta_revision("seo", SEO, base)
    pe.aprobar("seo", 1, base=base)
    r = pe.restaurar("seo", 0, base=base)
    assert r["estado"] == "en_revision" and r["restaurado_de"] == 0 and r["contenido"] == redaccion.PIEZAS["seo"]
    assert pe.activos(base=base) == {"seo": SEO}                    # hasta aprobarla, sigue la activa
    pe.aprobar("seo", r["version"], base=base)
    assert pe.detalle("seo", base=base)["activo"]["contenido"] == redaccion.PIEZAS["seo"]
    assert pe.restaurar("seo", 1, base=base)["contenido"] == SEO   # la versión 1 quedó archivada
    with pytest.raises(pe.ErrorPrompt, match="archivada"):
        pe.restaurar("seo", 99, base=base)
    with pytest.raises(pe.ErrorPrompt, match="no está archivada"):
        pe.restaurar("seo", r["version"], base=base)              # es la activa
    with pytest.raises(pe.ErrorPrompt, match="igual a la activa"):
        pe.restaurar("seo", 0, base=base)                         # el original, que es lo activo


def test_la_validacion_bloquea_enviar_y_aprobar(base):
    pe.guardar_borrador("formato", "## Formato\n- Markdown.", base=base)
    with pytest.raises(pe.ErrorPrompt, match="extension"):
        pe.enviar("formato", base=base)
    pe.guardar_borrador("seo", redaccion.PIEZAS["seo"], base=base)
    with pytest.raises(pe.ErrorPrompt, match="igual"):
        pe.enviar("seo", base=base)


@pytest.mark.parametrize("clave, texto, error", [
    ("seo", "Sin título.", "empezar con un título"),
    ("seo", "## SEO", "no tiene reglas"),
    ("seo", "## SEO\n" + "x" * pe.LARGO_MAX, "largo máximo"),
    ("identidad", "## Quién\nEscribís.", "sin títulos"),
    ("formato", "## Formato\n- Markdown.", "{extension}"),
    ("persona_comercial", "## Tu tarea\nT\n## Estructura\n1. a\n2. b\n## Estilo\nE", "Falta el rol"),
    ("persona_comercial", "Sos X.\n## Tu tarea\nT\n## Estructura\n1. a\n2. b", "## Estilo"),
    ("persona_comercial", "Sos X.\n## Tu tarea\nT\n## Estructura\nsin números\n## Estilo\nE", "lista numerada"),
    ("persona_comercial", "Sos X.\n## Tu tarea\nT\n## Estructura\n1. a\n## Estilo\nE", "al menos 2"),
])
def test_validar(clave, texto, error):
    assert any(error in e for e in pe.validar(clave, texto)["errores"])


def test_los_textos_originales_son_validos():
    for clave in pe.CLAVES:
        assert pe.validar(clave, redaccion.PIEZAS[clave]) == {"errores": [], "avisos": []}, clave
    assert pe.validar("seo", SEO + " {extension}")["avisos"]


def test_clave_desconocida_y_borrador_vacio(base):
    with pytest.raises(pe.ErrorPrompt, match="desconocida"):
        pe.guardar_borrador("inventada", "x", base=base)
    with pytest.raises(pe.ErrorPrompt, match="vacío"):
        pe.guardar_borrador("seo", "  ", base=base)
    with pytest.raises(pe.ErrorPrompt, match="borrador"):
        pe.descartar_borrador("seo", base=base)


def test_listar(base):
    _hasta_revision("seo", SEO, base)
    piezas = {p["clave"]: p for p in pe.listar(base=base)}
    assert list(piezas) == pe.CLAVES and len(pe.CLAVES) == 13
    assert piezas["seo"]["pendiente"] == {"estado": "en_revision", "version": 1}
    assert piezas["persona_comercial"]["titulo"] == "Comercial" and piezas["oficio"]["pendiente"] is None


# ── Endpoints ────────────────────────────────────────────────────────────────


@pytest.fixture
def client(api, prompts_en_memoria):
    flask_api, _ = api
    c = flask_api.app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = "admin"
    return c


def test_endpoints_del_recorrido(client):
    r = client.get("/api/prompts")
    assert r.status_code == 200 and len(r.json["piezas"]) == 13
    r = client.post("/api/prompts/seo/borrador", json={"contenido": "Sin título", "motivo": "m"})
    assert r.status_code == 200 and r.json["errores"]                 # se guarda, pero avisa
    assert client.post("/api/prompts/seo/enviar").status_code == 400
    client.post("/api/prompts/seo/borrador", json={"contenido": SEO})
    assert client.post("/api/prompts/seo/validar", json={"contenido": SEO}).json["errores"] == []
    assert client.post("/api/prompts/seo/enviar").json["pendiente"]["estado"] == "en_revision"
    r = client.post("/api/prompts/seo/aprobar", json={"version": 1})
    assert r.status_code == 200 and r.json["activo"]["contenido"] == SEO
    assert "Palabra clave en el primer párrafo" in client.post("/api/prompts/vista-previa", json={}).json["prompt"]
    assert client.get("/api/prompts/seo").json["historial"][0]["version"] == 0
    assert client.post("/api/prompts/seo/restaurar", json={"version": 0}).json["pendiente"]["restaurado_de"] == 0
    assert client.post("/api/prompts/seo/rechazar", json={"motivo": "no"}).json["pendiente"]["estado"] == "borrador"
    assert client.delete("/api/prompts/seo/borrador").status_code == 200
    assert client.get("/api/prompts/nada").status_code == 400


def test_vista_previa_con_un_borrador_sin_guardar(client):
    persona = "Sos ROL-BORRADOR.\n\n## Tu tarea\nT\n\n## Estructura\n1. Uno\n2. Dos\n\n## Estilo\nE"
    r = client.post("/api/prompts/vista-previa", json={"clave": "persona_ejecutivo", "contenido": persona, "largo": "corto"})
    assert r.json["persona"] == "ejecutivo" and r.json["prompt"].startswith("Sos ROL-BORRADOR.")
    assert redaccion.LARGOS["corto"] in r.json["prompt"]
    assert client.post("/api/prompts/vista-previa", json={"persona": "x"}).status_code == 400
    assert client.post("/api/prompts/vista-previa", json={"clave": "x"}).status_code == 400


def test_sin_login_no_se_puede(api):
    flask_api, _ = api
    assert flask_api.app.test_client().get("/api/prompts").status_code == 401


def test_vista_previa_por_partes_para_verla_como_archivo(client):
    r = client.post("/api/prompts/vista-previa", json={"persona": "comercial"}).json
    partes = r["partes"]
    assert "\n\n".join(p["texto"] for p in partes) == r["prompt"]
    assert [p["clave"] for p in partes] == ["identidad", "audiencia", "persona_comercial", "reglas_datos", "oficio",
                                            "enfoque_alephee", "formato", "seo", "secciones_fijas", "cierre", "salida"]
    automaticas = {p["clave"]: p for p in partes if not p["editable"]}
    assert set(automaticas) == {"secciones_fijas", "cierre"} and automaticas["cierre"]["titulo"] == "Idioma y cierre"
    assert partes[2]["titulo"] == "Comercial" and partes[2]["texto"].startswith("## Tu tarea")


def test_partes_y_prompt_son_el_mismo_texto():
    for compacto in (False, True):
        partes = redaccion.system_prompt_partes("divulgativo", compacto=compacto, directiva="D")
        assert "\n\n".join(t for _, t in partes) == redaccion.system_prompt("divulgativo", compacto=compacto, directiva="D")
        assert partes[-1] == ("directiva", "D")
