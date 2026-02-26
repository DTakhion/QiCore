# services/qicore_engine.py

class QiCoreEngine:
    def __init__(self, eta=0.5, lambda_2=2.0):
        self.eta = eta
        self.lambda_2 = lambda_2
        self.threshold = 1.0  # Umbral de energía (uso futuro)

    def hamiltonian_energy(self, utility, uncertainty, v_risk=0.05):
        """
        H(A) = -U(A) + λ1(η) * V_risk + λ2 * Σ(A)
        """
        lambda_1 = 1.0 / (self.eta + 1e-6)

        term_mission = -utility
        term_risk = lambda_1 * v_risk
        term_uncertainty = self.lambda_2 * uncertainty

        h_total = term_mission + term_risk + term_uncertainty
        return h_total, term_uncertainty

