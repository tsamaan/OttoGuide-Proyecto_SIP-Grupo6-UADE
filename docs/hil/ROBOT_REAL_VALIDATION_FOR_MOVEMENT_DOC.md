# Validación real del robot para documentación técnica - OttoGuide movimiento y preparación de autonomía

## 1. Resultado ejecutivo

**PARTIAL BASELINE READY**

La documentación técnica del pilar de movimiento puede generarse con una base real y auditada para red HIL, Git, ROS 2 Foxy, CycloneDDS, stack de sensores, topics raw y ejecutable `ottoguide-map`.

La base es parcial porque en el runtime actual faltan `/tf`, `/tf_static`, `/odom`, `/map` y `/map_metadata`. Por lo tanto no se debe afirmar mapping completo, mapa apto para navegación ni autonomía física operativa.

## 2. Alcance

Esta validación cubre:

- Red HIL, SSH, puertos TCP observados y servicios internos.
- Versión Git real en el robot.
- ROS 2 Foxy, CycloneDDS y topics disponibles.
- Stack sensor-only basado en Livox y `pointcloud_to_laserscan`.
- APIs/endpoints presentes en código y runtime HTTP observado.
- Ejecutable de campo `ottoguide-map`.
- Límites actuales de seguridad y pendientes.

No se movió el robot, no se publicó `/cmd_vel`, no se ejecutó Nav2 y no se inició captura.

## 3. Git y versión

| Elemento | Resultado | Evidencia |
|---|---|---|
| Rama robot | `robot` | Validado en robot real |
| HEAD robot | `b07d362` | Validado en robot real |
| Commit | `docs(hil): document robot runtime and add map executable` | Validado en robot real |
| Remoto origin | `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git` | Validado en robot real |
| `ottoguide-map` | Trackeado y ejecutable | Validado en robot real |
| Working tree | Sin cambios tracked; logs untracked locales | Validado en robot real |

Archivos versionados relevantes:

- `codigo ottoguide/tools/hil/ottoguide-map`
- `codigo ottoguide/tools/hil/office_sensor_capture.sh`
- `codigo ottoguide/docs/hil/OTTOGUIDE_MAP_EXECUTABLE_QUICKSTART.md`
- `docs/hil/GITHUB_ROBOT_BRANCH_VALIDATION.md`
- `docs/hil/OTTOGUIDE_HIL_ARCHITECTURE_AND_RUNTIME.md`
- `docs/hil/ROBOT_FACTORY_BASELINE_AND_OTTOGUIDE_EVOLUTION.md`
- `docs/hil/ROBOT_NETWORK_PORTS_API_INVENTORY.md`

## 4. Red HIL

| IP | Rol | Estado | Evidencia | Categoria |
|---|---|---|---|---|
| `192.168.123.101` | Notebook HIL | Activo desde Windows; ping desde robot sin respuesta | `Test-NetConnection` desde notebook; `ping` desde robot falla | Observado en red HIL |
| `192.168.123.164` | Companion PC | Activo | `eth0 UP 192.168.123.164/24`, SSH OK | Validado en robot real |
| `192.168.123.161` | Locomotion controller | Activo por ICMP; TCP 22/8080 no expuesto observado | `ping -c 3` OK desde robot y Windows | Observado en red HIL |
| `192.168.123.120` | Host HIL no identificado | No tocar | Detectado en sesiones previas | Pendiente de validación |

Interfaces relevantes del robot:

- `eth0`: `192.168.123.164/24`, red HIL.
- `usb1`: `10.21.209.158/24`, default route via `10.21.209.7`.
- `docker0`: `172.17.0.1/16`, down.

## 5. Puertos y servicios

| Host | Puerto | Resultado | Interpretación | Categoría |
|---|---:|---|---|---|
| `192.168.123.164` | 22 | OPEN | SSH companion | Observado en red HIL |
| `192.168.123.164` | 80 | OPEN | HTTP expuesto; propósito no verificado | Observado en red HIL |
| `192.168.123.164` | 443 | CLOSED/NO RESPONSE | HTTPS no expuesto observado | Observado en red HIL |
| `192.168.123.164` | 8000 | CLOSED/NO RESPONSE | FastAPI dev no observado en runtime | Observado en red HIL |
| `192.168.123.164` | 8001 | CLOSED/NO RESPONSE | API dev no observada | Observado en red HIL |
| `192.168.123.164` | 8080 | CLOSED/NO RESPONSE | HTTP alternativo no observado | Observado en red HIL |
| `192.168.123.164` | 11434 | CLOSED/NO RESPONSE | Ollama no expuesto por red HIL; loopback observado | Observado en red HIL |
| `192.168.123.161` | 22 | CLOSED/NO RESPONSE | SSH no expuesto observado | Observado en red HIL |
| `192.168.123.161` | 8080 | CLOSED/NO RESPONSE | Servicio no expuesto observado | Observado en red HIL |
| `192.168.123.164` | UDP 56000/56101/56201/57698 | UDP observado | Livox bridge | Validado en robot real |
| `192.168.123.164` | UDP 7400/7401/7410-7415 | UDP observado | DDS/RTPS ROS 2 | Validado en robot real |
| `127.0.0.1` | 11434 | LISTEN | Ollama local-only | Validado en robot real |
| `0.0.0.0` | 4000 | LISTEN | Servicio expuesto; propósito no verificado | Validado en robot real |

