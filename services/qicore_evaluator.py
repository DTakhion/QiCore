# services/qicore_evaluator.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional, List

from services.qicore_engine_piecewise import QiCoreEnginePiecewise
from scripts.qicore_gate_hamiltonian_post import extract_features, features_to_gp_like  # OK por ahora (ideal mover a services/)


def _make_engine() -> QiCoreEnginePiecewise:
    return QiCoreEnginePiecewise(
        eta=float(os.getenv("QICORE_ETA", "0.5")),
        lambda_2=float(os.getenv("QICORE_LAMBDA2", "2.0")),
        threshold=float(os.getenv("QICORE_H_THRESHOLD", os.getenv("QICORE_THRESH", "1.0"))),
        sigma_known=float(os.getenv("QICORE_SIGMA_KNOWN", "0.08")),
        sigma_border=float(os.getenv("QICORE_SIGMA_BORDER", "0.30")),
        beta_neg_border=float(os.getenv("QICORE_BETA_NEG_BORDER", "0.20")),
        mission_weight_ood=float(os.getenv("QICORE_MISSION_WEIGHT_OOD", "0.0")),
    )


def _default_safe_message() -> str:
    # Mensaje fijo (no “genera” nada nuevo). Editable por env si quieres.
    return os.getenv(
        "QICORE_SAFE_MESSAGE",
        "No tengo evidencia suficiente para responder con confianza. "
        "¿Puedes entregar más contexto o una fuente verificable?"
    )


def evaluate_llm_answer(
    *,
    answer: str,
    prompt: Optional[str] = None,
    engine_name: str = "custom",
    provider_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evalúa una respuesta LLM (texto) y retorna JSON de decisión.
    NO genera texto nuevo. Solo audita/riesgo/alucinación.
    """
    engine = _make_engine()

    feats = extract_features(answer)
    mu, sigma, v_risk, gp_meta = features_to_gp_like(feats)

    H, terms = engine.hamiltonian_energy_from_gp(
        mu=mu, sigma=sigma, v_risk=v_risk, return_terms=True
    )

    blocked = bool(terms.get("blocked", False))

    # --- extras recomendados para middleware ---
    H_threshold = float(os.getenv("QICORE_H_THRESHOLD", os.getenv("QICORE_THRESH", "1.0")))
    risk_score = 1.0 if H_threshold <= 0 else min(1.0, float(H) / H_threshold)

    flags = {
        "source_without_trace": bool(gp_meta.get("source_without_trace", False)),
        "suspicious_org_mix": bool(gp_meta.get("suspicious_org_mix", False)),
        "report_like_claim": bool(gp_meta.get("report_like_claim", False)),
        "contradiction": bool(feats.get("contradiction", False)),
    }

    reason_codes: List[str] = []
    if flags["source_without_trace"]:
        reason_codes.append("SOURCE_NO_TRACE")
    if flags["suspicious_org_mix"]:
        reason_codes.append("SUSPICIOUS_ORG_MIX")
    if flags["report_like_claim"]:
        reason_codes.append("REPORT_LIKE_CLAIM")
    if flags["contradiction"]:
        reason_codes.append("CONTRADICTION")

    safe_message = _default_safe_message() if blocked else None

    # JSON base estable (con extras)
    result: Dict[str, Any] = {
        "ok": True,
        "qicore": {
            "mode": "post_generation_gate",
            "engine": {
                "type": "QiCoreEnginePiecewise",
                "eta": float(os.getenv("QICORE_ETA", "0.5")),
                "lambda_2": float(os.getenv("QICORE_LAMBDA2", "2.0")),
                "H_threshold": H_threshold,
                "sigma_known": float(os.getenv("QICORE_SIGMA_KNOWN", "0.08")),
                "sigma_border": float(os.getenv("QICORE_SIGMA_BORDER", "0.30")),
                "beta_neg_border": float(os.getenv("QICORE_BETA_NEG_BORDER", "0.20")),
                "mission_weight_ood": float(os.getenv("QICORE_MISSION_WEIGHT_OOD", "0.0")),
            },
            "decision": {
                "blocked": blocked,
                "hallucination": blocked,  # explícito para integradores
                "recommended_action": "block" if blocked else "allow",
                "H": float(H),
                "H_threshold": H_threshold,  # duplicado útil a veces (clients simples)
                "risk_score": float(risk_score),  # 0..1
                "regime": terms.get("regime", ""),
                "reason_codes": reason_codes,  # lista corta
                "safe_message": safe_message,  # solo si blocked
            },
            "signals": {
                "mu": float(terms.get("mu", mu)),
                "sigma": float(terms.get("sigma", sigma)),
                "v_risk": float(gp_meta.get("v_risk", v_risk)),
                "flags": flags,
            },
            "audit": {
                "features": feats,
                "terms": terms,
            },
            "input": {
                "engine": engine_name,
                "prompt": prompt,
                "provider_meta": provider_meta or {},
            },
        },
    }
    return result