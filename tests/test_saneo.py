"""Tests del saneo de la Nota: salidas reales (y malas) del modelo como fixtures."""

import json

from afterdrive.ia.saneo import sanear

CUERPO = (
    "El parque automotor argentino supera los **15 millones** de vehículos y la demanda de "
    "repuestos crece un **8%** interanual. Los distribuidores que digitalizaron su catálogo "
    "venden más y con menos devoluciones por errores de fitment."
)

NOTA = f"""# La digitalización del catálogo ya no es opcional

## El dato que cambia el juego
{CUERPO}

## Qué hacen los que crecen
Integran su ERP con marketplaces y publican fichas con compatibilidad por año y motor.

Descubrí cómo Alephee conecta tu catálogo con los principales marketplaces.

*Catálogo digital y fitment: la ventaja del distribuidor de autopartes en 2026.*"""


def test_nota_limpia_pasa_intacta():
    r = sanear(NOTA)
    assert r.ok
    assert r.texto == NOTA


def test_quita_fences_y_etiquetas():
    r = sanear(f"```markdown\n<ARTICULO>\n{NOTA}\n</ARTICULO>\n```")
    assert r.ok
    assert r.texto.startswith("# La digitalización")
    assert "```" not in r.texto and "ARTICULO" not in r.texto


def test_descarta_preambulo_antes_del_titulo():
    r = sanear(f"Claro, acá tenés la nota pedida:\n\n{NOTA}")
    assert r.ok
    assert r.texto.startswith("# La digitalización")


def test_rechaza_razonamiento_del_modelo():
    # Salida real de nemotron-3.5-lightning (commit b9ead70): el plan en vez de la nota.
    plan = """I need to write an article about the aftermarket. Let me structure it.
## 1. Gancho con dato real - 1 paragraph
I'll aim for 900 words. Let me check the examples and the instructions.
## 2. La solucion concreta - 2 paragraphs
Now let me draft the title. The reader is a B2B distributor, and the article should use the context.
Let me re-read the user says part. Word count should be fine with the examples."""
    r = sanear(plan)
    assert not r.ok
    assert "razonamiento" in r.motivo


def test_desenvuelve_json_con_articulo():
    r = sanear(json.dumps({"accion": "redaccion", "articulo": NOTA}, ensure_ascii=False))
    assert r.ok
    assert r.texto.startswith("# La digitalización")


def test_nota_como_json_de_secciones():
    data = {
        "titulo": "Fitment digital",
        "estructura": [
            {"titulo": "El problema", "texto": CUERPO},
            {"titulo": "La solución", "texto": CUERPO.replace("argentino", "mexicano")},
        ],
        "meta_description": "Fitment digital para distribuidores.",
    }
    r = sanear("Metadata:\n" + json.dumps(data, ensure_ascii=False))
    assert r.ok
    assert r.texto.startswith("# Fitment digital")
    assert "## El problema" in r.texto


def test_cierre_repetido_queda_una_vez():
    cierre = "El aftermarket que se digitaliza hoy lidera el mercado de mañana."
    r = sanear(f"{NOTA}\n\n{cierre}\n\n{cierre}")
    assert r.ok
    assert r.texto.count(cierre) == 1


def test_seccion_duplicada_se_elimina():
    seccion = f"## El dato que cambia el juego\n{CUERPO}\n"
    r = sanear(NOTA.replace("## Qué hacen", seccion + "\n## Qué hacen"))
    assert r.ok
    assert r.texto.count("15 millones") == 1


def test_varios_cta_queda_el_ultimo():
    nota = NOTA.replace(
        "## Qué hacen los que crecen",
        "Conocé más sobre el catálogo en nuestro blog.\n\n## Qué hacen los que crecen",
    )
    r = sanear(nota)
    assert r.ok
    assert "Conocé más sobre el catálogo" not in r.texto
    assert "Descubrí cómo Alephee" in r.texto


