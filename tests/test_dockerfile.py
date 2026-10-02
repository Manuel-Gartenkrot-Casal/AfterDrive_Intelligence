"""El Dockerfile copia los módulos uno por uno: si falta uno, la imagen no arranca.

Ya pasó dos veces (jev_clasificador.py, historial.py): la app importaba un
módulo nuevo, el Dockerfile no lo copiaba y gunicorn salía con código 3
("Worker failed to boot") recién en Render. Este test recorre los imports de
los módulos que sí se copian y exige que todo módulo local importado también
esté copiado.
"""

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _copiados() -> set[str]:
    texto = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    return set(re.findall(r"^COPY ([A-Za-z_]\w*\.py) \.", texto, re.M))


def _imports_locales(archivo: Path) -> set[str]:
    nombres = set()
    for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            nombres.add(nodo.module.split(".")[0])
    return {f"{n}.py" for n in nombres if (RAIZ / f"{n}.py").exists()}


def test_todo_modulo_local_importado_esta_en_el_dockerfile():
    copiados = _copiados()
    assert "flask_api.py" in copiados
    faltantes = {
        f"{importado} (importado por {archivo})"
        for archivo in copiados
        for importado in _imports_locales(RAIZ / archivo)
        if importado not in copiados
    }
    assert not faltantes, "Agregar al Dockerfile: " + ", ".join(sorted(faltantes))
