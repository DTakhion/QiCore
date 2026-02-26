# experiments/experiment_qimeta_islas_piecewise_qimeta.py

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine_piecewise_qimeta import QiCoreEnginePiecewiseQiMeta


RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# --------------------------
# CONFIG DEBUG (rápido on/off)
# --------------------------
DEBUG = True
DEBUG_MAX_LINES_PER_SCENARIO = 9999  # pon 12 si quieres poco spam


# ==============================================================
# Helper: auto-calibrar sigmas de manera ROBUSTA (no solo X_train)
# ==============================================================
def calibrate_sigmas_robust(
    gp,
    isla_ranges,
    points_per_isla=200,
    q_known=0.99,
    q_border=0.999,
    min_gap=1.20,
    sigma_floor=1e-4,
):
    """
    Calibra sigma_known/sigma_border estimando σ(x) en una grilla densa
    DENTRO de las islas (no solo en X_train, donde σ≈0 por construcción).

    - sigma_floor evita que los umbrales queden ~1e-5 y conviertan todo en OOD.
    - min_gap fuerza separación entre known y border.
    """
    xs = []
    for (a, b) in isla_ranges:
        xs.append(np.linspace(a, b, int(points_per_isla)))
    X_cal = np.atleast_2d(np.concatenate(xs)).T

    _, sigma_cal = gp.predict(X_cal, return_std=True)
    sigma_cal = np.asarray(sigma_cal, dtype=float)

    s_known = float(np.quantile(sigma_cal, q_known))
    s_border = float(np.quantile(sigma_cal, q_border))

    # Floors y separación mínima
    s_known = max(s_known, float(sigma_floor))
    s_border = max(s_border, float(sigma_floor), min_gap * s_known, s_known + 1e-12)

    return s_known, s_border, X_cal, sigma_cal


# ==============================================================
# Runner (QiCore Piecewise + QiMeta)  + DEBUG de threshold/bloqueos
# ==============================================================
def run_sequence(
    name,
    inputs,
    gp,
    engine: QiCoreEnginePiecewiseQiMeta,
    threshold=0.6,
    v_risk=0.05,
):
    thr = float(threshold)
    if hasattr(engine, "threshold"):
        engine.threshold = thr

    if DEBUG:
        print(f"\n[debug:{name}] threshold(exp)={thr}  engine.threshold={getattr(engine,'threshold',None)}")
        print(f"[debug:{name}] sigma_known={getattr(engine,'sigma_known',None)}  sigma_border={getattr(engine,'sigma_border',None)}")
        print(f"[debug:{name}] eta_base={getattr(engine,'eta_base',None)}  eta_start={getattr(engine,'eta',None)}  lambda_2={getattr(engine,'lambda_2',None)}  v_risk={v_risk}")

    rows = []
    for t, x_val in enumerate(inputs, start=1):
        x_arr = np.atleast_2d([x_val]).T
        mu, sigma = gp.predict(x_arr, return_std=True)

        mu_val = float(mu[0])
        sigma_val = float(sigma[0])

        H, info = engine.hamiltonian_energy_from_gp(
            mu=mu_val,
            sigma=sigma_val,
            v_risk=float(v_risk),
            return_terms=True,
        )

        # decisión oficial del experimento (usa threshold del experimento)
        blocked = bool(float(H) > thr)

        if DEBUG and t <= DEBUG_MAX_LINES_PER_SCENARIO:
            info_block = info.get("blocked", None)
            print(
                f"[debug:{name}] t={t:02d} x={x_val:>7.2f}  mu={mu_val:+.4f}  "
                f"sigma={sigma_val:.6f}  reg={str(info.get('regime',None)):>6}  "
                f"H={float(H):+.6f}  (H>thr? {blocked})  info.blocked={info_block}"
            )

        eta_prev = float(engine.eta)
        engine.update_qimeta(1.0 if blocked else 0.0)
        eta_next = float(engine.eta)

        rows.append(
            {
                "scenario": name,
                "cycle": int(t),
                "x": float(x_val),
                "mu": mu_val,
                "sigma": sigma_val,
                "U_tanh": float(info.get("U_tanh", np.tanh(mu_val))),
                "regime": info.get("regime", None),
                "lambda_1": float(info.get("lambda_1", 1.0 / (eta_prev + 1e-6))),
                "term_mission": float(info.get("term_mission", np.nan)),
                "term_uncertainty": float(info.get("term_uncertainty", np.nan)),
                "term_risk": float(info.get("term_risk", np.nan)),
                "H": float(H),
                "blocked": bool(blocked),
                "blocked_engine": bool(info.get("blocked", False)) if (info.get("blocked", None) is not None) else None,
                "threshold_exp": thr,
                "threshold_engine": float(getattr(engine, "threshold", np.nan)),
                "eta_prev": eta_prev,
                "eta_next": eta_next,
            }
        )

    df = pd.DataFrame(rows)

    df["blocked_int"] = df["blocked"].astype(int)
    cascade_max = (
        df["blocked_int"]
        .groupby((df["blocked_int"] == 0).cumsum())
        .sum()
        .max()
    )

    rec_cycles = None
    eta_base = float(getattr(engine, "eta_base", np.nan))
    if np.isfinite(eta_base):
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
        "n_steps": int(len(inputs)),
        "blocked_total": int(df["blocked_int"].sum()),
        "cascade_max": int(cascade_max) if pd.notna(cascade_max) else 0,
        "recovery_cycles_to_95pct": rec_cycles,
        "eta_min": float(df["eta_next"].min()) if len(df) else np.nan,
        "eta_end": float(df["eta_next"].iloc[-1]) if len(df) else np.nan,
        "H_max": float(df["H"].max()) if len(df) else np.nan,
        "H_min": float(df["H"].min()) if len(df) else np.nan,
        "threshold_used": float(threshold),
    }

    if DEBUG:
        print(f"[debug:{name}] H_min={summary['H_min']:+.6f}  H_max={summary['H_max']:+.6f}  blocked_total={summary['blocked_total']}")

    return df, summary


