"""
generar_articulo.py — Genera un artículo original a partir de los scrapeados, usando
embeddings para elegir un tópico coherente y fresco (no repetido).

Flujo (ver charla de diseño):
  1. Cargar todos los artículos que tienen embedding.
  2. Cargar los artículos ya generados (con su embedding) → memoria de lo escrito.
  3. Elegir SEMILLA por frescura: el artículo que MENOS se parece a lo ya generado
     (y entre iguales, el más reciente). Así evita arrancar de un tópico ya cubierto.
  4. Armar el tópico: semilla + sus K vecinos más cercanos (k-NN) por encima de un
     umbral de similitud → paquete temático coherente.
  5. Redactar con LM Studio usando solo ese paquete (contexto denso y enfocado).
  6. Dedup de salida: vectorizar el artículo generado; si se parece demasiado a uno
     previo, descartarlo y probar con la siguiente semilla.
  7. Guardar el artículo CON su embedding (para el dedup futuro) y marcar usados.
"""

import argparse
import datetime
import re

import llm
from db import ESTADO_BORRADOR, col_afterdrive, crear_indices_texto, db, registrar_nota_descartada
from embeddings import coseno
from lm_studio import NotaRechazada
from lm_studio import generar_articulo as lm_generar

_PAYWALL_PATTERNS = [
    r"El contenido al que quiere acceder es exclusivo para suscriptores",
    r"acceso exclusivo para suscriptores",
    r"iniciá sesión o suscribite",
    r"Este contenido es solo para",
    r"ya puedes acceder a este artículo",
    r"¿Ya tienes una cuenta?",
    r"Registrate para leer más",
    r"Suscribite para continuar",
]

col_generados = db["articulos_generados"]

FUENTES = {
    "general": col_generados,
    "afterdrive": col_afterdrive,
}

TOKENS_POR_CARACTER = 0.28
_OVERHEAD_FIJO = 600
_MARGEN_RESPUESTA = 6000
_CONTEXTO_MAXIMO = 32768

# Parámetros de selección por embeddings (calibrados con la data real).
UMBRAL_TOPICO = 0.70  # similitud mínima para considerar a un doc "vecino" de la semilla
MIN_VECINOS = 2  # una semilla necesita al menos esta cantidad de vecinos
K_VECINOS = 15  # cuántos vecinos como máximo entran al tópico
UMBRAL_DEDUP = 0.95  # si el artículo generado supera esto vs uno previo, se descarta
MAX_INTENTOS = 3  # cuántas semillas probar antes de rendirse
LIMITE_TEXT = 20  # docs por fuente en la búsqueda $text


def _estimar_tokens(texto: str) -> int:
    return max(1, int(len(texto) * TOKENS_POR_CARACTER))


def _limpiar_paywall(texto: str) -> str:
    for pat in _PAYWALL_PATTERNS:
        texto = re.sub(pat, "", texto, flags=re.IGNORECASE)
    return texto.strip()


def _formatear_doc(doc: dict, fuente: str, idx: int) -> tuple[str, int]:
    titulo = doc.get("titulo", "(sin título)")
    fecha = doc.get("fecha", "fecha desconocida")
    cuerpo = doc.get("cuerpo", doc.get("bajada", "(sin contenido)"))
    cuerpo = _limpiar_paywall(cuerpo)
    cuerpo = cuerpo[:3500] + "..." if len(cuerpo) > 3500 else cuerpo
    texto = f"[#{idx} - {fuente} - {fecha}] {titulo}\nContenido: {cuerpo}\n"
    return texto, _estimar_tokens(texto)


def _cargar_candidatos(fuentes: list[str]) -> list[dict]:
    """Todos los artículos con embedding de las fuentes elegidas."""
    candidatos = []
    for nombre in fuentes:
        if nombre not in FUENTES:
            continue
        for d in FUENTES[nombre].find({"embedding": {"$exists": True}}):
            d["_fuente"] = nombre
            candidatos.append(d)
    return candidatos


def _cargar_generados_emb() -> list[list[float]]:
    """
    Embeddings de los artículos ya generados (memoria de lo escrito).
    Calcula y persiste el embedding de los que aún no lo tengan.
    """
    vecs = []
    for g in col_generados.find():
        vec = g.get("embedding")
        if not vec:
            vec = llm.embeber([g.get("contenido", "")])[0]
            if vec:
                col_generados.update_one({"_id": g["_id"]}, {"$set": {"embedding": vec}})
        if vec:
            vecs.append(vec)
    return vecs


