# Resumen de Auditoría Técnica – QiCore v3.0 (Primera Revisión)

## Contexto General

La nueva versión de QiCore (v3.0) se fundamenta principalmente en el trabajo de Tindall et al. (2026), específicamente en dos componentes matemáticos centrales:

1. **Tensor Networks (TN)**: mecanismo de representación comprimida de estados complejos mediante tensores locales conectados sobre un grafo.
2. **Belief Propagation (BP)**: algoritmo de propagación de mensajes utilizado para actualizar información local y aproximar correlaciones globales.

La propuesta de QiCore consiste en transferir estos conceptos desde el dominio de simulación cuántica hacia problemas industriales de optimización, logística, ciberseguridad OT, ciencia de materiales y compresión de redes neuronales.

---

# 1. Restricciones Fundamentales del Método TN-BP

El resultado de Tindall NO es universal.

Su aplicabilidad depende de que el problema satisfaga ciertas condiciones estructurales:

### P1. Grafo conocido y estable

La topología del problema debe poder representarse mediante un grafo bien definido:

\[
G = (V,E)
\]

donde:

- \(V\) = conjunto de nodos
- \(E\) = conjunto de conexiones

---

### P2. Entrelazamiento acotado

La complejidad del sistema está controlada por la dimensión de enlace:

\[
\chi
\]

(*bond dimension*)

La eficiencia del método depende críticamente de que \(\chi\) permanezca acotado.

---

### P3. Interacciones locales

El método funciona mejor cuando:

- el grado de cada nodo es moderado,
- las dependencias son locales,
- existen pocos loops pequeños altamente correlacionados.

Grafos densos o con dependencias globales degradan el rendimiento de BP.

---

### P4. Observables locales o semi-locales

Las correlaciones locales pueden calcularse eficientemente.

Funciones globales arbitrarias pueden requerir recursos exponenciales.

---

# 2. Representación Tensorial

El estado del sistema se representa mediante una red tensorial:

\[
|\Psi\rangle =
\sum_{\{s\}}
C(\{s\})
\prod_{i\in V}
A^{[i]}_{s_i}
\]

donde:

- \(A^{[i]}\) es el tensor local del nodo \(i\),
- \(d_i\) es el grado del nodo,
- \(\chi\) es la bond dimension.

---

## Interpretación

La idea NO es simplemente factorizar un vector de características.

La red tensorial intenta representar un estado global complejo mediante componentes locales conectadas, evitando almacenar explícitamente todas las combinaciones posibles del sistema.

---

# 3. Complejidad Espacial

La proposición presentada indica:

\[
O(N \cdot d_{phys} \cdot \chi^{d\cdot z/2})
\]

Para los casos estudiados:

\[
O(N\chi^4)
\]

---

## Observación Importante

La complejidad NO depende solamente de \(N\).

Depende simultáneamente de:

\[
N
\]

y

\[
\chi
\]

Por tanto, la afirmación de "escalabilidad lineal" debe interpretarse como:

> Lineal en \(N\) para valores de \(\chi\) controlados.

Si \(\chi\) crece significativamente, la ventaja computacional puede desaparecer.

---

# 4. Propagación de Creencias (BP)

La actualización de mensajes se realiza mediante:

\[
M_{i\rightarrow j}(x_j)
\propto
\sum_{x_i}
\psi_i(x_i)
\phi_{ij}(x_i,x_j)
\prod_{k\in\partial i\setminus j}
M_{k\rightarrow i}(x_i)
\]

---

## Interpretación

Cada nodo actualiza el mensaje enviado a sus vecinos utilizando:

- su información local,
- la interacción con el vecino objetivo,
- los mensajes recibidos desde el resto de sus vecinos.

BP es el mecanismo de evolución principal de QiCore.

---

# 5. Error de Correlación Cruzada

La precisión se mide mediante:

\[
\epsilon_c
=
\sqrt{
\frac{
\sum_{i>j}
(c_{ij}-\tilde c_{ij})^2
}{
\sum_{i>j}
\tilde c_{ij}^2
}
}
\]

donde:

- \(c_{ij}\) es la correlación estimada por TN,
- \(\tilde c_{ij}\) es la referencia exacta.

---

## Observación

Esta métrica mide:

> Precisión de la aproximación.

No mide directamente:

> Convergencia del algoritmo BP.

La estrategia de convergencia sigue siendo una pregunta abierta para la auditoría.

---

