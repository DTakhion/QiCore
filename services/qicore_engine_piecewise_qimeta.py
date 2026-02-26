# services/qicore_engine_piecewise_qimeta.py

from __future__ import annotations
from dataclasses import dataclass, field
import math
from typing import Dict, Any, Tuple, List


@dataclass
class QiCoreEnginePiecewiseQiMeta:
    """
    QiCore v2 (piecewise / regime-aware) + QiMeta (eta adaptativo)
    --------------------------------------------------------------
    Basado 1:1 en tu QiCoreEnginePiecewise, pero integrando:
      - eta dinámico (QiMeta): update_qimeta(last_error)
      - lambda_1 = 1/(eta + eps) se vuelve adaptativo
      - el resto (piecewise, tanh(mu), regímenes por sigma) se mantiene

    Convención energética (se mantiene):
        H = term_mission + λ1(eta) * V_risk + λ2 * σ

    Política clave (idéntica a tu piecewise):
      - En régimen known (σ baja): NO penalizamos utilidad negativa.
      - En border: penalización negativa amortiguada (beta_neg_border).
      - En ood: la misión casi no importa (mission_weight_ood).
    """

    # --- QiMeta base ---
    eta_base: float = 0.6     # valor "home"
    lambda_2: float = 2.5
    threshold: float = 1.0

    # --- Umbrales de régimen por incertidumbre (σ del GP) ---
    sigma_known: float = 0.08
    sigma_border: float = 0.30

    # --- Cómo tratar utilidad negativa por régimen ---
    beta_neg_border: float = 0.20

    # --- Peso misión en OOD ---
    mission_weight_ood: float = 0.0

    # --- eps para evitar división por cero ---
    eps: float = 1e-6

    # --- Parámetros QiMeta (idénticos a tu v2.1) ---
    delta_penal: float = 0.4
    delta_recup: float = 0.05
    shock_threshold: float = 0.5
    eta_min: float = 0.1

    # --- Estado interno ---
    eta: float = field(init=False)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # partimos en eta_base, como en tu QiCoreEngineV21
        self.eta = float(self.eta_base)

    # ==========================================================
    # QiMeta: update eta
    # ==========================================================

    def update_qimeta(self, last_error: float) -> float:
        """
        Ajusta eta con feedback:
        - SHOCK: si last_error > shock_threshold reduce eta (más conservador)
        - RECUPERACIÓN: si no, vuelve lentamente hacia eta_base

        Retorna el nuevo eta.
        """
        e = float(last_error)

        if e > self.shock_threshold:
            self.eta = max(self.eta_min, self.eta - self.delta_penal)
            mode = "shock"
        else:
            self.eta = min(self.eta_base, self.eta + self.delta_recup)
            mode = "recovery"

        self.history.append({"last_error": e, "eta": float(self.eta), "mode": mode})
        return float(self.eta)

    # ==========================================================
    # Internals (lambda_1, regime, tanh)
    # ==========================================================

    def _lambda_1(self) -> float:
        # ahora depende de eta dinámico
        return 1.0 / (self.eta + self.eps)

    def _regime(self, sigma: float) -> str:
        if sigma <= self.sigma_known:
            return "known"
        if sigma <= self.sigma_border:
            return "border"
        return "ood"

    @staticmethod
    def _tanh(x: float) -> float:
        return math.tanh(x)

    # ==========================================================
    # Hamiltoniano desde GP
    # ==========================================================

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
        # Término de misión (piecewise) — idéntico a tu engine
        # -------------------------
        if reg == "known":
            # Anti-falsos-positivos por signo:
            # En conocido, NO dejamos que lo negativo suba energía.
            term_mission = -U_pos

        elif reg == "border":
            # Transición: lo negativo penaliza, pero amortiguado.
            # OJO: U_neg es negativo; beta*U_neg también es negativo;
            # -(U_pos + beta*U_neg) => si U_neg<0, se suma algo positivo (penaliza).
            term_mission = -(U_pos + self.beta_neg_border * U_neg)

        else:  # "ood"
            # En OOD domina la incertidumbre. Misión se ignora o pesa poco.
            term_mission = -self.mission_weight_ood * U_pos

        # -------------------------
        # Riesgo e incertidumbre
        # -------------------------
        term_risk = lam1 * float(v_risk)
        term_uncertainty = self.lambda_2 * float(sigma)

        H_total = float(term_mission + term_risk + term_uncertainty)

        terms = {
            "regime": reg,
            "mu": float(mu),
            "sigma": float(sigma),
            "U_tanh": float(U),
            "eta": float(self.eta),
            "eta_base": float(self.eta_base),
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
