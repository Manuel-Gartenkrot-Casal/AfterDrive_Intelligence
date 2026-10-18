"""Tests del scheduler: los jobs reflejan exactamente la config guardada."""

import datetime
import zoneinfo

import pytest

from afterdrive import config_store
from afterdrive import scheduler
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
    trigger = scheduler._scheduler.get_job("generacion").trigger
    assert trigger.interval.days == 2 and trigger.start_date.hour == 11


def test_deshabilitar_saca_el_job(config):
    scheduler.aplicar()
    config["scraping"]["enabled"] = False
    scheduler.aplicar()
    assert {j.id for j in scheduler._scheduler.get_jobs()} == {"generacion"}


def test_cambio_de_intervalo_reagenda(config):
    scheduler.aplicar()
    config["scraping"]["interval_days"] = 3
    scheduler.aplicar()
    assert scheduler._scheduler.get_job("scraping").trigger.interval.days == 3


def test_proximas_sin_arrancar_no_explota(config):
    scheduler.aplicar()
    assert scheduler.proximas() == {"scraping": None, "generacion": None}


def test_la_hora_configurada_define_el_trigger_en_hora_argentina(config):
    config["scraping"]["hora"] = "06:45"
    config["generacion"]["hora"] = "19:05"
    scheduler.aplicar()
    assert _hora("scraping") == (6, 45)
    assert _hora("generacion") == (19, 5)
    assert scheduler._scheduler.get_job("scraping").trigger.timezone.key == "America/Argentina/Buenos_Aires"


def test_sin_hora_guardada_se_usa_la_de_siempre(config):
    # 05:30 y 11:00 en Argentina = 08:30 y 14:00 UTC, los horarios fijos de antes.
    scheduler.aplicar()
    assert _hora("scraping") == (5, 30)
    assert _hora("generacion") == (11, 0)


def _hora(job_id):
    """(hora, minuto) de la próxima ejecución, en hora argentina."""
    t = scheduler._scheduler.get_job(job_id).trigger
    proxima = t.get_next_fire_time(None, datetime.datetime.now(t.timezone))
    return proxima.hour, proxima.minute


@pytest.mark.parametrize("desde", ["2026-10-28", "2026-12-30", "2027-02-27"])
def test_cada_dos_dias_no_se_saltea_ni_repite_a_fin_de_mes(desde):
    tz = zoneinfo.ZoneInfo(scheduler.ZONA)
    t = scheduler.trigger(5, 30, 2)
    f = datetime.datetime.fromisoformat(desde).replace(tzinfo=tz)
    fechas = []
    for _ in range(4):
        f = t.get_next_fire_time(None, f)
        fechas.append(f)
        f += datetime.timedelta(minutes=1)
    assert all((b - a).days == 2 for a, b in zip(fechas, fechas[1:], strict=False))
    assert all((x.hour, x.minute) == (5, 30) for x in fechas)


def test_el_ritmo_no_depende_de_cuando_se_reinicio():
    tz = zoneinfo.ZoneInfo(scheduler.ZONA)
    ahora = datetime.datetime(2026, 11, 10, 12, tzinfo=tz)
    a = scheduler.trigger(5, 30, 3).get_next_fire_time(None, ahora)
    b = scheduler.trigger(5, 30, 3).get_next_fire_time(None, ahora)
    assert a == b


def test_crear_indices_no_frena_si_mongo_falla(monkeypatch):
    from afterdrive import db

    class Rota:
        def __getitem__(self, nombre):
            raise RuntimeError("sin Mongo")

    monkeypatch.setattr(db, "db", Rota())
    monkeypatch.setattr(db, "crear_indices_texto", lambda: None)
    db.crear_indices()  # no lanza


def test_crear_indices_crea_los_de_la_cola(monkeypatch):
    import mongomock

    from afterdrive import db
    base = mongomock.MongoClient().db
    monkeypatch.setattr(db, "db", base)
    monkeypatch.setattr(db, "crear_indices_texto", lambda: None)
    db.crear_indices()
    assert "estado_1_creada_1" in base.corridas.index_information()
    assert "url_1" in base.articulos.index_information()
