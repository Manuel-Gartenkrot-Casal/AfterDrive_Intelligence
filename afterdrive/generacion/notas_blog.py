"""
notas_blog.py — Notas de AfterDrive by Alephee para citar y enlazar desde una nota nueva.

Interfaz:
    relacionadas(consulta, categorias, idioma, limite=4) -> list[NotaBlog]
    formatear(notas, compacto=False) -> str      bloque para el prompt
    citadas(texto, notas) -> list[NotaBlog]      las que la nota terminó enlazando
    NotaBlog

Que el blog se cite a sí mismo ("como analizamos en AfterDrive by Alephee")
y lleve a otras notas suma contexto al lector y enlaces internos para SEO.
Pero solo sirve si la nota citada trata lo mismo: por eso se eligen las más
parecidas al tema (embeddings) y al plan y a la redacción se les pide citar
solo las que encajen con una sección, y solo con lo que dice su resumen.

Candidatas, en el idioma de la nota:
- Las notas reales del blog (afterdrive_ejemplos, scrapeadas de /es/blog):
  solo para notas en español.
- Las notas propias ya publicadas en HubSpot (notas_fase2, estado publicado,
  con URL pública).

Si los embeddings fallan, mandan la categoría y la fecha. Nunca lanza: sin
notas relacionadas, la nota se escribe igual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RESUMEN_MAX = 280
CANDIDATAS_MAX = 300
BONO_CATEGORIA = 0.08


@dataclass
class NotaBlog:
    titulo: str
    url: str
    resumen: str = ""
    origen: str = "blog"            # "blog" (afterdrive_ejemplos) o "propia" (notas_fase2 publicada)
    categorias: list[str] = field(default_factory=list)
    embedding: list | None = field(default=None, repr=False)
    puntaje: float = 0.0

    def como_dict(self) -> dict:
        return {"titulo": self.titulo, "url": self.url, "origen": self.origen}


def _resumen(texto: str) -> str:
    """El primer párrafo con contenido, recortado sin cortar palabras."""
    for parrafo in re.split(r"\n\s*\n", texto or ""):
        limpio = " ".join(parrafo.split()).strip("#*_ ")
        if len(limpio) > 60 and not parrafo.lstrip().startswith("#"):
            return limpio if len(limpio) <= RESUMEN_MAX else limpio[:RESUMEN_MAX].rsplit(" ", 1)[0] + "…"
    return ""


def _del_blog(base, idioma: str) -> list[NotaBlog]:
    if idioma != "es":
        return []   # el blog scrapeado es el de /es/
    docs = base["afterdrive_ejemplos"].find(
        {"url": {"$regex": "^https://"}, "titulo": {"$nin": ["", None]}},
        {"url": 1, "titulo": 1, "cuerpo": 1, "tag_slug": 1, "embedding": 1, "embedding_modelo": 1},
    ).sort("scrapeado_en", -1).limit(CANDIDATAS_MAX)
    return [NotaBlog(d["titulo"].strip(), d["url"], _resumen(d.get("cuerpo", "")), "blog",
                     [d["tag_slug"]] if d.get("tag_slug") else [], _vector(d)) for d in docs]


def _propias(base, idioma: str) -> list[NotaBlog]:
    from afterdrive import hubspot
    from afterdrive.db import ESTADO_PUBLICADO
    from afterdrive.generacion import calidad

    docs = base["notas_fase2"].find(
        {"estado": ESTADO_PUBLICADO, "hubspot.url": {"$regex": "^https://"}},
        {"contenido": 1, "regiones": 1, "categorias": 1, "hubspot": 1, "embedding": 1, "embedding_modelo": 1},
    ).sort("publicado_en", -1).limit(CANDIDATAS_MAX)
    notas = []
    for d in docs:
        if hubspot.idioma(d) != idioma:
            continue
        p = calidad.partes(d.get("contenido", ""))
        if p.titulo:
            notas.append(NotaBlog(p.titulo, d["hubspot"]["url"], p.meta or _resumen(d.get("contenido", "")), "propia",
                                  list(d.get("categorias") or []), _vector(d)))
    return notas


_modelo_actual = {"nombre": ""}


def _vector(d: dict) -> list | None:
    from afterdrive.ingesta.embeddings import vector_de
    return vector_de(d, _modelo_actual["nombre"]) if d.get("embedding") else None


def relacionadas(consulta: str, categorias: list[str], idioma: str | None, limite: int = 4, base=None) -> list[NotaBlog]:
    """Las `limite` notas del blog más parecidas al tema, en el idioma de la nota."""
    from afterdrive.ia import llm
    from afterdrive.ingesta.embeddings import coseno

    if not idioma:
        return []
    try:
        if base is None:
            from afterdrive.db import db as base
        _modelo_actual["nombre"] = llm.modelo_embeddings()
        candidatas = _propias(base, idioma) + _del_blog(base, idioma)
    except Exception as e:
        print(f"  [AVISO] No se pudieron leer las notas del blog para enlazar: {e}", flush=True)
        return []
    vistas, unicas = set(), []
    for n in candidatas:
        clave = n.url.rstrip("/").lower()
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(n)
    if not unicas:
        return []
    try:
        vec = llm.embeber([consulta], tipo="query")[0]
    except Exception as e:
        print(f"  [AVISO] Sin embeddings para elegir notas del blog ({e}): mandan las categorías.", flush=True)
        vec = None
    cats = set(categorias or [])
    for n in unicas:
        similitud = coseno(vec, n.embedding) if vec and n.embedding else 0.0
        n.puntaje = similitud + (BONO_CATEGORIA if cats & set(n.categorias) else 0.0)
    # sorted es estable: a igual puntaje quedan primero las propias y las más nuevas.
    return sorted(unicas, key=lambda n: n.puntaje, reverse=True)[:limite]


def formatear(notas: list[NotaBlog], compacto: bool = False) -> str:
    if not notas:
        return ""
    lineas = [
        "## Notas de AfterDrive by Alephee relacionadas",
        "Son notas propias del blog. Citá una o dos SOLO si tratan lo mismo que una sección y le suman contexto: "
        "nombrá a AfterDrive by Alephee como fuente y enlazá la nota con un texto descriptivo, por ejemplo "
        "\"como analizamos en AfterDrive by Alephee, [la catalogación por fitment reduce devoluciones](url)\". "
        "Usá solo lo que dice su resumen. Si ninguna encaja, no cites ninguna: es mejor que forzarla.",
    ]
    for i, n in enumerate(notas, 1):
        lineas.append(f"[B{i}] {n.titulo} — {n.url}")
        if n.resumen and not compacto:
            lineas.append(f"Resumen: {n.resumen}")
    return "\n".join(lineas)


def citadas(texto: str, notas: list[NotaBlog]) -> list[NotaBlog]:
    """Las notas del blog que quedaron enlazadas en el texto final."""
    urls = {u.rstrip("/").lower() for u in re.findall(r"\]\((https?://[^)\s]+)\)", texto or "")}
    return [n for n in notas if n.url.rstrip("/").lower() in urls]
