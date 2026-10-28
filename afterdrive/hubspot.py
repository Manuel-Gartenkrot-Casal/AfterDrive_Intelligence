"""
hubspot.py — Publica Notas aprobadas en el blog de HubSpot.

Interfaz:
    configurado() -> bool
    enviar(nota, publicar=False) -> dict   {"id", "url", "estado"}
    enviar_traduccion(nota, cod, contenido, primario_id, previo=None) -> dict
                                            la versión en otro idioma, como borrador vinculado al post original
    destino(nota) -> dict                   blog, idioma, etiquetas y autor que le tocan
    autores(idioma) -> [{"id", "nombre"}]   autores del blog en ese idioma
    vista_previa(nota) -> dict              lo que se mandaría, sin llamar a HubSpot
    subir_imagen(contenido, mime, nombre) -> url pública (scope "files")
    preparar(contenido) -> dict             título, cuerpo HTML y meta description
    ErrorHubSpot

Usa la API de CMS v3 (POST/PATCH /cms/v3/blogs/posts) con el token de una app
privada de HubSpot con el scope "content". Configuración:
    HUBSPOT_TOKEN      token de la app privada (Configuración > Integraciones > Apps privadas)
    HUBSPOT_BLOG_PRUEBAS  opcional: manda TODO a este blog (para probar en el "Blog test").
                       Se prende y apaga desde la vista Desarrollador (blog_pruebas()).
                       El viejo HUBSPOT_BLOG_ID ya no se usa.
    HUBSPOT_IMAGEN_DEFAULT  opcional: imagen destacada para las notas que no tienen una propia

El blog sale del idioma de la Nota (`idioma`, portugués en las nuevas; en las
viejas, sus regiones): español -> After Drive ES, portugués -> PT, inglés -> EN. Las etiquetas son las que ya existen en HubSpot
para cada categoría, en el idioma del blog (ETIQUETAS): nunca se crean nuevas,
porque son de toda la cuenta. El autor es el elegido al revisar la nota
(hubspot_autor_id) o, si no, AUTOR_POR_DEFECTO.

Si la Nota ya se envió antes (tiene hubspot.id), se actualiza esa misma entrada
en lugar de crear otra: reenviar después de editar no duplica posts.

Traducciones (ver traducciones.py): cada versión en otro idioma se crea como
"variación de idioma" del post original (create-language-variation), así
HubSpot las muestra como traducciones entre sí (selector de idioma, hreflang).
Si eso falla (por ejemplo, si los tres blogs no están configurados como
versiones de un mismo blog multilenguaje), se crea un borrador normal en el
blog de ese idioma y se intenta vincularlo (attach-to-lang-group). Si tampoco
se puede, queda como borrador suelto, con un aviso. Siempre como borrador.
Los códigos de idioma de HubSpot salen de LENGUAJES (HUBSPOT_LENGUAJES los cambia).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

import markdown
import requests

API = "https://api.hubapi.com/cms/v3/blogs/posts"
API_AUTORES = "https://api.hubapi.com/cms/v3/blogs/authors"
API_ARCHIVOS = "https://api.hubapi.com/files/v3/files"
CARPETA_IMAGENES = "/afterdrive-notas"
TIMEOUT_S = 30
META_MAX = 155   # lo que el editor de HubSpot marca como límite de la meta description

# Blogs de After Drive en HubSpot, por idioma (GET /cms/blog-settings/.../settings).
BLOGS = {"es": ("41065736183", "After Drive (español)"),
         "pt": ("43859303259", "After Drive (português)"),
         "en": ("43859745706", "After Drive (English)")}

# Gastón Zelerteins: los autores de HubSpot son por idioma, cada uno con su id.
AUTOR_POR_DEFECTO = {"es": "37798507784", "pt": "192904642075", "en": "194508336788"}

# Etiqueta de HubSpot de cada categoría, en (es, pt, en). Son las que ya usan los
# posts publicados (GET /cms/v3/blogs/tags). Una categoría que falte acá sale sin etiqueta.
ETIQUETAS = {
    "casos-de-exito":     ("191345473040", "193208803411", "194504268663"),
    "columna-de-opinion": ("191345473109", "192987213672", "194511751685"),
    "productos":          ("117924633707", "52357766052", "117924633717"),
    "soluciones":         ("191345473180", "192987119948", "194504268326"),
    "servicios":          ("191345473198", "192987213618", "194511751446"),
    "neumaticos":         ("118356603741", "118353313330", "118353313312"),
    "autopartes":         ("192987213995", "192987214119", "194504268094"),
    "motopartes":         ("192978989387", "118353313343", "194504268186"),
    "vehiculos-pesados":  ("191345473426", "192964709492", "194504268214"),
    "estadisticas":       ("191345473564", "192964709472", "198600176544"),
    "marketplaces":       ("192245575721", "192964709439", "194508618303"),
    "catalogacion":       ("191345473652", "192960530996", "194510524238"),
    "gestion-de-ventas":  ("192488154127", "193192816560", "194502855222"),
    "logistica":          ("191345473802", "192964709240", "194502855264"),
    "rentabilidad":       ("191345473831", "192960530855", "194502855332"),
    "eventos":            ("132665181879", "192964709123", "136907936677"),
}
_COLUMNA = {"es": 0, "pt": 1, "en": 2}

# Código de idioma de cada blog en HubSpot. HUBSPOT_LENGUAJES="es=es-ar,pt=pt-br,en=en" los cambia
# (deben coincidir con el idioma configurado en cada blog).
LENGUAJES = {"es": "es", "pt": "pt-br", "en": "en"}
API_VARIACION = f"{API}/multi-language/create-language-variation"
API_VINCULAR = f"{API}/multi-language/attach-to-lang-group"

_transporte = {"post": requests.post, "patch": requests.patch, "get": requests.get,
               "subir": requests.post}   # seam para los tests


class ErrorHubSpot(RuntimeError):
    """Fallo al publicar, con un mensaje apto para el usuario."""


def configurado() -> bool:
    return bool(os.getenv("HUBSPOT_TOKEN"))


def blog_pruebas() -> str:
    """Id del blog de pruebas si está cargado y el switch de la vista Desarrollador está prendido."""
    forzado = os.getenv("HUBSPOT_BLOG_PRUEBAS", "").strip()
    if not forzado:
        return ""
    try:
        from afterdrive import config_store
        activo = config_store.get_blog_pruebas_config()
    except Exception:
        activo = True  # sin Mongo, como antes: manda la variable
    return forzado if activo else ""


def idioma(nota: dict) -> str | None:
    """es, pt o en: el idioma en que se escribió la nota. None si no hay blog en ese idioma.

    Las notas nuevas lo guardan (`idioma`, el principal: portugués); las
    anteriores lo deducen de la voz de sus regiones.
    """
    from afterdrive.ia.redaccion import voz

    if nota.get("idioma") in BLOGS:
        return nota["idioma"]

    nombre = voz(nota.get("regiones")).idioma
    if nombre.startswith("español"):
        return "es"
    return {"portugués": "pt", "inglés": "en"}.get(nombre.split()[0])


def destino(nota: dict) -> dict:
    """Blog, etiquetas y autor que le tocan a la nota en HubSpot. Sin llamar a HubSpot."""
    cod = idioma(nota)
    if not cod:
        raise ErrorHubSpot("No hay un blog de After Drive en el idioma de esta nota: solo español, portugués e inglés.")
    blog_id, blog = BLOGS[cod]
    # Otro nombre que el viejo HUBSPOT_BLOG_ID (el blog de producción): uno que
    # haya quedado cargado en Render no manda todo a un solo blog.
    forzado = blog_pruebas()
    if forzado:
        blog_id, blog = forzado, f"Blog de pruebas ({forzado})"
    categorias = [c for c in nota.get("categorias") or [] if c in ETIQUETAS]
    return {
        "idioma": cod, "blog_id": blog_id, "blog": blog,
        "etiquetas": _nombres_etiquetas({"categorias": categorias}),
        "tag_ids": [ETIQUETAS[c][_COLUMNA[cod]] for c in categorias],
        "autor_id": str(nota.get("hubspot_autor_id") or AUTOR_POR_DEFECTO[cod]),
    }


def autores(cod: str) -> list[dict]:
    """Autores del blog en ese idioma, por nombre: para elegir quién firma la nota."""
    if not configurado():
        raise ErrorHubSpot("HubSpot no está configurado: falta HUBSPOT_TOKEN.")
    try:
        resp = _transporte["get"](API_AUTORES, params={"limit": 100}, headers=_headers(), timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErrorHubSpot(f"No se pudo conectar con HubSpot: {e}") from e
    if resp.status_code >= 400:
        raise _error(resp)
    lista = [{"id": str(a["id"]), "nombre": (a.get("fullName") or a.get("name") or "").strip()}
             for a in resp.json().get("results", []) if a.get("language") == cod]
    return sorted(lista, key=lambda a: a["nombre"].lower())


def _slug(texto: str, sufijo: str = "") -> str:
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-")[:80].rstrip("-")
    return f"{slug}-{sufijo}" if sufijo else slug


def preparar(contenido: str) -> dict:
    """Separa el título (# ...) y la meta description (*...* al final) del cuerpo.

    HubSpot muestra el título aparte: si quedara también en el cuerpo, saldría
    dos veces. La meta description de la Nota es la última línea en cursiva.
    """
    from afterdrive.ia.saneo import normalizar_formato

    # Las notas anteriores al arreglo de formato también salen bien.
    lineas = normalizar_formato((contenido or "").strip()).splitlines()
    titulo = ""
    for i, ln in enumerate(lineas):
        if ln.startswith("# "):
            titulo = ln[2:].strip().strip("*_ ")
            del lineas[i]
            break
    meta = ""
    while lineas and not lineas[-1].strip():
        lineas.pop()
    if lineas:
        ultima = lineas[-1].strip()
        m = re.fullmatch(r"[*_]{1,2}([^*_].*?)[*_]{1,2}", ultima)
        if m and len(m.group(1)) <= 300:
            meta = m.group(1).strip()
            lineas.pop()
    # Sin HTML crudo: si el modelo escribió un <script> o un <iframe>, llegaría
    # tal cual al blog. Las notas son Markdown; un "<" literal se ve igual.
    cuerpo = "\n".join(lineas).strip().replace("<", "&lt;")
    if not titulo:
        raise ErrorHubSpot("La nota no tiene título (una línea que empiece con '# ').")
    html = markdown.markdown(cuerpo, extensions=["extra", "sane_lists"])
    # Los posts del blog usan <h3> para los subtítulos: "## " baja un nivel (y "### " a h4).
    html = re.sub(r"<(/?)h([2-5])\b", lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}", html)
    return {"titulo": titulo, "html": html, "meta": _recortar(meta, META_MAX)}


def _recortar(texto: str, maximo: int) -> str:
    """El texto hasta `maximo` caracteres, sin cortar una palabra al medio."""
    if len(texto) <= maximo:
        return texto
    corte = texto[: maximo - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return corte + "…"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('HUBSPOT_TOKEN', '')}", "Content-Type": "application/json"}


def _error(resp) -> ErrorHubSpot:
    try:
        detalle = resp.json().get("message", "")
    except Exception:
        detalle = (resp.text or "")[:200]
    if resp.status_code in (401, 403):
        return ErrorHubSpot("HubSpot rechazó el token: revisá HUBSPOT_TOKEN y que la app privada tenga el scope 'content'.")
    if resp.status_code == 404:
        return ErrorHubSpot("HubSpot no encontró el blog, el post o el autor: revisá HUBSPOT_BLOG_PRUEBAS (si está cargado) y el autor elegido.")
    if resp.status_code == 429:
        return ErrorHubSpot("HubSpot está limitando las llamadas (429): probá de nuevo en un minuto.")
    return ErrorHubSpot(f"HubSpot respondió {resp.status_code}: {detalle}")


def despublicar(post_id: str) -> None:
    """Vuelve un post de HubSpot a borrador: deja de verse en el blog."""
    if not configurado():
        raise ErrorHubSpot("HubSpot no está configurado: falta HUBSPOT_TOKEN.")
    try:
        resp = _transporte["patch"](f"{API}/{post_id}", json={"state": "DRAFT"}, headers=_headers(), timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErrorHubSpot(f"No se pudo conectar con HubSpot: {e}") from e
    if resp.status_code >= 400:
        raise _error(resp)


def _nombres_etiquetas(nota: dict) -> list[str]:
    from afterdrive.generacion.scraper_afterdrive import CATEGORIAS
    return [CATEGORIAS.get(c, c) for c in nota.get("categorias") or []]


def _imagen(nota: dict, titulo: str) -> dict:
    """{url, alt} de la imagen destacada: la de la nota o la de por defecto.

    La de la nota es la foto de una de sus noticias; al subirla se copia a los
    archivos de HubSpot (hubspot_url) y se usa esa copia.
    """
    propia = nota.get("imagen") or {}
    # Una subida desde la computadora tiene una ruta de este servidor: solo sirve su copia en HubSpot.
    externa = propia.get("url") if not str(propia.get("url") or "").startswith("/") else ""
    url = propia.get("hubspot_url") or externa or os.getenv("HUBSPOT_IMAGEN_DEFAULT", "").strip()
    return {"url": url, "alt": propia.get("alt") or titulo} if url else {}


def imagenes_cuerpo(nota: dict) -> list[dict]:
    """[{url, alt}] de las imágenes que van dentro del texto (la copia en HubSpot si ya se hizo)."""
    return [{"url": im.get("hubspot_url") or im.get("url"), "alt": im.get("alt") or ""}
            for im in nota.get("imagenes_cuerpo") or [] if im.get("hubspot_url") or im.get("url")]


def con_imagenes(html: str, imagenes: list[dict]) -> str:
    """Reparte las imágenes entre las secciones del cuerpo: antes de los subtítulos a 1/3 y 2/3 de la nota.

    Nunca antes de la primera sección (la nota abre con texto) ni después de
    la última. Sin subtítulos suficientes, van después del primer párrafo.
    """
    from html import escape

    if not imagenes:
        return html
    figuras = [f'<p><img src="{escape(im["url"], quote=True)}" alt="{escape(im["alt"], quote=True)}" '
               f'style="max-width:100%; height:auto;" loading="lazy"></p>' for im in imagenes]
    titulos = [m.start() for m in re.finditer(r"<h3\b", html)]
    n = len(titulos)
    if n >= 3:
        indices = sorted({min(n - 1, max(1, round(n * (k + 1) / (len(figuras) + 1)))) for k in range(len(figuras))})
        # Si dos imágenes caen en el mismo lugar, van juntas.
        grupos = {i: [] for i in indices}
        for k, fig in enumerate(figuras):
            grupos[indices[min(k, len(indices) - 1)]].append(fig)
        for i in sorted(grupos, reverse=True):
            html = html[:titulos[i]] + "".join(grupos[i]) + html[titulos[i]:]
        return html
    fin = html.find("</p>")
    corte = fin + 4 if fin >= 0 else len(html)
    return html[:corte] + "".join(figuras) + html[corte:]


def subir_imagen(contenido: bytes, mime: str, nombre: str) -> str:
    """Sube una imagen al gestor de archivos de HubSpot y devuelve su URL pública.

    Necesita el scope "files" en la app privada, además de "content".
    """
    if not configurado():
        raise ErrorHubSpot("HubSpot no está configurado: falta HUBSPOT_TOKEN.")
    opciones = {"access": "PUBLIC_INDEXABLE", "overwrite": False, "duplicateValidationStrategy": "NONE"}
    try:
        resp = _transporte["subir"](
            API_ARCHIVOS,
            files={"file": (nombre, contenido, mime)},
            data={"folderPath": CARPETA_IMAGENES, "fileName": nombre, "options": json.dumps(opciones)},
            headers={"Authorization": f"Bearer {os.getenv('HUBSPOT_TOKEN', '')}"},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise ErrorHubSpot(f"No se pudo subir la imagen a HubSpot: {e}") from e
    if resp.status_code in (401, 403):
        raise ErrorHubSpot("HubSpot no dejó subir la imagen: la app privada necesita el scope 'files'.")
    if resp.status_code >= 400:
        raise _error(resp)
    url = (resp.json() or {}).get("url") or ""
    if not url:
        raise ErrorHubSpot("HubSpot subió la imagen pero no devolvió su URL.")
    return url


def vista_previa(nota: dict) -> dict:
    """Lo que se mandaría a HubSpot (título, meta, imagen, etiquetas y cuerpo), sin llamarlo."""
    partes = preparar(nota.get("contenido", ""))
    previo = nota.get("hubspot") or {}
    try:
        lugar = destino(nota)
    except ErrorHubSpot as e:
        lugar = {"error": str(e), "etiquetas": []}
    partes["html"] = con_imagenes(partes["html"], imagenes_cuerpo(nota))
    return {
        **partes,
        "imagen": _imagen(nota, partes["titulo"]),
        "etiquetas": lugar["etiquetas"],
        "destino": {k: v for k, v in lugar.items() if k != "tag_ids"},
        "slug": previo.get("slug") or _slug(partes["titulo"], str(nota.get("_id", ""))[-6:]),
    }


def enviar(nota: dict, publicar: bool = False) -> dict:
    """Crea (o actualiza) el post de la Nota en HubSpot, como borrador o publicado.

    nota: documento de Mongo con "_id", "contenido" y opcionalmente "hubspot",
    "imagen", "categorias", "regiones" y "hubspot_autor_id".
    """
    if not configurado():
        raise ErrorHubSpot("HubSpot no está configurado: falta HUBSPOT_TOKEN.")
    partes = preparar(nota.get("contenido", ""))
    lugar = destino(nota)
    cuerpo = {
        "name": partes["titulo"],
        "htmlTitle": partes["titulo"],
        "postBody": con_imagenes(partes["html"], imagenes_cuerpo(nota)),
        "metaDescription": partes["meta"],
        "state": "PUBLISHED" if publicar else "DRAFT",
    }
    previo = (nota.get("hubspot") or {}).get("id")
    # Al actualizar, autor y etiquetas solo si vienen de acá: no pisar lo que el
    # equipo haya cambiado a mano en HubSpot.
    if not previo or nota.get("hubspot_autor_id"):
        cuerpo["blogAuthorId"] = lugar["autor_id"]
    if lugar["tag_ids"]:
        cuerpo["tagIds"] = lugar["tag_ids"]
    imagen = _imagen(nota, partes["titulo"])
    if imagen:
        cuerpo.update(useFeaturedImage=True, featuredImage=imagen["url"], featuredImageAltText=imagen["alt"])

    try:
        if previo:
            resp = _transporte["patch"](f"{API}/{previo}", json=cuerpo, headers=_headers(), timeout=TIMEOUT_S)
        else:
            # Blog y slug van solo al crear: cambiarlos después rompería links ya compartidos.
            cuerpo["contentGroupId"] = lugar["blog_id"]
            cuerpo["slug"] = _slug(partes["titulo"], str(nota.get("_id", ""))[-6:])
            resp = _transporte["post"](API, json=cuerpo, headers=_headers(), timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErrorHubSpot(f"No se pudo conectar con HubSpot: {e}") from e
    if resp.status_code >= 400:
        raise _error(resp)
    data = resp.json()
    return {
        "id": str(data.get("id") or previo),
        "url": data.get("url") or "",
        "estado": data.get("state") or cuerpo["state"],
        "slug": data.get("slug") or cuerpo.get("slug") or (nota.get("hubspot") or {}).get("slug") or "",
    }


class ErrorHubSpotParcial(ErrorHubSpot):
    """El post se creó pero no se pudo completar: `post_id` permite actualizarlo en el próximo intento."""

    def __init__(self, mensaje: str, post_id: str):
        super().__init__(mensaje)
        self.post_id = post_id


def lenguaje(cod: str) -> str:
    """Código de idioma de HubSpot para es, pt o en."""
    for par in os.getenv("HUBSPOT_LENGUAJES", "").split(","):
        clave, _, valor = par.partition("=")
        if clave.strip() == cod and valor.strip():
            return valor.strip().lower()
    return LENGUAJES[cod]


def _llamar(metodo: str, url: str, cuerpo: dict):
    try:
        resp = _transporte[metodo](url, json=cuerpo, headers=_headers(), timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErrorHubSpot(f"No se pudo conectar con HubSpot: {e}") from e
    return resp


def _resultado(data: dict, cuerpo: dict, previo: dict | None = None) -> dict:
    previo = previo or {}
    return {
        "id": str(previo.get("id") or data.get("id") or ""),   # el post que se actualizó manda
        "url": data.get("url") or previo.get("url") or "",
        "estado": data.get("state") or cuerpo.get("state") or "DRAFT",
        "slug": data.get("slug") or cuerpo.get("slug") or previo.get("slug") or "",
    }


def enviar_traduccion(nota: dict, cod: str, contenido: str, primario_id: str, previo: dict | None = None) -> dict:
    """Crea (o actualiza) la versión de la Nota en el idioma `cod`, como borrador.

    contenido: la nota traducida (Markdown). primario_id: el post original en
    HubSpot. previo: lo que se guardó de un envío anterior de esta traducción.
    Devuelve {"id", "url", "estado", "slug", "vinculada", "aviso"}.
    """
    if not configurado():
        raise ErrorHubSpot("HubSpot no está configurado: falta HUBSPOT_TOKEN.")
    origen = idioma(nota)
    if cod not in BLOGS or not origen or cod == origen:
        raise ErrorHubSpot(f"No hay a qué idioma traducir: {cod}.")
    partes = preparar(contenido)
    categorias = [c for c in nota.get("categorias") or [] if c in ETIQUETAS]
    cuerpo = {
        "name": partes["titulo"], "htmlTitle": partes["titulo"],
        "postBody": con_imagenes(partes["html"], imagenes_cuerpo(nota)),
        "metaDescription": partes["meta"], "state": "DRAFT",
    }
    imagen = _imagen(nota, partes["titulo"])
    if imagen:
        cuerpo.update(useFeaturedImage=True, featuredImage=imagen["url"], featuredImageAltText=imagen["alt"])
    previo = previo or {}
    if previo.get("id"):
        # Ya existe: solo el contenido. Autor y etiquetas no se pisan (se pueden haber cambiado a mano).
        resp = _llamar("patch", f"{API}/{previo['id']}", cuerpo)
        if resp.status_code >= 400:
            raise _error(resp)
        return {**_resultado(resp.json(), cuerpo, previo), "vinculada": previo.get("vinculada", False), "aviso": ""}

    cuerpo["blogAuthorId"] = AUTOR_POR_DEFECTO[cod]
    if categorias:
        cuerpo["tagIds"] = [ETIQUETAS[c][_COLUMNA[cod]] for c in categorias]
    cuerpo["slug"] = _slug(partes["titulo"], f"{str(nota.get('_id', ''))[-6:]}-{cod}")
    forzado = blog_pruebas()
    if forzado:
        # Blog de pruebas: todo al mismo blog, sin vincular (no es multilenguaje).
        resp = _llamar("post", API, {**cuerpo, "contentGroupId": forzado})
        if resp.status_code >= 400:
            raise _error(resp)
        return {**_resultado(resp.json(), cuerpo), "vinculada": False,
                "aviso": "Blog de pruebas: la traducción se sube suelta, sin vincular al post original."}

    # 1) Variación de idioma del post original: HubSpot la crea en el blog de ese idioma, ya vinculada.
    resp = _llamar("post", API_VARIACION, {"id": str(primario_id), "language": lenguaje(cod),
                                           "primaryLanguage": lenguaje(origen)})
    if resp.status_code < 400 and (resp.json() or {}).get("id"):
        nuevo = str(resp.json()["id"])
        actualizado = _llamar("patch", f"{API}/{nuevo}", cuerpo)
        if actualizado.status_code >= 400:
            raise ErrorHubSpotParcial(str(_error(actualizado)), nuevo)
        return {**_resultado(actualizado.json(), cuerpo, {"id": nuevo}), "vinculada": True, "aviso": ""}
    motivo_variacion = str(_error(resp))

    # 2) Borrador normal en el blog de ese idioma, y vincularlo al original.
    resp = _llamar("post", API, {**cuerpo, "contentGroupId": BLOGS[cod][0]})
    if resp.status_code >= 400:
        raise _error(resp)
    creado = _resultado(resp.json(), cuerpo)
    vinculo = _llamar("post", API_VINCULAR, {"id": creado["id"], "language": lenguaje(cod),
                                             "primaryId": str(primario_id), "primaryLanguage": lenguaje(origen)})
    if vinculo.status_code < 400:
        return {**creado, "vinculada": True, "aviso": ""}
    return {**creado, "vinculada": False,
            "aviso": (f"Se subió como borrador suelto en {BLOGS[cod][1]}: HubSpot no dejó vincularla como traducción "
                      f"({motivo_variacion}). Revisá que los blogs estén configurados como versiones de un mismo "
                      "blog multilenguaje y el idioma de cada uno (HUBSPOT_LENGUAJES).")}
