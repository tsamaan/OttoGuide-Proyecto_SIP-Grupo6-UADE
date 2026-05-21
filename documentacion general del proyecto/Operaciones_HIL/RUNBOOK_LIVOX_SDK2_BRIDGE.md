# Runbook Livox SDK2 Bridge - OttoGuide HIL

## Objetivo

Validar el bridge `ottoguide_livox_sdk_bridge` antes de mapeo HIL fisico. Este
runbook no autoriza locomocion ni reemplaza el checklist mecanico.

## Precondiciones

- Robot fisicamente asegurado y operador con `L1 + A` disponible.
- ROS 2 Foxy cargado en la Companion PC.
- Livox SDK2 instalado con `livox_lidar_api.h` y `liblivox_lidar_sdk_shared.so`.
- No hay ningun proceso `livox_ros_driver2` activo.
- Config versionada: `codigo ottoguide/config/livox/mid360_sdk2_bridge.json`.

## Validacion estatica previa

```bash
cd "/home/unitree/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide"
source /opt/ros/foxy/setup.bash
python3 scripts/validate_livox_sdk2_static.py
python3 -m json.tool config/livox/mid360_sdk2_bridge.json >/dev/null
```

## Config de red esperada

- Companion PC / host: `192.168.123.164`
- Livox MID360 default: `192.168.123.120`
- IP alternativa pendiente HIL: `192.168.123.20`
- Puertos LiDAR SDK2: `56100`, `56200`, `56300`, `56400`, `56500`
- Puertos host SDK2: `56101`, `56201`, `56301`, `56401`, `56501`

No cambiar el default a `.20` sin evidencia HIL. Si la prueba fisica demuestra
`.20`, usar un override de config por sesion y documentar el resultado.

## Arranque controlado

```bash
export OTTOGUIDE_ROOT="/home/unitree/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide"
source /opt/ros/foxy/setup.bash
source "$OTTOGUIDE_ROOT/ros2_ws/install/setup.bash"
ros2 launch ottoguide_livox_sdk_bridge mid360_sdk2_bridge.launch.py
```

Topics esperados:

- `/utlidar/cloud` (`sensor_msgs/msg/PointCloud2`)
- `/livox/imu` (`sensor_msgs/msg/Imu`)

`frame_id` esperado: `utlidar_lidar`.

## Exclusiones operativas

- No ejecutar `livox_ros_driver2` simultaneamente.
- No iniciar `slam_toolbox` hasta tener `/scan`.
- No iniciar `pointcloud_to_laserscan` hasta tener `/utlidar/cloud`.
- No ejecutar `/cmd_vel`, `LocoClient.Move`, `SportClient` ni rutas factory REST durante esta validacion.

## Validacion progresiva

1. Ejecutar validacion estatica y JSON.
2. Build del bridge en ROS 2 Foxy.
3. Verificar `ldd` contra `liblivox_lidar_sdk_shared.so`.
4. Iniciar solo el bridge SDK2.
5. Confirmar `/utlidar/cloud` y `/livox/imu`.
6. Iniciar conversion `pointcloud_to_laserscan` solo si `/utlidar/cloud` esta estable.
7. Confirmar `/scan`.
8. Recién entonces habilitar `slam_toolbox` para mapeo, sin locomocion.

Comandos de build y `ldd`:

```bash
cd "/home/unitree/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/ros2_ws"
source /opt/ros/foxy/setup.bash
colcon build --packages-select ottoguide_livox_sdk_bridge
ldd install/ottoguide_livox_sdk_bridge/lib/ottoguide_livox_sdk_bridge/livox_sdk_bridge_node | grep livox_lidar_sdk_shared
```

## GO/NO-GO Livox

GO:

- Un solo driver Livox activo: `ottoguide_livox_sdk_bridge`.
- `/utlidar/cloud` estable.
- `/livox/imu` estable.
- `/scan` disponible antes de SLAM.
- Operador de hardstop designado.

NO-GO:

- `livox_ros_driver2` y bridge SDK2 activos a la vez.
- IP MID360 no confirmada.
- `frame_id` no encaja con TF del pipeline.
- `/scan` ausente antes de `slam_toolbox`.
- Operador sin control remoto o sin acceso a `L1 + A`.
