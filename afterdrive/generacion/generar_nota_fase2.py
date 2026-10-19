"""
generar_nota_fase2.py — Generador de notas estilo AfterDrive by Alephee.

Recorrido de una nota:
  1. Noticias de contexto: las noticias scrapeadas más útiles para el pedido
     (contexto_noticias), con su ficha. Son la única fuente de cifras,
     empresas y casos. Las usadas hace poco quedan para el final.
  2. Referencias de estilo: notas reales del blog (afterdrive_ejemplos), que
     también son los enlaces internos sugeridos, y notas propias que el equipo
     calificó alto.
  3. Calibración (calibracion.py): correcciones de rechazos, calificaciones y
     ediciones; aciertos; umbral del evaluador.
  4. Plan (plan.py): ángulo, título, palabra clave y secciones, sin repetir el
     ángulo de las notas recientes.
  5. Prompt: system de redaccion.py (persona + región + secciones fijas + SEO)
     ajustado al proveedor activo + pedido con noticias, referencias y plan.
  6. Redacción y revisión de cada versión: saneo (saneo.py), enlaces
     inventados afuera y datos contra las noticias (verificacion.py), estilo y
     SEO (calidad.py), evaluación con IA y parecido con notas recientes. Un
     problema grave se arregla una vez con el modelo de corrección
     (correccion.py, barato); solo una nota repetida se reescribe de cero.
     Queda la mejor versión.
  7. El largo (corto, medio, largo) se elige en Crear nota.
  8. Lo que gastó la API paga en esta nota queda en `costo`. La imagen
     destacada se genera con NVIDIA (imagenes.py), siempre gratis.
  9. Sección de fuentes con las noticias usadas, y todo lo revisado se guarda
     con la nota para mostrarlo al revisarla.

Uso:
    python -m afterdrive.generacion.generar_nota_fase2 \\
        --categorias autopartes marketplaces \\
        --clientes cliente_a cliente_b \\
        --puntapie https://alephee.com/landing \\
        --persona comercial
"""

import argparse
import datetime
import os
import sys
from dataclasses import dataclass, field

from afterdrive import calibracion, imagenes
from afterdrive.db import ESTADO_BORRADOR, db, registrar_nota_descartada
from afterdrive.generacion import calidad, contexto_noticias, correccion, plan, verificacion
from afterdrive.generacion.regiones import REGION_SLUGS, REGIONES
from afterdrive.generacion.scraper_afterdrive import CATEGORIAS, get_ejemplos_por_tags
from afterdrive.ia import consumo, llm, redaccion
from afterdrive.ia.saneo import sanear

col_notas_fase2 = db["notas_fase2"]
col_clientes = db["clientes"]

EJEMPLOS_POR_CATEGORIA = 2
NOTICIAS_POR_NOTA = 5


def _recortar_parrafos(texto: str, limite: int) -> str:
    """Corta en el último párrafo completo que entra, para no imitar notas truncadas."""
    texto = (texto or "").strip()
    if len(texto) <= limite:
        return texto
    corte = texto.rfind("\n", 0, limite)
    return texto[:corte].rstrip() if corte > limite * 0.5 else texto[:limite].rstrip() + "..."


def _formatear_ejemplos(ejemplos: list[dict], chars: int) -> str:
    bloques = []
    for i, ej in enumerate(ejemplos, 1):
        bloques.append(
            f"--- Referencia {i} ---\n"
            f"# {ej.get('titulo', '')}\n"
            f"{_recortar_parrafos(ej.get('cuerpo', ''), chars)}"
        )
    return "\n\n".join(bloques)


def _formatear_clientes(clientes: list[dict]) -> str:
    lines = []
    for c in clientes:
        linea = f"- {c.get('nombre', '')}"
        if c.get("descripcion"):
            linea += f": {c['descripcion']}"
        if c.get("productos"):
            linea += f" | Productos/servicios: {', '.join(c['productos'])}"
        lines.append(linea)
    return "\n".join(lines)


