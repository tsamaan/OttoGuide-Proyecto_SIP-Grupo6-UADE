# Reporte HIL ODOM/TF Audit - 2026-05-26

## Alcance y seguridad

Sesion de auditoria de cableado logico ROS para SLAM, sin navegacion ni locomocion. El operador confirmo en runtime que el robot se encontraba sentado en una silla, fisicamente estacionario y supervisado antes de autorizar TF temporal y `slam_toolbox`.

Etiquetado obligatorio del gate ejecutado:

- TF temporal usado: YES
- diagnostico estacionario
- robot seated on chair
- no representa odometria real
- no representa mapeo fisico en movimiento
- no apto para navegacion
- no habilita Nav2

## Baseline Git y runtime

- Repositorio robot: `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git`
- Rama robot al inicio: `robot`
- HEAD inicial: `3757df6`
- `origin/robot` cacheado: `3757df6`
- Ahead/behind inicial contra `origin/robot`: `0 0`
- `git fetch --prune origin`: iniciado para auditoria, sin respuesta remota dentro del timeout; procesos del fetch detenidos por PID propio. No se modificaron refs por ese intento.
- Cambios tracked iniciales: ninguno.
- Untracked inicial: solo logs historicos bajo `codigo ottoguide/logs/`.
- Runtime ROS/locomocion previo: ninguno detectado.

## Auditoria pasiva ROS base

- Paquetes disponibles: `slam_toolbox async_slam_toolbox_node`, `tf2_ros static_transform_publisher`, `tf2_ros tf2_echo`, `nav2_map_server map_saver_cli`.
- Nodos base detectados: ninguno.
- Topicos base detectados: `/parameter_events`, `/rosout`.
- Servicios y acciones base detectados: ninguno.
- `/odom` antes del gate: ausente.
- `/tf` antes del gate: ausente.
- `/tf_static` antes del gate: ausente.
- Candidatos `/lowstate`, `/sportmodestate`, `/sport_state`, `/joint_states`, `/unitree/*`, `/robot_pose`, `/body_state`, `/base_state`, `/vel`: no detectados.
- Fuente candidata real para odometria: no encontrada.

## Scan gate y TF antes de temporal

- `scan_gate.launch.py` ejecutado sin crash observado.
- `/utlidar/cloud`: visible, 1 publisher.
- `/livox/imu`: visible, 1 publisher.
- `/scan`: visible, 1 publisher.
- Muestra sincronizada `/scan`: `frame_id=utlidar_lidar`, `count=6095`, `length=723`, `finite=20`, `inf=703`, `nan=0`.
- Frames TF detectados antes de TF temporal: ninguno.
- `base_link` antes de TF temporal: ausente.
- `odom` antes de TF temporal: ausente.
- `base_link -> utlidar_lidar` antes de TF temporal: no disponible.
- `odom -> base_link` antes de TF temporal: no disponible.
- `map -> odom` antes de SLAM: no disponible.

## Gate SLAM estacionario autorizado

- TF temporal `odom -> base_link`: publicado como identidad para diagnostico solamente.
- TF temporal `base_link -> utlidar_lidar`: publicado como identidad para diagnostico solamente.
- `/tf_static` con TF temporal: visible, 2 publishers.
- `tf2_echo odom base_link`: identidad verificada.
- `tf2_echo base_link utlidar_lidar`: identidad verificada.
- Config utilizada: `codigo ottoguide/ros2_ws/src/ottoguide_livox_sdk_bridge/config/slam_toolbox_mapping.yaml`.
- `slam_toolbox`: `async_slam_toolbox_node` iniciado y vivo durante la observacion.
- `/map`: visible, 1 publisher.
- `/tf` durante SLAM: visible, 2 publishers.
- Errores SLAM relevantes: ninguno observado; el nodo registro sensor y solver correctamente.

## Artefacto de mapa diagnostico

- Map save ejecutado solo tras confirmar publisher de `/map`.
- Archivos: `codigo ottoguide/maps/hil_stationary_slam_temp_tf_seated_20260527_030251.yaml` y `.pgm`.
- Dimension informada por `map_saver_cli`: `71 x 52` a `0.05 m/pix`.
- stationary diagnostic artifact
- not usable for navigation
- not a physical walking map
- generated with temporary TF while robot was seated

## Logs de evidencia

Los logs no se stagean ni se versionan:

- `codigo ottoguide/logs/scan_gate_odom_tf_audit_sync_20260527_025213.log`
- `codigo ottoguide/logs/scan_gate_stationary_temp_tf_20260527_030251.log`
- `codigo ottoguide/logs/static_tf_odom_base_20260527_030251.log`
- `codigo ottoguide/logs/static_tf_base_lidar_20260527_030251.log`
- `codigo ottoguide/logs/slam_gate_stationary_20260527_030251.log`

## Limpieza y conclusion

- Procesos detenidos: solo PIDs propios de scan gate, hijos Livox/pointcloud, TF temporal y `slam_toolbox`.
- Runtime ROS propio restante al finalizar: ninguno detectado.
- Clasificacion final: `SLAM_STATIONARY_MAP_SAVED_WITH_TEMP_TF`.
- Proxima accion: investigar fuente Unitree real de odometria/pose para disenar `odom_bridge`; este gate no habilita navegacion ni mapeo fisico en movimiento.

## Invariantes respetadas

- Nav2 ejecutado: NO
- nav2_bringup ejecutado: NO
- navegacion ejecutada: NO
- locomocion ejecutada: NO
- `/cmd_vel` publicado: NO
- SportClient ejecutado: NO
- LocoClient ejecutado: NO
- `eth0` modificado: NO
- red modificada: NO
- `cyclonedds.xml` modificado: NO
- codigo C++ modificado: NO
- paquetes instalados: NO
- logs borrados: NO
- logs stageados: NO
- `git reset` ejecutado: NO
- `git clean` ejecutado: NO
- `git push` ejecutado: NO
