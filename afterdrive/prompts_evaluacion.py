"""Prueba aislada de prompts: mismas fuentes, modelo y criterios; nunca publica notas.

No predice la calidad de todas las notas futuras. Rechaza regresiones observadas,
respuestas incompletas y propuestas sin suficientes casos reales para comparar.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from afterdrive.ia import llm, redaccion

MIN_CASOS = 3
MAX_CASOS = 5
PUNTAJE_MIN = 8
GANANCIA_MIN = 0.5


def huella(piezas: dict) -> str:
    return hashlib.sha256(json.dumps(piezas, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def modelo() -> str:
    """Identificador sin credenciales: invalida pruebas cuando cambia el proveedor/modelo."""
    p = llm._perfil_chat()
    return huella({"proveedor": p.nombre, "modelo": p.modelo, "tareas": p.modelos_tarea,
                   "ajustes": asdict(llm.ajustes_redaccion())})


def _entrada(nota: dict, base, ajustes) -> dict | None:
    guardada = nota.get("prompts_prueba")
    if isinstance(guardada, dict) and guardada.get("user") and guardada.get("contexto"):
        return guardada
    # Migración sin llamadas de red: recuperar las fuentes originales, nunca
    # usar una nota generada como evidencia de sus propios hechos.
    from afterdrive.generacion import contexto_noticias as cn
    from afterdrive.generacion import generar_nota_fase2 as gen
    urls = [f.get("url") for f in nota.get("fuentes", []) if f.get("url")]
    fuentes = [cn._desde_doc(d) for d in base.articulos.find({"url": {"$in": urls}})
               if len(d.get("cuerpo") or d.get("bajada") or "") >= 200]
    if not fuentes:
        return None
    categorias = nota.get("categorias") or []
    return {
        "user": gen._build_user_prompt(fuentes, [], categorias, nota.get("tema"), ajustes,
                                       evitar=nota.get("correcciones_usadas"), plan_nota=nota.get("plan"),
                                       indicaciones=nota.get("indicaciones")),
        "contexto": gen._contexto(fuentes, [], max_chars=12000),
        "opciones": {"categorias": categorias, "clientes": [], "puntapie_url": nota.get("puntapie_url"),
                     "persona": nota.get("persona") or "comercial", "regiones": nota.get("regiones") or [],
                     "largo": nota.get("largo"), "idioma": nota.get("idioma") or "pt"},
        "reglas": nota.get("correcciones_usadas") or [],
        "reconstruida": True,
    }


def casos(base, claves: list[str], ajustes) -> list[dict]:
    requeridas = {c.removeprefix("persona_") for c in claves if c.startswith("persona_")}
    solo_personas = all(c.startswith("persona_") for c in claves)
    candidatos, vistos = [], set()
    for n in base.notas_fase2.find().sort("_id", -1).limit(80):
        if solo_personas and n.get("persona") not in requeridas:
            continue
        entrada = _entrada(n, base, ajustes)
        if not entrada:
            continue
        firma = huella({"contexto": entrada["contexto"], "persona": entrada["opciones"]["persona"]})
        if firma in vistos:
            continue
        vistos.add(firma)
        candidatos.append({"nota_id": str(n["_id"]), "titulo": (n.get("contenido") or "").split("\n", 1)[0].lstrip("# ")[:150],
                           "entrada": entrada})
    # Primero cubrir cada persona modificada; después diversificar el resto.
    elegidos = []
    for persona in sorted(requeridas):
        encontrado = next((c for c in candidatos if c["entrada"]["opciones"]["persona"] == persona), None)
        if encontrado is None:
            return []
        elegidos.append(encontrado)
    for c in candidatos:
        if c not in elegidos:
            elegidos.append(c)
        if len(elegidos) >= max(MIN_CASOS, len(requeridas)):
            break
    return elegidos[:MAX_CASOS]


def _medir(texto: str, entrada: dict, referencia: dict, ajustes) -> dict:
    from afterdrive.generacion import calidad, critica, juez
    opciones = entrada["opciones"]
    crit = critica.criticar(texto, opciones["persona"], opciones.get("regiones"), opciones.get("idioma"),
                           piezas=referencia)
    juicio = juez.juzgar(texto, entrada["contexto"], entrada.get("reglas", []), piezas=referencia, estricto=True)
    llm.verificar_cancelacion()
    if crit.get("error") or juicio.get("error") or not _puntaje(crit.get("puntaje"), 10):
        raise ValueError(crit.get("error") or juicio.get("error") or "Crítica sin puntaje válido.")
    if not {"gramatica", "redaccion", "tono", "estructura"}.issubset(crit.get("aspectos", {})):
        raise ValueError("La crítica no evaluó todos los aspectos de la redacción.")
    if not _puntaje(juicio.get("calificacion"), 5):
        raise ValueError("El juez no devolvió una calificación válida.")
    revision = calidad.revisar(texto, redaccion.voz_de_idioma(opciones.get("idioma") or "pt"),
                              faq=not ajustes.compacto)
    return {"puntaje": crit["puntaje"], "aspectos": crit.get("aspectos", {}),
            "errores": crit.get("errores", []), "juez": juicio["calificacion"],
            "pasa": juicio.get("pasa") is True and juicio.get("confianza", 0) >= juez.CONFIANZA_MIN,
            "graves": [h.codigo for h in revision.hallazgos if h.grave],
            "alephee": juez.fallas_alephee(juicio), "motivos": juicio.get("motivos", [])}


def _puntaje(valor, maximo):
    return not isinstance(valor, bool) and isinstance(valor, (int, float)) and 1 <= valor <= maximo


def comparar(antes: dict, despues: dict, referencia: dict, base, *, automatico: bool) -> dict:
    """Solo una prueba completa puede habilitar una copia. No aprende de sus propias pruebas."""
    from afterdrive.generacion import generar_nota_fase2 as gen
    claves = [k for k in despues if despues[k] != antes[k]]
    if claves == ["imagenes"]:
        return {"estado": "aprobada", "tipo": "imagenes", "casos": [],
                "motivo": "Solo cambia la selección de imágenes. Los prompts de redacción quedan idénticos."}
    resultado = {"estado": "no_evaluable", "tipo": "redaccion", "casos": [],
                 "minimo": PUNTAJE_MIN, "ganancia_minima": GANANCIA_MIN if automatico else 0,
                 "modelo": modelo()}
    ajustes = llm.ajustes_redaccion()
    try:
        muestra = casos(base, claves, ajustes)
        if len(muestra) < MIN_CASOS:
            resultado["motivo"] = (f"Se necesitan al menos {MIN_CASOS} notas con fuentes recuperables y cobertura "
                                   "de las personas modificadas. Generá más notas con los prompts actuales.")
            return resultado
        for i, caso in enumerate(muestra):
            llm.verificar_cancelacion()
            entrada = caso["entrada"]
            sistemas = {nombre: gen._build_system_prompt(**entrada["opciones"], ajustes=ajustes, piezas=piezas)
                        for nombre, piezas in (("antes", antes), ("despues", despues))}
            if sistemas["antes"] == sistemas["despues"]:
                # Una pieza de otra persona no afecta a este caso: no cuenta como prueba.
                continue
            print(f"[PROMPTS IA] Comparando caso {i + 1}/{len(muestra)} con las mismas fuentes...", flush=True)
            fila = {"nota_id": caso["nota_id"], "titulo": caso["titulo"], "persona": entrada["opciones"]["persona"],
                    "reconstruida": entrada.get("reconstruida", False)}
            # Alternar el orden evita favorecer siempre al primer/último texto.
            for nombre in (("antes", "despues") if i % 2 == 0 else ("despues", "antes")):
                texto, motivo, _ = gen._redactar(sistemas[nombre], entrada["user"], ajustes)
                if not texto:
                    raise ValueError(f"No se obtuvo una nota evaluable ({nombre}): {motivo}")
                fila[nombre] = _medir(texto, entrada, referencia, ajustes)
            resultado["casos"].append(fila)
        if len(resultado["casos"]) < MIN_CASOS:
            resultado["motivo"] = "El cambio no afecta suficientes casos de prueba. No se activó."
            return resultado
        antes_media = sum(c["antes"]["puntaje"] for c in resultado["casos"]) / len(resultado["casos"])
        despues_media = sum(c["despues"]["puntaje"] for c in resultado["casos"]) / len(resultado["casos"])
        problemas = []
        for c in resultado["casos"]:
            a, d = c["antes"], c["despues"]
            if d["puntaje"] < max(PUNTAJE_MIN, a["puntaje"]) or d["juez"] < a["juez"]:
                problemas.append("La propuesta baja una calificación o no alcanza 8/10.")
            if any(d["aspectos"].get(k, -1) < v for k, v in a["aspectos"].items()):
                problemas.append("Empeora un aspecto de la redacción.")
            if not d["pasa"] or d["alephee"] or d["graves"]:
                problemas.append("La propuesta no supera los controles de datos, estilo o Alephee.")
        if despues_media - antes_media < resultado["ganancia_minima"]:
            problemas.append("La mejora automática no demuestra una ganancia de al menos 0,5 puntos.")
        if modelo() != resultado["modelo"]:
            raise ValueError("Cambió el modelo durante la comparación; repetí la prueba.")
        resultado.update(estado="rechazada" if problemas else "aprobada", antes=round(antes_media, 2),
                         despues=round(despues_media, 2),
                         motivo=" ".join(dict.fromkeys(problemas)) or "La comparación no detectó regresiones.")
    except llm.Cancelada:
        raise
    except Exception as e:
        resultado.update(estado="no_evaluable", motivo=f"No se completó la comparación: {e}")
    return resultado