# 6. Hamiltoniano de Decisión de QiCore

La función objetivo principal es:

\[
H_G(A)
=
-U_G(A)
+
\lambda(\chi)V^{TN}_{risk}(A)
+
\beta ||A-A_{prev}||^2
\]

---

## Componentes

### Utilidad

\[
-U_G(A)
\]

Busca maximizar el beneficio o desempeño del sistema.

---

### Riesgo Tensorial

\[
\lambda(\chi)V^{TN}_{risk}(A)
\]

Introduce una penalización asociada al riesgo estimado mediante TN.

Todavía no existe una definición completamente clara de:

\[
V^{TN}_{risk}
\]

por lo que sigue siendo un punto relevante para futuras auditorías.

---

### Inercia

\[
\beta ||A-A_{prev}||^2
\]

Penaliza cambios excesivos respecto al estado anterior.

Su objetivo es evitar decisiones demasiado agresivas o inestables.

---

# 7. Invariantes Arquitectónicas

QiCore introduce tres invariantes fundamentales que actúan como mecanismos de autocontrol y validación. Ningún módulo TN-BP debe ejecutarse fuera de estas condiciones.

---

## I1. Honestidad de Grafo

Antes de ejecutar cualquier proceso TN-BP, el sistema debe verificar que la complejidad requerida del problema sea compatible con la capacidad máxima configurada:

\[
\chi_{req}(\epsilon_{target})
\le
\chi_{max}
\]

donde:

- \(\chi_{req}\): bond dimension requerida para alcanzar el error objetivo.
- \(\epsilon_{target}\): error máximo tolerable por la aplicación.
- \(\chi_{max}\): bond dimension máxima permitida por restricciones de hardware, tiempo o configuración.

### Interpretación

Antes de resolver el problema, QiCore debe responder:

> "¿Puedo representar este problema con suficiente precisión utilizando TN-BP?"

Si la respuesta es negativa, el algoritmo no debe continuar utilizando el núcleo tensorial.

### Preguntas abiertas de auditoría

- ¿Cómo se estima exactamente \(\chi_{req}\)?
- ¿Qué tan precisa es dicha estimación?
- ¿Cómo se determina \(\chi_{max}\) para cada aplicación?

---

## I2. Trazabilidad de Error

Todo resultado generado por QiCore debe incluir explícitamente una estimación de error:

\[
\epsilon_c
\]

y además reportar:

\[
n_{dis}
\]

donde:

- \(\epsilon_c\): error de correlación cruzada estimado.
- \(n_{dis}\): número de realizaciones de desorden o escenarios evaluados.

### Interpretación

QiCore no sólo entrega una respuesta, sino también una estimación cuantitativa de la confianza asociada al resultado.

La intención es evitar resultados "caja negra" sin métricas de calidad.

### Observación

\(\epsilon_c\) mide precisión respecto de una referencia, pero no constituye por sí mismo una métrica de convergencia del algoritmo BP.

---

## I3. Degradación Graceful

Si el problema excede la complejidad que el sistema puede representar:

\[
\chi_{req}
>
\chi_{max}
\]

el núcleo TN-BP debe detenerse y transferir la resolución a un método alternativo.

### Interpretación

QiCore debe evitar operar fuera de su dominio de validez.

En lugar de producir resultados potencialmente incorrectos o perder estabilidad, el sistema debe:

1. Detectar la violación de la condición.
2. Reportar explícitamente la situación.
3. Activar un solucionador alternativo (*fallback solver*).

### Objetivo

Garantizar que el sistema:

- no falle silenciosamente,
- no entregue resultados sin respaldo,
- mantenga continuidad operacional aun cuando TN-BP deje de ser aplicable.

---

# 8. Análisis de la Arquitectura QiCore v3.0

## Vista General

La arquitectura propuesta por QiCore v3.0 puede interpretarse como una cadena de transformación que convierte información de entrada (sensores, datos o eventos) en una decisión optimizada mediante un núcleo tensorial TN-BP supervisado continuamente por mecanismos de validación y control de calidad.

De forma conceptual:

```text
Entrada / Sensores
        │
        ▼
L1 ─ QiPerception
        │
        ▼
     Grafo G
        │
        ▼
┌─────────────────────┐
│ Núcleo TN-BP        │
│ H_G(A)              │
│ χ-manager           │
└─────────────────────┘
        │
        ▼
L2 ─ QiEvolution
        │
        ▼
L3 ─ QiMeasure
        │
        ▼
L4 ─ QiDecide
        │
        ▼
      Acción A*
```

