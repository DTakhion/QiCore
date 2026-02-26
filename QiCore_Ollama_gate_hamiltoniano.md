# QiCore + Ollama: Explicación resumida del Gate Hamiltoniano

Este script implementa un **gate post–generación** para modelos LLM (vía Ollama) usando un **Hamiltoniano de QiCore** como función de decisión.

La idea central es:  
👉 *el modelo puede generar muchas respuestas, pero QiCore decide cuál es aceptable (o si ninguna lo es).*  

---

## Flujo completo (en 6 pasos)

### 1. Generación de candidatos (Ollama)
- Ollama genera **N respuestas** al mismo prompt.
- Se varía `temperature` y `seed` para obtener diversidad.
- Resultado: una lista de textos candidatos.

---

### 2. Extracción de señales desde el texto
Cada texto se analiza con reglas heurísticas (`extract_features`), por ejemplo:
- ¿Menciona “según…” o “fuente:” **sin enlace**?
- ¿Mezcla organismos de forma sospechosa?
- ¿Usa números grandes con falsa precisión?
- ¿Habla con exceso de confianza (“100%”, “sin duda”)?
- ¿Incluye disclaimers coherentes (“no tengo acceso a…”)?

Estas señales son **auditables** y quedan guardadas.

---

### 3. Mapeo texto → (mu, sigma, v_risk)
Las señales se convierten en tres variables tipo GP:

- **mu (μ)** → utilidad / calidad esperada  
  - Sube con prudencia real.
  - Baja con sobreconfianza, contradicciones o “fuentes inventadas”.

- **sigma (σ)** → incertidumbre epistemológica  
  - Sube fuerte cuando hay indicios de alucinación.
  - Representa “qué tan fuera del conocimiento confiable estoy”.

- **v_risk** → riesgo base  
  - Penaliza precisión numérica riesgosa, contradicciones y patrones sospechosos.

---

### 4. Evaluación del Hamiltoniano
Con `(mu, sigma, v_risk)` se evalúa:

\[
H = term\_mission + \lambda_1 \cdot V_{risk} + \lambda_2 \cdot \sigma
\]

Donde:
- `term_mission` depende de `U = tanh(mu)` y del régimen:
  - **known**: no se penaliza utilidad negativa.
  - **border**: penalización amortiguada.
  - **ood**: manda la incertidumbre.
- `λ1 = 1/(eta + eps)`
- `λ2` penaliza incertidumbre epistemológica.

Resultado: **una energía H por candidato**.

---

### 5. Selección del mejor candidato
- Se ordenan los candidatos por **H ascendente**.
- El de menor energía es el “mejor” según QiCore.

---

### 6. Gate final (bloqueo o paso)
- Si `H > threshold` → **BLOQUEO**
  - Se devuelve una respuesta segura del tipo:
    > “No tengo evidencia suficiente para responder con confianza…”
- Si `H ≤ threshold` → **SE ACEPTA**
  - Se imprime la respuesta seleccionada.

---

## Intuición clave

- **Ollama explora** el espacio de respuestas.
- **QiCore controla** qué respuestas son confiables.
- El Hamiltoniano actúa como un **filtro energético**:
  - baja energía → respuesta aceptable,
  - alta energía → riesgo de alucinación → bloqueo.

---

## Por qué esto es auditable
- Cada decisión queda descompuesta en:
  - `term_mission`
  - `term_risk`
  - `term_uncertainty`
- Se guarda `H`, `threshold`, régimen y señales textuales.
- Permite mostrar **por qué** una respuesta fue aceptada o bloqueada.

---

**Resumen en una frase:**  
> *QiCore no evita que el LLM genere errores; evita que esos errores salgan al usuario.*
