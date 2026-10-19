"""Registro de tokens: una llamada de la API paga tiene costo, una gratuita no."""

import json

import pytest

from afterdrive.ia import consumo


@pytest.mark.parametrize("proveedor,costo", [("paga", True), ("local", False)])
def test_registrar_directo(consumo_en_memoria, proveedor, costo):
    usd = consumo.registrar("redaccion", "modelo-x", 1000, 1000, proveedor=proveedor, max_tokens=4000)
    assert (usd > 0) is costo
    assert json.loads(json.dumps(consumo_en_memoria.find_one({}, {"_id": 0})))["max_tokens"] == 4000
