"""
imagen_destacada.py — Qué fotos van en una Nota: la destacada y CANTIDAD - 1 para el cuerpo.

Interfaz:
    elegir(noticias, titulo, angulo="", cantidad=CANTIDAD, extra=None, excluir=(), respaldo=None) -> Eleccion

Las candidatas son las fotos de las noticias de la nota (las que la respaldan
primero; cada noticia guarda varias), hasta MAX_FOTOS, sin repetir las que ya
están en otras notas. La IA las juzga según la pieza editable "imagenes"
(selección y reglas de portada) y devuelve las aptas en orden: la primera va como
destacada y las siguientes dentro del texto (hubspot.py las reparte entre las
secciones).

- Con la API paga (llm.ve_imagenes) el modelo de clasificación mira las fotos.
- Sin ella, el mismo modelo juzga sin verlas: por la noticia de la que salen,
  su texto alternativo y el nombre del archivo.

Si no se juntan `cantidad` fotos aptas, no se conforma: las busca en este
orden hasta completarlas (cada paso, solo las que faltan):
  1. las otras fotos de las páginas de sus noticias (las scrapeadas antes de
     que se guardaran todas se releen);
  2. otras noticias del mismo tema (`extra`);
  3. bancos de imágenes (`respaldo`, ver imagenes_respaldo.py): una búsqueda
     por ronda, hasta MAX_RONDAS_RESPALDO.
Solo si después de todo eso faltan, la nota sale con menos y el motivo queda
para mostrarlo al revisarla.

Una foto guardada que el sitio ya no sirve (404) se vuelve a buscar en la
página de la noticia. Si la IA falla, no se agregan fotos sin evaluar: la nota
conserva solo las que ya pasaron los criterios editoriales.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

CANTIDAD = 5        # destacada + 4 en el cuerpo
MAX_FOTOS = 12      # fotos que la IA mira por pasada
MAX_BUSQUEDAS = 5   # páginas de noticias viejas que se descargan para buscarles la foto
MAX_RONDAS_RESPALDO = 8   # búsquedas en bancos de imágenes antes de rendirse
REFRESCOS = 3       # fotos que dejaron de responder: se relee su página para tomar la actual
# Bedrock rechaza imágenes de más de 3,75 MB en Converse.
MAX_BYTES_IA = 3_750_000

_CRITERIOS = """\
Aplicá estas reglas editoriales vigentes para decidir qué fotos son aptas y cuáles pueden ser portada:
{criterios}

En cada foto indicá "personas": true si se ve una persona o parte de una (cara, cuerpo, manos), aunque sea
chica o de fondo. Es una descripción, no un veto: "portada" indica si la foto puede ser portada según las
reglas editoriales de arriba. "apta" indica si se puede usar en la nota. No inventes restricciones adicionales.
Ordená las aptas según esas reglas ("elegidas", como mucho {cantidad}). Si ninguna es apta, "elegidas" es [].

