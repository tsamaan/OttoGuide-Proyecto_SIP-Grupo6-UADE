# Plan de captura total y replay progresivo - Unitree G1 EDU 8

## Estado

El flujo sensor-only Livox fue validado durante 180 segundos. La siguiente capa agrega telemetria Unitree mediante un bridge receive-only de dos procesos. Esta etapa no implementa movimiento, odometria, TF, SLAM ni navegacion.

## Arquitectura de captura

```text
Livox ROS topics --------------------+
                                      +-> ottoguide-map -> rosbag2
Unitree DDS -> tap -> AF_UNIX -> ROS -+
```

`ottoguide-map plan` debe mostrar por separado:

1. Topics ROS descubiertos y seleccionados para grabacion.
2. Canales DDS nativos esperados a traves del capture bridge.

Los canales DDS no se descubren con `ros2 topic list`.

## Gates progresivos

| Nivel | Requisito | Estado esperado en stationary |
|---|---|---|
| L0 | `/utlidar/cloud`, `/livox/imu`, `/scan` | ready |
| L1 | L0, `/unitree/remote_joy`, continuidad <= 1 s | candidate o ready |
| L2 | L1 y pose/twist validado o `/odom` estandar | not ready |
| L3 | L2, localizacion, `/map`, `/tf`, `/tf_static` | not ready |

LowState, IMU, joints y FSM aportan contexto de captura pero no satisfacen L2.

## Preflight stationary

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge plan
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge build
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge start
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge validate
./tools/hil/ottoguide-map prep
./tools/hil/ottoguide-map plan
```

Antes de grabar se exige:

- Los seis topics `/unitree/*` de la allowlist.
- Los tres topics Livox base.
- Cero publishers `/cmd_vel` y `/odom`.
- Nav2 y SLAM ausentes.
- Robot inmovil.

## Validacion corta

```bash
./tools/hil/ottoguide-map timed \
  --duration 10 \
  --label "unitree_capture_bridge_stationary_validation"
./tools/hil/ottoguide-map finalize
```

Luego se ejecuta `analyze_capture_sqlite.py` en modo read-only. La captura se acepta solo si contiene sensores, los seis topics Unitree y ausencia de topics de control.

## Cierre

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge stop
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge status
```

El cierre debe dejar tap y nodo ROS detenidos, socket eliminado y cero procesos huerfanos. La evidencia liviana excluye DB3, bags y binarios.
