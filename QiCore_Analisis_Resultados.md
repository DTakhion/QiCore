# QiCore – Análisis de Resultados (Experimento Anti‑Alucinación)

## Contexto del Experimento

Este experimento evalúa el comportamiento de **QiCore** como *capa de control epistemológico* sobre un modelo de lenguaje **local**, sin acceso a web ni RAG, utilizando generación de múltiples candidatos, evaluación energética (Hamiltoniano) y un *gate* de aceptación/bloqueo.

El objetivo es **reducir alucinaciones factuales**, especialmente aquellas donde el modelo declara no tener información pero luego entrega cifras, fechas o fuentes concretas.

---

## Modelo Utilizado

**Runtime / Servidor**
- Ollama (ejecución local)

**Modelo**
- Nombre: `llama3.2:latest`
- Familia: LLaMA
- Tipo: Instruct / Chat
- Tamaño aproximado en disco: **~2.0 GB**
- Arquitectura: Transformer decoder‑only
- Acceso a internet: ❌ No
- RAG / herramientas externas: ❌ No
- Ejecución: 100% local (Apple Silicon M1)

**Implicación clave**  
El modelo **no puede verificar información externa** en tiempo de ejecución. Cualquier cifra o fuente específica proviene de memoria paramétrica y puede ser **inventada** (alucinación).

---

## Configuración de QiCore

### Pipeline
1. Generación de *N* candidatos (temperaturas variadas)
2. Cálculo de energía \(E\) por candidato
3. Selección del candidato con menor energía
4. Gate:
   - Si \(E > THRESH\) → bloqueo / respuesta prudente
   - Si \(E ≤ THRESH\) → respuesta aceptada

### Hamiltoniano (v1.2)

La energía total se define como:

\[
E = e_1 + e_2 + e_3 + e_4 + e_5
\]

Donde:

- **e1 – Overconfidence**  
  Penaliza lenguaje de certeza absoluta (“100%”, “definitivamente”, etc.)

- **e2 – Números riesgosos**  
  Penaliza densidad de números mayores a un umbral (> 12), ignorando valores pequeños usados en definiciones matemáticas.

- **e3 – Falta de hedging con números**  
  Penaliza cifras específicas sin lenguaje de incertidumbre.

- **e4 – Control de forma**  
  Penaliza respuestas demasiado cortas o excesivamente largas.

- **e5 – Contradicción epistemológica (clave)**  
  Penaliza fuertemente cuando el modelo:
  - Declara no tener acceso / información  
  **y**
  - Entrega cifras, porcentajes o fuentes concretas.

Este último término es crucial para detectar **alucinaciones de alta confianza**.

---

## Prompt de Evaluación (Caso Alucinable)

> ¿Cuál fue el porcentaje exacto de desempleo en Chile en 2022 (promedio anual) y cuál fue la fuente?  
> Responde con un número y una fuente concreta.

Este prompt fuerza:
- precisión numérica,
- referencia temporal,
- y una fuente institucional.

---

## Resultados Observados

### Candidato Aceptado (Menor Energía)

- **E = 0.40**
- Reconoce explícitamente no tener la información.
- No entrega porcentaje ni fuente concreta.
- No incurre en contradicción.

**Resultado:**  
Respuesta prudente, honesta, **no alucinada** → aceptada por QiCore.

---

### Candidatos Rechazados (Alta Energía)

Casos con energías **E ≥ 2.2** presentan el patrón:

- Declaración de falta de acceso a información  
- Entrega de:
  - porcentaje exacto (ej. 7.5%)
  - fuente concreta (INE)
- Sin verificación posible

**Activación clara de `e5` (contradicción epistemológica).**

**Resultado:**  
Candidatos descartados automáticamente por QiCore.

---

## Conclusión Técnica

Este experimento demuestra que:

- Los modelos locales **sí pueden alucinar**, aun declarando incertidumbre.
- QiCore **no modifica el modelo base** ni sus pesos.
- QiCore mejora la calidad factual evaluando la **coherencia epistemológica** de la respuesta.
- La reducción de alucinaciones se logra mediante:
  - scoring auditable,
  - reglas explícitas,
  - y control de aceptación/bloqueo.

En particular, la penalización de contradicciones del tipo  
> “no tengo acceso, pero el dato es X según Y”  
resulta altamente efectiva.

---

## Estado del Sistema

- QiCore operativo (Hamiltoniano heurístico v1.2)
- Observabilidad completa (desglose de energía por término)
- Listo para:
  - integrar función de utilidad tanh + piecewise,
  - registrar métricas comparativas,
  - escalar a otros modelos y entornos.

---

**Este documento fue generado como parte de un experimento reproducible en entorno local.**
