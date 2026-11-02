"""Tests de los system prompts de redacción."""

import re

import pytest

from afterdrive.ia import redaccion


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


# ── Piezas editables desde el dashboard ──────────────────────────────────────

from afterdrive import prompts_editables  # noqa: E402


def _activar(col, clave, contenido, version=1):
    col.insert_one({"clave": clave, "contenido": contenido, "estado": "activo", "version": version})
    prompts_editables.invalidar_cache()


@pytest.mark.parametrize("persona", list(redaccion.PERSONAS))
def test_cada_persona_ida_y_vuelta_por_markdown(persona):
    md = redaccion.PIEZAS[f"persona_{persona}"]
    assert md.startswith(redaccion.PERSONAS[persona]["rol"]) and "## Estructura\n1. " in md
    assert redaccion.parsear_persona(md) == redaccion.PERSONAS[persona]


def test_parsear_persona_tolera_titulos_y_lineas_de_continuacion():
    p = redaccion.parsear_persona(
        "# Comercial\nSos redactor.\n\n## Tu tarea:\nVender\nbien.\n\n## Estructura (en orden)\n"
        "1) Gancho\n   con un dato.\n2. Solución\n\n## Otra cosa\nse ignora\n\n## Estilo\nSobrio."
    )
    assert p == {"rol": "Sos redactor.", "tarea": "Vender bien.", "estructura": ["Gancho con un dato.", "Solución"],
                 "estilo": "Sobrio."}


def test_sin_ediciones_el_prompt_suma_el_enfoque_alephee():
    p = redaccion.system_prompt("comercial")
    assert "## Enfoque Alephee" in p and p.index("## Oficio del sector") < p.index("## Enfoque Alephee") < p.index("## Formato")
    assert "## Enfoque Alephee" not in redaccion.system_prompt("comercial", compacto=True)


def test_la_version_activa_reemplaza_al_texto_original(prompts_en_memoria):
    _activar(prompts_en_memoria, "seo", "## SEO\n- REGLA-SEO-NUEVA")
    _activar(prompts_en_memoria, "formato", "## Formato\n- Largo: {extension}. {otra} llave")
    _activar(prompts_en_memoria, "persona_comercial",
             "Sos ROL-NUEVO.\n\n## Tu tarea\nTAREA\n\n## Estructura\n1. Uno\n2. Dos\n\n## Estilo\nESTILO")
    p = redaccion.system_prompt("comercial", extension="entre 1 y 2 palabras")
    assert "REGLA-SEO-NUEVA" in p and "Mostrá cómo una solución" not in p
    assert "- Largo: entre 1 y 2 palabras. {otra} llave" in p
    assert p.startswith("Sos ROL-NUEVO. Escribís notas") and "1. Uno\n2. Dos" in p
    assert redaccion.persona("comercial")["estructura"] == ["Uno", "Dos"]
    assert redaccion.persona("analitico") == redaccion.PERSONAS["analitico"]


def test_una_persona_activa_ilegible_usa_la_original(prompts_en_memoria):
    _activar(prompts_en_memoria, "persona_ejecutivo", "Sos alguien.\n\n## Tu tarea\nAlgo")
    assert redaccion.persona("ejecutivo") == redaccion.PERSONAS["ejecutivo"]


def test_las_piezas_de_la_vista_previa_pisan_lo_activo(prompts_en_memoria):
    _activar(prompts_en_memoria, "salida", "## Respuesta\nACTIVA")
    p = redaccion.system_prompt("comercial", piezas={"salida": "## Respuesta\nBORRADOR"})
    assert "BORRADOR" in p and "ACTIVA" not in p
    assert "ACTIVA" in redaccion.system_prompt("comercial")


def test_lo_activo_se_lee_de_mongo_una_vez_por_minuto(prompts_en_memoria, monkeypatch):
    _activar(prompts_en_memoria, "seo", "## SEO\nPRIMERA")
    assert "PRIMERA" in redaccion.system_prompt("comercial")
    prompts_en_memoria.update_one({"clave": "seo"}, {"$set": {"contenido": "## SEO\nSEGUNDA"}})
    assert "PRIMERA" in redaccion.system_prompt("comercial")      # sigue la caché
    t = prompts_editables.time.monotonic() + prompts_editables.CACHE_S + 1
    monkeypatch.setattr(prompts_editables.time, "monotonic", lambda: t)
    assert "SEGUNDA" in redaccion.system_prompt("comercial")


def test_si_mongo_falla_se_usan_los_textos_originales(monkeypatch):
    def roto(base=None):
        raise RuntimeError("Mongo caído")
    monkeypatch.setattr(prompts_editables, "_col", roto)
    prompts_editables.invalidar_cache()
    assert redaccion.system_prompt("analitico") == "\n\n".join(
        redaccion.system_prompt("analitico", piezas=dict(redaccion.PIEZAS)).split("\n\n"))
    assert "## Oficio del sector" in redaccion.system_prompt("analitico")
