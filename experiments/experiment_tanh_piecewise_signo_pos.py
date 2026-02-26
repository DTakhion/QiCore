# experiments/experiment_tanh_piecewise_signo_pos.py
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine_piecewise import QiCoreEnginePiecewise


# ==============================================================
# Experimento INVERSO: "Signo con tanh (saturación +1)" usando Engine Piecewise
# Objetivo: mismo experimento, pero ahora en un intervalo donde sin(x)>0,
#           para que AMP*sin(x) sea grande positivo y tanh(mu)≈+1.
#           En régimen known (σ≈0), NO debería bloquear por misión.
#
# Versión AUTO-CALIBRADA:
#   - sigma_known y sigma_border se derivan de percentiles de σ_train
#   - evita perillas manipulables por el "usuario" (hardcode)
# ==============================================================

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# Zona conocida: intervalo denso donde sin(x) es mayoritariamente POSITIVO
# (primer "lomo" positivo antes de pi)
X_MIN, X_MAX = 0.4, 2.6
N_TRAIN = 60

# Amplificación para saturar tanh(mu) hacia +1 en esa zona
AMP = 8.0

# Auto-calibración: percentiles sobre σ_train
Q_KNOWN = 0.99     # P99(σ_train) => límite "known"
Q_BORDER = 0.999   # P99.9(σ_train) => límite "border"

# Pisos numéricos / separaciones mínimas
SIGMA_FLOOR = 1e-6
BORDER_MIN_RATIO = 1.05  # sigma_border >= 1.05 * sigma_known

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

# --- Auto-calibración de umbrales de régimen desde σ en training ---
_, sigma_train = gp.predict(X_train, return_std=True)

sigma_known = float(np.quantile(sigma_train, Q_KNOWN))
sigma_border = float(np.quantile(sigma_train, Q_BORDER))

# blindajes numéricos
sigma_known = max(sigma_known, SIGMA_FLOOR)
sigma_border = max(sigma_border, sigma_known * BORDER_MIN_RATIO)

print(f"[calib] σ_train: min={sigma_train.min():.6g} max={sigma_train.max():.6g}")
print(f"[calib] sigma_known=P{int(Q_KNOWN*100)}={sigma_known:.6g} | "
      f"sigma_border=P{Q_BORDER*100:.1f}={sigma_border:.6g}")

# Espacio de prueba (incluye zona conocida y fuera)
X_test = np.linspace(0, 15, 450).reshape(-1, 1)
mu, sigma = gp.predict(X_test, return_std=True)

# Motor QiCore Piecewise (mismos params base que el experimento anterior)
qicore = QiCoreEnginePiecewise(
    eta=0.4,
    lambda_2=2.5,
    threshold=1.0,

    # AUTO-CALIBRADOS desde σ_train
    sigma_known=sigma_known,
    sigma_border=sigma_border,

    beta_neg_border=0.20,
    mission_weight_ood=0.0
)

THRESHOLD = qicore.threshold

rows = []
for x, m, s in zip(X_test.ravel(), mu, sigma):
    m = float(m)
    s = float(s)

    H, info = qicore.hamiltonian_energy_from_gp(
        mu=m,
        sigma=s,
        v_risk=0.05,
        return_terms=True
    )
    estado = "BLOQUEADO" if info["blocked"] else "SEGURO"

    rows.append([
        float(x),
        m,
        s,
        info.get("U_tanh"),
        float(H),
        info.get("regime"),
        info.get("term_mission"),
        info.get("term_uncertainty"),
        info.get("term_risk"),
        estado
    ])

df = pd.DataFrame(
    rows,
    columns=[
        "Input", "mu", "sigma", "U_tanh", "H",
        "regime", "term_mission", "term_uncertainty", "term_risk",
        "Estado"
    ]
)

# Métrica: bloqueos dentro de la zona conocida
in_known = (df["Input"] >= X_MIN) & (df["Input"] <= X_MAX)
blocked_known = int(((df["Estado"] == "BLOQUEADO") & in_known).sum())
total_known = int(in_known.sum())
regime_counts_known = df.loc[in_known, "regime"].value_counts(dropna=False).to_dict()

# Guardar CSV
csv_path = os.path.join(RESULTS_DIR, "experiment_intervalo_tanh_signo_piecewise_pos.csv")
df.to_csv(csv_path, index=False)
print(f"CSV guardado en: {csv_path}")
print(f"Zona conocida [{X_MIN},{X_MAX}] N_TRAIN={N_TRAIN} AMP={AMP}")
print(f"Bloqueos dentro de zona conocida: {blocked_known}/{total_known}")
print(f"Regímenes dentro zona conocida: {regime_counts_known}")

# Gráficas (mismo estilo)
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
ax1.set_title("GP: μ(x) y σ(x) — Intervalo entrenado (saturación positiva)")
ax1.legend()
ax1.grid(True, alpha=0.3)

# 2) H y umbral + bloqueos
H_arr = df["H"].to_numpy()
ax2.plot(X_test, H_arr, linewidth=2, label="H(x) (engine piecewise, U=tanh(mu) interno)")
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
ax2.set_title("QiCore Piecewise: H(x) — experimento inverso (saturación +1)")
ax2.set_xlabel("x")
ax2.set_ylabel("H")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
png_path = os.path.join(RESULTS_DIR, "experiment_intervalo_tanh_signo_piecewise_pos.png")
plt.savefig(png_path, dpi=200)
print(f"PNG guardado en: {png_path}")
plt.show()

# Resumen
summary_path = os.path.join(RESULTS_DIR, "experiment_intervalo_tanh_signo_piecewise_pos_summary.txt")
with open(summary_path, "w", encoding="utf-8") as f:
    f.write("=== EXPERIMENTO INVERSO: tanh (+1) con engine piecewise (AUTO-CALIBRADO) ===\n\n")
    f.write(f"Zona conocida: [{X_MIN},{X_MAX}] con N_TRAIN={N_TRAIN}\n")
    f.write(f"AMP: {AMP}\n")
    f.write(f"Kernel (fit): {gp.kernel_}\n")
    f.write(f"alpha: {gp.alpha}\n")
    f.write(f"Threshold: {THRESHOLD}\n\n")

    f.write("Auto-calibración (desde σ_train):\n")
    f.write(f"  Q_KNOWN: {Q_KNOWN}\n")
    f.write(f"  Q_BORDER: {Q_BORDER}\n")
    f.write(f"  sigma_train_min: {float(np.min(sigma_train))}\n")
    f.write(f"  sigma_train_max: {float(np.max(sigma_train))}\n")
    f.write(f"  sigma_known: {sigma_known}\n")
    f.write(f"  sigma_border: {sigma_border}\n")
    f.write(f"  beta_neg_border: {qicore.beta_neg_border}\n")
    f.write(f"  mission_weight_ood: {qicore.mission_weight_ood}\n\n")

    f.write(f"Bloqueos dentro zona conocida: {blocked_known}/{total_known}\n")
    f.write(f"Regímenes dentro zona conocida: {regime_counts_known}\n\n")

    cols = ["Input","mu","sigma","U_tanh","H","regime","term_mission","term_uncertainty","term_risk","Estado"]
    f.write("Muestra (zona conocida) — head:\n")
    f.write(df.loc[in_known, cols].head(12).to_string(index=False))
    f.write("\n\nMuestra (zona conocida) — tail:\n")
    f.write(df.loc[in_known, cols].tail(12).to_string(index=False))

print(f"Resumen guardado en: {summary_path}")
