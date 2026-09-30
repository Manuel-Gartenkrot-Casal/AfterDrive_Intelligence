"""
corridas.py — El único camino para ejecutar una Corrida del pipeline.

Una Corrida es una ejecución de scraping, generación o cualquier script del
pipeline. Todas pasan por acá, la dispare el cron, un botón del dashboard o un
endpoint con streaming, así que nunca corren dos a la vez (en el plan free de
Render dos corridas simultáneas se quedan sin RAM).

Interfaz:
    scraping(max_articulos=None) -> dict      in-process (cron y botón)
    generacion(params=None) -> dict           in-process; sin params usa la config guardada
    script(nombre, argv) -> dict              subprocess, salida capturada
    stream(nombre, argv) -> Iterator[str]     subprocess, salida línea por línea (SSE)
    en_curso() -> str | None

Si hay otra Corrida en curso, la nueva no espera: devuelve/emite un aviso de
ocupado. El lock es por proceso; alcanza porque gunicorn corre con --workers 1.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator

TIMEOUT_S = 1800  # 30 min

_lock = threading.Lock()
_actual: str | None = None

# Logs de LM Studio / gRPC que ensucian la salida que ve el usuario.
_LOG_RUIDO = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[(INFO|DEBUG|WARNING|WARN)\]")
_ERR_RUIDO = re.compile(r".*Channel Error.*", re.IGNORECASE)


def en_curso() -> str | None:
    return _actual


@contextlib.contextmanager
def _reservar(nombre: str):
    """Toma el lock sin esperar. Cede None si está ocupado."""
    global _actual
    if not _lock.acquire(blocking=False):
        yield None
        return
    _actual = nombre
    try:
        yield nombre
    finally:
        _actual = None
        _lock.release()


def _ocupado(nombre: str) -> str:
    return f"Otra corrida en curso ({en_curso()}). Se omite '{nombre}'; reintentá cuando termine."


# ── In-process ────────────────────────────────────────────────────────────────


def scraping(max_articulos: int | None = None) -> dict:
    """Scrapea todas las URLs confiables activas e ingiere lo nuevo."""
    with _reservar("scraping") as ok:
        if not ok:
            print(f"[{datetime.datetime.now()}] {_ocupado('scraping')}", flush=True)
            return {"success": False, "error": _ocupado("scraping")}
        return _scrapear_fuentes(max_articulos)


def _scrapear_fuentes(max_articulos: int | None) -> dict:
    from afterdrive import config_store
    from afterdrive.db import col_trusted_urls
    from afterdrive.ingesta.ingesta import ingerir
    from afterdrive.ingesta.scraper import start

    if max_articulos is None:
        max_articulos = config_store.get_scraping_config()["max_articulos"]
    print(f"[{datetime.datetime.now()}] Iniciando scraping de URLs confiables...", flush=True)

    try:
        total_en_db = col_trusted_urls.count_documents({})
        fuentes = list(col_trusted_urls.find({"estado": "activo"}))
        print(f"[DB] Total en trusted_urls: {total_en_db} | Activas: {len(fuentes)}", flush=True)
    except Exception as e:
        print(f"[ERROR] No se pudo consultar la base de datos: {e}", flush=True)
        return {"success": False, "error": str(e)}

    if not fuentes:
        if total_en_db == 0:
            print("No hay URLs confiables en la base de datos. Agregá una desde el panel.", flush=True)
        else:
            print(f"Hay {total_en_db} URL(s) en la DB pero ninguna con estado='activo'.", flush=True)
        return {"success": True, "aprobados": 0}

    print(f"Procesando {len(fuentes)} fuentes (max {max_articulos} artículos/fuente)...", flush=True)
    aprobados = 0
    for doc in fuentes:
        url = doc["url"]
        print(f"Scrapeando: {url}", flush=True)
        try:
            items = start([url], modo="list", max_articulos=max_articulos).items
            if items:
                res = ingerir(items)
                aprobados += res["aprobados"]
                print(f"  [OK] {res['aprobados']} nuevos artículos aprobados.", flush=True)
            else:
                print(f"  [WARN] No se encontraron artículos nuevos en {url}", flush=True)
            col_trusted_urls.update_one(
                {"url": url}, {"$set": {"ultima_ejecucion": datetime.datetime.now(datetime.UTC).isoformat()}}
            )
        except Exception as e:
            print(f"  [ERROR] Fallo al procesar {url}: {e}", flush=True)

    print(f"[{datetime.datetime.now()}] Scraping finalizado.", flush=True)
    return {"success": True, "aprobados": aprobados}


def parametros_guardados() -> dict | None:
    """Parámetros de una Nota Fase 2 según la config del dashboard, o None si no hay categorías."""
    from afterdrive import config_store
    fase2 = config_store.get_fase2_config()
    gen = config_store.get_generacion_config()
    if not fase2.get("categorias"):
        return None
    puntapie_url = None
    if fase2.get("puntapie_activo"):
        puntapie_url = fase2.get("puntapie_url") or gen.get("puntapie_url") or None
    return {
        "categorias": fase2["categorias"],
        "clientes_ids": fase2.get("clientes") or [],
        "puntapie_url": puntapie_url,
        "persona": gen.get("persona") or "comercial",
        "tema": gen.get("tema") or None,
        "regiones": fase2.get("regiones") or [],
    }


def generacion(params: dict | None = None) -> dict:
    """Genera una Nota Fase 2. Sin params usa la config guardada en el dashboard."""
    with _reservar("generacion") as ok:
        if not ok:
            print(f"[{datetime.datetime.now()}] {_ocupado('generacion')}", flush=True)
            return {"success": False, "error": _ocupado("generacion")}
        try:
            from afterdrive.generacion.generar_nota_fase2 import generar_nota

            params = params or parametros_guardados()
            if params is None:
                print("[Generación] Sin categorías activas guardadas. Se omite.", flush=True)
                return {"success": False, "error": "Sin categorías activas guardadas."}
            print(f"[Generación] Categorías: {params['categorias']} | Persona: {params.get('persona')}", flush=True)
            resultado = generar_nota(**params)
        except Exception as e:
            resultado = {"success": False, "error": f"Fallo en generación: {e}"}
        if resultado.get("success"):
            print("[Generación] [OK] Nota generada y guardada en 'notas_fase2'.", flush=True)
        else:
            print(f"[Generación] [ERROR] {resultado.get('error')}", flush=True)
        return resultado


def en_segundo_plano(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


# ── Subprocess ────────────────────────────────────────────────────────────────


def _cmd(nombre: str, argv: list[str] | None) -> list[str]:
    """`nombre` es un módulo (afterdrive.x.y, se corre con -m) o la ruta a un .py."""
    destino = [nombre] if nombre.endswith(".py") else ["-m", nombre]
    return [sys.executable, "-u", *destino, *(argv or [])]


def _env() -> dict:
    return {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}


def script(nombre: str, argv: list[str] | None = None) -> dict:
    """Corre un script del pipeline y devuelve su salida completa."""
    with _reservar(nombre) as ok:
        if not ok:
            return {"success": False, "output": "", "error": _ocupado(nombre)}
        try:
            r = subprocess.run(
                _cmd(nombre, argv), capture_output=True, text=True, timeout=TIMEOUT_S,
                env=_env(), encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": "Timeout: el proceso tardó más de 30 minutos."}
        except Exception as e:
            return {"success": False, "output": "", "error": str(e)}
        out = [ln for ln in r.stdout.splitlines(True) if not _LOG_RUIDO.match(ln)]
        err = [ln for ln in r.stderr.splitlines(True) if not _ERR_RUIDO.match(ln)]
        return {"success": r.returncode == 0, "output": "".join(out), "error": "".join(err) if r.returncode else ""}


def stream(nombre: str, argv: list[str] | None = None) -> Iterator[str]:
    """Corre un script del pipeline y emite su stdout línea por línea.

    Si el cliente corta la conexión (el generador se cierra), el proceso se
    mata: seguir corriendo sin lector termina bloqueado con el pipe lleno.
    """
    with _reservar(nombre) as ok:
        if not ok:
            yield f"[OCUPADO] {_ocupado(nombre)}\n"
            return
        inicio = time.time()
        emitidas = 0
        try:
            proc = subprocess.Popen(
                _cmd(nombre, argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                bufsize=1, env=_env(), encoding="utf-8", errors="replace",
            )
        except Exception as e:
            yield f"[ERROR] {e}\n"
            return

        def _stderr_a_logs():
            for line in proc.stderr:
                if line.strip():
                    print(f"[SUBPROCESS STDERR] {line.rstrip()}", flush=True)

        t = threading.Thread(target=_stderr_a_logs, daemon=True)
        t.start()
        try:
            for line in proc.stdout:
                if time.time() - inicio > TIMEOUT_S:
                    yield "[TIME OUT] El proceso superó el límite de tiempo.\n"
                    return
                if _LOG_RUIDO.match(line):
                    continue
                emitidas += 1
                yield line
            proc.wait(timeout=10)
            t.join(timeout=3)
            if proc.returncode != 0 and not emitidas:
                yield f"[ERROR] El proceso terminó con código {proc.returncode} sin output.\n"
                yield "[ERROR] Revisá los logs del servidor para más detalles.\n"
        except Exception as e:
            yield f"[ERROR] {e}\n"
        finally:
            if proc.poll() is None:
                proc.kill()
