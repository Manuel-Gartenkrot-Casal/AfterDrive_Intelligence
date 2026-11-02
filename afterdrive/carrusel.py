"""
carrusel.py — Carruseles de 3 imágenes para redes a partir de una Nota, uno por idioma.

Interfaz:
    textos_con_ia(nota_md, idioma) -> dict | None      {"titulo", "subtitulo", "puntos", "cta"}
    textos_sin_ia(nota_md, idioma) -> dict             mismo formato, sacado del texto de la nota
    validar(textos) -> dict                            recorta y completa; ErrorCarrusel si falta lo esencial
    html_diapositivas(textos, fondo=None, url="") -> [str]   una página HTML por diapositiva
    renderizar(htmls) -> ([png], pdf)                  con Chromium (Playwright)
    carruseles(nota) -> {idioma: carrusel}             los guardados (entiende el formato viejo)
    generar(nota_id, idiomas=None, solo_imagenes=False, base=None) -> {idioma: carrusel}
    guardar_textos(nota_id, idioma, textos) / en_post(nota_id, activo)

De dónde sale cada cosa:
- Las diapositivas son plantillas HTML con los colores y el logo de AfterDrive que Chromium
  pasa a PNG (1080x1350, el formato vertical de Instagram). No son fotos de un banco ni
  imágenes hechas por IA.
- La única foto es el fondo de la portada: la imagen destacada de la nota (la misma que va a
  HubSpot). Sin ella, la portada va con el color oscuro de la marca.
- Los textos los escribe el modelo barato (tarea "carrusel" → el de evaluación) solo con lo
  que dice la nota, directo en cada idioma: parte de la traducción de la nota si ya existe, y
  si no, del original. Si la IA falla, salen del texto en ese idioma (título, meta description
  y viñetas de implicancias). Se pueden editar en el dashboard: al guardarlos se vuelve a
  dibujar ese idioma sin llamar a la IA.

Las tres diapositivas:
    1. Gancho: título corto y subtítulo, sobre la imagen destacada.
    2. Valor: 3 puntos clave.
    3. Llamada a la acción: leer la nota completa en el blog (el post de ese idioma si ya está en HubSpot).

Por defecto se arman los 3 idiomas de los blogs (es, pt, en), así hay uno listo para cada
post. Las imágenes y el PDF de cada idioma (las 3 páginas, para LinkedIn) van a
`imagenes_subidas` y se sirven en /api/imagenes/<id>. La nota guarda `carruseles`
({idioma: textos, URLs, id del PDF, cuándo}) y `carrusel_en_post`.

Al subir la nota a HubSpot, las diapositivas se copian a sus archivos y cada post (el original
y sus traducciones) lleva como galería el carrusel de su idioma, antes de las fuentes (ver
hubspot.con_galeria). No publica en ninguna red social: eso necesita las apps y tokens de
Meta y LinkedIn.

Uso (lo encola el dashboard):
    python -m afterdrive.carrusel --nota <id> [--idiomas es pt en] [--solo-imagenes]
"""

from __future__ import annotations

import argparse
import base64
import datetime
import html
import os
import re
import sys
from pathlib import Path

from bson import ObjectId
from bson.errors import InvalidId

ANCHO, ALTO = 1080, 1350
TITULO_MAX = 90   # tope duro; a la IA se le pide 70
SUBTITULO_MAX = 140
PUNTO_MAX = 110
CTA_MAX = 70
PUNTOS = 3

CTA_DEFAULT = {
    "es": "Leé la nota completa en el blog de AfterDrive",
    "pt": "Leia o artigo completo no blog da AfterDrive",
    "en": "Read the full article on the AfterDrive blog",
}
ETIQUETA_PUNTOS = {"es": "Lo clave", "pt": "O essencial", "en": "Key points"}
ETIQUETA_DESLIZA = {"es": "Deslizá →", "pt": "Deslize →", "en": "Swipe →"}
_IDIOMA_NOMBRE = {"es": "español rioplatense (voseo)", "pt": "portugués de Brasil", "en": "inglés"}

# Colores de la marca (los del dashboard, ver dashboard.css).
MARCA = {"principal": "#C93D58", "oscuro": "#9E2A41", "fondo": "#1D1B29", "claro": "#F6F4F9"}

