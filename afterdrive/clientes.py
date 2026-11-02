"""
clientes.py — Empresas que las notas pueden nombrar y las que no.

Interfaz:
    slug(nombre) -> str
    normalizar_modo(valor) -> "mencionar" | "no_mencionar" | None
    parsear_lista(texto) -> [{"nombre", "descripcion", "alias"}]   la lista que pasan, una por línea
    no_mencionar(col=None) -> [dict]                               las que ninguna nota puede nombrar
    nombrados(texto, clientes) -> [nombre]                         cuáles aparecen en el texto

Cada cliente de la colección `clientes` tiene un `modo`:
- "mencionar" (o sin el campo, los viejos): se puede elegir en Crear nota para
  que la nota lo use como caso o ejemplo.
- "no_mencionar": ninguna nota lo nombra nunca, aunque aparezca en las
  noticias. Se avisa en el prompt y se revisa el texto después (sin IA): si lo
  nombra, la nota se corrige y no se aprueba sola.

La lista llega como texto, una empresa por línea: "Nombre | descripción |
alias1, alias2". Solo el nombre es obligatorio. Los alias son otras formas de
escribirla (siglas, nombre comercial) y también cuentan como mención.
"""

from __future__ import annotations

import re
import unicodedata

MENCIONAR = "mencionar"
NO_MENCIONAR = "no_mencionar"
MODOS = (MENCIONAR, NO_MENCIONAR)
MAX_LINEAS = 500
MAX_NOMBRE = 120
MAX_DESCRIPCION = 300


def slug(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-")


def normalizar_modo(valor) -> str | None:
    """El modo pedido, "mencionar" si no viene, o None si es inválido."""
    if valor in (None, ""):
        return MENCIONAR
    return valor if valor in MODOS else None


def modo(cliente: dict) -> str:
    return NO_MENCIONAR if cliente.get("modo") == NO_MENCIONAR else MENCIONAR


def parsear_lista(texto: str) -> list[dict]:
    """Una empresa por línea: "Nombre | descripción | alias1, alias2". Sin repetidas (por slug)."""
    vistos, resultado = set(), []
    for linea in (texto or "").splitlines()[:MAX_LINEAS]:
        partes = [p.strip() for p in re.split(r"\s*[|\t]\s*", linea.strip())]
        nombre = partes[0][:MAX_NOMBRE] if partes else ""
        nombre = re.sub(r"^[-*•\d.)\s]+", "", nombre).strip()   # viñetas o numeración de una lista pegada
        if not nombre or not slug(nombre) or slug(nombre) in vistos:
            continue
        vistos.add(slug(nombre))
        alias = [a.strip()[:MAX_NOMBRE] for a in (partes[2] if len(partes) > 2 else "").split(",") if a.strip()]
        resultado.append({"nombre": nombre, "descripcion": (partes[1] if len(partes) > 1 else "")[:MAX_DESCRIPCION],
                          "alias": alias})
    return resultado


def no_mencionar(col=None) -> list[dict]:
    """Los clientes que ninguna nota puede nombrar. Si Mongo falla, ninguno (y se avisa)."""
    if col is None:
        from afterdrive.db import col_clientes as col
    try:
        return list(col.find({"modo": NO_MENCIONAR}, {"_id": 0, "embedding": 0}))
    except Exception as e:
        print(f"  [AVISO] No se pudo leer la lista de empresas a no mencionar: {e}", flush=True)
        return []


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes: "Peças" y "pecas" son la misma mención."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def _patron(nombre: str) -> re.Pattern | None:
    plano = " ".join(_plano(nombre).split())
    if len(plano) < 2:
        return None
    # Palabra entera: "Ford" no es mención dentro de "Stanford". Espacios flexibles.
    cuerpo = r"\s+".join(re.escape(p) for p in plano.split(" "))
    return re.compile(rf"(?<![a-z0-9]){cuerpo}(?![a-z0-9])")


def nombrados(texto: str, clientes: list[dict]) -> list[str]:
    """Nombres de los clientes que aparecen en el texto (por nombre o alias), en el orden de la lista."""
    plano = _plano(texto)
    encontrados = []
    for c in clientes or []:
        for variante in [c.get("nombre", ""), *(c.get("alias") or [])]:
            patron = _patron(variante)
            if patron and patron.search(plano):
                encontrados.append(c.get("nombre", variante))
                break
    return encontrados
