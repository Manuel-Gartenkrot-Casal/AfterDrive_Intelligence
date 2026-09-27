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
    assert "day='*/2'" in trigger and "hour='11'" in trigger


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


def test_la_hora_configurada_define_el_trigger_en_hora_argentina(config):
    config["scraping"]["hora"] = "06:45"
    config["generacion"]["hora"] = "19:05"
    scheduler.aplicar()
    scraping = str(scheduler._scheduler.get_job("scraping").trigger)
    generacion = str(scheduler._scheduler.get_job("generacion").trigger)
    assert "hour='6'" in scraping and "minute='45'" in scraping
    assert "hour='19'" in generacion and "minute='5'" in generacion
    assert scheduler._scheduler.get_job("scraping").trigger.timezone.key == "America/Argentina/Buenos_Aires"


def test_sin_hora_guardada_se_usa_la_de_siempre(config):
    # 05:30 y 11:00 en Argentina = 08:30 y 14:00 UTC, los horarios fijos de antes.
    scheduler.aplicar()
    assert "hour='5'" in str(scheduler._scheduler.get_job("scraping").trigger)
    assert "hour='11'" in str(scheduler._scheduler.get_job("generacion").trigger)
