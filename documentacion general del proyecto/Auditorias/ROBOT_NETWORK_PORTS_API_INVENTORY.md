# Robot network, ports and API inventory

## Proposito

Inventariar red, puertos, ROS/DDS y APIs de OttoGuide con separacion entre observado, configurado y no verificado.

## IPs observadas

| IP | Rol | Evidencia | Estado |
|---|---|---|---|
| `192.168.123.101` | Notebook HIL | Windows Ethernet 5 | Activo |
| `192.168.123.164` | Companion PC | ping/SSH/runtime | Activo |
| `192.168.123.161` | Locomotion | ping | Activo |
| `192.168.123.120` | Host HIL no identificado | observado previamente | No tocar |

## Puertos TCP observados desde notebook

| Host | Puerto | Resultado | Interpretacion |
|---|---:|---|---|
| `192.168.123.164` | 22 | OPEN | SSH companion |
| `192.168.123.164` | 80 | OPEN | Servicio HTTP observado; proposito no verificado |
| `192.168.123.164` | 443 | CLOSED/NO RESPONSE | HTTPS no expuesto observado |
| `192.168.123.164` | 8000 | CLOSED/NO RESPONSE | API dev no expuesta observada |
| `192.168.123.164` | 8001 | CLOSED/NO RESPONSE | API dev no expuesta observada |
| `192.168.123.164` | 8080 | CLOSED/NO RESPONSE | HTTP alternativo no expuesto observado |
| `192.168.123.164` | 11434 | CLOSED/NO RESPONSE | Ollama no expuesto por red HIL; runtime escucha en loopback |
| `192.168.123.161` | 22 | CLOSED/NO RESPONSE | SSH no expuesto observado |
| `192.168.123.161` | 7890 | CLOSED/NO RESPONSE | Servicio no expuesto observado |
| `192.168.123.161` | 8080 | CLOSED/NO RESPONSE | Servicio no expuesto observado |

Los resultados TCP no son concluyentes para DDS/UDP.

## Puertos/servicios internos observados en companion

| Binding | Proceso/servicio | Interpretacion |
|---|---|---|
| `0.0.0.0:22`, `[::]:22` | `sshd` | SSH companion |
| `0.0.0.0:80`, `[::]:80` | No verificado | HTTP expuesto observado |
| `0.0.0.0:4000`, `[::]:4000` | No verificado | Servicio expuesto observado |
| `192.168.123.164:1026` | No verificado | Servicio TCP interno observado |
| `127.0.0.1:11434` | `ollama` | Ollama local-only |
| `127.0.0.1:11511` | `_ros2_daemon` | Daemon ROS 2 local |
| `127.0.0.1:23366-23367` | No verificado | Servicios locales observados |
| UDP `56000`, `56101`, `56201`, `57698` | Livox bridge | Puertos sensor/bridge observados |
| UDP `7400`, `7401`, `7410-7415` | DDS/RTPS | Comunicacion ROS 2/DDS observada |

Servicios Linux running relevantes: `ssh.service`, `ollama.service`, `master_service.service`, `ota_pipe.service`, `docker.service`, `NetworkManager.service`, `unitree-upgrade.service`.

## ROS/DDS

| Elemento | Valor |
|---|---|
| `ROS_DISTRO` | `foxy` |
| `ROS_DOMAIN_ID` | vacio/default observado |
| `RMW_IMPLEMENTATION` | `rmw_cyclonedds_cpp` |
| `CYCLONEDDS_URI` | `file://.../codigo ottoguide/config/cyclonedds.foxy.xml` |
| DDS multicast | Revisar XML para conclusion final |
| Peers | Revisar XML para conclusion final |

## Topics ROS observados

| Topic | Tipo | Publishers | Subscribers | Estado |
|---|---|---:|---:|---|
| `/utlidar/cloud` | `sensor_msgs/msg/PointCloud2` | 1 | No verificado | Activo |
| `/livox/imu` | `sensor_msgs/msg/Imu` | 1 | No verificado | Activo |
| `/scan` | `sensor_msgs/msg/LaserScan` | 1 | No verificado | Activo |
| `/tf` | No disponible | 0 | No verificado | Faltante |
| `/tf_static` | No disponible | 0 | No verificado | Faltante |
| `/odom` | No disponible | 0 | No verificado | Faltante |
| `/map` | No disponible | 0 | No verificado | Faltante |
| `/cmd_vel` | No disponible | 0 | No verificado | Faltante; no publicado por OttoGuide |

Nodos observados: `/livox_sdk_bridge_node`, `/pointcloud_to_laserscan`.

## APIs/endpoints OttoGuide observados en el código al momento de la auditoría

> **Nota de vigencia del repositorio — commit `7216d6f`:**
> esta tabla conserva el resultado de la auditoría original.
> `codigo ottoguide/src/api/server.py` fue retirado posteriormente.
> La superficie HTTP canónica vigente se define en
> `codigo ottoguide/api/router.py`, sus contratos en
> `codigo ottoguide/api/schemas.py` y la aplicación se ensambla desde
> `codigo ottoguide/main.py`.
> Las observaciones de runtime de esta sección pertenecen al momento
> original de la auditoría y no fueron revalidadas por este cambio documental.

| Endpoint | Metodo | Archivo | Funcion | Estado | Uso |
|---|---|---|---|---|---|
| `/tour/start` | POST | `codigo ottoguide/src/api/server.py` | `endpoint_start_tour` | Implementado en codigo; runtime no observado | Iniciar tour por API |
| `/tour/pause` | POST | `codigo ottoguide/src/api/server.py` | `endpoint_pause` | Implementado en codigo; runtime no observado | Pausar tour |
| `/emergency` | POST | `codigo ottoguide/src/api/server.py` | `endpoint_emergency` | Implementado en codigo; runtime no observado | Emergency stop de aplicacion |
| `/status` | GET | `codigo ottoguide/src/api/server.py` | `endpoint_status` | Implementado en codigo; runtime no observado | Estado de orquestador |
| `/api/generate` | POST | `codigo ottoguide/src/interaction/conversation_manager.py` | cliente Ollama | Cliente interno | LLM local via Ollama |
| `/v1/chat/completions` | POST | `conversation_manager.py` | cliente OpenAI | Cliente externo | LLM remoto |
| `/v1/audio/speech` | POST | `conversation_manager.py` | cliente OpenAI | Cliente externo | TTS remoto |

No se observo proceso `uvicorn`/FastAPI corriendo en runtime. Los puertos `8000`, `8001` y `8080` no respondieron desde notebook.

## Servicios no expuestos / no disponibles

| Item | Estado |
|---|---|
| SSH en locomotion `192.168.123.161:22` | No expuesto observado |
| HTTPS companion `443` | No expuesto observado |
| FastAPI dev `8000/8001/8080` | No expuesto observado |
| Ollama por red HIL `11434` | No expuesto observado; loopback activo |
| `/tf`, `/tf_static`, `/odom`, `/map` | No disponibles en ROS durante inventario |
| APIs oficiales Unitree | Pendiente de documentacion oficial |

No se usa la expresion "bloqueado por fabricante" porque no hay evidencia oficial en esta auditoria.
