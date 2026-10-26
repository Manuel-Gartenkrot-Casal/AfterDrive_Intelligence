"""
aprobacion_auto.py — Aprobar sola una Nota de la generación programada, si el switch está prendido.

Interfaz:
    procesar(coleccion, item_id, base=None) -> dict | None   None = switch apagado o nota inexistente

Pasos (ver generacion/juez.py):
1. Filtro duro sin IA y juicio del editor crítico (ya guardado en la nota al generarla).
2. Si pasa: estado "aprobada" (aprobada_por = "ia") y sube a HubSpot como BORRADOR, al blog
   que diga el switch de blog_test; después se encolan las traducciones. Nunca publica.
3. Si no pasa: queda en borrador con los motivos, para que la revise una persona.

La decisión queda en la nota (`aprobacion_auto`) en los dos casos.
"""

from __future__ import annotations

import datetime

from bson import ObjectId

from afterdrive import config_store, historial
from afterdrive import db as _db
from afterdrive.generacion import juez


def procesar(coleccion: str, item_id: str, base=None) -> dict | None:
    if not config_store.get_aprobacion_auto_config():
        return None
    col = (base if base is not None else _db.db)[coleccion]
    doc = col.find_one({"_id": ObjectId(item_id)}, {"embedding": 0})
    if not doc:
        return None
    decision = {**juez.decidir(doc), "fecha": datetime.datetime.now(datetime.UTC).isoformat()}
    if not decision["pasa"]:
        col.update_one({"_id": doc["_id"]}, {"$set": {"aprobacion_auto": decision}})
        print(f"[Aprobación automática] No pasa: {'; '.join(decision['motivos'])}", flush=True)
        return decision

    historial.cambiar_estado(coleccion, item_id, _db.ESTADO_APROBADA, base=base)
    col.update_one({"_id": doc["_id"]}, {"$set": {"aprobacion_auto": decision, "aprobada_por": "ia"}})
    print("[Aprobación automática] Aprobada por la IA.", flush=True)

    from afterdrive import hubspot, traducciones
    if not hubspot.configurado():
        decision["hubspot"] = "HubSpot no está configurado: queda aprobada sin subir."
    else:
        try:
            item = historial.enviar_a_hubspot(coleccion, item_id, publicar=False, base=base)
            decision["hubspot"] = (item or {}).get("hubspot", {}).get("url") or "subida como borrador"
            decision["traducciones"] = traducciones.encolar(coleccion, item_id)
        except Exception as e:  # la aprobación vale igual; el envío se reintenta a mano
            decision["hubspot"] = f"No se pudo subir a HubSpot: {e}"
    print(f"[Aprobación automática] HubSpot: {decision['hubspot']}", flush=True)
    col.update_one({"_id": doc["_id"]}, {"$set": {"aprobacion_auto": decision}})
    return decision
