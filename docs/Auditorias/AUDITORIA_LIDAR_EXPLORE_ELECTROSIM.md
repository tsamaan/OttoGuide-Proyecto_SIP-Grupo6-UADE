# AUDITORIA_LIDAR_EXPLORE_ELECTROSIM

## @SUMMARY

- Rama auditada: `robot`.
- Estado inicial de trabajo: limpio (`git status --short` sin salida).
- Estado RC1_LOCKED respetado: no se modifico logica de negocio Python, FSM, `src/`, motores, `/cmd_vel`, factory packet endpoints, merges, rebase, commit ni push.
- Ruta operativa recomendada: ROS 2 Foxy + CycloneDDS Unicast + SDK2 DDS contra `192.168.123.161`.
- Ruta LiDAR detectada: `livox_ros_driver2` publica `/utlidar/cloud` y `/utlidar/imu`; `slam_toolbox` esta configurado para consumir `/scan`.
- Contradiccion activa: documentacion heredada usa LiDAR `192.168.123.20`; contexto operativo declara `192.168.123.120`. No se encontro `MID360_config.json` que confirme IP real.

## @CONFIRMED_IMPLEMENTED

- `codigo ottoguide/scripts/preflight_sensors.sh` existe.
- Antes del parche ya verificaba `livox_ros_driver2`, `realsense2_camera` y `slam_toolbox`.
- Despues del parche tambien verifica `nav2_bringup` y `pointcloud_to_laserscan`.
- Antes del parche media frecuencia de `/utlidar/cloud`, `/utlidar/imu`, `/camera/depth/image_rect_raw` y `/tf`.
- Despues del parche tambien valida `/scan` como topico critico y mide su frecuencia.
- `codigo ottoguide/scripts/hil_start_mapping.sh` lanza `livox_ros_driver2`, `realsense2_camera` y `slam_toolbox scan_topic:=/scan`.
- Despues del parche `hil_start_mapping.sh` ejecuta `preflight_sensors.sh` antes de lanzar `slam_toolbox`.
- `codigo ottoguide/scripts/hil_start_navigation.sh` lanza `livox_ros_driver2`, `realsense2_camera` y `nav2_bringup`.
- `codigo ottoguide/src/navigation/nav2_bridge.py` es el unico archivo bajo `codigo ottoguide/src` que importa `rclpy`.
- `codigo ottoguide/src/infrastructure/unitree/factory_rest_client.py` esta limitado a `GET /con_check`; no implementa `POST /rest/remote/packet/post`, `/startup` ni `/pull`.
- `documentacion general del proyecto/Arquitectura/ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` reconoce que Unitree Explore soporta G1/G1_D, pero no es ruta MVP por AR8030, cloud/auth y complejidad de bypass.
- `documentacion general del proyecto/Arquitectura/ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` recomienda mantener SDK2 DDS sobre `192.168.123.161`.
- `codigo ottoguide/libs/unitree_ros2-master/` y `codigo ottoguide/libs/unitree_ros2/` existen como fuentes estaticas Unitree ROS 2.
- `codigo ottoguide/libs/unitree_sdk2_python-master/` y `codigo ottoguide/libs/unitree_sdk2_python/` existen como fuentes estaticas SDK2 Python.

## @CONSIDERED_BUT_NOT_IMPLEMENTED

- No se lanzo `pointcloud_to_laserscan` desde `hil_start_mapping.sh`; solo se agrego validacion y fallo accionable.
- No se reemplazo globalmente `192.168.123.20` por `192.168.123.120`; se agrego `LIVOX_MID360_IP="${LIVOX_MID360_IP:-192.168.123.120}"` en preflight.
- No se copio codigo desde `electroSim`.
- No se modifico `nav2_bridge.py`, `factory_rest_client.py` ni ningun archivo Python de `src/`.
- No se corrigio `codigo ottoguide/cyclonedds.xml`, aunque contiene namespace XML con sintaxis Markdown. Queda como parche recomendado separado.
- No se purgaron duplicados `unitree_ros2-master`/`unitree_ros2` ni `unitree_sdk2_python-master`/`unitree_sdk2_python`.

## @CONTRADICTIONS