No se atribuye un puerto cerrado al fabricante sin evidencia oficial; cuando un puerto no responde se documenta como no expuesto observado o sin respuesta.

## 6. ROS/DDS

| Elemento | Resultado | Categoria |
|---|---|---|
| ROS distro | `foxy` | Validado en robot real |
| `ROS_DOMAIN_ID` | vacio/default | Validado en robot real |
| RMW | `rmw_cyclonedds_cpp` | Configurado por OttoGuide |
| CycloneDDS URI | `config/cyclonedds.foxy.xml` | Configurado por OttoGuide |
| Network interface DDS | `eth0` | Configurado por OttoGuide |
| Multicast | `false` | Configurado por OttoGuide |
| Peers | `192.168.123.161`, `192.168.123.164` | Configurado por OttoGuide |

Relacion con red HIL: CycloneDDS queda acotado a `eth0` y peers fijos de companion/locomotion. Esto evita depender de multicast en la red HIL observada.

## 7. Topics ROS

| Topic | Tipo | Estado | Publisher | Frecuencia | frame_id | Uso |
|---|---|---|---|---|---|---|
| `/utlidar/cloud` | `sensor_msgs/msg/PointCloud2` | Activo | `livox_sdk_bridge_node` | No medida por `ros2 topic hz` en esta sesion; mensajes recibidos | `utlidar_lidar` | Nube raw LiDAR para replay/mapping offline |
| `/livox/imu` | `sensor_msgs/msg/Imu` | Activo | `livox_sdk_bridge_node` | No medida por `ros2 topic hz` en esta sesion; mensajes recibidos | `utlidar_lidar` | IMU Livox para sincronizacion/replay |
| `/scan` | `sensor_msgs/msg/LaserScan` | Activo | `pointcloud_to_laserscan` | `scan_time` observado `0.10000000149`; hz CLI sin salida medible | `utlidar_lidar` | LaserScan 2D derivado para SLAM futuro |
| `/tf` | No disponible | Faltante en runtime actual | Ninguno observado | No aplica | No aplica | Requisito para mapping completo |
| `/tf_static` | No disponible | Faltante en runtime actual | Ninguno observado | No aplica | No aplica | Requisito para frames estaticos |
| `/odom` | No disponible | Faltante en runtime actual | Ninguno observado | No aplica | No aplica | Requisito para localizacion/navegacion |
| `/map` | No disponible | Faltante en runtime actual | Ninguno observado | No aplica | No aplica | Requisito para export PGM/YAML directo |
| `/map_metadata` | No disponible | Faltante en runtime actual | Ninguno observado | No aplica | No aplica | Metadata de mapa |
| `/cmd_vel` | No disponible | Faltante en runtime actual; no publicado por agente | Ninguno observado | No aplica | No aplica | Solo evidencia si aparece, nunca publicar desde captura |

Nodos observados:

- `/livox_sdk_bridge_node`
- `/pointcloud_to_laserscan`

Servicios observados: servicios de parametros de esos dos nodos. Actions: ninguna observada.

## 8. Stack de sensores

| Componente | Estado | Evidencia | Categoria |
|---|---|---|---|
| `scan_gate.launch.py` | Vivo | Proceso `ros2 launch ottoguide_livox_sdk_bridge scan_gate.launch.py` PID observado | Validado en robot real |
| `livox_sdk_bridge_node` | Vivo | Publica `/utlidar/cloud` y `/livox/imu` | Validado en robot real |
| `pointcloud_to_laserscan_node` | Vivo | Publica `/scan`, remapea `cloud_in:=/utlidar/cloud` | Validado en robot real |
| `pointcloud_to_laserscan.yaml` | Presente | Config en `ros2_ws/src/.../config/` | Presente en codigo |
| `slam_toolbox_mapping.yaml` | Presente | Config en repo | Presente en codigo |
| Paquetes Nav2/SLAM | Instalados | `ros2 pkg list` muestra `slam_toolbox`, `nav2_*`, `nav2_map_server`, `nav2_amcl` | Validado en robot real |
| Nav2 runtime | No observado | No hay nodos Nav2 corriendo | Pendiente de validacion |

