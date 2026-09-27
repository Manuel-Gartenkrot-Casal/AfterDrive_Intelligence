"""Tests de los system prompts de redacción."""

import re

import pytest

import redaccion


@pytest.mark.parametrize("persona", list(redaccion.PERSONAS))
def test_cada_persona_tiene_estructura_reglas_y_cierre(persona):
    p = redaccion.system_prompt(persona)
    assert "## Estructura" in p
    assert "noticias de contexto" in p          # la regla de datos
    assert "meta description" in p
    assert "Respondé solo con la nota" in p


def test_voz_por_region():
    assert "rioplatense" in redaccion.system_prompt("comercial")
    assert "voseo" in redaccion.system_prompt("comercial", region=["argentina"])
    mx = redaccion.system_prompt("comercial", region=["mexico"])
    assert "tuteo" in mx and "Descubre cómo" in mx and "Descubrí" not in mx
    assert "portugués" in redaccion.system_prompt("comercial", region=["brasil"])
    assert "inglés" in redaccion.system_prompt("comercial", region=["asia"])
    # Mezcla de regiones hispanas -> tuteo neutro
    assert "tuteo" in redaccion.system_prompt("comercial", region=["argentina", "mexico"])


def test_compacto_es_mucho_mas_corto_y_conserva_lo_esencial():
    largo = redaccion.system_prompt("divulgativo")
    corto = redaccion.system_prompt("divulgativo", compacto=True)
    assert len(corto) < len(largo) * 0.6
    for esencial in ("## Estructura", "noticias de contexto", "meta description", "Respondé solo con la nota"):
        assert esencial in corto


def test_sin_casos_ni_cifras_de_ejemplo_que_el_modelo_copie():
    for persona in redaccion.PERSONAS:
        p = redaccion.system_prompt(persona)
        for marca in ("Bridgestone", "Volkswagen", "Renault", "Toyota"):
            assert marca not in p
        assert not re.search(r"\d+\s?%", p), "no debe haber porcentajes de ejemplo"


def test_ortografia_del_prompt():
    # El modelo imita lo que lee: el prompt tiene que estar bien escrito.
    texto = " ".join(redaccion.system_prompt(p) for p in redaccion.PERSONAS).lower()
    for mal in (" articulo ", " analisis ", " tecnico ", " catalogo ", " region ", " numero "):
        assert mal not in texto


def test_puntapie_y_directiva_del_proveedor():
    p = redaccion.system_prompt("comercial", puntapie_url="https://alephee.com/x", directiva="DIRECTIVA-MODELO")
    assert "https://alephee.com/x" in p
    assert p.rstrip().endswith("DIRECTIVA-MODELO")


def test_persona_desconocida_usa_analitico():
    assert redaccion.system_prompt("inexistente") == redaccion.system_prompt("analitico")
