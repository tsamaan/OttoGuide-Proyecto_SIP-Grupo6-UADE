# OttoGuide — Runbook de replay del rosbag HIL

## Objetivo

Reproducir y visualizar localmente el rosbag HIL validado para generar evidencia técnica y visual del pipeline:

LiDAR MID360 -> /utlidar/cloud -> /scan -> TF -> SLAM -> /map

## Estado base

- Commit: `4c051c4`
- Bag: `artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755`
- Duración: `44.377 s`
- Tamaño `.db3`: `512,876,544 bytes`
- `ros2 bag info`: OK en robot
- Validación local: No ejecutada porque ros2 no estaba disponible en el entorno local (Windows). Validación válida en base a la ejecución en el robot.

## Tópicos principales

| Tópico | Tipo | Mensajes |
|---|---|---:|
| `/utlidar/cloud` | `sensor_msgs/msg/PointCloud2` | 66302 |
| `/livox/imu` | `sensor_msgs/msg/Imu` | 8866 |
| `/scan` | `sensor_msgs/msg/LaserScan` | 65425 |
| `/tf` | `tf2_msgs/msg/TFMessage` | 888 |
| `/tf_static` | `tf2_msgs/msg/TFMessage` | 2 |
| `/map` | `nav_msgs/msg/OccupancyGrid` | 23 |
| `/map_metadata` | `nav_msgs/msg/MapMetaData` | 23 |
| `/slam_toolbox/graph_visualization` | `visualization_msgs/msg/MarkerArray` | 22 |

## Replay con ROS 2

Desde Linux/WSL2/Ubuntu con ROS 2:

```bash
cd /mnt/c/Users/lucas/Documents/OttoGuide-Proyecto_SIP-Grupo6-UADE

source /opt/ros/foxy/setup.bash 2>/dev/null || true
source /opt/ros/humble/setup.bash 2>/dev/null || true

ros2 bag info artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755

ros2 bag play artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755 --clock --loop
```

## Visualización en RViz2

En otra terminal:

```bash
rviz2
```

Configuración sugerida:

* Fixed Frame: `map`
* Display `Map`: topic `/map`
* Display `LaserScan`: topic `/scan`
* Display `PointCloud2`: topic `/utlidar/cloud`
* Display `TF`
* Display `MarkerArray`: topic `/slam_toolbox/graph_visualization`

## Capturas/video sugeridos

Capturar:

1. Mapa `/map` visible.
2. LaserScan `/scan` sobre el mapa.
3. Nube de puntos `/utlidar/cloud`.
4. Árbol TF.
5. Visualización del grafo de SLAM si se ve correctamente.
6. Breve video de replay con el bag en loop.

## Foxglove

Usar Foxglove Studio si puede abrir el bag ROS 2 SQLite directamente. Si no, preparar conversión fuera del repositorio y no commitear archivos pesados convertidos.

## Exportar /map a .pgm/.yaml

El mapa está dentro del rosbag como `/map` y `/map_metadata`.

Para exportarlo localmente, reproducir el bag y usar herramientas ROS 2 disponibles, por ejemplo `map_saver_cli` si el paquete correspondiente está instalado.

Ejemplo orientativo:

```bash
ros2 bag play artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755 --clock --loop
```

En otra terminal:

```bash
ros2 run nav2_map_server map_saver_cli -f artifacts/maps/ottoguide_hil_stationary_map
```

Notas:

* Esto debe ejecutarse solo localmente, no en el robot.
* No implica navegación autónoma.
* No usar el mapa como definitivo para navegación hasta calibrar TF y validar odometría.

## Advertencias

* El TF usado en la sesión HIL fue temporal diagnóstico.
* No hay navegación autónoma validada.
* No hay Nav2 validado.
* No hay `/cmd_vel`.
* No usar esta evidencia como autorización para movimiento físico.
