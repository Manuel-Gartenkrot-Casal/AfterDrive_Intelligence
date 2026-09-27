"""Tests del scheduler: los jobs reflejan exactamente la config guardada."""

import pytest

import config_store
import scheduler


@pytest.fixture
def config(monkeypatch):
    cfg = {
        "scraping": {"enabled": True, "interval_days": 1, "max_articulos": 10},
        "generacion": {"enabled": True, "interval_days": 2},
    }
    monkeypatch.setattr(config_store, "get_scraping_config", lambda: cfg["scraping"])
    monkeypatch.setattr(config_store, "get_generacion_config", lambda: cfg["generacion"])
    yield cfg
    for job in scheduler._scheduler.get_jobs():
        job.remove()


def test_aplicar_agenda_los_habilitados(config):
    scheduler.aplicar()
    ids = {j.id for j in scheduler._scheduler.get_jobs()}
    assert ids == {"scraping", "generacion"}
    trigger = str(scheduler._scheduler.get_job("generacion").trigger)
    assert "day='*/2'" in trigger and "hour='14'" in trigger


def test_deshabilitar_saca_el_job(config):
    scheduler.aplicar()
    config["scraping"]["enabled"] = False
    scheduler.aplicar()
    assert {j.id for j in scheduler._scheduler.get_jobs()} == {"generacion"}


def test_cambio_de_intervalo_reagenda(config):
    scheduler.aplicar()
    config["scraping"]["interval_days"] = 3
    scheduler.aplicar()
    assert "day='*/3'" in str(scheduler._scheduler.get_job("scraping").trigger)


def test_proximas_sin_arrancar_no_explota(config):
    scheduler.aplicar()
    assert scheduler.proximas() == {"scraping": None, "generacion": None}
