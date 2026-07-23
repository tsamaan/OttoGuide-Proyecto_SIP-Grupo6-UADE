# ODOM/TF R2-P2 — contrato de semántica de frames y covarianza

> **Superseded for future consumption by P2A.** El resultado y los outputs
> históricos P2 permanecen sin reinterpretación. P2A cierra bypasses de enums,
> enlaza mapping por hash, valida P1A, separa dominios de covarianza y deriva
> readiness desde objetos validados. Ver
> [ODOM_TF_R2_P2A_CONTRACT_AUDIT_AND_HARDENING.md](ODOM_TF_R2_P2A_CONTRACT_AUDIT_AND_HARDENING.md).

## Alcance

R2-P2 define un contrato puro, versionado (`2.2.0-p2`), determinista y
fail-closed. No construye mensajes ROS, no publica `/odom` ni TF, no selecciona
un canal autoritativo, no ejecuta ROS 2, Nav2, mapping, simuladores, DDS, SSH ni
acciones sobre el robot.

El acceso futuro al robot se considera permanentemente no disponible. Los
claims físicos no resolubles con la evidencia preservada quedan
`UNRESOLVED_NO_NEW_HARDWARE_ACCESS`; esto no impide definir contratos separados
para replay o simulación.

## Contextos de validación

Todo claim de frames o covarianza pertenece exactamente a uno de estos
contextos:

| Contexto | Autoriza claims físicos | Uso en P2 |
|---|---:|---|
| `PHYSICAL_EVIDENCE` | Solo hasta la fuerza de la evidencia R4/R4B preservada | Conserva límites físicos |
| `OFFLINE_REPLAY` | No | Define replay determinista sin promoción a SI |
| `SIMULATION` | No | Define política paramétrica simulation-only |
| `STRUCTURAL_ONLY` | No | Valida forma, vocabulario y blockers |

Una fixture sintética o una configuración de simulación nunca puede promoverse
a `PHYSICAL_EVIDENCE`.

## Nombres configurados y semántica

Los nombres conocidos son:

```text
SOURCE_FRAME_LABEL = unitree_odom_candidate
CONFIGURED_PARENT_FRAME_NAME = odom
CONFIGURED_CHILD_FRAME_NAME = base_link
CONFIGURED_SENSOR_FRAME_NAME = utlidar_lidar
```

Son labels o nombres configurados; no equivalen por sí mismos a semántica
física validada. El techo de evidencia física continúa siendo:

```text
SOURCE_FRAME_SEMANTICS_STATUS = PARTIAL
CHILD_FRAME_SEMANTICS_STATUS = UNRESOLVED
TRANSLATION_SCALE_STATUS = UNRESOLVED
YAW_SCALE_STATUS = UNRESOLVED
SOURCE_CHANNEL_STATUS = UNRESOLVED
TIME_DOMAIN_POLICY = UNRESOLVED_FOR_ROS_HEADER
BOOT_DOMAIN_POLICY = PER_BOOT_NO_CROSS_BOOT_CONCATENATION
```

El replay conserva ejes, orden y unidades de la fuente sin convertirlos a SI.
Cada sesión tiene un origen local y no puede concatenarse entre boots. El
contrato de simulación usa una política ROS convencional únicamente dentro del
modelo simulado y queda marcado `SIMULATION_ONLY=true`,
`PHYSICAL_VALIDATION_CLAIM=false`.

## Vocabulario de frames

El paquete tipa referencias a `map`, `odom`, `base_link`,
`unitree_odom_candidate`, `utlidar_lidar`, `livox_imu` e `imu_link` mediante
clasificaciones separadas: nombre configurado, label de fuente, referencia de
evidencia física, referencia de mapping/replay, modelo de simulación, fixture
sintética, documentación histórica, candidato de salida ROS o alias no
resuelto.

Cada entrada incluye paths relativos, contexto, fuerza, provenance y
limitaciones. La frecuencia de aparición no constituye evidencia.

