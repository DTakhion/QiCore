# experiments/experiment_qimeta_antifragilidad.py

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine_qimeta import QiCoreEngineV21


# ==============================================================
# Experimento QiMeta: Antifragilidad y Stress Test
# ==============================================================

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)


# ==============================================================
# Utilidad: correr una secuencia (stress test)
# ==============================================================

def run_sequence(name, inputs, gp, eta_base=0.7, lambda_2=2.5, threshold=1.0):
    q = QiCoreEngineV21(eta_base=eta_base, lambda_2=lambda_2)
    q.threshold = threshold

    rows = []
    for t, x_val in enumerate(inputs, start=1):
        x_arr = np.atleast_2d([x_val]).T
        mu, sigma = gp.predict(x_arr, return_std=True)

        h = q.calculate_hamiltonian(float(mu[0]), float(sigma[0]))
        blocked = h > q.threshold

        eta_prev = q.eta
        q.update_qimeta(1.0 if blocked else 0.0)

        rows.append({
            "scenario": name,
            "cycle": t,
            "x": float(x_val),
            "mu": float(mu[0]),
            "sigma": float(sigma[0]),
            "H": float(h),
            "blocked": blocked,
            "eta_prev": eta_prev,
            "eta_next": q.eta,
        })

    df = pd.DataFrame(rows)

    # métricas de stress
    df["blocked_int"] = df["blocked"].astype(int)
    cascade_max = (
        df["blocked_int"]
        .groupby((df["blocked_int"] == 0).cumsum())
        .sum()
        .max()
    )

    # recuperación
    rec_cycles = None
    if (df["eta_prev"] < eta_base).any():
        target = 0.95 * eta_base
        idx0 = df.index[df["eta_prev"] < eta_base][0]
        post = df.iloc[idx0:]
        hit = post.index[post["eta_next"] >= target]
        if len(hit) > 0:
            rec_cycles = int(hit[0] - idx0 + 1)

    collateral = int(df[(df["x"] <= 5.0) & (df["blocked"])].shape[0])

    summary = {
        "scenario": name,
        "n_steps": len(inputs),
        "blocked_total": int(df["blocked_int"].sum()),
        "cascade_max": int(cascade_max) if pd.notna(cascade_max) else 0,
        "recovery_cycles_to_95pct": rec_cycles,
        "collateral_blocks_safe_zone": collateral,
        "eta_min": float(df["eta_next"].min()),
        "eta_end": float(df["eta_next"].iloc[-1]),
    }

    return df, summary


# ==============================================================
# 1. Entrenamiento base (conocimiento real)
# ==============================================================

X_train = np.atleast_2d([0.5, 1.5, 2.5, 3.5, 4.5]).T
y_train = np.sin(X_train).ravel()

gp = GaussianProcessRegressor(kernel=C(1.0) * RBF(1.0), n_restarts_optimizer=10)
gp.fit(X_train, y_train)


# ==============================================================
# 2. Escenarios de stress
# ==============================================================

scenarios = {
    "A_normal":       [1.0, 2.0, 3.0, 4.0, 2.5, 1.5, 5.0, 3.5, 4.2, 0.8],
    "B_shock":        [12.0, 12.5, 13.0, 14.0, 15.0, 13.5, 12.2, 14.8, 13.9, 12.1],
    "C_shock_return": [2.0, 3.0, 12.0, 12.5, 13.0, 2.5, 3.5, 4.0, 1.5, 2.2],
    "D_alternate":    [2.0, 12.0, 2.5, 12.5, 3.0, 13.0, 3.5, 13.5, 4.0, 14.0],
}

all_rows = []
summaries = []

for name, seq in scenarios.items():
    df_s, s = run_sequence(name, seq, gp)
    all_rows.append(df_s)
    summaries.append(s)

df_all = pd.concat(all_rows, ignore_index=True)
df_summary = pd.DataFrame(summaries)

# Guardar resultados
df_all.to_csv(os.path.join(RESULTS_DIR, "qimeta_stress_all.csv"), index=False)
df_summary.to_csv(os.path.join(RESULTS_DIR, "qimeta_stress_summary.csv"), index=False)

print("\n=== RESUMEN STRESS TESTS (QiMeta) ===")
print(df_summary.to_string(index=False))


# ==============================================================
# 3. Gráficas por escenario
# ==============================================================

for name in scenarios.keys():
    d = df_all[df_all["scenario"] == name]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

    ax1.plot(d["cycle"], d["H"], marker="o", linewidth=2)
    ax1.axhline(1.0, linestyle="--")
    ax1.set_title(f"{name} — Energía H y Umbral")
    ax1.grid(True, alpha=0.3)

    ax2.step(d["cycle"], d["eta_prev"], where="post", linewidth=2)
    ax2.set_title(f"{name} — Evolución de η (QiMeta)")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, f"qimeta_{name}.png"), dpi=200)
    plt.show()