y transversalmente:

```text
         L5 ─ QiAudit
     (monitoreo continuo)
```

---

# L1 — QiPerception

## Objetivo

Transformar las entradas del problema en una representación de grafo compatible con TN-BP.

El documento define esta capa como:

```text
Mapeo sensor → grafo G
```

---

## Función conceptual

```text
Sensores
Datos
Eventos
Variables

        ↓

Representación estructurada

        ↓

Grafo G=(V,E)
```

---

## Observación de Auditoría

Esta capa representa uno de los puntos más críticos de toda la arquitectura.

El trabajo de Tindall parte de grafos ya definidos.

QiCore, en cambio, parte desde datos de entrada y debe construir dicho grafo.

Por tanto, la calidad de la representación del problema depende directamente de esta etapa.

---

## Preguntas abiertas

- ¿Cómo se construye exactamente el grafo?
- ¿Qué criterios determinan nodos y aristas?
- ¿Cómo se preservan las propiedades necesarias para TN-BP?
- ¿Cómo se estima χreq durante esta etapa?

---

# Núcleo TN-BP

## Componentes

El diagrama identifica tres componentes centrales:

```text
TN-BP
H_G(A)
χ-manager
```

---

## Función

Representa el corazón matemático de QiCore.

Integra:

- Redes Tensoriales (TN)
- Propagación de Creencias (BP)
- Hamiltoniano de Decisión
- Gestión de complejidad tensorial (χ)

---

# χ-manager

## Interpretación

Aunque el documento no lo define explícitamente, el diagrama sugiere que esta componente es responsable de gestionar la complejidad tensorial del problema.

Su función probable consiste en controlar:

```text
χreq
χused
χmax
```

---

## Funciones esperadas

### Validación

Verificar:

\[
\chi_{req}
\le
\chi_{max}
\]

---

### Ajuste dinámico

Incrementar χ cuando:

\[
\epsilon_c
>
\epsilon_{target}
\]

siempre que:

\[
\chi
<
\chi_{max}
\]

---

### Activación de fallback

Cuando:

\[
\chi_{req}
>
\chi_{max}
\]

activar degradación graceful.

---

## Observación

Actualmente χ-manager parece ser una de las piezas más relevantes de la arquitectura y una de las menos detalladas en el documento.

---

> **Observación de Auditoría – Estimación de χreq**
>
> La capa L1 (QiPerception) incorpora una funcionalidad adicional no descrita previamente en detalle: la estimación de la bond dimension requerida ((\chi_{req})).
>
> El documento indica que dicha estimación se realiza mediante una **heurística de entropía de entrelazamiento de corte**, haciendo referencia a la bibliografía asociada. Sin embargo, hasta este punto del documento no se especifica:
>
> * la definición operacional de "entropía de entrelazamiento" para problemas industriales;
> * la metodología exacta de cálculo;
> * la relación matemática utilizada para transformar dicha entropía en una estimación de (\chi_{req});
> * ni los criterios de validación de esta heurística.
>
> Dado que la condición:
>
> [
> \chi_{req} \le \chi_{max}
> ]
>
> constituye la Invariante I1 y determina si el núcleo TN-BP puede ejecutarse o debe activarse el mecanismo de degradación graceful (Invariante I3), la estimación de (\chi_{req}) representa actualmente uno de los puntos críticos de la arquitectura y uno de los principales focos de auditoría técnica.
>
> Con la información disponible hasta esta sección, el flujo lógico parece ser:
>
> ```text
> L1 ─ QiPerception
>       │
>       ├── χreq ≤ χmax
>       │        ↓
>       │      L2 ─ QiEvolution
>       │
>       └── χreq > χmax
>                ↓
>             L5 ─ QiAudit
>                ↓
>         Fallback Solver
> ```
>
> No obstante, el documento aún no detalla cómo se implementa internamente esta transición ni qué criterios específicos utiliza el sistema para seleccionar el solucionador alternativo.

---

# L2 — QiEvolution

## Objetivo

Realizar la evolución del estado tensorial.

Implementa:

```text
BP simple update
+
Trotterización
```

---

## Función conceptual

```text
Grafo
    ↓
Belief Propagation
    ↓
Estado Tensorial Actualizado
```

---

## Relación con Tindall

