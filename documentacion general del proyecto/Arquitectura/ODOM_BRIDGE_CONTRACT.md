# ODOM bridge contract

Este documento define el contrato offline del futuro `odom_bridge` de OttoGuide. El objetivo futuro seria publicar `/odom` como `nav_msgs/msg/Odometry` solo si existe una fuente traslacional validada en HIL.

Este contrato no valida navegacion autonoma. Este contrato no valida mapa navegable. Este contrato no habilita Nav2 fisico. Este contrato no publica `/cmd_vel`. Este contrato no implementa un nodo ROS runtime.

## Entradas candidatas

### Aceptable solo con validacion HIL

- Canal DDS/Unitree HG que entregue pose XY y yaw o twist corporal validable.
- Fuente externa de localizacion/SLAM offline solo para replay, no para hardware.

### No aceptable como odometria traslacional por si sola

- `LowState` solo.
- `SportModeState` solo.
- IMU sola.
- Joints solos.
- TF identidad temporal.
- Mapa estacionario.

Para G1/G1 EDU la linea DDS/IDL correcta a investigar es `unitree_hg`. No asumir `unitree_go` para G1 salvo en documentos historicos marcados como no confirmados.

## Salida esperada

Contrato de mensaje futuro, no publicacion runtime actual:

```text
Topic: /odom
Type: nav_msgs/msg/Odometry
header.frame_id: odom
child_frame_id: base_link
pose.pose.position.x: metros
pose.pose.position.y: metros
pose.pose.position.z: 0.0 salvo evidencia contraria
pose.pose.orientation: quaternion derivado de yaw/orientacion validada
twist.twist.linear.x: m/s si existe fuente valida
twist.twist.angular.z: rad/s si existe fuente valida
```

No publicar `/odom` si la fuente traslacional no esta validada.

## Frames

```text
map -> odom
  Futuro: localizacion/SLAM. No validado fisicamente.

odom -> base_link
  Dinamico. Solo desde odom_bridge si existe fuente traslacional valida.

base_link -> utlidar_lidar
  Estatico. Extrinseco pendiente de medicion fisica.

base_link -> imu_link o livox_imu
  Opcional. Pendiente de confirmar frame real de /livox/imu.
```

No usar TF identidad como evidencia fisica. No usar mapa estacionario como evidencia de navegacion. No tratar `frame_id=utlidar_lidar` como `base_link`.

## Covarianzas

- Covarianzas deben ser explicitas.
- Si la fuente no esta calibrada, `x`, `y` y `yaw` deben tener varianzas altas.
- Si no hay twist validado, twist debe marcarse como no confiable o no publicarse.
- No usar covarianzas cero salvo medicion validada.

Valores placeholder offline, no validados:

```text
pose covariance:
x/y >= 0.50 m^2 si no esta calibrado
z alto o fijo segun contrato planar
roll/pitch altos si no se usan
yaw >= 0.10 rad^2 si no esta calibrado

twist covariance:
linear.x >= 0.50
linear.y alto
angular.z >= 0.10
```

## Flags de seguridad

El futuro bridge debe estar deshabilitado por defecto. Para permitir activacion futura deben cumplirse todos estos flags:

```text
OTTOGUIDE_ENABLE_ODOM_BRIDGE=1
OTTOGUIDE_HIL_SESSION_CONFIRMED=1
OTTOGUIDE_ODOM_SOURCE_VALIDATED=1
OTTOGUIDE_ODOM_SOURCE=<nombre_fuente_validada>
```

Condiciones:

- No publicar `/odom` si no hay fuente traslacional validada.
- No publicar `/odom` desde `LowState` solo.
- No publicar `/odom` desde `SportModeState` solo.
- No publicar `/cmd_vel` nunca desde este bridge.
- No activar automaticamente desde startup general.

## Criterios de activacion HIL

Para permitir publicacion real de `/odom` en una sesion fisica futura:

1. Operador fisico presente.
2. Hardstop disponible.
3. Robot estable.
4. Fuente DDS/Unitree identificada como pose/twist traslacional.
5. Frecuencia de fuente medida.
6. Frames confirmados.
7. Extrinseco `base_link -> utlidar_lidar` medido o declarado como provisional.
8. Covarianzas configuradas.
9. No hay publishers inesperados a `/cmd_vel`.
10. Logs de auditoria activos.

## Contrato offline testeable

El modulo `codigo ottoguide/src/navigation/odom_bridge_contract.py` implementa solo reglas puras de aceptacion, flags, frames y covarianzas. No importa `rclpy`, `nav_msgs` ni `geometry_msgs`; no inicializa nodos ROS 2; no publica topics; no conecta al robot.
