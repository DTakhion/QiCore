# experiments/experiment_qimeta_ab_test.py

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine_piecewise_qimeta import QiCoreEnginePiecewiseQiMeta
from services.qicore_engine_piecewise_qimeta_optimal import QiCoreEnginePiecewiseQiMetaOptimal


RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

DEBUG_FIRST_K = 6          # cuantos pasos imprime por escenario (como ya lo haces)
DEBUG_COMPARE = False      # True => imprime A y B lado a lado por ciclo


# ==============================================================
# Helpers: métricas
# ==============================================================

def _cascade_max(blocked_int: pd.Series) -> int:
    if blocked_int.empty:
        return 0
    grp = (blocked_int == 0).cumsum()
    m = blocked_int.groupby(grp).sum().max()
    return int(m) if pd.notna(m) else 0

def _recovery_cycles_to_95pct(df: pd.DataFrame, eta_base: float) -> int | None:
    target = 0.95 * float(eta_base)
    idx_drop = df.index[df["eta_prev"] < float(eta_base)]
    if len(idx_drop) == 0:
        return None
    i0 = int(idx_drop[0])
    post = df.iloc[i0:]
    hit = post.index[post["eta_next"] >= target]
    if len(hit) == 0:
        return None
    return int(hit[0] - i0 + 1)

def _blocked_flips(blocked_bool: pd.Series) -> int:
    if blocked_bool.empty:
        return 0
    b = blocked_bool.astype(int).to_numpy()
    return int(np.sum(np.abs(np.diff(b))))


# ==============================================================
# Runner A/B
# ==============================================================

