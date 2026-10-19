"""
correccion.py — Arreglar los problemas de una Nota sin escribirla de nuevo.

Interfaz:
    corregir(nota, problemas, contexto="", max_tokens=8000) -> str | None
    necesita_reescritura(codigos) -> bool

Cuando la revisión encuentra un problema (un dato sin respaldo, una sección
que falta, una repetición), reescribir la nota entera con el modelo de
redacción cuesta lo mismo que la primera versión: es texto que escribe el
modelo caro. Acá el modelo de corrección (tarea "correccion": por defecto el
de evaluación, ver llm.RESPALDO_TAREA) recibe la nota y la lista de problemas
y devuelve la misma nota con solo eso arreglado. Además no toca lo que ya
estaba bien.

Se reescribe de cero solo cuando el problema es el ángulo (una nota que
repite a una reciente): eso no se arregla retocando.
"""

from __future__ import annotations

from afterdrive.ia import llm
from afterdrive.ia.saneo import sanear

# Problemas que no se arreglan retocando: piden otra nota.
REESCRIBIR = {"repetida"}

_SYSTEM = """\
Corregís notas B2B del blog de AfterDrive by Alephee antes de publicarlas.

## Tu tarea
Te paso una nota y la lista de problemas que encontró la revisión. Devolvé la MISMA nota con esos
problemas corregidos y nada más:
- No cambies lo que no está en la lista: estructura, títulos, tono, idioma, links y negritas quedan igual.
- Un dato sin respaldo se saca o se reemplaza por uno que esté en las noticias. Nunca inventes otro.
- Si falta una sección, agregala en su lugar con lo que ya dice la nota.
- Si algo se repite, dejalo una sola vez.

## Respuesta
Respondé solo con la nota corregida y completa, empezando por el título ("# "). Sin explicaciones."""


def necesita_reescritura(codigos: list[str]) -> bool:
    return any(c in REESCRIBIR for c in codigos)


def corregir(nota: str, problemas: list[str], contexto: str = "", max_tokens: int = 8000) -> str | None:
    """La nota corregida, o None si el modelo falló o no devolvió una nota publicable."""
    partes = ["## Problemas a corregir\n" + "\n".join(f"- {p}" for p in problemas)]
    if contexto:
        partes.append("## Noticias de contexto (la única fuente de datos)\n" + contexto)
    partes.append("## Nota\n" + nota)
    try:
        crudo = llm.completar(_SYSTEM, "\n\n".join(partes), temperature=0.2, max_tokens=max_tokens, stream=True,
                              tarea="correccion")
    except llm.ErrorLLM as e:
        print(f"  [AVISO] No se pudo corregir la nota ({e}).", flush=True)
        return None
    saneo = sanear(crudo)
    if not saneo.ok:
        print(f"  [AVISO] La corrección no devolvió una nota publicable: {saneo.motivo}.", flush=True)
        return None
    return saneo.texto
