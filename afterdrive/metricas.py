"""metricas.py — Números del pipeline para el tablero de la vista Desarrollador.

Interfaz:
    resumen(dias=14, base=None) -> dict

Todo sale de colecciones que ya existen, sin guardar nada nuevo:
    articulos / articulos_descartados   lo que trajo el scraping, por día y por sitio
    notas_fase2 / notas_descartadas     notas escritas y versiones descartadas
    corridas                            resultado y duración de cada corrida
    consumo_ia                          gasto de la API paga del mes

Los días se cuentan en hora de Argentina, como la programación. Las fechas
salen del _id (ObjectId) o del campo de fecha de cada documento, y cada
consulta se limita al período pedido para no recorrer la base entera.
"""

from __future__ import annotations

import datetime
from collections import Counter, defaultdict
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bson import ObjectId

from afterdrive import db as _db

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
DIAS_MAX = 60
VENTANA_LARGA = 30   # fuentes, corridas y calidad miran un mes
TOP_FUENTES = 6
TIPOS_CORRIDA = {"scraping": "Buscar noticias", "generacion": "Generar nota"}
ESTADOS_CORRIDA = ("ok", "error", "cancelada", "interrumpida")


def _base(base):
    return base if base is not None else _db.db


def _fecha(valor) -> datetime.datetime | None:
    """datetime con zona a partir de un ISO, un datetime o un ObjectId."""
    if isinstance(valor, ObjectId):
        return valor.generation_time
    if isinstance(valor, datetime.datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=datetime.UTC)
    if isinstance(valor, str) and valor:
        try:
            d = datetime.datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=datetime.UTC)
    return None


def _dia(valor) -> str | None:
    d = _fecha(valor)
    return d.astimezone(ZONA).date().isoformat() if d else None


