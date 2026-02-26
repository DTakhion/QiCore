#experiments/experiment_tanh_audit.py 
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine import QiCoreEngine


# ==============================================================
# Experimento: "Signo con tanh" (falsos positivos por saturación negativa)
# Objetivo: mostrar bloqueos en zona conocida por -tanh(U) cuando tanh(U)≈-1,
#           aun con σ≈0 (culpa del término de misión, no de incertidumbre).
# ==============================================================

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# Zona conocida: intervalo denso donde sin(x) es mayoritariamente NEGATIVO
X_MIN, X_MAX = 2.9, 4.7
N_TRAIN = 60

# Amplificación para saturar tanh(U) hacia -1 en esa zona
AMP = 8.0

X_train = np.linspace(X_MIN, X_MAX, N_TRAIN).reshape(-1, 1)
y_train = (AMP * np.sin(X_train)).ravel()

# GP (queremos σ muy baja en la zona conocida)
kernel = C(1.0) * RBF(0.6)
gp = GaussianProcessRegressor(
    kernel=kernel,
    n_restarts_optimizer=10,
    alpha=1e-8,          # casi sin ruido -> σ→0 en train
    normalize_y=False
)
gp.fit(X_train, y_train)

# Espacio de prueba (incluye zona conocida y fuera)
X_test = np.linspace(0, 15, 450).reshape(-1, 1)
mu, sigma = gp.predict(X_test, return_std=True)

# Motor QiCore (tal cual tu base)
qicore = QiCoreEngine(eta=0.4, lambda_2=2.5)
THRESHOLD = qicore.threshold

# Hamiltoniano usando SOLO utilidad tanh(mu)
rows = []
for x, m, s in zip(X_test.ravel(), mu, sigma):
    m = float(m)
    s = float(s)

    U_tanh = float(np.tanh(m))   # <- receta Gemini, aplicada a la utilidad
    H, _ = qicore.hamiltonian_energy(utility=U_tanh, uncertainty=s)

    estado = "BLOQUEADO" if H > THRESHOLD else "SEGURO"
    rows.append([float(x), m, s, U_tanh, float(H), estado])

df = pd.DataFrame(rows, columns=["Input", "mu", "sigma", "U_tanh", "H", "Estado"])

# Métrica: bloqueos dentro de la zona conocida
in_known = (df["Input"] >= X_MIN) & (df["Input"] <= X_MAX)
blocked_known = int(((df["Estado"] == "BLOQUEADO") & in_known).sum())
total_known = int(in_known.sum())

# Guardar CSV
csv_path = os.path.join(RESULTS_DIR, "experiment_intervalo_tanh_signo.csv")
df.to_csv(csv_path, index=False)
print(f"CSV guardado en: {csv_path}")
print(f"Zona conocida [{X_MIN},{X_MAX}] N_TRAIN={N_TRAIN} AMP={AMP}")
print(f"Bloqueos dentro de zona conocida: {blocked_known}/{total_known}")

# Gráficas (mismo estilo que tu experimento)
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))

# 1) μ y σ + zona conocida
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
ax1.set_title("GP: μ(x) y σ(x) — Intervalo entrenado (sin amplificado negativo)")
ax1.legend()
ax1.grid(True, alpha=0.3)

# 2) H y umbral + bloqueos
H_arr = df["H"].to_numpy()
ax2.plot(X_test, H_arr, linewidth=2, label="H(x) con U=tanh(μ)")
ax2.axhline(y=THRESHOLD, linestyle="--", label=f"Threshold={THRESHOLD}")

baseline = float(min(-2.0, H_arr.min()))
ax2.fill_between(
    X_test.ravel(),
    baseline,
    H_arr,
    where=(H_arr > THRESHOLD),
    alpha=0.25,
    label="BLOQUEADO",
)

# resaltar bloqueos dentro de zona conocida
x_known_blocked = df.loc[(df["Estado"] == "BLOQUEADO") & in_known, "Input"].to_numpy()
y_known_blocked = df.loc[(df["Estado"] == "BLOQUEADO") & in_known, "H"].to_numpy()
if len(x_known_blocked) > 0:
    ax2.scatter(x_known_blocked, y_known_blocked, label="Bloqueo dentro zona conocida")

ax2.axvspan(X_MIN, X_MAX, alpha=0.15, label="Zona conocida (train)")
ax2.set_title("QiCore: Bloqueo por H(x) usando U=tanh(μ) — sesgo por signo (saturación -1)")
ax2.set_xlabel("x")
ax2.set_ylabel("H")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
png_path = os.path.join(RESULTS_DIR, "experiment_intervalo_tanh_signo.png")
plt.savefig(png_path, dpi=200)
print(f"PNG guardado en: {png_path}")
plt.show()

# Resumen
summary_path = os.path.join(RESULTS_DIR, "experiment_intervalo_tanh_signo_summary.txt")
with open(summary_path, "w", encoding="utf-8") as f:
    f.write(f"Zona conocida: [{X_MIN},{X_MAX}] con N_TRAIN={N_TRAIN}\n")
    f.write(f"AMP: {AMP}\n")
    f.write(f"Kernel: {gp.kernel_}\n")
    f.write(f"alpha: {gp.alpha}\n")
    f.write(f"Threshold: {THRESHOLD}\n")
    f.write(f"Bloqueos dentro zona conocida: {blocked_known}/{total_known}\n\n")
    f.write(df.loc[in_known, ["Input", "mu", "sigma", "U_tanh", "H", "Estado"]].head(12).to_string(index=False))
    f.write("\n\n")
    f.write(df.loc[in_known, ["Input", "mu", "sigma", "U_tanh", "H", "Estado"]].tail(12).to_string(index=False))

print(f"Resumen guardado en: {summary_path}")
