# Validación física — sesión r0b1-20260717T215047Z

## Contexto

Sesión de telemetría física real capturada el 2026-07-17 sobre un Unitree G1
EDU, mediante la herramienta HIL read-only descrita en
`docs/Arquitectura/HIL_READONLY_OBSERVABILITY_BOUNDARY.md`. El robot
permaneció inmóvil durante toda la sesión; el agente nunca envió comandos de
movimiento.

## Qué se observó

```text
source_profile = REAL
session_id     = r0b1-20260717T215047Z
seq            = estrictamente creciente

WebSocket      = 101 Switching Protocols (handshake real, verificado con
                 cliente websockets estandar y a mano por RFC 6455)
motors         = 29 (contrato LowState completo: q_rad, q_deg, dq, ddq,
                 tau_est, temperature por articulacion)
IMU            = quaternion, gyroscope, accelerometer, rpy_deg recibidos
odom           = rt/odommodestate: position/velocity/yaw_speed recibidos
lf_odom        = rt/lf/odommodestate: position/velocity/yaw_speed recibidos
lidar          = rt/utlidar/cloud_livox_mid360: metadata + puntos (~20000+)
BMS            = probe aceptado (20/20 mensajes coherentes); soc=23,
                 voltage_v=45.34, current_a=-2.03,
                 relative_cell_sum_error=0.001 (escala verificada)

LowState Hz  = 451.8
Odom Hz      = 417.1
LF Odom Hz   = 19.8
LiDAR Hz     = 9.9

dds_writers_created         = 0
movement_clients_imported   = 0
movement_commands_sent      = 0
browser POST/PUT/PATCH/DELETE = 0 (405 READ_ONLY_DEMO)
console errors               = 0
external requests            = 0
```

## Afirmaciones permitidas

- Telemetría física real mostrada en un dashboard Web.
- 29 estados de motor recibidos y decodificados correctamente.
- IMU recibido.
- Mensajes de odometría principal y LF recibidos.
- Metadata de LiDAR recibida.
- Conversión canónica de BMS observada (con `relative_cell_sum_error` como
  chequeo independiente de escala).
- Runtime DDS read-only observado (DataReader only, cero writers).
- Flujo WebSocket real observado (handshake 101, frames REAL entregados a
  10 Hz).

## Afirmaciones prohibidas

Ver `PHYSICAL_VALIDATION_LIMITATIONS.md` — esta sesión **no** valida
`/odom` como fuente de control, TF, Nav2, navegación autónoma, recuperación
física de cable, recorrido manual, ni ninguna demo concurrente de IA legacy.

## Evidencia preservada

```text
R0B1_LIVE_MONITOR_REPORT.json
REMOTE_HEALTH.json
REMOTE_STATUS.json
REMOTE_LIVE_FRAMES_10.jsonl   (tambien usado como fixture de replay)
REMOTE_STATIC_GATE.json / REMOTE_STATIC_GATE_R0B.json
R0B1_REMOTE_HASH_PROOF.json
LIVE_UI_NETWORK_SUMMARY.json
```

## Dato crudo remoto

El raw completo (chunks JSONL de LowState/odom/LiDAR/BMS a resolución
completa) permanece únicamente en el Companion. Ver
`REMOTE_RAW_DATA_RETRIEVAL_PENDING.md`.