def _build_system_prompt(
    categorias: list[str],
    clientes: list[dict],
    puntapie_url: str | None,
    persona: str,
    regiones: list[str] | None = None,
    ajustes: "llm.Redaccion | None" = None,
    largo: str | None = None,
) -> str:
    ajustes = ajustes or llm.Redaccion()
    base = redaccion.system_prompt(
        persona,
        region=regiones,
        compacto=ajustes.compacto,
        extension=redaccion.extension(largo),
        puntapie_url=puntapie_url,
    )
    extra = []
    if regiones:
        nombres = [REGIONES.get(s, s) for s in regiones]
        extra.append(
            f"- Región: {', '.join(nombres)}. Contextualizá la nota en ese mercado; datos de otras "
            "regiones solo como comparación puntual."
        )
    if categorias:
        nombres = [CATEGORIAS.get(s, s) for s in categorias]
        extra.append(
            f"- Categorías: {', '.join(nombres)}. La nota tiene que encuadrarse en ellas, respetando la "
            "estructura de secciones de arriba."
        )
    if clientes:
        extra.append(
            "- Clientes a mencionar como casos o ejemplos del sector, con contexto real y sin tono "
            f"publicitario:\n{_formatear_clientes(clientes)}"
        )
    else:
        extra.append("- No menciones clientes específicos de Alephee.")
    prompt = base + "\n\n## Para esta nota\n" + "\n".join(extra)
    # La indicación propia del modelo va al final: es lo último que lee.
    return prompt + ("\n\n" + ajustes.directiva if ajustes.directiva else "")


def _build_user_prompt(
    noticias: list,
    ejemplos: list[dict],
    categorias: list[str],
    tema: str | None,
    ajustes: "llm.Redaccion | None" = None,
    evitar: list[str] | None = None,
    plan_nota: dict | None = None,
    aciertos: list[str] | None = None,
    propios: list[dict] | None = None,
    enlaces: list[dict] | None = None,
) -> str:
    ajustes = ajustes or llm.Redaccion()
    partes = []
    if noticias:
        partes.append(
            "## Noticias de contexto\n"
            "Son la única fuente de hechos concretos para esta nota (cifras, empresas, casos, citas).\n\n"
            + contexto_noticias.formatear(noticias, max_chars=3500 if ajustes.compacto else 7000)
        )
    else:
        partes.append(
            "## Noticias de contexto\n"
            "No hay noticias recientes para este tema. Escribí un análisis sin cifras, empresas ni "
            "casos concretos: explicá el tema con criterio de negocio."
        )
    if ejemplos:
        partes.append(
            "## Notas publicadas de referencia\n"
            "Imitá su tono, estructura y profundidad. No copies su contenido ni sus datos.\n\n"
            + _formatear_ejemplos(ejemplos, ajustes.chars_ejemplo)
        )
    if propios:
        partes.append(
            "## Notas propias que el equipo calificó alto\n"
            "Tomalas como referencia de lo que funciona. No copies su tema ni sus datos.\n\n"
            + _formatear_ejemplos([{"titulo": p["titulo"], "cuerpo": p["cuerpo"]} for p in propios],
                                  ajustes.chars_ejemplo)
        )
    if enlaces and not ajustes.compacto:
        partes.append(
            "## Notas del blog para enlazar\n"
            "Enlazá una o dos donde aporten, con un texto de enlace descriptivo.\n"
            + "\n".join(f"- [{e['titulo']}]({e['url']})" for e in enlaces)
        )
    if evitar:
        partes.append(
            "## Correcciones de notas anteriores\n"
            "El equipo marcó estos problemas en notas anteriores (rechazos, calificaciones y ediciones). "
            "No los repitas:\n" + "\n".join(f"- {m}" for m in evitar)
        )
    if aciertos:
        partes.append("## Lo que el equipo valoró en notas anteriores\n" + "\n".join(f"- {m}" for m in aciertos))
    if plan_nota:
        partes.append(plan.formatear(plan_nota))
    partes.append("## Pedido\n" + _pedido(categorias, tema))
    return "\n\n".join(partes)


