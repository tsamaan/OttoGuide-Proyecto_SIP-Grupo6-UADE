# Preflight proxima sesion fisica ODOM/TF

Objetivo: preparar una sesion read-only para descubrir fuentes reales de TF/odom sin mover el robot ni publicar comandos de locomocion.

## Condiciones de seguridad

- Robot supervisado por operador responsable y hardstop disponible.
- Prohibido publicar `/cmd_vel`.
- Prohibido ejecutar Nav2 fisico, `ottoguide-map start`, `stand`, `sit`, `walk` o `damp` desde este preflight.
- No activar locomocion ni cambiar red persistente.

## Estado esperado a verificar

```text
ROS_DISTRO=foxy
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
CYCLONEDDS_URI=file:///home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/config/cyclonedds.foxy.xml
```

## Checks read-only

```bash
ros2 topic list
ros2 node list
ros2 topic info /scan
ros2 topic hz /scan
ros2 topic info /livox/imu || true
ros2 topic info /utlidar/cloud || true
ros2 topic info /tf || true
ros2 topic info /tf_static || true
ros2 topic info /odom || true
ros2 topic info /map || true
ros2 topic info /map_metadata || true
```

## Candidatos Unitree a investigar

- DDS HG `rt/lowstate`: IMU/joints/FSM; no asumir pose XY ni twist traslacional.
- DDS HG `rt/sportmodestate`: confirmar tipo real y campos; no asumir `/odom`.
- Peer `192.168.123.161`: revisar solo de forma pasiva si expone estado traslacional.

## TF minimo a validar como diseno, no como prueba fisica

```text
map -> odom
odom -> base_link
base_link -> utlidar_lidar
base_link -> imu_link
```

`base_link -> utlidar_lidar` requiere medicion real del extrinseco. Cualquier TF temporal identidad debe marcarse como diagnostico offline y no como geometria validada.

## Criterios de no avance

- No aparece una fuente traslacional confiable para `/odom`.
- `/scan` no tiene frecuencia estable o frame coherente.
- No se puede confirmar semantica de frames.
- Cualquier paso requeriria mover el robot, activar locomocion o publicar `/cmd_vel`.
