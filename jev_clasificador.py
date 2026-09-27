import os
import requests
import json
from lm_studio import clasificar_articulo as llm_clasificar

# ── Config ──────────────────────────────────────────────────────────────────
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")
JEV_ENDPOINT = os.getenv("JEV_ENDPOINT", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL = os.getenv("JEV_MODEL", "jev-latest")
JEV_THRESHOLD = float(os.getenv("JEV_THRESHOLD", "0.5"))

def clasificar_articulo(titulo: str, cuerpo: str) -> dict:
    """
    Clasificador de relevancia usando Jev (TypeSafe System One).
    Si no hay key o falla, hace fallback al LLM clásico.
    """
    if not TYPESAFE_API_KEY:
        return llm_clasificar(titulo, cuerpo)

    cuerpo_truncado = (cuerpo or "")[:2000]
    
    payload = {
        "model": JEV_MODEL,
        "state": f"Título: {titulo}\n\nCuerpo: {cuerpo_truncado}",
        "questions": {
            "relevante": {
                "type": "noul",
                "instructions": "¿Este artículo trata sobre la industria de autopartes y aftermarket (repuestos, catálogos, fitment, e-commerce B2B de repuestos)? Responde con probabilidad alta (cerca de 1) si trata de repuestos y 0 si trata de ventas de vehículos 0km, seguros, contenido B2C genérico o alucinaciones."
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
        print(f"[Jev Error] Fallo al llamar Jev, fallback al LLM: {e}", flush=True)
        return llm_clasificar(titulo, cuerpo)
