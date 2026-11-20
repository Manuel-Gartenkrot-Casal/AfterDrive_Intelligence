"""
filtros.py — Los filtros de la redacción, en una sola lista.

Interfaz:
    Contexto(prohibidos, piezas)                lo que los filtros necesitan saber de esta nota
    contexto(col_clientes=None, piezas=None) -> Contexto
    reglas(ctx) -> [texto]                       lo que se le pide al modelo en "## Para esta nota"
    piezas_editables(piezas=None) -> [(clave, texto)]   las piezas de Prompts que usan los filtros
    revisar(texto, ctx) -> {campo: [hallazgo]}   la nota escrita, sin IA: un campo por filtro
    problemas(hallazgos) -> [(codigo, pedido)]   lo que frena, como pedido de corrección para el modelo
    motivos(doc) -> [motivo]                     lo que frena la aprobación automática (juez.filtro_duro)
    para_el_dashboard() -> [dict]                cómo mostrar lo que encontró cada filtro (GET /api/filtros)

Cada filtro hace dos cosas: antes de escribir le pide algo al modelo y después
revisa el texto. Lo que pide sale de `pieza` (una pieza editable de la pestaña
Prompts) o de `regla` (armada con el contexto de la nota). Lo que encuentra queda
en la nota, en el campo `campo`, y el dashboard lo muestra con `titulo` e
`indicacion`. Si `frena`, la nota vuelve a corregirse y no se aprueba sola; si no,
solo queda el aviso para quien la revisa.

Para sumar un filtro: escribir un Filtro y agregarlo a FILTROS. La generación
(generar_nota_fase2), el juez, la edición de notas (historial), la vista previa
del prompt y el aviso en la revisión de la nota (recorrido.js) recorren la lista:
no hay que tocarlos. Si usa una pieza editable nueva, esa pieza se suma además a
redaccion.PIEZAS y a prompts_editables._CATALOGO, y sus textos a i18n/textos.js.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from afterdrive import clientes, sensibles
from afterdrive.ia import redaccion


@dataclass(frozen=True)
class Contexto:
    prohibidos: list[dict] = field(default_factory=list)   # empresas que no se nombran (clientes.no_mencionar)
    piezas: dict | None = None                             # piezas del prompt que pisan a las activas


def contexto(col_clientes=None, piezas: dict | None = None) -> Contexto:
    return Contexto(clientes.no_mencionar(col_clientes), piezas)


@dataclass(frozen=True)
class Filtro:
    campo: str                                         # dónde quedan los hallazgos en la nota (único)
    revisar: Callable[[str, Contexto], list[str]]      # qué encontró en el texto escrito
    titulo: str                                        # el aviso en la revisión de la nota (en español:
    indicacion: str                                    # idioma.js lo traduce con i18n/textos.js)
    pieza: str | None = None                           # pieza editable de Prompts que se le pide al modelo
    regla: Callable[[Contexto], str | None] = lambda ctx: None   # o una regla armada para esta nota
    nombres: dict[str, str] = field(default_factory=dict)        # cómo mostrar cada hallazgo (si no, tal cual)
    frena: bool = False                                # corrige la nota y frena la aprobación automática
    codigo: str = ""                                   # código del problema en la vuelta de corrección
    pedido: Callable[[list[str]], str] = lambda h: ""  # qué se le pide al modelo al corregir
    motivo: Callable[[list[str]], str] = lambda h: ""  # por qué el juez no la aprueba sola


# ── Empresas que no se nombran (clientes.py) ─────────────────────────────────

def _regla_prohibidas(ctx: Contexto) -> str | None:
    nombres = ", ".join(c.get("nombre", "") for c in ctx.prohibidos if c.get("nombre"))
    if not nombres:
        return None
    return (f"- Nunca nombres a estas empresas, aunque aparezcan en las noticias: {nombres}. Si un dato "
            "depende de una de ellas, contalo sin el nombre o no lo uses.")


EMPRESAS_PROHIBIDAS = Filtro(
    campo="empresas_prohibidas",
    regla=_regla_prohibidas,
    revisar=lambda texto, ctx: clientes.nombrados(texto, ctx.prohibidos),
    titulo="Nombra empresas que no se mencionan",
    indicacion="Sacalas antes de aprobar.",
    frena=True,
    codigo="empresa_prohibida",
    pedido=lambda h: (f"nombraba empresas que no se pueden mencionar: {', '.join(h)}. Sacalas del texto; si un "
                      "dato depende de ellas, contalo sin el nombre o quitalo"),
    motivo=lambda h: f"nombra empresas que no se pueden mencionar: {', '.join(h[:3])}",
)


# ── Datos personales o sensibles (sensibles.py) ──────────────────────────────
# Solo avisa: la nota no se corrige ni se frena. Los montos no se buscan en las
# notas: hablar de precios y pagos del mercado es normal, y marcarlos sería ruido.
TIPOS_EN_NOTAS = tuple(t for t in sensibles.TIPOS if t != "monto")

DATOS_SENSIBLES = Filtro(
    campo="datos_sensibles",
    pieza="privacidad",
    revisar=lambda texto, ctx: sensibles.tipos_en(texto, TIPOS_EN_NOTAS),
    titulo="Puede tener datos sensibles",
    indicacion="Revisalos antes de publicar.",
    nombres={"email": "Email", "telefono": "Teléfono", "dni": "Documento", "cuit": "CUIT/CUIL", "cpf": "CPF",
             "cnpj": "CNPJ", "tarjeta": "Tarjeta", "cuenta": "Cuenta bancaria", "clave": "Clave o token"},
)


FILTROS: list[Filtro] = [EMPRESAS_PROHIBIDAS, DATOS_SENSIBLES]


def _filtros() -> list[Filtro]:
    campos = [f.campo for f in FILTROS]
    if len(set(campos)) != len(campos):
        raise ValueError(f"Dos filtros guardan en el mismo campo de la nota: {campos}")
    return FILTROS


def reglas(ctx: Contexto) -> list[str]:
    textos = [redaccion.texto(f.pieza, ctx.piezas).strip() if f.pieza else f.regla(ctx) for f in _filtros()]
    return [t for t in textos if t]


def piezas_editables(piezas: dict | None = None) -> list[tuple[str, str]]:
    return [(f.pieza, redaccion.texto(f.pieza, piezas)) for f in _filtros() if f.pieza]


def revisar(texto: str, ctx: Contexto) -> dict[str, list[str]]:
    return {f.campo: f.revisar(texto, ctx) for f in _filtros()}


def problemas(hallazgos: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(f.codigo, f.pedido(hallazgos[f.campo])) for f in _filtros() if f.frena and hallazgos.get(f.campo)]


def motivos(doc: dict) -> list[str]:
    return [f.motivo(doc[f.campo]) for f in _filtros() if f.frena and doc.get(f.campo)]


def para_el_dashboard() -> list[dict]:
    return [{"campo": f.campo, "titulo": f.titulo, "indicacion": f.indicacion, "frena": f.frena,
             "nombres": f.nombres} for f in _filtros()]