def run_sequence_ab(
    scenario_name: str,
    inputs: list[float],
    gp: GaussianProcessRegressor,
    *,
    eta_base: float = 0.7,
    lambda_2: float = 2.5,
    threshold: float = 0.20,
    sigma_known: float = 0.08,
    sigma_border: float = 0.30,
    beta_neg_border: float = 0.20,
    mission_weight_ood: float = 0.0,
    v_risk: float = 0.12,

    # --- clave para que A y B no colapsen igual ---
    shock_threshold: float = 0.98,
    delta_penal: float = 0.15,
    delta_recup: float = 0.08,
    eta_min: float = 0.25,
):
    # A: baseline piecewise+qimeta simple
    eng_A = QiCoreEnginePiecewiseQiMeta(
        eta_base=eta_base,
        lambda_2=lambda_2,
        threshold=threshold,
        sigma_known=sigma_known,
        sigma_border=sigma_border,
        beta_neg_border=beta_neg_border,
        mission_weight_ood=mission_weight_ood,

        # tuning
        shock_threshold=shock_threshold,
        delta_penal=delta_penal,
        delta_recup=delta_recup,
        eta_min=eta_min,
    )

    # B: optimal/adaptive eta policy (mismo Hamiltoniano piecewise)
    eng_B = QiCoreEnginePiecewiseQiMetaOptimal(
        eta_base=eta_base,
        lambda_2=lambda_2,
        threshold=threshold,
        sigma_known=sigma_known,
        sigma_border=sigma_border,
        beta_neg_border=beta_neg_border,
        mission_weight_ood=mission_weight_ood,

        # tuning
        shock_threshold=shock_threshold,
        delta_penal=delta_penal,
        delta_recup=delta_recup,
        eta_min=eta_min,
    )

    engines = [
        ("A_baseline", eng_A),
        ("B_optimal", eng_B),
    ]

    all_rows = []

    # contadores para diagnosticar si B efectivamente usa risk_value
    b_used_risk_value_steps = 0
    b_fallback_steps = 0

    # si quieres debug A vs B en el mismo ciclo
    def _fmt(engine_name, t, x, H, thr, blocked, stress, shock_event, eta_prev, eta_next, path):
        return (f"[debug:{scenario_name}] {engine_name} "
                f"t={t:02d} x={x:5.3f} H={H: .4f} thr={thr:.3f} "
                f"blk={int(blocked)} stress={stress:.3f} shockEvt={int(shock_event)} "
                f"eta:{eta_prev:.3f}->{eta_next:.3f} {path}")

    for engine_name, q in engines:
        rows = []
        for t, x_val in enumerate(inputs, start=1):
            x_arr = np.atleast_2d([x_val]).T
            mu, sigma = gp.predict(x_arr, return_std=True)

            eta_prev = float(q.eta)

            H, terms = q.hamiltonian_energy_from_gp(
                mu=float(mu[0]),
                sigma=float(sigma[0]),
                v_risk=v_risk,
                return_terms=True,
            )
            blocked = bool(H > q.threshold)

            # ----------------------------------------------------------
            # stress continuo (0..1) relativo al umbral
            # ----------------------------------------------------------
            denom = max(1e-9, 0.4 * float(q.threshold))
            stress = float(np.clip((float(H) - 0.8 * float(q.threshold)) / denom, 0.0, 1.0))

            # shock_event solo para métricas/debug (NO para el update)
            shock_event = bool(stress >= float(shock_threshold))

            # ----------------------------------------------------------
            # CAMBIO CLAVE: feedback continuo
            # ----------------------------------------------------------
            #last_error = float(stress)
            #last_error = float(stress**2)   # comprime valores medios, deja 1.0 como 1.0

            last_error = float(np.sqrt(stress))  # lo contrario (más sensible)


            # update A/B
            path = ""
            if engine_name == "A_baseline":
                q.update_qimeta(last_error)
                path = "path=A_last_error=stress"
            else:
                try:
                    q.update_qimeta(last_error, risk_value=stress)
                    b_used_risk_value_steps += 1
                    path = "path=B_risk_value"
                except TypeError:
                    q.update_qimeta(last_error)
                    b_fallback_steps += 1
                    path = "path=B_fallback"

            eta_next = float(q.eta)

            # debug por escenario (primeros K)
            if t <= DEBUG_FIRST_K and engine_name == "B_optimal" and not DEBUG_COMPARE:
                # mantienes tu estilo: una línea por paso, pero solo B
                print(_fmt("B", t, float(x_val), float(H), float(q.threshold), blocked, stress, shock_event,
                           eta_prev, eta_next, path))

            if t <= DEBUG_FIRST_K and DEBUG_COMPARE:
                print(_fmt("A" if engine_name == "A_baseline" else "B",
                           t, float(x_val), float(H), float(q.threshold), blocked, stress, shock_event,
                           eta_prev, eta_next, path))

            rows.append({
                "scenario": scenario_name,
                "engine": engine_name,
                "cycle": int(t),
                "x": float(x_val),
                "mu": float(mu[0]),
                "sigma": float(sigma[0]),
                "regime": terms.get("regime"),
                "H": float(H),
                "blocked": bool(blocked),
                "stress": float(stress),
                "shock_event": bool(shock_event),

                "eta_prev": float(eta_prev),
                "eta_next": float(eta_next),

                "lambda_1": float(terms.get("lambda_1", np.nan)),
                "term_mission": float(terms.get("term_mission", np.nan)),
                "term_risk": float(terms.get("term_risk", np.nan)),
                "term_uncertainty": float(terms.get("term_uncertainty", np.nan)),

                "threshold": float(q.threshold),
                "v_risk": float(v_risk),
                "shock_threshold": float(shock_threshold),
                "delta_penal": float(delta_penal),
                "delta_recup": float(delta_recup),
                "eta_min_cfg": float(eta_min),
            })

        df = pd.DataFrame(rows)
        df["blocked_int"] = df["blocked"].astype(int)

        H_start = float(df["H"].iloc[0]) if len(df) > 0 else float("nan")
        H_end = float(df["H"].iloc[-1]) if len(df) > 0 else float("nan")

        summary = {
            "scenario": scenario_name,
            "engine": engine_name,
            "n_steps": int(len(df)),

            "blocked_total": int(df["blocked_int"].sum()),
            "blocked_rate": float(df["blocked_int"].mean()) if len(df) > 0 else 0.0,
            "blocked_flips": _blocked_flips(df["blocked"]),
            "cascade_max": _cascade_max(df["blocked_int"]),

            "stress_mean": float(df["stress"].mean()) if len(df) > 0 else 0.0,
            "stress_max": float(df["stress"].max()) if len(df) > 0 else 0.0,

            "shock_events_total": int(df["shock_event"].astype(int).sum()),

            "H_start": H_start,
            "H_end": H_end,
            "delta_H": float(H_end - H_start) if (not np.isnan(H_end) and not np.isnan(H_start)) else float("nan"),
            "H_mean": float(df["H"].mean()),
            "H_sum": float(df["H"].sum()),
            "H_min": float(df["H"].min()),
            "H_max": float(df["H"].max()),

            "eta_min": float(df["eta_next"].min()),
            "eta_end": float(df["eta_next"].iloc[-1]),
            "recovery_cycles_to_95pct": _recovery_cycles_to_95pct(df, eta_base=eta_base),

            "threshold": float(threshold),
            "v_risk": float(v_risk),

            # tuning info
            "shock_threshold": float(shock_threshold),
            "delta_penal": float(delta_penal),
            "delta_recup": float(delta_recup),
            "eta_min_cfg": float(eta_min),
        }

        all_rows.append((df, summary))

    dfA, sA = all_rows[0]
    dfB, sB = all_rows[1]

    df_all = pd.concat([dfA, dfB], ignore_index=True)
    df_summary = pd.DataFrame([sA, sB])

    # inyecta contadores en ambos summaries (para ver si B usó risk_value)
    df_summary["B_used_risk_value_steps"] = 0
    df_summary["B_fallback_steps"] = 0
    df_summary.loc[df_summary["engine"] == "B_optimal", "B_used_risk_value_steps"] = int(b_used_risk_value_steps)
    df_summary.loc[df_summary["engine"] == "B_optimal", "B_fallback_steps"] = int(b_fallback_steps)

    return df_all, df_summary


