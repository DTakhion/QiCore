# QiCore – Auditoría de Antifragilidad (QiMeta v2.1)

**La utilidad no puede ser una señal universal. Su interpretación depende del régimen, del dominio y del contexto.**

Este repositorio contiene una auditoría experimental del motor **QiCore v2.1**, enfocado en la detección y mitigación de **alucinaciones** mediante un criterio hamiltoniano y un mecanismo de **memoria adaptativa (QiMeta)**.

El objetivo no es optimizar predicción, sino **evaluar robustez, estabilidad y posibles fallas estructurales** del enfoque bajo distintos escenarios de stress.

---

## Marco Conceptual

El motor QiCore utiliza un **Hamiltoniano de decisión**:

\[
H(A) = -U(A) + \lambda_1(\eta)\,V_{risk} + \lambda_2\,\Sigma(A)
\]

donde:

- **U(A)**: utilidad (misión) de la acción  
- **V\_{risk}**: riesgo basal  
- **Σ(A)**: incertidumbre epistémica (estimada con Gaussian Process)  
- **η**: tolerancia dinámica al riesgo (QiMeta)  
- **λ₁ = 1/η**: sensibilidad al riesgo  
- **λ₂**: peso de la incertidumbre  

Una acción se **bloquea** si `H(A) > threshold`.

---

## QiMeta: Memoria y Adaptación

QiMeta introduce una **memoria jerárquica**:

- **Memoria rápida** (`η(t)`): responde a eventos recientes  
- **Memoria lenta** (`η_base`): línea base de estabilidad  

Regla de actualización (simplificada):

- Si se detecta bloqueo, entonces **η disminuye bruscamente** (modo defensivo)
- Si no hay bloqueo, entonces **η se recupera lentamente** hacia `η_base`

Esto implementa un mecanismo de **antifragilidad defensiva**, no aprendizaje estadístico.

---

## Stress Tests Ejecutados

Se evaluaron cuatro escenarios con 10 interacciones secuenciales cada uno:

| Escenario | Descripción |
|---------|------------|
| **A_normal** | Inputs dentro del dominio conocido |
| **B_shock** | Inputs completamente fuera de dominio |
| **C_shock_return** | Shock seguido de retorno a zona segura |
| **D_alternate** | Alternancia entre seguro y fuera de dominio |

---

## Resultados Resumidos

=== RESUMEN STRESS TESTS (QiMeta) ===
scenario n_steps blocked_total cascade_max recovery_cycles_to_95pct collateral_blocks_safe_zone eta_min eta_end
A_normal 10 2 1 None 2 0.1 0.15
B_shock 10 10 10 None 0 0.1 0.10
C_shock_return 10 4 3 None 1 0.1 0.20
D_alternate 10 6 3 None 1 0.1 0.10

---

## Análisis Crítico

### Comportamiento Esperado
- **B_shock**: bloqueo total y sostenido. Correcto para un modo defensivo.
- **C_shock_return**: el sistema logra desbloquear al volver a zona conocida, aunque con recuperación lenta.

### Hallazgos Críticos
- **A_normal** presenta bloqueos dentro de zona segura.
- Existen **bloqueos colaterales** (`collateral_blocks_safe_zone > 0`).
- El sistema puede terminar con **η muy bajo incluso sin ataque sostenido**.

Esto indica que QiMeta puede transformarse en una **trampa defensiva**, no solo en una virtud.

---

## Causa Raíz Identificada

El término de utilidad fue definido como:

U(A) = μ

Dado que `μ` puede ser negativo (por ejemplo, `sin(x)`), el término `-U(A)` se vuelve positivo y **empuja artificialmente el Hamiltoniano hacia el bloqueo**, incluso con baja incertidumbre.

En consecuencia:
- El sistema puede bloquear por “misión” mal definida, no por alucinación real.
- QiMeta reacciona a sus propias decisiones, reforzando el endurecimiento.

---

## Recomendaciones de Corrección 

1. **Redefinir U(A)**  
   Ejemplos:
   - `U = -abs(μ)`
   - `U =tanh(U)`
   - otras.

2. **Feedback continuo en QiMeta**
   - Reemplazar error binario por:
     ```
     error = clip((H - threshold)/threshold, 0, 1)
     ```
   - o basarlo directamente en Σ(A)

3. **Aumentar ventana de recuperación**
   - Evaluar escenarios largos para validar retorno a `η_base`

---

## Conclusión