## 9. APIs/endpoints

| Endpoint/API | Metodo | Archivo | Runtime | Estado |
|---|---|---|---|---|
| `/tour/start` | POST | `codigo ottoguide/src/api/server.py` | No observado en puerto 8000 | Presente en codigo, no observado en runtime |
| `/tour/pause` | POST | `codigo ottoguide/src/api/server.py` | No observado en puerto 8000 | Presente en codigo, no observado en runtime |
| `/emergency` | POST | `codigo ottoguide/src/api/server.py` | No observado en puerto 8000 | Presente en codigo, no observado en runtime |
| `/status` | GET | `codigo ottoguide/src/api/server.py` | No observado en puerto 8000 | Presente en codigo, no observado en runtime |
| WebSocket telemetry | WebSocket manager | `codigo ottoguide/src/api/websocket_manager.py` | No observado en runtime | Presente en codigo, no observado en runtime |
| Ollama `/api/generate` | POST cliente | `codigo ottoguide/src/interaction/conversation_manager.py` | `127.0.0.1:11434` escucha; no expuesto por red HIL | Presente en codigo y loopback observado |
| Unitree SDK examples | DDS/client examples | `/home/unitree/unitree_sdk2` | No ejecutados | Observado en imagen/sistema del robot |

`curl http://127.0.0.1:8000/docs`, `/openapi.json` y `/status` fallaron con connection refused. No se inicio servidor.

## 10. Ejecutable `ottoguide-map`

| Comando | Funcion documentada | Estado |
|---|---|---|
| `prep` | Carga ROS/CycloneDDS, verifica topics y levanta/verifica sensor stack si hace falta | Ejecutado; PASS para raw capture, PARTIAL por falta de TF |
| `start` | Inicia rosbag raw sensor-only | No ejecutado |
| `timed` | Captura raw por duracion fija | No ejecutado |
| `status` | Muestra PID, BAG_DIR, tamano y logs | No ejecutado |
| `stop` | SIGINT limpio al PID de rosbag | No ejecutado |
| `finalize` | `ros2 bag info`, manifiestos, hashes y map_saver solo si `/map` existe | No ejecutado |
| `package` | Tarball en `/tmp` y comando `scp` | No ejecutado |

`prep` observo `/utlidar/cloud`, `/livox/imu` y `/scan`, no relanzo el stack y no inicio captura.

## 11. Diferencia entre raw capture, mapping completo y navegacion autonoma

| Modo | Estado | Requisitos | Resultado permitido |
|---|---|---|---|
| Raw capture | Disponible parcialmente | `/utlidar/cloud` o `/scan` vivos | Rosbag para replay/offline |
| Mapping completo | Parcial | Sensores + `/tf` + `/odom` + `/map` o SLAM activo | No validado en runtime actual |
| Navegacion autonoma | No validada | Mapa, localizacion, Nav2, safety, `/cmd_vel` controlado | No ejecutar |

## 12. Datos no verificados

- Datos oficiales de fabrica del Unitree G1 EDU.
- APIs oficiales Unitree para locomocion.
- Puertos oficiales de fabrica.
- Significado de servicios TCP `4000`, `1026`, `23366`, `23367`.
- `/tf`, `/tf_static`, `/odom`, `/map`, `/map_metadata`.
- Nav2 fisico.
- Repeticion automatica de recorrido.
- Safety gate de locomocion automatica.

## 13. Decisiones tecnicas validadas

- Usar rama `robot`/commit `b07d362` como baseline HIL actual.
- Usar `ottoguide-map` como ejecutable de campo.
- Aceptar raw capture sin TF para replay/offline.
- No mover el robot desde scripts de captura.
- No publicar `/cmd_vel` desde el agente.
- Mantener artifacts pesados fuera de Git.
- Documentar puertos cerrados como no expuestos observados, no como bloqueos de fabricante.

## 14. Proximos pasos

1. Ejecutar captura raw cuando el robot este en piso, estable, con zona despejada y control remoto humano.
2. Copiar artifacts al notebook.
3. Reproducir rosbag offline.
4. Reconstruir/proveer TF.
5. Ejecutar SLAM/mapa offline.
6. Extraer waypoints.
7. Validar localizacion/Nav2 offline.
8. Recien despues planificar navegacion fisica controlada.
