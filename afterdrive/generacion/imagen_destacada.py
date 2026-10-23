"""
imagen_destacada.py — Qué foto de las noticias va como imagen destacada de una Nota.

Interfaz:
    elegir(noticias, titulo, angulo="") -> Eleccion

Las candidatas son las fotos de las noticias de la nota (las que la respaldan
primero). Con la API paga en uso (llm.ve_imagenes) el modelo de clasificación
las mira: descarta logos, banners, gráficos con texto o fotos que no tienen
que ver con el tema, y elige la que mejor acompaña a la nota. Si las descarta
todas, la nota queda sin imagen y el motivo se muestra al revisarla.

Sin API paga, o si la IA falla, va la primera foto, como antes: la IA mejora
la elección pero nunca la frena.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_FOTOS = 4
# Bedrock rechaza imágenes de más de 3,75 MB en Converse.
MAX_BYTES_IA = 3_750_000

_SYSTEM = """\
Sos el editor de fotografía del blog B2B AfterDrive by Alephee (aftermarket automotor en Latinoamérica). \
Elegís la imagen destacada de una nota entre las fotos de las noticias que usa.

Una foto es apta si:
- Es una fotografía real: no un logo, un ícono, un banner publicitario, una captura de pantalla ni un gráfico \
o infografía con mucho texto.
- Tiene que ver con el tema de la nota o con el sector: repuestos, talleres, vehículos, depósitos, logística, \
fábricas, ferias o personas trabajando en ellos.
- Se ve nítida y no tiene marcas de agua grandes ni texto sobreimpreso que la tape.

De las aptas, elegí la que mejor acompaña el título de la nota. Si ninguna es apta, "elegida" es null.

Respondé solo con este JSON, una entrada por foto en el orden recibido:
{"fotos": [{"n": 1, "apta": true, "motivo": "una oración en español"}], "elegida": 1}"""


@dataclass
class Eleccion:
    imagen: dict | None                 # campo `imagen` de la nota, o None
    metodo: str                         # "ia", "primera" o "ninguna"
    veredictos: dict = field(default_factory=dict)   # url -> {"apta": bool, "motivo": str}
    motivo: str = ""                    # por qué no hay imagen o por qué no decidió la IA

    def como_dict(self) -> dict:
        return {"metodo": self.metodo, "motivo": self.motivo}


def elegir(noticias: list, titulo: str, angulo: str = "") -> Eleccion:
    """Elige la foto. Nunca lanza, salvo una cancelación desde el dashboard."""
    from afterdrive.generacion import contexto_noticias
    from afterdrive.ia import llm

    candidatas = contexto_noticias.con_foto(noticias, limite=MAX_FOTOS)
    if not candidatas:
        return Eleccion(None, "ninguna", motivo="Ninguna noticia de la nota tiene foto.")
    primera = Eleccion(contexto_noticias.imagen_de(candidatas[0]), "primera")
    if not llm.ve_imagenes():
        return primera

    from afterdrive import imagen_web

    veredictos, enviadas, imagenes = {}, [], []
    for n in candidatas:
        try:
            imagenes.append(imagen_web.descargar(n.imagen["url"], max_bytes=MAX_BYTES_IA))
            enviadas.append(n)
        except imagen_web.ErrorDescarga as e:
            veredictos[n.imagen["url"]] = {"apta": False, "motivo": f"No se pudo descargar: {e}."}
    if not enviadas:
        primera.motivo = "No se pudo descargar ninguna foto para que la IA las mire."
        primera.veredictos = veredictos
        return primera

    print(f"  Eligiendo la imagen destacada con IA entre {len(enviadas)} foto(s)...", flush=True)
    lista = "\n".join(f"{i}. Foto de la noticia \"{n.titulo}\"" for i, n in enumerate(enviadas, 1))
    pedido = f"Título de la nota: {titulo}\n" + (f"Ángulo: {angulo}\n" if angulo else "") + f"\nFotos:\n{lista}"
    try:
        crudo = llm.completar(_SYSTEM, pedido, temperature=0, max_tokens=1500, tarea="clasificacion",
                              imagenes=imagenes)
        respuesta = _leer(crudo, len(enviadas))
    except llm.Cancelada:
        raise
    except Exception as e:
        print(f"  [AVISO] La IA no pudo mirar las fotos ({e}): va la primera.", flush=True)
        primera.motivo = f"La IA no pudo mirar las fotos: {e}"
        primera.veredictos = veredictos
        return primera

    for i, n in enumerate(enviadas, 1):
        veredictos[n.imagen["url"]] = respuesta["fotos"].get(i, {"apta": False, "motivo": "La IA no la evaluó."})
    elegida = respuesta["elegida"]
    if elegida is None:
        motivos = "; ".join(v["motivo"] for v in veredictos.values() if v.get("motivo"))
        print("  [AVISO] La IA descartó todas las fotos: la nota queda sin imagen.", flush=True)
        return Eleccion(None, "ia", veredictos, motivo=f"La IA descartó todas las fotos. {motivos}".strip())
    return Eleccion(contexto_noticias.imagen_de(enviadas[elegida - 1]), "ia", veredictos)


def _leer(crudo: str, total: int) -> dict:
    """{"fotos": {n: {"apta", "motivo"}}, "elegida": n | None}. ValueError si no hay JSON útil."""
    from afterdrive.ia.lm_studio import _extraer_json

    data = _extraer_json(crudo)
    if not isinstance(data, dict) or not isinstance(data.get("fotos"), list):
        raise ValueError("la respuesta no trae la lista de fotos")
    fotos = {}
    for f in data["fotos"]:
        if isinstance(f, dict) and isinstance(f.get("n"), int | float) and 1 <= int(f["n"]) <= total:
            fotos[int(f["n"])] = {"apta": f.get("apta") is True, "motivo": " ".join(str(f.get("motivo") or "").split())[:200]}
    elegida = data.get("elegida")
    elegida = int(elegida) if isinstance(elegida, int | float) and 1 <= int(elegida) <= total else None
    # Una elegida que la misma respuesta marcó como no apta no se usa.
    if elegida is not None and fotos.get(elegida, {}).get("apta") is False:
        elegida = None
    return {"fotos": fotos, "elegida": elegida}
