"""Tests del perfil de recursos: cuánta RAM ve el container y qué perfil elige."""

from types import SimpleNamespace

import pytest

from afterdrive.ingesta import resource_detector as rd

MB = 1024 * 1024


@pytest.fixture
def host(monkeypatch, tmp_path):
    """RAM del host simulada y sin archivos de cgroups (como en una PC local)."""
    estado = {"disponible_mb": 8000, "cpus": 8}
    monkeypatch.setattr(
        rd.psutil, "virtual_memory",
        lambda: SimpleNamespace(available=estado["disponible_mb"] * MB),
    )
    monkeypatch.setattr(rd.psutil, "cpu_count", lambda logical=True: estado["cpus"])
    monkeypatch.setattr(rd, "CGROUP_MEMORY_PATHS", (str(tmp_path / "no_existe"),))
    monkeypatch.delenv("DISABLE_BROWSER", raising=False)
    monkeypatch.delenv("FORCE_PROFILE", raising=False)
    return estado


def _cgroup(monkeypatch, tmp_path, contenido, nombre="memory.max"):
    archivo = tmp_path / nombre
    archivo.write_text(contenido)
    monkeypatch.setattr(rd, "CGROUP_MEMORY_PATHS", (str(archivo),))


# --- RAM del container ---

def test_sin_cgroups_usa_la_ram_del_host(host):
    assert rd._leer_ram_container_mb() == pytest.approx(8000)


def test_limite_del_container_manda_sobre_el_host(host, monkeypatch, tmp_path):
    _cgroup(monkeypatch, tmp_path, f"{512 * MB}\n")
    assert rd._leer_ram_container_mb() == pytest.approx(512)


def test_si_el_host_tiene_menos_libre_que_el_limite_gana_el_host(host, monkeypatch, tmp_path):
    host["disponible_mb"] = 300
    _cgroup(monkeypatch, tmp_path, str(2048 * MB))
    assert rd._leer_ram_container_mb() == pytest.approx(300)


@pytest.mark.parametrize("contenido", ["max", "", "basura", str(200 * 1024 * MB)])
def test_limite_ausente_o_absurdo_cae_al_host(host, monkeypatch, tmp_path, contenido):
    _cgroup(monkeypatch, tmp_path, contenido)
    assert rd._leer_ram_container_mb() == pytest.approx(8000)


def test_cgroups_v1_se_lee_si_v2_no_existe(host, monkeypatch, tmp_path):
    v1 = tmp_path / "memory.limit_in_bytes"
    v1.write_text(str(1024 * MB))
    monkeypatch.setattr(rd, "CGROUP_MEMORY_PATHS", (str(tmp_path / "memory.max"), str(v1)))
    assert rd._leer_ram_container_mb() == pytest.approx(1024)


# --- Perfil ---

@pytest.mark.parametrize("ram, perfil", [
    (4000, rd.PERFIL_ALTO),
    (1501, rd.PERFIL_ALTO),
    (1500, rd.PERFIL_MEDIO),
    (601, rd.PERFIL_MEDIO),
    (600, rd.PERFIL_BAJO),
    (200, rd.PERFIL_BAJO),
])
def test_perfil_segun_la_ram(host, ram, perfil):
    host["disponible_mb"] = ram
    assert rd._calcular_perfil() == (perfil, pytest.approx(ram))


@pytest.mark.parametrize("valor", ["true", "TRUE", "True ", " true\n"])
def test_disable_browser_fuerza_bajo_aunque_sobre_ram(host, monkeypatch, valor):
    monkeypatch.setenv("DISABLE_BROWSER", valor)
    assert rd._calcular_perfil()[0] == rd.PERFIL_BAJO


def test_disable_browser_false_no_cambia_nada(host, monkeypatch):
    monkeypatch.setenv("DISABLE_BROWSER", "false")
    assert rd._calcular_perfil()[0] == rd.PERFIL_ALTO


@pytest.mark.parametrize("valor, perfil", [
    ("bajo", rd.PERFIL_BAJO),
    (" Medio ", rd.PERFIL_MEDIO),
    ("ALTO\n", rd.PERFIL_ALTO),
])
def test_force_profile(host, monkeypatch, valor, perfil):
    host["disponible_mb"] = 1000
    monkeypatch.setenv("FORCE_PROFILE", valor)
    assert rd._calcular_perfil()[0] == perfil


def test_force_profile_invalido_se_ignora(host, monkeypatch):
    monkeypatch.setenv("FORCE_PROFILE", "turbo")
    assert rd._calcular_perfil()[0] == rd.PERFIL_ALTO


def test_disable_browser_gana_sobre_force_profile(host, monkeypatch):
    monkeypatch.setenv("DISABLE_BROWSER", "true")
    monkeypatch.setenv("FORCE_PROFILE", "alto")
    assert rd._calcular_perfil()[0] == rd.PERFIL_BAJO


# --- Ajustes derivados del perfil ---

@pytest.mark.parametrize("perfil, browser, workers, sleep, delay", [
    (rd.PERFIL_ALTO, True, 4, 0.3, 1),
    (rd.PERFIL_MEDIO, True, 3, 0.2, 3),
    (rd.PERFIL_BAJO, False, 2, 0.1, 5),
])
def test_ajustes_por_perfil(host, monkeypatch, perfil, browser, workers, sleep, delay):
    monkeypatch.setattr(rd, "_perfil", perfil)
    assert rd.get_perfil() == perfil
    assert rd.usar_browser() is browser
    assert rd.get_max_workers() == workers
    assert rd.get_scrape_sleep() == sleep
    assert rd.get_startup_delay_minutes() == delay


def test_workers_no_superan_los_cpus(host, monkeypatch):
    host["cpus"] = 1
    monkeypatch.setattr(rd, "_perfil", rd.PERFIL_ALTO)
    assert rd.get_max_workers() == 1


def test_cpu_count_desconocido_usa_uno(host, monkeypatch):
    monkeypatch.setattr(rd.psutil, "cpu_count", lambda logical=True: None)
    monkeypatch.setattr(rd, "_perfil", rd.PERFIL_ALTO)
    assert rd.get_max_workers() == 1
