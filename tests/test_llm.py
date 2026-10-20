"""Tests del módulo LLM a través de su interfaz, con un adapter de transporte falso."""

import json

import pytest

from afterdrive.ia import consumo, llm


class Resp:
    def __init__(self, status=200, body=None, lineas=None):
        self.status_code = status
        self._body = body or {}
        self._lineas = lineas or []

    @property
    def ok(self):
        return self.status_code < 400

    @property
    def text(self):
        return json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_lines(self):
        return iter(self._lineas)


def chat(texto):
    return Resp(body={"choices": [{"message": {"content": texto}}]})


class Transporte:
    """Adapter falso: responde por orden según la URL y registra los payloads."""

    def __init__(self, respuestas, modelos=()):
        self.respuestas = list(respuestas)
        self.modelos = list(modelos)
        self.posts = []

    def post(self, url, *, json, headers, timeout, stream):
        self.posts.append({"url": url, "json": json, "headers": headers, "stream": stream})
        r = self.respuestas.pop(0)
        return r(json) if callable(r) else r

    def get(self, url, *, headers, timeout):
        return Resp(body={"data": [{"id": m} for m in self.modelos]})


@pytest.fixture
def transporte(monkeypatch):
    def instalar(respuestas, modelos=()):
        t = Transporte(respuestas, modelos)
        monkeypatch.setattr(llm, "_transporte", {"post": t.post, "get": t.get})
        return t

    monkeypatch.setattr(llm, "_dormir", lambda s: None)
    monkeypatch.setattr(llm, "_disponible_cache", {})
    monkeypatch.setattr(llm, "_modelos_caidos", {})
    return instalar


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "mistral-small")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", "mistral-fallback")
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)


@pytest.fixture
def nvidia(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-key")
    monkeypatch.setenv("NVIDIA_MODEL", "kimi")
    monkeypatch.setenv("NVIDIA_FALLBACK_MODEL", "gpt-oss")
    monkeypatch.setenv("NVIDIA_EMB_MODEL", "nemotron-embed")
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)


