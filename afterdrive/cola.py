"""
cola.py — La Cola de Corridas: las que llegan mientras otra corre esperan su turno.

Antes, una Corrida que llegaba con otra en curso se rechazaba (ADR-0001) y el
scheduler perdía la programada sin aviso. Ahora se encola y corre después.
Ver docs/adr/0002-cola-de-corridas.md.

Interfaz:
    encolar(tipo, params=None, origen="manual") -> dict   {"id", "posicion", "duplicada"}
    listar() -> dict                                      {"en_curso", "pendientes", "recientes"}
    log(id, desde=0) -> dict | None                       líneas nuevas + estado
    cancelar(id) -> dict
    iniciar()                                             arranca el consumidor (lo llama el scheduler)
    procesar_pendientes()                                 corre lo pendiente, en este thread

Tipos:
    scraping    in-process, todas las Fuentes activas. Se cancela entre fuente y fuente.
    generacion  in-process, Nota Fase 2 (sin params usa la config guardada). No se corta a mitad.
    script      subprocess de un módulo del pipeline ({"modulo", "argv"}). Cancelar lo mata.
                El módulo lo arma el servidor, nunca viene del cliente.

La cola vive en Mongo (colección `corridas`) para que un redeploy no pierda las
pendientes. Corre una sola a la vez: el consumidor es un único thread y además
toma el lock de corridas.py. Depende de gunicorn --workers 1; el claim con
find_one_and_update ya es atómico, pero el lock de corridas.py no lo es entre procesos.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import sys
import threading
import time

from afterdrive import corridas
from afterdrive.ia import llm

MAX_PENDIENTES = 5
LINEAS_GUARDADAS = 500
RECIENTES = 20
TERMINALES = ("ok", "error", "cancelada", "interrumpida")

ETIQUETAS = {"scraping": "Buscar noticias", "generacion": "Generar nota"}


class ColaLlena(RuntimeError):
    pass


class NoCancelable(RuntimeError):
    pass


# Cancelar una Corrida levanta corridas._cancelar; la IA lo consulta antes de
# cada llamada y en cada fragmento de una respuesta por streaming.
llm.al_cancelar(corridas._cancelar.is_set)


_despertar = threading.Event()
_estado = threading.Lock()   # protege _actual, _lineas y _proc
_actual: str | None = None   # id de la Corrida en curso
_lineas: list[str] = []      # log en memoria de la Corrida en curso
_proc = None                 # subprocess en curso (tipo script)
_tipo_actual: str | None = None
_volcado = 0.0               # última vez que el log en curso se guardó en Mongo
VOLCAR_CADA_S = 5            # para que otro proceso (el dashboard) vea el log en vivo


def _col():
    from afterdrive.db import db
    return db["corridas"]


def _ahora() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _clave(tipo: str, params: dict | None) -> str:
    return json.dumps({"tipo": tipo, "params": params or {}}, sort_keys=True, ensure_ascii=False)


def _publica(doc: dict) -> dict:
    """Lo que ve el dashboard: sin el log ni la clave interna."""
    return {
        "id": str(doc["_id"]),
        "tipo": doc["tipo"],
        "etiqueta": doc.get("etiqueta") or doc["tipo"],
        "origen": doc.get("origen", "manual"),
        "estado": doc["estado"],
        "creada": doc.get("creada"),
        "inicio": doc.get("inicio"),
        "fin": doc.get("fin"),
        "error": (doc.get("resultado") or {}).get("error"),
    }


# ── Encolar ───────────────────────────────────────────────────────────────────


def encolar(tipo: str, params: dict | None = None, origen: str = "manual", etiqueta: str | None = None) -> dict:
    """Agrega una Corrida a la cola. Si ya hay una idéntica pendiente, devuelve esa."""
    if tipo not in ("scraping", "generacion", "script"):
        raise ValueError(f"Tipo de Corrida desconocido: {tipo}")
    col = _col()
    clave = _clave(tipo, params)
    existente = col.find_one({"estado": "pendiente", "clave": clave})
    if existente:
        return {"id": str(existente["_id"]), "posicion": _posicion(existente), "duplicada": True}
    if col.count_documents({"estado": "pendiente"}) >= MAX_PENDIENTES:
        raise ColaLlena(f"Ya hay {MAX_PENDIENTES} corridas esperando. Esperá a que avancen.")
    doc = {
        "tipo": tipo,
        "params": params or {},
        "clave": clave,
        "etiqueta": etiqueta or ETIQUETAS.get(tipo, tipo),
        "origen": origen,
        "estado": "pendiente",
        "creada": _ahora(),
    }
    doc["_id"] = col.insert_one(doc).inserted_id
    print(f"[Cola] Encolada '{doc['etiqueta']}' ({origen}).", flush=True)
    _despertar.set()
    return {"id": str(doc["_id"]), "posicion": _posicion(doc), "duplicada": False}


def _posicion(doc: dict) -> int:
    """1 = la próxima en correr."""
    return _col().count_documents({"estado": "pendiente", "creada": {"$lt": doc["creada"]}}) + 1


# ── Consultar ─────────────────────────────────────────────────────────────────


def listar() -> dict:
    col = _col()
    en_curso = col.find_one({"estado": "en_curso"})
    pendientes = list(col.find({"estado": "pendiente"}).sort("creada", 1))
    recientes = list(col.find({"estado": {"$in": list(TERMINALES)}}).sort("fin", -1).limit(RECIENTES))
    return {
        "en_curso": _publica(en_curso) if en_curso else None,
        "pendientes": [_publica(d) for d in pendientes],
        "recientes": [_publica(d) for d in recientes],
    }


def _buscar(id_: str):
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        return _col().find_one({"_id": ObjectId(id_)})
    except (InvalidId, TypeError):
        return None


def log(id_: str, desde: int = 0) -> dict | None:
    """Líneas del log desde la posición `desde`, para leer por polling."""
    doc = _buscar(id_)
    if not doc:
        return None
    with _estado:
        lineas = list(_lineas) if _actual == id_ else list(doc.get("log") or [])
    desde = max(0, desde)
    respuesta = {
        **_publica(doc),
        "lineas": lineas[desde:],
        "siguiente": max(desde, len(lineas)),
        "resultado": doc.get("resultado"),
    }
    if doc["estado"] == "pendiente":
        respuesta["posicion"] = _posicion(doc)
    return respuesta


# ── Cancelar ──────────────────────────────────────────────────────────────────


def cancelar(id_: str) -> dict:
    col = _col()
    doc = _buscar(id_)
    if not doc:
        raise KeyError(id_)
    if doc["estado"] == "pendiente":
        r = col.update_one(
            {"_id": doc["_id"], "estado": "pendiente"},
            {"$set": {"estado": "cancelada", "fin": _ahora()}},
        )
        if r.modified_count:
            return {"estado": "cancelada"}
        doc = col.find_one({"_id": doc["_id"]})  # justo arrancó: se trata como en curso
    if doc["estado"] != "en_curso":
        return {"estado": doc["estado"]}
    with _estado:
        local = _actual == id_
    if not local:
        if doc.get("ejecutor") == "github":
            # Corre en otro proceso: se deja el pedido y el ejecutor lo lee al volcar el log.
            _col().update_one({"_id": doc["_id"]}, {"$set": {"cancelar_pedido": True}})
            return {"estado": "cancelando"}
        return {"estado": doc["estado"]}
    with _estado:
        # La generación corre en este proceso: llm la corta en la próxima
        # llamada o fragmento (ver llm.Cancelada) y la nota no se guarda.
        corridas._cancelar.set()
        if _proc is not None and _proc.poll() is None:
            _proc.kill()
    return {"estado": "cancelando"}


# ── Consumidor ────────────────────────────────────────────────────────────────


class _Tee(io.TextIOBase):
    """stdout que además guarda cada línea en el log de la Corrida en curso.

    redirect_stdout es global: lo que otros threads impriman mientras tanto
    también cae en el log. Se acepta: es una sola Corrida a la vez y todo sigue
    saliendo por el stdout real (los logs de Render no cambian).
    """

    def __init__(self, real):
        self._real = real
        self._pendiente = ""

    def write(self, s):
        self._real.write(s)
        self._pendiente += s
        *completas, self._pendiente = self._pendiente.split("\n")
        completas = [ln for ln in completas if not ln.startswith("[Cola]")]  # avisos de la propia cola
        if completas:
            _agregar(completas)
        return len(s)

    def flush(self):
        self._real.flush()

    def cerrar(self):
        if self._pendiente:
            _agregar([self._pendiente])
            self._pendiente = ""


def _agregar(lineas: list[str]) -> None:
    global _volcado
    with _estado:
        _lineas.extend(ln.rstrip("\r") for ln in lineas)
        if time.monotonic() - _volcado < VOLCAR_CADA_S or _actual is None:
            return
        _volcado = time.monotonic()
        id_, copia = _actual, list(_lineas[-LINEAS_GUARDADAS:])
    _volcar(id_, copia)


def _volcar(id_: str, lineas: list[str]) -> None:
    """Guarda el log parcial y mira si desde otro proceso pidieron cancelar.

    Hace falta cuando la Corrida corre en GitHub Actions: el dashboard está en
    otro proceso y solo ve lo que hay en Mongo.
    """
    from bson import ObjectId
    try:
        doc = _col().find_one_and_update(
            {"_id": ObjectId(id_)}, {"$set": {"log": lineas}}, projection={"cancelar_pedido": 1})
    except Exception:
        return
    if doc and doc.get("cancelar_pedido"):
        corridas._cancelar.set()
        with _estado:
            if _proc is not None and _proc.poll() is None:
                _proc.kill()


def _ejecutar(doc: dict) -> dict:
    """Corre la Corrida (el lock ya está tomado) y devuelve su resultado."""
    global _proc
    tipo, params = doc["tipo"], doc.get("params") or {}
    if tipo in ("scraping", "generacion"):
        tee = _Tee(sys.stdout)
        try:
            with contextlib.redirect_stdout(tee):
                if tipo == "scraping":
                    return corridas._scrapear_fuentes(params.get("max_articulos"))
                return corridas._generar(params or None)
        finally:
            tee.cerrar()

    def _guardar_proc(p):
        global _proc
        with _estado:
            _proc = p

    for linea in corridas._subproceso(params["modulo"], params.get("argv") or [], al_iniciar=_guardar_proc):
        _agregar([linea.rstrip("\n")])
    with _estado:
        proc, _proc = _proc, None
    if corridas._cancelar.is_set():
        return {"success": False, "error": "Cancelada."}
    codigo = proc.returncode if proc is not None else None
    if codigo == 0:
        return {"success": True}
    return {"success": False, "error": f"El proceso terminó con código {codigo}."}


def _correr(doc: dict) -> None:
    global _actual, _tipo_actual
    id_ = str(doc["_id"])
    with corridas._reservar(doc.get("etiqueta") or doc["tipo"], esperar=True):
        corridas._cancelar.clear()
        with _estado:
            _actual, _tipo_actual = id_, doc["tipo"]
            _lineas.clear()
        try:
            resultado = _ejecutar(doc)
        except Exception as e:
            _agregar([f"[ERROR] {e}"])
            resultado = {"success": False, "error": str(e)}
        cancelada = corridas._cancelar.is_set()
        corridas._cancelar.clear()
        estado = "cancelada" if cancelada else ("ok" if resultado.get("success") else "error")
        with _estado:
            lineas = list(_lineas)
        _col().update_one({"_id": doc["_id"]}, {"$set": {
            "estado": estado,
            "fin": _ahora(),
            "resultado": {k: v for k, v in resultado.items() if isinstance(v, (str, int, float, bool, type(None)))},
            "log": lineas[-LINEAS_GUARDADAS:],
        }})
        with _estado:
            _actual = _tipo_actual = None
            _lineas.clear()
    print(f"[Cola] '{doc.get('etiqueta')}' terminó: {estado}.", flush=True)


def _tomar_siguiente():
    """Marca como en curso la pendiente más vieja y la devuelve (atómico)."""
    from pymongo import ReturnDocument
    return _col().find_one_and_update(
        {"estado": "pendiente"},
        {"$set": {"estado": "en_curso", "inicio": _ahora(), "ejecutor": "servidor"}},
        sort=[("creada", 1)],
        return_document=ReturnDocument.AFTER,
    )


def procesar_pendientes() -> int:
    """Corre todas las pendientes, una tras otra. Devuelve cuántas corrió."""
    n = 0
    while (doc := _tomar_siguiente()) is not None:
        _correr(doc)
        n += 1
    return n


MAX_HORAS_EXTERNA = 3   # una Corrida de GitHub Actions que pasó esto sin terminar, murió


def recuperar_al_arrancar() -> None:
    """Las que estaban en curso cuando el proceso murió no se reintentan: quedan marcadas.

    Las que corren en GitHub Actions no dependen de este servidor: solo se
    marcan si llevan más de MAX_HORAS_EXTERNA (el runner murió sin avisar).
    """
    limite = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=MAX_HORAS_EXTERNA)).isoformat()
    r = _col().update_many(
        {"estado": "en_curso", "$or": [{"ejecutor": {"$ne": "github"}}, {"inicio": {"$lt": limite}}]},
        {"$set": {"estado": "interrumpida", "fin": _ahora(),
                  "resultado": {"success": False, "error": "Se cortó mientras corría (reinicio o runner caído)."}}},
    )
    if r.modified_count:
        print(f"[Cola] {r.modified_count} corrida(s) interrumpida(s) por un reinicio.", flush=True)


def ejecutar_aca(tipo: str, params: dict | None = None, origen: str = "cron", ejecutor: str = "github",
                 etiqueta: str | None = None) -> str:
    """Corre una Corrida en ESTE proceso sin pasar por la espera de la cola.

    Para GitHub Actions: la Corrida queda registrada en la colección (el
    dashboard la ve con su log) pero la ejecuta el runner. Devuelve el estado final.
    """
    doc = {
        "tipo": tipo, "params": params or {}, "clave": _clave(tipo, params),
        "etiqueta": etiqueta or ETIQUETAS.get(tipo, tipo), "origen": origen,
        "estado": "en_curso", "creada": _ahora(), "inicio": _ahora(), "ejecutor": ejecutor,
    }
    doc["_id"] = _col().insert_one(doc).inserted_id
    _correr(doc)
    return _col().find_one({"_id": doc["_id"]}, {"estado": 1})["estado"]


DIAS_HISTORIAL = 30


def limpiar_viejas() -> int:
    """Borra del historial las Corridas terminadas hace más de DIAS_HISTORIAL días."""
    limite = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=DIAS_HISTORIAL)).isoformat()
    r = _col().delete_many({"estado": {"$in": list(TERMINALES)}, "fin": {"$lt": limite}})
    if r.deleted_count:
        print(f"[Cola] {r.deleted_count} corrida(s) de más de {DIAS_HISTORIAL} días borradas del historial.", flush=True)
    return r.deleted_count


def _bucle() -> None:
    while True:
        try:
            if procesar_pendientes():
                limpiar_viejas()
        except Exception as e:
            print(f"[Cola] Error en el consumidor: {e}", flush=True)
        _despertar.wait(timeout=10)  # el timeout recoge lo que haya quedado sin aviso
        _despertar.clear()


_iniciada = False


def iniciar() -> None:
    global _iniciada
    if _iniciada:
        return
    _iniciada = True
    try:
        recuperar_al_arrancar()
        limpiar_viejas()
    except Exception as e:
        print(f"[Cola] No se pudo revisar la cola al arrancar: {e}", flush=True)
    threading.Thread(target=_bucle, name="cola-corridas", daemon=True).start()
    print("[Cola] consumidor iniciado.", flush=True)
