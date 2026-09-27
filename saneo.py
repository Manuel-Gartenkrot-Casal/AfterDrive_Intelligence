"""
saneo.py — Texto crudo del modelo -> Nota publicable, o rechazo con motivo.

Interfaz:
    sanear(crudo) -> Saneo(texto, motivo)

Antes había dos copias de esta lógica (Fase 1 en lm_studio.generar_articulo,
Fase 2 en generar_nota_fase2) y cada bug de salida del modelo se arreglaba en
una sola. Todo lo que el modelo puede ensuciar (fences, wrappers JSON,
razonamiento filtrado, secciones/CTA duplicados) se resuelve acá, y los tests
de tests/test_saneo.py usan salidas malas reales como fixtures.
"""

from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass

LARGO_MINIMO = 200


@dataclass(frozen=True)
class Saneo:
    texto: str
    motivo: str | None = None  # None = publicable

    @property
    def ok(self) -> bool:
        return self.motivo is None


def sanear(crudo: str) -> Saneo:
    """Extrae la Nota publicable del texto crudo del modelo.

    Devuelve Saneo con motivo != None cuando no hay Nota publicable (respuesta
    vacía, razonamiento en vez de nota, texto demasiado corto).
    """
    crudo = (crudo or "").strip()
    if not crudo:
        return Saneo("", "respuesta vacía del modelo")

    texto = _desenvolver_json(crudo) or crudo
    texto = _limpiar_artefactos(texto)

    if _es_degenerado(texto):
        return Saneo("", "el modelo devolvió texto degenerado (repeticiones sin sentido)")

    marcas = len(_PLANNING.findall(texto))
    if marcas >= 3 and not _parece_nota(texto):
        return Saneo("", f"el modelo devolvió razonamiento en vez de la nota ({marcas} marcas de planning)")

    texto = _desde_primer_titulo(texto) or _texto_de_json_embebido(texto) or texto
    texto = _deduplicar(texto).strip()

    if len(texto) < LARGO_MINIMO:
        return Saneo(texto, "no se pudo extraer una nota de largo suficiente")
    return Saneo(texto)


# ── Wrappers ──────────────────────────────────────────────────────────────────