## Mapping como fuente read-only

Se inventariaron las grabaciones y artefactos existentes: bags DB3, JSONL,
mapas PGM/YAML, launch/configs, frame inventories, resultados KISS-ICP y
contratos simulados R3X/R3Y. Este material aporta:

- vocabulario de frames y topics;
- sesiones de replay con provenance;
- cadenas candidatas `map -> odom -> base -> sensor`;
- forma de un contrato de simulación.

No aporta por sí mismo autoridad de canal, equivalencia física de frames,
escala métrica de la fuente, política ROS Time ni covarianza física.

## Covarianza

P2 separa cuatro objetos:

1. `PHYSICAL_SOURCE_UNIT_EVIDENCE`: estadísticas estacionarias, residuales
   dinámicos y residuales de yaw-speed de P1/P1A, conservados en unidades de
   fuente.
2. `OFFLINE_REPLAY_COVARIANCE_POLICY`: preserva evidencia y canales separados;
   no convierte a SI.
3. `SIMULATION_COVARIANCE_POLICY`: contrato paramétrico en SI por definición
   del simulador, nunca por evidencia física.
4. `ROS_SI_PUBLICATION_CANDIDATE`: matriz `None`, no publicable.

Las dispersiones por eje pueden producir candidatos diagonales en
`source_unit²`. No son una matriz ROS. El yaw-speed residual no se convierte en
pose-yaw covariance. Los canales primary y LF no se mezclan. Las
off-diagonales quedan `UNRESOLVED_NOT_ASSUMED_ZERO`.

`None`, `UNAVAILABLE` y `UNRESOLVED` representan desconocidos. Cero y 999 no
son marcadores de desconocido ni evidencia. Los valores históricos
0.50/0.10/999 quedan tipados como
`LEGACY_PLACEHOLDER_NOT_EVIDENCE`, con `publication_allowed=false`.

## Readiness

P2 permite:

```text
P2_CONTRACT_STRUCTURALLY_READY = true
OFFLINE_REPLAY_CONTRACT_READY = true
SIMULATION_CONTRACT_READY = true
```

P2 exige:

```text
PHYSICAL_ODOM_PUBLICATION_READY = false
PHYSICAL_TF_PUBLICATION_READY = false
SIMULATED_ODOM_PUBLICATION_READY = false
SIMULATED_TF_PUBLICATION_READY = false
NAV2_SIMULATION_READINESS = false
```

Los últimos tres estados se difieren a P3. Los blockers físicos son:

- `AUTHORITATIVE_SOURCE_CHANNEL_UNRESOLVED`
- `SOURCE_FRAME_SEMANTICS_PARTIAL`
- `CHILD_FRAME_ID_UNRESOLVED`
- `TRANSLATION_SCALE_UNRESOLVED`
- `YAW_SCALE_UNRESOLVED`
- `ROS_HEADER_STAMP_POLICY_UNRESOLVED`
- `COVARIANCE_SI_CONVERSION_UNAVAILABLE`
- `NO_NEW_HARDWARE_ACCESS`

## Implementación

El paquete vive en
`codigo ottoguide/src/navigation/odometry_contract_r2_p2/`. Todos sus modelos
son dataclasses frozen y keyword-only. No importa ROS, DDS ni Unitree.

La CLI
`codigo ottoguide/tools/hil/offline_navigation/build_odom_tf_r2_p2_contract.py`
requiere todos los paths y el timestamp por argumentos explícitos, verifica el
descriptor del harvest y solo escribe dentro de un `output-dir` nuevo. Sus
outputs son deterministas y no contienen paths personales ni material raw.

El contrato legado conserva wrappers diagnósticos, pero
`activation_allowed()` queda deprecado y nunca autoriza publicación. La antigua
lógica está disponible como `legacy_prerequisites_satisfied()` sin significado
de readiness.
