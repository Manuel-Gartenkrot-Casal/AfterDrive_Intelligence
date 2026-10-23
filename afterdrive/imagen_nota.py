"""
imagen_nota.py — Genera (o regenera) la imagen destacada de una nota, como Corrida.

Lo encola el botón "Generar imagen con IA" de la vista previa: corre como
subprocess de la Cola, así aparece en Corridas con su registro y se puede
cancelar (la Cola mata el proceso y no se guarda nada).

Uso:
    python -m afterdrive.imagen_nota <coleccion> <id> [descripcion]
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    from afterdrive import historial, imagenes

    parser = argparse.ArgumentParser(description="Imagen destacada de una nota (NVIDIA)")
    parser.add_argument("coleccion")
    parser.add_argument("id")
    parser.add_argument("descripcion", nargs="?", default="")
    args = parser.parse_args(argv)

    print(f"[Imagen] Generando con NVIDIA ({imagenes.modelo()})...", flush=True)
    if args.descripcion:
        print(f"[Imagen] Descripción pedida: {args.descripcion}", flush=True)
    try:
        item = historial.generar_imagen(args.coleccion, args.id, args.descripcion)
    except historial.ErrorHistorial as e:
        print(f"[ERROR] {e}", flush=True)
        return 1
    if item is None:
        print("[ERROR] Nota no encontrada.", flush=True)
        return 1
    print("[OK] Imagen generada y guardada en la nota.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