# ==============================================================
# Plot comparativo por escenario
# ==============================================================

def plot_ab(df_all: pd.DataFrame, scenario_name: str, out_png: str, threshold: float = 0.20):
    dA = df_all[df_all["engine"] == "A_baseline"].sort_values("cycle")
    dB = df_all[df_all["engine"] == "B_optimal"].sort_values("cycle")

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(12, 12))

    ax1.plot(dA["cycle"], dA["sigma"], marker="o", linewidth=2, label="σ (GP)")
    ax1.set_title(f"{scenario_name} — Incertidumbre σ (GP)")
    ax1.set_ylabel("σ")
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    ax2.plot(dA["cycle"], dA["H"], marker="o", linewidth=2, label="H A_baseline")
    ax2.plot(dB["cycle"], dB["H"], marker="o", linewidth=2, label="H B_optimal")
    ax2.axhline(threshold, linestyle="--", label="threshold")
    ax2.set_title(f"{scenario_name} — Energía H (A vs B)")
    ax2.set_ylabel("H")
    ax2.grid(True, alpha=0.3)
    ax2.legend()

    ax3.plot(dA["cycle"], dA["stress"], marker="o", linewidth=2, label="stress A")
    ax3.plot(dB["cycle"], dB["stress"], marker="o", linewidth=2, label="stress B")
    ax3.set_title(f"{scenario_name} — Stress (0..1)")
    ax3.set_ylabel("stress")
    ax3.set_ylim(-0.05, 1.05)
    ax3.grid(True, alpha=0.3)
    ax3.legend()

    ax4.step(dA["cycle"], dA["eta_prev"], where="post", linewidth=2, label="η A_baseline")
    ax4.step(dB["cycle"], dB["eta_prev"], where="post", linewidth=2, label="η B_optimal")

    a_blk = dA[dA["blocked"]]
    b_blk = dB[dB["blocked"]]
    if not a_blk.empty:
        ax4.scatter(a_blk["cycle"], a_blk["eta_prev"], label="bloqueo A")
    if not b_blk.empty:
        ax4.scatter(b_blk["cycle"], b_blk["eta_prev"], label="bloqueo B")

    ax4.set_title(f"{scenario_name} — η y Bloqueos (A vs B)")
    ax4.set_xlabel("cycle")
    ax4.set_ylabel("η")
    ax4.grid(True, alpha=0.3)
    ax4.legend()

    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    plt.close(fig)


