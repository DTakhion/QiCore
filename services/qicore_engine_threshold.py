# services/qicore_engine_threshold.py

from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Dict, Any, Tuple


@dataclass
class QiCoreEngineThreshold:
    """
    QiCore v3 (threshold-aware)
    ------------------------------------
    Objetivo:
      - Mantener H = term_mission + λ1*V_risk + λ2*sigma
      - Mantener el fix anti-signo en KNOWN (U<0 no penaliza allí)
      - Resolver el hallazgo de auditoría: un threshold fijo no conversa con los términos
        (colapso en KNOWN, separación mala entre regímenes).

    Estrategia:
      - Se calcula H igual que en piecewise.
      - La decisión de bloqueo NO usa un threshold fijo, sino un threshold dinámico T(regime)
        definido en función del baseline del propio modelo:

          baseline(sigma) = λ1*V_risk + λ2*sigma

        y márgenes por régimen:

          T_known  = baseline + margin_known + k_known * U_pos
          T_border = baseline + margin_border + k_border * U_pos
          T_ood    = baseline + margin_ood   + k_ood * U_pos

      Intuición:
        - KNOWN: H tiende a baseline - U_pos. Si el baseline domina, un threshold fijo se vuelve
          irrelevante o bloquea todo. Aquí el threshold se “ancla” al baseline para que la decisión
          dependa del exceso energético real.
        - BORDER/OOD: el threshold puede volverse más estricto (margen menor) o más permisivo
          según política. Por defecto, hacemos OOD más estricto (margin_ood pequeño),
          para que σ empuje al bloqueo.

    Nota:
      - Esto NO cambia H; solo cambia la política de decisión "blocked".
      - Los márgenes y gains son parámetros de política (auditables).
    """

    # --- parámetros base del modelo ---
    eta: float = 0.5
    lambda_2: float = 2.0

    # umbrales de régimen por sigma (normalmente auto-calibrados)
    sigma_known: float = 0.08
    sigma_border: float = 0.30

    # utilidad negativa en border (amortiguación)
    beta_neg_border: float = 0.20

    # peso de misión en OOD (premia positivo débil si >0)
    mission_weight_ood: float = 0.0

    # eps numérico
    eps: float = 1e-6

    # ==========================================================
    # Política de thresholds dinámicos (LO NUEVO)
    # ----------------------------------------------------------
    # margins: cuánto “aire” dejamos sobre el baseline en cada régimen.
    # gains:   cómo dejamos que U_pos suba el threshold (más permisivo si misión es buena).
    #
    # Lectura:
    # - margin pequeño => más estricto (bloquea más)
    # - margin grande  => más permisivo
    # - gain_U_pos > 0 => si la misión es muy buena (U_pos alto), sube T => bloquea menos
    #
    # Defaults conservadores:
    # - KNOWN: margen moderado para que no bloquee por baseline
    # - BORDER: un poco más estricto
    # - OOD: bastante más estricto (queremos que σ gobierne)
    # ==========================================================
    margin_known: float = 0.10
    margin_border: float = 0.05
    margin_ood: float = 0.00

    gain_U_known: float = 0.20
    gain_U_border: float = 0.10
    gain_U_ood: float = 0.00

    # Umbral fijo opcional (para compatibilidad / debugging).
    # Si use_dynamic_threshold=False, se usa threshold_fixed.
    threshold_fixed: float = 1.0
    use_dynamic_threshold: bool = True

    # ----------------------------------------------------------

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
        return math.tanh(x)

    def _term_mission(self, reg: str, U: float) -> float:
        U_pos = max(U, 0.0)
        U_neg = min(U, 0.0)

        if reg == "known":
            # FIX anti-falsos-positivos por signo: U<0 NO sube energía
            return -U_pos

        if reg == "border":
            # Transición: lo negativo penaliza amortiguado
            return -(U_pos + self.beta_neg_border * U_neg)

        # OOD: por defecto misión ignorable, o premia positivo muy débil si mission_weight_ood>0
        return -self.mission_weight_ood * U_pos

    def _dynamic_threshold(self, reg: str, baseline: float, U: float) -> float:
        U_pos = max(U, 0.0)

        if reg == "known":
            return float(baseline + self.margin_known + self.gain_U_known * U_pos)
        if reg == "border":
            return float(baseline + self.margin_border + self.gain_U_border * U_pos)
        # ood
        return float(baseline + self.margin_ood + self.gain_U_ood * U_pos)

    def hamiltonian_energy_from_gp(
        self,
        mu: float,
        sigma: float,
        v_risk: float = 0.05,
        return_terms: bool = True
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calcula:
          H = term_mission + λ1*V_risk + λ2*sigma

        y decide bloqueo con threshold dinámico (si está habilitado).
        """
        mu = float(mu)
        sigma = float(sigma)

        lam1 = self._lambda_1()
        reg = self._regime(sigma)

        U = self._tanh(mu)

        term_mission = self._term_mission(reg, U)
        term_risk = lam1 * float(v_risk)
        term_uncertainty = self.lambda_2 * sigma

        baseline = float(term_risk + term_uncertainty)
        H_total = float(term_mission + baseline)

        if self.use_dynamic_threshold:
            T = self._dynamic_threshold(reg, baseline, U)
        else:
            T = float(self.threshold_fixed)

        blocked = bool(H_total > T)

        terms = {
            "regime": reg,
            "mu": mu,
            "sigma": sigma,
            "U_tanh": float(U),
            "lambda_1": float(lam1),
            "term_mission": float(term_mission),
            "term_risk": float(term_risk),
            "term_uncertainty": float(term_uncertainty),
            "baseline": float(baseline),
            "threshold_effective": float(T),
            "blocked": blocked,
        }

        if return_terms:
            return H_total, terms
        return H_total, {}

    def is_blocked(self, mu: float, sigma: float, v_risk: float = 0.05) -> bool:
        _, info = self.hamiltonian_energy_from_gp(mu=mu, sigma=sigma, v_risk=v_risk, return_terms=True)
        return bool(info["blocked"])
