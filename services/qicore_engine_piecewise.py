# services/qicore_engine_piecewise.py

from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Dict, Any, Tuple


@dataclass
class QiCoreEnginePiecewise:
    """
    QiCore v2 (piecewise)
    ------------------------------------
    Objetivo:
      - Mantener la normalización de utilidad con tanh(mu) ∈ [-1, 1]
      - Evitar falsos positivos por signo en "zona conocida" (sigma muy baja)
      - Hacer explícita la dependencia por régimen (sigma: known / border / ood)

    Convención energética:
        H = term_mission + λ1 * V_risk + λ2 * sigma

    Donde:
      - term_mission depende del régimen y de U = tanh(mu)
      - λ1 = 1/(eta + eps) como en el engine base qicore_engine.py
      - V_risk es un término fijo (por ahora). Junto con lambda_1, término de riesgo. 
      - λ2 * sigma penaliza incertidumbre (epistemológica)
    Política clave:
      - En régimen known (sigma baja): NO penalizamos utilidad negativa.
        (esto neutraliza el caso auditado donde U≈-1 => -U≈+1 => bloqueos en conocido)
      - En border: penalización negativa amortiguada (beta_neg)
      - En ood: la utilidad casi no importa (mission_weight muy baja o 0)
    """

    eta: float = 0.5
    lambda_2: float = 2.0
    threshold: float = 1.0

    # Umbrales de régimen por incertidumbre (σ del GP)
    sigma_known: float = 0.08     # <= esto: "conocido"
    sigma_border: float = 0.30    # (known, border] transición; > esto: OOD

    # Cómo tratar utilidad negativa por régimen
    beta_neg_border: float = 0.20   # peso de penalización para U<0 en borde (0 = ignorar, 1 = penalizar completo)

    # Peso del término misión en OOD (en general queremos que mande sigma)
    mission_weight_ood: float = 0.0  # 0 = ignorar misión; 0.1 = débil; etc.

    # eps para evitar división por cero
    eps: float = 1e-6

    def _lambda_1(self) -> float:
        return 1.0 / (self.eta + self.eps)

    def _regime(self, sigma: float) -> str:
        if sigma <= self.sigma_known:
            return "known"
        if sigma <= self.sigma_border:
            return "border"
        return "ood"

    @staticmethod
    def _tanh(x: float) -> float:
        # tanh estable; math.tanh ya es robusta
        return math.tanh(x)

    def hamiltonian_energy_from_gp(
        self,
        mu: float,
        sigma: float,
        v_risk: float = 0.05,
        return_terms: bool = True
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Usa directamente (mu, sigma) del GP.
        - mu -> señal de utilidad
        - sigma -> incertidumbre

        Retorna:
          H_total, terms
        """
        lam1 = self._lambda_1()
        reg = self._regime(sigma)

        # Utilidad normalizada
        U = self._tanh(mu)  # [-1, 1]
        U_pos = max(U, 0.0)
        U_neg = min(U, 0.0)  # negativo o 0

        # -------------------------
        # Término de misión (piecewise)
        # -------------------------
        if reg == "known":
            # Política anti-falsos-positivos por signo:
            # - Solo "premiamos" utilidad positiva (baja energía).
            # - Utilidad negativa NO debe subir energía en conocido.
            term_mission = -U_pos

        elif reg == "border":
            # Transición: permitimos que lo negativo penalice, pero amortiguado.
            # Ejemplo: U=-1 => aporte +beta_neg_border (en vez de +1 completo)
            term_mission = -(U_pos + self.beta_neg_border * U_neg)

        else:  # "ood"
            # En OOD manda la incertidumbre. La misión se ignora o pesa poco.
            term_mission = -self.mission_weight_ood * U_pos  # opcional: solo premia positivo muy débil

        # -------------------------
        # Riesgo e incertidumbre
        # -------------------------
        term_risk = lam1 * v_risk
        term_uncertainty = self.lambda_2 * float(sigma)

        H_total = float(term_mission + term_risk + term_uncertainty)

        terms = {
            "regime": reg,
            "mu": float(mu),
            "sigma": float(sigma),
            "U_tanh": float(U),
            "lambda_1": float(lam1),
            "term_mission": float(term_mission),
            "term_risk": float(term_risk),
            "term_uncertainty": float(term_uncertainty),
            "threshold": float(self.threshold),
            "blocked": bool(H_total > self.threshold),
        }

        if return_terms:
            return H_total, terms
        return H_total, {}

    def is_blocked(self, mu: float, sigma: float, v_risk: float = 0.05) -> bool:
        H, _ = self.hamiltonian_energy_from_gp(mu=mu, sigma=sigma, v_risk=v_risk, return_terms=False)
        return H > self.threshold
