"""
llm.py — Módulo LLM: el único lugar que sabe hablar con un proveedor de IA.

Interfaz:
    completar(system, user, temperature=..., max_tokens=..., stream=False) -> str
    embeber(textos, tipo="passage") -> list[vector | None]
    disponible() -> bool
    ajustes_redaccion() -> Redaccion
    estado() -> dict
    set_proveedor(nombre) -> dict
    ErrorLLM

Todo lo que varía por proveedor (URL, key, modelo, fallback, quirks del payload,
límites de embeddings) es un Perfil: datos, no ramas `if AI_PROVIDER == ...`
repartidas entre callers. Los tres proveedores hablan la API compatible con
OpenAI, así que hay un solo adapter HTTP; el seam `_transporte` existe para que
los tests inyecten un adapter falso (ver tests/test_llm.py).

El proveedor activo se lee de AI_PROVIDER en cada llamada, no al importar: así
el orden de imports deja de importar y un cambio desde el dashboard llega
también a los subprocesos (que heredan os.environ).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

load_dotenv()

PROVEEDORES = ("local", "nvidia", "openrouter")

# Códigos que significan "este modelo ya no existe": reintentar no lo revive.
# 404 = nunca existió con ese id; 410 = fue dado de baja por el proveedor.
_MODELO_CAIDO = (404, 410)


class ErrorLLM(RuntimeError):
    """Fallo del proveedor con un mensaje accionable para el usuario."""


_ANTI_RAZONAMIENTO = (
    "Importante: este modelo tiende a escribir su razonamiento. No lo hagas: la respuesta "
    "empieza directamente con el título de la nota (\"# ...\") y termina con la meta description."
)


@dataclass(frozen=True)
class Redaccion:
    """Cómo conviene pedirle una nota a este proveedor.

    Valores razonados por familia de modelo, no benchmarkeados: ajustables
    con REDACCION_TEMPERATURA si hace falta.
    """
    temperatura: float = 0.6
    max_tokens: int = 4000        # los modelos que razonan gastan tokens antes de escribir
    compacto: bool = False        # prompt corto para modelos chicos
    max_ejemplos: int = 3         # notas de referencia de estilo
    chars_ejemplo: int = 1500
    directiva: str = ""           # instrucción extra específica del modelo


@dataclass(frozen=True)
class Perfil:
    nombre: str
    base_url: str
    api_key: str
    modelo: str
    modelo_fallback: str = ""
    variable_modelo: str = ""  # env var a corregir si el modelo fue dado de baja
    extra_payload: dict = field(default_factory=dict)
    modelo_emb: str = ""
    emb_max_chars: int = 8000
    emb_input_type: bool = False  # NVIDIA exige input_type en /embeddings
    redaccion: Redaccion = field(default_factory=Redaccion)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}


def _perfil(nombre: str) -> Perfil:
    """Construye el perfil de un proveedor desde el entorno.

    Un proveedor cloud sin API key cae a LM Studio local, que es el
    comportamiento histórico.
    """
    env = os.getenv
    if nombre == "nvidia" and env("NVIDIA_API_KEY"):
        return Perfil(
            nombre="nvidia",
            base_url=env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            api_key=env("NVIDIA_API_KEY", ""),
            modelo=env("NVIDIA_MODEL", "moonshotai/kimi-k3"),
            modelo_fallback=env("NVIDIA_FALLBACK_MODEL", "openai/gpt-oss-20b"),
            variable_modelo="NVIDIA_MODEL",
            modelo_emb=env("NVIDIA_EMB_MODEL", "nvidia/nemotron-3-embed-1b"),
            emb_max_chars=1500,
            emb_input_type=True,
            # kimi y el fallback gpt-oss son modelos que razonan: si se les
            # escapa el plan, la nota sale inservible (ver saneo.py).
            # Razonan antes de escribir: con 4000 tokens kimi-k3 los gastaba todos
            # pensando y devolvía la nota vacía.
            redaccion=Redaccion(temperatura=0.6, max_tokens=16000, directiva=_ANTI_RAZONAMIENTO),
        )
    if nombre == "openrouter" and env("OPENROUTER_API_KEY"):
        return Perfil(
            nombre="openrouter",
            base_url=env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=env("OPENROUTER_API_KEY", ""),
            modelo=env("OPENROUTER_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free"),
            modelo_fallback=env("OPENROUTER_FALLBACK_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free"),
            variable_modelo="OPENROUTER_MODEL",
            # include_reasoning solo existe en OpenRouter; NVIDIA lo rechaza con 400.
            extra_payload={"include_reasoning": False},
            # OpenRouter no tiene /embeddings: _perfil_emb() nunca lo elige.
            # mistral-small instruct sigue bien prompts largos; algo menos de
            # temperatura reduce datos "creativos" sin volver rígido el texto.
            redaccion=Redaccion(temperatura=0.55),
        )
    return Perfil(
        nombre="local",
        base_url=env("LMSTUDIO_URL", "http://localhost:1234/v1"),
        api_key="",
        modelo=env("LMSTUDIO_MODEL", "mistral-7b-instruct-v0.3"),
        variable_modelo="LMSTUDIO_MODEL",
        modelo_emb=env("LMSTUDIO_EMB_MODEL", "text-embedding-nomic-embed-text-v1.5"),
        # Modelos locales chicos (7B): prompt compacto, menos ejemplos y menos
        # temperatura, porque con prompts largos pierden instrucciones.
        redaccion=Redaccion(temperatura=0.45, compacto=True, max_ejemplos=2, chars_ejemplo=700),
    )


def proveedor_activo() -> str:
    return os.getenv("AI_PROVIDER", "local")


def _perfil_chat() -> Perfil:
    return _perfil(proveedor_activo())


def _perfil_emb() -> Perfil:
    """Perfil para embeddings, independiente del de chat.

    EMBEDDINGS_PROVIDER manda si está definido. OpenRouter no sirve embeddings,
    así que si terminara elegido se cae a LM Studio: es preferible fallar contra
    un endpoint local que mandar la request a un proveedor que devuelve 404.
    """
    nombre = os.getenv("EMBEDDINGS_PROVIDER", "").strip().lower() or proveedor_activo()
    if nombre == "openrouter":
        # OpenRouter no tiene /embeddings. NVIDIA si hay key; si no, LM Studio.
        nombre = "nvidia" if os.getenv("NVIDIA_API_KEY") else "local"
    return _perfil(nombre)


def _stream_read_timeout() -> int:
    # Segundos sin recibir un byte antes de dar por colgada una generación en
    # streaming. Sin esto, un proveedor mudo deja la request colgada 30 min.
    return int(os.getenv("STREAM_READ_TIMEOUT", "180"))


# ── Seam de transporte ────────────────────────────────────────────────────────


def _http_post(url: str, *, json: dict, headers: dict, timeout, stream: bool) -> requests.Response:
    return requests.post(url, json=json, headers=headers, timeout=timeout, stream=stream)


def _http_get(url: str, *, headers: dict, timeout) -> requests.Response:
    return requests.get(url, headers=headers, timeout=timeout)


_transporte = {"post": _http_post, "get": _http_get}


def _dormir(segundos: float) -> None:
    time.sleep(segundos)


# ── Disponibilidad ────────────────────────────────────────────────────────────

_disponible_cache: dict[str, bool] = {}


def disponible() -> bool:
    """True si el proveedor activo responde. Se chequea una vez por proveedor."""
    perfil = _perfil_chat()
    if perfil.nombre not in _disponible_cache:
        try:
            _transporte["get"](f"{perfil.base_url}/models", headers=perfil.headers, timeout=5)
            _disponible_cache[perfil.nombre] = True
        except Exception:
            _disponible_cache[perfil.nombre] = False
            print(f"[AVISO] Proveedor '{perfil.nombre}' ({perfil.base_url}) no disponible.", flush=True)
    return _disponible_cache[perfil.nombre]


def ajustes_redaccion() -> Redaccion:
    """Ajustes de redacción del proveedor de chat activo."""
    r = _perfil_chat().redaccion
    temp = os.getenv("REDACCION_TEMPERATURA", "").strip()
    if temp.replace(".", "", 1).isdigit():
        r = Redaccion(float(temp), r.max_tokens, r.compacto, r.max_ejemplos, r.chars_ejemplo, r.directiva)
    return r


def estado() -> dict:
    """Estado del proveedor para el dashboard."""
    chat, emb = _perfil_chat(), _perfil_emb()
    try:
        _transporte["get"](f"{_perfil('local').base_url}/models", headers={}, timeout=5)
        local = True
    except Exception:
        local = False
    return {
        "provider": proveedor_activo(),
        "local_available": local,
        "nvidia_available": bool(os.getenv("NVIDIA_API_KEY")),
        "openrouter_available": bool(os.getenv("OPENROUTER_API_KEY")),
        "model": chat.modelo,
        "emb_model": emb.modelo_emb,
        "emb_provider": emb.nombre,
    }


def set_proveedor(nombre: str) -> dict:
    """Cambia el proveedor de chat en runtime (y para los subprocesos)."""
    if nombre not in PROVEEDORES:
        return {"success": False, "error": "Proveedor inválido. Usá 'local', 'nvidia' u 'openrouter'."}
    if nombre == "nvidia" and not os.getenv("NVIDIA_API_KEY"):
        return {"success": False, "error": "No hay API key de NVIDIA configurada."}
    if nombre == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        return {"success": False, "error": "No hay API key de OpenRouter configurada."}
    if nombre == "local":
        # La elección se persiste: aceptar "local" donde no hay LM Studio (p. ej.
        # en Render) deja fallando la generación programada hasta que alguien lo note.
        base_url = _perfil("local").base_url
        try:
            _transporte["get"](f"{base_url}/models", headers={}, timeout=5)
        except Exception:
            return {"success": False, "error": f"LM Studio no responde en {base_url}. Se mantiene el proveedor actual."}
    os.environ["AI_PROVIDER"] = nombre
    _disponible_cache.pop(nombre, None)
    disponible()
    return {"success": True, **estado()}


# ── Chat ──────────────────────────────────────────────────────────────────────


def _error_modelo_caido(perfil: Perfil, modelo: str, status: int, variable: str) -> str:
    """Mensaje accionable: qué variable cambiar y qué modelos hay hoy."""
    try:
        r = _transporte["get"](f"{perfil.base_url}/models", headers=perfil.headers, timeout=15)
        r.raise_for_status()
        ids = [m.get("id", "") for m in r.json().get("data", []) if m.get("id")][:40]
    except Exception:
        ids = []
    detalle = (
        "\n  Modelos disponibles hoy en este proveedor:\n    " + "\n    ".join(ids)
        if ids
        else "\n  (no se pudo leer el catálogo del proveedor para sugerir alternativas)"
    )
    return (
        f"El modelo '{modelo}' devolvió HTTP {status}: ya no está disponible. "
        f"Actualizá la variable de entorno {variable}.{detalle}"
    )


def _post_chat(perfil: Perfil, payload: dict, *, timeout, stream: bool, reintentos: int = 5) -> requests.Response:
    """POST a /chat/completions con fallback de modelo y backoff para 429.

    - 404/410 (modelo dado de baja): se prueba el fallback una vez; reintentar
      el mismo modelo es inútil.
    - 429: en el primer intento se prueba el fallback; después, backoff.
    """
    url = f"{perfil.base_url}/chat/completions"
    post = _transporte["post"]
    fallback = perfil.modelo_fallback if perfil.modelo_fallback != payload["model"] else ""

    def _probar_fallback(motivo: str):
        print(f"[FALLBACK] '{payload['model']}' {motivo} -> probando {fallback}", flush=True)
        return post(url, json={**payload, "model": fallback}, headers=perfil.headers, timeout=timeout, stream=stream)

    resp = None
    for intento in range(reintentos):
        resp = post(url, json=payload, headers=perfil.headers, timeout=timeout, stream=stream)
        if resp.status_code in _MODELO_CAIDO:
            if fallback:
                resp_fb = _probar_fallback(f"devolvió {resp.status_code} (modelo dado de baja)")
                if resp_fb.status_code == 200:
                    return resp_fb
            return resp
        if resp.status_code != 429:
            return resp
        if intento == 0 and fallback:
            resp_fb = _probar_fallback("rate-limited (429)")
            if resp_fb.status_code == 200:
                return resp_fb
        espera = min(5 * (2**intento), 60)
        print(f"[RETRY] 429 - esperando {espera}s (intento {intento + 1}/{reintentos})", flush=True)
        _dormir(espera)
    return resp


def _levantar_si_falla(perfil: Perfil, resp: requests.Response) -> None:
    if resp.ok:
        return
    if resp.status_code == 429:
        raise ErrorLLM(f"Rate limit de {perfil.nombre} (429). Esperá unos minutos y reintentá.")
    if resp.status_code in _MODELO_CAIDO:
        raise ErrorLLM(_error_modelo_caido(perfil, perfil.modelo, resp.status_code, perfil.variable_modelo))
    raise ErrorLLM(f"HTTP {resp.status_code}: {resp.text[:1000]}")


def _heartbeat(etiqueta: str, stop: threading.Event, cada: int = 20) -> None:
    """Señales de vida mientras el proveedor no emite el primer token.

    Mantiene tráfico en el stream SSE del dashboard para que el proxy no corte
    la conexión por inactividad.
    """
    t0 = time.time()
    while not stop.wait(cada):
        print(f"  [{int(time.time() - t0)}s] {etiqueta}", flush=True)


def _contenido_de_chunk(chunk: dict) -> str:
    """Texto de un chunk SSE. Solo `content`: nunca `reasoning_content`.

    El razonamiento interno de los modelos reasoning no es parte de la nota;
    dejarlo pasar es lo que hizo que salieran notas con "Let me structure...".
    """
    choices = chunk.get("choices") or []
    if choices:
        return (choices[0].get("delta") or {}).get("content") or ""
    return chunk.get("content") or ""  # formato nativo llama.cpp


@dataclass
class _Stream:
    texto: str = ""
    razonamiento: int = 0         # chars de reasoning_content recibidos (se descartan)
    fin: str | None = None        # finish_reason del último chunk


def _leer_stream(perfil: Perfil, resp: requests.Response) -> _Stream:
    partes: list[str] = []
    info = _Stream()
    t0 = last = time.time()
    try:
        for line in resp.iter_lines():
            if not line:
                continue
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            if text.startswith("data: "):
                text = text[6:]
            if text == "[DONE]":
                break
            try:
                chunk = json.loads(text)
            except json.JSONDecodeError:
                continue
            if "error" in chunk:
                print(f"[ERROR del modelo] {chunk.get('message', chunk['error'])}", flush=True)
                continue
            partes.append(_contenido_de_chunk(chunk))
            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                info.razonamiento += len(delta.get("reasoning_content") or delta.get("reasoning") or "")
                info.fin = choices[0].get("finish_reason") or info.fin
            now = time.time()
            if now - last >= 60:
                print(f"  [{int(now - t0)}s] {len(''.join(partes))} chars...", flush=True)
                last = now
    except requests.exceptions.Timeout as e:
        # Si ya llegaron tokens se devuelve lo parcial en vez de perder todo.
        if not partes:
            raise ErrorLLM(
                f"El modelo '{perfil.modelo}' aceptó la conexión pero no envió ningún token en "
                f"{_stream_read_timeout()}s. Suele pasar con modelos ':free' saturados: probá otro modelo."
            ) from e
        print("  [AVISO] El stream se cortó por inactividad. Se devuelve lo generado hasta acá.", flush=True)
    info.texto = "".join(partes)
    extra = f", {info.razonamiento} chars de razonamiento descartados" if info.razonamiento else ""
    print(f"  Generación completa en {int(time.time() - t0)}s ({len(info.texto)} chars{extra})", flush=True)
    return info


def completar(
    system: str,
    user: str,
    *,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    stream: bool = False,
) -> str:
    """Envía un system + user prompt al proveedor activo y devuelve el texto.

    stream=True es para generaciones largas: agrega heartbeat y corta si el
    proveedor queda mudo STREAM_READ_TIMEOUT segundos, pero la interfaz es la
    misma (devuelve el texto completo).

    Raises:
        ErrorLLM con un mensaje accionable (rate limit, modelo dado de baja,
        proveedor mudo, HTTP inesperado).
    """
    perfil = _perfil_chat()
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": user})
    payload = {
        "model": perfil.modelo,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
        **perfil.extra_payload,
    }

    if not stream:
        try:
            resp = _post_chat(perfil, payload, timeout=120, stream=False)
        except requests.exceptions.RequestException as e:
            raise ErrorLLM(f"No se pudo contactar a {perfil.nombre}: {e}") from e
        _levantar_si_falla(perfil, resp)
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    info = _completar_stream(perfil, payload)
    if info.texto.strip() or not info.razonamiento:
        return info.texto
    # Solo razonó: agotó los tokens pensando y no escribió. Un intento con el
    # modelo de respaldo antes de rendirse.
    if perfil.modelo_fallback and perfil.modelo_fallback != payload["model"]:
        print(f"[FALLBACK] '{payload['model']}' solo razonó ({info.razonamiento} chars, fin={info.fin}) "
              f"-> probando {perfil.modelo_fallback}", flush=True)
        info = _completar_stream(perfil, {**payload, "model": perfil.modelo_fallback})
        if info.texto.strip() or not info.razonamiento:
            return info.texto
    raise ErrorLLM(
        f"El modelo '{payload['model']}' gastó todo el presupuesto ({max_tokens} tokens) razonando y no "
        f"escribió la nota. Probá con otro modelo o subí max_tokens para este proveedor."
    )


def _completar_stream(perfil: Perfil, payload: dict) -> _Stream:
    stop = threading.Event()
    threading.Thread(target=_heartbeat, args=(f"esperando respuesta de {payload['model']}...", stop), daemon=True).start()
    try:
        resp = _post_chat(perfil, payload, timeout=(15, _stream_read_timeout()), stream=True)
    except requests.exceptions.Timeout as e:
        raise ErrorLLM(
            f"El proveedor no respondió en {_stream_read_timeout()}s usando el modelo '{perfil.modelo}'. "
            f"Probá con otro modelo o subí STREAM_READ_TIMEOUT."
        ) from e
    except requests.exceptions.RequestException as e:
        raise ErrorLLM(f"No se pudo contactar a {perfil.nombre}: {e}") from e
    finally:
        stop.set()
    _levantar_si_falla(perfil, resp)
    return _leer_stream(perfil, resp)


# ── Embeddings ────────────────────────────────────────────────────────────────


def _post_emb(perfil: Perfil, entrada, tipo: str, timeout: int) -> requests.Response:
    payload = {"model": perfil.modelo_emb, "input": entrada}
    if perfil.emb_input_type:
        payload["input_type"] = tipo
    return _transporte["post"](
        f"{perfil.base_url}/embeddings", json=payload, headers=perfil.headers, timeout=timeout, stream=False
    )


def _embeber_uno(perfil: Perfil, texto: str, tipo: str) -> list[float] | None:
    esperas = [0.5, 1, 2, 3, 3]
    for intento, espera in enumerate(esperas):
        try:
            resp = _post_emb(perfil, texto, tipo, timeout=30)
            if resp.status_code in _MODELO_CAIDO:
                print("[ERROR] " + _error_modelo_caido(perfil, perfil.modelo_emb, resp.status_code,
                                                       "NVIDIA_EMB_MODEL"), flush=True)
                return None
            # NVIDIA a veces devuelve 400 en vez de 429 para rate limit.
            if resp.status_code in (400, 429):
                _dormir(espera)
                continue
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except requests.exceptions.ConnectionError:
            return None                  # servidor inexistente: reintentar no lo levanta
        except Exception as e:
            if intento < len(esperas) - 1:
                _dormir(espera)
                continue
            print(f"[AVISO] No se pudo calcular embedding tras {len(esperas)} intentos: {e}", flush=True)
    return None


def embeber(textos: list[str], tipo: str = "passage") -> list[list[float] | None]:
    """Vectoriza textos en una sola llamada; si el batch falla, uno por uno.

    Args:
        tipo: "passage" (contenido) o "query" (búsqueda). Solo aplica a NVIDIA.

    Returns:
        Un vector (o None si falló) por cada texto, en el mismo orden.
        Textos vacíos devuelven None sin llamar al proveedor.
    """
    perfil = _perfil_emb()
    limpios = [(t or "").strip()[: perfil.emb_max_chars] for t in textos]
    resultado: list[list[float] | None] = [None] * len(limpios)
    indices = [i for i, t in enumerate(limpios) if t]
    if not indices:
        return resultado

    entrada = [limpios[i] for i in indices]
    for espera in (1, 2, 4):
        try:
            resp = _post_emb(perfil, entrada, tipo, timeout=60)
        except requests.exceptions.ConnectionError as e:
            # Conexión rechazada (p. ej. LM Studio en localhost dentro de Render):
            # reintentar 3 + 5 veces solo sumaba ~14 s por llamada.
            print(f"  [AVISO] El servidor de embeddings de '{perfil.nombre}' no responde ({perfil.base_url}): "
                  f"se sigue sin embeddings. Configurá EMBEDDINGS_PROVIDER=nvidia. Detalle: {e}", flush=True)
            return resultado
        except Exception as e:
            print(f"  [AVISO] Batch embedding falló: {e}", flush=True)
            _dormir(espera)
            continue
        try:
            if resp.status_code in _MODELO_CAIDO:
                # Caer al uno-por-uno fallaría igual N veces seguidas.
                print("[ERROR] " + _error_modelo_caido(perfil, perfil.modelo_emb, resp.status_code,
                                                       "NVIDIA_EMB_MODEL"), flush=True)
                return resultado
            if resp.status_code in (400, 429):
                print(f"  [AVISO] Embedding batch rate-limited ({resp.status_code}), retry en {espera}s...", flush=True)
                _dormir(espera)
                continue
            resp.raise_for_status()
            data = sorted(resp.json().get("data", []), key=lambda d: d.get("index", 0))
            for i, d in zip(indices, data, strict=False):
                resultado[i] = d["embedding"]
            return resultado
        except Exception as e:
            print(f"  [AVISO] Batch embedding falló: {e}", flush=True)
            _dormir(espera)

    print("  [AVISO] Usando fallback uno por uno.", flush=True)
    for i in indices:
        resultado[i] = _embeber_uno(perfil, limpios[i], tipo)
    return resultado