Esta es probablemente la capa más directamente heredada del formalismo TN-BP utilizado en los experimentos originales de Tindall et al.

---

> **Observación de Auditoría – L2 (QiEvolution)**
>
> La capa L2 implementa el mecanismo de evolución principal del sistema mediante:
>
> * Propagación de Creencias (BP) utilizando la actualización definida en la Ecuación (2).
> * Trotterización de segundo orden para aproximar la evolución dinámica del estado tensorial.
>
> Un aspecto relevante es que el documento indica que:
>
> > "χ se aumenta iterativamente hasta χmax con truncación SVD controlada."
>
> Esto sugiere que la ejecución no necesariamente ocurre con un valor fijo de (\chi), sino que existe un proceso adaptativo donde la bond dimension puede incrementarse progresivamente hasta alcanzar la precisión requerida o el límite máximo permitido.
>
> Conceptualmente:
>
> ```text
> χ inicial
>      ↓
> Evolución BP
>      ↓
> Evaluación de error
>      ↓
> ¿Precisión suficiente?
>      │
>      ├── Sí → continuar
>      │
>      └── No → aumentar χ
>                   ↓
>              repetir proceso
> ```
>
> ---
>
> ### Complejidad Computacional
>
> El documento reporta una latencia:
>
> [
> O(N\chi^4 d_{phys})
> ]
>
> donde:
>
> * (N): número de nodos o variables del problema.
> * (\chi): bond dimension utilizada durante la evolución.
> * (d_{phys}): dimensión física local del sistema.
>
> ---
>
> ### Observación Importante
>
> La afirmación de escalabilidad lineal debe interpretarse con cautela.
>
> La complejidad no depende únicamente de (N), sino también de:
>
> [
> \chi
> ]
>
> y potencialmente de:
>
> [
> n_{dis}
> ]
>
> cuando múltiples realizaciones de desorden o escenarios deben evaluarse.
>
> Por tanto, una interpretación más precisa sería:
>
> > La complejidad escala linealmente respecto de (N) únicamente cuando (\chi) permanece acotado y el número de realizaciones de desorden se mantiene controlado.
>
> Si (\chi) crece significativamente para alcanzar el error objetivo, la complejidad efectiva puede aumentar de forma considerable.
>
> ---
>
> ### Preguntas abiertas de auditoría
>
> * ¿Qué criterio determina cuándo incrementar (\chi)?
> * ¿Cómo se relaciona (\epsilon_c) con dicho incremento?
> * ¿Cuántas iteraciones típicas de ajuste de (\chi) requiere el sistema?
> * ¿Cómo impacta (n_{dis}) en la latencia final reportada?
> * ¿La complejidad reportada corresponde a una sola evolución BP o al ciclo completo hasta convergencia?

---

# L3 — QiMeasure

## Objetivo

Extraer observables y métricas desde el estado tensorial evolucionado.

Implementa:

```text
MPS Message Passing
Loop-BP
```

---

## Función conceptual

```text
Estado Tensorial
        ↓
Observación
        ↓
Correlaciones
Métricas
Observables
```

---

## Resultado

Produce cantidades como:

\[
c_{ij}
\]

que posteriormente son utilizadas para la toma de decisiones.

---

## Interpretación

Esta capa no optimiza ni decide.

Su función consiste exclusivamente en medir.

---