Respondé solo con este JSON, una entrada por foto en el orden recibido:
{{"fotos": [{{"n": 1, "apta": true, "portada": true, "personas": false, "motivo": "una oración en español"}}], "elegidas": [1]}}"""

SIN_PORTADA = "Ninguna foto apta cumple las reglas de portada vigentes o se puede usar sin crédito."

_SYSTEM_VISION = ("Sos el editor de fotografía del blog B2B AfterDrive by Alephee (aftermarket automotor en "
                  "Latinoamérica). Elegís las fotos de una nota entre las de las noticias que usa.\n\n" + _CRITERIOS)

_SYSTEM_TEXTO = ("Sos el editor de fotografía del blog B2B AfterDrive by Alephee (aftermarket automotor en "
                 "Latinoamérica). Elegís las fotos de una nota entre las de las noticias que usa, SIN verlas: "
                 "solo tenés el título de la noticia de la que sale cada foto, su texto alternativo y el nombre "
                 "del archivo. Juzgá qué muestra probablemente cada una y aplicá las mismas reglas editoriales.\n\n"
                 + _CRITERIOS)


def _permite_portada(veredicto: dict) -> bool:
    """La IA aplica el prompt vigente; respuestas viejas conservan la regla original."""
    return veredicto.get("portada", not veredicto.get("personas")) is True


@dataclass
class Eleccion:
    imagenes: list[dict]                # campo `imagen` de cada una, en orden (la primera es la destacada)
    metodo: str                         # "ia", "ia-texto", "sin-evaluar" o "ninguna"
    veredictos: dict = field(default_factory=dict)   # url -> {apta, portada, personas, motivo}
    motivo: str = ""                    # por qué no hay imagen o por qué no decidió la IA

    def _no_portada(self, im: dict) -> bool:
        """El prompt no la admite de portada, o pide crédito (HubSpot no lo muestra ahí)."""
        return not _permite_portada(self.veredictos.get(im["url"], {})) or bool(im.get("atribucion"))

    @property
    def imagen(self) -> dict | None:
        """La portada: la primera foto, si cumple las reglas vigentes y no pide crédito."""
        return self.imagenes[0] if self.imagenes and not self._no_portada(self.imagenes[0]) else None

    @property
    def cuerpo(self) -> list[dict]:
        """Las que van dentro del texto (pueden tener personas)."""
        return self.imagenes[1:] if self.imagen else self.imagenes[:CANTIDAD - 1]

    def ordenar(self, cantidad: int) -> Eleccion:
        """Pone primero la primera foto que puede ser portada y deja `cantidad`."""
        libres = [im for im in self.imagenes if not self._no_portada(im)]
        if libres:
            self.imagenes = [libres[0]] + [im for im in self.imagenes if im is not libres[0]]
        elif self.imagenes:
            self.motivo = SIN_PORTADA
        self.imagenes = self.imagenes[:cantidad]
        return self

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


def fotos_usadas(dias: int | None = None, base=None) -> set[str]:
    """URLs de las fotos (destacada y del cuerpo) de las notas de los últimos `dias`.

    Cuando ya se usaron todas las noticias, las notas salen de las mismas
    noticias y sin esto llevaban siempre las mismas fotos.
    """
    import datetime

    from afterdrive.generacion.contexto_noticias import DIAS_SIN_REPETIR
    if base is None:
        from afterdrive.db import db as base
    desde = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=dias or DIAS_SIN_REPETIR)).isoformat()
    usadas = set()
    campos = {f"{c}.{k}": 1 for c in ("imagen", "imagenes_cuerpo") for k in ("url", "banco", "origen.url")}
    for d in base.notas_fase2.find({"generado_en": {"$gte": desde}}, campos):
        for im in [d.get("imagen") or {}] + (d.get("imagenes_cuerpo") or []):
            if im.get("url"):
                usadas.add(im["url"])
            # Las de bancos también por su página: el link de Pixabay cambia en cada búsqueda y,
            # guardada en la base, la foto queda con una URL interna.
            if im.get("banco") and (im.get("origen") or {}).get("url"):
                usadas.add(im["origen"]["url"])
    return usadas


def _vista(n, vistas: set[str]) -> bool:
    """La foto ya está en otra nota o ya se miró: por su URL o, si es de un banco, por su página."""
    return n.imagen["url"] in vistas or (n.id is None and n.url in vistas)


def _faltan(eleccion: Eleccion, cantidad: int) -> int:
    """Fotos que faltan; al menos 1 si hay fotos pero ninguna sirve de portada."""
    return max(cantidad - len(eleccion.imagenes), 0 if eleccion.imagen or not eleccion.imagenes else 1)


def _sumar(eleccion: Eleccion, otra: Eleccion, cantidad: int) -> Eleccion:
    imagenes = eleccion.imagenes + otra.imagenes
    veredictos = {**eleccion.veredictos, **otra.veredictos}
    if not imagenes:
        return Eleccion([], otra.metodo, veredictos, motivo=f"{eleccion.motivo} {otra.motivo}".strip())
    return Eleccion(imagenes, eleccion.metodo if eleccion.imagenes else otra.metodo, veredictos).ordenar(cantidad)


def elegir(noticias: list, titulo: str, angulo: str = "", cantidad: int = CANTIDAD, extra=None,
           excluir: set[str] = frozenset(), respaldo=None) -> Eleccion:
    """Elige `cantidad` fotos (menos solo si se agotaron todas las fuentes). Nunca lanza, salvo una
    cancelación desde el dashboard.

    extra: función sin argumentos que devuelve más noticias del mismo tema.
    excluir: fotos que ya están en otras notas (ver fotos_usadas): no se repiten.
    respaldo: función ronda -> fotos de bancos de imágenes (imagenes_respaldo.buscador).
    """
    from afterdrive.generacion import contexto_noticias
    from afterdrive.ia import llm

    con_foto = contexto_noticias.con_foto(noticias, max_busquedas=MAX_BUSQUEDAS, limite=MAX_FOTOS)
    todas = _unicas(contexto_noticias.todas_las_fotos(con_foto))
    candidatas = [n for n in todas if n.imagen["url"] not in excluir][:MAX_FOTOS]
    if candidatas:
        eleccion = _ronda(candidatas, titulo, angulo, cantidad)
    elif todas:
        eleccion = Eleccion([], "ninguna", motivo="Las fotos de sus noticias ya están en otras notas.")
    else:
        eleccion = Eleccion([], "ninguna", motivo="Ninguna noticia de la nota tiene foto.")
    eleccion.ordenar(cantidad)
    if eleccion.metodo == "sin-evaluar":   # sin evaluador no se agregan fotos sin revisar
        return eleccion
    vistas = {n.imagen["url"] for n in candidatas} | set(excluir)
    urls_nota = {n.url for n in noticias}

    def de_otras_noticias():
        mas = [n for n in extra() if n.url not in urls_nota]
        return contexto_noticias.todas_las_fotos(
            contexto_noticias.con_foto(mas, max_busquedas=MAX_BUSQUEDAS, limite=MAX_FOTOS))

    pasos = [("otras fotos de las páginas de sus noticias",
              lambda: contexto_noticias.mas_fotos(noticias, max_busquedas=MAX_BUSQUEDAS) + todas)]
    if extra is not None:
        pasos.append(("otras noticias del tema", de_otras_noticias))
    if respaldo is not None:
        pasos += [("bancos de imágenes", lambda r=r: respaldo(r)) for r in range(MAX_RONDAS_RESPALDO)]
    for nombre, buscar in pasos:
        faltan = _faltan(eleccion, cantidad)
        if faltan <= 0:
            break
        # Están todas pero ninguna sirve de portada: una foto que pide crédito tampoco serviría.
        solo_portada = len(eleccion.imagenes) >= cantidad and not eleccion.imagen
        try:
            nuevas = [n for n in _unicas(buscar()) if not _vista(n, vistas)
                      and not (solo_portada and n.imagen.get("atribucion"))][:MAX_FOTOS]
        except llm.Cancelada:
            raise
        except Exception as e:
            print(f"  [AVISO] No se pudieron buscar más fotos en {nombre}: {e}", flush=True)
            continue
        if not nuevas:
            continue
        vistas |= {n.imagen["url"] for n in nuevas} | {n.url for n in nuevas if n.id is None}
        que = "la portada" if solo_portada else f"{faltan} imagen(es) apta(s)"
        print(f"  Falta {que}: se busca entre {len(nuevas)} foto(s) de {nombre}.", flush=True)
        otra = _ronda(nuevas, titulo, angulo, faltan, portada=solo_portada)
        if otra.metodo == "sin-evaluar":
            if not eleccion.imagenes:
                return otra
            eleccion.veredictos.update(otra.veredictos)
            eleccion.motivo = f"{eleccion.motivo} {otra.motivo}".strip()
            return eleccion
        eleccion = _sumar(eleccion, otra, cantidad)
    faltan = _faltan(eleccion, cantidad)
    if faltan > 0 and eleccion.imagenes:
        aviso = f"Se consiguieron {len(eleccion.imagenes)} de {cantidad} fotos: no hubo más aptas sin repetir."
        eleccion.motivo = f"{eleccion.motivo} {aviso}".strip()
        print(f"  [AVISO] {aviso}", flush=True)
    return eleccion


def _descargar(n, refrescos: list[int]) -> tuple[bytes, str]:
    """Bytes de la foto de la noticia. Si el sitio ya no la sirve (4xx), se vuelve a leer la
    página de la noticia una vez para tomar su foto actual (hasta `refrescos` por nota)."""
    from afterdrive import imagen_web
    from afterdrive.generacion import contexto_noticias

    try:
        return imagen_web.descargar(n.imagen["url"], max_bytes=MAX_BYTES_IA)
    except imagen_web.ErrorDescarga as e:
        if refrescos[0] <= 0 or "respondió 4" not in str(e) or not getattr(n, "refrescable", True):
            raise
        refrescos[0] -= 1
        if contexto_noticias.refrescar_imagen(n) is None:
            raise
        print(f"  La foto de '{n.titulo[:50]}' cambió en su página: se usa la actual.", flush=True)
        return imagen_web.descargar(n.imagen["url"], max_bytes=MAX_BYTES_IA)


def _no_bajada(n, error) -> dict:
    return {"apta": False, "personas": False, "motivo": f"No se pudo descargar ({error}): en el blog saldría rota."}


def _bajables(candidatas: list, refrescos: list[int], veredictos: dict) -> list:
    """Las que se pueden descargar. Las otras quedan en los veredictos como no aptas: si este servidor
    no puede bajarla, tampoco se puede copiar a HubSpot y en el blog sale rota."""
    from afterdrive import imagen_web

    buenas = []
    for n in candidatas:
        try:
            _descargar(n, refrescos)
            buenas.append(n)
        except imagen_web.ErrorDescarga as e:
            print(f"  [AVISO] No se pudo descargar la foto de '{n.titulo[:50]}': {e}", flush=True)
            veredictos[n.imagen["url"]] = _no_bajada(n, e)
    return buenas


def _ronda(candidatas: list, titulo: str, angulo: str, cantidad: int, ver: bool | None = None,
           portada: bool = False) -> Eleccion:
    """Una pasada de la IA sobre las candidatas. ver=False la obliga a juzgar sin mirar las fotos.
    portada=True: solo falta una foto que cumpla las reglas vigentes de portada.

    Una foto que no se puede descargar no se elige nunca (antes completaba los lugares que faltaban,
    juzgada por su texto, y en HubSpot salía rota): faltan fotos, y elegir() las busca en otro lado.
    """
    from afterdrive.generacion import contexto_noticias
    from afterdrive.ia import llm

    veredictos, refrescos = {}, [REFRESCOS]
    if ver is not False and llm.ve_imagenes():
        from afterdrive import imagen_web
        enviadas, imagenes = [], []
        for n in candidatas:
            try:
                imagenes.append(_descargar(n, refrescos))
                enviadas.append(n)
            except imagen_web.ErrorDescarga as e:
                print(f"  [AVISO] No se pudo descargar la foto de '{n.titulo[:50]}': {e}", flush=True)
                veredictos[n.imagen["url"]] = _no_bajada(n, e)
        if not enviadas:
            return Eleccion([], "ia", veredictos, motivo="No se pudo descargar ninguna de estas fotos.")
        return _ronda_con(enviadas, imagenes, titulo, angulo, cantidad, veredictos, portada)
    # Sin verlas: la IA juzga por el texto y después se comprueba que las elegidas se puedan bajar.
    eleccion = _ronda_con(candidatas, None, titulo, angulo, cantidad, veredictos, portada)
    por_url = {n.imagen["url"]: n for n in candidatas}
    elegidas = [por_url[im["url"]] for im in eleccion.imagenes if im["url"] in por_url]
    buenas = _bajables(elegidas, refrescos, eleccion.veredictos)
    if len(buenas) < len(elegidas):
        eleccion.imagenes = [contexto_noticias.imagen_de(n) for n in buenas]
        if not eleccion.imagenes:
            eleccion.motivo = (eleccion.motivo + " No se pudo descargar ninguna de las elegidas.").strip()
    return eleccion


def _ronda_con(enviadas: list, imagenes, titulo: str, angulo: str, cantidad: int, veredictos: dict,
               portada: bool = False) -> Eleccion:
    from afterdrive.generacion import contexto_noticias
    from afterdrive.ia import llm, redaccion

    con_vista = imagenes is not None
    print(f"  Eligiendo las imágenes con IA entre {len(enviadas)} foto(s)"
          f"{'' if con_vista else ' (sin verlas: por su noticia y su texto)'}...", flush=True)
    if con_vista:
        lista = "\n".join(f"{i}. Foto de la noticia \"{n.titulo}\"" for i, n in enumerate(enviadas, 1))
    else:
        lista = "\n".join(f"{i}. Noticia: \"{n.titulo}\" | texto alternativo: \"{n.imagen.get('alt', '')}\" | "
                          f"archivo: {_archivo(n.imagen['url'])}" for i, n in enumerate(enviadas, 1))
    pedido = f"Título de la nota: {titulo}\n" + (f"Ángulo: {angulo}\n" if angulo else "") + f"\nFotos:\n{lista}"
    if portada:
        pedido += ("\n\nLa nota ya tiene sus fotos del texto: solo falta la PORTADA. Elegí primero una foto "
                   "apta que cumpla las reglas editoriales vigentes de portada.")
    try:
        system = (_SYSTEM_VISION if con_vista else _SYSTEM_TEXTO).format(
            cantidad=cantidad, criterios=redaccion.texto("imagenes"))
        crudo = llm.completar(system, pedido,
                              temperature=0, max_tokens=1500, tarea="clasificacion",
                              **({"imagenes": imagenes} if con_vista else {}))
        respuesta = _leer(crudo, len(enviadas))
    except llm.Cancelada:
        raise
    except Exception as e:
        motivo = f"No se agregaron fotos sin evaluar: la IA no pudo comprobar su relación con la nota ({e})."
        print(f"  [AVISO] {motivo}", flush=True)
        for n in enviadas:
            veredictos[n.imagen["url"]] = {"apta": False, "portada": False, "motivo": motivo}
        return Eleccion([], "sin-evaluar", veredictos, motivo=motivo)

    for i, n in enumerate(enviadas, 1):
        veredictos[n.imagen["url"]] = respuesta["fotos"].get(i, {"apta": False, "motivo": "La IA no la evaluó."})
    metodo = "ia" if con_vista else "ia-texto"
    elegidas = respuesta["elegidas"][:cantidad]
    fotos = respuesta["fotos"]
    def puede_ser_portada(i: int) -> bool:
        return _permite_portada(fotos.get(i, {})) and not enviadas[i - 1].imagen.get("atribucion")

    if elegidas and not any(puede_ser_portada(i) for i in elegidas):
        # Ninguna elegida cumple las reglas de portada: entra una apta que sí sirva, si hay.
        libre = next((i for i in sorted(fotos) if fotos[i]["apta"] and puede_ser_portada(i)
                      and i not in elegidas), None)
        if libre:
            elegidas = [libre] + elegidas[:cantidad - 1]
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
            fotos[int(f["n"])] = {"apta": f.get("apta") is True, "personas": f.get("personas") is True,
                                  "motivo": " ".join(str(f.get("motivo") or "").split())[:200]}
            if isinstance(f.get("portada"), bool):
                fotos[int(f["n"])]["portada"] = f["portada"]
    crudas = data.get("elegidas")
    if crudas is None:   # formato anterior: una sola
        crudas = [data.get("elegida")] if data.get("elegida") is not None else []
    elegidas = []
    for e in crudas if isinstance(crudas, list) else []:
        if isinstance(e, int | float) and 1 <= int(e) <= total and int(e) not in elegidas \
                and fotos.get(int(e), {}).get("apta") is True:   # solo fotos evaluadas y aprobadas explícitamente
            elegidas.append(int(e))
    return {"fotos": fotos, "elegidas": elegidas}