def _pedido(categorias: list[str], tema: str | None) -> str:
    if tema:
        return f"Escribí la nota sobre este tema: {tema}."
    if categorias:
        return f"Escribí la nota sobre {', '.join(CATEGORIAS.get(s, s) for s in categorias).lower()}."
    return "Escribí la nota."


def _consulta(categorias: list[str], tema: str | None, regiones: list[str]) -> str:
    """Texto con el que se buscan las noticias de contexto."""
    base = tema or ", ".join(CATEGORIAS.get(s, s) for s in categorias)
    region = " ".join(REGIONES.get(s, s) for s in regiones)
    return f"{base} {region} autopartes aftermarket".strip()


# Lineamientos que, si fallan, justifican reescribir la nota una vez. Los demás
# (negritas, vocabulario…) se informan pero no gastan otra llamada al modelo.
CRITICOS = ("sin_alucinaciones", "sin_paywall", "no_repetitivo", "estructura_correcta")
MAX_INTENTOS = 2


def parecido_maximo() -> float:
    """Similitud (coseno) a partir de la cual una nota repite a una reciente."""
    try:
        return float(os.getenv("NOTA_PARECIDO_MAX", "0.93"))
    except ValueError:
        return 0.93


def fallas_criticas(evaluacion: dict | None) -> list[str]:
    """Lineamientos críticos que la evaluación marcó en falso. Sin evaluación: ninguno."""
    lineamientos = (evaluacion or {}).get("lineamientos") or {}
    return [k for k in CRITICOS if lineamientos.get(k) is False]


def puntaje(evaluacion: dict | None) -> int:
    """Cuántos lineamientos cumple la nota (0 a 9)."""
    return sum(1 for v in ((evaluacion or {}).get("lineamientos") or {}).values() if v is True)


_MOTIVOS_EVALUADOR = {
    "sin_alucinaciones": "inventaba datos, conceptos o casos que no están en las noticias",
    "sin_paywall": "incluía frases de suscripción o paywall",
    "no_repetitivo": "repetía información entre secciones",
    "estructura_correcta": "no tenía secciones (##) bien definidas",
}


def _pedido_de_correccion(problemas: list[str]) -> str:
    return (
        "\n\nIMPORTANTE: una versión anterior de esta nota fue rechazada por esto:\n"
        + "\n".join(f"- {p}" for p in problemas)
        + "\nEscribila de nuevo corrigiendo todo eso."
    )


def _redactar(system: str, user_msg: str, ajustes) -> tuple[str | None, str, str]:
    """(nota saneada, "", crudo) o (None, motivo, crudo). Lanza ErrorLLM si el proveedor falla."""
    crudo = llm.completar(system, user_msg, temperature=ajustes.temperatura, max_tokens=ajustes.max_tokens, stream=True,
                          tarea="redaccion")
    saneo = sanear(crudo)
    if not saneo.ok:
        return None, saneo.motivo, crudo
    return saneo.texto, "", crudo


def _calibracion(persona: str) -> calibracion.Calibracion:
    """Lo aprendido de calificaciones, rechazos y ediciones. Si Mongo falla, la nota se escribe igual."""
    return calibracion.contexto(persona)


def _coseno(a, b) -> float:
    return contexto_noticias._coseno(a, b)


