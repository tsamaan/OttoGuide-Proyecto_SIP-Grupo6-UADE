# ODOM/TF R2-P2A — auditoría y hardening del contrato

## Resultado

`MVP_ODOM_TF_R2_P2A_COMPLETE_WITH_LIMITATIONS`

P2A supersede el contrato P2 para consumo futuro. El resultado histórico P2 no
se reinterpreta: sus outputs y bundle permanecen inmutables. P2A conserva el
límite offline y no autoriza publicación de odometría, TF, ROS, Nav2 ni acceso
al robot.

Schema P2A: `2.2.1-p2a`.

## Hallazgos reproducidos

La auditoría adversarial se guardó antes de modificar código. H1–H7 y H9–H15
fueron `REPRODUCED`; H8 fue `PARTIAL`, porque NaN e infinito ya terminaban
rechazados, aunque `bool`, subclases de contenedores y secuencias hostiles no
tenían una frontera fail-closed uniforme.

| Hipótesis | Corrección P2A |
| --- | --- |
| H1/H2 | Enums de tipo exacto para contextos, clasificaciones y estados |
| H3–H5 | Manifest mapping sanitizado, validado y enlazado por SHA-256 |
| H6 | Schema P1A y bundle embebido exigidos; findings H1–H10 exactos |
| H7/H8 | Números finitos simples, límites representables y containers exactos |
| H9 | Un cero se preserva solo si existe evidencia fuente measured-zero en el mismo eje; el material actual no la demuestra |
| H10/H11 | Evidencia cross-channel y yaw-rate separada por dominio |
| H12 | Simulación reducida a `SIMULATION_POLICY_CANDIDATE` |
| H13 | Readiness derivada de un `ContractEvidenceSet` validado |
| H14 | UTC canónico `YYYY-MM-DDTHH:MM:SSZ` |
| H15 | Autoridad canónica y rol staging del mirror explícitos |

## Binding de mapping

El manifest
`docs/Operaciones_HIL/Evidencia/R2_P2A_MAPPING_EVIDENCE_MANIFEST.json`
contiene únicamente IDs, categorías, frames/topics observados, artefactos
resumidos y hashes seleccionados. Cada fuente existe bajo el workspace mapping,
coincide con su SHA-256 y está incluida en su manifest de origen.

El binding permite vocabulario configurado, provenance de replay y referencias
derivadas. Prohíbe promover mapping a semántica física, escala, autoridad de
odometría, REP-103, handedness o unity scale verificados.

## P1A

El input preservado tiene schema `2.1.1-p1a`, diez findings H1–H10, diez
registros estacionarios válidos, canales permitidos y políticas explícitas que
prohíben concatenación cross-boot.

El documento histórico contiene una preferencia analítica LF
`SUPPORTED_INFERENCE`. P2A la acepta solamente al coincidir el hash exacto del
input preservado, la marca como `quarantined` y no la propaga. Esto no es una
selección autoritativa. Los valores contractuales P2A son:

- `AUTHORITATIVE_SOURCE_CHANNEL = null`;
- `PREFERRED_ANALYSIS_CHANNEL = null`.

Cualquier documento mutado o sintético con un preferred channel no nulo falla.

## Dominios de covarianza

P2A separa:

- `POSE_POSITION_SOURCE_DISPERSION`;
- `POSE_ORIENTATION_UNAVAILABLE`;
- `TWIST_LINEAR_RESIDUAL`;
- `TWIST_ANGULAR_YAW_RATE_RESIDUAL`;
- `CROSS_CHANNEL_RESIDUAL`.

Los residuos `BOTH` no se replican en primary/LF. Los residuos yaw-rate quedan
como cross-channel en `rad/s`, nunca como pose-yaw. Un cero se conserva como
varianza fuente `0.0` solo bajo el predicado estricto de evidencia fuente; el
material actual no contiene ese caso. Ausencia o invalidez queda en `null`.

No existe conversión de posición a SI, matriz ROS, off-diagonals resueltas ni
modelo publicable.

## Replay y simulación

Estados P2A:

- `OFFLINE_REPLAY_POLICY_STRUCTURALLY_READY = true`;
- `OFFLINE_REPLAY_ADAPTER_READY = false`;
- `OFFLINE_REPLAY_EXECUTION_VALIDATED = false`;
- `SIMULATION_POLICY_STRUCTURALLY_READY = true`;
- `SIMULATION_MODEL_BOUND = false`;
- `SIMULATION_ADAPTER_IMPLEMENTED = false`;
- `SIMULATION_EXECUTION_READY = false`.

P2A no declara REP-103, handedness o unity scale verificados. Ningún simulador,
asset de modelo, adapter o ejecución fue iniciado.

## Contrato legado

`activation_allowed()` permanece como API compatible deprecada que siempre
retorna `false`. `legacy_prerequisites_satisfied()` es sólo diagnóstico.
`default_conservative_covariance()` conserva los valores históricos bajo
`LEGACY_PLACEHOLDER_NOT_EVIDENCE` y nunca habilita publicación. No existen
callers productivos que dependan de un retorno `true`.

## Limitaciones

- semántica del source frame: `PARTIAL`;
- `child_frame_id`: `UNRESOLVED`;
- translation/yaw scale: `UNRESOLVED`;
- ROS header timestamp: `UNRESOLVED`;
- matriz de covarianza ROS SI: `None`;
- publicación ODOM/TF: `false`;
- acceso futuro al robot: `NOT_EXPECTED`.

## Candidato local P2C

El hardening local P2C mantiene cerrados por implementacion y regresion los
findings de modelos, inputs e I/O. Independent Audit R1 reabrio F19 y F20:
`MEASURED_ZERO_PRESERVED` usaba ceros cross-channel como evidencia de varianza
fuente y `source_heads.pilar-web` no coincidia con las refs remotas vivas.

Claims/State R2 corrige el predicado measured-zero, conserva el claim en
`false` para el material actual, estrecha las garantias de mapping, P1A, enums
y numeros a propiedades estructurales demostrables, deriva las vistas desde un
ledger canonico y reconcilia `pilar-web` con ambos remotos. Un caso unitario
sintetico positivo prueba la logica measured-zero, pero no constituye evidencia
fisica. La restriccion de overlap entre frames configurados y observados queda
como limitacion baja aceptada, sin redisenar el mapping.

Este estado es un candidato local sin commit y sin publicacion remota. No esta
integrado en `review/orchestrator-unification`, no existe una rama P2C remota y
la auditoria independiente R2 permanece pendiente. El siguiente gate es
`MVP-ODOM-TF-R2-P2C-CLAIMS-STATE-R2-INDEPENDENT-AUDIT-R1`.

Los limites funcionales no cambian: no se declara `/odom` fisico, TF fisico,
Nav2, localizacion, mapa fisico, matriz de covarianza ROS/SI, replay ejecutado,
simulacion ejecutada, canal autoritativo, preferencia LF autoritativa ni nueva
evidencia fisica.
