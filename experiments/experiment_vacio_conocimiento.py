# experiments/experiment_vacio_conocimiento.py

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C

from services.qicore_engine import QiCoreEngine


# ==============================================================
# Experimento: Vacío de Conocimiento / Alucinación
# ==============================================================

# 0. Asegurar carpeta de resultados
RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# 1. Datos conocidos por la IA (entrenamiento)
X_train = np.atleast_2d([0.5, 1.2, 2.8, 3.5, 4.8]).T
y_train = np.sin(X_train).ravel()

# 2. Proceso Gaussiano para estimar incertidumbre Σ(A)
kernel = C(1.0) * RBF(1.0)
gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=10)
gp.fit(X_train, y_train)

# 3. Espacio de prueba: conocido + desconocido
X_test = np.linspace(0, 15, 200).reshape(-1, 1)
mu, sigma = gp.predict(X_test, return_std=True)

# 4. Instancia del motor QiCore
qicore = QiCoreEngine(eta=0.4, lambda_2=2.5)

# 5. Evaluación hamiltoniana
results = []
for i in range(len(X_test)):
    h_val, sigma_cost = qicore.hamiltonian_energy(
        utility=float(mu[i]),
        uncertainty=float(sigma[i])
    )

    status = "BLOQUEADO (Alucinación)" if h_val > qicore.threshold else "SEGURO"

    results.append([
        float(X_test[i][0]),
        float(mu[i]),
        float(sigma[i]),
        float(h_val),
        status
    ])

# 6. Resultados en DataFrame
df_results = pd.DataFrame(
    results,
    columns=[
        "Input",
        "Prediccion_IA",
        "Incertidumbre_Sigma",
        "Energia_H",
        "Estado"
    ]
)

# 7. Guardar resultados tabulares
csv_path = os.path.join(RESULTS_DIR, "experiment_vacio_conocimiento.csv")
df_results.to_csv(csv_path, index=False)
print(f"Resultados CSV guardados en: {csv_path}")

# (Opcional) Guardar en parquet (más eficiente)
# parquet_path = os.path.join(RESULTS_DIR, "experiment_vacio_conocimiento.parquet")
# df_results.to_parquet(parquet_path, index=False)
# print(f"Resultados Parquet guardados en: {parquet_path}")


# ==============================================================
# 8. Gráficas
# ==============================================================

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))

# --- GRÁFICA 1: comportamiento del modelo + incertidumbre ---
ax1.plot(X_train, y_train, 'ro', label='Datos Reales (Entrenamiento)')
ax1.plot(X_test, mu, 'b--', label='Predicción (media) μ(x)')

ax1.fill_between(
    X_test.flatten(),
    (mu - 1.96 * sigma),
    (mu + 1.96 * sigma),
    alpha=0.2,
    label='Incertidumbre Epistémica (≈95%)'
)

ax1.axvspan(5, 15, alpha=0.1, label='Zona de Extrapolación (potencial alucinación)')
ax1.set_title("QiSim - Incertidumbre en el Espacio de Acción")
ax1.legend()
ax1.grid(True, alpha=0.3)

# --- GRÁFICA 2: filtro hamiltoniano ---
H = df_results["Energia_H"].to_numpy()
ax2.plot(X_test, H, linewidth=2, label='Energía Hamiltoniana H(x)')
ax2.axhline(y=qicore.threshold, linestyle='--', label=f'Umbral QiCore = {qicore.threshold}')

baseline = float(min(-2.0, H.min()))
ax2.fill_between(
    X_test.flatten(),
    baseline,
    H,
    where=(H > qicore.threshold),
    alpha=0.3,
    label='BLOQUEADO'
)

ax2.set_ylabel("Energía H")
ax2.set_xlabel("Input (extrapolación)")
ax2.set_title("QiOpt - Bloqueo por Energía")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()

# Guardar figura en results/
png_path = os.path.join(RESULTS_DIR, "experiment_vacio_conocimiento.png")
plt.savefig(png_path, dpi=200)
print(f"Figura guardada en: {png_path}")

# Mostrar figura (opcional; útil en local)
plt.show()


# ==============================================================
# 9. Tabla resumen (muestra reproducible)
# ==============================================================

sample = df_results.iloc[[10, 50, 150, 190]]
sample_path = os.path.join(RESULTS_DIR, "experiment_vacio_conocimiento_sample.txt")

with open(sample_path, "w", encoding="utf-8") as f:
    f.write(sample.to_string(index=False))

print(f"Muestra guardada en: {sample_path}")

print("\n" + "=" * 60)
print(" COMPARATIVA DE INTEGRIDAD: IA TRADICIONAL VS QICORE v2.1")
print("=" * 60)
print(sample.to_string(index=False))
print("=" * 60)
print("NOTA: En este demo, cuando H > threshold, QiCore marca el punto como 'BLOQUEADO'.")
