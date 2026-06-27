# OttoGuide - Estado HIL fisico al 2026-06-04

## Baseline

- Rama: `robot`
- HEAD robot/local: `4b8eb09`
- Robot: Unitree G1 EDU 8
- ROS 2: Foxy
- RMW: `rmw_cyclonedds_cpp`
- ROS_DOMAIN_ID: `0`
- CycloneDDS: `codigo ottoguide/config/cyclonedds.foxy.xml`
- eth0: `192.168.123.164/24`
- Ruta interna: `192.168.123.0/24 dev eth0`

## Validaciones completadas

| Gate | Resultado | Evidencia |
|---|---|---|
| DDS Foxy | PASS | `validate_cyclonedds_config.sh` con `VALIDATE_RC=0` |
| Discovery inicial | PASS / NO READY | Solo `/parameter_events` y `/rosout` visibles antes de iniciar sensores |
| Livox flow | PASS | `cloud_count=22390`, `imu_count=2999` |
| scan_gate | PASS | `scan_count=22419`, `cloud_count=23937` |
| SLAM estacionario inicial | PARTIAL | `/map` tuvo publisher, pero `map_count=0` porque no se aplico la config esperada |
| SLAM config-fix | PASS | `MAP_COUNT=2`, `frame_id=map` |

## Resultado SLAM config-fix

- YAML usado: `codigo ottoguide/ros2_ws/src/ottoguide_livox_sdk_bridge/config/slam_toolbox_mapping.yaml`
- Argumento launch ROS 2 Foxy: `params_file`
- `base_frame` efectivo: `base_link`
- `odom_frame` efectivo: `odom`
- `map_frame` efectivo: `map`
- `scan_topic` efectivo: `/scan`
- `/utlidar/cloud`: `sensor_msgs/msg/PointCloud2`
- `/livox/imu`: `sensor_msgs/msg/Imu`
- `/scan`: `sensor_msgs/msg/LaserScan`
- `/map`: `nav_msgs/msg/OccupancyGrid`
- `SCAN_COUNT=1634`
- `TF_COUNT=20`
- `TF_STATIC_COUNT=1`
- `MAP_COUNT=2`
- `LAST_MAP frame_id=map`
- `resolution=0.05000000074505806`
- `width=4`
- `height=6`
- `data_len=24`

## Advertencia

El TF usado fue temporal diagnostico e identidad:

- `odom -> base_link`
- `base_link -> utlidar_lidar`

Este TF no esta calibrado para navegacion autonoma y no debe tratarse como definitivo.

## Acciones no realizadas

- No Nav2.
- No RealSense.
- No locomocion.
- No `/cmd_vel`.
- No `map_saver`.
- No navegacion autonoma.
- No cambios de red.
- No cambios Git en robot.
- No limpieza de untracked.

## Decision

Estado: listo para preparar una sesion de rosbag de mapeo controlado sin Nav2.

Proximo paso recomendado:

- Grabar `/scan`, `/utlidar/cloud`, `/livox/imu`, `/tf`, `/tf_static`, `/map` y `/map_metadata`.
- Mantener TF diagnostico o reemplazarlo por TF calibrado explicito.
- No iniciar Nav2.
- No ejecutar locomocion autonoma.
