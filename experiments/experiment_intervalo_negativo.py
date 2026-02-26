# experiments/experiment_intervalo_negativo.py

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine import QiCoreEngine


# ==============================================================
# Experimento: "Intervalo Negativo" (U(A)=mu(x) < 0 en zona conocida)
# Objetivo: evidenciar bloqueos por signo (no por incertidumbre)
# ==============================================================

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# 1) Zona conocida: intervalo denso donde sin(x) es mayoritariamente negativo
X_MIN, X_MAX = 2.9, 4.7
N_TRAIN = 40

X_train = np.linspace(X_MIN, X_MAX, N_TRAIN).reshape(-1, 1)
y_train = np.sin(X_train).ravel()

# 2) GP para estimar incertidumbre
kernel = C(1.0) * RBF(1.0)
gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=10)
gp.fit(X_train, y_train)

# 3) Espacio de prueba: incluye zona conocida y fuera de ella
X_test = np.linspace(0, 15, 400).reshape(-1, 1)
mu, sigma = gp.predict(X_test, return_std=True)

# 4) Motor QiCore (sin QiMeta, lambda_1 fijo por eta)
qicore = QiCoreEngine(eta=0.4, lambda_2=2.5)

# 5) Hamiltoniano + estado
rows = []
for x, m, s in zip(X_test.ravel(), mu, sigma):
    h, _ = qicore.hamiltonian_energy(utility=float(m), uncertainty=float(s))
    estado = "BLOQUEADO" if h > qicore.threshold else "SEGURO"
    rows.append([float(x), float(m), float(s), float(h), estado])

df = pd.DataFrame(rows, columns=["Input", "mu", "sigma", "H", "Estado"])

# Métrica útil: bloqueos dentro de la zona conocida
in_known = (df["Input"] >= X_MIN) & (df["Input"] <= X_MAX)
blocked_known = int(((df["Estado"] == "BLOQUEADO") & in_known).sum())
total_known = int(in_known.sum())

# 6) Guardar CSV
csv_path = os.path.join(RESULTS_DIR, "experiment_intervalo_negativo.csv")
df.to_csv(csv_path, index=False)
print(f"CSV guardado en: {csv_path}")
print(f"Bloqueos dentro de zona conocida [{X_MIN},{X_MAX}]: {blocked_known}/{total_known}")

# 7) Gráficas
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))

# --- Gráfica 1: mu y sigma + zona conocida ---
ax1.plot(X_train, y_train, "ro", label="Train (zona conocida)")
ax1.plot(X_test, mu, "b--", label="Predicción μ(x)")
ax1.fill_between(
    X_test.ravel(),
    mu - 1.96 * sigma,
    mu + 1.96 * sigma,
    alpha=0.2,
    label="Incertidumbre (≈95%)",
)
ax1.axvspan(X_MIN, X_MAX, alpha=0.15, label="Zona conocida (train)")
ax1.set_title("GP: μ(x) y σ(x) — Intervalo de entrenamiento negativo")
ax1.legend()
ax1.grid(True, alpha=0.3)

# --- Gráfica 2: H y umbral + bloqueos ---
H = df["H"].to_numpy()
ax2.plot(X_test, H, linewidth=2, label="H(x)")
ax2.axhline(y=qicore.threshold, linestyle="--", label=f"Threshold={qicore.threshold}")

baseline = float(min(-2.0, H.min()))
ax2.fill_between(
    X_test.ravel(),
    baseline,
    H,
    where=(H > qicore.threshold),
    alpha=0.3,
    label="BLOQUEADO",
)

# resaltar bloqueos dentro de zona conocida
x_known_blocked = df.loc[(df["Estado"] == "BLOQUEADO") & in_known, "Input"].to_numpy()
y_known_blocked = df.loc[(df["Estado"] == "BLOQUEADO") & in_known, "H"].to_numpy()
if len(x_known_blocked) > 0:
    ax2.scatter(x_known_blocked, y_known_blocked, label="Bloqueo dentro zona conocida")

ax2.axvspan(X_MIN, X_MAX, alpha=0.15, label="Zona conocida (train)")
ax2.set_title("QiCore v1: Bloqueo por H(x) (evidencia de sesgo por signo)")
ax2.set_xlabel("x")
ax2.set_ylabel("H")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()

png_path = os.path.join(RESULTS_DIR, "experiment_intervalo_negativo.png")
plt.savefig(png_path, dpi=200)
print(f"PNG guardado en: {png_path}")

plt.show()

# 8) Resumen textual reproducible
summary_path = os.path.join(RESULTS_DIR, "experiment_intervalo_negativo_summary.txt")
with open(summary_path, "w", encoding="utf-8") as f:
    f.write(f"Zona conocida: [{X_MIN},{X_MAX}] con N_TRAIN={N_TRAIN}\n")
    f.write(f"Bloqueos dentro zona conocida: {blocked_known}/{total_known}\n\n")
    f.write(df.loc[in_known, ["Input", "mu", "sigma", "H", "Estado"]].head(12).to_string(index=False))
    f.write("\n\n")
    f.write(df.loc[in_known, ["Input", "mu", "sigma", "H", "Estado"]].tail(12).to_string(index=False))

print(f"Resumen guardado en: {summary_path}")