def _recientes(limite: int = 15) -> list[dict]:
    """Las últimas notas: sus títulos van al plan y sus vectores detectan repeticiones."""
    try:
        docs = list(col_notas_fase2.find({}, {"contenido": 1, "embedding": 1, "embedding_modelo": 1})
                    .sort("generado_en", -1).limit(limite))
    except Exception as e:
        print(f"  [AVISO] No se pudieron leer las notas recientes: {e}", flush=True)
        return []
    return [{"titulo": calibracion._titulo(d.get("contenido", "")), "embedding": d.get("embedding"),
             "embedding_modelo": d.get("embedding_modelo")} for d in docs]


def _parecida(emb, modelo: str, recientes: list[dict]) -> dict | None:
    """La nota reciente más parecida, si supera parecido_maximo()."""
    if not emb:
        return None
    mejor = None
    for r in recientes:
        if r.get("embedding") and r.get("embedding_modelo") in (modelo, None):
            sim = _coseno(emb, r["embedding"])
            if sim >= parecido_maximo() and (mejor is None or sim > mejor["similitud"]):
                mejor = {"titulo": r["titulo"], "similitud": round(sim, 3)}
    return mejor


@dataclass
class _Version:
    """Una versión escrita de la nota y todo lo que se revisó de ella."""
    texto: str
    evaluacion: dict | None
    verificacion: verificacion.Verificacion
    revision: calidad.Revision
    enlaces_quitados: list[str]
    embedding: list | None
    parecida: dict | None
    problemas: list[str] = field(default_factory=list)   # graves: justifican reescribir
    codigos: list[str] = field(default_factory=list)

    @property
    def orden(self) -> tuple:
        """Menos problemas graves primero; a igualdad, más lineamientos cumplidos."""
        return (len(self.codigos), -puntaje(self.evaluacion))


def _revisar(texto: str, noticias: list, extra: str, voz, compacto: bool, palabra_clave: str,
             permitidas: tuple, recientes: list[dict], umbral: int | None) -> _Version:
    from afterdrive.ia.lm_studio import evaluar_lineamientos

    texto, quitados = verificacion.sanear_enlaces(texto, noticias, permitidas, DOMINIOS_PROPIOS)
    if quitados:
        print(f"  [AVISO] Se quitaron {len(quitados)} enlace(s) a URLs que no salen de las noticias.", flush=True)
    print("  Verificando los datos contra las noticias...", flush=True)
    v = verificacion.verificar(texto, noticias, extra=extra)
    revision = calidad.revisar(texto, voz, faq=not compacto, palabra_clave=palabra_clave)
    print("  Evaluando calidad...", flush=True)
    evaluacion = evaluar_lineamientos(texto)
    if evaluacion.get("error"):
        evaluacion = None
    modelo_emb = llm.modelo_embeddings()
    emb = llm.embeber([texto])[0]
    parecida = _parecida(emb, modelo_emb, recientes)

    version = _Version(texto, evaluacion, v, revision, quitados, emb, parecida)
    for f in fallas_criticas(evaluacion):
        version.codigos.append(f)
        version.problemas.append(_MOTIVOS_EVALUADOR.get(f, f))
    if v.grave:
        version.codigos.append("datos_sin_respaldo")
        version.problemas.append(verificacion.pedido_de_correccion(v))
    for h in revision.graves:
        version.codigos.append(h.codigo)
        version.problemas.append(h.detalle)
    if parecida:
        version.codigos.append("repetida")
        version.problemas.append(f"se parecía demasiado a una nota reciente (\"{parecida['titulo']}\"): "
                                 "elegí otro ángulo y otro hecho central")
    if umbral is not None and evaluacion is not None and puntaje(evaluacion) < umbral:
        version.codigos.append("puntaje_bajo")
        version.problemas.append(f"cumplía {puntaje(evaluacion)} de 9 lineamientos; el equipo pide al menos {umbral}")
    return version


# Dominios a los que una nota siempre puede enlazar (la casa).
DOMINIOS_PROPIOS = ("alephee.com",)


