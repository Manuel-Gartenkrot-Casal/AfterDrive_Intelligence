"""Tests del módulo LLM a través de su interfaz, con un adapter de transporte falso."""

import json

import pytest

import llm


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


def test_embeber_nunca_va_a_openrouter(transporte, openrouter):
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
