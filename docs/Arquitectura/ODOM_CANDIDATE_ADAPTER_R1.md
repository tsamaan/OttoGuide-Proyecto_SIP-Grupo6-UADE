# ODOM-R1 Adapter Contract

TASK_ID = OTTOGUIDE_ODOM_R1_SPORTMODESTATE_TO_ODOM_OFFLINE_ADAPTER_NO_PUBLISH

Implementación offline pura del contrato de datos aceptado en MFR-R6. No publica nada, no requiere ROS/DDS/robot para ejecutarse.

## Fuente primaria

`rt/odommodestate` — confirmado en MFR-R6 con 80 muestras reales, ~507 Hz, sin gaps.

## Fuente secundaria

`rt/lf/odommodestate` — confirmado en MFR-R6 con 80 muestras reales, ~20 Hz, sin gaps, fuente independiente (no alias) de la primaria.

Cualquier `source_channel` fuera de `{rt/odommodestate, rt/lf/odommodestate}` es rechazado como inválido por `to_odometry_candidate()`.

## Campos aceptados

- `position_xyz` (de `position[0..2]`)
- `velocity_xyz` (de `velocity[0..2]`)
- `yaw_speed`
- `orientation_quaternion_xyzw` (de `imu_state.quaternion`)
- `rpy` (de `imu_state.rpy`)

## Campos no confiables

- `message_stamp_sec` / `message_stamp_nanosec` — preservados en la estructura de salida para trazabilidad, pero **no usados como fuente de tiempo**. Confirmado en 160/160 muestras reales que ambos son siempre 0.
- `gyro_reliable` — `False` cuando `imu_state.gyroscope == [0,0,0]` (caso de las 160 muestras reales capturadas).
- `accel_reliable` — `False` cuando `imu_state.accelerometer == [0,0,0]` (caso de las 160 muestras reales capturadas).

## Política de timestamp

`timestamp_policy = "MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED"` (constante fija en `validation.py`, expuesta en cada `OdometryCandidate`).

- El adapter **no lee el reloj del sistema**; el `receipt_monotonic_ns`/`receipt_wall_utc_ns` deben venir ya en el `sample` de entrada (capturados en el momento de recepción DDS, no en el momento del procesamiento offline).
- Si `stamp_sec == 0 and stamp_nanosec == 0`, se agrega un warning explícito en `OdometryCandidate.warnings`, nunca se sustituye silenciosamente.
- `receipt_monotonic_ns` ausente o no siendo un entero positivo invalida la muestra (`errors`, `valid=False`).

## Política de frame

`frame_id = "unitree_odom_candidate"` (constante fija, nunca `"odom"`).
`child_frame_id = None` (nunca se declara `"base_link"`).

No se realiza ninguna transformación de frame — el adapter no sabe ni asume a qué frame de referencia corresponde `position`/`velocity` más allá de esta etiqueta provisional.

## Política de covarianza

`covariance_policy = "NO_COVARIANCE_IN_SOURCE_DOCUMENT_GAP"` (constante fija).
`covariance_available = False` siempre — `SportModeState_` no trae covarianza, y este adapter no la inventa ni la aproxima.

## Criterios de aceptación (implementados y testeados)

1. Función pura: `to_odometry_candidate(sample: dict) -> OdometryCandidate`. Sin I/O, sin red, sin reloj de sistema, sin estado global.
2. Input: dict con los campos capturados por el probe MFR-R6/SDK-R4 (`channel`, `receipt_monotonic_ns`, `receipt_wall_utc_ns`, `stamp_sec`, `stamp_nanosec`, `position`, `velocity`, `yaw_speed`, `imu_quaternion`, `imu_rpy`, `imu_gyroscope`, `imu_accelerometer`).
3. Output: `OdometryCandidate` (dataclass interna, no `nav_msgs/Odometry`, nunca publicada).
4. Tests con las 160 muestras reales capturadas en MFR-R6 como fixtures (`fixtures/*.jsonl`).
5. Fail-closed: `position`, `velocity`, `yaw_speed` faltantes o inválidos (NaN/Inf) producen `valid=False` con `errors` explícitos, nunca una excepción no controlada ni un valor por defecto silencioso.

## Criterios NO-GO (verificados por los tests)

- Sin muestras → `valid=False` en caso de canal sin publisher (no aplicable directamente aquí, la ausencia de muestras se maneja aguas arriba en la extracción de fixtures).
- `position` con NaN/Inf → `valid=False`.
- `velocity` con NaN/Inf → `valid=False`.
- `receipt_monotonic_ns` faltante o no positivo → `valid=False`.
- `source_channel` fuera del set autorizado → `valid=False`.
- Estos 4 casos están cubiertos por tests explícitos en `test_odometry_candidate_adapter.py`.

## Por qué no se publica `/odom`

`/odom` es un tópico `nav_msgs/Odometry` con campos de covarianza y un frame de referencia declarado formalmente (`odom -> base_link`). Ninguno de esos dos requisitos está resuelto: no hay covarianza en la fuente (gap documentado, no inventado) y el frame de referencia real de `position`/`velocity` no ha sido validado (requeriría mover el robot de forma controlada, fuera de alcance de cualquier checkpoint read-only hasta ahora). Publicar `/odom` con datos incompletos induciría a error a cualquier consumidor aguas abajo (Nav2, AMCL, etc.) que asuma la semántica estándar del mensaje.

## Por qué no se publica TF

Publicar la transformación `odom -> base_link` exige el mismo frame de referencia validado que `/odom`, más una decisión de diseño sobre child_frame_id que este checkpoint explícitamente no toma (`child_frame_id = None`). Sin esa validación, publicar TF generaría una jerarquía de frames potencialmente incorrecta que otros nodos (RViz, Nav2, transformaciones de sensores) consumirían como si fuera confiable.

## Por qué no se declara navegación autónoma lista

Este checkpoint produce una estructura de datos interna testeada contra datos reales de un robot **estacionario**. No se ha validado: (a) el comportamiento del candidato durante movimiento real, (b) el frame de referencia, (c) la deriva a largo plazo, (d) la fusión con otros sensores (LIDAR, IMU externa), ni (e) ningún componente de localización/mapeo. Afirmar que la navegación autónoma está lista a partir de este checkpoint sería una sobre-extrapolación no respaldada por la evidencia recolectada.
