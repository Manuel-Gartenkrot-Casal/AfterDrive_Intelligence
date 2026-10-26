"""
traducciones.py — Las versiones de una Nota en los otros idiomas del blog, como borradores en HubSpot.

Uso (lo encola el servidor después de subir la nota a HubSpot; corre en la Cola):
    python -m afterdrive.traducciones <coleccion> <id>

Interfaz:
    activas() -> bool                         HUBSPOT_TRADUCCIONES=0 las apaga
    idiomas_destino(nota) -> ["pt", "en"]     los del blog menos el de la nota
    traducir(contenido, origen, destino) -> str       ErrorTraduccion
    subir(coleccion, item_id, base=None) -> {"subidas": [...], "errores": [...], "avisos": [...]}
    ErrorTraduccion

La nota se escribe en un idioma (el de sus regiones) y se sube a ese blog.
Acá se traduce a los otros dos (español, portugués, inglés) con la voz de
cada blog y cada versión se sube como borrador vinculado al post original
(ver hubspot.enviar_traduccion). Nunca se publica: el equipo revisa y publica
desde HubSpot.

La traducción queda guardada en la nota (`traducciones.<idioma>`) con la
huella del texto original: reenviar sin haber editado la nota no vuelve a
pagar la traducción, solo actualiza el borrador. Lo que devolvió HubSpot de
cada versión queda en `hubspot_traducciones.<idioma>`, así un reenvío
actualiza ese borrador en vez de crear otro.

La traducción no inventa: mismo Markdown, mismos enlaces (un enlace que no
estaba en el original se quita) y las secciones fijas con el título que les
toca en ese idioma. Si sale cortada o sin título, esa versión no se sube.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import sys

IDIOMAS = ("es", "pt", "en")
NOMBRE = {"es": "español", "pt": "portugués", "en": "inglés"}
LARGO_MINIMO = 0.6   # una traducción de menos del 60 % del original vino cortada

_SYSTEM = """\
Sos traductor editorial del blog B2B AfterDrive by Alephee (aftermarket automotor). Traducís una nota \
ya publicada al {idioma}, con {trato}, como la escribiría un periodista del sector de ese mercado.

Reglas:
- Mismo Markdown, línea por línea: el título con "# ", las secciones con "## ", las preguntas con "### ", \
listas, negritas y enlaces. No agregues ni quites secciones, párrafos ni información.
- Los enlaces se traducen solo en su texto: la URL entre paréntesis queda idéntica.
- Nombres de empresas, marcas, productos, plataformas y medios no se traducen (AfterDrive by Alephee, \
Alephee, Mercado Libre...). Cifras, monedas y fechas, iguales.
- Terminología del sector en ese idioma (en portugués: autopeças, reposição, oficina; en inglés: auto \
parts, aftermarket, repair shop; en español: repuestos, autopartes, taller).
- Estas secciones llevan exactamente este título en el idioma de destino:
{secciones}
- La última línea es la meta description en *cursiva*: traducila y que siga en cursiva, de 155 caracteres \
como máximo.

