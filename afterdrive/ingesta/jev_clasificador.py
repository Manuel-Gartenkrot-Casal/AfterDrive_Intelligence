"""
jev_clasificador.py — Adapter del clasificador Jev (TypeSafe System One).

clasificar() devuelve None cuando Jev no está configurado o falla: qué hacer
entonces (caer al clasificador LLM) lo decide ingesta.clasificar.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")
JEV_ENDPOINT = os.getenv("JEV_ENDPOINT", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL = os.getenv("JEV_MODEL", "jev-latest")
JEV_THRESHOLD = float(os.getenv("JEV_THRESHOLD", "0.5"))

def clasificar(titulo: str, cuerpo: str) -> dict | None:
    """{"aprobado": bool, "razon": str}, o None si Jev no está disponible."""
    if not TYPESAFE_API_KEY:
        return None

    cuerpo_truncado = (cuerpo or "")[:2000]

    payload = {
        "model": JEV_MODEL,
        "state": f"Título: {titulo}\n\nCuerpo: {cuerpo_truncado}",
        "questions": {
            "relevante": {
                "type": "noul",
                # Mismo criterio que lm_studio._SYSTEM_EVALUAR: antes solo aceptaba repuestos y catálogos
                # y rechazaba casi toda noticia del sector.
                "instructions": "¿Esta noticia le sirve al negocio de distribuidoras de repuestos, fabricantes de autopartes, talleres o lubricentros de Latinoamérica? Probabilidad alta (cerca de 1) si trata de autopartes, repuestos, mercado de reposición/posventa, talleres, neumáticos, lubricantes, industria automotriz o autopartista, parque automotor, logística o e-commerce del sector. Cerca de 0 solo si es de otro tema (política, policiales, deportes, espectáculos), una review de un auto nuevo para consumidores, seguros o trámites del conductor, o contenido vacío."
            },
            "motivo": {
                "type": "choice",
                "instructions": "Clasifica el motivo de rechazo si es irrelevante.",
                "criteria": {
                    "relevante": "Trata de autopartes/aftermarket",
                    "vehiculos_0km": "Venta de vehículos nuevos, concesionarias",
                    "seguros": "Seguros automotrices",
                    "b2c_generico": "Contenido para consumidor básico",
                    "alucinacion": "Concepto técnico inventado",
                    "irrelevante": "No relacionado al sector"
                }
            }
        }
    }

    try:
        resp = requests.post(
            JEV_ENDPOINT,
            headers={"Authorization": f"Bearer {TYPESAFE_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        relevante_score = data["answers"]["relevante"]["noul"]
        motivo = data["answers"]["motivo"]["choice"]

        aprobado = relevante_score >= JEV_THRESHOLD
        razon = "Relevante" if aprobado else f"Motivo: {motivo} (conf: {relevante_score:.2f})"

        return {"aprobado": aprobado, "razon": razon}

    except Exception as e:
        print(f"[Jev Error] Fallo al llamar Jev: {e}", flush=True)
        return None