def _dominio(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host.removeprefix("www.") or "sin sitio"


def _desde_oid(desde: datetime.datetime) -> dict:
    return {"_id": {"$gte": ObjectId.from_datetime(desde)}}


def _por_dia(fechas, dias: list[str]) -> list[int]:
    cuenta = Counter(d for d in fechas if d)
    return [cuenta.get(d, 0) for d in dias]


def _articulos(b, desde_corto, desde_largo, dias):
    guardados_dia, descartados_dia = [], []
    por_sitio: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for doc in b["articulos"].find(_desde_oid(desde_largo), {"url": 1}):
        if doc["_id"].generation_time >= desde_corto:
            guardados_dia.append(_dia(doc["_id"]))
        por_sitio[_dominio(doc.get("url"))][0] += 1
    # Los descartados se reescriben con upsert: la fecha real es fecha_descarte.
    filtro = {"$or": [{"fecha_descarte": {"$gte": desde_largo.isoformat()}}, _desde_oid(desde_largo)]}
    for doc in b["articulos_descartados"].find(filtro, {"url": 1, "fecha_descarte": 1}):
        cuando = _fecha(doc.get("fecha_descarte")) or doc["_id"].generation_time
        if cuando < desde_largo:
            continue
        if cuando >= desde_corto:
            descartados_dia.append(_dia(cuando))
        por_sitio[_dominio(doc.get("url"))][1] += 1
    top = sorted(por_sitio.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:TOP_FUENTES]
    return {
        "guardados": _por_dia(guardados_dia, dias),
        "descartados": _por_dia(descartados_dia, dias),
        "fuentes": [{"sitio": s, "guardados": g, "descartados": d} for s, (g, d) in top],
    }


def _promedio(xs: list) -> float | None:
    return round(sum(xs) / len(xs), 1) if xs else None


def _inicio_del_dia(dia: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(dia, datetime.time(), ZONA).astimezone(datetime.UTC)


def _notas(b, desde_corto, desde_largo, dias):
    escritas_dia, puntajes, intentos, estrellas = [], [], [], []
    estados = Counter()
    campos = {"generado_en": 1, "estado": 1, "calidad": 1, "calificacion": 1}
    for doc in b["notas_fase2"].find({"generado_en": {"$gte": desde_largo.isoformat()}}, campos):
        cuando = _fecha(doc.get("generado_en"))
        if not cuando:
            continue
        if cuando >= desde_corto:
            escritas_dia.append(_dia(cuando))
        estados[doc.get("estado") or _db.ESTADO_BORRADOR] += 1
        calidad = doc.get("calidad") or {}
        if isinstance(calidad.get("puntaje"), (int, float)):
            puntajes.append(calidad["puntaje"])
        if isinstance(calidad.get("intentos"), int):
            intentos.append(calidad["intentos"])
        cal = doc.get("calificacion") or {}
        if isinstance(cal.get("puntaje"), (int, float)):
            estrellas.append(cal["puntaje"])
    descartadas = [_dia(d["_id"]) for d in b["notas_descartadas"].find(_desde_oid(desde_corto), {"_id": 1})]
    return {
        "escritas": _por_dia(escritas_dia, dias),
        "descartadas": _por_dia(descartadas, dias),
        "estados": {e: estados.get(e, 0) for e in _db.ESTADOS_NOTA},
        "puntaje_promedio": _promedio(puntajes),          # lineamientos cumplidos, 0 a 9
        "intentos_promedio": _promedio(intentos),
        "calificacion_promedio": _promedio(estrellas),    # estrellas del equipo, 1 a 5
        "calificadas": len(estrellas),
    }


def _corridas(b, desde_largo):
    por_tipo = {t: {"etiqueta": e, **{s: 0 for s in ESTADOS_CORRIDA}, "duraciones": []}
                for t, e in TIPOS_CORRIDA.items()}
    filtro = {"tipo": {"$in": list(TIPOS_CORRIDA)}, "creada": {"$gte": desde_largo.isoformat()}}
    for doc in b["corridas"].find(filtro, {"tipo": 1, "estado": 1, "inicio": 1, "fin": 1}):
        t = por_tipo[doc["tipo"]]
        if doc.get("estado") in ESTADOS_CORRIDA:
            t[doc["estado"]] += 1
        ini, fin = _fecha(doc.get("inicio")), _fecha(doc.get("fin"))
        if doc.get("estado") == "ok" and ini and fin and fin >= ini:
            t["duraciones"].append((fin - ini).total_seconds())
    salida = []
    for tipo, t in por_tipo.items():
        dur = sorted(t.pop("duraciones"))
        total = sum(t[s] for s in ESTADOS_CORRIDA)
        salida.append({
            "tipo": tipo, **t, "total": total,
            "exito": round(t["ok"] / total, 3) if total else None,
            "duracion_mediana_s": round(dur[len(dur) // 2]) if dur else None,
        })
    return salida


def _gasto(b, dias):
    from afterdrive.ia import consumo

    hoy = datetime.datetime.now(datetime.UTC)
    por_dia: dict[str, float] = defaultdict(float)
    por_tarea: dict[str, float] = defaultdict(float)
    total = 0.0
    desde = _inicio_del_dia(datetime.date.fromisoformat(dias[0])).isoformat()
    filtro = {"$or": [{"mes": hoy.strftime("%Y-%m")}, {"fecha": {"$gte": desde}}]}
    for doc in b["consumo_ia"].find(filtro, {"fecha": 1, "mes": 1, "tarea": 1, "costo_usd": 1}):
        costo = float(doc.get("costo_usd") or 0)
        if doc.get("mes") == hoy.strftime("%Y-%m"):
            total += costo
            por_tarea[doc.get("tarea") or "general"] += costo
        dia = _dia(doc.get("fecha"))
        if dia:
            por_dia[dia] += costo
    return {
        "mes_usd": round(total, 4),
        "tope_usd": consumo.tope(),
        "por_tarea": {k: round(v, 4) for k, v in sorted(por_tarea.items(), key=lambda kv: -kv[1])},
        "por_dia": [round(por_dia.get(d, 0.0), 4) for d in dias],
    }


def resumen(dias: int = 14, base=None) -> dict:
    dias = max(1, min(int(dias), DIAS_MAX))
    b = _base(base)
    hoy = datetime.datetime.now(ZONA).date()
    serie = [(hoy - datetime.timedelta(days=i)).isoformat() for i in range(dias - 1, -1, -1)]
    desde_corto = _inicio_del_dia(hoy - datetime.timedelta(days=dias - 1))
    desde_largo = min(desde_corto, _inicio_del_dia(hoy - datetime.timedelta(days=VENTANA_LARGA - 1)))
    return {
        "dias": serie,
        "ventana_larga": max(dias, VENTANA_LARGA),
        "articulos": _articulos(b, desde_corto, desde_largo, serie),
        "notas": _notas(b, desde_corto, desde_largo, serie),
        "corridas": _corridas(b, desde_largo),
        "gasto": _gasto(b, serie),
    }