> **Observación de Auditoría – L3 (QiMeasure)**
>
> La capa L3 tiene como objetivo extraer observables y métricas desde el estado tensorial generado por L2.
>
> Para ello, el documento indica el uso de:
>
> * MPS Message Passing para lattices cilíndricos.
> * Loop-Corrected Belief Propagation para lattices 3D.
> * Registro continuo de (\epsilon_c).
>
> ---
>
> ### Dependencia de Geometrías Específicas
>
> Un aspecto relevante es que los mecanismos de medición descritos continúan haciendo referencia explícita a estructuras utilizadas en el trabajo de Tindall:
>
> ```text
> Lattices 2D
> Lattices cilíndricos
> Lattices 3D
> ```
>
> Estas geometrías poseen propiedades altamente estructuradas:
>
> * conectividad local,
> * grado de nodo acotado,
> * regularidad topológica,
> * correlaciones de corto alcance.
>
> ---
>
> ### Observación de Transferibilidad
>
> Muchos problemas industriales reales presentan características diferentes:
>
> * grafos irregulares,
> * hubs altamente conectados,
> * dependencias globales,
> * estructuras dinámicas,
> * topologías no estacionarias.
>
> Por tanto, aunque la metodología de medición se encuentra respaldada para los casos estudiados por Tindall, la capacidad de generalizar estos mecanismos hacia problemas empresariales arbitrarios sigue siendo una cuestión abierta.
>
> ---
>
> ### Complejidad Reportada
>
> El documento indica una complejidad:
>
> [
> O(N^2\chi^8)
> ]
>
> para el cálculo de todos los correladores mediante MPS Message Passing.
>
> Esta complejidad es significativamente mayor que la complejidad de evolución reportada en L2:
>
> [
> O(N\chi^4 d_{phys})
> ]
>
> lo que sugiere que la etapa de medición podría transformarse en un cuello de botella para problemas de gran tamaño.
>
> ---
>
> ### Preguntas abiertas de auditoría
>
> * ¿Cómo se adapta QiMeasure a grafos no regulares?
> * ¿Cómo se realiza la medición cuando la topología no corresponde a un lattice?
> * ¿Qué observables industriales equivalen a los correladores físicos (c_{ij})?
> * ¿La complejidad reportada corresponde a casos reales o únicamente a las geometrías analizadas por Tindall?
> * ¿Cómo impacta el crecimiento de (\chi) sobre el costo final de medición?
>
> ---
>
> ### Conclusión preliminar
>
> L3 parece mantener una dependencia conceptual fuerte respecto de los escenarios físicos originales utilizados para validar TN-BP. En consecuencia, esta capa constituye otro punto crítico de la auditoría, ya que la validez de sus métricas en dominios industriales aún requiere justificación teórica y validación empírica independiente.

---

# L4 — QiDecide

## Objetivo

Tomar la decisión final utilizando la información producida por L3.

Implementa:

\[
A^*
=
\arg\min H_G(A)
\]

---

## Función conceptual

```text
Observables
      ↓
Hamiltoniano
      ↓
Optimización
      ↓
Acción Óptima
```

---

## Observación

Esta separación entre:

```text
Inferencia
```

y

```text
Decisión
```

representa una arquitectura limpia y modular.

---

> **Observación de Auditoría – L4 (QiDecide)**
>
> Esta sección no introduce nuevos elementos matemáticos respecto de los ya definidos anteriormente.
>
> Sin embargo, explicita una dependencia importante dentro de la arquitectura:
>
> ```text
> L2 ─ QiEvolution
>          ↓
> L3 ─ QiMeasure
>          ↓
> L4 ─ QiDecide
> ```
>
> En particular, el Hamiltoniano de decisión:
>
> [
> H_G(A)
> ======
>
> -U_G(A)
> +
> \lambda(\chi)V^{TN}*{risk}(A)
> +
> \beta ||A-A*{prev}||^2
> ]
>
> no opera directamente sobre el estado tensorial generado por L2, sino sobre los observables y correlaciones extraídos por L3 (QiMeasure).
>
> Conceptualmente:
>
> ```text
> Estado Tensorial
>         ↓
> Observables
>         ↓
> Hamiltoniano
>         ↓
> Acción Óptima
> ```
>
> Esto refuerza la separación arquitectónica entre:
>
> * Evolución del sistema (L2),
> * Medición de observables (L3),
> * Toma de decisiones (L4).
>
> Asimismo, la sección confirma que la Invariante I3 puede activarse no sólo por una violación de:
>
> [
> \chi_{req}
>
> >
>
> \chi_{max}
> ]
>
> sino también cuando:
>
> [
> \epsilon_c
>
> >
>
> \epsilon_{target}
> ]
>
> obligando al sistema a abandonar el núcleo TN-BP y activar explícitamente un solucionador alternativo (*fallback solver*).

---

# L5 — QiAudit

## Objetivo

Supervisar continuamente el funcionamiento de todo el sistema.

A diferencia de las demás capas, no forma parte del flujo principal de procesamiento.

Opera transversalmente sobre toda la arquitectura.

---

## Variables monitoreadas

Según el documento:

- \(\epsilon_c\)
- \(\chi_{used}/\chi_{max}\)
- Tiempo de ejecución
- Cumplimiento de P1–P4

---

## Función conceptual

```text
Control de Calidad
+
Control de Dominio de Validez
+
Supervisión de Recursos
```

---

## Interpretación

QiAudit funciona como un observador permanente encargado de garantizar que QiCore opere dentro de los límites para los cuales sus resultados son considerados confiables.

