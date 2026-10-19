"""
llm.py — Módulo LLM: el único lugar que sabe hablar con un proveedor de IA.

Interfaz:
    completar(system, user, temperature=..., max_tokens=..., stream=False, tarea="") -> str
    embeber(textos, tipo="passage") -> list[vector | None]
    modelo_embeddings() -> str
    usa_api_paga() -> bool
    proveedor_activo() / proveedor_base() -> str
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
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from afterdrive.ia import consumo, modo_pago

load_dotenv()

PROVEEDORES = ("local", "nvidia", "openrouter", "paga")

# Tareas del pipeline que llaman al chat. Solo la API paga las separa en
# modelos distintos (PAGA_MODEL_<TAREA>); el resto usa un modelo para todo.
TAREAS = ("clasificacion", "redaccion", "evaluacion")


def paga_configurada(*extra: str) -> bool:
    """True si la API paga tiene key, URL y las variables extra pedidas (p. ej. PAGA_MODEL)."""
    return all(os.getenv(v) for v in ("PAGA_API_KEY", "PAGA_BASE_URL", *extra))

# Códigos que significan "este modelo ya no existe": reintentar no lo revive.
# 404 = nunca existió con ese id; 410 = fue dado de baja por el proveedor.
_MODELO_CAIDO = (404, 410)


class ErrorLLM(RuntimeError):
    """Fallo del proveedor con un mensaje accionable para el usuario."""


class Cancelada(ErrorLLM):
    """La Corrida se canceló desde el dashboard.

    Se corta antes de la próxima llamada o, en una respuesta por streaming, en
    el próximo fragmento. Una llamada sin streaming (Bedrock Converse) no se
    puede interrumpir: se corta cuando vuelve.
    """


def _nunca() -> bool:
    return False


_cancelada: Callable[[], bool] = _nunca


def al_cancelar(consulta: Callable[[], bool]) -> None:
    """Registra la función que dice si la Corrida en curso se canceló (la conecta cola.py)."""
    global _cancelada
    _cancelada = consulta


def verificar_cancelacion() -> None:
    if _cancelada():
        raise Cancelada("Cancelada desde el dashboard.")


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
    modelos_tarea: dict = field(default_factory=dict)  # tarea -> modelo (solo API paga)
    campo_max_tokens: str = "max_tokens"  # OpenAI pide max_completion_tokens
    enviar_temperatura: bool = True       # los modelos que razonan de OpenAI pueden rechazarla
    api: str = "chat"                     # "chat" (/chat/completions) o "converse" (Bedrock)
    tarea: str = ""                       # tarea de la llamada en curso: precio en el registro de consumo
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
    if nombre == "paga" and paga_configurada():
        # API paga: el proveedor concreto se elige solo con variables de entorno.
        # Sin defaults de URL/modelo a propósito. PAGA_API=converse para Bedrock
        # (application inference profiles: Chat Completions los rechaza).
        return Perfil(
            nombre="paga",
            base_url=env("PAGA_BASE_URL", ""),
            api_key=env("PAGA_API_KEY", ""),
            modelo=env("PAGA_MODEL", ""),
            modelo_fallback=env("PAGA_FALLBACK_MODEL", ""),
            variable_modelo="PAGA_MODEL",
            modelo_emb=env("PAGA_EMB_MODEL", ""),
            # Un modelo por tarea; la que no tenga variable usa PAGA_MODEL.
            modelos_tarea={t: env(f"PAGA_MODEL_{t.upper()}") for t in TAREAS if env(f"PAGA_MODEL_{t.upper()}")},
            # ponytail: sin probar contra la API real. Si OpenAI rechaza un
            # parámetro, se corrige desde estas variables sin tocar código.
            campo_max_tokens=env("PAGA_CAMPO_MAX_TOKENS", "max_completion_tokens"),
            enviar_temperatura=env("PAGA_TEMPERATURA", "1") != "0",
            api="converse" if env("PAGA_API", "").strip().lower() == "converse" else "chat",
            # Los modelos de OpenAI que razonan descuentan el razonamiento de este
            # presupuesto: con 4000 pueden agotarlo y no escribir (como kimi-k3).
            redaccion=Redaccion(max_tokens=16000),
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


def proveedor_base() -> str:
    """El proveedor elegido en la vista Desarrollador (o por AI_PROVIDER)."""
    return os.getenv("AI_PROVIDER", "local")


def proveedor_activo() -> str:
    """El proveedor que usa el pipeline ahora: el modo pago, mientras dure, manda sobre el base."""
    if modo_pago.vigente() and paga_configurada("PAGA_MODEL"):
        return "paga"
    return proveedor_base()


def _perfil_chat() -> Perfil:
    nombre = proveedor_activo()
    if nombre == "paga" and not paga_configurada("PAGA_MODEL"):
        nombre = "local"  # mismo criterio que un proveedor cloud sin key
    elif nombre == "paga" and (motivo := consumo.motivo_tope()):
        # Tope mensual de la API paga: se sigue con NVIDIA (o local sin su key).
        print(f"[CONSUMO] API paga en pausa: {motivo}. Se usa NVIDIA.", flush=True)
        nombre = "nvidia"
    return _perfil(nombre)


def usa_api_paga() -> bool:
    """True si el chat va hoy por la API paga (activa, configurada y bajo el tope)."""
    return _perfil_chat().nombre == "paga"


def _perfil_emb() -> Perfil:
    """Perfil para embeddings, independiente del de chat.

    EMBEDDINGS_PROVIDER manda si está definido. OpenRouter no sirve embeddings,
    así que si terminara elegido se cae a LM Studio: es preferible fallar contra
    un endpoint local que mandar la request a un proveedor que devuelve 404.
    """
    explicito = os.getenv("EMBEDDINGS_PROVIDER", "").strip().lower()
    nombre = explicito or proveedor_activo()
    # La API paga vectoriza solo si se la pide explícitamente: elegirla para el
    # chat desde el dashboard no debe cambiar el modelo de los vectores guardados.
    paga_emb = (explicito == "paga" and paga_configurada("PAGA_EMB_MODEL")
                and os.getenv("PAGA_API", "").strip().lower() != "converse"  # Converse no hace embeddings
                and consumo.motivo_tope() is None)
    if nombre == "openrouter" or (nombre == "paga" and not paga_emb):
        # OpenRouter no tiene /embeddings. NVIDIA si hay key; si no, LM Studio.
        nombre = "nvidia" if os.getenv("NVIDIA_API_KEY") else "local"
    return _perfil(nombre)


def modelo_embeddings() -> str:
    """Id del modelo que produce los vectores hoy ("proveedor/modelo").

    Se guarda junto a cada embedding: vectores de modelos distintos no se
    pueden comparar, aunque tengan el mismo largo.
    """
    p = _perfil_emb()
    return f"{p.nombre}/{p.modelo_emb}"


def _variable_emb(perfil: Perfil) -> str:
    return "LMSTUDIO_EMB_MODEL" if perfil.nombre == "local" else f"{perfil.nombre.upper()}_EMB_MODEL"


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

# proveedor -> (responde, cuándo se chequeó). El resultado vence: un "no
# responde" cacheado para siempre dejaba el clasificador en modo degradado
# (aprobando todo) hasta reiniciar el servidor, que en Render vive días.
_disponible_cache: dict[str, tuple[bool, float]] = {}
VIGENCIA_OK_S = 600       # si respondió, no se vuelve a preguntar por 10 min
VIGENCIA_CAIDO_S = 60     # si no respondió, se reintenta al minuto
_reloj = time.monotonic   # seam para los tests


def disponible() -> bool:
    """True si el proveedor activo responde. El resultado se cachea un rato."""
    perfil = _perfil_chat()
    cache = _disponible_cache.get(perfil.nombre)
    if cache is not None:
        ok, cuando = cache
        if _reloj() - cuando < (VIGENCIA_OK_S if ok else VIGENCIA_CAIDO_S):
            return ok
    try:
        _transporte["get"](f"{perfil.base_url}/models", headers=perfil.headers, timeout=5)
        ok = True
    except Exception:
        ok = False
        print(f"[AVISO] Proveedor '{perfil.nombre}' ({perfil.base_url}) no disponible.", flush=True)
    _disponible_cache[perfil.nombre] = (ok, _reloj())
    return ok


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
        "provider_base": proveedor_base(),
        **modo_pago.estado(),
        "local_available": local,
        "nvidia_available": bool(os.getenv("NVIDIA_API_KEY")),
        "openrouter_available": bool(os.getenv("OPENROUTER_API_KEY")),
        "paga_available": paga_configurada("PAGA_MODEL"),
        **_estado_consumo(),
        "model": chat.modelo,
        "emb_model": emb.modelo_emb,
        "emb_provider": emb.nombre,
    }


def _estado_consumo() -> dict:
    # Con la API paga configurada aunque no esté en uso: el aviso del modo pago
    # muestra cuánto se gastó en el mes antes de prenderlo.
    if not paga_configurada("PAGA_MODEL"):
        return {}
    motivo = consumo.motivo_tope()
    return {"paga_gastado_mes_usd": round(consumo.gastado_mes(), 4), "paga_tope_usd": consumo.tope(),
            "paga_tope_alcanzado": motivo is not None, "paga_motivo_pausa": motivo or ""}


def set_proveedor(nombre: str) -> dict:
    """Cambia el proveedor de chat en runtime (y para los subprocesos)."""
    if nombre not in PROVEEDORES:
        return {"success": False, "error": "Proveedor inválido. Usá 'local', 'nvidia', 'openrouter' o 'paga'."}
    if nombre == "nvidia" and not os.getenv("NVIDIA_API_KEY"):
        return {"success": False, "error": "No hay API key de NVIDIA configurada."}
    if nombre == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        return {"success": False, "error": "No hay API key de OpenRouter configurada."}
    if nombre == "paga" and not paga_configurada("PAGA_MODEL"):
        return {"success": False, "error": "La API paga necesita PAGA_API_KEY, PAGA_BASE_URL y PAGA_MODEL."}
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
    if perfil.api == "converse":  # Bedrock runtime no tiene catálogo en /models
        return (f"El modelo '{modelo}' devolvió HTTP {status}: no existe o no está disponible en esa región. "
                f"Revisá {variable}.")
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


def _post_chat(perfil: Perfil, payload: dict, *, timeout, stream: bool,
               reintentos: int = 5) -> tuple[requests.Response, str]:
    """POST a /chat/completions con fallback de modelo y backoff para 429 (ver _con_respaldo)."""
    url = f"{perfil.base_url}/chat/completions"

    def enviar(modelo: str) -> requests.Response:
        return _transporte["post"](url, json={**payload, "model": modelo}, headers=perfil.headers,
                                   timeout=timeout, stream=stream)

    return _con_respaldo(perfil, payload["model"], enviar, reintentos)


def _con_respaldo(perfil: Perfil, modelo: str, enviar, reintentos: int = 5) -> tuple[requests.Response, str]:
    """Envía con `enviar(modelo)`, con fallback de modelo y backoff para 429.

    Devuelve (respuesta, modelo que contestó): el costo depende de cuál fue.

    - 404/410 (modelo dado de baja): se prueba el fallback una vez; reintentar
      el mismo modelo es inútil.
    - 429: en el primer intento se prueba el fallback; después, backoff.
    """
    fallback = perfil.modelo_fallback if perfil.modelo_fallback != modelo else ""

    def _probar_fallback(motivo: str):
        print(f"[FALLBACK] '{modelo}' {motivo} -> probando {fallback}", flush=True)
        return enviar(fallback)

    resp = None
    for intento in range(reintentos):
        resp = enviar(modelo)
        if resp.status_code in _MODELO_CAIDO:
            if fallback:
                resp_fb = _probar_fallback(f"devolvió {resp.status_code} (modelo dado de baja)")
                if resp_fb.status_code == 200:
                    return resp_fb, fallback
            return resp, modelo
        if resp.status_code != 429:
            return resp, modelo
        if intento == 0 and fallback:
            resp_fb = _probar_fallback("rate-limited (429)")
            if resp_fb.status_code == 200:
                return resp_fb, fallback
        espera = min(5 * (2**intento), 60)
        print(f"[RETRY] 429 - esperando {espera}s (intento {intento + 1}/{reintentos})", flush=True)
        _dormir(espera)
    return resp, modelo


def _levantar_si_falla(perfil: Perfil, resp: requests.Response) -> None:
    if resp.ok:
        return
    if resp.status_code == 429:
        cuota = " (ThrottlingException: revisá la cuota del perfil en Bedrock)" if perfil.api == "converse" else ""
        raise ErrorLLM(f"Rate limit de {perfil.nombre} (429){cuota}. Esperá unos minutos y reintentá.")
    if resp.status_code in _MODELO_CAIDO:
        raise ErrorLLM(_error_modelo_caido(perfil, perfil.modelo, resp.status_code, perfil.variable_modelo))
    if resp.status_code in (401, 403):
        raise ErrorLLM(f"{perfil.nombre} rechazó la key para el modelo '{perfil.modelo}' (HTTP {resp.status_code}): "
                       f"revisá la key y {perfil.variable_modelo}. Detalle: {resp.text[:500]}")
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
    uso: dict = field(default_factory=dict)  # "usage" del último chunk (stream_options.include_usage)


def _leer_stream(perfil: Perfil, resp: requests.Response) -> _Stream:
    partes: list[str] = []
    info = _Stream()
    t0 = last = time.time()
    try:
        for line in resp.iter_lines():
            verificar_cancelacion()
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
            info.uso = chunk.get("usage") or info.uso
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
    tarea: str = "",
) -> str:
    """Envía un system + user prompt al proveedor activo y devuelve el texto.

    tarea ("clasificacion", "redaccion", "evaluacion") elige el modelo cuando
    el proveedor separa modelos por tarea (API paga); si no, se ignora.

    stream=True es para generaciones largas: agrega heartbeat y corta si el
    proveedor queda mudo STREAM_READ_TIMEOUT segundos, pero la interfaz es la
    misma (devuelve el texto completo).

    Raises:
        ErrorLLM con un mensaje accionable (rate limit, modelo dado de baja,
        proveedor mudo, HTTP inesperado).
    """
    verificar_cancelacion()
    perfil = replace(_perfil_chat(), tarea=tarea)
    if perfil.modelos_tarea.get(tarea):
        perfil = replace(perfil, modelo=perfil.modelos_tarea[tarea], variable_modelo=f"PAGA_MODEL_{tarea.upper()}")
    if perfil.api == "converse":
        return _completar_converse(perfil, system, user, max_tokens=max_tokens, stream=stream)
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": user})
    payload = {
        "model": perfil.modelo,
        "messages": messages,
        perfil.campo_max_tokens: max_tokens,
        "stream": stream,
        **perfil.extra_payload,
    }
    if perfil.enviar_temperatura:
        payload["temperature"] = temperature
    if perfil.nombre == "paga" and stream:
        payload["stream_options"] = {"include_usage": True}  # tokens para el registro de consumo

    if not stream:
        try:
            resp, modelo = _post_chat(perfil, payload, timeout=120, stream=False)
        except requests.exceptions.Timeout as e:
            _registrar_estimado(perfil, payload["model"], system + user, max_tokens)
            raise ErrorLLM(f"{perfil.nombre} no respondió a tiempo: {e}") from e
        except requests.exceptions.RequestException as e:
            raise ErrorLLM(f"No se pudo contactar a {perfil.nombre}: {e}") from e
        _levantar_si_falla(perfil, resp)
        data = resp.json()
        choices = data.get("choices") or [{}]
        contenido = (choices[0].get("message") or {}).get("content") or ""
        _registrar_uso(perfil, modelo, data.get("usage") or {}, entrada=system + user, salida=contenido)
        if not data.get("choices"):
            raise ErrorLLM(f"{perfil.nombre} respondió sin 'choices': {resp.text[:500]}")
        return contenido.strip()

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
        resp, modelo = _post_chat(perfil, payload, timeout=(15, _stream_read_timeout()), stream=True)
    except requests.exceptions.Timeout as e:
        _registrar_estimado(perfil, payload["model"], json.dumps(payload["messages"]), payload.get(perfil.campo_max_tokens, 0))
        raise ErrorLLM(
            f"El proveedor no respondió en {_stream_read_timeout()}s usando el modelo '{perfil.modelo}'. "
            f"Probá con otro modelo o subí STREAM_READ_TIMEOUT."
        ) from e
    except requests.exceptions.RequestException as e:
        raise ErrorLLM(f"No se pudo contactar a {perfil.nombre}: {e}") from e
    finally:
        stop.set()
    _levantar_si_falla(perfil, resp)
    try:
        info = _leer_stream(perfil, resp)
    except ErrorLLM:
        # Aceptó y no mandó nada: pudo haber razonado (y cobrado) sin transmitirlo.
        _registrar_estimado(perfil, modelo, json.dumps(payload["messages"]), payload.get(perfil.campo_max_tokens, 0))
        raise
    # Sin usage (stream cortado) se estima con lo que llegó: texto y razonamiento.
    _registrar_uso(perfil, modelo, info.uso, entrada=json.dumps(payload["messages"]),
                   salida=info.texto, chars_razonamiento=info.razonamiento)
    return info


def _tokens_estimados(chars: int) -> int:
    # ~4 caracteres por token en español; se divide por 3 para estimar por lo alto.
    return chars // 3 + 1


def _registrar_uso(perfil: Perfil, modelo: str, uso: dict, *, entrada: str = "", salida: str = "",
                   chars_razonamiento: int = 0) -> None:
    """Suma la llamada al registro de consumo (solo API paga).

    Sin tokens informados se registra una estimación por lo alto: una llamada
    paga nunca queda fuera del tope.
    """
    if perfil.nombre != "paga":
        return
    t_entrada = uso.get("prompt_tokens", uso.get("inputTokens", 0)) or 0
    t_salida = uso.get("completion_tokens", uso.get("outputTokens", 0)) or 0
    if t_entrada or t_salida:
        # Bedrock informó inputTokens=2 con prompts de ~1100 tokens: la entrada
        # cacheada se informa aparte (o solo en totalTokens). Se cuenta lo más
        # alto entre lo informado, total - salida y un piso por caracteres, todo
        # al precio de entrada completo (el cache suele ser más barato: sobreestima).
        cache = (uso.get("cacheReadInputTokens") or 0) + (uso.get("cacheWriteInputTokens") or 0)
        total = uso.get("totalTokens", uso.get("total_tokens")) or 0
        piso = len(entrada) // 4
        contada = max(t_entrada + cache, total - t_salida if total else 0, piso)
        if contada != t_entrada:
            crudo = {k: v for k, v in uso.items() if isinstance(v, int | float)}
            print(f"  [CONSUMO] usage informado {crudo}: se cuentan {contada} tokens de entrada.", flush=True)
        consumo.registrar(perfil.tarea, modelo, int(contada), int(t_salida))
        return
    print(f"  [CONSUMO] '{modelo}' no informó tokens: se registra una estimación.", flush=True)
    consumo.registrar(perfil.tarea, modelo, _tokens_estimados(len(entrada)),
                      _tokens_estimados(len(salida) + chars_razonamiento), estimado=True)


def _registrar_estimado(perfil: Perfil, modelo: str, entrada: str, max_tokens: int) -> None:
    """Llamada cortada por timeout: el proveedor puede cobrarla entera, se cuenta el máximo.

    El corte pudo pasar en el modelo de respaldo: se valúa con el más caro de los dos.
    """
    if perfil.nombre != "paga":
        return
    candidatos = [m for m in (modelo, perfil.modelo_fallback) if m]
    modelo = max(candidatos, key=lambda m: consumo.precio_de_modelo(m)[1])
    consumo.registrar(perfil.tarea, modelo, _tokens_estimados(len(entrada)), int(max_tokens), estimado=True)


# ── Converse (Bedrock) ────────────────────────────────────────────────────────


def _converse_timeout() -> int:
    # Converse sin streaming entrega todo al final: un modelo que razona con
    # 16000 tokens puede tardar varios minutos.
    return int(os.getenv("CONVERSE_TIMEOUT", "600"))


def _completar_converse(perfil: Perfil, system: str, user: str, *, max_tokens: int, stream: bool) -> str:
    """Una llamada a la API Converse de Bedrock.

    POST {base}/model/{modelo URL-encoded}/converse. El modelo puede ser un ARN
    de application inference profile. No se manda temperature: los Luna
    rechazan el campo entero, aunque valga 0.
    """
    # ponytail: sin streaming (ConverseStream usa el formato binario de AWS, no
    # SSE). Para stream=True se mantiene el heartbeat mientras se espera.
    cuerpo = {
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system:
        cuerpo["system"] = [{"text": system}]

    def enviar(modelo: str) -> requests.Response:
        return _transporte["post"](f"{perfil.base_url}/model/{quote(modelo, safe='')}/converse", json=cuerpo,
                                   headers=perfil.headers, timeout=(15, _converse_timeout()), stream=False)

    stop = threading.Event()
    if stream:
        threading.Thread(target=_heartbeat, args=(f"esperando respuesta de {perfil.variable_modelo}...", stop),
                         daemon=True).start()
    entrada = system + user
    try:
        resp, modelo = _con_respaldo(perfil, perfil.modelo, enviar)
    except requests.exceptions.ConnectTimeout as e:
        raise ErrorLLM(f"No se pudo conectar con Bedrock en {perfil.base_url} (15 s). Revisá PAGA_BASE_URL.") from e
    except requests.exceptions.Timeout as e:
        _registrar_estimado(perfil, perfil.modelo, entrada, max_tokens)
        raise ErrorLLM(f"Bedrock no respondió en {_converse_timeout()}s ({perfil.variable_modelo}). "
                       "Subí CONVERSE_TIMEOUT o probá con otro perfil.") from e
    except requests.exceptions.RequestException as e:
        raise ErrorLLM(f"No se pudo contactar a {perfil.nombre}: {e}") from e
    finally:
        stop.set()
    _levantar_si_falla(perfil, resp)

    data = resp.json()
    bloques = ((data.get("output") or {}).get("message") or {}).get("content") or []
    # Solo los bloques de texto: los de "reasoningContent" son el razonamiento.
    texto = "".join(b["text"] for b in bloques if isinstance(b, dict) and isinstance(b.get("text"), str)).strip()
    razono = any(isinstance(b, dict) and "reasoningContent" in b for b in bloques)
    _registrar_uso(perfil, modelo, data.get("usage") or {}, entrada=entrada, salida=json.dumps(bloques))
    corte = data.get("stopReason")
    if not texto and (razono or corte == "max_tokens"):
        raise ErrorLLM(f"El modelo de {perfil.variable_modelo} razonó y no escribió la respuesta (stopReason={corte}, "
                       f"presupuesto {max_tokens} tokens). Probá con otro perfil o subí max_tokens.")
    if texto and corte == "max_tokens":
        print(f"  [AVISO] La respuesta de {perfil.variable_modelo} se cortó por max_tokens ({max_tokens}): "
              "puede estar incompleta.", flush=True)
    return texto


# ── Embeddings ────────────────────────────────────────────────────────────────


def _post_emb(perfil: Perfil, entrada, tipo: str, timeout: int) -> requests.Response:
    payload = {"model": perfil.modelo_emb, "input": entrada}
    if perfil.emb_input_type:
        payload["input_type"] = tipo
    resp = _transporte["post"](
        f"{perfil.base_url}/embeddings", json=payload, headers=perfil.headers, timeout=timeout, stream=False
    )
    if perfil.nombre == "paga" and resp.status_code == 200:
        try:
            uso = resp.json().get("usage") or {}
        except Exception:
            uso = {}
        _registrar_uso(replace(perfil, tarea="embeddings"), perfil.modelo_emb, uso, entrada=json.dumps(entrada))
    return resp


def _embeber_uno(perfil: Perfil, texto: str, tipo: str) -> list[float] | None:
    esperas = [0.5, 1, 2, 3, 3]
    for intento, espera in enumerate(esperas):
        try:
            resp = _post_emb(perfil, texto, tipo, timeout=30)
            if resp.status_code in _MODELO_CAIDO:
                print("[ERROR] " + _error_modelo_caido(perfil, perfil.modelo_emb, resp.status_code,
                                                       _variable_emb(perfil)), flush=True)
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
                                                       _variable_emb(perfil)), flush=True)
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