def _primer_json(texto: str) -> dict | None:
    """Primer objeto JSON completo del texto, respetando strings."""
    inicio = texto.find("{")
    if inicio == -1:
        return None
    depth, en_string, escape = 0, False, False
    for i in range(inicio, len(texto)):
        ch = texto[i]
        if en_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                en_string = False
            continue
        if ch == '"':
            en_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(texto[inicio : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _desenvolver_json(crudo: str) -> str:
    """Si el modelo envolvió la nota en {"articulo": "..."}, la saca."""
    if '"articulo"' not in crudo:
        return ""
    for candidato in (crudo, '{"accion": "redaccion",' + crudo):
        data = _primer_json(candidato)
        if data and isinstance(data.get("articulo"), str) and data["articulo"].strip():
            return data["articulo"]
    m = re.search(r'"articulo"\s*:\s*"(.+)"\s*}', crudo, re.DOTALL)
    if m:
        return m.group(1).replace("\\n", "\n").replace('\\"', '"')
    return ""


def _limpiar_artefactos(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r"^```(?:markdown)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)
    texto = re.sub(r"</?ARTICULO>", "", texto)
    # Líneas que son SOLO un corchete literal (borrador que se coló). Solo la
    # línea entera: "[texto](url)" al inicio de línea es un link válido.
    texto = re.sub(r"^\[[^\]\n]*\]\s*$", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"(?i)(?:^|\n)\s*Meta Description:\s*", "\n", texto)
    texto = re.sub(r"(?i)(?:^|\n)\s*SEO:\s*", "\n", texto)
    return texto.strip()


def _desde_primer_titulo(texto: str) -> str:
    """Descarta el preámbulo (prosa, JSON de metadata) antes del primer título."""
    lineas = texto.split("\n")
    for i, linea in enumerate(lineas):
        if linea.strip().startswith(("# ", "## ")):
            posible = "\n".join(lineas[i:]).strip()
            if len(posible) > LARGO_MINIMO:
                return posible
    return ""


def _texto_de_json_embebido(texto: str) -> str:
    """Nota escrita como JSON de secciones (formatos que emitieron modelos débiles)."""
    for match in reversed(list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", texto, re.DOTALL))):
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        partes = [f"# {data['titulo']}"] if data.get("titulo") else []
        if isinstance(data.get("contenido"), str):
            partes.append(data["contenido"])
        elif isinstance(data.get("estructura"), list):
            for sec in data["estructura"]:
                if isinstance(sec, dict):
                    if st := sec.get("sectionTitle") or sec.get("titulo"):
                        partes.append(f"\n## {st}")
                    if tx := sec.get("content") or sec.get("texto"):
                        partes.append(tx)
        elif any(f"texto_seccion{i}" in data for i in range(1, 5)):
            for i in range(1, 5):
                if f"texto_seccion{i}" in data:
                    st = re.sub(r"^\*{1,2}|\*{1,2}$", "", data.get(f"seccion{i}", "")).strip()
                    if st:
                        partes.append(f"\n## {st}")
                    partes.append(data[f"texto_seccion{i}"])
        elif any(k.startswith("seccion") for k in data):
            for key in sorted(k for k in data if k.startswith("seccion")):
                sec = data[key]
                if isinstance(sec, dict):
                    if st := sec.get("titulo"):
                        partes.append(f"\n## {st}")
                    if tx := sec.get("texto"):
                        partes.append(tx)
        else:
            continue
        if md := data.get("meta_description"):
            partes.append(f"\n*{md.strip('*')}*")
        if len(partes) > 1 or (partes and not data.get("titulo")):
            return "\n".join(partes)
    return ""


def _es_degenerado(texto: str) -> bool:
    """Bucles de tokens ("ellsellsells...") que algunos modelos free emiten.

    Un texto real comprime a ~45% de su tamaño; un bucle repetitivo, a menos
    del 25%. Solo se mide con texto suficiente para que la señal sea estable.
    """
    datos = texto.encode("utf-8")
    if len(datos) < 400:
        return False
    return len(zlib.compress(datos)) / len(datos) < 0.28


# ── Razonamiento filtrado ─────────────────────────────────────────────────────

# Algunos modelos (ej: nemotron-3.5-lightning) emiten su cadena de pensamiento
# como si fuera la nota: "I need to...", "Let me structure...".
_PLANNING = re.compile(
    r"\b(I need to|I'll |I would|Let me|Now let|Let's (think|see)|"
    r"I can reference|I should use|Let me think|we need to|Let me draft|"
    r"First, the title|Possible angle|I'm going to|Let me write the|"
    r"I will make sure|Actually, re-reading|Let me check|Word count|"
    r"I'll aim|I need to be careful|Let me re-read)\b",
    re.IGNORECASE,
)

_ESTRUCTURA_DE_LA_TAREA = [
    "gancho con dato real", "la solucion concreta", "casos de exito",
    "cta + meta description", "panorama macro", "desafio estrategico",
    "1 paragraph", "paragraphs",
]


def _parece_nota(texto: str) -> bool:
    """Distingue una nota final de un plan del modelo.

    El planning es casi todo en inglés y repite los títulos de la estructura
    pedida sin desarrollarlos.
    """
    t = texto.lower()
    secciones = re.findall(r"^#{1,2}\s+(.+)$", t, re.MULTILINE)
    copiadas = sum(1 for s in secciones if any(p in s for p in _ESTRUCTURA_DE_LA_TAREA))
    planning_ingles = len(re.findall(
        r"\b(the examples|the instructions|the context|a solution|an article|"
        r"the article|the title|the reader|the user says|let me)\b", t))
    en_ingles = len(re.findall(r"\b(i|you|the|and|from|with)\b", t))
    en_espanol = len(re.findall(r"\b(la|el|los|las|una|para|con|del|de los)\b", t))
    predomina_ingles = en_ingles > en_espanol * 3
    return not (predomina_ingles and (copiadas >= 2 or planning_ingles >= 3))


# ── Repeticiones de modelos débiles ───────────────────────────────────────────

# Imperativo en cualquier voseo/tuteo: Descubre/Descubrí, Conoce/Conocé, ...
_CTA = re.compile(r"(descubr[eí]|conoc[eé]|transform[aá]|descarg[aá]|acced[eé]|visit[aá])\b", re.IGNORECASE)


def _deduplicar(texto: str) -> str:
    if not texto or len(texto) < 100:
        return texto
    lineas = _sin_cierre_repetido(texto.split("\n"))
    lineas = [_sin_oraciones_repetidas(ln) for ln in lineas]
    lineas = _sin_secciones_repetidas(lineas)
    lineas = _un_solo_cta(lineas)
    return "\n".join(lineas)


def _sin_cierre_repetido(lineas: list[str]) -> list[str]:
    """La misma frase de cierre pegada 2+ veces: se deja la primera."""
    ultima = next((ln.strip() for ln in reversed(lineas) if ln.strip() and not ln.strip().startswith("*")), "")
    if not ultima or sum(1 for ln in lineas if ln.strip() == ultima) < 2:
        return lineas
    vista = False
    salida = []
    for ln in lineas:
        if ln.strip() == ultima:
            if vista:
                continue
            vista = True
        salida.append(ln)
    return salida


def _sin_oraciones_repetidas(linea: str) -> str:
    stripped = linea.strip()
    if len(stripped) <= 80 or stripped.count(".") < 2:
        return linea
    oraciones = [o.strip() for o in stripped.split(".") if o.strip()]
    vistas, unicas = set(), []
    for o in oraciones:
        clave = re.sub(r"\s+", " ", o.lower())
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(o)
    return ". ".join(unicas) + "." if len(unicas) < len(oraciones) else linea


def _sin_secciones_repetidas(lineas: list[str]) -> list[str]:
    """Dos bloques ## con >60% de palabras en común: se deja el primero."""
    bloques: list[dict] = []
    actual = {"titulo": "", "lineas": []}
    for ln in lineas:
        if ln.strip().startswith("## "):
            if actual["lineas"] or actual["titulo"]:
                bloques.append(actual)
            actual = {"titulo": ln, "lineas": []}
        else:
            actual["lineas"].append(ln)
    bloques.append(actual)
    if len(bloques) < 2:
        return lineas

    def palabras(b):
        return set(re.sub(r"\s+", " ", " ".join(b["lineas"]).lower()).split())

    unicos = [bloques[0]]
    for b in bloques[1:]:
        pb = palabras(b)
        duplicado = any(
            len(pb) > 10 and len(pe := palabras(e)) > 10 and len(pb & pe) / len(pb | pe) > 0.6
            for e in unicos
        )
        if not duplicado:
            unicos.append(b)
    if len(unicos) == len(bloques):
        return lineas
    salida = []
    for b in unicos:
        if b["titulo"]:
            salida.append(b["titulo"])
        salida.extend(b["lineas"])
    return salida


def _es_linea_cta(linea: str) -> bool:
    s = linea.strip()
    # Títulos y la meta description (*cursiva*) no son CTA.
    if s.startswith("#") or (s.startswith("*") and not s.startswith("**")):
        return False
    return bool(_CTA.match(s.lstrip("*> -")))


def _un_solo_cta(lineas: list[str]) -> list[str]:
    """Varias líneas CTA: se deja la última, que es el cierre de la nota.

    Solo cuenta como CTA una línea que EMPIEZA con el verbo: una oración del
    cuerpo que menciona "conocé" no es un CTA y no se borra.
    """
    es_cta = [_es_linea_cta(ln) for ln in lineas]
    if sum(es_cta) < 2:
        return lineas
    ultima = max(i for i, c in enumerate(es_cta) if c)
    return [ln for i, ln in enumerate(lineas) if not es_cta[i] or i == ultima]
