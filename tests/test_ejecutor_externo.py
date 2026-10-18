"""Tests de las Corridas en GitHub Actions: qué toca correr y cómo se ve desde el dashboard."""

import datetime
import zoneinfo

import mongomock
import pytest

from afterdrive import cola, config_store, corridas, ejecutor_externo, scheduler

TZ = zoneinfo.ZoneInfo(scheduler.ZONA)


@pytest.fixture
def config(monkeypatch):
    store = {"scraping": {"enabled": True, "hora": "05:30", "interval_days": 1},
             "generacion": {"enabled": True, "hora": "11:00", "interval_days": 1}}
    revisado = {}
    monkeypatch.setattr(config_store, "get_scraping_config", lambda: store["scraping"])
    monkeypatch.setattr(config_store, "get_generacion_config", lambda: store["generacion"])
    monkeypatch.setattr(config_store, "get_ejecutor_externo", lambda: dict(revisado))
    monkeypatch.setattr(config_store, "set_ejecutor_externo", lambda r: revisado.update(r))
    return store, revisado


def _a(hh, mm, dia=20):
    return datetime.datetime(2026, 10, dia, hh, mm, tzinfo=TZ)


def test_toca_lo_que_paso_desde_la_ultima_revision(config):
    _, revisado = config
    revisado.update(scraping=_a(5, 7).isoformat(), generacion=_a(5, 7).isoformat())
    assert ejecutor_externo.pendientes(_a(6, 7)) == ["scraping"]      # 05:30 cayó en la ventana
    assert ejecutor_externo.pendientes(_a(7, 7)) == []                # ya se revisó: no se repite
    assert ejecutor_externo.pendientes(_a(11, 7)) == ["generacion"]


def test_una_hora_salteada_no_pierde_la_corrida(config):
    _, revisado = config
    revisado.update(scraping=_a(4, 7).isoformat(), generacion=_a(4, 7).isoformat())
    # GitHub demoró el cron y la siguiente revisión fue tres horas después.
    assert ejecutor_externo.pendientes(_a(7, 40)) == ["scraping"]


def test_deshabilitado_no_corre(config):
    store, revisado = config
    store["scraping"]["enabled"] = False
    revisado.update(scraping=_a(5, 7).isoformat(), generacion=_a(5, 7).isoformat())
    assert ejecutor_externo.pendientes(_a(6, 7)) == []


def test_primera_vez_mira_solo_las_ultimas_dos_horas(config):
    assert ejecutor_externo.pendientes(_a(6, 7)) == ["scraping"]
    assert ejecutor_externo.pendientes(_a(23, 0, dia=21)) == ["scraping", "generacion"]


def test_en_modo_externo_el_servidor_no_programa_pero_informa_la_proxima(config, monkeypatch):
    monkeypatch.setenv("CORRIDAS_EXTERNAS", "github")
    scheduler.aplicar()
    try:
        assert scheduler._scheduler.get_jobs() == []
        proximas = scheduler.proximas()
        assert proximas["scraping"] and proximas["generacion"]
        assert datetime.datetime.fromisoformat(proximas["scraping"]).astimezone(TZ).strftime("%H:%M") == "05:30"
    finally:
        for job in scheduler._scheduler.get_jobs():
            job.remove()


# ── Registro en la cola ───────────────────────────────────────────────────────


@pytest.fixture
def col(monkeypatch):
    c = mongomock.MongoClient().db.corridas
    monkeypatch.setattr(cola, "_col", lambda: c)
    return c


def test_ejecutar_aca_queda_registrada_como_de_github(col, monkeypatch):
    monkeypatch.setattr(corridas, "_scrapear_fuentes", lambda m: print("leyendo fuentes") or {"success": True})
    assert cola.ejecutar_aca("scraping") == "ok"
    doc = col.find_one()
    assert doc["ejecutor"] == "github" and doc["origen"] == "cron" and "leyendo fuentes" in doc["log"]


def test_el_log_se_vuelca_a_mongo_mientras_corre(col, monkeypatch):
    vistos = []

    def scrapear(m):
        print("fuente 1")
        cola._volcado = 0        # forzar el volcado sin esperar 5 s
        print("fuente 2")
        vistos.extend(col.find_one()["log"])
        return {"success": True}

    monkeypatch.setattr(corridas, "_scrapear_fuentes", scrapear)
    cola.ejecutar_aca("scraping")
    assert "fuente 1" in vistos   # otro proceso ya lo podía leer antes de terminar


def test_cancelar_desde_el_dashboard_llega_al_runner(col, monkeypatch):
    """Dashboard y runner son procesos distintos: el pedido viaja por Mongo."""
    id_ = str(col.insert_one({"estado": "en_curso", "ejecutor": "github", "tipo": "scraping"}).inserted_id)

    # 1) El dashboard (no tiene esta Corrida en memoria) pide cancelar.
    monkeypatch.setattr(cola, "_actual", None)
    assert cola.cancelar(id_) == {"estado": "cancelando"}
    assert col.find_one()["cancelar_pedido"] is True

    # 2) El runner, al volcar su log, ve el pedido y levanta la bandera de corte.
    corridas._cancelar.clear()
    monkeypatch.setattr(cola, "_actual", id_)
    monkeypatch.setattr(cola, "_volcado", 0)
    cola._agregar(["Scrapeando: fuente 2"])
    try:
        assert corridas._cancelar.is_set()
        assert col.find_one()["log"][-1] == "Scrapeando: fuente 2"
    finally:
        corridas._cancelar.clear()
        cola._lineas.clear()


def test_reiniciar_el_servidor_no_interrumpe_la_de_github(col):
    ahora = datetime.datetime.now(datetime.UTC)
    col.insert_many([
        {"estado": "en_curso", "ejecutor": "servidor", "inicio": ahora.isoformat()},
        {"estado": "en_curso", "ejecutor": "github", "inicio": ahora.isoformat()},
        {"estado": "en_curso", "ejecutor": "github", "inicio": (ahora - datetime.timedelta(hours=5)).isoformat()},
    ])
    cola.recuperar_al_arrancar()
    estados = sorted((d["ejecutor"], d["estado"]) for d in col.find())
    assert estados == [("github", "en_curso"), ("github", "interrumpida"), ("servidor", "interrumpida")]
