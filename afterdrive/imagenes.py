"""
imagenes.py — Imagen destacada de una Nota, generada con NVIDIA (build.nvidia.com).

Interfaz:
    configurado() -> bool
    describir(plan, categorias, pedido="") -> str        prompt de la imagen (sin IA)
    generar(prompt) -> (bytes, mime)                      llama a NVIDIA; ErrorImagen si falla
    guardar(contenido, mime, prompt, base=None) -> id     colección `imagenes`
    leer(id, base=None) -> (bytes, mime) | None
    borrar(id, base=None)
    para_nota(plan, categorias, titulo, pedido="", base=None) -> dict   todo junto: {"url", "alt", "generada"}
    ErrorImagen

Siempre el mismo modelo (NVIDIA_IMAGE_MODEL, FLUX.1-dev por defecto), sin
importar qué proveedor redacta: la imagen va por NVIDIA aunque el texto vaya
por la API paga. Solo hace falta NVIDIA_API_KEY.

Las imágenes quedan en Mongo y el dashboard las muestra desde
/api/imagenes/<id>. HubSpot necesita una URL pública: al enviar la nota, la
imagen se sube a su gestor de archivos (hubspot.subir_imagen) y desde ahí
queda la URL.

El prompt sale sin IA: la escena que propuso el plan (en inglés) o, si no hay,
una genérica por categoría. Siempre pide una foto editorial genérica, sin
texto, sin logos y sin modelos de autos puntuales: los modelos de imagen
inventan detalles y una pieza o un vehículo "parecido" se nota en un medio
del sector.
"""

from __future__ import annotations

import base64
import datetime
import os
import time

import requests

URL_BASE = "https://ai.api.nvidia.com/v1/genai"
# Si la imagen tarda, NVIDIA responde 202 con un id (header NVCF-REQID) y hay
# que consultar este endpoint hasta que esté lista.
URL_ESTADO = "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/{}"
ESPERA_S = 2
MODELO_DEFAULT = "black-forest-labs/flux.1-dev"
TAMANO_DEFAULT = "1344x768"   # apaisada, para el encabezado del blog
# NVIDIA sostiene la conexión hasta tener la imagen; con su cola cargada eso
# pasaba el timeout de lectura. Con NVCF-POLL-SECONDS contesta 202 a los
# POLL_NVIDIA_S y se consulta el estado hasta ESPERA_TOTAL_S.
POLL_NVIDIA_S = 20
TIMEOUT_S = (10, 180)   # (conexión, lectura): holgado por si NVIDIA ignora el header y sostiene la conexión
ESPERA_TOTAL_S = 300

_transporte = {"post": requests.post, "get": requests.get}   # seam para los tests
_dormir = time.sleep

_ESTILO = ("Editorial photograph for a B2B automotive aftermarket industry blog. Realistic, natural light, "
           "professional, clean composition, shallow depth of field. No text, no letters, no numbers, no logos, "
           "no brand names, no watermarks.")

# Escena genérica por categoría, cuando el plan no propuso una.
_ESCENAS = {
    "autopartes": "neatly organized shelves of new automotive spare parts in a distributor warehouse",
    "marketplaces": "a laptop showing an online auto parts catalog on a parts store counter",
    "logistica": "boxes of auto parts being prepared for shipping in a logistics warehouse",
    "talleres": "a mechanic working on a car in a modern independent repair workshop",
    "neumaticos": "rows of new tires stacked in a tire shop",
    "frenos": "close-up of new brake discs and pads on a workbench",
}
_ESCENA_GENERICA = "the counter of a modern auto parts store with shelves of spare parts in the background"


class ErrorImagen(RuntimeError):
    """Fallo al generar la imagen, con un mensaje apto para el usuario."""


def configurado() -> bool:
    return bool(os.getenv("NVIDIA_API_KEY"))


def automaticas() -> bool:
    """Una imagen con cada nota nueva. IMAGENES_AUTOMATICAS=0 las apaga."""
    return configurado() and os.getenv("IMAGENES_AUTOMATICAS", "1").strip() != "0"


def modelo() -> str:
    return os.getenv("NVIDIA_IMAGE_MODEL", "").strip() or MODELO_DEFAULT


def _tamano() -> tuple[int, int]:
    try:
        ancho, alto = (int(x) for x in os.getenv("NVIDIA_IMAGE_SIZE", TAMANO_DEFAULT).lower().split("x"))
        return ancho, alto
    except ValueError:
        return 1344, 768


def describir(plan: dict | None, categorias: list[str] | None = None, pedido: str = "") -> str:
    """Prompt de la imagen. `pedido` (lo que escribió una persona) manda sobre el plan."""
    escena = " ".join((pedido or "").split()) or " ".join(((plan or {}).get("imagen") or "").split())
    if not escena:
        escena = next((_ESCENAS[c] for c in categorias or [] if c in _ESCENAS), _ESCENA_GENERICA)
    return f"{escena.rstrip('.')}. {_ESTILO}"[:1500]


def _payload(prompt: str, ancho: int, alto: int) -> dict:
    cuerpo = {"prompt": prompt, "width": ancho, "height": alto, "seed": 0}
    if "schnell" in modelo():
        cuerpo["steps"] = 4                     # schnell: pocos pasos y sin cfg
    else:
        cuerpo.update(mode="base", cfg_scale=3.5, steps=30)
    return cuerpo


def _imagen_de(data: dict) -> str:
    """Base64 de la imagen en las formas que devuelve la API de NVIDIA."""
    artefactos = data.get("artifacts") or []
    if artefactos:
        a = artefactos[0]
        if a.get("finishReason") not in (None, "SUCCESS"):
            raise ErrorImagen(f"NVIDIA no devolvió la imagen ({a.get('finishReason')}): probá con otra descripción.")
        return a.get("base64") or ""
    datos = data.get("data") or []
    if datos:
        return datos[0].get("b64_json") or ""
    return data.get("image") or ""