def generar_nota(
    categorias: list[str],
    clientes_ids: list[str] | None = None,
    puntapie_url: str | None = None,
    persona: str = "comercial",
    tema: str | None = None,
    regiones: list[str] | None = None,
    largo: str = redaccion.LARGO_DEFAULT,
) -> dict:
    """Genera, revisa y guarda una Nota. Lo que gasta la API paga queda en la nota (costo)."""
    with consumo.medir() as costo:
        resultado = _generar_nota(categorias, clientes_ids, puntapie_url, persona, tema, regiones, largo, costo)
    if costo.llamadas:
        detalle = ", ".join(f"{k} {v:.3f}" for k, v in sorted(costo.por_tarea.items(), key=lambda t: -t[1]))
        print(f"  [COSTO] Esta nota: USD {costo.total:.3f} ({detalle})", flush=True)
    return resultado


def _generar_nota(categorias, clientes_ids, puntapie_url, persona, tema, regiones, largo, costo) -> dict:
    clientes_ids = clientes_ids or []
    regiones = regiones or []
    ajustes = llm.ajustes_redaccion()
    voz = redaccion.voz(regiones)

    clientes_docs = []
    for cid in clientes_ids:
        doc = col_clientes.find_one({"slug": cid}) or col_clientes.find_one({"nombre": {"$regex": cid, "$options": "i"}})
        if doc:
            clientes_docs.append(doc)

    noticias = contexto_noticias.seleccionar(_consulta(categorias, tema, regiones), limite=NOTICIAS_POR_NOTA)
    print(f"  Noticias de contexto: {len(noticias)}", flush=True)
    for n in noticias:
        print(f"    - {n.titulo[:80]}", flush=True)
    if not noticias:
        print("  [WARN] No hay noticias scrapeadas: la nota se escribe sin datos concretos.", flush=True)

    ejemplos = get_ejemplos_por_tags(categorias, regiones=regiones or None, limit=EJEMPLOS_POR_CATEGORIA)
    enlaces = [{"titulo": e.get("titulo", ""), "url": e["url"]} for e in ejemplos if e.get("url") and e.get("titulo")][:4]
    ejemplos = ejemplos[: ajustes.max_ejemplos]
    print(f"  Few-shot: {len(ejemplos)} ejemplo(s) cargado(s) para {categorias}", flush=True)

    cal = _calibracion(persona)
    propios = cal.ejemplos_propios[: max(0, ajustes.max_ejemplos - 1)]
    if cal.reglas:
        print(f"  Correcciones del equipo: {len(cal.reglas)}", flush=True)
    if propios:
        print(f"  Notas propias bien calificadas como referencia: {len(propios)}", flush=True)
    if cal.umbral is not None:
        print(f"  Umbral del evaluador calibrado con las calificaciones: {cal.umbral}/9", flush=True)

    recientes = _recientes()
    print("  Planificando la nota...", flush=True)
    estructura = (redaccion.PERSONAS.get(persona) or redaccion.PERSONAS["analitico"])["estructura"]
    plan_nota = plan.planificar(
        noticias, _pedido(categorias, tema), estructura,
        publicadas=[r["titulo"] for r in recientes if r["titulo"]], reglas=cal.reglas,
        contexto=contexto_noticias.formatear(noticias, max_chars=5000), idioma=voz.idioma,
    )
    if plan_nota:
        print(f"  Plan: {plan_nota['titulo']}", flush=True)

    system = _build_system_prompt(categorias, clientes_docs, puntapie_url, persona, regiones, ajustes, largo)
    user_msg = _build_user_prompt(noticias, ejemplos, categorias, tema, ajustes, cal.reglas, plan_nota,
                                  cal.aciertos, propios, enlaces)

    extra = " ".join([_formatear_clientes(clientes_docs), tema or ""])
    permitidas = tuple(x for x in [puntapie_url, redaccion.alephee_url(), *(e["url"] for e in enlaces)] if x)
    palabra_clave = (plan_nota or {}).get("palabra_clave", "")

    # Hasta MAX_INTENTOS: si la nota no pasa el saneo o tiene un problema grave
    # (datos sin respaldo, lineamiento crítico, falta una sección fija, repite
    # una nota reciente, no llega al umbral calibrado), se reescribe diciéndole
    # al modelo qué estuvo mal. Queda la mejor.
    mejor: _Version | None = None
    anterior: _Version | None = None
    motivo, pedido, intentos = "", user_msg, 0
    reescrita_por: list[str] = []
    segundo_intento = ""   # "correccion" o "reescritura"
    for intento in range(1, MAX_INTENTOS + 1):
        intentos = intento
        if anterior is not None and not correccion.necesita_reescritura(anterior.codigos):
            # Retocar con el modelo de corrección (barato) en lugar de pagar otra redacción entera.
            segundo_intento = "correccion"
            print("  Corrigiendo la nota...", flush=True)
            articulo = correccion.corregir(anterior.texto, anterior.problemas, contexto_noticias.formatear(noticias),
                                           max_tokens=ajustes.max_tokens)
            if articulo is None:
                break
        else:
            if intento > 1:
                segundo_intento = "reescritura"
            print("  Generando nota..." if intento == 1 else f"  Reescribiendo la nota (intento {intento})...",
                  flush=True)
            try:
                articulo, motivo, crudo = _redactar(system, pedido, ajustes)
            except llm.ErrorLLM as e:
                if mejor:
                    break
                return {"success": False, "error": str(e)}
        if articulo is None:
            print(f"  [WARN] {motivo}. Se descarta esta versión.", flush=True)
            registrar_nota_descartada(
                "fase2", crudo, motivo, tema=tema, persona=persona, categorias=categorias, regiones=regiones,
            )
            continue

        version = _revisar(articulo, noticias, extra, voz, ajustes.compacto, palabra_clave, permitidas,
                           recientes, cal.umbral)
        if mejor is None or version.orden < mejor.orden:
            mejor = version
        anterior = version
        if not version.codigos:
            break
        print(f"  [WARN] La nota tiene problemas: {', '.join(version.codigos)}.", flush=True)
        reescrita_por = version.codigos
        pedido = user_msg + _pedido_de_correccion(version.problemas)

    if mejor is None:
        return {"success": False, "error": f"No se obtuvo una nota publicable: {motivo}"}

    # Fuentes: las noticias citadas en el texto, las que respaldaron algún dato
    # y las que el plan asignó a una sección. Sin ninguna señal, todas.
    citadas = verificacion.urls_citadas(mejor.texto)
    del_plan = {id(n) for n in plan.noticias_del_plan(plan_nota, noticias)}
    usadas = [n for i, n in enumerate(noticias)
              if (n.url and n.url.strip().rstrip("/").lower() in citadas) or i in mejor.verificacion.noticias_citadas
              or id(n) in del_plan]
    articulo = verificacion.agregar_fuentes(mejor.texto, usadas or noticias, voz.titulo_fuentes)
    evaluacion = mejor.evaluacion

    doc = {
        "contenido": articulo,
        "categorias": categorias,
        "regiones": regiones,
        "clientes_mencionados": [c.get("nombre") for c in clientes_docs],
        "puntapie_url": puntapie_url,
        "persona": persona,
        "tema": tema,
        "fuentes": [{"titulo": n.titulo, "url": n.url} for n in noticias],
        "ejemplos_usados": [e.get("url") for e in ejemplos],
        "evaluacion": evaluacion,
        "calidad": {
            "puntaje": puntaje(evaluacion) if evaluacion else None,
            "fallas_criticas": fallas_criticas(evaluacion),
            "intentos": intentos,
            "reescrita_por": reescrita_por if intentos > 1 else [],
            "problemas": mejor.codigos,
            "segundo_intento": segundo_intento or None,
        },
        "verificacion": mejor.verificacion.como_dict(),
        "estilo": mejor.revision.como_dict()["hallazgos"],
        "seo": mejor.revision.seo,
        "plan": plan_nota,
        "parecida_a": mejor.parecida,
        "enlaces_quitados": mejor.enlaces_quitados,
        "calibracion_usada": cal.como_dict(),
        "largo": largo,
        "proveedor": llm.proveedor_activo(),
        "correcciones_usadas": cal.reglas,
        "estado": ESTADO_BORRADOR,
        "generado_en": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    if mejor.embedding:
        doc["embedding"] = mejor.embedding
        doc["embedding_modelo"] = llm.modelo_embeddings()

    if imagenes.automaticas():
        # Siempre con NVIDIA (gratis), sin importar el proveedor de la redacción.
        print("  Generando la imagen destacada...", flush=True)
        try:
            doc["imagen"] = imagenes.para_nota(plan_nota, categorias, calidad.partes(articulo).titulo)
        except imagenes.ErrorImagen as e:
            print(f"  [AVISO] La nota se guarda sin imagen: {e}", flush=True)
    doc["costo"] = costo.como_dict()   # lo gastado hasta acá: todas las llamadas de esta nota
    col_notas_fase2.insert_one(dict(doc))  # copia: insert_one agrega un _id no serializable
    contexto_noticias.marcar_usadas(noticias)
    print("[OK] Nota guardada en 'notas_fase2'.", flush=True)

    meta = {k: v for k, v in doc.items() if k not in ("embedding", "embedding_modelo")}
    return {"success": True, "contenido": articulo, "meta": meta}


def get_ultima_nota() -> dict | None:
    return col_notas_fase2.find_one({}, sort=[("generado_en", -1)])


def _validar_entorno() -> None:
    """Falla temprano y con mensaje claro si falta configuración crítica."""
    provider = llm.proveedor_activo()
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        sys.exit("[ERROR] AI_PROVIDER=openrouter pero OPENROUTER_API_KEY no está configurado.")
    if provider == "nvidia" and not os.getenv("NVIDIA_API_KEY"):
        sys.exit("[ERROR] AI_PROVIDER=nvidia pero NVIDIA_API_KEY no está configurado.")
    if provider == "paga" and not llm.paga_configurada("PAGA_MODEL"):
        sys.exit("[ERROR] AI_PROVIDER=paga pero falta PAGA_API_KEY, PAGA_BASE_URL o PAGA_MODEL.")
    if not os.getenv("MONGO_URI"):
        sys.exit("[ERROR] MONGO_URI no está configurado.")


if __name__ == "__main__":
    import io
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Generador de notas Fase 2 — AfterDrive")
    parser.add_argument("--categorias", nargs="+", choices=list(CATEGORIAS.keys()), default=["autopartes"])
    parser.add_argument("--clientes", nargs="+", default=[])
    parser.add_argument("--puntapie", type=str, default=None)
    parser.add_argument("--persona", default="comercial",
                        choices=["analitico", "periodistico", "comercial", "divulgativo", "ejecutivo"])
    parser.add_argument("--tema", type=str, default=None)
    parser.add_argument("--largo", choices=list(redaccion.LARGOS), default=redaccion.LARGO_DEFAULT)
    parser.add_argument("--regiones", nargs="+", choices=REGION_SLUGS, default=[],
                        help="Regiones objetivo (argentina, brasil, mexico, latinoamerica, europa, china, asia)")
    args = parser.parse_args()
    _validar_entorno()

    resultado = generar_nota(
        categorias=args.categorias,
        clientes_ids=args.clientes,
        puntapie_url=args.puntapie,
        persona=args.persona,
        tema=args.tema,
        regiones=args.regiones,
        largo=args.largo,
    )

    if resultado["success"]:
        print("\n" + "=" * 60)
        print(resultado["contenido"][:1500])
        print("=" * 60)
    else:
        print(f"[ERROR] {resultado['error']}")