_LOGO = Path(__file__).parent / "assets" / "logo_afterdrive.svg"


class ErrorCarrusel(RuntimeError):
    """Algo que el dashboard le puede mostrar a la persona."""


# ── Textos ────────────────────────────────────────────────────────────────────


def _recortar(texto: str, maximo: int) -> str:
    """Sin cortar palabras ni dejar markdown suelto."""
    texto = " ".join(re.sub(r"[*_`#>]+", "", str(texto or "")).split())
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)   # [texto](url) -> texto
    if len(texto) <= maximo:
        return texto
    corte = texto.rfind(" ", 0, maximo - 1)
    return texto[: corte if corte > maximo * 0.6 else maximo - 1].rstrip(" ,;:.") + "…"


def validar(textos: dict, idioma: str = "pt") -> dict:
    """Los textos listos para dibujar: recortados, con 3 puntos como máximo y CTA por defecto."""
    if not isinstance(textos, dict):
        raise ErrorCarrusel("Textos del carrusel inválidos.")
    titulo = _recortar(textos.get("titulo"), TITULO_MAX)
    puntos = textos.get("puntos")
    if isinstance(puntos, str):
        puntos = [p for p in puntos.splitlines() if p.strip()]
    puntos = [_recortar(p, PUNTO_MAX) for p in (puntos if isinstance(puntos, list) else []) if str(p).strip()]
    puntos = [p for p in puntos if p][:PUNTOS]
    if not titulo:
        raise ErrorCarrusel("El carrusel necesita un título.")
    if not puntos:
        raise ErrorCarrusel("El carrusel necesita al menos un punto clave.")
    return {
        "titulo": titulo,
        "subtitulo": _recortar(textos.get("subtitulo"), SUBTITULO_MAX),
        "puntos": puntos,
        "cta": _recortar(textos.get("cta"), CTA_MAX) or CTA_DEFAULT.get(idioma, CTA_DEFAULT["pt"]),
    }


def textos_sin_ia(nota_md: str, idioma: str = "pt") -> dict:
    """Título, meta description y las viñetas de la nota (primero las de implicancias)."""
    from afterdrive.generacion import calidad

    p = calidad.partes(nota_md)
    vinetas = [ln.strip()[2:] for ln in p.cuerpo.splitlines() if ln.strip().startswith(("- ", "* "))]
    vinetas = [v for v in vinetas if not v.startswith("[")]   # la sección de fuentes son links
    if not vinetas:
        # Sin viñetas: la primera oración de cada sección.
        bloques = re.split(r"^## .*$", p.cuerpo, flags=re.M)[1:]
        vinetas = [re.split(r"(?<=[.!?])\s", b.strip(), maxsplit=1)[0] for b in bloques if b.strip()]
    return validar({"titulo": p.titulo, "subtitulo": p.meta, "puntos": vinetas[:PUNTOS]}, idioma)


_SYSTEM = """\
Sos editor de redes sociales de AfterDrive by Alephee, un medio B2B sobre el aftermarket automotor.
Convertís una nota del blog en los textos de un carrusel de 3 diapositivas para Instagram y LinkedIn.

## Reglas
- Solo con lo que dice la nota: no agregues cifras, empresas ni promesas que no estén.
- Escribí en {idioma}.
- titulo: el gancho, de 70 caracteres como máximo, concreto, sin signos de exclamación ni emojis.
- subtitulo: una oración de 140 caracteres como máximo que diga por qué importa.
- puntos: exactamente 3, de 110 caracteres como máximo cada uno, accionables o con el dato clave. Sin viñetas.
- cta: una invitación a leer la nota completa en el blog, de 70 caracteres como máximo.

## Respuesta
Solo un JSON, sin texto alrededor:
{{"titulo": "...", "subtitulo": "...", "puntos": ["...", "...", "..."], "cta": "..."}}"""