- LiDAR IP:
  - `documentacion general del proyecto/Operaciones_HIL/PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md` documenta `192.168.123.20`.
  - `documentacion general del proyecto/Hardware_Reference/G1-EDU 信息搜集与分析.md` documenta `192.168.123.20`.
  - Contexto operativo de esta auditoria declara `192.168.123.120`.
  - No existe `MID360_config.json` en el arbol auditado.
- ROS 2:
  - `README.md` aun menciona `ROS2 Humble`.
  - Target G1/Jetson auditado y `unitree_ros2` priorizan Foxy.
  - `preflight_sensors.sh` priorizaba Humble; parcheado a Foxy-first.
- `/scan`:
  - `hil_start_mapping.sh` usa `slam_toolbox ... scan_topic:=/scan`.
  - No existe lanzamiento real de `pointcloud_to_laserscan`.
  - `TODO.md` ya declara pendiente validar si `livox_ros_driver2` publica `/scan`.
- App movil:
  - `documentacion general del proyecto/AppPhone/README_AppPhone.md` describe Unitree Go como referencia factory pasiva tras reubicacion documental.
  - `ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` indica que Unitree Go soporta Go2/no G1 y que Unitree Explore es la app G1/G1_D.
- DDS XML:
  - `codigo ottoguide/config/cyclonedds.xml` usa namespace XML valido y peer `192.168.123.161`.
  - `codigo ottoguide/cyclonedds.xml` usa `xmlns="[https://...](https://...)"`, formato no valido para CycloneDDS.

## @RISKS

- Si `/scan` no existe, `slam_toolbox` no recibe LaserScan y el mapeo no converge.
- Si el LiDAR real esta en `192.168.123.20`, el default nuevo `192.168.123.120` debe sobreescribirse con `LIVOX_MID360_IP=192.168.123.20` hasta resolver la evidencia fisica.
- Si `codigo ottoguide/cyclonedds.xml` es usado por `CYCLONEDDS_URI`, CycloneDDS puede fallar por XML invalido.
- `README.md` conserva `ROS2 Humble`; puede inducir provisioning incorrecto en G1 EDU con Ubuntu 20.04/Foxy.
- `codigo ottoguide/libs/` contiene duplicados y SDKs/simuladores voluminosos; riesgo de despliegue pesado y ambiguedad de import.
- No se verifico hardware fisico ni se ejecuto ROS 2 en runtime durante esta auditoria.
- No se verifico que `/cmd_vel_nav` sea consumido por el controlador fisico final.

## @PATCHES_APPLIED

- `codigo ottoguide/scripts/preflight_sensors.sh`
  - Foxy-first: `ROS_SETUP_OVERRIDE`, `/opt/ros/foxy/setup.bash`, `/opt/ros/humble/setup.bash`.
  - LiDAR IP configurable: `LIVOX_MID360_IP="${LIVOX_MID360_IP:-192.168.123.120}"`.
  - `/scan` movido a topico critico.
  - Medicion de frecuencia de `/scan` con `PREFLIGHT_MIN_HZ_SCAN`.
  - Verificacion de `nav2_bringup`.
  - Verificacion de `pointcloud_to_laserscan` con mensaje accionable.
- `codigo ottoguide/scripts/hil_start_mapping.sh`
  - Ejecuta `preflight_sensors.sh` tras levantar Livox/RealSense y antes de `slam_toolbox`.
  - Variables: `HIL_PREFLIGHT_ENABLED` y `HIL_SENSOR_WARMUP_S`.
- `documentacion general del proyecto/Auditorias/AUDITORIA_LIDAR_EXPLORE_ELECTROSIM.md`
  - Informe reproducible de auditoria y decision tecnica.

## @PATCHES_RECOMMENDED_NOT_APPLIED

- Corregir `codigo ottoguide/cyclonedds.xml` para usar:
  - `xmlns="https://cdds.io/config"`
  - `xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"`
  - `xsi:schemaLocation="https://cdds.io/config https://raw.githubusercontent.com/eclipse-cyclonedds/cyclonedds/master/etc/cyclonedds.xsd"`
