# OttoGuide - Rosbag HIL estacionario validado

## Baseline

- Rama: `robot`
- HEAD robot/local: `ecefad1`
- Robot: Unitree G1 EDU 8
- ROS 2: Foxy
- RMW: `rmw_cyclonedds_cpp`
- ROS_DOMAIN_ID: `0`
- CycloneDDS: `cyclonedds.foxy.xml`
- Modo: HIL estacionario, sin Nav2 y sin locomocion

## Bag validado

- BAG_DIR robot: `/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/artifacts/rosbags/hil_mapping_stationary_retry_20260605_070755`
- BAG_DIR local: `artifacts/rosbags/hil_mapping_stationary_retry_20260605_070755`
- Duracion: `44.377 s`
- Tamano `.db3`: `512,876,544 bytes / 489.1 MiB`
- `metadata.yaml`: presente, `5310 bytes`
- `ros2 bag info`: OK en robot
- Validacion local Windows: no ejecutada porque `ros2` no esta disponible localmente

## Topicos grabados

| Topico | Tipo | Mensajes |
|---|---|---:|
| `/utlidar/cloud` | `sensor_msgs/msg/PointCloud2` | 66302 |
| `/livox/imu` | `sensor_msgs/msg/Imu` | 8866 |
| `/scan` | `sensor_msgs/msg/LaserScan` | 65425 |
| `/tf` | `tf2_msgs/msg/TFMessage` | 888 |
| `/tf_static` | `tf2_msgs/msg/TFMessage` | 2 |
| `/map` | `nav_msgs/msg/OccupancyGrid` | 23 |
| `/map_metadata` | `nav_msgs/msg/MapMetaData` | 23 |
| `/slam_toolbox/scan_visualization` | `sensor_msgs/msg/LaserScan` | 0 |
| `/slam_toolbox/graph_visualization` | `visualization_msgs/msg/MarkerArray` | 22 |

## Seguridad

- No Nav2.
- No RealSense.
- No locomocion autonoma.
- No `/cmd_vel`.
- No `map_saver`.
- No cambios de red.
- No credenciales GitHub en robot.
- No procesos residuales.
- No se versiona el rosbag en Git.

## Advertencia

El TF usado fue temporal diagnostico e identidad:

- `odom -> base_link`
- `base_link -> utlidar_lidar`

No esta calibrado para navegacion autonoma.

## Uso recomendado

Este rosbag sirve para:

- replay tecnico;
- visualizacion en RViz/Foxglove;
- evidencia academica del pipeline LiDAR -> scan -> SLAM -> map;
- preparacion de video/capturas para presentacion.

No debe usarse todavia como base definitiva para navegacion autonoma.

## Replay local sugerido

Con ROS 2 Foxy disponible en una maquina de analisis:

```bash
source /opt/ros/foxy/setup.bash
ros2 bag info artifacts/rosbags/hil_mapping_stationary_retry_20260605_070755
ros2 bag play artifacts/rosbags/hil_mapping_stationary_retry_20260605_070755 --clock
```

Para RViz2, visualizar como minimo:

- `Map` sobre `/map`
- `LaserScan` sobre `/scan`
- `PointCloud2` sobre `/utlidar/cloud`
- `TF`

Para Foxglove, importar el bag SQLite o convertirlo fuera del repositorio si se requiere un formato alternativo. No commitear conversiones pesadas.
