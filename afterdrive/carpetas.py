"""
carpetas.py — La carpeta de cada cliente: datos del cliente y eventos.

Interfaz:
    nueva_entrada(tipo, body) -> (doc, None) | (None, error)  valida lo que se sube
    listar(slug, tipo=None, col=None) -> [dict]             lo guardado de un cliente (para el backend)

La carpeta es la de un cliente de la colección `clientes` (por su slug). Cada
entrada es un documento de `carpetas_clientes`:
    {cliente_slug, tipo: "dato" | "evento", <campos>, creado_en}
- dato:   titulo, contenido
- evento: nombre, fecha (AAAA-MM-DD), lugar, descripcion

Se guarda tal como se sube: la información sensible se filtra después, en la
redacción, que es donde llega a una nota.
"""

from __future__ import annotations

import datetime

DATO = "dato"
EVENTO = "evento"
TIPOS = (DATO, EVENTO)
# campo -> (tope de caracteres, obligatorio)
CAMPOS = {
    DATO: {"titulo": (120, True), "contenido": (5000, True)},
    EVENTO: {"nombre": (160, True), "lugar": (160, False), "descripcion": (5000, False)},
}


# ── Entradas ─────────────────────────────────────────────────────────────────

def nueva_entrada(tipo: str, body: dict) -> tuple[dict | None, str | None]:
    """(documento listo para guardar, None) o (None, error)."""
    if tipo not in TIPOS:
        return None, "Tipo inválido: dato o evento."
    doc: dict = {"tipo": tipo}
    for campo, (tope, obligatorio) in CAMPOS[tipo].items():
        valor = body.get(campo, "")
        if not isinstance(valor, str):
            return None, f"El campo '{campo}' tiene que ser texto."
        valor = valor.strip()
        if obligatorio and not valor:
            return None, f"Falta '{campo}'."
        if len(valor) > tope:
            return None, f"'{campo}' es muy largo (máximo {tope} caracteres)."
        doc[campo] = valor
    if tipo == EVENTO:
        fecha = body.get("fecha")
        try:
            doc["fecha"] = datetime.date.fromisoformat(fecha).isoformat()
        except (TypeError, ValueError):
            return None, "Falta la fecha del evento (AAAA-MM-DD)."
    doc["creado_en"] = datetime.datetime.now(datetime.UTC).isoformat()
    return doc, None


def listar(slug: str, tipo: str | None = None, col=None) -> list[dict]:
    """Las entradas de la carpeta de un cliente: los eventos por fecha y los datos por carga, lo nuevo primero."""
    if col is None:
        from afterdrive.db import col_carpetas as col
    filtro = {"cliente_slug": slug, **({"tipo": tipo} if tipo else {})}
    docs = list(col.find(filtro))
    docs.sort(key=lambda d: (d.get("fecha") or "", d.get("creado_en") or ""), reverse=True)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs
