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


def _calcular_perfil() -> tuple[str, float]:
    if os.getenv("DISABLE_BROWSER", "").lower() == "true":
        ram = psutil.virtual_memory().available / 1024 / 1024
        return PERFIL_BAJO, ram

    forced = os.getenv("FORCE_PROFILE", "").lower()
    if forced in (PERFIL_ALTO, PERFIL_MEDIO, PERFIL_BAJO):
        ram = psutil.virtual_memory().available / 1024 / 1024
        return forced, ram

    ram = psutil.virtual_memory().available / 1024 / 1024

    if ram > 1500:
        return PERFIL_ALTO, ram
    elif ram > 600:
        return PERFIL_MEDIO, ram
    else:
        return PERFIL_BAJO, ram


_perfil, _ram_mb = _calcular_perfil()

print(f"[PERFIL] RAM disponible: {_ram_mb:.0f} MB → perfil '{_perfil}'", flush=True)


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