def _novedad(vec: list[float], generados: list[list[float]]) -> float:
    """1 - (máxima similitud con lo ya generado). 1.0 = tema totalmente nuevo."""
    if not generados:
        return 1.0
    return 1.0 - max(coseno(vec, g) for g in generados)


def _vecinos(semilla: dict, candidatos: list[dict]) -> list[tuple[dict, float]]:
    """Vecinos de la semilla por encima del umbral, ordenados por similitud desc."""
    sem_vec = semilla["embedding"]
    cercanos = []
    for d in candidatos:
        if d["_id"] == semilla["_id"]:
            continue
        s = coseno(sem_vec, d["embedding"])
        if s >= UMBRAL_TOPICO:
            cercanos.append((d, s))
    cercanos.sort(key=lambda x: x[1], reverse=True)
    return cercanos[:K_VECINOS]


def _buscar_por_tema(tema: str, limite: int = LIMITE_TEXT) -> list[tuple[dict, float]]:
    """$text search en todas las fuentes. Devuelve [(doc, textScore_normalizado)]."""
    docs = []
    for nombre, col in FUENTES.items():
        try:
            cursor = (
                col.find(
                    {"$text": {"$search": tema}},
                    {"text_score": {"$meta": "textScore"}},
                )
                .sort([("text_score", {"$meta": "textScore"})])
                .limit(limite)
            )
            for d in cursor:
                d["_fuente"] = nombre
                docs.append((d, d.get("text_score", 0.0)))
        except Exception:
            continue

    if not docs:
        return []

    max_score = max(s for _, s in docs)
    if max_score > 0:
        docs = [(d, s / max_score) for d, s in docs]
    docs.sort(key=lambda x: x[1], reverse=True)
    return docs


def guardar_articulo(contenido, ids_usados, fuentes, tema, embedding) -> None:
    col_generados.insert_one(
        {
            "contenido": contenido,
            "fuentes": fuentes,
            "tema": tema,
            "docs_usados": [str(i) for i in ids_usados],
            "embedding": embedding,
            "generado_en": datetime.datetime.now(datetime.UTC).isoformat(),
            "estado": ESTADO_BORRADOR,
        }
    )


def marcar_usados(coleccion, ids: list) -> None:
    if ids:
        coleccion.update_many({"_id": {"$in": ids}}, {"$set": {"usado_para_articulo": True}})