Respondé solo con la nota traducida, empezando por el título."""


class ErrorTraduccion(RuntimeError):
    """La traducción no salió usable, con un motivo apto para el usuario."""


def activas() -> bool:
    return os.getenv("HUBSPOT_TRADUCCIONES", "1").strip() != "0"


def idiomas_destino(nota: dict) -> list[str]:
    from afterdrive import hubspot
    origen = hubspot.idioma(nota)
    return [c for c in IDIOMAS if origen and c != origen]


def huella(contenido: str) -> str:
    return hashlib.sha1((contenido or "").strip().encode()).hexdigest()


def _urls(texto: str) -> set[str]:
    return set(re.findall(r"\]\((https?://[^)\s]+)\)", texto or ""))


def _limpiar(texto: str) -> str:
    """Saca un bloque ```markdown``` o un razonamiento <think> que se haya colado."""
    texto = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.DOTALL).strip()
    texto = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", texto).strip()
    titulo = re.search(r"(?m)^# ", texto)   # una frase de presentación antes del título se descarta
    return texto[titulo.start():] if titulo else texto


def traducir(contenido: str, origen: str, destino: str) -> str:
    """La nota en el idioma `destino` (es, pt, en). ErrorTraduccion si no sale usable."""
    from afterdrive.generacion import verificacion
    from afterdrive.ia import llm
    from afterdrive.ia.redaccion import voz_de_idioma

    vo, vd = voz_de_idioma(origen), voz_de_idioma(destino)
    secciones = "\n".join(f"  - \"{a}\" -> \"{b}\"" for a, b in ((vo.titulo_implicancias, vd.titulo_implicancias),
                                                               (vo.titulo_faq, vd.titulo_faq),
                                                               (vo.titulo_fuentes, vd.titulo_fuentes)))
    system = _SYSTEM.format(idioma=vd.idioma, trato=vd.trato, secciones=secciones)
    max_tokens = max(8000, llm.ajustes_redaccion().max_tokens)
    crudo = llm.completar(system, contenido, temperature=0.2, max_tokens=max_tokens, stream=True, tarea="traduccion")
    texto = _limpiar(crudo)
    if not texto.startswith("# "):
        raise ErrorTraduccion(f"la traducción al {NOMBRE[destino]} no empieza con el título")
    if len(texto) < len(contenido.strip()) * LARGO_MINIMO:
        raise ErrorTraduccion(f"la traducción al {NOMBRE[destino]} vino cortada")
    # Un enlace que no estaba en el original se quita (el texto queda).
    texto, quitados = verificacion.sanear_enlaces(texto, [], tuple(_urls(contenido)))
    if quitados:
        print(f"  [AVISO] Se quitaron {len(quitados)} enlace(s) que la traducción agregó.", flush=True)
    return texto


def subir(coleccion: str, item_id: str, base=None) -> dict:
    """Traduce lo que falte (o cambió) y sube cada versión a HubSpot como borrador."""
    from bson import ObjectId

    from afterdrive import hubspot
    from afterdrive.ia import consumo, llm

    if base is None:
        from afterdrive.db import db as base
    col = base[coleccion]
    doc = col.find_one({"_id": ObjectId(item_id)}, {"embedding": 0})
    if not doc:
        raise ErrorTraduccion("Nota no encontrada.")
    primario = (doc.get("hubspot") or {}).get("id")
    if not primario:
        raise ErrorTraduccion("La nota todavía no está en HubSpot: subila primero en su idioma.")
    origen = hubspot.idioma(doc)
    destinos = idiomas_destino(doc)
    if not destinos:
        raise ErrorTraduccion("La nota no está en un idioma de los blogs (español, portugués o inglés).")

    actual = huella(doc.get("contenido", ""))
    resultado = {"subidas": [], "errores": [], "avisos": []}
    with consumo.medir() as costo:
        for cod in destinos:
            nombre = NOMBRE[cod]
            guardada = (doc.get("traducciones") or {}).get(cod) or {}
            try:
                if guardada.get("huella") == actual and guardada.get("contenido"):
                    texto = guardada["contenido"]
                    print(f"[{cod}] La traducción al {nombre} ya estaba hecha: se actualiza el borrador.", flush=True)
                else:
                    print(f"[{cod}] Traduciendo al {nombre}...", flush=True)
                    texto = traducir(doc.get("contenido", ""), origen, cod)
                    col.update_one({"_id": doc["_id"]}, {"$set": {f"traducciones.{cod}": {
                        "contenido": texto, "huella": actual, "proveedor": llm.proveedor_activo(),
                        "traducido_en": datetime.datetime.now(datetime.UTC).isoformat()}}})
                previo = (doc.get("hubspot_traducciones") or {}).get(cod)
                print(f"[{cod}] Subiendo a HubSpot como borrador...", flush=True)
                r = hubspot.enviar_traduccion(doc, cod, texto, primario, previo=previo)
            except llm.Cancelada:
                raise
            except hubspot.ErrorHubSpotParcial as e:
                # El post se creó: se guarda su id para completarlo en el próximo intento.
                col.update_one({"_id": doc["_id"]}, {"$set": {f"hubspot_traducciones.{cod}": {
                    "id": e.post_id, "estado": "DRAFT", "vinculada": True, "error": str(e)}}})
                resultado["errores"].append(f"{nombre}: {e}")
                print(f"[ERROR] {nombre}: {e}", flush=True)
                continue
            except (ErrorTraduccion, llm.ErrorLLM, hubspot.ErrorHubSpot) as e:
                col.update_one({"_id": doc["_id"]}, {"$set": {f"hubspot_traducciones.{cod}.error": str(e)}})
                resultado["errores"].append(f"{nombre}: {e}")
                print(f"[ERROR] {nombre}: {e}", flush=True)
                continue
            aviso = r.pop("aviso", "")
            col.update_one({"_id": doc["_id"]}, {"$set": {f"hubspot_traducciones.{cod}": {
                **r, "enviado_en": datetime.datetime.now(datetime.UTC).isoformat(), **({"aviso": aviso} if aviso else {})}}})
            resultado["subidas"].append(cod)
            if aviso:
                resultado["avisos"].append(f"{nombre}: {aviso}")
                print(f"[AVISO] {nombre}: {aviso}", flush=True)
            print(f"[OK] {nombre}: borrador en HubSpot" + (" (vinculado al original)." if r.get("vinculada") else "."),
                  flush=True)
    if costo.llamadas:
        # Lo que costó traducir se suma al costo de la nota.
        col.update_one({"_id": doc["_id"]}, {"$inc": {
            "costo.total_usd": round(costo.total, 4), "costo.llamadas": costo.llamadas,
            **{f"costo.por_tarea.{t}": round(v, 4) for t, v in costo.por_tarea.items()}}})
    return resultado


def encolar(coleccion: str, item_id: str) -> dict | None:
    """{"id", "idiomas"} de la Corrida que traduce y sube las otras versiones, o None si no corresponde."""
    from bson import ObjectId

    from afterdrive import cola, historial
    from afterdrive import db as _db

    if not activas() or coleccion not in historial.COLECCIONES_CON_ESTADO:
        return None
    doc = _db.db[coleccion].find_one({"_id": ObjectId(item_id)}, {"regiones": 1, "hubspot": 1})
    idiomas = idiomas_destino(doc or {})
    if not doc or not (doc.get("hubspot") or {}).get("id") or not idiomas:
        return None
    nombres = " y ".join(NOMBRE[c] for c in idiomas)
    try:
        r = cola.encolar("script", {"modulo": "afterdrive.traducciones", "argv": [coleccion, item_id]},
                         etiqueta=f"Traducir al {nombres} y subir a HubSpot")
    except cola.ColaLlena as e:
        return {"error": str(e), "idiomas": idiomas}
    return {"id": r.get("id"), "idiomas": idiomas}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Versiones de una nota en los otros idiomas del blog (HubSpot)")
    parser.add_argument("coleccion")
    parser.add_argument("id")
    args = parser.parse_args(argv)
    try:
        r = subir(args.coleccion, args.id)
    except ErrorTraduccion as e:
        print(f"[ERROR] {e}", flush=True)
        return 1
    if r["errores"]:
        print(f"[ERROR] No se subieron todas las versiones: {'; '.join(r['errores'])}", flush=True)
        return 1
    print(f"[OK] Versiones subidas como borrador: {', '.join(NOMBRE[c] for c in r['subidas'])}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
