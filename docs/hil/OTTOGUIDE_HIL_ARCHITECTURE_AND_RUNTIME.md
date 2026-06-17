# OttoGuide HIL architecture and runtime

## Diagrama textual

```text
GitHub target-uade/robot
        |
        | git fetch / bundle / version control
        v
Notebook HIL 192.168.123.101
        |
        | SSH, scp, ROS/DDS discovery
        v
Companion PC 192.168.123.164
        |
        | ROS 2 Foxy + CycloneDDS
        | sensor stack scan_gate
        v
LiDAR/IMU topics: /utlidar/cloud, /livox/imu, /scan

Locomotion controller 192.168.123.161
        |
        | ping observed only
        v
No software locomotion from OttoGuide in validated flow

Artifacts offline
        |
        v
rosbags, manifests, hashes, reports, future map/waypoint extraction
```

## Esquema cliente-servidor

| Componente | Rol |
|---|---|
| Notebook HIL | Cliente SSH/scp, auditoria Git, almacenamiento de artifacts copiados. |
| Companion PC | Servidor SSH, host ROS 2 Foxy, bridge Livox, scripts HIL. |
| Locomotion controller | Host observado en red; no controlado por OttoGuide durante estas pruebas. |
| ROS/DDS | Middleware peer-to-peer para topics, servicios y descubrimiento. |
| GitHub | Control de versiones, no runtime del robot. |
| Artifacts offline | Rutas para rosbags, logs, mapas y reportes fuera de Git. |

## Roles runtime

| Rol | Estado actual |
|---|---|
| Sensor stack | `scan_gate.launch.py` recupera LiDAR/IMU/scan. |
| Mapping completo | Parcial; falta TF/odom/map en vivo. |
| Raw sensor capture | Ready conceptualmente si `/utlidar/cloud` o `/scan` estan vivos. |
| API FastAPI OttoGuide | Implementada en codigo, no expuesta en runtime observado. |
| Navegacion autonoma | No validada. |

## Flujo de captura previsto

1. `prep`: cargar ROS 2 Foxy/CycloneDDS, verificar sensores y levantar `scan_gate` si hace falta.
2. `start`: crear `artifacts/ottoguide_map_<RUN_ID>/` y grabar rosbag raw sensor-only en background.
3. `status`: leer PID, bag dir, tamano, topics y logs sin modificar estado.
4. `stop`: enviar SIGINT al PID de rosbag y generar `ros2 bag info`.
5. `finalize`: generar manifiestos, hashes, README e intentar mapa solo si `/map` existe.
6. `package`: crear `.tar.gz` en `/tmp` e imprimir comando `scp`.

## Raw capture vs mapping completo vs navegacion autonoma

| Modo | Requisitos | Estado | Resultado esperado |
|---|---|---|---|
| Raw sensor capture | `/utlidar/cloud` o `/scan` | Ready con sensor stack activo | Rosbag para replay/offline |
| Mapping completo | Sensores, TF, odom/SLAM y `/map` | Parcial | PGM/YAML solo si `/map` existe |
| Navegacion autonoma | Mapa, localizacion, Nav2, safety y validacion fisica | No validado | No ejecutar en esta fase |

## Estado actual

| Area | Resultado |
|---|---|
| Raw sensor capture | READY si sensor stack esta vivo |
| Mapping completo | PARTIAL por falta de `/tf`, `/tf_static`, `/odom`, `/map` |
| Navegacion autonoma | NO VALIDADA |
| Movimiento por agente | Prohibido |
| `/cmd_vel` por agente | Prohibido |

## Estructura del proyecto usada

| Ruta | Uso |
|---|---|
| `codigo ottoguide/` | Base runtime del robot. |
| `codigo ottoguide/config/` | Configuracion ROS/DDS, incluido CycloneDDS. |
| `codigo ottoguide/ros2_ws/src/ottoguide_livox_sdk_bridge/` | Bridge Livox y `scan_gate`. |
| `codigo ottoguide/tools/hil/` | Scripts HIL de auditoria, mapping y captura. |
| `codigo ottoguide/docs/hil/` | Runbooks HIL dentro de codigo robot. |
| `docs/hil/` | Documentacion versionable de operacion y auditoria. |
| `artifacts/` | Evidencia local, rosbags, logs y paquetes fuera del flujo de commit. |

## Seguridad operacional

- El agente no publica `/cmd_vel`.
- El agente no ejecuta stand/sit/walk ni cambia modos motores.
- El agente no ejecuta Nav2 autonomo.
- El movimiento fisico, si ocurre, debe ser por control remoto humano.
- La grabacion se detiene con SIGINT limpio al PID del rosbag.
- Los artifacts pesados quedan fuera de Git.
- No se toca `192.168.123.120`.

## Pendiente antes de locomocion automatica

1. Mantener el ejecutable `ottoguide-map` sincronizado entre robot, Windows y `target-uade/robot`.
2. Obtener rosbag raw real de oficina.
3. Reproducir offline y reconstruir TF/SLAM.
4. Exportar y limpiar mapa.
5. Extraer waypoints.
6. Validar AMCL/Nav2 offline.
7. Definir prueba fisica controlada con parada segura antes de cualquier movimiento autonomo.