def main():
    parser = argparse.ArgumentParser(description="Generador de artículos con IA + embeddings (LM Studio)")
    parser.add_argument(
        "--fuente",
        nargs="+",
        choices=list(FUENTES.keys()),
        default=list(FUENTES.keys()),
        metavar="FUENTE",
        help="Fuentes a usar. Por defecto: todas.",
    )
    parser.add_argument("--budget-contexto", type=int, default=0, help="0 = auto (32768 - márgenes)")
    parser.add_argument(
        "--tema", type=str, default=None, help="Tema específico para el artículo. Si se omite, se elige por embeddings."
    )
    parser.add_argument(
        "--persona",
        type=str,
        default="analitico",
        choices=["analitico", "periodistico", "comercial", "divulgativo", "ejecutivo"],
        help="Personalidad de redacción. Por defecto: analitico.",
    )
    args = parser.parse_args()

    # Aprovecha el contexto de 32K (mejora de Manuel): más vecinos por tópico.
    budget = (
        args.budget_contexto if args.budget_contexto > 0 else _CONTEXTO_MAXIMO - _MARGEN_RESPUESTA
    ) - _OVERHEAD_FIJO

    # Asegurar índices $text para la búsqueda híbrida.
    crear_indices_texto()

    # ── 1-2. Cargar candidatos y memoria de lo ya generado ───────────────
    candidatos = _cargar_candidatos(args.fuente)
    print(f"Artículos con embedding disponibles: {len(candidatos)}")
    if not candidatos:
        print("No hay artículos vectorizados. Corré primero el backfill (embeddings.py).")
        return

    generados = _cargar_generados_emb()
    print(f"Artículos ya generados (memoria anti-repetición): {len(generados)}")

    # ── Cuando se pasa --tema, buscar semanticamente por embeddings ────
    modo_tema = bool(args.tema)
    if modo_tema:
        print(f"Modo tema específico: '{args.tema}'")
        query_expandido = f"{args.tema} autopartes aftermarket repuestos"
        emb_tema = llm.embeber([query_expandido], tipo="query")[0] if candidatos else None
        paquete = None
        if emb_tema:
            scored = [(d, d["_fuente"], coseno(emb_tema, d["embedding"])) for d in candidatos if d.get("embedding")]
            scored.sort(key=lambda x: x[2], reverse=True)
            scored = [x for x in scored if x[2] >= 0.50]
            if scored:
                paquete = scored[:25]
                print(f"  {len(paquete)} artículos por similitud semántica (mejor: {scored[0][2]:.3f})")
            else:
                print("  Sin coincidencias semánticas, intentando búsqueda por texto...")
        if paquete is None:
            texto_docs = _buscar_por_tema(args.tema, limite=30)
            if not texto_docs:
                print(f"No se encontraron artículos sobre '{args.tema}'.")
                return
            paquete = [(d, d["_fuente"], s) for d, s in texto_docs[:25]]
            print(f"  {len(paquete)} artículos encontrados por texto para '{args.tema}'")
        tema = args.tema
    else:
        # ── 3. Ordenar semillas por frescura (y recencia como desempate) ─────
        candidatos.sort(
            key=lambda d: (_novedad(d["embedding"], generados), d["_id"].generation_time.timestamp()),
            reverse=True,
        )
        # ── 4-7. Probar semillas hasta lograr un artículo no repetido ────────
        for intento, semilla in enumerate(candidatos[:MAX_INTENTOS], 1):
            tema = semilla.get("titulo", "(sin título)")
            print(f"\n── Intento {intento}: semilla → {tema[:70]}")
            vecinos = _vecinos(semilla, candidatos)
            if len(vecinos) < MIN_VECINOS:
                print(f"   semilla con pocos vecinos ({len(vecinos)}), probando otra...")
                continue
            # ── Hybrid: merge KNN + $text search ───────────────────────────
            texto_docs = _buscar_por_tema(tema)
            merged = {}
            for d, s in vecinos:
                merged[d["_id"]] = {"doc": d, "fuente": d["_fuente"], "knn": s, "text": 0.0}
            for d, s in texto_docs:
                if d["_id"] in merged:
                    merged[d["_id"]]["text"] = s
                else:
                    merged[d["_id"]] = {"doc": d, "fuente": d["_fuente"], "knn": 0.0, "text": s}
            hermanos = sorted(merged.values(), key=lambda x: max(x["knn"], x["text"]), reverse=True)
            print(f"   vecinos KNN: {len(vecinos)}, $text: {len(texto_docs)}, pool único: {len(hermanos)}")
            paquete = [(semilla, semilla["_fuente"], 1.0)]
            for item in hermanos:
                if item["doc"]["_id"] == semilla["_id"]:
                    continue
                paquete.append((item["doc"], item["fuente"], max(item["knn"], item["text"])))
            break
        else:
            print(f"\nNo se logró un artículo nuevo tras {MAX_INTENTOS} intentos (todo muy parecido a lo ya escrito).")
            return

    # ── Armar contexto y generar ─────────────────────────────────────────
    contexto = ""
    seleccionados = []
    tokens = _OVERHEAD_FIJO
    for idx, (doc, fuente, sim) in enumerate(paquete, 1):
        texto_doc, t = _formatear_doc(doc, fuente, idx)
        if tokens + t > budget:
            continue
        tokens += t
        contexto += f"\n── Fuente: {fuente} (afinidad: {sim:.2f}) ──\n" + texto_doc
        seleccionados.append((doc, fuente))

    print(f"   tópico armado: {len(seleccionados)} artículos (~{tokens} tokens)")

    # ── Contexto suplementario: artículos recientes como recurso opcional ──
    if tokens < budget * 0.7:
        docs_usados_ids = {d["_id"] for d, _ in seleccionados}
        recientes = []
        for d in col_afterdrive.find().sort("_id", -1).limit(10):
            if d["_id"] in docs_usados_ids:
                continue
            cuerpo = _limpiar_paywall(d.get("cuerpo", "")[:1200])
            if not cuerpo.strip():
                continue
            t_extra = _estimar_tokens(cuerpo) + 50
            if tokens + t_extra > budget:
                break
            tokens += t_extra
            recientes.append(f"- {d.get('titulo', '(sin titulo)')}: {cuerpo}")
        if recientes:
            contexto += "\n\n<RECURSOS ADICIONALES>\n" + "\n".join(recientes[:5]) + "\n</RECURSOS ADICIONALES>"
            print(f"   + {len(recientes[:5])} artículos recientes como recurso adicional (~{tokens} tokens total)")

    print("   generando artículo...")
    print("=" * 60)
    fuentes_contexto = sorted({f for _, f in seleccionados})
    try:
        articulo = lm_generar(contexto, persona=args.persona, tema=args.tema)
    except NotaRechazada as e:
        # Hubo texto pero no una Nota publicable: queda en el historial.
        print(f"\nError al generar: {e}")
        registrar_nota_descartada(
            "fase1", e.crudo, e.motivo, tema=tema, persona=args.persona, fuentes=fuentes_contexto
        )
        return
    except Exception as e:
        print(f"\nError al generar: {e}")
        return
    print("=" * 60)

    if not articulo:
        print("   articulo vacio.")
        return

    # ── 6. Quality gate: rechazar articulos con problemas criticos ──────
    problemas = []

    # Muy corto para ser util
    if len(articulo) < 300:
        problemas.append("muy corto")

    # Sin secciones ## (estructura basica)
    if not re.search(r"^##\s", articulo, re.MULTILINE):
        problemas.append("sin secciones ##")

    # Conteo de repeticiones de oraciones largas (>60 chars)
    oraciones = [o.strip() for o in re.split(r'[.!?]', articulo) if len(o.strip()) > 60]
    if oraciones:
        vistas = set()
        repetidas = 0
        for o in oraciones:
            norm = re.sub(r'\s+', ' ', o.lower().strip())
            if norm in vistas:
                repetidas += 1
            vistas.add(norm)
        if repetidas >= 2:
            problemas.append(f"{repetidas} oraciones repetidas")

    # Meta description duplicada al final
    lineas = articulo.strip().split("\n")
    ultimas_3 = [l.strip() for l in lineas[-3:] if l.strip()]
    if len(ultimas_3) >= 2 and ultimas_3[-1] == ultimas_3[-2]:
        problemas.append("conclusion duplicada")

    # Detectar secciones con contenido identico (clonacion de viñetas)
    bloques_seccion = []
    for l in lineas:
        if l.strip().startswith("## "):
            bloques_seccion.append([])
        if bloques_seccion:
            bloques_seccion[-1].append(l.strip())
    if len(bloques_seccion) >= 2:
        textos_bloques = []
        for b in bloques_seccion:
            texto_b = " ".join(b).lower()
            textos_bloques.append(texto_b)
        for i in range(len(textos_bloques)):
            for j in range(i + 1, len(textos_bloques)):
                palabras_i = set(textos_bloques[i].split())
                palabras_j = set(textos_bloques[j].split())
                if len(palabras_i) > 15 and len(palabras_j) > 15:
                    interseccion = len(palabras_i & palabras_j)
                    union = len(palabras_i | palabras_j)
                    if union > 0 and interseccion / union > 0.5:
                        problemas.append("secciones clonadas")
                        break
            if "secciones clonadas" in problemas:
                break

    # Detectar CTA repetido (mismo patrón de llamada a la acción)
    patron_cta = re.compile(r'(descubre|conoce|transforma|descarga|accede|visita)\b.*\b(tu negocio|el mercado|el sector|las oportunidades)', re.IGNORECASE)
    ctas = [l for l in lineas if patron_cta.search(l)]
    if len(ctas) >= 2:
        problemas.append("CTA repetido")

    # Titulo con errores de concordancia detectables
    titulo_linea = ""
    for l in lineas:
        if l.strip().startswith("# ") and not l.strip().startswith("## "):
            titulo_linea = l.strip()
            break
    if titulo_linea:
        if re.search(r'cambiando la juego|revolucionando la', titulo_linea, re.IGNORECASE):
            problemas.append("titulo con error gramatical")

    if problemas:
        motivo = f"Calidad insuficiente: {', '.join(problemas)}"
        print(f"   [RECHAZADO] {motivo}")
        registrar_nota_descartada(
            "fase1", articulo, motivo, tema=tema, persona=args.persona, fuentes=fuentes_contexto
        )
        return

    # ── 7. Dedup de salida ───────────────────────────────────────────────
    emb_art = llm.embeber([articulo])[0]
    if emb_art and generados:
        parecido = max(coseno(emb_art, g) for g in generados)
        if parecido >= UMBRAL_DEDUP:
            motivo = f"Demasiado parecido a un artículo ya generado (similitud {parecido:.2f})"
            print(f"   [RECHAZADO] {motivo}.")
            registrar_nota_descartada(
                "fase1", articulo, motivo, tema=tema, persona=args.persona, fuentes=fuentes_contexto
            )
            return

    # ── 8. Guardar ───────────────────────────────────────────────────────
    ids = [d["_id"] for d, _ in seleccionados]
    fuentes_usadas = list({f for _, f in seleccionados})
    guardar_articulo(articulo, ids, fuentes_usadas, tema, emb_art)
    for nombre in fuentes_usadas:
        marcar_usados(FUENTES[nombre], [d["_id"] for d, f in seleccionados if f == nombre])

    print(f"\n[OK] Artículo guardado (tema: {tema[:50]}) usando {len(seleccionados)} fuentes.")


if __name__ == "__main__":
    main()
