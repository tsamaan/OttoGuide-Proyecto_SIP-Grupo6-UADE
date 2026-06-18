# Scan Gate Configuration

## Objetivo del Gate
Proveer una configuración reproducible para arrancar el bridge de Livox SDK2 junto con `pointcloud_to_laserscan`, de manera estable y probada en HIL, garantizando la conversión de nubes de puntos 3D a escaneos 2D requeridos por Nav2/SLAM, sin activar la navegación completa.

## Historial de Tuning
- Commit base: `d2ae8fa`
- Problema detectado: La configuración inicial producía `finite ranges = 0` en ciertas pruebas debido a filtros de altura muy restrictivos o dinámicas del entorno.
- Combinación elegida: **Case F** (`min_height: -3.00`, `max_height: 3.00`, sin `target_frame` explícito). Esto permite capturar el volumen completo de la nube y retener el frame `utlidar_lidar` original, maximizando la detección de obstáculos cercanos.
- Aclaración: SLAM y Nav2 no fueron ejecutados durante esta validación.

## Entorno Requerido
```bash
source /opt/ros/foxy/setup.bash
source ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=0
export CYCLONEDDS_URI="file://$PWD/cyclonedds.xml"
```

## Comando de Ejecución
```bash
ros2 launch ottoguide_livox_sdk_bridge scan_gate.launch.py
```

## Criterio de Éxito
- `/scan` es visible vía `ros2 topic info`.
- Scan subscriber count > 0.
- Finite ranges > 0 en el escaneo procesado.
- Sin errores TF ni crasheos por load DDS.
- Sin activación de SLAM o Nav2.

## Gate SLAM diagnostico sin navegacion - 2026-05-23

Resultado: `SLAM_BLOCKED_BY_ODOM_TF`.

Ejecucion:
- HEAD y `origin/robot` auditados al inicio: `2eb4a65`, ahead/behind `0 0`.
- `slam_toolbox`: instalado, con `async_slam_toolbox_node` disponible.
- `tf2_ros`: disponible, con `tf2_echo` y `static_transform_publisher`.
- Map saver: disponible via `nav2_map_server map_saver_cli`.
- Scan gate log de auditoria: `logs/scan_gate_before_slam_20260523_051655.log` (no versionado).

Scan observado:
- `/utlidar/cloud`: visible.
- `/livox/imu`: visible.
- `/scan`: visible.
- `LaserScan.frame_id`: `utlidar_lidar`.
- `scan_count=9743`, `scan_length=723`, `finite=42`, `inf=681`, `nan=0`.

Bloqueo TF/odom:
- `/tf`: no visible.
- `/tf_static`: no visible.
- `/odom`: no visible.
- `base_link`: no detectado.
- Transform `base_link -> utlidar_lidar`: no disponible.
- Transform `odom -> base_link`: no disponible.
- Transform `map -> odom`: no disponible.

Decision del gate:
No se ejecuto `slam_toolbox` porque falta la cadena minima de TF/odom para mapeo. No se publico TF temporal porque el bloqueo no es solo `base_link -> utlidar_lidar`; tambien falta `/odom` y `odom -> base_link`.

Siguiente accion tecnica:
Resolver `odom -> base_link` y validar una TF estatica calibrada `base_link -> utlidar_lidar` antes del siguiente gate SLAM sin navegacion.

