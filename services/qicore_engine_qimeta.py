# services/qicore_engine_qimeta.py

class QiCoreEngineV21:
    """
    Motor QiCore v2.1 con QiMeta (memoria rápida/lenta) y ajuste adaptativo de eta.
    """

    def __init__(self, eta_base=0.6, lambda_2=2.5):
        self.eta = eta_base
        self.eta_base = eta_base
        self.lambda_2 = lambda_2
        self.threshold = 0.15 # antes 1.0
        self.history = []

    def update_qimeta(self, last_error: float):
        """
        Ajusta eta con feedback:
        - SHOCK: si last_error > 0.5 reduce eta (más conservador)
        - RECUPERACIÓN: si no, vuelve lentamente hacia eta_base
        """
        delta_penal = 0.4
        delta_recup = 0.05

        if last_error > 0.5:
            self.eta = max(0.1, self.eta - delta_penal)
        else:
            self.eta = min(self.eta_base, self.eta + delta_recup)

    def calculate_hamiltonian(self, utility: float, uncertainty: float, v_risk: float = 0.05) -> float:
        """
        H(A) = -U(A) + λ1(η)*Vrisk(A) + λ2*Σ(A)
        donde λ1 = 1/η
        """
        lambda_1 = 1.0 / (self.eta + 1e-6)
        return (-utility) + (lambda_1 * v_risk) + (self.lambda_2 * uncertainty)