- Definir un `MID360_config.json` versionado o documentar la ruta real usada por `/home/unitree/livox_ws/install/setup.bash`.
- Agregar lanzamiento controlado de `pointcloud_to_laserscan` si en HIL se confirma que `livox_ros_driver2` no publica `/scan`.
- Actualizar `README.md` para reemplazar `ROS2 Humble` por `ROS2 Foxy` en target G1 EDU.
- Actualizar `documentacion general del proyecto/AppPhone/README_AppPhone.md` para declarar Unitree Go como referencia Go2/factory, no app primaria G1.
- Deducir y consolidar `libs/` para evitar dos copias de `unitree_ros2` y `unitree_sdk2_python`.

## @ELECTROSIM_USEFULNESS

- Repo auditado en `/tmp/electroSim-audit`.
- `unitree_monitor/dds_reader.py` usa `ChannelFactoryInitialize(0, interface)` y `ChannelSubscriber("rt/lowstate", LowState)`.
- Para `robot_type == "go2"` usa `unitree_go.msg.dds_.LowState_`.
- Para `robot_type != "go2"` usa `unitree_hg.msg.dds_.LowState_`, por lo tanto G1 cae en `unitree_hg`.
- La lectura es read-only: no usa `ChannelPublisher`, no invoca `LocoClient`, no publica comandos.
- `unitree_monitor/joint_maps.py` incluye tabla G1 de 29 motores, util para telemetria y UI.
- `unitree_monitor/ui_main.py` exporta CSV de snapshots de motores, IMU, bateria y fuerzas.
- `requirements.txt`: `PyQt6`, `openpyxl`, `pyinstaller`.
- `generar_exe_windows.bat` incluye flags PyInstaller: `--onefile --windowed --collect-all unitree_sdk2py --collect-all cyclonedds`.
- Sirve para OttoGuide como referencia de:
  - tabla de mapeo de motores G1;
  - patron read-only DDS `rt/lowstate`;
  - exportacion CSV de telemetria;
  - empaquetado PyInstaller con SDK2/CycloneDDS.
- No sirve para:
  - navegacion Nav2;
  - LiDAR `/utlidar/cloud` o `/scan`;
  - control locomotor;
  - Unitree Explore/AR8030;
  - despliegue directo en RC1 sin adaptar UI Qt y dependencias.

## @NEXT_COMMANDS_FOR_HIL

```bash
cd "./robot/codigo ottoguide"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$PWD/config/cyclonedds.xml"
source /opt/ros/foxy/setup.bash
source /home/unitree/livox_ws/install/setup.bash
ros2 pkg list | grep -E '^(livox_ros_driver2|realsense2_camera|slam_toolbox|nav2_bringup|pointcloud_to_laserscan)$'
ros2 topic list | grep -E '^(/utlidar/cloud|/utlidar/imu|/scan|/camera/depth/image_rect_raw|/tf)$'
LIVOX_MID360_IP=192.168.123.120 PREFLIGHT_TOPIC_WAIT_S=20 PREFLIGHT_HZ_DURATION_S=5 bash scripts/preflight_sensors.sh
HIL_PREFLIGHT_ENABLED=1 HIL_SENSOR_WARMUP_S=10 LIVOX_MID360_IP=192.168.123.120 bash scripts/hil_start_mapping.sh
```

Si el LiDAR fisico responde en `.20`, repetir solo con:

```bash
LIVOX_MID360_IP=192.168.123.20 bash scripts/preflight_sensors.sh
```

## @FILES_TOUCHED

- `codigo ottoguide/scripts/preflight_sensors.sh`
- `codigo ottoguide/scripts/hil_start_mapping.sh`
- `documentacion general del proyecto/Auditorias/AUDITORIA_LIDAR_EXPLORE_ELECTROSIM.md`

## @ROLLBACK

```bash
cd "./robot"
git restore -- "codigo ottoguide/scripts/preflight_sensors.sh" "codigo ottoguide/scripts/hil_start_mapping.sh"
```

`documentacion general del proyecto/Auditorias/AUDITORIA_LIDAR_EXPLORE_ELECTROSIM.md` es archivo nuevo no trackeado; conservarlo como evidencia o removerlo solo con orden explicita.