def test_oracion_del_cuerpo_con_verbo_cta_no_se_borra():
    nota = NOTA.replace(
        "Integran su ERP",
        "Quien conoce su fitment vende más. Integran su ERP",
    )
    r = sanear(nota + "\n\nConocé los casos de éxito en alephee.com.")
    assert "Quien conoce su fitment vende más" in r.texto


def test_link_markdown_al_inicio_de_linea_se_conserva():
    nota = NOTA + "\n\n[Conocé Alephee](https://alephee.com/landing)"
    r = sanear(nota)
    assert "(https://alephee.com/landing)" in r.texto
    assert "[Conocé Alephee]" in r.texto


def test_corchete_suelto_de_borrador_se_quita():
    r = sanear(NOTA.replace("## Qué hacen", "[insertar dato de mercado]\n## Qué hacen"))
    assert "[insertar dato de mercado]" not in r.texto


def test_rechaza_vacio_y_corto():
    assert not sanear("").ok
    assert not sanear("   ").ok
    corto = sanear("# Título\nMuy poco.")
    assert not corto.ok
    assert "largo" in corto.motivo


def test_rechaza_texto_degenerado():
    # Salida real de nemotron-3.5-lightning:free en OpenRouter (27/9): bucle de tokens.
    basura = ("Here andellsellsellsellsellsells andellsellsells where fromellsellsellsellsells weellsellsellsells "
              "deepellsellsellsellsellsells fromellsellsellsells rigor rigorellsellsellsellsells ") * 12
    r = sanear(basura)
    assert not r.ok
    assert "degenerad" in r.motivo


# ── Formato para HubSpot (Python-Markdown no perdona lo que marked sí) ────────

from afterdrive.ia.saneo import _sin_oraciones_repetidas, normalizar_formato  # noqa: E402


def test_titulo_y_meta_sin_negritas_ni_etiqueta():
    out = normalizar_formato("# Frasle invierte **US$ 20 millones**\n\nTexto.\n\n*Meta description: Sube **15%** la venta.*")
    assert out.splitlines()[0] == "# Frasle invierte US$ 20 millones"
    assert out.splitlines()[-1] == "*Sube 15% la venta.*"


def test_listas_y_titulos_pegados_al_parrafo_se_separan():
    out = normalizar_formato("# T\nPárrafo:\n- a\n  - sub\n- b\n1. uno\n## Sección\nTexto.")
    assert out == "# T\nPárrafo:\n\n- a\n    - sub\n- b\n\n1. uno\n\n## Sección\nTexto."


def test_normalizar_no_toca_lo_que_ya_esta_bien_ni_el_codigo():
    bien = "# T\n\nPárrafo.\n\n- a\n- b\n\n## S\n\nTexto **con negrita**.\n\n*Meta.*"
    assert normalizar_formato(bien) == bien
    codigo = "```\nlinea\n- no es lista\n```"
    assert normalizar_formato(codigo) == codigo


def test_quitar_oraciones_repetidas_no_rompe_cifras_ni_links():
    # Caso real (nota Chery Himla): "50.000" salía "50. 000" y los links "https://www. ambito. com".
    linea = ("El cupo de 50.000 unidades se mantuvo y el tope subió de u$s16.000 a u$s35.000. "
             "Zuppi proyecta 515.000 unidades, según [declaraciones](https://www.ambito.com/autos/a-n1). "
             "Geely evalúa una planta, [según confirmó](https://www.ambito.com/autos/b-n2). "
             "Zuppi proyecta 515.000 unidades, según [declaraciones](https://www.ambito.com/autos/a-n1).")
    out = _sin_oraciones_repetidas(linea)
    assert "50.000" in out and "u$s35.000" in out and "https://www.ambito.com/autos/b-n2" in out
    assert out.count("Zuppi proyecta") == 1
    sin_repetir = linea.rsplit(" Zuppi", 1)[0]
    assert _sin_oraciones_repetidas(sin_repetir) == sin_repetir
