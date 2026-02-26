# experiments/experiment_qimeta_islas_conocimiento.py

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine_qimeta import QiCoreEngineV21


RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)


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
            "blocked": bool(blocked),
            "eta_prev": float(eta_prev),
            "eta_next": float(q.eta),
        })

    df = pd.DataFrame(rows)

    # métricas mínimas (auditoría)
    df["blocked_int"] = df["blocked"].astype(int)
    cascade_max = (
        df["blocked_int"]
        .groupby((df["blocked_int"] == 0).cumsum())
        .sum()
        .max()
    )

    # recuperación a 95% de eta_base (si alcanza)
    rec_cycles = None
    target = 0.95 * eta_base
    idx_drop = df.index[df["eta_prev"] < eta_base]
    if len(idx_drop) > 0:
        i0 = idx_drop[0]
        post = df.iloc[i0:]
        hit = post.index[post["eta_next"] >= target]
        if len(hit) > 0:
            rec_cycles = int(hit[0] - i0 + 1)

    summary = {
        "scenario": name,
        "n_steps": len(inputs),
        "blocked_total": int(df["blocked_int"].sum()),
        "cascade_max": int(cascade_max) if pd.notna(cascade_max) else 0,
        "recovery_cycles_to_95pct": rec_cycles,
        "eta_min": float(df["eta_next"].min()),
        "eta_end": float(df["eta_next"].iloc[-1]),
    }

    return df, summary


def plot_sequence(df, title, out_png, threshold=1.0, islands=None):
    # islands: list of (a,b) to highlight known zones
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 10))

    # 1) sigma
    ax1.plot(df["cycle"], df["sigma"], marker="o", linewidth=2)
    ax1.set_title(f"{title} — Incertidumbre σ (GP)")
    ax1.set_ylabel("σ")
    ax1.grid(True, alpha=0.3)

    # 2) H + umbral
    ax2.plot(df["cycle"], df["H"], marker="o", linewidth=2)
    ax2.axhline(threshold, linestyle="--")
    ax2.set_title(f"{title} — Energía H y Umbral")
    ax2.set_ylabel("H")
    ax2.grid(True, alpha=0.3)

    # 3) eta + bloqueos
    ax3.step(df["cycle"], df["eta_prev"], where="post", linewidth=2, label="η")
    # marcar bloqueos
    blocked_cycles = df[df["blocked"]]["cycle"].tolist()
    if blocked_cycles:
        ax3.scatter(blocked_cycles, df[df["blocked"]]["eta_prev"], label="bloqueo")
    ax3.set_title(f"{title} — η (QiMeta) y Bloqueos")
    ax3.set_xlabel("cycle")
    ax3.set_ylabel("η")
    ax3.grid(True, alpha=0.3)
    ax3.legend()

    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    plt.show()


# ==============================================================
# 1) Entrenamiento: "islas de conocimiento"
#    X_train = [0.5,4.5] ∪ [15,21.5]
# ==============================================================

# Muestreo simple por grilla en cada isla (toy, pero suficiente)
x_isla_1 = np.linspace(0.5, 4.5, 9)
x_isla_2 = np.linspace(15.0, 21.5, 10)

X_train = np.atleast_2d(np.concatenate([x_isla_1, x_isla_2])).T
y_train = np.sin(X_train).ravel()

gp = GaussianProcessRegressor(kernel=C(1.0) * RBF(1.0), n_restarts_optimizer=10)
gp.fit(X_train, y_train)

# Guardar train para trazabilidad
train_df = pd.DataFrame({"x": X_train.ravel(), "y": y_train})
train_df.to_csv(os.path.join(RESULTS_DIR, "qimeta_islas_train.csv"), index=False)


# ==============================================================
# 2) Escenarios: vacío (gap) + reingreso a isla 2
# ==============================================================

scenarios = {
    # Cruza el vacío y luego entra a isla 2 (lo que planteaste)
    "gap_then_isla2": [3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 15.5, 17.0, 19.0, 20.5],

    # Permanecer en el vacío (shock sostenido dentro del gap)
    "gap_sustained": [6.0, 7.0, 8.0, 9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 12.0, 9.0],

    # Alternar isla1 ↔ gap ↔ isla2 (oscilación)
    "isla1_gap_isla2_alternate": [2.0, 8.0, 3.5, 10.0, 4.2, 12.0, 3.0, 15.5, 4.0, 17.0, 4.5],

    # Control: solo isla 2 (debería ser “normal” en esa isla)
    "isla2_only": [15.2, 16.0, 17.5, 18.2, 19.0, 20.0, 21.0, 15.8, 16.7, 18.9],
}

all_rows = []
summaries = []

for name, seq in scenarios.items():
    df_s, s = run_sequence(name, seq, gp, eta_base=0.7, lambda_2=2.5, threshold=1.0)
    all_rows.append(df_s)
    summaries.append(s)

df_all = pd.concat(all_rows, ignore_index=True)
df_summary = pd.DataFrame(summaries)

# Guardar resultados
df_all.to_csv(os.path.join(RESULTS_DIR, "qimeta_islas_all.csv"), index=False)
df_summary.to_csv(os.path.join(RESULTS_DIR, "qimeta_islas_summary.csv"), index=False)

print("\n=== RESUMEN: ISLAS DE CONOCIMIENTO (QiMeta) ===")
print(df_summary.to_string(index=False))

# Plots por escenario
for name in scenarios.keys():
    d = df_all[df_all["scenario"] == name].copy()
    out_png = os.path.join(RESULTS_DIR, f"qimeta_islas_{name}.png")
    plot_sequence(d, title=name, out_png=out_png, threshold=1.0)

