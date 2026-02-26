# experiments/experiment_hamiltonian_threshold_inversion.py
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

#from services.qicore_engine_piecewise import QiCoreEnginePiecewise
from services.qicore_engine_threshold import QiCoreEngineThreshold



# ==============================================================
# EXPERIMENTO (AUDITORÍA): Inversión por threshold (búsqueda automática)
# --------------------------------------------------------------
# Objetivo:
#  - Encontrar automáticamente un threshold T* que:
#       1) Bloquee casi todo en el intervalo conocido (train interval)
#       2) Deje pasar el mayor porcentaje posible fuera del intervalo
#
# Mantiene estructura GP + auto-calibración + plots + CSV/txt
# No modifica el engine. Solo calcula H y explora thresholds.
# ==============================================================

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# Zona conocida (intervalo de entrenamiento)
X_MIN, X_MAX = 2.9, 4.7
N_TRAIN = 60

# Amplificación de sin(x) para saturar tanh
AMP = 8.0

# Auto-calibración (percentiles sobre σ_train)
Q_KNOWN = 0.99
Q_BORDER = 0.999

SIGMA_FLOOR = 1e-6
BORDER_MIN_RATIO = 1.05

# --- Parámetros engine ---
ETA = 0.4
LAMBDA_2 = 2.5
V_RISK = 0.05
BETA_NEG_BORDER = 0.20

# Permite "escape" fuera (OOD) cuando mu positivo
MISSION_WEIGHT_OOD = 1.0

# --- Búsqueda de threshold ---
TARGET_BLOCK_KNOWN = 0.98   # queremos bloquear >=98% dentro del intervalo train
N_GRID_THRESHOLDS = 600     # densidad de búsqueda (sube a 1200 si quieres más fino)
EPS = 1e-9

# --------------------------------------------------------------
# 1) Datos train
# --------------------------------------------------------------
X_train = np.linspace(X_MIN, X_MAX, N_TRAIN).reshape(-1, 1)
y_train = (AMP * np.sin(X_train)).ravel()

# --------------------------------------------------------------
# 2) GP
# --------------------------------------------------------------
kernel = C(1.0) * RBF(0.6)
gp = GaussianProcessRegressor(
    kernel=kernel,
    n_restarts_optimizer=10,
    alpha=1e-8,
    normalize_y=False
)
gp.fit(X_train, y_train)

_, sigma_train = gp.predict(X_train, return_std=True)
sigma_known = float(np.quantile(sigma_train, Q_KNOWN))
sigma_border = float(np.quantile(sigma_train, Q_BORDER))

sigma_known = max(sigma_known, SIGMA_FLOOR)
sigma_border = max(sigma_border, sigma_known * BORDER_MIN_RATIO)

print(f"[calib] σ_train: min={sigma_train.min():.6g} max={sigma_train.max():.6g}")
print(
    f"[calib] sigma_known=P{int(Q_KNOWN*100)}={sigma_known:.6g} | "
    f"sigma_border=P{Q_BORDER*100:.1f}={sigma_border:.6g}"
)

# --------------------------------------------------------------
# 3) Espacio de test
# --------------------------------------------------------------
X_test = np.linspace(0, 15, 450).reshape(-1, 1)
mu, sigma = gp.predict(X_test, return_std=True)

# --------------------------------------------------------------
# 4) Engine (threshold placeholder)
# --------------------------------------------------------------
# qicore = QiCoreEnginePiecewise(
#     eta=ETA,
#     lambda_2=LAMBDA_2,
#     threshold=1.0,  # no lo usamos para decidir; exploramos thresholds afuera
#     sigma_known=sigma_known,
#     sigma_border=sigma_border,
#     beta_neg_border=BETA_NEG_BORDER,
#     mission_weight_ood=MISSION_WEIGHT_OOD
# )

qicore = QiCoreEngineThreshold(
    eta=0.4,
    lambda_2=2.5,

    # umbrales de régimen (auto-calibrados en el experimento)
    sigma_known=sigma_known,
    sigma_border=sigma_border,

    # misión (igual que antes)
    beta_neg_border=0.20,
    mission_weight_ood=0.0,

    # NUEVO: política threshold-aware
    margin_known=0.08,
    margin_border=0.04,
    margin_ood=0.00,

    gain_U_known=0.20,
    gain_U_border=0.10,
    gain_U_ood=0.00,

    use_dynamic_threshold=True
)


