"""
imagen_destacada.py — Qué fotos de las noticias van en una Nota: la destacada y dos para el cuerpo.

Interfaz:
    elegir(noticias, titulo, angulo="", cantidad=CANTIDAD, extra=None) -> Eleccion

Las candidatas son las fotos de las noticias de la nota (las que la respaldan
primero), hasta MAX_FOTOS, sin repetir. La IA las juzga contra el TEMA de la
nota (no alcanza con que sean del sector) y devuelve las aptas en orden: la
primera va como destacada y las siguientes dentro del texto (hubspot.py las
reparte entre las secciones).

- Con la API paga (llm.ve_imagenes) el modelo de clasificación mira las fotos.
- Sin ella, el mismo modelo juzga sin verlas: por la noticia de la que salen,
  su texto alternativo y el nombre del archivo. Descarta las que claramente no
  tienen que ver (antes iba la primera foto a ciegas, aunque fuera de otra cosa).

Una foto guardada que el sitio ya no sirve (404) se vuelve a buscar en la
página de la noticia. Si entre las de la nota no hay suficientes aptas, se
buscan las que faltan entre otras noticias del mismo tema (`extra`).

Si la IA falla, van las primeras en orden: la IA mejora la elección pero nunca
la frena. Si las descarta todas, la nota queda sin imágenes y el motivo se
muestra al revisarla.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

CANTIDAD = 3        # destacada + 2 en el cuerpo
MAX_FOTOS = 8
MAX_BUSQUEDAS = 5   # páginas de noticias viejas que se descargan para buscarles la foto
REFRESCOS = 3       # fotos que dejaron de responder: se relee su página para tomar la actual
# Bedrock rechaza imágenes de más de 3,75 MB en Converse.
MAX_BYTES_IA = 3_750_000

_CRITERIOS = """\
Una foto es apta si cumple todo:
- Es una fotografía real: no un logo, un ícono, un banner publicitario, una captura de pantalla ni un gráfico \
o infografía con mucho texto.
- Tiene que ver con la nota: muestra el TEMA concreto (el producto, la actividad, el lugar o el tipo de \
empresa del que habla el título) o, si no, el sector de la nota (repuestos, autos, talleres, depósitos, \
logística, fábricas, ferias, comercio de autopartes). NO es apta una foto ajena al sector aunque venga de \
una noticia usada: billetes o cotizaciones, políticos, deportes, catástrofes, personas sin contexto.
- Se ve nítida y no tiene marcas de agua grandes ni texto sobreimpreso que la tape.

Ordená las aptas: primero las que muestran el tema y después las del sector ("elegidas", como mucho \
{cantidad}). Si ninguna es apta, "elegidas" es [].

