"""
resource_detector.py

Detecta los recursos disponibles del sistema al startup y devuelve un perfil
de ejecución que el resto de los módulos usa para ajustar su comportamiento.

Perfiles:
  alto  → RAM > 1500 MB disponibles  → Chromium + 4 threads
  medio → RAM 600-1500 MB            → requests primero, Chromium como fallback, 3 threads
  bajo  → RAM < 600 MB               → requests + Wayback, sin Chromium, 2 threads

Overrides via variables de entorno:
  DISABLE_BROWSER=true  → fuerza perfil bajo
  FORCE_PROFILE=alto|medio|bajo → fuerza el perfil indicado (útil para testing)
"""

import os

import psutil

PERFIL_ALTO = "alto"
PERFIL_MEDIO = "medio"
PERFIL_BAJO = "bajo"

_ram_mb: float = 0.0
_perfil: str = ""


def _leer_ram_container_mb() -> float:
    """
    En Docker/Render, psutil.virtual_memory() reporta la RAM del HOST, no del container.
    Intentamos leer el límite real del container desde cgroups.
    Si no está disponible (entorno local sin Docker), usamos psutil como fallback.
    """
    # cgroups v2 (Linux moderno, Render usa esto)
    for path in [
        "/sys/fs/cgroup/memory.max",         # cgroups v2
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # cgroups v1
    ]:
        try:
            with open(path) as f:
                val = f.read().strip()
            if val and val != "max":
                limit_bytes = int(val)
                # Si el límite es absurdamente alto (> 100 GB), es que no hay límite real
                if limit_bytes < 100 * 1024 ** 3:
                    # Retornamos el mínimo entre el límite del container y la RAM disponible del host
                    available_host = psutil.virtual_memory().available
                    return min(limit_bytes, available_host) / 1024 / 1024
        except Exception:
            continue

    # Fallback: RAM disponible del host (entorno local o sin límite de container)
    return psutil.virtual_memory().available / 1024 / 1024


def _calcular_perfil() -> tuple[str, float]:
    if os.getenv("DISABLE_BROWSER", "").lower() == "true":
        ram = _leer_ram_container_mb()
        return PERFIL_BAJO, ram

    forced = os.getenv("FORCE_PROFILE", "").lower()
    if forced in (PERFIL_ALTO, PERFIL_MEDIO, PERFIL_BAJO):
        ram = _leer_ram_container_mb()
        return forced, ram

    ram = _leer_ram_container_mb()

    if ram > 1500:
        return PERFIL_ALTO, ram
    elif ram > 600:
        return PERFIL_MEDIO, ram
    else:
        return PERFIL_BAJO, ram


_perfil, _ram_mb = _calcular_perfil()

print(f"[PERFIL] RAM container: {_ram_mb:.0f} MB → perfil '{_perfil}'", flush=True)


def get_perfil() -> str:
    return _perfil


def get_ram_mb() -> float:
    return _ram_mb


def usar_browser() -> bool:
    return _perfil in (PERFIL_ALTO, PERFIL_MEDIO)


def get_max_workers() -> int:
    cpus = psutil.cpu_count(logical=True) or 1
    if _perfil == PERFIL_ALTO:
        return min(4, cpus)
    elif _perfil == PERFIL_MEDIO:
        return min(3, cpus)
    else:
        return min(2, cpus)


def get_scrape_sleep() -> float:
    if _perfil == PERFIL_ALTO:
        return 0.3
    elif _perfil == PERFIL_MEDIO:
        return 0.2
    else:
        return 0.1


def get_startup_delay_minutes() -> int:
    if _perfil == PERFIL_ALTO:
        return 1
    elif _perfil == PERFIL_MEDIO:
        return 3
    else:
        return 5