# --------------------------------------------------------------
# 5) Calcula H en todo el grid (una sola vez)
# --------------------------------------------------------------
rows = []
for x, m, s in zip(X_test.ravel(), mu, sigma):
    H, info = qicore.hamiltonian_energy_from_gp(
        mu=float(m),
        sigma=float(s),
        v_risk=V_RISK,
        return_terms=True
    )
    rows.append([
        float(x),
        float(m),
        float(s),
        float(info["U_tanh"]),
        float(H),
        info["regime"],
        float(info["term_mission"]),
        float(info["term_uncertainty"]),
        float(info["term_risk"]),
    ])

df = pd.DataFrame(
    rows,
    columns=[
        "Input", "mu", "sigma", "U_tanh", "H",
        "regime", "term_mission", "term_uncertainty", "term_risk",
    ]
)

# Masks intervalos
in_known_interval = (df["Input"] >= X_MIN) & (df["Input"] <= X_MAX)
out_interval = ~in_known_interval

H_known = df.loc[in_known_interval, "H"].to_numpy()
H_out = df.loc[out_interval, "H"].to_numpy()

# --------------------------------------------------------------
# 6) Búsqueda automática del threshold "más invertido"
# --------------------------------------------------------------
# Buscamos thresholds en un rango razonable:
# - Entre (min(H_known)-margen) y (max(H_known)+margen)
# Así nos movemos cerca del "borde" donde cambia bloqueo en known.
t_min = float(H_known.min() - 0.5)
t_max = float(H_known.max() + 0.5)

grid_T = np.linspace(t_min, t_max, N_GRID_THRESHOLDS)

best = None  # (score, T, block_known, pass_out, block_out)

for T in grid_T:
    blocked_known = float(np.mean(H_known > T))
    blocked_out = float(np.mean(H_out > T))
    pass_out = 1.0 - blocked_out

    # Constraint: bloquear casi todo en known interval
    if blocked_known + 1e-12 < TARGET_BLOCK_KNOWN:
        continue

    # Score: maximizar pass_out; en empate, preferir menor bloqueo_known (más "justo")
    score = pass_out

    if (best is None) or (score > best[0] + 1e-12):
        best = (score, float(T), blocked_known, pass_out, blocked_out)

if best is None:
    # fallback: el umbral más bajo que bloquee todo known (min(H_known)-eps)
    T_star = float(H_known.min() - EPS)
    blocked_known_star = float(np.mean(H_known > T_star))
    blocked_out_star = float(np.mean(H_out > T_star))
    pass_out_star = 1.0 - blocked_out_star
    note = "No se encontró T que cumpla TARGET_BLOCK_KNOWN; usando fallback min(H_known)-eps."
else:
    pass_out_star, T_star, blocked_known_star, pass_out_star, blocked_out_star = best
    note = "T* encontrado por búsqueda con constraint de bloqueo en known."

# Recalcular estados con T_star
df["threshold_star"] = T_star
df["blocked_star"] = df["H"] > T_star
df["Estado_star"] = np.where(df["blocked_star"], "BLOQUEADO", "SEGURO")

# Métricas por régimen con T*
is_known_regime = df["regime"] == "known"
is_border_regime = df["regime"] == "border"
is_ood_regime = df["regime"] == "ood"

def _rate(x):
    return float(x)

b_known = _rate(np.mean(df.loc[is_known_regime, "blocked_star"])) if is_known_regime.any() else 0.0
b_border = _rate(np.mean(df.loc[is_border_regime, "blocked_star"])) if is_border_regime.any() else 0.0
b_ood = _rate(np.mean(df.loc[is_ood_regime, "blocked_star"])) if is_ood_regime.any() else 0.0

print("\n=== EXPERIMENTO: INVERSIÓN POR THRESHOLD (BÚSQUEDA AUTOMÁTICA) ===")
print(f"Engine params: eta={ETA} lambda_2={LAMBDA_2} v_risk={V_RISK} mission_weight_ood={MISSION_WEIGHT_OOD}")
print(f"Constraint: blocked_known_interval >= {TARGET_BLOCK_KNOWN:.2f}")
print(f"Grid thresholds: [{t_min:.3g}, {t_max:.3g}] con N={N_GRID_THRESHOLDS}")
print(f"{note}")
print(f"T* = {T_star:.6g}")

print("\n--- Intervalo conocido (geométrico) ---")
print(f"blocked_known_interval = {blocked_known_star:.3f}  (objetivo >= {TARGET_BLOCK_KNOWN:.2f})")

print("\n--- Fuera del intervalo conocido ---")
print(f"blocked_out_interval   = {blocked_out_star:.3f}")
print(f"pass_out_interval      = {pass_out_star:.3f}  (maximizado)")