---

> **Observación de Auditoría – L5 (QiAudit)**
>
> Esta sección no introduce nuevos componentes matemáticos ni nuevas ecuaciones respecto de las ya discutidas anteriormente.
>
> Sin embargo, refuerza una interpretación importante de la arquitectura:
>
> QiAudit no actúa únicamente como monitor de error, sino como un monitor continuo del dominio de validez del sistema.
>
> En particular, supervisa:
>
> * Error de correlación:
>
> [
> \epsilon_c
> ]
>
> * Utilización de capacidad tensorial:
>
> [
> \chi_{used}/\chi_{max}
> ]
>
> * Tiempo real de ejecución (*wall clock time*).
> * Cumplimiento de las precondiciones P1–P4.
>
> ---
>
> ### Interpretación
>
> QiAudit funciona como una capa transversal encargada de verificar que QiCore continúe operando dentro del dominio para el cual existen garantías explícitas de funcionamiento.
>
> Conceptualmente:
>
> ```text
> Calidad del resultado
> +
> Uso de recursos
> +
> Cumplimiento de supuestos
> +
> Dominio de aplicabilidad
> ```
>
> ---
>
> ### Observación relevante
>
> La referencia explícita al "dominio de validez demostrado" constituye una señal importante de honestidad metodológica, ya que reconoce que la transferencia desde los sistemas físicos estudiados por Tindall hacia dominios industriales aún se encuentra condicionada por los supuestos P1–P4 y por la calidad de las aproximaciones realizadas durante la construcción del grafo y la estimación de χ.
>
> En consecuencia, QiAudit puede interpretarse como el mecanismo formal encargado de detectar cuándo la arquitectura abandona el régimen donde sus resultados pueden considerarse respaldados por la evidencia disponible.

---