def _mime(contenido: bytes) -> str:
    if contenido.startswith(b"\x89PNG"):
        return "image/png"
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _esperar(resp, headers: dict):
    """Mientras NVIDIA responda 202 (en proceso), consulta el estado hasta que termine."""
    limite = time.monotonic() + ESPERA_TOTAL_S
    while resp.status_code == 202:
        req_id = (getattr(resp, "headers", None) or {}).get("NVCF-REQID") or \
            (getattr(resp, "headers", None) or {}).get("nvcf-reqid")
        if not req_id:
            raise ErrorImagen("NVIDIA dejó la imagen en proceso sin decir cómo consultarla (falta NVCF-REQID).")
        if time.monotonic() > limite:
            raise ErrorImagen(f"NVIDIA no terminó la imagen en {ESPERA_TOTAL_S // 60} minutos: probá de nuevo más tarde.")
        _dormir(ESPERA_S)
        try:
            resp = _transporte["get"](URL_ESTADO.format(req_id), headers=headers, timeout=TIMEOUT_S)
        except requests.Timeout:
            continue   # se vuelve a consultar hasta el límite
        except requests.RequestException as e:
            raise ErrorImagen(f"No se pudo consultar el estado de la imagen en NVIDIA: {e}") from e
    return resp


def generar(prompt: str) -> tuple[bytes, str]:
    """(bytes, mime) de la imagen. Si el tamaño apaisado no se acepta, reintenta cuadrada."""
    if not configurado():
        raise ErrorImagen("Falta NVIDIA_API_KEY: las imágenes se generan con NVIDIA (build.nvidia.com).")
    headers = {"Authorization": f"Bearer {os.getenv('NVIDIA_API_KEY')}", "Accept": "application/json",
               "NVCF-POLL-SECONDS": str(POLL_NVIDIA_S)}
    url = f"{URL_BASE}/{modelo()}"
    ancho, alto = _tamano()
    for intento_ancho, intento_alto in ((ancho, alto), (1024, 1024)):
        try:
            resp = _transporte["post"](url, json=_payload(prompt, intento_ancho, intento_alto), headers=headers,
                                       timeout=TIMEOUT_S)
        except requests.Timeout as e:
            raise ErrorImagen("NVIDIA tardó demasiado en responder (suele ser que está saturado): "
                              "probá de nuevo en unos minutos.") from e
        except requests.RequestException as e:
            raise ErrorImagen(f"No se pudo contactar a NVIDIA para la imagen: {e}") from e
        resp = _esperar(resp, headers)
        if resp.status_code in (400, 422) and (intento_ancho, intento_alto) != (1024, 1024):
            continue   # el modelo no acepta ese tamaño
        if resp.status_code == 429:
            raise ErrorImagen("NVIDIA está limitando las llamadas (429): probá de nuevo en un minuto.")
        if resp.status_code in (401, 403):
            raise ErrorImagen("NVIDIA rechazó la key para generar imágenes: revisá NVIDIA_API_KEY.")
        if resp.status_code == 404:
            raise ErrorImagen(f"NVIDIA no encontró el modelo de imagen '{modelo()}': revisá NVIDIA_IMAGE_MODEL.")
        if resp.status_code >= 400:
            raise ErrorImagen(f"NVIDIA respondió {resp.status_code} al generar la imagen: {resp.text[:300]}")
        try:
            contenido = base64.b64decode(_imagen_de(resp.json()))
        except ErrorImagen:
            raise
        except Exception as e:
            raise ErrorImagen(f"NVIDIA respondió algo que no es una imagen: {e}") from e
        if not contenido:
            raise ErrorImagen("NVIDIA respondió sin imagen.")
        return contenido, _mime(contenido)
    raise ErrorImagen("NVIDIA no aceptó el tamaño de imagen pedido.")


# ── Guardado ──────────────────────────────────────────────────────────────────


def _col(base):
    from afterdrive import db
    return (base if base is not None else db.db)["imagenes"]


def guardar(contenido: bytes, mime: str, prompt: str, base=None) -> str:
    from bson import Binary
    r = _col(base).insert_one({
        "contenido": Binary(contenido), "mime": mime, "prompt": prompt, "modelo": modelo(),
        "creada": datetime.datetime.now(datetime.UTC).isoformat(),
    })
    return str(r.inserted_id)


def _oid(imagen_id: str):
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        return ObjectId(imagen_id)
    except (InvalidId, TypeError):
        return None


def leer(imagen_id: str, base=None) -> tuple[bytes, str] | None:
    oid = _oid(imagen_id)
    doc = _col(base).find_one({"_id": oid}) if oid else None
    return (bytes(doc["contenido"]), doc.get("mime", "image/jpeg")) if doc else None


def borrar(imagen_id: str | None, base=None) -> None:
    oid = _oid(imagen_id) if imagen_id else None
    if oid:
        _col(base).delete_one({"_id": oid})


def para_nota(plan: dict | None, categorias: list[str] | None, titulo: str, pedido: str = "",
              base=None) -> dict:
    """Genera y guarda la imagen; devuelve el campo `imagen` de la nota. Lanza ErrorImagen."""
    prompt = describir(plan, categorias, pedido)
    contenido, mime = generar(prompt)
    imagen_id = guardar(contenido, mime, prompt, base=base)
    return {"url": "", "alt": titulo, "generada": {"id": imagen_id, "prompt": prompt, "modelo": modelo()}}