QiCore + QiMeta implementa correctamente un **mecanismo de defensa adaptativa** frente a incertidumbre extrema.  
Sin embargo, en su forma actual:

> **La memoria puede ser una virtud… o una trampa.**

Sin una definición cuidadosa de la utilidad y del feedback de error, el sistema puede volverse **excesivamente conservador**, bloqueando incluso en condiciones normales.

> No existe una utilidad escalar universal que funcione:
para todos los signos,
todos los dominios,
todos los regímenes,
todos los contextos.
Ni U, ni |U|, ni tanh(U).
Es una propiedad del problema.
La utilidad no es física, es semántica.

> A pesar del cambio de la función de misión, por tangente hipérbólica, se presetan falsos negativos. Por ello, se estructuro a la función Hamiltoniana como una función del tipo piecewise con ranfos estadísticos en función del modelo GP. 

---

# Auditoría QiMeta v2.1 — Islas de Conocimiento y Vacíos Estructurales

## Contexto del Experimento

Se evalúa el comportamiento del motor **QiCore + QiMeta** bajo escenarios donde el conocimiento del modelo no es continuo, sino que se organiza en **islas disjuntas**, separadas por vacíos de conocimiento real.

El objetivo es analizar si el mecanismo de:
- Energía Hamiltoniana `H(A)`
- Memoria adaptativa `η` (QiMeta)

logra distinguir entre:
- Incertidumbre legítima (vacíos)
- Reingreso a regiones conocidas
- Fragmentación estructural del dominio

---

## Escenarios Evaluados

### 1. `gap_then_isla2`
**Secuencia**:  
Isla 1 → Vacío → Isla 2

**Resultados**:
- Bloqueos: 2
- Cascada máxima: 1
- η final: 0.20

**Análisis**:
El sistema bloquea correctamente durante el vacío.  
Al ingresar a la segunda isla (con baja incertidumbre), la energía se normaliza y QiMeta inicia una recuperación parcial.

Comportamiento aceptable  
Recuperación dependiente de que el vacío sea breve

---

### 2. `gap_sustained`
**Secuencia**:  
Isla → Vacío prolongado

**Resultados**:
- Bloqueos: 2
- Cascada máxima: 2
- η final: 0.35

**Análisis**:
El sistema entra en modo defensivo sostenido.  
Aunque no colapsa completamente, **η queda deprimido**, mostrando un sesgo de memoria hacia el vacío.

Penalización acumulativa  
Recuperación incompleta aun sin nueva evidencia de riesgo

---

### 3. `isla1_gap_isla2_alternate` **ESCENARIO CRÍTICO**
**Secuencia**:  
Isla 1 ↔ Vacío ↔ Isla 2 ↔ Vacío (alternado)

**Resultados**:
- Bloqueos: 6
- Cascada máxima: 3
- η final: 0.10 (mínimo)

**Análisis**:
Este escenario induce un **colapso sistémico** del mecanismo QiMeta.

Cada reingreso al vacío reactiva la penalización, sin permitir una recuperación suficiente en las islas conocidas.  
El sistema queda **hiperconservador**, bloqueando incluso en regiones con conocimiento real.

**Fallo estructural**:
QiMeta confunde fragmentación del dominio con riesgo persistente.

---

### 4. `isla2_only` (Control)
**Secuencia**:  
Solo una isla conocida

**Resultados**:
- Bloqueos: 1
- η final: 0.65

**Análisis**:
Comportamiento estable y deseado:
- Incertidumbre casi nula
- Energía controlada
- Recuperación efectiva de η

Demuestra que el problema no es QiMeta aislado  
El fallo emerge solo con discontinuidad del dominio

---

## Conclusión General de Auditoría

En presencia de **islas de conocimiento separadas por vacíos estructurales**, el mecanismo QiMeta:

- Penaliza por historial, no por contexto
- No distingue entre transición legítima y permanencia en incertidumbre
- Acumula memoria defensiva sin noción de topología del dominio

### Formulación clave

> **QiMeta aprende a temer al espacio, no al error.**

O en términos más formales:

> **La memoria adaptativa induce conservadurismo patológico bajo fragmentación del dominio, afectando decisiones posteriores incluso en regiones conocidas.**

---

## Implicancia Sistémica

Este fallo **no depende de**:
- Gaussian Process
- Valor específico del threshold
- Un caso puntual de U(A)

Es un **problema emergente de memoria + energía + dominio disjunto**.
