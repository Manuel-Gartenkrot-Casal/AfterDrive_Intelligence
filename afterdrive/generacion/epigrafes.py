"""
epigrafes.py — El epígrafe (la bajada) de cada foto dentro del texto de una Nota, en los tres idiomas.

Interfaz:
    completar(nota, veredictos=None) -> int      escribe los que faltan en nota["imagenes_cuerpo"]; cuántos
    texto(imagen, idioma) -> str                 el epígrafe de una foto en ese idioma ("" si no tiene)

Cada foto del cuerpo lleva `epigrafe: {"pt": ..., "es": ..., "en": ...}`: una
oración corta que dice qué muestra y la vincula con la nota. hubspot.py lo pone
debajo de la foto, en el idioma de cada versión (la original y las traducciones).

La IA no siempre vio la foto: escribe a partir de lo que dijo el editor de
fotografía al elegirla (imagen_destacada.py, si la miró), del texto alternativo
y de la noticia de la que sale. Por eso se le pide no inventar nombres, lugares
ni cifras: si no sabe qué hay en la foto, una bajada genérica del tema.

Una sola llamada por nota (modelo de traducción). Nunca lanza, salvo una
cancelación desde el dashboard: sin epígrafe la foto sale igual, como antes.
Las notas anteriores los reciben al subirse a HubSpot (historial.py).
"""

from __future__ import annotations

IDIOMAS = ("pt", "es", "en")
MAX_CARACTERES = 160

_SYSTEM = """\
Sos editor del blog B2B AfterDrive by Alephee (aftermarket automotor en Latinoamérica). Escribís el \
epígrafe que va debajo de cada foto de una nota: la bajada que le dice al lector qué está viendo y por \
qué importa para la nota.

Reglas:
- Una sola oración por foto, de 8 a 20 palabras, sin punto final si es una frase nominal.
- Describí lo que muestra la foto y conectalo con el tema de la nota. Nada de "En la imagen se ve", \
"Foto de" ni "Imagen ilustrativa".
- No inventes: ni nombres de personas o empresas, ni lugares, fechas o cifras que no estén en los datos. \
Si no se sabe con certeza qué muestra, escribí una bajada general sobre lo que la foto representa para el tema.
- Tres versiones con el mismo sentido: portugués de Brasil, español rioplatense neutro (sin voseo) e inglés.

Respondé solo con este JSON, una entrada por foto en el orden recibido:
{"epigrafes": [{"n": 1, "pt": "...", "es": "...", "en": "..."}]}"""


def texto(imagen: dict, idioma: str | None) -> str:
    """El epígrafe de la foto en `idioma`, o "" si no tiene."""
    epigrafe = (imagen or {}).get("epigrafe")
    if not isinstance(epigrafe, dict) or not idioma:
        return ""
    return str(epigrafe.get(idioma) or "").strip()


def _titulo(nota: dict) -> str:
    for linea in (nota.get("contenido") or "").splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return ""


def _motivos(nota: dict, veredictos: dict | None) -> dict[str, str]:
    """url de la foto -> lo que dijo el editor de fotografía (los veredictos o lo guardado en `fuentes`)."""
    motivos = {f["imagen"]: f.get("imagen_motivo") or "" for f in nota.get("fuentes") or []
               if isinstance(f, dict) and f.get("imagen")}
    for url, v in (veredictos or {}).items():
        if isinstance(v, dict) and v.get("motivo"):
            motivos[url] = v["motivo"]
    return motivos


def _limpio(valor) -> str:
    return " ".join(str(valor or "").split())[:MAX_CARACTERES].strip()


def completar(nota: dict, veredictos: dict | None = None) -> int:
    """Escribe el epígrafe de las fotos del cuerpo que no lo tienen. Devuelve cuántas quedaron con uno nuevo.

    Modifica `nota["imagenes_cuerpo"]` en el lugar (quien llama decide si lo guarda).
    """
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    faltan = [im for im in nota.get("imagenes_cuerpo") or []
              if isinstance(im, dict) and im.get("url") and not all(texto(im, c) for c in IDIOMAS)]
    if not faltan:
        return 0
    motivos = _motivos(nota, veredictos)
    lineas = []
    for i, im in enumerate(faltan, 1):
        origen = im.get("origen") or {}
        datos = [f'noticia de la que sale: "{origen.get("titulo") or "—"}"']
        if motivos.get(im["url"]):
            datos.append(f'lo que vio el editor de fotografía: "{motivos[im["url"]]}"')
        if im.get("alt") and im.get("alt") != origen.get("titulo"):
            datos.append(f'texto alternativo: "{im["alt"]}"')
        if im.get("banco"):
            datos.append("foto de un banco de imágenes")
        lineas.append(f"{i}. " + " | ".join(datos))
    plan = nota.get("plan") or {}
    pedido = (f"Título de la nota: {_titulo(nota)}\n"
              + (f"Ángulo: {plan['angulo']}\n" if plan.get("angulo") else "")
              + "\nFotos:\n" + "\n".join(lineas))
    try:
        crudo = llm.completar(_SYSTEM, pedido, temperature=0.3, max_tokens=300 + 150 * len(faltan), tarea="traduccion")
        data = _extraer_json(crudo)
    except llm.Cancelada:
        raise
    except Exception as e:
        print(f"  [AVISO] No se pudieron escribir los epígrafes de las fotos: {e}", flush=True)
        return 0
    escritos = 0
    for e in (data.get("epigrafes") if isinstance(data, dict) else None) or []:
        if not isinstance(e, dict) or not isinstance(e.get("n"), int | float) or not 1 <= int(e["n"]) <= len(faltan):
            continue
        epigrafe = {c: _limpio(e.get(c)) for c in IDIOMAS}
        if all(epigrafe.values()):
            faltan[int(e["n"]) - 1]["epigrafe"] = epigrafe
            escritos += 1
    if escritos < len(faltan):
        print(f"  [AVISO] Epígrafes: {escritos} de {len(faltan)} fotos.", flush=True)
    return escritos