def plot_sequence(df, title, out_png, threshold=1.0):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 10))

    ax1.plot(df["cycle"], df["sigma"], marker="o", linewidth=2)
    ax1.set_title(f"{title} — Incertidumbre σ (GP)")
    ax1.set_ylabel("σ")
    ax1.grid(True, alpha=0.3)

    ax2.plot(df["cycle"], df["H"], marker="o", linewidth=2)
    ax2.axhline(float(threshold), linestyle="--")
    ax2.set_title(f"{title} — Energía H y Umbral")
    ax2.set_ylabel("H")
    ax2.grid(True, alpha=0.3)

    ax3.step(df["cycle"], df["eta_prev"], where="post", linewidth=2, label="η")
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
# 1) Entrenamiento: "islas de conocimiento" (CONFIGURABLE)
# ==============================================================

# --- Cambia esto para crear un "desierto" largo ---
ISLA1 = (0.5, 4.5)
ISLA2 = (100.0, 110.0)   # <-- vacío enorme: gap ~95 unidades

isla_ranges = [ISLA1, ISLA2]

# muestreo TRAIN (pocos puntos, toy)
x_isla_1 = np.linspace(ISLA1[0], ISLA1[1], 9)
x_isla_2 = np.linspace(ISLA2[0], ISLA2[1], 10)

X_train = np.atleast_2d(np.concatenate([x_isla_1, x_isla_2])).T
y_train = np.sin(X_train).ravel()

gp = GaussianProcessRegressor(kernel=C(1.0) * RBF(1.0), n_restarts_optimizer=10)
gp.fit(X_train, y_train)

pd.DataFrame({"x": X_train.ravel(), "y": y_train}).to_csv(
    os.path.join(RESULTS_DIR, "qimeta_islas_piecewise_train.csv"), index=False
)

# --- Auto-calibración robusta (grilla densa en islas + floor) ---
sigma_known, sigma_border, X_cal, sigma_cal = calibrate_sigmas_robust(
    gp,
    isla_ranges=isla_ranges,
    points_per_isla=250,
    q_known=0.99,
    q_border=0.999,
    min_gap=1.20,
    sigma_floor=1e-4,
)
pd.DataFrame({"x_cal": X_cal.ravel(), "sigma_cal": sigma_cal}).to_csv(
    os.path.join(RESULTS_DIR, "qimeta_islas_piecewise_sigma_cal.csv"),
    index=False
)

print(f"[auto-calib robust] sigma_known={sigma_known:.6f}  sigma_border={sigma_border:.6f}")


# ==============================================================
# 2) Escenarios (VACÍO EXTENSO)
# ==============================================================

def linspace_list(a, b, n):
    return [float(x) for x in np.linspace(a, b, int(n))]

scenarios = {
    # sale de isla1, cruza el desierto en muchos pasos, entra a isla2
    "gap_then_isla2_extenso": (
        [3.0, 4.0] +
        linspace_list(8.0, 95.0, 15) +   # <-- desierto largo con 15 pasos
        [100.5, 103.0, 106.0, 109.0]
    ),

    # desierto sostenido (muchos ciclos en OOD)
    "gap_sustained_extenso": linspace_list(10.0, 95.0, 25),

    # control: solo isla2
    "isla2_only": [100.5, 102.0, 104.5, 106.0, 108.0, 109.5, 101.0, 103.2],
}

# ---------
# EXP CONFIG
# ---------
THRESHOLD_EXP = 0.6
V_RISK = 0.05
ETA_BASE = 0.7
LAMBDA_2 = 2.5

all_rows = []
summaries = []

for name, seq in scenarios.items():
    engine = QiCoreEnginePiecewiseQiMeta(
        eta_base=float(ETA_BASE),
        lambda_2=float(LAMBDA_2),
        threshold=float(THRESHOLD_EXP),
        sigma_known=float(sigma_known),
        sigma_border=float(sigma_border),
        beta_neg_border=0.20,
        mission_weight_ood=0.0,
    )

    df_s, s = run_sequence(
        name,
        seq,
        gp,
        engine,
        threshold=float(THRESHOLD_EXP),
        v_risk=float(V_RISK),
    )
    all_rows.append(df_s)
    summaries.append(s)

df_all = pd.concat(all_rows, ignore_index=True)
df_summary = pd.DataFrame(summaries)

df_all.to_csv(os.path.join(RESULTS_DIR, "qimeta_islas_piecewise_all.csv"), index=False)
df_summary.to_csv(os.path.join(RESULTS_DIR, "qimeta_islas_piecewise_summary.csv"), index=False)

print("\n=== RESUMEN: ISLAS DE CONOCIMIENTO (Piecewise + QiMeta, GAP EXTENSO) ===")
print(df_summary.to_string(index=False))

for name in scenarios.keys():
    d = df_all[df_all["scenario"] == name].copy()
    out_png = os.path.join(RESULTS_DIR, f"qimeta_islas_piecewise_{name}.png")
    plot_sequence(d, title=name, out_png=out_png, threshold=float(THRESHOLD_EXP))