# ==============================================================
# MAIN
# ==============================================================

def main():
    x_isla_1 = np.linspace(0.5, 4.5, 9)
    x_isla_2 = np.linspace(15.0, 21.5, 10)

    X_train = np.atleast_2d(np.concatenate([x_isla_1, x_isla_2])).T
    y_train = np.sin(X_train).ravel()

    gp = GaussianProcessRegressor(kernel=C(1.0) * RBF(1.0), n_restarts_optimizer=10)
    gp.fit(X_train, y_train)

    pd.DataFrame({"x": X_train.ravel(), "y": y_train}).to_csv(
        os.path.join(RESULTS_DIR, "qimeta_ab_train.csv"), index=False
    )

    scenarios = {
        "gap_then_isla2": [3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 15.5, 17.0, 19.0, 20.5],
        "gap_sustained": [6.0, 7.0, 8.0, 9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 12.0, 9.0],
        "isla1_gap_isla2_alternate": [2.0, 8.0, 3.5, 10.0, 4.2, 12.0, 3.0, 15.5, 4.0, 17.0, 4.5],
        "isla2_only": [15.2, 16.0, 17.5, 18.2, 19.0, 20.0, 21.0, 15.8, 16.7, 18.9],
    }

    # hiperparámetros compartidos
    eta_base = 0.7
    lambda_2 = 2.5
    threshold = 0.20
    v_risk = 0.12

    # tuning para evitar colapso a eta_min
    shock_threshold = 0.98
    delta_penal = 0.15
    delta_recup = 0.08
    eta_min = 0.25

    print(f"[debug] threshold={threshold} v_risk={v_risk} "
          f"shock_threshold={shock_threshold} delta_penal={delta_penal} "
          f"delta_recup={delta_recup} eta_min={eta_min}")

    sigma_known = 0.08
    sigma_border = 0.30

    all_dfs = []
    all_summaries = []

    for name, seq in scenarios.items():
        df_all, df_sum = run_sequence_ab(
            name, seq, gp,
            eta_base=eta_base,
            lambda_2=lambda_2,
            threshold=threshold,
            sigma_known=sigma_known,
            sigma_border=sigma_border,
            beta_neg_border=0.20,
            mission_weight_ood=0.0,
            v_risk=v_risk,

            shock_threshold=shock_threshold,
            delta_penal=delta_penal,
            delta_recup=delta_recup,
            eta_min=eta_min,
        )
        all_dfs.append(df_all)
        all_summaries.append(df_sum)

        out_png = os.path.join(RESULTS_DIR, f"qimeta_ab_{name}.png")
        plot_ab(df_all, scenario_name=name, out_png=out_png, threshold=threshold)

    df_all = pd.concat(all_dfs, ignore_index=True)
    df_summary = pd.concat(all_summaries, ignore_index=True)

    df_all.to_csv(os.path.join(RESULTS_DIR, "qimeta_ab_all.csv"), index=False)
    df_summary.to_csv(os.path.join(RESULTS_DIR, "qimeta_ab_summary.csv"), index=False)

    cols = [
        "scenario","engine","n_steps",
        "blocked_total","blocked_rate","blocked_flips","cascade_max",
        "stress_mean","stress_max","shock_events_total",
        "H_start","H_end","delta_H","H_mean","H_sum","H_min","H_max",
        "eta_min","eta_end","recovery_cycles_to_95pct",
        "threshold","v_risk",
        "shock_threshold","delta_penal","delta_recup","eta_min_cfg",
        "B_used_risk_value_steps","B_fallback_steps",
    ]
    df_print = df_summary.sort_values(["scenario", "engine"])[cols]
    print("\n=== RESUMEN A/B: QiMeta (Piecewise) ===")
    print(df_print.to_string(index=False))


if __name__ == "__main__":
    main()
