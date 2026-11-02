"""
carrusel.py — Un carrusel de 3 imágenes para redes a partir de una Nota.

Interfaz:
    textos_con_ia(nota_md, idioma) -> dict | None      {"titulo", "subtitulo", "puntos", "cta"}
    textos_sin_ia(nota_md, idioma) -> dict             mismo formato, sacado del texto de la nota
    validar(textos) -> dict                            recorta y completa; ErrorCarrusel si falta lo esencial
    html_diapositivas(textos, fondo=None, url="") -> [str]   una página HTML por diapositiva
    renderizar(htmls) -> ([png], pdf)                  con Chromium (Playwright)
    generar(nota_id, idioma=None, solo_imagenes=False, base=None) -> dict   todo junto, y lo guarda

Las tres diapositivas (1080x1350, el formato vertical de Instagram):
    1. Gancho: título corto y subtítulo, sobre la imagen destacada de la nota.
    2. Valor: 3 puntos clave.
    3. Llamada a la acción: leer la nota completa en el blog.

Los textos los escribe el modelo barato (tarea "carrusel" → el de evaluación) solo con lo
que dice la nota; si falla, salen del texto (título, meta description y las viñetas de
implicancias). Se pueden editar en el dashboard: al guardarlos se vuelven a dibujar las
imágenes sin llamar a la IA.

Las imágenes y el PDF (las 3 páginas, para subir a LinkedIn como documento) se guardan en
`imagenes_subidas` y se sirven en /api/imagenes/<id>. La nota guarda en `carrusel` los
textos, las URLs, el id del PDF, el idioma y cuándo se generó.

Al subir la nota a HubSpot, las diapositivas se copian a sus archivos y van como galería
en el post del idioma del carrusel, antes de las fuentes (`en_post`, prendido por defecto;
ver hubspot.con_galeria). No publica en ninguna red social: eso necesita las apps y tokens
de Meta y LinkedIn.

Uso (lo encola el dashboard):
    python -m afterdrive.carrusel --nota <id> [--idioma pt] [--solo-imagenes]
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
.contador {{ position: absolute; right: 0; top: 6px; font-size: 26px; color: rgba(255,255,255,.7); }}
.desliza {{ margin-top: 48px; font-size: 30px; font-weight: 600; color: rgba(255,255,255,.85); }}
.valor {{ background: {MARCA['claro']}; color: {MARCA['fondo']}; }}
.valor .logo {{ color: {MARCA['principal']}; }}
.valor .contador {{ color: rgba(29,27,41,.55); }}
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
    total = 3

    def contador(n: int) -> str:
        return f'<span class="contador">{n}/{total}</span>'

    fondo_css = f'<div class="fondo" style="background-image:url(\'{fondo}\')"></div><div class="velo"></div>' if fondo else ""
    t = textos["titulo"]
    gancho = (
        f'<section class="slide">{fondo_css}<div class="contenido">'
        f'<div style="position:relative">{marca}{contador(1)}</div>'
        f'<div class="pie"><h1 style="font-size:{_tamano(t, 92, 68, TITULO_MAX)}px">{e(t)}</h1>'
        + (f'<p class="sub">{e(textos["subtitulo"])}</p>' if textos.get("subtitulo") else "")
        + f'<p class="desliza">{e(ETIQUETA_DESLIZA.get(idioma, ETIQUETA_DESLIZA["pt"]))}</p></div></div></section>'
    )
    largo = max(len(p) for p in textos["puntos"])
    tam = _tamano("x" * largo, 44, 36, PUNTO_MAX)
    valor = (
        f'<section class="slide valor"><div class="contenido">'
        f'<div style="position:relative">{marca}{contador(2)}</div>'
        f'<h2>{e(ETIQUETA_PUNTOS.get(idioma, ETIQUETA_PUNTOS["pt"]))}</h2><ol class="puntos">'
        + "".join(f'<li style="font-size:{tam}px"><span class="num">{i}</span><span>{e(p)}</span></li>'
                  for i, p in enumerate(textos["puntos"], 1))
        + "</ol></div></section>"
    )
    c = textos["cta"]
    cta = (
        f'<section class="slide cta"><div class="contenido">'
        f'<div style="position:relative">{marca}{contador(3)}</div>'
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


def renderizar(htmls: list[str]) -> tuple[list[bytes], bytes]:
    """(PNG de cada diapositiva, PDF con las 3 páginas)."""
    try:
        with _playwright() as p:
            navegador = _chromium(p)
            try:
                pagina = navegador.new_page(viewport={"width": ANCHO, "height": ALTO})
                pngs = []
                for doc in htmls:
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


def _texto_en(nota: dict, idioma: str) -> str:
    if idioma == nota.get("idioma") or not idioma:
        return nota.get("contenido") or ""
    traduccion = (nota.get("traducciones") or {}).get(idioma) or {}
    if not traduccion.get("contenido"):
        raise ErrorCarrusel(f"La nota todavía no tiene versión en {idioma}: traducila antes de armar el carrusel.")
    return traduccion["contenido"]


def _base(base):
    if base is not None:
        return base
    from afterdrive import db
    return db.db


def generar(nota_id: str, idioma: str | None = None, solo_imagenes: bool = False, base=None,
            render=renderizar) -> dict:
    """Arma el carrusel de la nota y lo guarda en ella. Devuelve lo guardado en `carrusel`.

    solo_imagenes: usa los textos ya guardados (los editó una persona) y no llama a la IA.
    """
    from afterdrive import hubspot

    b = _base(base)
    try:
        oid = ObjectId(nota_id)
    except (InvalidId, TypeError) as e:
        raise ErrorCarrusel("Nota inválida.") from e
    nota = b.notas_fase2.find_one({"_id": oid}, {"embedding": 0})
    if not nota:
        raise ErrorCarrusel("Nota no encontrada.")
    nota["idioma"] = hubspot.idioma(nota) or nota.get("idioma") or "pt"
    anterior = nota.get("carrusel") or {}
    idioma = idioma or anterior.get("idioma") or nota["idioma"]
    if idioma not in CTA_DEFAULT:
        raise ErrorCarrusel("Idioma inválido: es, pt o en.")

    if solo_imagenes and anterior.get("textos"):
        textos, origen = validar(anterior["textos"], idioma), anterior.get("origen_textos", "editado")
    else:
        texto = _texto_en(nota, idioma)
        print("  Escribiendo los textos del carrusel...", flush=True)
        textos = textos_con_ia(texto, idioma)
        origen = "ia" if textos else "nota"
        textos = textos or textos_sin_ia(texto, idioma)
    print(f"  Título: {textos['titulo']}", flush=True)

    url = url_blog(nota, idioma)
    print("  Dibujando las 3 diapositivas...", flush=True)
    pngs, pdf = render(html_diapositivas(textos, _fondo(nota, b), url, idioma))

    from afterdrive import historial
    ahora = datetime.datetime.now(datetime.UTC).isoformat()
    ids = []
    for i, (contenido, mime) in enumerate([(x, "image/png") for x in pngs] + [(pdf, "application/pdf")], 1):
        ids.append(b.imagenes_subidas.insert_one({
            "contenido": contenido, "mime": mime, "nombre": f"carrusel-{nota_id}-{i}", "coleccion": "notas_fase2",
            "nota_id": oid, "carrusel": True, "fecha": ahora}).inserted_id)
    # Las del carrusel anterior ya no se usan.
    viejos = [ObjectId(u.rsplit("/", 1)[-1]) for u in anterior.get("diapositivas") or [] if u.rsplit("/", 1)[-1]]
    if anterior.get("pdf_id"):
        viejos.append(ObjectId(anterior["pdf_id"]))
    if viejos:
        b.imagenes_subidas.delete_many({"_id": {"$in": viejos}, "carrusel": True})

    carrusel = {
        "textos": textos, "origen_textos": origen, "idioma": idioma, "url": url,
        "diapositivas": [historial.PREFIJO_IMAGEN_SUBIDA + str(i) for i in ids[:-1]],
        "pdf_id": str(ids[-1]), "generado_en": ahora,
        # La galería en el post de HubSpot: se mantiene lo que se eligió para el carrusel anterior.
        "en_post": anterior.get("en_post", True),
    }
    b.notas_fase2.update_one({"_id": oid}, {"$set": {"carrusel": carrusel}})
    return carrusel


def guardar_textos(nota_id: str, textos: dict, base=None) -> dict:
    """Guarda los textos editados en el dashboard (después se vuelven a dibujar las imágenes)."""
    b = _base(base)
    try:
        oid = ObjectId(nota_id)
    except (InvalidId, TypeError) as e:
        raise ErrorCarrusel("Nota inválida.") from e
    nota = b.notas_fase2.find_one({"_id": oid}, {"carrusel": 1})
    if not nota:
        raise ErrorCarrusel("Nota no encontrada.")
    idioma = (nota.get("carrusel") or {}).get("idioma") or "pt"
    limpios = validar(textos, idioma)
    b.notas_fase2.update_one({"_id": oid}, {"$set": {"carrusel.textos": limpios, "carrusel.idioma": idioma,
                                                     "carrusel.origen_textos": "editado"}})
    return limpios


def en_post(nota_id: str, activo: bool, base=None) -> None:
    """Si la galería del carrusel va en el post de HubSpot (se aplica al subir o volver a subir la nota)."""
    b = _base(base)
    try:
        oid = ObjectId(nota_id)
    except (InvalidId, TypeError) as e:
        raise ErrorCarrusel("Nota inválida.") from e
    if not b.notas_fase2.update_one({"_id": oid, "carrusel": {"$exists": True}},
                                    {"$set": {"carrusel.en_post": bool(activo)}}).matched_count:
        raise ErrorCarrusel("La nota no tiene carrusel.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carrusel de 3 imágenes a partir de una nota")
    parser.add_argument("--nota", required=True)
    parser.add_argument("--idioma", choices=list(CTA_DEFAULT), default=None)
    parser.add_argument("--solo-imagenes", action="store_true", help="Usa los textos guardados, sin IA")
    args = parser.parse_args(argv)
    try:
        carrusel = generar(args.nota, args.idioma, args.solo_imagenes)
    except ErrorCarrusel as e:
        print(f"[ERROR] {e}", flush=True)
        return 1
    print(f"[OK] Carrusel listo: {len(carrusel['diapositivas'])} imágenes y PDF.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
