"""API paga por Bedrock Converse y tope mensual de consumo, con transporte falso (sin red)."""

import json

import pytest

from afterdrive.ia import consumo, llm

ARN_LUNA = "arn:aws:bedrock:us-east-2:000000000000:application-inference-profile/luna6"
ARN_KIMI = "arn:aws:bedrock:us-east-2:000000000000:application-inference-profile/kimi"


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    @property
    def ok(self):
        return self.status_code < 400

    @property
    def text(self):
        return json.dumps(self._body)

    def json(self):
        return self._body


def converse(texto, entrada=100, salida=20, razonamiento=None, stop="end_turn"):
    bloques = ([{"reasoningContent": {"reasoningText": {"text": razonamiento}}}] if razonamiento else [])
    bloques += [{"text": texto}] if texto else []
    return Resp(body={"output": {"message": {"role": "assistant", "content": bloques}}, "stopReason": stop,
                      "usage": {"inputTokens": entrada, "outputTokens": salida}})


@pytest.fixture
def bedrock(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "paga")
    monkeypatch.setenv("PAGA_API", "converse")
    monkeypatch.setenv("PAGA_API_KEY", "br-key")
    monkeypatch.setenv("PAGA_BASE_URL", "https://bedrock-runtime.us-east-2.amazonaws.com")
    monkeypatch.setenv("PAGA_MODEL", ARN_LUNA)
    monkeypatch.setenv("PAGA_MODEL_REDACCION", ARN_KIMI)
    for v in ("PAGA_MODEL_CLASIFICACION", "PAGA_MODEL_EVALUACION", "PAGA_FALLBACK_MODEL", "PAGA_TOPE_MENSUAL_USD",
              "PAGA_PRECIO_REDACCION", "PAGA_PRECIO_CLASIFICACION"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    monkeypatch.setattr(llm, "_dormir", lambda s: None)
    posts = []

    def instalar(respuestas):
        def post(url, *, json, headers, timeout, stream):
            posts.append({"url": url, "json": json, "headers": headers})
            return respuestas.pop(0)
        monkeypatch.setattr(llm, "_transporte", {"post": post, "get": lambda *a, **k: Resp()})
        return posts
    return instalar


def test_converse_arma_la_llamada_y_lee_solo_el_texto(bedrock):
    posts = bedrock([converse("Nota final.", razonamiento="Primero pienso que...")])
    assert llm.completar("sos un redactor", "escribí", max_tokens=16000, tarea="redaccion") == "Nota final."
    p = posts[0]
    assert p["url"] == ("https://bedrock-runtime.us-east-2.amazonaws.com/model/"
                        "arn%3Aaws%3Abedrock%3Aus-east-2%3A000000000000%3Aapplication-inference-profile%2Fkimi/converse")
    assert p["headers"] == {"Authorization": "Bearer br-key"}
    assert p["json"] == {
        "messages": [{"role": "user", "content": [{"text": "escribí"}]}],
        "inferenceConfig": {"maxTokens": 16000},
        "system": [{"text": "sos un redactor"}],
    }
    assert "temperature" not in json.dumps(p["json"])


def test_converse_registra_tokens_y_costo_por_tarea(bedrock, consumo_en_memoria):
    bedrock([converse("ok", entrada=1_000_000, salida=1_000_000)])
    llm.completar("s", "u", tarea="redaccion")
    fila = consumo_en_memoria.find_one()
    assert fila["tarea"] == "redaccion" and fila["modelo"] == ARN_KIMI
    assert (fila["tokens_entrada"], fila["tokens_salida"]) == (1_000_000, 1_000_000)
    assert fila["costo_usd"] == pytest.approx(3.30 + 16.50)
    assert consumo.gastado_mes() == pytest.approx(19.80)


def test_precio_sale_del_modelo_que_contesto(bedrock, monkeypatch):
    monkeypatch.setenv("PAGA_MODEL_CLASIFICACION", "arn-luna")
    monkeypatch.setenv("PAGA_PRECIO_CLASIFICACION", "1/2")
    assert consumo.precio_de_modelo("arn-luna") == (1.0, 2.0)
    monkeypatch.setenv("PAGA_PRECIO_CLASIFICACION", "basura")
    assert consumo.precio_de_modelo("arn-luna") == consumo.PRECIOS_DEFAULT["clasificacion"]
    assert consumo.precio_de_modelo("arn-desconocido") == (3.30, 16.50)  # sin precio: el más alto
    assert consumo.precio_de_modelo(ARN_LUNA) == (3.30, 16.50)          # PAGA_MODEL sin PAGA_PRECIO_GENERAL


def test_si_contesta_el_respaldo_se_cobra_al_precio_del_respaldo(bedrock, monkeypatch, consumo_en_memoria):
    monkeypatch.setenv("PAGA_MODEL_CLASIFICACION", "arn-luna")
    monkeypatch.setenv("PAGA_FALLBACK_MODEL", ARN_KIMI)
    posts = bedrock([Resp(429, {"message": "ThrottlingException"}), converse("ok", 1_000_000, 0)])
    llm.completar("s", "u", tarea="clasificacion")
    assert "kimi" in posts[1]["url"]
    fila = consumo_en_memoria.find_one()
    assert fila["modelo"] == ARN_KIMI and fila["costo_usd"] == pytest.approx(3.30)


def test_insert_fallido_sigue_contando_para_el_tope(bedrock, monkeypatch, consumo_en_memoria):
    ahora = [0.0]
    monkeypatch.setattr(consumo, "_reloj", lambda: ahora[0])
    assert consumo.gastado_mes() == 0

    class SoloLectura:
        def insert_one(self, doc):
            raise RuntimeError("escritura rechazada")

        def aggregate(self, pipeline):
            return consumo_en_memoria.aggregate(pipeline)

    monkeypatch.setattr(consumo, "_coleccion", lambda: SoloLectura())
    monkeypatch.setattr(consumo, "_sin_registrar", {})
    consumo.registrar("redaccion", ARN_KIMI, 0, 2_000_000)  # USD 33
    ahora[0] += 120                                          # vence el cache: se relee Mongo
    assert consumo.gastado_mes() == pytest.approx(33.0)


def test_timeout_de_converse_registra_el_maximo(bedrock, consumo_en_memoria):
    import requests

    def post(*a, **k):
        raise requests.exceptions.ReadTimeout("lento")
    llm._transporte["post"] = post
    with pytest.raises(llm.ErrorLLM, match="CONVERSE_TIMEOUT"):
        llm.completar("s", "u" * 300, max_tokens=16000, tarea="redaccion")
    fila = consumo_en_memoria.find_one()
    assert fila["estimado"] and fila["tokens_salida"] == 16000


def test_converse_solo_razonamiento_da_error_aunque_termine_bien(bedrock):
    bedrock([converse("", razonamiento="pienso", stop="end_turn")])
    with pytest.raises(llm.ErrorLLM, match="razonó"):
        llm.completar("s", "u", tarea="redaccion")


def test_con_converse_los_embeddings_nunca_van_a_bedrock(bedrock, monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "paga")
    monkeypatch.setenv("PAGA_EMB_MODEL", "emb")
    monkeypatch.setenv("NVIDIA_EMB_MODEL", "nemotron")
    assert llm.modelo_embeddings() == "nvidia/nemotron"


def test_tope_alcanzado_pasa_a_nvidia_y_vuelve_jev(bedrock, monkeypatch, consumo_en_memoria):
    monkeypatch.setenv("PAGA_TOPE_MENSUAL_USD", "40")
    assert llm.usa_api_paga()
    consumo.registrar("redaccion", ARN_KIMI, 1_000_000, 2_200_000)  # USD 39.60
    assert llm.usa_api_paga()
    consumo.registrar("redaccion", ARN_KIMI, 200_000, 0)              # +0.66 -> 40.26
    assert not llm.usa_api_paga()
    assert llm._perfil_chat().nombre == "nvidia"
    e = llm.estado()
    assert e["paga_tope_alcanzado"] and e["paga_tope_usd"] == 40 and e["paga_gastado_mes_usd"] >= 40

    from afterdrive.ingesta import ingesta
    usados = []
    monkeypatch.setattr(ingesta.jev_clasificador, "clasificar", lambda t, c: usados.append("jev") or {"aprobado": True})
    ingesta.clasificar("t", "c")
    assert usados == ["jev"]


def test_sin_poder_leer_el_consumo_no_se_usa_la_api_paga(bedrock, monkeypatch):
    llamadas = []

    def rota():
        llamadas.append(1)
        raise RuntimeError("mongo caído")
    monkeypatch.setattr(consumo, "_coleccion", rota)
    assert not llm.usa_api_paga()
    assert "no se pudo leer" in consumo.motivo_tope()
    assert not llm.usa_api_paga() and len(llamadas) == 1  # el fallo se cachea


def test_converse_sin_texto_por_max_tokens_da_error(bedrock):
    bedrock([converse("", razonamiento="pienso" * 100, stop="max_tokens")])
    with pytest.raises(llm.ErrorLLM, match="razonó"):
        llm.completar("s", "u", tarea="redaccion")


def test_converse_key_sin_permiso_da_error_accionable(bedrock):
    bedrock([Resp(401, {"message": "User BedrockAPIKey is not authorized to perform: bedrock:InvokeModel"})])
    with pytest.raises(llm.ErrorLLM, match="PAGA_MODEL_REDACCION"):
        llm.completar("s", "u", tarea="redaccion")


def test_converse_429_reintenta_con_backoff(bedrock):
    posts = bedrock([Resp(429, {"message": "ThrottlingException"}), converse("ok")])
    assert llm.completar("s", "u", tarea="clasificacion") == "ok"
    assert len(posts) == 2


def test_chat_completions_de_la_api_paga_tambien_registra(monkeypatch, consumo_en_memoria):
    monkeypatch.setenv("AI_PROVIDER", "paga")
    monkeypatch.delenv("PAGA_API", raising=False)
    monkeypatch.setenv("PAGA_API_KEY", "k")
    monkeypatch.setenv("PAGA_BASE_URL", "https://api.paga.test/v1")
    monkeypatch.setenv("PAGA_MODEL", "m")
    body = {"model": "m", "choices": [{"message": {"content": "hola"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    monkeypatch.setattr(llm, "_transporte", {"post": lambda url, **k: Resp(body=body), "get": lambda *a, **k: Resp()})
    assert llm.completar("s", "u", tarea="evaluacion") == "hola"
    fila = consumo_en_memoria.find_one()
    assert (fila["tarea"], fila["tokens_entrada"], fila["tokens_salida"]) == ("evaluacion", 10, 5)


def test_timeout_en_el_respaldo_se_valua_con_el_mas_caro(bedrock, monkeypatch, consumo_en_memoria):
    import requests
    monkeypatch.setenv("PAGA_MODEL_CLASIFICACION", "arn-luna")
    monkeypatch.setenv("PAGA_FALLBACK_MODEL", ARN_KIMI)
    respuestas = [Resp(429, {"message": "ThrottlingException"})]

    def post(url, **k):
        if respuestas:
            return respuestas.pop(0)
        raise requests.exceptions.ReadTimeout("el respaldo tardó")
    llm._transporte["post"] = post
    with pytest.raises(llm.ErrorLLM):
        llm.completar("s", "u", max_tokens=16000, tarea="clasificacion")
    fila = consumo_en_memoria.find_one()
    assert fila["modelo"] == ARN_KIMI and fila["estimado"]
    assert fila["costo_usd"] >= 16000 * 16.50 / 1_000_000


def _paga_chat(monkeypatch, respuesta):
    monkeypatch.setenv("AI_PROVIDER", "paga")
    monkeypatch.delenv("PAGA_API", raising=False)
    monkeypatch.setenv("PAGA_API_KEY", "k")
    monkeypatch.setenv("PAGA_BASE_URL", "https://api.paga.test/v1")
    monkeypatch.setenv("PAGA_MODEL", "m")
    monkeypatch.setattr(llm, "_transporte", {"post": lambda url, **k: respuesta, "get": lambda *a, **k: Resp()})


def test_chat_sin_choices_registra_y_da_error_claro(monkeypatch, consumo_en_memoria):
    _paga_chat(monkeypatch, Resp(body={"usage": {"prompt_tokens": 10, "completion_tokens": 900}}))
    with pytest.raises(llm.ErrorLLM, match="choices"):
        llm.completar("s", "u", tarea="evaluacion")
    assert consumo_en_memoria.find_one()["tokens_salida"] == 900


def test_stream_callado_registra_una_estimacion(monkeypatch, consumo_en_memoria):
    import requests

    class Callado(Resp):
        def iter_lines(self):
            raise requests.exceptions.ReadTimeout("sin tokens")
    _paga_chat(monkeypatch, Callado())
    with pytest.raises(llm.ErrorLLM):
        llm.completar("s", "u", max_tokens=16000, stream=True, tarea="redaccion")
    fila = consumo_en_memoria.find_one()
    assert fila["estimado"] and fila["tokens_salida"] == 16000


@pytest.mark.parametrize("uso, esperado", [
    ({"inputTokens": 2, "outputTokens": 50, "cacheReadInputTokens": 1100}, 1102),                 # cache aparte
    ({"inputTokens": 2, "outputTokens": 50, "cacheWriteInputTokens": 900, "totalTokens": 1500}, 1450),  # total manda
    ({"inputTokens": 2, "outputTokens": 50}, 1000),                                                 # piso por caracteres
    ({"inputTokens": 3000, "outputTokens": 50}, 3000),                                              # lo informado alcanza
])
def test_entrada_contada_nunca_por_debajo_de_lo_enviado(bedrock, consumo_en_memoria, uso, esperado):
    bedrock([Resp(body={"output": {"message": {"content": [{"text": "ok"}]}}, "stopReason": "end_turn",
                        "usage": uso})])
    llm.completar("", "x" * 4000, tarea="clasificacion")  # 4000 chars -> piso de 1000 tokens
    fila = consumo_en_memoria.find_one()
    assert (fila["tokens_entrada"], fila["tokens_salida"]) == (esperado, 50)


def test_bedrock_marca_el_corte_por_max_tokens(bedrock, consumo_en_memoria):
    bedrock([converse("texto cortado", entrada=900, salida=1024, stop="max_tokens")])
    llm.completar("s", "u", max_tokens=1024, tarea="evaluacion")
    fila = consumo_en_memoria.find_one()
    assert fila["proveedor"] == "paga" and fila["truncado"] is True and fila["max_tokens"] == 1024
    assert fila["costo_usd"] > 0