def test_completar_devuelve_el_texto(transporte, openrouter):
    t = transporte([chat("  hola  ")])
    assert llm.completar("sys", "user") == "hola"
    enviado = t.posts[0]
    assert enviado["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert enviado["headers"] == {"Authorization": "Bearer or-key"}
    assert enviado["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


def test_include_reasoning_solo_en_openrouter(transporte, openrouter, monkeypatch):
    t = transporte([chat("a"), chat("b")])
    llm.completar("s", "u")
    assert t.posts[0]["json"]["include_reasoning"] is False

    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    llm.completar("s", "u")
    assert "include_reasoning" not in t.posts[1]["json"]


def test_proveedor_se_lee_en_cada_llamada(transporte, openrouter, monkeypatch):
    t = transporte([chat("a"), chat("b")])
    llm.completar("s", "u")
    monkeypatch.setenv("OPENROUTER_MODEL", "otro-modelo")
    llm.completar("s", "u")
    assert [p["json"]["model"] for p in t.posts] == ["mistral-small", "otro-modelo"]


def test_cloud_sin_key_cae_a_lm_studio(transporte, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    t = transporte([chat("local")])
    assert llm.completar("s", "u") == "local"
    assert t.posts[0]["url"].startswith("http://localhost:1234/v1")


def test_modelo_dado_de_baja_usa_fallback(transporte, nvidia):
    t = transporte([Resp(410), chat("desde fallback")])
    assert llm.completar("s", "u") == "desde fallback"
    assert [p["json"]["model"] for p in t.posts] == ["kimi", "gpt-oss"]


def test_modelo_y_fallback_caidos_da_error_accionable(transporte, nvidia):
    transporte([Resp(410), Resp(404)], modelos=["kimi-k4", "llama-4"])
    with pytest.raises(llm.ErrorLLM) as e:
        llm.completar("s", "u")
    assert "NVIDIA_MODEL" in str(e.value)
    assert "kimi-k4" in str(e.value)


def test_rate_limit_prueba_fallback_y_despues_backoff(transporte, openrouter):
    t = transporte([Resp(429), Resp(429), Resp(429), chat("ok")])
    assert llm.completar("s", "u") == "ok"
    assert [p["json"]["model"] for p in t.posts] == [
        "mistral-small", "mistral-fallback", "mistral-small", "mistral-small",
    ]


def test_rate_limit_persistente_levanta_error(transporte, openrouter):
    transporte([Resp(429)] * 20)
    with pytest.raises(llm.ErrorLLM, match="429"):
        llm.completar("s", "u")


def sse(*chunks):
    return [f"data: {json.dumps(c)}".encode() for c in chunks] + [b"data: [DONE]"]


def test_stream_junta_solo_content_nunca_reasoning(transporte, openrouter):
    lineas = sse(
        {"choices": [{"delta": {"reasoning_content": "Let me think..."}}]},
        {"choices": [{"delta": {"content": "# Título"}}]},
        {"choices": [{"delta": {"content": "\nCuerpo"}}]},
        {"choices": [{"delta": {}}]},
    )
    t = transporte([Resp(lineas=lineas)])
    assert llm.completar("s", "u", stream=True) == "# Título\nCuerpo"
    assert t.posts[0]["stream"] is True


def test_embeber_batch_en_orden_y_vacios_sin_llamar(transporte, nvidia):
    t = transporte([Resp(body={"data": [
        {"index": 1, "embedding": [2.0]},
        {"index": 0, "embedding": [1.0]},
    ]})])
    assert llm.embeber(["uno", "", "dos"]) == [[1.0], None, [2.0]]
    enviado = t.posts[0]["json"]
    assert enviado["input"] == ["uno", "dos"]
    assert enviado["input_type"] == "passage"
    assert enviado["model"] == "nemotron-embed"


def test_embeber_con_chat_openrouter_usa_embeddings_provider(transporte, openrouter, monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    t = transporte([Resp(body={"data": [{"index": 0, "embedding": [1.0]}]})])
    llm.embeber(["x"])
    assert t.posts[0]["url"] == "https://integrate.api.nvidia.com/v1/embeddings"


def test_embeber_nunca_va_a_openrouter(transporte, openrouter, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)   # sin key de NVIDIA, a LM Studio
    t = transporte([Resp(body={"data": [{"index": 0, "embedding": [1.0]}]})])
    llm.embeber(["x"])
    assert t.posts[0]["url"].startswith("http://localhost:1234/v1")


def test_embeber_modelo_caido_devuelve_none_sin_reintentar(transporte, nvidia):
    t = transporte([Resp(410)])
    assert llm.embeber(["a", "b"]) == [None, None]
    assert len(t.posts) == 1


def test_embeber_si_falla_el_batch_va_uno_por_uno(transporte, nvidia):
    t = transporte([Resp(500), Resp(500), Resp(500),
                    Resp(body={"data": [{"embedding": [1.0]}]}),
                    Resp(body={"data": [{"embedding": [2.0]}]})])
    assert llm.embeber(["a", "b"]) == [[1.0], [2.0]]
    assert [p["json"]["input"] for p in t.posts[3:]] == ["a", "b"]


def test_set_proveedor_valida_y_persiste_en_entorno(transporte, monkeypatch):
    transporte([])
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert not llm.set_proveedor("gemini")["success"]
    assert not llm.set_proveedor("nvidia")["success"]
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    r = llm.set_proveedor("nvidia")
    assert r["success"] and r["provider"] == "nvidia"
    import os
    assert os.environ["AI_PROVIDER"] == "nvidia"


def test_stream_que_solo_razona_reintenta_con_el_fallback(transporte, nvidia):
    solo_razona = sse({"choices": [{"delta": {"reasoning_content": "pienso " * 50}}]},
                      {"choices": [{"delta": {}, "finish_reason": "length"}]})
    ok = sse({"choices": [{"delta": {"content": "# Nota"}}]})
    t = transporte([Resp(lineas=solo_razona), Resp(lineas=ok)])
    assert llm.completar("s", "u", stream=True, max_tokens=4000) == "# Nota"
    assert [p["json"]["model"] for p in t.posts] == ["kimi", "gpt-oss"]


def test_stream_que_solo_razona_da_error_explicativo(transporte, nvidia):
    solo_razona = sse({"choices": [{"delta": {"reasoning_content": "pienso " * 50}}]},
                      {"choices": [{"delta": {}, "finish_reason": "length"}]})
    transporte([Resp(lineas=solo_razona), Resp(lineas=solo_razona)])
    with pytest.raises(llm.ErrorLLM, match="razonando"):
        llm.completar("s", "u", stream=True)


def test_embeddings_sin_servidor_fallan_rapido(transporte, openrouter, monkeypatch):
    import requests as rq
    intentos = []

    def rechazado(url, **kw):
        intentos.append(url)
        raise rq.exceptions.ConnectionError("Connection refused")

    t = transporte([])
    monkeypatch.setattr(llm, "_transporte", {"post": rechazado, "get": t.get})
    assert llm.embeber(["a", "b"]) == [None, None]
    assert len(intentos) == 1        # antes: 3 en lote + 5 por texto


def test_con_openrouter_los_embeddings_van_a_nvidia_si_hay_key(transporte, openrouter, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    t = transporte([Resp(body={"data": [{"index": 0, "embedding": [1.0]}]})])
    llm.embeber(["x"])
    assert t.posts[0]["url"].startswith("https://integrate.api.nvidia.com")


def test_set_proveedor_local_se_rechaza_si_lm_studio_no_responde(transporte, monkeypatch):
    # En Render no hay LM Studio: elegir "local" dejaba la generación programada
    # fallando todos los días hasta que alguien volvía a otro proveedor.
    def sin_respuesta(url, *, headers, timeout):
        raise ConnectionError("connection refused")

    transporte([])
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    monkeypatch.setitem(llm._transporte, "get", sin_respuesta)
    r = llm.set_proveedor("local")
    assert not r["success"] and "LM Studio" in r["error"]
    assert llm.proveedor_activo() == "nvidia"


def test_set_proveedor_local_se_acepta_si_lm_studio_responde(transporte, monkeypatch):
    transporte([], modelos=["mistral-7b"])
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    r = llm.set_proveedor("local")
    assert r["success"] and llm.proveedor_activo() == "local"


def test_disponible_se_vuelve_a_chequear_despues_de_una_caida(monkeypatch, openrouter):
    """Un 'no responde' no puede quedar cacheado para siempre (modo degradado eterno)."""
    ahora = [1000.0]
    respuestas = [False, True]
    llamadas = []

    def get(url, *, headers, timeout):
        llamadas.append(url)
        if not respuestas.pop(0):
            raise ConnectionError("caído")

    monkeypatch.setattr(llm, "_disponible_cache", {})
    monkeypatch.setattr(llm, "_reloj", lambda: ahora[0])
    monkeypatch.setattr(llm, "_transporte", {"get": get, "post": None})
    assert llm.disponible() is False
    assert llm.disponible() is False and len(llamadas) == 1   # dentro de la vigencia, no pregunta
    ahora[0] += llm.VIGENCIA_CAIDO_S + 1
    assert llm.disponible() is True and len(llamadas) == 2    # vencida, vuelve a preguntar
    ahora[0] += llm.VIGENCIA_CAIDO_S + 1
    assert llm.disponible() is True and len(llamadas) == 2    # un OK dura más


@pytest.mark.parametrize("respuesta, esperado", [
    ('{"aprobado": true, "razon": "ok"}', True),
    ('{"aprobado": false, "razon": "no"}', False),
    ('{"aprobado": "false", "razon": "no"}', False),
    ('{"aprobado": "true", "razon": "ok"}', True),
    ('{"aprobado": 1, "razon": "?"}', False),
])
def test_clasificador_lee_aprobado_sin_trampas(monkeypatch, respuesta, esperado):
    from afterdrive.ia import lm_studio
    monkeypatch.setattr(lm_studio.llm, "disponible", lambda: True)
    monkeypatch.setattr(lm_studio.llm, "completar", lambda *a, **k: respuesta)
    assert lm_studio.clasificar_articulo("t", "c")["aprobado"] is esperado


@pytest.fixture
def paga(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "paga")
    monkeypatch.setenv("PAGA_API_KEY", "pg-key")
    monkeypatch.setenv("PAGA_BASE_URL", "https://api.paga.test/v1")
    monkeypatch.setenv("PAGA_MODEL", "modelo-pago")
    monkeypatch.delenv("PAGA_EMB_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)


def test_paga_usa_su_url_key_y_modelo(transporte, paga):
    t = transporte([chat("hola")])
    assert llm.completar("s", "u") == "hola"
    assert t.posts[0]["url"] == "https://api.paga.test/v1/chat/completions"
    assert t.posts[0]["headers"] == {"Authorization": "Bearer pg-key"}
    assert t.posts[0]["json"]["model"] == "modelo-pago"
    assert "include_reasoning" not in t.posts[0]["json"]


def test_paga_sin_modelo_de_embeddings_no_recibe_embeddings(transporte, paga, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    t = transporte([Resp(body={"data": [{"index": 0, "embedding": [1.0]}]})])
    llm.embeber(["x"])
    assert "integrate.api.nvidia.com" in t.posts[0]["url"]


def test_set_proveedor_paga_exige_key_url_y_modelo(transporte, paga, monkeypatch):
    transporte([])
    monkeypatch.setenv("AI_PROVIDER", "local")
    monkeypatch.delenv("PAGA_MODEL")
    assert not llm.set_proveedor("paga")["success"]
    monkeypatch.setenv("PAGA_MODEL", "modelo-pago")
    r = llm.set_proveedor("paga")
    assert r["success"] and r["provider"] == "paga" and r["paga_available"]


def test_paga_elige_modelo_por_tarea(transporte, paga, monkeypatch):
    monkeypatch.setenv("PAGA_MODEL_CLASIFICACION", "luna")
    monkeypatch.setenv("PAGA_MODEL_REDACCION", "astra")
    monkeypatch.delenv("PAGA_MODEL_EVALUACION", raising=False)
    t = transporte([chat("a"), chat("b"), chat("c")])
    llm.completar("s", "u", tarea="clasificacion")
    llm.completar("s", "u", tarea="redaccion")
    llm.completar("s", "u", tarea="evaluacion")
    assert [p["json"]["model"] for p in t.posts] == ["luna", "astra", "modelo-pago"]
    assert "max_completion_tokens" in t.posts[0]["json"] and "max_tokens" not in t.posts[0]["json"]


def test_tarea_no_cambia_el_modelo_de_otros_proveedores(transporte, openrouter, monkeypatch):
    monkeypatch.setenv("PAGA_MODEL_REDACCION", "astra")
    t = transporte([chat("a")])
    llm.completar("s", "u", tarea="redaccion")
    assert t.posts[0]["json"]["model"] == "mistral-small"
    assert "max_tokens" in t.posts[0]["json"] and "temperature" in t.posts[0]["json"]


def test_paga_sin_temperatura(transporte, paga, monkeypatch):
    monkeypatch.setenv("PAGA_TEMPERATURA", "0")
    t = transporte([chat("a")])
    llm.completar("s", "u")
    assert "temperature" not in t.posts[0]["json"]


def test_cancelar_corta_el_stream_en_el_proximo_fragmento(transporte, openrouter, monkeypatch):
    leidos = []

    def cancelada():
        return len(leidos) >= 2  # se cancela después del segundo fragmento

    lineas = sse(*({"choices": [{"delta": {"content": f"parte {i} "}}]} for i in range(50)))
    resp = Resp(lineas=lineas)
    resp.iter_lines = lambda: (leidos.append(linea) or linea for linea in lineas)
    transporte([resp])
    monkeypatch.setattr(llm, "_cancelada", cancelada)
    with pytest.raises(llm.Cancelada):
        llm.completar("s", "u", stream=True)
    assert len(leidos) < 5


def test_cancelada_no_llama_al_proveedor(transporte, openrouter, monkeypatch):
    t = transporte([chat("no debería pedirse")])
    monkeypatch.setattr(llm, "_cancelada", lambda: True)
    with pytest.raises(llm.Cancelada):
        llm.completar("s", "u")
    assert t.posts == []


def test_plan_y_correccion_usan_el_modelo_de_evaluacion(transporte, paga, monkeypatch):
    monkeypatch.setenv("PAGA_MODEL_EVALUACION", "barato")
    monkeypatch.setenv("PAGA_MODEL_REDACCION", "caro")
    t = transporte([chat("x")] * 4)
    for tarea in ("planificacion", "correccion", "redaccion", "otra"):
        llm.completar("s", "u", tarea=tarea)
    assert [p["json"]["model"] for p in t.posts] == ["barato", "barato", "caro", "modelo-pago"]
    monkeypatch.setenv("PAGA_MODEL_CORRECCION", "propio")
    t = transporte([chat("x")])
    llm.completar("s", "u", tarea="correccion")
    assert t.posts[0]["json"]["model"] == "propio"


# ── Tokens de cada llamada (todos los proveedores) ─────────────────────────────


def test_llamada_de_nvidia_guarda_tokens_sin_costo(transporte, nvidia, consumo_en_memoria, capsys):
    transporte([Resp(body={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 120, "completion_tokens": 30}})])
    llm.completar("s", "u", max_tokens=512, tarea="clasificacion")
    fila = consumo_en_memoria.find_one()
    assert fila["proveedor"] == "nvidia" and fila["tarea"] == "clasificacion"
    assert (fila["tokens_entrada"], fila["tokens_salida"], fila["max_tokens"]) == (120, 30, 512)
    assert fila["costo_usd"] == 0 and fila["truncado"] is False
    assert "[TOKENS] clasificacion · nvidia · entrada 120 · salida 30 · total 150 (límite de salida 512)" in capsys.readouterr().out
    assert consumo.gastado_mes() == 0   # lo gratuito no suma al tope de la API paga


def test_respuesta_cortada_por_el_limite(transporte, openrouter, consumo_en_memoria, capsys):
    transporte([Resp(body={"choices": [{"message": {"content": "a medias"}, "finish_reason": "length"}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 256}})])
    llm.completar("s", "u", max_tokens=256)
    assert consumo_en_memoria.find_one()["truncado"] is True
    assert "CORTADA POR EL LÍMITE" in capsys.readouterr().out


def test_stream_pide_los_tokens_y_marca_el_corte(transporte, nvidia, consumo_en_memoria):
    lineas = sse({"choices": [{"delta": {"content": "Hola"}}]},
                 {"choices": [{"delta": {}, "finish_reason": "length"}]},
                 {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 4000}})
    t = transporte([Resp(lineas=lineas)])
    llm.completar("s", "u", stream=True, max_tokens=4000, tarea="redaccion")
    assert t.posts[0]["json"]["stream_options"] == {"include_usage": True}
    fila = consumo_en_memoria.find_one()
    assert (fila["tokens_salida"], fila["truncado"], fila["estimado"]) == (4000, True, False)


def test_si_el_modelo_rechaza_stream_options_se_reintenta_sin(transporte, nvidia, consumo_en_memoria):
    rechazo = Resp(status=400, body={"error": "Unknown field: stream_options"})
    t = transporte([rechazo, Resp(lineas=sse({"choices": [{"delta": {"content": "Nota"}}]}))])
    assert llm.completar("s", "u", stream=True) == "Nota"
    assert "stream_options" not in t.posts[1]["json"]
    assert consumo_en_memoria.find_one()["estimado"] is True   # sin usage, se estima


def test_embeddings_de_nvidia_tambien_se_registran(transporte, nvidia, consumo_en_memoria):
    transporte([Resp(body={"data": [{"index": 0, "embedding": [0.1]}], "usage": {"prompt_tokens": 7}})])
    llm.embeber(["hola"])
    fila = consumo_en_memoria.find_one()
    assert fila["tarea"] == "embeddings" and fila["tokens_entrada"] == 7 and fila["costo_usd"] == 0


def test_modelo_dado_de_baja_se_recuerda_y_va_directo_al_respaldo(transporte, nvidia):
    t = transporte([Resp(410), chat("uno"), chat("dos")])
    assert llm.completar("s", "u") == "uno"
    assert llm.completar("s", "u") == "dos"
    assert [p["json"]["model"] for p in t.posts] == ["kimi", "gpt-oss", "gpt-oss"]


def test_gpt_oss_pide_razonamiento_bajo(transporte, nvidia, monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "openai/gpt-oss-20b")
    t = transporte([chat("ok")])
    llm.completar("sys", "u")
    assert t.posts[0]["json"]["messages"][0] == {"role": "system", "content": "Reasoning: low\n\nsys"}


def test_sin_stream_si_solo_razono_reintenta_con_mas_tokens(transporte, nvidia):
    vacia = Resp(body={"choices": [{"message": {"content": "", "reasoning_content": "pienso"}, "finish_reason": "length"}]})
    t = transporte([vacia, chat('{"ok": true}')])
    assert llm.completar("s", "u", max_tokens=900, tarea="clasificacion") == '{"ok": true}'
    assert [p["json"]["max_tokens"] for p in t.posts] == [900, 3600]
