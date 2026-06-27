# Capture Bridge Subscriber-Only - Unitree G1 EDU 8

## Objetivo

Capturar telemetria nativa del G1 junto con Livox sin introducir control, odometria, navegacion ni movimiento.

```text
Unitree DDS domain 0 / eth0
        -> native tap receive-only
        -> AF_UNIX SOCK_DGRAM
        -> ROS 2 Foxy receiver
        -> /unitree/*
        -> ottoguide-map
        -> rosbag2
```

## Procesos

El tap C++ enlaza explicitamente el target oficial estatico `libunitree_sdk2.a`. Crea canales de recepcion y no contiene writers ni clientes RPC. El nodo Python no importa ni carga Unitree SDK2; solo recibe datagramas locales y publica la allowlist ROS.

## Evidencia DDS

| Canal | Estado | Tasa nativa observada | Uso |
|---|---|---:|---|
| `rt/lowstate` | confirmado | ~1052 Hz | IMU, FSM de bajo nivel y `wireless_remote` |
| `rt/secondary_imu` | confirmado | ~1052 Hz | IMU secundaria |
| `rt/sportmodestate` | confirmado | ~100 Hz | FSM sport |
| `rt/lf/lowstate` | opcional/variable | 0 Hz y ~20 Hz en sesiones distintas | contador diagnostico; nunca remote source |

La configuracion observada de `master_service` usa domain 0 y `eth0`; esto no demuestra por si solo que publique un canal concreto. `slam_nav` estaba deshabilitado en esa configuracion.

## Remote humano

Los 40 bytes de `LowState.wireless_remote` se decodifican con `unitree::common::REMOTE_DATA_RX` del header instalado. No se mantiene un layout paralelo supuesto.

```text
axes: [lx, ly, rx, ry]
buttons: [R1, L1, Start, Select, R2, L2, F1, F2,
          A, B, X, Y, Up, Right, Down, Left]
```

Estos datos representan intencion humana registrada. Ningun componente los convierte en acciones.

## IPC, tasas y diagnostico

- Socket: `/tmp/ottoguide_unitree_capture.sock`.
- Transporte: `AF_UNIX SOCK_DGRAM`, JSON v1, maximo 4096 bytes.
- LowState combinado: hasta 50 Hz.
- IMU secundaria: hasta 100 Hz.
- FSM: hasta 10 Hz.
- Health: 1 Hz.
- El tap contabiliza recepciones, envios y drops IPC.
- El bridge contabiliza errores de parseo/socket, edad del ultimo dato y edad de health.
- Health pasa a WARN por drops/errores y a ERROR si falta socket o health supera 5 segundos.

## Linking reproducible

El build usa:

- `lib/aarch64/libunitree_sdk2.a` explicitamente.
- `-isystem` para `include`, `thirdparty/include` y `thirdparty/include/ddscxx`.
- RUNPATH para `lib/aarch64` y `thirdparty/lib/aarch64`.
- `libddscxx.so.0` y `libddsc.so.0` resueltas sin `LD_LIBRARY_PATH` manual.
- Ningun `DT_NEEDED` para una biblioteca Unitree shared.

## ROS allowlist

- `/unitree/remote_joy`
- `/unitree/lowstate_imu`
- `/unitree/secondary_imu`
- `/unitree/fsm_state`
- `/unitree/lowstate_summary`
- `/unitree/sdk_health`

## Niveles de evidencia

- L0: `/utlidar/cloud`, `/livox/imu` y `/scan`.
- L1: L0, `/unitree/remote_joy` y gaps maximos de un segundo.
- L2: requiere pose XY/twist validado o `/odom` de tipo `nav_msgs/msg/Odometry`; IMU, joints, LowState y FSM no alcanzan.
- L3: requiere L2 valido mas localizacion, `/map`, `/tf` y `/tf_static`.

## Invariantes

- Robot stationary durante la validacion.
- Sin control de locomocion ni postura.
- Sin publishers `/cmd_vel`, `/odom`, `/tf` o `/tf_static`.
- Sin Nav2 ni SLAM.
- Sin cambios en SDK, `/unitree`, red o servicios del robot.
