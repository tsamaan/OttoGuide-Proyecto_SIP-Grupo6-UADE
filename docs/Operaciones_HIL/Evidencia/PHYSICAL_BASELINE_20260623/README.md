# Baseline Físico — Auditoría 2026-06-23

**Fecha de auditoría**: 2026-06-23  
**Fase**: 2H.2.5R (reconciliación post-auditoría física)  
**HEAD publicado (robot)**: `80417b727c1ac7324447ac8745652b29062a9a2e`  
**HEAD físicamente desplegado**: `23d9d9cd1aee2f4507dadfaee17e188d0d37135b`  
**Relación**: `23d9d9c` es ancestro de `80417b7`; el robot estaba 38 commits detrás.

```text
CURRENT_PUBLISHED_CODE        = 80417b7
PHYSICAL_DEPLOYED_HEAD        = 23d9d9c
CURRENT_RUNTIME_CODE_PHYSICALLY_VALIDATED = NO
```

Esta evidencia corresponde al estado real del robot el 2026-06-23. No valida el
código publicado en `80417b7` — ese código nunca fue ejecutado físicamente.

## Contenido

- `physical_environment_summary.json` — plataforma, red, ROS, variables de entorno observadas.
- `route_capture_summary.json` — metadatos de las dos tomas de captura de ruta manual.
- `route_capture_hashes.sha256` — hashes SHA256 de los paquetes de captura físicos.

## Readiness al momento de la auditoría

```text
RAW_ROUTE_CAPTURE                    = COMPLETE
PHYSICAL_L0_SENSORS                  = OBSERVED_AND_RECORDED
PHYSICAL_L1_UNITREE_TELEMETRY        = OBSERVED_AND_RECORDED
CUSTOM_R0_PHYSICAL_INVENTORY         = EXECUTED
FORMAL_P0_V2_COLLECTOR               = NOT_EXECUTED
P0_CURRENT_CODE_ON_ROBOT             = NOT_DEPLOYED
L2_ODOMETRY                          = NOT_READY
TF_PHYSICAL                          = NOT_READY
L3_LOCALIZATION_MAP                  = NOT_READY
CMD_VEL_SAFETY_CHAIN                 = NOT_READY
NAV2_PHYSICAL                        = NOT_PRESENT
AUTONOMOUS_NAVIGATION                = NOT_VALIDATED
PHYSICAL_MOVEMENT_BY_SOFTWARE        = NONE
MANUAL_REMOTE_ROUTE_CAPTURE          = EXECUTED
```

## Limitaciones

- El reloj de pared del robot es inválido (epoch ~Mayo 1970). Los `RUN_ID` `19700526_*`
  son identificadores técnicos, no timestamps UTC reales.
- La captura valida los scripts en `23d9d9c`, no los 38 commits posteriores.
- El probe `find_spec()` se ejecutó sin sourcear ROS; los resultados de `rclpy`,
  `geometry_msgs`, `nav2_msgs` = `false` no prueban ausencia en entorno sourced.

## No versionado

Los archivos `.db3`, `.tar.gz` y outputs masivos de las tomas no están versionados
en el repositorio. Solo se versionan metadatos, hashes y muestras acotadas.
