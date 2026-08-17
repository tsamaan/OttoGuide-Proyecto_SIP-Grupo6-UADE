# OttoGuide - Handoff offline local

## Objetivo

Permitir continuar el analisis, replay y preparacion visual sin conexion fisica al robot.

## Artefactos copiados

| Artefacto | Ruta local | Uso |
|---|---|---|
| Rosbag validado | `artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755` | Replay RViz/Foxglove |
| SHA256SUMS | `artifacts/handoff_offline_20260604/manifests/SHA256SUMS.txt` | Verificacion de integridad |
| FILES_SIZES | `artifacts/handoff_offline_20260604/manifests/FILES_SIZES.txt` | Inventario local |
| Logs relevantes | `artifacts/handoff_offline_20260604/logs/` | Evidencia tecnica |
| Auditoria robot | `artifacts/handoff_offline_20260604/manifests/ROBOT_AUDIT.txt` | Estado Git, procesos y artefactos al extraer |

## Bag validado

- Duracion: `44.377 s`
- Tamano `.db3`: `512,876,544 bytes`
- `metadata.yaml`: presente, `5310 bytes`
- `ros2 bag info`: OK en robot
- Bag size reportado por ROS 2: `489.1 MiB`
- Mensajes totales: `141551`

## Topicos principales

- `/utlidar/cloud`
- `/livox/imu`
- `/scan`
- `/tf`
- `/tf_static`
- `/map`
- `/map_metadata`
- `/slam_toolbox/graph_visualization`

## Nota sobre el mapa

El mapa esta contenido en el rosbag como `/map` y `/map_metadata`.

No se genero todavia un mapa definitivo `.pgm/.yaml` con `map_saver`.

La exportacion a `.pgm/.yaml` debe realizarse despues, localmente, en un entorno Linux/ROS 2, reproduciendo el bag y usando herramientas ROS adecuadas.

## Seguridad

- No Nav2.
- No RealSense.
- No locomocion.
- No `/cmd_vel`.
- No `map_saver`.
- No credenciales GitHub en robot.
- No se versionan artefactos pesados del handoff.

## Push manual

Este documento se prepara para commit local. El push queda deliberadamente manual:

```powershell
git push target-uade robot
```