Respondé solo con este JSON, una entrada por foto en el orden recibido:
{{"fotos": [{{"n": 1, "apta": true, "motivo": "una oración en español"}}], "elegidas": [1]}}"""

_SYSTEM_VISION = ("Sos el editor de fotografía del blog B2B AfterDrive by Alephee (aftermarket automotor en "
                  "Latinoamérica). Elegís las fotos de una nota entre las de las noticias que usa.\n\n" + _CRITERIOS)

_SYSTEM_TEXTO = ("Sos el editor de fotografía del blog B2B AfterDrive by Alephee (aftermarket automotor en "
                 "Latinoamérica). Elegís las fotos de una nota entre las de las noticias que usa, SIN verlas: "
                 "solo tenés el título de la noticia de la que sale cada foto, su texto alternativo y el nombre "
                 "del archivo. Juzgá qué muestra probablemente cada una: si la noticia es del sector, su foto "
                 "probablemente también. Si la noticia es de otro tema, no es apta. Un nombre de archivo o texto que sugiere logo, banner, autor o publicidad, "
                 "no es apta.\n\n" + _CRITERIOS)


@dataclass
class Eleccion:
    imagenes: list[dict]                # campo `imagen` de cada una, en orden (la primera es la destacada)
    metodo: str                         # "ia", "ia-texto", "primera" o "ninguna"
    veredictos: dict = field(default_factory=dict)   # url -> {"apta": bool, "motivo": str}
    motivo: str = ""                    # por qué no hay imagen o por qué no decidió la IA

    @property
    def imagen(self) -> dict | None:
        return self.imagenes[0] if self.imagenes else None

    def como_dict(self) -> dict:
        return {"metodo": self.metodo, "motivo": self.motivo, "cantidad": len(self.imagenes)}


def _archivo(url: str) -> str:
    return os.path.basename(urlparse(url).path)[:80]


def _unicas(noticias: list) -> list:
    vistas, resultado = set(), []
    for n in noticias:
        url = n.imagen["url"]
        if url not in vistas:
            vistas.add(url)
            resultado.append(n)
    return resultado


def elegir(noticias: list, titulo: str, angulo: str = "", cantidad: int = CANTIDAD, extra=None) -> Eleccion:
    """Elige hasta `cantidad` fotos. Nunca lanza, salvo una cancelación desde el dashboard.

    extra: función sin argumentos que devuelve más noticias del mismo tema. Si
    entre las de la nota no hay `cantidad` fotos aptas, se buscan ahí las que faltan.
    """
    from afterdrive.generacion import contexto_noticias

    candidatas = _unicas(contexto_noticias.con_foto(noticias, max_busquedas=MAX_BUSQUEDAS, limite=MAX_FOTOS))
    eleccion = _ronda(candidatas, titulo, angulo, cantidad) if candidatas else \
        Eleccion([], "ninguna", motivo="Ninguna noticia de la nota tiene foto.")
    faltan = cantidad - len(eleccion.imagenes)
    if faltan <= 0 or extra is None or eleccion.metodo == "primera":
        return eleccion
    vistas = {n.imagen["url"] for n in candidatas} | {id(n) for n in noticias}
    try:
        mas = [n for n in extra() if id(n) not in vistas and n.url not in {x.url for x in noticias}]
    except Exception as e:
        print(f"  [AVISO] No se pudieron buscar más noticias con foto: {e}", flush=True)
        return eleccion
    otras = [n for n in _unicas(contexto_noticias.con_foto(mas, max_busquedas=MAX_BUSQUEDAS, limite=MAX_FOTOS))
             if n.imagen["url"] not in vistas]
    if not otras:
        return eleccion
    print(f"  Faltan {faltan} imagen(es) apta(s): se buscan entre {len(otras)} foto(s) de otras noticias del tema.",
          flush=True)
    segunda = _ronda(otras, titulo, angulo, faltan)
    imagenes = eleccion.imagenes + segunda.imagenes
    veredictos = {**eleccion.veredictos, **segunda.veredictos}
    if not imagenes:
        motivo = eleccion.motivo + " Tampoco sirvió ninguna foto de otras noticias del tema."
        return Eleccion([], segunda.metodo, veredictos, motivo=motivo.strip())
    return Eleccion(imagenes, eleccion.metodo if eleccion.imagenes else segunda.metodo, veredictos)


def _descargar(n, refrescos: list[int]) -> tuple[bytes, str]:
    """Bytes de la foto de la noticia. Si el sitio ya no la sirve (4xx), se vuelve a leer la
    página de la noticia una vez para tomar su foto actual (hasta `refrescos` por nota)."""
    from afterdrive import imagen_web
    from afterdrive.generacion import contexto_noticias

    try:
        return imagen_web.descargar(n.imagen["url"], max_bytes=MAX_BYTES_IA)
    except imagen_web.ErrorDescarga as e:
        if refrescos[0] <= 0 or "respondió 4" not in str(e):
            raise
        refrescos[0] -= 1
        if contexto_noticias.refrescar_imagen(n) is None:
            raise
        print(f"  La foto de '{n.titulo[:50]}' cambió en su página: se usa la actual.", flush=True)
        return imagen_web.descargar(n.imagen["url"], max_bytes=MAX_BYTES_IA)


def _ronda(candidatas: list, titulo: str, angulo: str, cantidad: int, ver: bool | None = None) -> Eleccion:
    """Una pasada de la IA sobre las candidatas. ver=False la obliga a juzgar sin mirar las fotos."""
    from afterdrive.generacion import contexto_noticias
    from afterdrive.ia import llm

    primeras = Eleccion([contexto_noticias.imagen_de(n) for n in candidatas[:cantidad]], "primera")
    veredictos, enviadas, imagenes = {}, candidatas, None
    if ver is not False and llm.ve_imagenes():
        from afterdrive import imagen_web
        enviadas, imagenes, refrescos, sin_bajar = [], [], [REFRESCOS], []
        for n in candidatas:
            try:
                imagenes.append(_descargar(n, refrescos))
                enviadas.append(n)
            except imagen_web.ErrorDescarga as e:
                print(f"  [AVISO] No se pudo descargar la foto de '{n.titulo[:50]}': {e}", flush=True)
                sin_bajar.append(n)
        if not enviadas:
            # Ninguna se pudo mirar: se juzgan por su noticia y su texto en vez de descartarlas.
            return _ronda(sin_bajar, titulo, angulo, cantidad, ver=False)
        vistas = _ronda_con(enviadas, imagenes, titulo, angulo, cantidad, veredictos, primeras)
        faltan = cantidad - len(vistas.imagenes)
        if faltan > 0 and sin_bajar and vistas.metodo != "primera":
            # Las que no se pudieron bajar completan los lugares que faltan, juzgadas sin verlas.
            resto = _ronda(sin_bajar, titulo, angulo, faltan, ver=False)
            vistas.veredictos.update(resto.veredictos)
            if resto.imagenes:
                return Eleccion(vistas.imagenes + resto.imagenes, vistas.metodo, vistas.veredictos)
            if not vistas.imagenes:
                vistas.motivo = (vistas.motivo + " " + resto.motivo).strip()
        return vistas
    return _ronda_con(enviadas, None, titulo, angulo, cantidad, veredictos, primeras)


def _ronda_con(enviadas: list, imagenes, titulo: str, angulo: str, cantidad: int, veredictos: dict,
               primeras: Eleccion) -> Eleccion:
    from afterdrive.generacion import contexto_noticias
    from afterdrive.ia import llm

    con_vista = imagenes is not None
    print(f"  Eligiendo las imágenes con IA entre {len(enviadas)} foto(s)"
          f"{'' if con_vista else ' (sin verlas: por su noticia y su texto)'}...", flush=True)
    if con_vista:
        lista = "\n".join(f"{i}. Foto de la noticia \"{n.titulo}\"" for i, n in enumerate(enviadas, 1))
    else:
        lista = "\n".join(f"{i}. Noticia: \"{n.titulo}\" | texto alternativo: \"{n.imagen.get('alt', '')}\" | "
                          f"archivo: {_archivo(n.imagen['url'])}" for i, n in enumerate(enviadas, 1))
    pedido = f"Título de la nota: {titulo}\n" + (f"Ángulo: {angulo}\n" if angulo else "") + f"\nFotos:\n{lista}"
    try:
        crudo = llm.completar((_SYSTEM_VISION if con_vista else _SYSTEM_TEXTO).format(cantidad=cantidad), pedido,
                              temperature=0, max_tokens=1500, tarea="clasificacion",
                              **({"imagenes": imagenes} if con_vista else {}))
        respuesta = _leer(crudo, len(enviadas))
    except llm.Cancelada:
        raise
    except Exception as e:
        print(f"  [AVISO] La IA no pudo juzgar las fotos ({e}): van las primeras.", flush=True)
        primeras.motivo = f"La IA no pudo juzgar las fotos: {e}"
        primeras.veredictos = veredictos
        return primeras

    for i, n in enumerate(enviadas, 1):
        veredictos[n.imagen["url"]] = respuesta["fotos"].get(i, {"apta": False, "motivo": "La IA no la evaluó."})
    metodo = "ia" if con_vista else "ia-texto"
    elegidas = respuesta["elegidas"][:cantidad]
    if not elegidas:
        motivos = "; ".join(v["motivo"] for v in veredictos.values() if v.get("motivo"))
        print("  [AVISO] La IA descartó todas las fotos.", flush=True)
        return Eleccion([], metodo, veredictos, motivo=f"La IA descartó todas las fotos. {motivos}".strip())
    return Eleccion([contexto_noticias.imagen_de(enviadas[i - 1]) for i in elegidas], metodo, veredictos)


def _leer(crudo: str, total: int) -> dict:
    """{"fotos": {n: {"apta", "motivo"}}, "elegidas": [n, ...]}. ValueError si no hay JSON útil."""
    from afterdrive.ia.lm_studio import _extraer_json

    data = _extraer_json(crudo)
    if not isinstance(data, dict) or not isinstance(data.get("fotos"), list):
        raise ValueError("la respuesta no trae la lista de fotos")
    fotos = {}
    for f in data["fotos"]:
        if isinstance(f, dict) and isinstance(f.get("n"), int | float) and 1 <= int(f["n"]) <= total:
            fotos[int(f["n"])] = {"apta": f.get("apta") is True, "motivo": " ".join(str(f.get("motivo") or "").split())[:200]}
    crudas = data.get("elegidas")
    if crudas is None:   # formato anterior: una sola
        crudas = [data.get("elegida")] if data.get("elegida") is not None else []
    elegidas = []
    for e in crudas if isinstance(crudas, list) else []:
        if isinstance(e, int | float) and 1 <= int(e) <= total and int(e) not in elegidas \
                and fotos.get(int(e), {}).get("apta") is not False:   # una marcada como no apta no se usa
            elegidas.append(int(e))
    return {"fotos": fotos, "elegidas": elegidas}
