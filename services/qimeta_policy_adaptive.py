# services/qimeta_policy_adaptive.py  (patch recomendado)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass
class QiMetaAdaptiveConfig:
    eta_base: float = 0.6
    eta_min: float = 0.1
    eta_max: float = 2.0

    delta_penal: float = 0.4
    delta_recup: float = 0.05
    shock_threshold: float = 0.5

    # borde/chattering
    risk_threshold: float = 0.6
    risk_band: float = 0.05
    ema_alpha: float = 0.2
    dwell_steps: int = 3
    flip_window: int = 12
    flip_rate_hi: float = 0.25
    eta_border_scale: float = 1.25

    # recovery lento de lambda_1
    safe_steps_to_recover: int = 6
    eta_recover_boost: float = 0.08
    lambda1_target_min: float = 1.2
    lambda1_eps: float = 1e-6

@dataclass
class QiMetaAdaptiveState:
    t: int = 0
    risk_ema: Optional[float] = None
    last_mode: str = "SAFE"
    last_mode_change_t: int = -10**9
    mode_hist: List[str] = field(default_factory=list)
    safe_streak: int = 0
    lambda1_at_safe_start: Optional[float] = None

class QiMetaAdaptivePolicy:
    def __init__(self, cfg: QiMetaAdaptiveConfig):
        self.cfg = cfg
        self.state = QiMetaAdaptiveState()

    def _clamp(self, x: float) -> float:
        return max(self.cfg.eta_min, min(self.cfg.eta_max, x))

    def step(
        self,
        eta: float,
        last_error: float,
        lambda1: float,
        risk_value: Optional[float] = None,  # 👈 NUEVO (opcional)
    ) -> Dict[str, Any]:
        s = self.state
        c = self.cfg

        # Señal de riesgo efectiva (por defecto: last_error)
        r_eff = float(last_error if risk_value is None else risk_value)

        # --- EMA del riesgo ---
        if s.risk_ema is None:
            s.risk_ema = r_eff
        else:
            s.risk_ema = c.ema_alpha * r_eff + (1 - c.ema_alpha) * s.risk_ema

        # --- modo por histéresis alrededor de risk_threshold ---
        in_border = abs(s.risk_ema - c.risk_threshold) <= c.risk_band
        mode_now = "RISK" if s.risk_ema >= c.risk_threshold else "SAFE"

        if mode_now != s.last_mode and (s.t - s.last_mode_change_t) < c.dwell_steps:
            mode_now = s.last_mode
        elif mode_now != s.last_mode:
            s.last_mode = mode_now
            s.last_mode_change_t = s.t

        s.mode_hist.append(mode_now)
        if len(s.mode_hist) > c.flip_window:
            s.mode_hist.pop(0)

        flips = sum(1 for i in range(1, len(s.mode_hist)) if s.mode_hist[i] != s.mode_hist[i-1])
        flip_rate = flips / max(1, len(s.mode_hist) - 1)

        # shock sigue usando last_error (binario o continuo según lo definas)
        e = float(last_error)
        is_shock = e > c.shock_threshold

        # recovery lento: SAFE sostenido + lambda1 bajo
        if mode_now == "SAFE":
            s.safe_streak += 1
            if s.safe_streak == 1:
                s.lambda1_at_safe_start = float(lambda1)
        else:
            s.safe_streak = 0
            s.lambda1_at_safe_start = None

        lambda1_too_low = float(lambda1) < float(c.lambda1_target_min)
        slow_recovery = (mode_now == "SAFE" and s.safe_streak >= c.safe_steps_to_recover and lambda1_too_low)

        # chattering: borde + flips altos
        chattering = (in_border and flip_rate >= c.flip_rate_hi)

        eta_next = float(eta)
        reasons = []

        if is_shock:
            eta_next = self._clamp(eta_next - c.delta_penal)
            reasons.append("shock: eta -= delta_penal")
        else:
            if eta_next < c.eta_base:
                eta_next = min(c.eta_base, eta_next + c.delta_recup)
                reasons.append("base_recovery: eta += delta_recup")

            if chattering:
                eta_next = self._clamp(eta_next * c.eta_border_scale)
                reasons.append("border_chattering: eta *= eta_border_scale")

            if slow_recovery:
                eta_next = self._clamp(eta_next - c.eta_recover_boost)
                reasons.append("slow_lambda1_recovery: eta -= eta_recover_boost")

        out = {
            "t": s.t,
            "last_error": e,
            "risk_value": float(r_eff),
            "risk_ema": float(s.risk_ema),
            "mode": mode_now,
            "in_border": bool(in_border),
            "flips": int(flips),
            "flip_rate": float(flip_rate),
            "shock": bool(is_shock),
            "chattering": bool(chattering),
            "slow_recovery": bool(slow_recovery),
            "eta_prev": float(eta),
            "eta_next": float(eta_next),
            "lambda1": float(lambda1),
            "reasons": reasons,
        }

        s.t += 1
        return out
