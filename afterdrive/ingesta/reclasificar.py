"""
reclasificar.py — Vuelve a pasar por la clasificación los Artículos descartados.

Uso (en una consola con MONGO_URI y el proveedor de IA configurados, p. ej. el Shell de Render):
    python -m afterdrive.ingesta.reclasificar             # los descartados de los últimos 30 días
    python -m afterdrive.ingesta.reclasificar --dias 90 --limite 200

Para qué: un descartado no se vuelve a scrapear nunca. Cuando el filtro era
demasiado estricto (aprobaba solo repuestos y catálogos) o una respuesta rota
del modelo contaba como rechazo, se perdieron noticias útiles. Esto las vuelve
a juzgar con el criterio actual: las que aprueba pasan a Artículos (con ficha
y embedding, igual que en la ingesta) y salen de descartados; las que rechaza
quedan descartadas con el motivo nuevo; las que la IA no pudo juzgar quedan
como estaban.

Cuesta una llamada de clasificación por artículo (más la ficha de los aprobados).
"""

from __future__ import annotations

import argparse
import datetime
import sys


def reclasificar(dias: int = 30, limite: int = 500) -> dict:
    """{"revisados", "aprobados", "rechazados", "pendientes"}.

    `dias` y `limite` tienen que ser al menos 1: en Mongo un limit(0) es
    "sin límite", así que reclasificaría (y pagaría) todos los descartados.
    """
    if dias < 1 or limite < 1:
        raise ValueError("dias y limite tienen que ser al menos 1")
    from afterdrive.ingesta import ingesta

    # Las mismas colecciones en las que escribe la ingesta.
    col_articulos, col_descartados = ingesta.col_articulos, ingesta.col_descartados
    desde = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=dias)).isoformat()
    docs = list(col_descartados.find({"fecha_descarte": {"$gte": desde}, "cuerpo": {"$nin": ["", None]}})
                .sort("fecha_descarte", -1).limit(limite))
    if not docs:
        print(f"No hay artículos descartados en los últimos {dias} días.", flush=True)
        return {"revisados": 0, "aprobados": 0, "rechazados": 0, "pendientes": 0}
    print(f"Reclasificando {len(docs)} artículo(s) descartado(s) de los últimos {dias} días...", flush=True)
    items = [{k: d[k] for k in ("url", "titulo", "cuerpo", "fuente", "fecha") if d.get(k) is not None}
             for d in docs]
    res = ingesta.ingerir(items)
    # Los aprobados ya están en Artículos: dejan de estar descartados.
    urls = [i["url"] for i in items]
    guardadas = [d["url"] for d in col_articulos.find({"url": {"$in": urls}}, {"url": 1})]
    if guardadas:
        col_descartados.delete_many({"url": {"$in": guardadas}})
    resumen = {"revisados": len(items), "aprobados": res["aprobados"], "rechazados": res["rechazados"],
               "pendientes": res.get("pendientes", 0)}
    print(f"[OK] {resumen['aprobados']} recuperado(s), {resumen['rechazados']} siguen descartados, "
          f"{resumen['pendientes']} sin juzgar (la IA no respondió).", flush=True)
    return resumen


def _entero_positivo(texto: str) -> int:
    try:
        valor = int(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{texto}' no es un número entero") from None
    if valor < 1:
        raise argparse.ArgumentTypeError("tiene que ser al menos 1")
    return valor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vuelve a clasificar los artículos descartados.")
    parser.add_argument("--dias", type=_entero_positivo, default=30, help="descartados en los últimos N días (30)")
    parser.add_argument("--limite", type=_entero_positivo, default=500, help="como mucho N artículos (500)")
    args = parser.parse_args(argv)
    reclasificar(args.dias, args.limite)
    return 0


if __name__ == "__main__":
    sys.exit(main())
