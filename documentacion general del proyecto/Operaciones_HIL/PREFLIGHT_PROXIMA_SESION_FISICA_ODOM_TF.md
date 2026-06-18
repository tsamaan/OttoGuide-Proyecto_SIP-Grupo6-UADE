# Preflight proxima sesion fisica ODOM/TF

Objetivo: preparar una sesion read-only para descubrir fuentes reales de TF/odom sin mover el robot ni publicar comandos de locomocion.

## Alcance

Este preflight solo recolecta evidencia. No habilita navegacion, no crea mapas navegables y no activa el futuro `odom_bridge`.

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

## Preflight Git

```bash
git status --short --branch
git rev-parse --short HEAD
git remote -v
```

Nota de sesion read-only 2026-06-18:

- Robot observado en `2b7fc5c` mientras el canonico local estaba en `e85420c`.
- `git fetch origin robot` fallo por DNS (`Could not resolve host: github.com`).
- No actualizar con `merge --ff-only` si existen logs untracked sin clasificar.

Nota de iteracion sensor-gate 2026-06-18:

- El robot tenia default route por `usb1`, pero `ping 1.1.1.1`, DNS GitHub y
  TCP 443 a GitHub fallaron.
- Antes de Git, confirmar internet USB real.
- No mover `codigo ottoguide/logs/` completo: en el repo viejo incluye manifests
  versionados. Si hace falta limpiar, archivar solo archivos `??` listados por
  `git status --short --untracked-files=all`.

## Preflight ROS/CycloneDDS

```bash
printenv ROS_DISTRO
printenv RMW_IMPLEMENTATION
printenv CYCLONEDDS_URI
```

Nota de sesion read-only 2026-06-18:

- La config activa `/home/unitree/cyclonedds_ws/cyclonedds.xml` fallo con
  `Interfaces: unknown element` en Foxy/CycloneDDS.
- El config versionado `codigo ottoguide/config/cyclonedds.foxy.xml` evito ese
  error en shell temporal, pero no aparecieron publishers de sensores.
- Si un topic no existe, evitar usar `ros2 topic hz` como primera prueba: en
  esa sesion produjo `Segmentation fault` sobre topics ausentes.

## Checks read-only de topics

```bash
ros2 topic list
ros2 node list
ros2 topic info /scan
ros2 topic hz /scan
ros2 topic echo --once /scan
ros2 topic info /livox/imu || true
ros2 topic echo --once /livox/imu || true
ros2 topic info /utlidar/cloud || true
```

## Checks TF/odom

```bash
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
- Cualquier fuente candidata debe cumplir el contrato en `documentacion general del proyecto/Arquitectura/ODOM_BRIDGE_CONTRACT.md`.

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

## Criterios GO/NO-GO

GO read-only:

- Runtime reporta `ROS_DISTRO=foxy` y `rmw_cyclonedds_cpp`.
- `/scan` responde con frecuencia medible y `frame_id` documentado.
- Cualquier candidato de estado Unitree se inspecciona sin mover robot.

NO-GO:

- Falta operador fisico o hardstop.
- El comando requerido activa locomocion, Nav2 fisico o publicacion de velocidad.
- La fuente candidata solo entrega `LowState`, `SportModeState`, IMU o joints sin pose/twist traslacional.

## Evidencia a guardar

- Salida de `ros2 topic list`.
- Salida de `ros2 node list`.
- `ros2 topic info` de `/scan`, `/livox/imu`, `/utlidar/cloud`, `/tf`, `/tf_static`, `/odom`, `/map` y `/map_metadata`.
- Captura textual de frecuencia de `/scan`.
- Nombre exacto, tipo, frecuencia y semantica declarada de cualquier fuente candidata de pose/twist.

## Que NO ejecutar

- No ejecutar `ottoguide-map start`.
- No ejecutar Nav2 fisico ni bringup con control.
- No ejecutar `stand`, `sit`, `walk`, `damp` ni comandos de locomocion desde este preflight.
- No publicar `/cmd_vel`.
- No cambiar configuracion persistente de red.