def textos_con_ia(nota_md: str, idioma: str = "pt") -> dict | None:
    """Los textos que escribe el modelo barato, o None si no respondió algo usable."""
    from afterdrive.ia import llm
    from afterdrive.ia.lm_studio import _extraer_json

    try:
        crudo = llm.completar(_SYSTEM.format(idioma=_IDIOMA_NOMBRE.get(idioma, _IDIOMA_NOMBRE["pt"])),
                              f"## Nota\n{(nota_md or '')[:12000]}", temperature=0.4, max_tokens=1500,
                              tarea="carrusel")
        return validar(_extraer_json(crudo), idioma)
    except llm.Cancelada:
        raise
    except Exception as e:
        print(f"  [AVISO] La IA no armó los textos del carrusel ({e}); se sacan de la nota.", flush=True)
        return None


# ── Diseño ────────────────────────────────────────────────────────────────────


def _logo() -> str:
    try:
        svg = _LOGO.read_text(encoding="utf-8")
    except OSError:
        return ""
    return svg.replace("<svg ", '<svg class="logo" ', 1)


def _tamano(texto: str, grande: int, chico: int, largo_max: int) -> int:
    """Tamaño de letra: más chico cuanto más largo el texto, para que entre."""
    proporcion = min(1.0, len(texto) / max(1, largo_max))
    return round(grande - (grande - chico) * proporcion)


_CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: {ANCHO}px; height: {ALTO}px; }}
body {{ font-family: "Inter", "Helvetica Neue", Arial, sans-serif; color: #fff; background: {MARCA['fondo']};
        -webkit-font-smoothing: antialiased; }}
.slide {{ position: relative; width: {ANCHO}px; height: {ALTO}px; overflow: hidden; padding: 96px 88px;
          display: flex; flex-direction: column; }}
.fondo {{ position: absolute; inset: 0; background-size: cover; background-position: center; }}
.velo {{ position: absolute; inset: 0;
         background: linear-gradient(180deg, rgba(29,27,41,.25) 0%, rgba(29,27,41,.55) 45%, rgba(29,27,41,.96) 100%); }}
