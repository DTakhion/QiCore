# services/qicore_engine_piecewise_qimeta_optimal.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from services.qicore_engine_piecewise_qimeta import QiCoreEnginePiecewiseQiMeta
from services.qimeta_policy_adaptive import QiMetaAdaptiveConfig, QiMetaAdaptivePolicy


@dataclass
class QiCoreEnginePiecewiseQiMetaOptimal(QiCoreEnginePiecewiseQiMeta):
    """
    Igual Hamiltoniano piecewise, pero eta se actualiza con policy adaptativa:
    - detecta chattering en borde (con risk_value continuo)
    - detecta recuperación lenta de lambda_1
    - mantiene shock/recovery base (con last_error)
    """

    policy_cfg: QiMetaAdaptiveConfig = field(default_factory=QiMetaAdaptiveConfig)
    _policy: QiMetaAdaptivePolicy = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()

        # sincroniza config con engine actual
        self.policy_cfg.eta_base = float(self.eta_base)
        self.policy_cfg.eta_min = float(self.eta_min)

        # IMPORTANTE:
        # risk_threshold es el umbral de "modo" SAFE/RISK (para el EMA),
        # NO el shock_threshold del engine.
        # Como ahora risk_value es 0..1 (stress), un valor razonable es 0.6.
        self.policy_cfg.risk_threshold = 0.6

        self._policy = QiMetaAdaptivePolicy(self.policy_cfg)

    def update_qimeta(self, last_error: float, risk_value: Optional[float] = None) -> float:
        """
        Override: usa policy adaptativa.

        - last_error: señal dura de shock (0/1)
        - risk_value: señal continua 0..1 (stress) para EMA/borde/chattering
          Si no se entrega, se usa last_error como proxy.
        """
        lam1 = self._lambda_1()

        # si no hay risk_value, usa last_error como proxy
        r = float(last_error) if risk_value is None else float(risk_value)

        diag = self._policy.step(
            eta=float(self.eta),
            last_error=float(r),   # la policy trata "last_error" como riesgo/proxy
            lambda1=float(lam1),
        )

        self.eta = float(diag["eta_next"])
        self.history.append(diag)
        return float(self.eta)
