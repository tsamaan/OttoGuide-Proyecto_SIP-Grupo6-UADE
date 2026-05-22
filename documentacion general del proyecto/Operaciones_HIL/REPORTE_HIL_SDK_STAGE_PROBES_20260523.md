# Reporte HIL — SDK stage probes y frontera previa al full run

## Estado Git

- Rama: `robot`
- HEAD al inicio: `ac668d6`
- origin/robot: `ac668d6`
- Estado tracked: clean
- Logs untracked: presentes, no stageados

## Clasificación actual

`SDK_STAGE_PROBES_PASS_NEED_FULL_RUN`

## Resumen

Se estabilizó el modo diagnóstico no-SDK del bridge Livox SDK2. El nodo ya no crashea cuando `debug_disable_livox_sdk:=true`, el timer no corre en modo no-SDK y los markers de timer `MARK_140/MARK_143` desaparecen en ese modo.

Después de esa corrección, se ejecutaron pruebas por etapas con SDK activo para aislar la frontera del crash sin ejecutar `/scan`.

## Resultados confirmados

- `before_sdk_init`: salida limpia, sin crash.
- `after_sdk_init`: salida limpia, sin crash.
- `after_callbacks_registered`: salida limpia, sin crash.
- `before_sdk_start`: salida limpia, sin crash.
- `after_sdk_start`: salida limpia, sin crash.
- `sdk_active_callbacks_disabled`: vivo después de 5 s, sin crash.
- `sdk_active_dryrun_callbacks`: vivo después de 5 s, sin crash.

## Interpretación

El SDK Livox puede inicializar, registrar callbacks y arrancar. Los callbacks también pueden ejecutarse en modo dry-run sin publicar ni encolar hacia el flujo normal.

La caída previa del full run ya no se atribuye a:

- no-SDK timer loop;
- marker flood;
- SDK init;
- SDK start;
- registro de callbacks;
- DDS discovery inicial;
- `/scan`;
- `pointcloud_to_laserscan`.

La frontera pendiente está entre:

1. callback normal con enqueue;
2. timer de publicación;
3. publicación ROS/DDS;
4. interacción callback/timer.

## Evidencia previa de full run fallido

En una corrida con SDK activo normal, el bridge no permaneció vivo a los 20 s, se observó `exit code -11`, y los tópicos `/utlidar/cloud` y `/livox/imu` no quedaron visibles. No se ejecutó subscriber porque el bridge cayó antes.

## Qué NO se ejecutó

- `/scan`
- `pointcloud_to_laserscan`
- SLAM
- Nav2
- navegación
- locomoción
- `/cmd_vel`
- SportClient
- LocoClient

## Archivos involucrados

- `ros2_ws/src/ottoguide_livox_sdk_bridge/src/livox_sdk_bridge_node.cpp`
- `ros2_ws/src/ottoguide_livox_sdk_bridge/launch/mid360_sdk2_bridge.launch.py`
- `cyclonedds.xml`
- logs HIL bajo `logs/` no versionados

## Próximo plan recomendado

Antes de cualquier gate `/scan`, ejecutar aislamiento post-SDK:

1. `callbacks_enqueue_no_timer` con `debug_disable_timers:=true`.
2. `callbacks_timer_no_publishers` con `debug_disable_publishers:=true`.
3. `full_sdk_short`.
4. `full_sdk_20s` solo si el corto pasa.
5. Subscriber QoS solo si el full run queda vivo.

## Criterio de desbloqueo hacia `/scan`

Solo preparar `pointcloud_to_laserscan` cuando:

- bridge con SDK activo permanece vivo al menos 20 s;
- sin `exit code -11`;
- sin `std::bad_alloc`;
- `/utlidar/cloud` visible;
- `/livox/imu` visible;
- subscriber QoS BEST_EFFORT/VOLATILE recibe clouds e IMUs.
