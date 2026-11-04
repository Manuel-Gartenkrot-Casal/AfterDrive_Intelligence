"""El filtro de artículos scrapeados: respuestas rotas, criterio y reclasificar descartados."""

import datetime

import mongomock
import pytest

from afterdrive.ia import lm_studio
from afterdrive.ingesta import ingesta, reclasificar


@pytest.fixture
def respuestas(monkeypatch):
    """completar() devuelve, en orden, las respuestas de la lista; anota cuántas veces se llamó."""
    pendientes, llamadas = [], []

    def completar(system, mensaje, **k):
        llamadas.append(mensaje)
        return pendientes.pop(0)
    monkeypatch.setattr(lm_studio.llm, "disponible", lambda: True)
    monkeypatch.setattr(lm_studio.llm, "completar", completar)
    return pendientes, llamadas


def test_una_respuesta_rota_se_pregunta_otra_vez(respuestas):
    pendientes, llamadas = respuestas
    pendientes += ["no sé qué decirte", '{"aprobado": true, "razon": "Mercado de repuestos"}']
    assert lm_studio.clasificar_articulo("t", "c") == {"aprobado": True, "razon": "Mercado de repuestos"}
    assert len(llamadas) == 2


@pytest.mark.parametrize("rotas", [["basura", "más basura"], ['{"razon": "sin veredicto"}', "[]"]])
def test_dos_respuestas_rotas_dejan_el_articulo_pendiente_y_no_descartado(respuestas, rotas):
    """Antes una respuesta rota contaba como rechazo y el artículo quedaba descartado para siempre."""
    respuestas[0].extend(rotas)
    r = lm_studio.clasificar_articulo("t", "c")
    assert r["pendiente"] is True and r["aprobado"] is False


def test_el_criterio_acepta_noticias_del_negocio_y_no_solo_repuestos():
    for tema in ("Industria automotriz", "Parque automotor", "Talleres, lubricentros", "Ante la duda"):
        assert tema in lm_studio._SYSTEM_EVALUAR
    assert "APROBAR solo si" not in lm_studio._SYSTEM_EVALUAR


@pytest.fixture
def base(monkeypatch):
    db = mongomock.MongoClient().db
    monkeypatch.setattr(ingesta, "col_articulos", db.articulos)
    monkeypatch.setattr(ingesta, "col_descartados", db.articulos_descartados)
    monkeypatch.setattr(ingesta, "fichas_activas", lambda: False)
    monkeypatch.setattr(ingesta.llm, "embeber", lambda textos, **k: [None] * len(textos))
    monkeypatch.setattr(ingesta.llm, "modelo_embeddings", lambda: "m")
    ahora = datetime.datetime.now(datetime.UTC)
    db.articulos_descartados.insert_many([
        {"url": "https://a.com/1", "titulo": "Crece la producción de autopartes", "cuerpo": "x" * 200,
         "fecha_descarte": ahora.isoformat()},
        {"url": "https://a.com/2", "titulo": "Ganó Boca", "cuerpo": "y" * 200, "fecha_descarte": ahora.isoformat()},
        {"url": "https://a.com/3", "titulo": "Vieja", "cuerpo": "z" * 200,
         "fecha_descarte": (ahora - datetime.timedelta(days=90)).isoformat()},
    ])
    return db


def test_reclasificar_recupera_los_que_ahora_se_aprueban(base, monkeypatch):
    monkeypatch.setattr(ingesta, "clasificar", lambda t, c: {"aprobado": "autopartes" in t, "razon": "r"})
    r = reclasificar.reclasificar(dias=30)
    assert (r["revisados"], r["aprobados"], r["rechazados"]) == (2, 1, 1)   # la de hace 90 días no entra
    assert [d["url"] for d in base.articulos.find()] == ["https://a.com/1"]
    assert sorted(d["url"] for d in base.articulos_descartados.find()) == ["https://a.com/2", "https://a.com/3"]


def test_reclasificar_sin_ia_no_pierde_nada(base, monkeypatch):
    monkeypatch.setattr(ingesta, "clasificar", lambda t, c: {"aprobado": False, "pendiente": True, "razon": "caída"})
    r = reclasificar.reclasificar(dias=30)
    assert r["pendientes"] == 2 and base.articulos.count_documents({}) == 0
    assert base.articulos_descartados.count_documents({}) == 3


def test_reclasificar_respeta_el_limite(base, monkeypatch):
    monkeypatch.setattr(ingesta, "clasificar", lambda t, c: {"aprobado": False, "razon": "r"})
    assert reclasificar.reclasificar(dias=30, limite=1)["revisados"] == 1


@pytest.mark.parametrize("dias, limite", [(30, 0), (30, -5), (0, 500), (-1, 500)])
def test_reclasificar_rechaza_limite_o_dias_menores_a_uno(base, monkeypatch, dias, limite):
    llamadas = []
    monkeypatch.setattr(ingesta, "clasificar", lambda t, c: llamadas.append(t) or {"aprobado": True, "razon": "r"})
    with pytest.raises(ValueError):
        reclasificar.reclasificar(dias=dias, limite=limite)
    assert llamadas == []  # no gastó ni una llamada a la IA
    assert base.articulos_descartados.count_documents({}) == 3


@pytest.mark.parametrize("argv", [["--limite", "0"], ["--dias", "-3"], ["--limite", "muchos"]])
def test_reclasificar_cli_rechaza_valores_invalidos(argv, capsys):
    with pytest.raises(SystemExit) as salida:
        reclasificar.main(argv)
    assert salida.value.code == 2
    assert "--" in capsys.readouterr().err


def test_reclasificar_cli_pasa_dias_y_limite(monkeypatch):
    recibidos = []
    monkeypatch.setattr(reclasificar, "reclasificar", lambda dias, limite: recibidos.append((dias, limite)))
    assert reclasificar.main(["--dias", "90", "--limite", "200"]) == 0
    assert reclasificar.main([]) == 0
    assert recibidos == [(90, 200), (30, 500)]