> ## Observación de Auditoría – Algoritmo 1 (TN-BP Decision Cycle)
>
> El Algoritmo 1 constituye principalmente una formalización operacional de los componentes arquitectónicos descritos previamente (L1–L5), más que la introducción de nuevos elementos matemáticos.
>
> Su principal valor consiste en mostrar explícitamente cómo interactúan las distintas capas dentro del flujo completo de decisión.
>
> Conceptualmente:
>
> ```text
> Problema P
>      ↓
> L1 ─ QiPerception
>      ↓
> Construcción del grafo G
>      ↓
> Estimación de χreq
>      ↓
> ¿χreq ≤ χmax?
>      │
>      ├── No → Fallback Solver (I3)
>      │
>      └── Sí
>             ↓
> L2 ─ QiEvolution
>             ↓
> Evolución TN-BP
>             ↓
> L3 ─ QiMeasure
>             ↓
> Correlaciones {cij}
>             ↓
> L5 ─ QiAudit
>             ↓
> Cálculo de εc
>             ↓
> ¿εc ≤ εtarget?
>      │
>      ├── No → aumentar χ y repetir
>      │
>      └── Sí
>             ↓
> L4 ─ QiDecide
>             ↓
> arg min HG(A)
>             ↓
> Acción óptima A*
> ```
>
> ---
>
> ### Confirmaciones Arquitectónicas
>
> El pseudocódigo confirma varias hipótesis previamente inferidas:
>
> #### 1. Estimación explícita de χreq
>
> Aparece formalmente una función:
>
> \[
> \chi_{req}
> \leftarrow
> EstimateBondDim(G,\epsilon_{target})
> \]
>
> lo que confirma la existencia de un mecanismo dedicado para estimar la bond dimension requerida antes de ejecutar el núcleo TN-BP.
>
> Sin embargo, el documento sigue sin especificar:
>
> - la metodología utilizada;
> - la heurística de entropía de entrelazamiento mencionada anteriormente;
> - ni la precisión esperada de dicha estimación.
>
> ---
>
> #### 2. Implementación explícita de la Invariante I3
>
> El algoritmo implementa directamente:
>
> \[
> \chi_{req}
> >
> \chi_{max}
> \]
>
> como condición de salida hacia:
>
> ```text
> FallbackSolver(P)
> ```
>
> confirmando que la degradación graceful no es únicamente una declaración conceptual sino una regla operacional del flujo.
>
> ---
>
> #### 3. Ciclo adaptativo de χ
>
> El algoritmo formaliza una característica que anteriormente sólo se infería desde la descripción de L2:
>
> ```text
> Error elevado
>      ↓
> Aumentar χ
>      ↓
> Reiniciar evolución TN-BP
> ```
>
> mediante:
>
> ```text
> if εc > εtarget then
>     aumentar χ
>     goto línea 6
> ```
>
> Esto confirma que χ no necesariamente permanece fijo durante toda la ejecución.
>
> ---
>
> #### 4. Segundo mecanismo de activación de fallback
>
> Hasta ahora se había identificado:
>
> \[
> \chi_{req}
> >
> \chi_{max}
> \]
>
> como condición de degradación.
>
> El algoritmo muestra además una segunda condición:
>
> \[
> \epsilon_c
> >
> \epsilon_{target}
> \]
>
> lo que implica que QiCore puede abandonar el núcleo TN-BP incluso cuando el problema inicialmente cumple las restricciones de complejidad.
>
> ---
>
> ### Pregunta Crítica de Auditoría
>
> El algoritmo incorpora:
>
> \[
> \epsilon_c
> \leftarrow
> ComputeError(\{c_{ij}\})
> \]
>
> Sin embargo, la definición previa de:
>
> \[
> \epsilon_c
> =
> \sqrt{
> \frac{
> \sum (c_{ij}-\tilde c_{ij})^2
> }{
> \sum \tilde c_{ij}^2
> }}
> \]
>
> requiere conocer:
>
> \[
> \tilde c_{ij}
> \]
>
> es decir, una referencia considerada exacta.
>
> En los experimentos físicos de Tindall esta referencia existe y puede calcularse mediante métodos de comparación.
>
> No obstante, para problemas industriales reales surge una pregunta fundamental:
>
> > ¿Cómo obtiene QiCore los valores de referencia \(\tilde c_{ij}\) necesarios para calcular \(\epsilon_c\) cuando no existe una solución exacta conocida?
>
> Esta constituye actualmente una de las preguntas abiertas más relevantes de la auditoría.
>
> ---
>
> ### Conclusión Preliminar
>
> El Algoritmo 1 no permite verificar experimentalmente el rendimiento de QiCore, ya que no se dispone del código fuente, datasets ni procedimientos completos de ejecución.
>
> Sin embargo, sí permite validar la consistencia interna de la arquitectura propuesta, confirmando:
>
> - la interacción entre las capas L1–L5;
> - la existencia implícita de un gestor de χ;
> - la implementación práctica de las invariantes arquitectónicas;
> - el mecanismo iterativo de ajuste de χ;
> - y la dependencia crítica de la estimación de error \(\epsilon_c\).
>
> En consecuencia, el pseudocódigo fortalece la coherencia conceptual del diseño, aunque deja abiertas preguntas fundamentales sobre la estimación de χ y el cálculo práctico de \(\epsilon_c\) en dominios industriales.

---

# Conclusión de Auditoría

La arquitectura sugiere que la innovación principal de QiCore no se encuentra únicamente en TN o BP, sino en dos componentes críticos:

1. El proceso de construcción del grafo (QiPerception).
2. El mecanismo de estimación y control de χ (χ-manager).

Mientras que las capas de evolución, medición y decisión siguen patrones relativamente conocidos, la validez práctica de la transferencia desde sistemas físicos hacia dominios industriales depende fundamentalmente de estas dos piezas.

Por esta razón, ambas constituyen actualmente los principales focos de auditoría técnica para futuras revisiones del documento.

---

## Resumen Conceptual

Las tres invariantes pueden interpretarse como:

| Invariante | Propósito |
|------------|------------|
| I1 | No ejecutar TN-BP fuera de su dominio válido |
| I2 | Reportar la incertidumbre y calidad del resultado |
| I3 | Mantener operación segura mediante fallback cuando TN-BP deja de ser aplicable |

En conjunto, estas invariantes transforman a QiCore desde un algoritmo de optimización hacia una arquitectura con mecanismos explícitos de validación, trazabilidad y control de calidad.

---

## Preguntas abiertas

1. ¿Cómo se estima exactamente \(\chi_{req}\)?
2. ¿Cómo se define formalmente \(V^{TN}_{risk}\)?
3. ¿Cómo se verifica la convergencia de BP?
4. ¿Cómo se construye el grafo empresarial a partir de un problema real?
5. ¿Qué tan robusta es la transferencia desde Ising/TN hacia logística y OT?
6. ¿Qué evidencia experimental existe para QiRoute y QiShield fuera del dominio físico original?