.contenido {{ position: relative; display: flex; flex-direction: column; height: 100%; }}
.marca {{ display: flex; align-items: center; gap: 18px; font-weight: 700; font-size: 30px; letter-spacing: .02em; }}
.logo {{ width: 52px; height: 58px; color: #fff; }}
.logo path {{ fill: currentColor; }}
.pie {{ margin-top: auto; }}
.etiqueta {{ display: inline-block; background: {MARCA['principal']}; color: #fff; font-weight: 700; font-size: 26px;
             text-transform: uppercase; letter-spacing: .08em; padding: 10px 22px; border-radius: 999px; margin-bottom: 36px; }}
h1 {{ font-weight: 800; line-height: 1.08; letter-spacing: -.01em; }}
.sub {{ margin-top: 32px; font-size: 38px; line-height: 1.35; color: rgba(255,255,255,.88); }}
.desliza {{ margin-top: 48px; font-size: 30px; font-weight: 600; color: rgba(255,255,255,.85); }}
.valor {{ background: {MARCA['claro']}; color: {MARCA['fondo']}; }}
.valor .logo {{ color: {MARCA['principal']}; }}
.valor h2 {{ font-size: 64px; font-weight: 800; margin: auto 0 56px; color: {MARCA['fondo']}; }}
.puntos {{ list-style: none; display: flex; flex-direction: column; gap: 40px; margin-bottom: auto; }}
.puntos li {{ display: flex; gap: 32px; align-items: flex-start; line-height: 1.32; font-weight: 500; }}
.num {{ flex: 0 0 76px; height: 76px; border-radius: 50%; background: {MARCA['principal']}; color: #fff;
        display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 38px; }}
.cta {{ background: linear-gradient(160deg, {MARCA['principal']} 0%, {MARCA['oscuro']} 100%); }}
.cta h1 {{ margin-top: auto; }}
.boton {{ display: inline-block; margin-top: 56px; background: #fff; color: {MARCA['oscuro']}; font-weight: 800;
          font-size: 34px; padding: 26px 44px; border-radius: 18px; }}
.url {{ margin-top: 28px; font-size: 30px; color: rgba(255,255,255,.85); word-break: break-all; }}
"""


def _pagina(cuerpo: str) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>'
            f'<body>{cuerpo}</body></html>')


def html_diapositivas(textos: dict, fondo: str | None = None, url: str = "", idioma: str = "pt") -> list[str]:
    """Las 3 páginas HTML. `fondo`: data URL de la imagen destacada (sin ella, el color de la marca)."""
    e = html.escape
    logo = _logo()
    marca = f'<div class="marca">{logo}<span>AfterDrive</span></div>'
    # Sin contador "1/3" dibujado: Instagram y LinkedIn muestran el suyo.

    fondo_css = f'<div class="fondo" style="background-image:url(\'{fondo}\')"></div><div class="velo"></div>' if fondo else ""
    t = textos["titulo"]
    gancho = (
        f'<section class="slide">{fondo_css}<div class="contenido">'
        f'<div style="position:relative">{marca}</div>'
        f'<div class="pie"><h1 style="font-size:{_tamano(t, 92, 68, TITULO_MAX)}px">{e(t)}</h1>'
        + (f'<p class="sub">{e(textos["subtitulo"])}</p>' if textos.get("subtitulo") else "")
        + f'<p class="desliza">{e(ETIQUETA_DESLIZA.get(idioma, ETIQUETA_DESLIZA["pt"]))}</p></div></div></section>'
    )
    largo = max(len(p) for p in textos["puntos"])
    tam = _tamano("x" * largo, 44, 36, PUNTO_MAX)
    valor = (
        f'<section class="slide valor"><div class="contenido">'
        f'<div style="position:relative">{marca}</div>'
        f'<h2>{e(ETIQUETA_PUNTOS.get(idioma, ETIQUETA_PUNTOS["pt"]))}</h2><ol class="puntos">'
        + "".join(f'<li style="font-size:{tam}px"><span class="num">{i}</span><span>{e(p)}</span></li>'
                  for i, p in enumerate(textos["puntos"], 1))
        + "</ol></div></section>"
    )
    c = textos["cta"]
    cta = (
        f'<section class="slide cta"><div class="contenido">'
        f'<div style="position:relative">{marca}</div>'
        f'<h1 style="font-size:{_tamano(c, 84, 64, CTA_MAX)}px">{e(c)}</h1>'
        f'<div><span class="boton">afterdrive.alephee.com</span></div>'
        + (f'<p class="url">{e(url)}</p>' if url else "")
        + "</div></section>"
    )
    return [_pagina(x) for x in (gancho, valor, cta)]


# ── Render ────────────────────────────────────────────────────────────────────


def _chromium(p):
    """Chromium de Playwright; CHROMIUM_PATH elige otro ejecutable (p. ej. el del sistema)."""
    ruta = os.getenv("CHROMIUM_PATH", "").strip()
    return p.chromium.launch(executable_path=ruta or None, args=["--no-sandbox"])


def _playwright():
    """El de Scrapling (patchright, el que instala el Dockerfile) o, si no está, playwright."""
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright
    return sync_playwright()


def renderizar(htmls: list[str], solo: list[int] | None = None) -> tuple[list[bytes | None], bytes]:
    """(PNG de cada diapositiva, PDF con las 3 páginas).

    solo: números de diapositiva (desde 1) a dibujar; las demás vuelven como None. El PDF
    siempre lleva las 3 (es un solo archivo).
    """
    try:
        with _playwright() as p:
            navegador = _chromium(p)
            try:
                pagina = navegador.new_page(viewport={"width": ANCHO, "height": ALTO})
                pngs = []
                for n, doc in enumerate(htmls, 1):
                    if solo and n not in solo:
                        pngs.append(None)
                        continue
                    pagina.set_content(doc, wait_until="load")
                    pngs.append(pagina.screenshot(type="png", clip={"x": 0, "y": 0, "width": ANCHO, "height": ALTO}))
                # PDF: las 3 en un solo documento, una por página.
                juntas = htmls[0].replace("</body></html>", "") + "".join(
                    re.search(r"<body>(.*)</body>", d, re.S).group(1) for d in htmls[1:]) + "</body></html>"
                juntas = juntas.replace("</style>", ".slide { page-break-after: always; } html, body { height: auto; }</style>", 1)
                pagina.set_content(juntas, wait_until="load")
                pdf = pagina.pdf(width=f"{ANCHO}px", height=f"{ALTO}px", print_background=True,
                                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            finally:
                navegador.close()
    except Exception as e:
        raise ErrorCarrusel(f"No se pudieron dibujar las imágenes del carrusel: {e}") from e
    return pngs, pdf


# ── Todo junto ────────────────────────────────────────────────────────────────


def _fondo(nota: dict, base) -> str | None:
    """La imagen destacada como data URL (Chromium no tiene que salir a buscarla). None si no hay o falla."""
    from afterdrive import historial, imagen_web

    im = nota.get("imagen") or {}
    url = im.get("hubspot_url") or im.get("url") or ""
    if not url:
        return None
    try:
        if url.startswith(historial.PREFIJO_IMAGEN_SUBIDA):
            local = historial.imagen_subida(url[len(historial.PREFIJO_IMAGEN_SUBIDA):], base=base)
            if not local:
                return None
            contenido, mime = local
        else:
            contenido, mime = imagen_web.descargar(url)
    except Exception as e:
        print(f"  [AVISO] No se pudo bajar la imagen destacada para el carrusel ({e}): va sin foto.", flush=True)
        return None
    return f"data:{mime};base64,{base64.b64encode(contenido).decode()}"


def url_blog(nota: dict, idioma: str) -> str:
    """A dónde manda la última diapositiva: el post en HubSpot si ya se subió, si no el blog."""
    if idioma == nota.get("idioma") and (nota.get("hubspot") or {}).get("url"):
        return nota["hubspot"]["url"]
    traduccion = (nota.get("hubspot_traducciones") or {}).get(idioma) or {}
    if traduccion.get("url"):
        return traduccion["url"]
    return os.getenv("CARRUSEL_URL_BLOG", f"https://afterdrive.alephee.com/{idioma}/blog/").strip()


IDIOMAS = ("es", "pt", "en")   # los de los blogs de HubSpot


def carruseles(nota: dict) -> dict:
    """{idioma: carrusel} de la nota. Las de antes tenían uno solo en `carrusel`."""
    guardados = {k: v for k, v in (nota.get("carruseles") or {}).items() if isinstance(v, dict)}
    viejo = nota.get("carrusel")
    if isinstance(viejo, dict) and viejo.get("idioma") and viejo["idioma"] not in guardados:
        guardados[viejo["idioma"]] = viejo
    return guardados


def migrar(col, nota: dict) -> dict:
    """Pasa el formato viejo (un solo `carrusel`) a `carruseles` + `carrusel_en_post`. Devuelve la nota al día."""
    viejo = nota.get("carrusel")
    if not isinstance(viejo, dict):
        return nota
    nuevos = carruseles(nota)
    activo = en_post_activo(nota)
    col.update_one({"_id": nota["_id"]}, {"$set": {"carruseles": nuevos, "carrusel_en_post": activo},
                                          "$unset": {"carrusel": ""}})
    nota = {k: v for k, v in nota.items() if k != "carrusel"}
    return {**nota, "carruseles": nuevos, "carrusel_en_post": activo}


def en_post_activo(nota: dict) -> bool:
    """Si las galerías van en los posts de HubSpot (prendido salvo que se haya apagado)."""
    if "carrusel_en_post" in nota:
        return nota["carrusel_en_post"] is not False
    return (nota.get("carrusel") or {}).get("en_post") is not False


def _texto_base(nota: dict, idioma: str) -> tuple[str, bool]:
    """(texto del que salen los textos, si ya está en ese idioma). Sin traducción, el original."""
    if idioma == nota.get("idioma"):
        return nota.get("contenido") or "", True
    traduccion = (nota.get("traducciones") or {}).get(idioma) or {}
    if traduccion.get("contenido"):
        return traduccion["contenido"], True
    return nota.get("contenido") or "", False


def _base(base):
    if base is not None:
        return base
    from afterdrive import db
    return db.db


def _nota(b, nota_id: str) -> dict:
    try:
        oid = ObjectId(nota_id)
    except (InvalidId, TypeError) as e:
        raise ErrorCarrusel("Nota inválida.") from e
    nota = b.notas_fase2.find_one({"_id": oid}, {"embedding": 0})
    if not nota:
        raise ErrorCarrusel("Nota no encontrada.")
    from afterdrive import hubspot
    nota["idioma"] = hubspot.idioma(nota) or nota.get("idioma") or "pt"
    return migrar(b.notas_fase2, nota)


def _textos(nota: dict, idioma: str, anterior: dict, solo_imagenes: bool) -> tuple[dict, str]:
    if solo_imagenes and anterior.get("textos"):
        return validar(anterior["textos"], idioma), anterior.get("origen_textos", "editado")
    texto, ya_traducido = _texto_base(nota, idioma)
    print(f"  [{idioma}] Escribiendo los textos del carrusel...", flush=True)
    textos = textos_con_ia(texto, idioma)
    if textos:
        return textos, "ia"
    if not ya_traducido:
        raise ErrorCarrusel(f"la IA no respondió y la nota no tiene versión en {idioma} para sacar los textos")
    return textos_sin_ia(texto, idioma), "nota"


def _guardar_archivo(b, nota_id, oid, idioma, numero, contenido, mime, ahora):
    return b.imagenes_subidas.insert_one({
        "contenido": contenido, "mime": mime, "nombre": f"carrusel-{nota_id}-{idioma}-{numero}",
        "coleccion": "notas_fase2", "nota_id": oid, "carrusel": True, "idioma": idioma, "fecha": ahora,
    }).inserted_id


def _guardar_archivos(b, nota_id, oid, idioma, pngs, pdf, ahora) -> list:
    pares = [(x, "image/png") for x in pngs] + [(pdf, "application/pdf")]
    return [_guardar_archivo(b, nota_id, oid, idioma, i, c, m, ahora) for i, (c, m) in enumerate(pares, 1)]


def _borrar_archivos(b, carrusel: dict) -> None:
    viejos = [u.rsplit("/", 1)[-1] for u in carrusel.get("diapositivas") or []]
    viejos += [carrusel["pdf_id"]] if carrusel.get("pdf_id") else []
    oids = [ObjectId(v) for v in viejos if ObjectId.is_valid(v)]
    if oids:
        b.imagenes_subidas.delete_many({"_id": {"$in": oids}, "carrusel": True})


def generar(nota_id: str, idiomas=None, solo_imagenes: bool = False, base=None, render=renderizar,
            diapositivas: list[int] | None = None) -> dict:
    """Arma el carrusel de cada idioma (por defecto los 3) y lo guarda. Devuelve {idioma: carrusel}.

    Un idioma que falla no frena a los otros; si fallan todos, ErrorCarrusel.
    solo_imagenes: usa los textos ya guardados (los editó una persona) y no llama a la IA.
    diapositivas: con solo_imagenes, redibuja solo esas (1 a 3) y deja las otras como estaban
    (las que cambiaron al corregir un texto, ver diapositivas_cambiadas). El PDF se rehace entero.
    """
    from afterdrive import historial

    b = _base(base)
    nota = _nota(b, nota_id)
    idiomas = [i for i in (idiomas or IDIOMAS)]
    if any(i not in IDIOMAS for i in idiomas):
        raise ErrorCarrusel("Idioma inválido: es, pt o en.")
    guardados = carruseles(nota)
    fondo = _fondo(nota, b)   # una sola descarga para los 3
    hechos, errores = {}, []
    for idioma in idiomas:
        anterior = guardados.get(idioma) or {}
        try:
            textos, origen = _textos(nota, idioma, anterior, solo_imagenes)
            print(f"  [{idioma}] Título: {textos['titulo']}", flush=True)
            url = url_blog(nota, idioma)
            # Redibujar solo algunas exige tener las otras ya hechas.
            parcial = sorted(set(diapositivas)) if (solo_imagenes and diapositivas
                                                     and len(anterior.get("diapositivas") or []) == 3) else None
            if parcial:
                print(f"  [{idioma}] Dibujando la diapositiva {', '.join(map(str, parcial))}...", flush=True)
                pngs, pdf = render(html_diapositivas(textos, fondo, url, idioma), solo=parcial)
            else:
                print(f"  [{idioma}] Dibujando las 3 diapositivas...", flush=True)
                pngs, pdf = render(html_diapositivas(textos, fondo, url, idioma))
        except ErrorCarrusel as e:
            print(f"  [AVISO] [{idioma}] No se armó el carrusel: {e}", flush=True)
            errores.append(f"{idioma}: {e}")
            continue
        ahora = datetime.datetime.now(datetime.UTC).isoformat()
        if parcial:
            urls, reemplazadas = list(anterior["diapositivas"]), []
            for n in parcial:
                nuevo = _guardar_archivo(b, nota_id, nota["_id"], idioma, n, pngs[n - 1], "image/png", ahora)
                reemplazadas.append(urls[n - 1])
                urls[n - 1] = historial.PREFIJO_IMAGEN_SUBIDA + str(nuevo)
            pdf_id = _guardar_archivo(b, nota_id, nota["_id"], idioma, 4, pdf, "application/pdf", ahora)
            _borrar_archivos(b, {"diapositivas": reemplazadas, "pdf_id": anterior.get("pdf_id")})
        else:
            ids = _guardar_archivos(b, nota_id, nota["_id"], idioma, pngs, pdf, ahora)
            _borrar_archivos(b, anterior)
            urls, pdf_id = [historial.PREFIJO_IMAGEN_SUBIDA + str(i) for i in ids[:-1]], ids[-1]
        # Sin hubspot_urls: las copias en HubSpot son de las imágenes anteriores y se vuelven a hacer al subir.
        hechos[idioma] = {
            "textos": textos, "origen_textos": origen, "idioma": idioma, "url": url,
            "diapositivas": urls, "pdf_id": str(pdf_id), "generado_en": ahora,
            "redibujadas": parcial or [1, 2, 3],
        }
        b.notas_fase2.update_one({"_id": nota["_id"]}, {"$set": {f"carruseles.{idioma}": hechos[idioma]}})
    if not hechos:
        raise ErrorCarrusel("No se pudo armar ningún carrusel. " + "; ".join(errores))
    return hechos


def diapositivas_cambiadas(antes: dict | None, despues: dict) -> list[int]:
    """Qué diapositivas cambian con estos textos: 1 título y subtítulo, 2 los puntos, 3 la llamada a la acción."""
    antes = antes or {}
    cambian = []
    if (antes.get("titulo"), antes.get("subtitulo")) != (despues.get("titulo"), despues.get("subtitulo")):
        cambian.append(1)
    if list(antes.get("puntos") or []) != list(despues.get("puntos") or []):
        cambian.append(2)
    if antes.get("cta") != despues.get("cta"):
        cambian.append(3)
    return cambian


def guardar_textos(nota_id: str, idioma: str, textos: dict, base=None) -> tuple[dict, list[int]]:
    """Guarda los textos editados de un idioma. Devuelve (textos, diapositivas que hay que redibujar)."""
    if idioma not in IDIOMAS:
        raise ErrorCarrusel("Idioma inválido: es, pt o en.")
    b = _base(base)
    nota = _nota(b, nota_id)
    limpios = validar(textos, idioma)
    actual = carruseles(nota).get(idioma) or {"idioma": idioma}
    cambiadas = diapositivas_cambiadas(actual.get("textos"), limpios)
    if cambiadas:
        b.notas_fase2.update_one({"_id": nota["_id"]}, {"$set": {
            f"carruseles.{idioma}": {**actual, "textos": limpios, "origen_textos": "editado"}}})
    return limpios, cambiadas


def en_post(nota_id: str, activo: bool, base=None) -> None:
    """Si las galerías de los carruseles van en los posts de HubSpot (se aplica al subir o volver a subir)."""
    b = _base(base)
    nota = _nota(b, nota_id)
    if not carruseles(nota):
        raise ErrorCarrusel("La nota no tiene carrusel.")
    b.notas_fase2.update_one({"_id": nota["_id"]}, {"$set": {"carrusel_en_post": bool(activo)}})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carruseles de 3 imágenes a partir de una nota, uno por idioma")
    parser.add_argument("--nota", required=True)
    parser.add_argument("--idiomas", nargs="+", choices=list(IDIOMAS), default=None)
    parser.add_argument("--solo-imagenes", action="store_true", help="Usa los textos guardados, sin IA")
    parser.add_argument("--diapositivas", nargs="+", type=int, choices=[1, 2, 3], default=None,
                        help="Con --solo-imagenes: redibuja solo esas")
    args = parser.parse_args(argv)
    try:
        hechos = generar(args.nota, args.idiomas, args.solo_imagenes, diapositivas=args.diapositivas)
    except ErrorCarrusel as e:
        print(f"[ERROR] {e}", flush=True)
        return 1
    print(f"[OK] Carruseles listos: {', '.join(hechos)}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