print("\n--- Por régimen (según sigma auto-calibrada) ---")
print(f"blocked KNOWN(regime)  = {b_known:.3f}")
print(f"blocked BORDER(regime) = {b_border:.3f}")
print(f"blocked OOD(regime)    = {b_ood:.3f}")

# --------------------------------------------------------------
# 7) Guardar CSV
# --------------------------------------------------------------
csv_path = os.path.join(RESULTS_DIR, "experiment_hamiltonian_threshold_inversion_search.csv")
df.to_csv(csv_path, index=False)
print(f"\nCSV guardado en: {csv_path}")

# --------------------------------------------------------------
# 8) Gráficas
# --------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))

# (1) μ y σ
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
ax1.set_title("GP: μ(x) y σ(x) — Intervalo entrenado")
ax1.legend()
ax1.grid(True, alpha=0.3)

# (2) H + threshold T*
H_arr = df["H"].to_numpy()
ax2.plot(X_test, H_arr, linewidth=2, label="H(x) (engine piecewise)")
ax2.axhline(y=T_star, linestyle="--", label=f"T*={T_star:.3g} (auto-search)")

baseline = float(min(-2.0, H_arr.min()))
ax2.fill_between(
    X_test.ravel(),
    baseline,
    H_arr,
    where=df["blocked_star"].to_numpy(),
    alpha=0.25,
    label="BLOQUEADO (con T*)",
)

ax2.axvspan(X_MIN, X_MAX, alpha=0.15, label="Zona conocida (train)")
ax2.set_title("QiCore Piecewise: H(x) — Threshold T* maximiza 'pass_out' con bloqueo en train")
ax2.set_xlabel("x")
ax2.set_ylabel("H")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()

png_path = os.path.join(RESULTS_DIR, "experiment_hamiltonian_threshold_inversion_search.png")
plt.savefig(png_path, dpi=200)
print(f"PNG guardado en: {png_path}")
plt.show()

# --------------------------------------------------------------
# 9) Resumen TXT
# --------------------------------------------------------------
summary_path = os.path.join(RESULTS_DIR, "experiment_hamiltonian_threshold_inversion_search_summary.txt")
with open(summary_path, "w", encoding="utf-8") as f:
    f.write("=== EXPERIMENTO: INVERSIÓN POR THRESHOLD (BÚSQUEDA AUTOMÁTICA) ===\n\n")
    f.write(f"Zona conocida: [{X_MIN},{X_MAX}] con N_TRAIN={N_TRAIN}\n")
    f.write(f"AMP: {AMP}\n")
    f.write(f"Kernel (fit): {gp.kernel_}\n")
    f.write(f"alpha: {gp.alpha}\n\n")

    f.write("Auto-calibración (desde σ_train):\n")
    f.write(f"  Q_KNOWN: {Q_KNOWN}\n")
    f.write(f"  Q_BORDER: {Q_BORDER}\n")
    f.write(f"  sigma_train_min: {float(np.min(sigma_train))}\n")
    f.write(f"  sigma_train_max: {float(np.max(sigma_train))}\n")
    f.write(f"  sigma_known: {sigma_known}\n")
    f.write(f"  sigma_border: {sigma_border}\n\n")

    f.write("Engine params:\n")
    f.write(f"  eta: {ETA}\n")
    f.write(f"  lambda_2: {LAMBDA_2}\n")
    f.write(f"  v_risk: {V_RISK}\n")
    f.write(f"  beta_neg_border: {BETA_NEG_BORDER}\n")
    f.write(f"  mission_weight_ood: {MISSION_WEIGHT_OOD}\n\n")

    f.write("Búsqueda threshold:\n")
    f.write(f"  TARGET_BLOCK_KNOWN: {TARGET_BLOCK_KNOWN}\n")
    f.write(f"  N_GRID_THRESHOLDS: {N_GRID_THRESHOLDS}\n")
    f.write(f"  rango: [{t_min},{t_max}]\n")
    f.write(f"  nota: {note}\n")
    f.write(f"  T*: {T_star}\n\n")

    f.write("Resultados:\n")
    f.write(f"  blocked_known_interval: {blocked_known_star}\n")
    f.write(f"  blocked_out_interval: {blocked_out_star}\n")
    f.write(f"  pass_out_interval: {pass_out_star}\n")
    f.write(f"  blocked_known_regime: {b_known}\n")
    f.write(f"  blocked_border_regime: {b_border}\n")
    f.write(f"  blocked_ood_regime: {b_ood}\n\n")

print(f"Resumen guardado en: {summary_path}")
