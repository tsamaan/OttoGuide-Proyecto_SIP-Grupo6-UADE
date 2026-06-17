# Robot factory baseline and OttoGuide evolution

## Proposito

Este documento separa lo que esta documentado, lo que fue observado en campo y lo que fue configurado por OttoGuide para el robot fisico Unitree G1 EDU / Ottoman usado como guia universitario UADE.

## Alcance

El alcance cubre inventario HIL, red, ROS 2, sensores, scripts de captura y limites de seguridad. No valida navegacion autonoma, locomocion por software ni comportamiento interno propietario de Unitree.

## Criterios de evidencia

| Categoria | Significado |
|---|---|
| Documentado oficialmente | Dato respaldado por manual, documentacion de fabricante o fuente oficial verificada. |
| Observado empiricamente | Dato medido en el robot, notebook HIL, Git local/remoto o runtime ROS. |
| Configurado por OttoGuide | Dato creado o ajustado por el proyecto OttoGuide. |
| Supuesto pendiente de validacion | Dato razonable pero no comprobado con evidencia suficiente. |

## Robot fisico

| Elemento | Estado | Evidencia |
|---|---|---|
| Modelo | Unitree G1 EDU / Ottoman | Contexto del proyecto; pendiente de documento oficial adjunto. |
| Companion PC | Observada | Host SSH `192.168.123.164`, usuario `unitree`, hostname `ubuntu`, Linux aarch64 Tegra. |
| Locomotion controller | Observado en red | Host `192.168.123.161` responde ping; SSH no expuesto observado. |
| LiDAR Livox MID360 | Observado por stack | `livox_sdk_bridge_node` publica `/utlidar/cloud` y `/livox/imu`. |
| IMU | Observada por ROS | Topic `/livox/imu`, `frame_id=utlidar_lidar`. |
| Control remoto | No verificado por topic | Se planifica movimiento humano por control remoto; topics de control remoto no verificados. |

## Estado de fabrica/documentado

No se consulto ni adjunto manual oficial del fabricante durante esta auditoria. Por lo tanto:

| Area | Estado |
|---|---|
| APIs oficiales Unitree disponibles | No verificado |
| Puertos oficiales de fabrica | No verificado |
| Servicios obligatorios de locomocion | No verificado |
| Politicas de seguridad de fabricante | No verificado |
| Modo recomendado para mapeo externo | No verificado |

No se afirma que ningun puerto o servicio este bloqueado por fabricante. Los resultados de red se documentan como observados.

## Estado observado al inicio/progreso HIL

| Item | Resultado | Tipo |
|---|---|---|
| Notebook HIL | `192.168.123.101/24` | Observado empiricamente |
| Companion PC | `192.168.123.164` | Observado empiricamente |
| Locomotion | `192.168.123.161` | Observado empiricamente |
| Host HIL no identificado | `192.168.123.120` | Observado empiricamente; no tocar |
| SSH companion | `192.168.123.164:22` abierto | Observado empiricamente |
| SSH locomotion | `192.168.123.161:22` no expuesto observado | Observado empiricamente |
| ROS | Foxy | Observado empiricamente |
| DDS | CycloneDDS con `rmw_cyclonedds_cpp` | Configurado por OttoGuide |
| CycloneDDS XML | `codigo ottoguide/config/cyclonedds.foxy.xml` | Configurado por OttoGuide |

## Topics ROS observados

| Topic | Estado | Tipo | Frame |
|---|---|---|---|
| `/utlidar/cloud` | Activo | `sensor_msgs/msg/PointCloud2` | `utlidar_lidar` |
| `/livox/imu` | Activo | `sensor_msgs/msg/Imu` | `utlidar_lidar` |
| `/scan` | Activo | `sensor_msgs/msg/LaserScan` | `utlidar_lidar` |
| `/tf` | Faltante | No verificado | No aplica |
| `/tf_static` | Faltante | No verificado | No aplica |
| `/odom` | Faltante | No verificado | No aplica |
| `/map` | Faltante | No verificado | No aplica |
| `/map_metadata` | Faltante | No verificado | No aplica |
| `/cmd_vel` | Faltante | No publicado por OttoGuide | No aplica |

## Evolucion OttoGuide

| Cambio | Estado |
|---|---|
| Rama Git `robot` | Validada por `git ls-remote` en `target-uade` a `fad510f`. |
| Tooling HIL versionado | Scripts `physical_mapping_*`, auditoria de artifacts y config CycloneDDS presentes en `target-uade/robot`. |
| `scan_gate` | Launch sensor-only presente en repo y observado en runtime. |
| Captura raw sensor-only | Preparada en robot para grabar sensores aunque falte TF. |
| `ottoguide-map` | No encontrado en el baseline remoto `target-uade/robot:fad510f`; preparado para sincronizacion versionada en el commit documental posterior. |
| Artifacts locales | Deben vivir bajo `artifacts/`; no versionar rosbags pesados. |
| Restricciones de seguridad | No publicar `/cmd_vel`, no mover por software, no Nav2 fisico sin validacion. |

## No validado

| Item | Estado |
|---|---|
| Navegacion autonoma fisica | No validado |
| Nav2 fisico | No validado |
| Repeticion automatica de recorrido | No validado |
| TF completo | Pendiente |
| Odometria `/odom` | Pendiente |
| Mapa `/map` en vivo | Pendiente |
| Export PGM/YAML directo | Pendiente de `/map` |
| APIs oficiales Unitree | No verificado |
| Control remoto expuesto como topic ROS | No verificado |

## Riesgos y limites

- Sin `/tf`, `/tf_static` y `/odom`, la captura raw sirve para replay/offline, pero no garantiza mapeo 2D directo.
- Sin `/map`, `map_saver` debe omitirse o registrarse como `MAP_EXPORT_SKIPPED_NO_MAP_TOPIC`.
- La companion expone servicios internos observados, pero no se atribuyen a fabricante sin evidencia oficial.
- La navegacion autonoma requiere mapa, localizacion, TF, safety envelope y validacion offline antes de cualquier prueba fisica.

## Proximos pasos

1. Revisar y commitear documentacion si el equipo la aprueba.
2. Mantener `ottoguide-map` versionado en la rama `robot` junto con su quickstart.
3. Ejecutar captura raw con robot en piso, estable, zona despejada y control remoto humano.
4. Reproducir rosbag offline para reconstruir TF/SLAM.
5. Validar mapa, waypoints, AMCL/Nav2 offline antes de planificar locomocion automatica.
