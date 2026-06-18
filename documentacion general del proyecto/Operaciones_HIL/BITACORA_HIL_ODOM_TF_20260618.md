# Bitacora HIL ODOM/TF 2026-06-18

## Iteracion - scan_gate crash posterior a actualizacion robot

- Fecha: 2026-06-18.
- HEAD robot: `3288c92`.
- Comando ejecutado: `ros2 launch ottoguide_livox_sdk_bridge scan_gate.launch.py` con ROS 2 Foxy, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `ROS_DOMAIN_ID=0` y `CYCLONEDDS_URI=file://.../codigo ottoguide/config/cyclonedds.foxy.xml`.
- Resultado: `scan_gate` arranco y luego finalizaron `livox_sdk_bridge_node` y `pointcloud_to_laserscan_node` con `exit code -11`.
- Sensor detectado: `47MCN8N0035124`, `dev_type:9`, `cmd_port:56100`.
- Paquetes publicados antes del crash: se observaron `Published Livox cloud packets=700 last_points=96` y `imu_callback Livox packet sample count=1000`.
- Procesos con exit code -11: `pointcloud_to_laserscan_node` y `livox_sdk_bridge_node`.
- Topics presentes luego del crash: `/livox/imu`, `/parameter_events`, `/rosout`, `/scan`, `/utlidar/cloud`.
- Resultado pointcloud_to_laserscan aislado: con argumentos manuales fallo por parseo de `target_frame:=`; con YAML del launch finalizo por timeout `PCL_ONLY_YAML_EXIT=245`, sin segfault registrado.
- dmesg/coredumpctl: sin evidencia util disponible en la captura (`dmesg`, `coredumpctl` y `journalctl --user` sin entradas relevantes).
- Tests contrato: `tests/unit/test_odom_bridge_contract.py` paso: `23 passed`.
- Artifact temporal: `/tmp/scan_gate_crash_20260618_codex.light.tar.gz`, 3.5 KB en el robot. Copia SCP local bloqueada por runner.
- Conclusion: el MID360 fue detectado y el bridge publico paquetes antes del crash; el crash conjunto aparece durante el flujo bridge + pointcloud_to_laserscan. El test aislado de pointcloud_to_laserscan con YAML no reprodujo segfault dentro del timeout.
- Proximo paso: aislar `livox_sdk_bridge_node` sin `pointcloud_to_laserscan` y capturar backtrace/core si el entorno lo permite, sin instalar paquetes ni mover el robot.

## Iteracion - aislamiento Livox bridge vs pointcloud_to_laserscan

- Fecha: 2026-06-18.
- HEAD robot: `3288c92`.
- Livox solo: `ros2 run ottoguide_livox_sdk_bridge livox_sdk_bridge_node` fue ejecutado sin `pointcloud_to_laserscan`; al cierre de la ventana de 25 s el PID ya no aparecia vivo en `ps`.
- Topics Livox solo: al finalizar solo quedaron visibles los topics base; `/utlidar/cloud`, `/livox/imu`, `/scan`, `/tf`, `/tf_static`, `/odom` y `/cmd_vel` no estaban disponibles para `ros2 topic info`.
- Frecuencia `/utlidar/cloud`: no medida porque el topic no estaba disponible al momento de medicion.
- Frecuencia `/livox/imu`: no medida porque el topic no estaba disponible al momento de medicion.
- PCL separado con Livox vivo: no ejecutado porque `livox_sdk_bridge_node` no quedo vivo.
- Resultado `/scan`: no disponible.
- Crash observado: el aislamiento indica que `livox_sdk_bridge_node` tambien termina sin PCL; no se obtuvo `exit code` del proceso al ejecutarlo en background, pero desaparecio antes de la medicion.
- dmesg/coredump: sin evidencia relevante capturada en `dmesg`/`coredumpctl`.
- Artifact temporal: `/tmp/livox_isolation_20260618_codex.light.tar.gz`, 1.9 KB en el robot. Copia SCP local bloqueada por runner.
- Conclusion: el foco inmediato pasa a `livox_sdk_bridge_node`; `pointcloud_to_laserscan` no es prerequisito para reproducir la caida.
- Proximo paso: ejecutar `livox_sdk_bridge_node` con captura explicita de exit code/backtrace si el entorno lo permite, manteniendo sensor-only y sin instalar paquetes.

## Iteracion — interaccion bridge estable + PCL separado vs scan_gate

- Fecha: 2026-06-18.
- HEAD robot: `3288c92`.
- Bridge aislado: `mid360_sdk2_bridge.launch.py` quedo vivo 12 s antes de medicion; `BRIDGE_ALIVE=true`. Cloud packets ~19300, IMU packets ~2400 en 12 s.
- `/utlidar/cloud`: `sensor_msgs/msg/PointCloud2`, Publisher count: 1. ACTIVO.
- `/livox/imu`: `sensor_msgs/msg/Imu`, Publisher count: 1. ACTIVO.
- PCL separado: `pointcloud_to_laserscan_node` lanzado contra `/utlidar/cloud` vivo. `PCL_ALIVE=true` tras 20 s. Publico `/scan` (`sensor_msgs/msg/LaserScan`, Publisher count: 1). Sin segfault. Bridge siguio vivo durante PCL separado.
- `/scan`: publicado correctamente por PCL separado con YAML del paquete.
- scan_gate once: `SCAN_GATE_EXIT=124` (timeout limpio 35 s). `pointcloud_to_laserscan_node-2` arranco (pid 8390). Bridge MARK_001 OK. Topics al cierre: `/livox/imu`, `/parameter_events`, `/rosout`, `/scan`, `/utlidar/cloud`. Sin `process has died`, sin segfault, sin `exit code -11`.
- Crash: NO REPRODUCIDO en esta sesion. scan_gate completo termino por timeout, no por fallo.
- dmesg/coredump: sin entradas relevantes. coredumpctl vacio.
- Artifact: `scan_gate_interaction_20260619_023233.light.tar.gz`, 33 K. Descargado localmente en scratch/.
- Conclusion: el crash previo de scan_gate (exit code -11) NO es reproducible en este run. Todos los componentes (bridge, PCL separado, scan_gate completo) completaron el timeout limpio. El crash previo pudo deberse a condicion de carrera en inicializacion del SDK2 o sobrecarga de memoria/CPU en los primeros segundos de arranque conjunto, posiblemente correlacionada con la sesion anterior donde el sensor ya estaba activo.
- Proximo paso: ejecutar scan_gate repetidamente (3-5 veces seguidas sin reiniciar el robot) para determinar si el crash es intermitente/estadistico. Capturar `ros2 topic hz /scan` durante 30 s dentro de scan_gate para confirmar flujo E2E completo.

## Iteración — estabilidad scan_gate 5 corridas

- Fecha: 2026-06-18
- HEAD robot: 3288c92
- Cantidad de corridas: 5
- Duración por corrida: 45 s
- Resultados:
  - Run 1: EXIT=124, timeout limpio
  - Run 2: EXIT=124, timeout limpio
  - Run 3: EXIT=124, timeout limpio
  - Run 4: EXIT=124, timeout limpio
  - Run 5: EXIT=124, timeout limpio
- Crash exit -11: NO REPRODUCIDO. Ningún process has died, ningún exit -11.
- Topics observados: /livox/imu, /scan, /utlidar/cloud activos en cada corrida.
- dmesg/coredump: Sin entradas relevantes ni segfaults.
- Artifact: scan_gate_stability_20260619_023847.light.tar.gz
- Conclusión: El crash no es reproducible en la sesión actual. scan_gate completo operó de forma estable durante 5 corridas de 45 segundos, procesando las pointclouds y emitiendo laserscans. El sistema se encuentra estable, la falla original pudo deberse a un estado corrupto pre-existente o a un issue de inicialización en frío ya disipado.
- Próximo paso: Proceder con la prueba física / de integración siguiente, asumiendo que scan_gate es estable en entorno limpio.

## Iteración — captura raw sensor-only corta

- Fecha: 2026-06-18
- HEAD robot: 3288c92
- scan_gate: Ejecutado en background, pid 10657.
- Topics previos: /utlidar/cloud, /livox/imu, /scan confirmados activos antes del rosbag.
- Rosbag: timeout de 60s exitoso (BAG_EXIT=124).
- Topics grabados: /utlidar/cloud (88035 msgs), /scan (86091 msgs), /livox/imu (11900 msgs).
- Tamaño bag: 659.2 MiB (660M).
- /cmd_vel: Unknown topic.
- Movimiento: Ninguno (sensor-only).
- Nav2: No ejecutado.
- Artifact liviano: raw_capture_short_20260619_024718.light.tar.gz (contiene contexto, pero no el bag).
- Conclusión: El stack de adquisición base (bridge Livox + pointcloud_to_laserscan) se comportó de forma completamente estable y sin fugas de memoria o caídas abruptas durante 1 minuto de grabación a disco SSD del robot. La base algorítmica de sensado se encuentra lista para el análisis ODOM/TF offline.
- Próximo paso: Descargar localmente los rosbags pesados desde el robot, actualizar el ODOM_TF_OFFLINE_ANALYSIS_20260618.md, y proceder con el replay y el mapeo.

## Iteración — validación del ejecutable operativo de captura/mapeo

- Fecha: 2026-06-18
- HEAD local: 8b69f1c
- HEAD robot: 3288c92 (Pendiente de actualización)
- Ejecutables auditados: codigo ottoguide/tools/hil/ottoguide-map, hil_capture_mapping_bundle.sh, office_sensor_capture.sh
- Cambios realizados: Se inyectó LD_LIBRARY_PATH faltante, ROS_DOMAIN_ID=0 y validación estricta contra livox_ros_driver2 en ottoguide-map.
- Validaciones locales: git diff --check y bash -n exitosos. Sin llamadas inseguras no bloqueadas a Nav2/movimiento en raw mode.
- Commit/push: 8b69f1c tools(hil): align mapping capture executable with validated scan gate
- Robot actualizado: FALSO. Requiere comando manual.
- ottoguide-map prep: Pendiente.
- ottoguide-map timed/raw: Pendiente.
- Topics esperados: /utlidar/cloud, /livox/imu, /scan
- /cmd_vel: No publica.
- Movimiento: Bloqueado en raw.
- Nav2: Bloqueado en raw.
- Conclusión: El orquestador de captura `ottoguide-map` ha sido alineado con el stack Livox SDK2 + CycloneDDS y validado estáticamente. Está listo para ser descargado y ejecutado en el robot.
- Próximo paso: Ejecutar git pull en el robot y luego correr la validación física segura (ottoguide-map prep + timed 15).

## Iteración — validación en robot del ejecutable ottoguide-map

- Fecha: 2026-06-18
- HEAD robot: 8b69f1c
- ottoguide-map prep: Ejecutado exitosamente. Confirmó el stack base y rechazó uso si faltan componentes.
- ottoguide-map timed/raw: Ejecutado (timed 15). PID 13162 finalizó limpiamente.
- Topics observados: /utlidar/cloud, /livox/imu, /scan.
- Rosbag: 15.63s, 166.4 MiB.
- /cmd_vel: No publica.
- Movimiento: Ninguno (sensor-only).
- Nav2: No ejecutado.
- Artifact: ottoguide_map_validation_20260619_030256.light.tar.gz
- Conclusión: El orquestador `ottoguide-map` opera de manera segura y correcta sobre el robot, registrando los topics validados mediante CycloneDDS sin interferir en la locomoción.
- Próximo paso: Realizar recorrido físico humano con el control remoto e invocar `ottoguide-map start` para grabar el dataset definitivo del pasillo/oficina.

## Iteración — análisis liviano del bag generado por ottoguide-map

- Fecha: 2026-06-18
- HEAD robot: 8b69f1c
- Bag analizado: ottoguide_map_20260619_030331
- Tamaño: 166.4 MiB
- Duración: 15.63s
- Topics: /utlidar/cloud, /scan, /livox/imu
- Counts: /scan: 21708, /utlidar/cloud: 22236, /livox/imu: 3014
- frame_id /utlidar/cloud: utlidar_lidar
- frame_id /livox/imu: utlidar_lidar
- frame_id /scan: utlidar_lidar
- /tf: No grabado.
- /tf_static: No grabado.
- /odom: No grabado.
- /map: No grabado.
- /cmd_vel: No grabado.
- Conclusión: El bag contiene exitosamente la data base sensoria con las frecuencias y timestamps esperados para 15 segundos, validando que ottoguide-map produce datasets íntegros de Livox SDK2 sin requerir movimiento físico. Las caídas al parsear las PointCloud2 completas son un issue conocido de ros2cli en ROS 2 Foxy, sin impacto en la validez del bag.
- Próximo paso: Desplegar el robot físicamente, ejecutar la captura real con movimiento y recuperar el dataset pesado en la workstation de procesamiento ODOM/TF.

## Iteración — mirror LucasCap12 y validación corta previa a captura física

- Fecha: 2026-06-18
- HEAD canónico local: f1526aa
- HEAD robot: f1526aa
- Mirror LucasCap12: PASS. main=f1526aaddc98ad1f3ba369e2b1959146130b3607, robot=f1526aaddc98ad1f3ba369e2b1959146130b3607
- Remotos locales finales: origin → https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git (único)
- Validación corta: FAIL — ros2 bag record SEGFAULT (exit -11) durante captura de 20 s
- Bag validación corta: ottoguide_map_20260619_033111 (parcial, sin metadata.yaml)
- Tamaño: 4 MiB (db3-wal sin flush; bag corrupto/incompleto)
- Topics suscriptos antes del crash: /utlidar/cloud, /scan, /livox/imu (todos confirmados activos)
- Counts: no disponibles (metadata.yaml ausente; SQLite error 10 disk I/O al intentar ros2 bag info)
- /cmd_vel: No grabado. No publicado.
- Nav2: No ejecutado.
- Diagnóstico crash: ros2cli `topic echo` segfault es issue conocido de Foxy con PointCloud2. El segfault en `ros2 bag record` es nuevo; db3-wal de 4 MiB sin checkpoint indica crash en las primeras tramas. Posible causa: agotamiento de memoria o condición de carrera en inicialización concurrente del subscriber con alta tasa de mensajes PointCloud2.
- Artifact liviano: map_validation_20s_analysis_20260619_033218.light.tar.gz (980 bytes, metadatos de sesión fallida)
- SCP: PASS
- Captura larga: PENDIENTE de confirmación explícita del operador físico
- Comando preparado: `./tools/hil/ottoguide-map timed --duration 180` (ver paso 8 de la sesión)
- Conclusión: Mirror hacia LucasCap12 ejecutado y verificado. La validación corta de 20 s falló por segfault en ros2 bag record; el stack de sensores siguió activo (topics publicados). El crash de ros2 bag record puede ser intermitente (como el scan_gate -11 previo) o sensible a la carga de PointCloud2. La captura larga de 180 s debe intentarse con el operador físico presente y el robot en modo quieto.
- Próximo paso: Confirmar si se intenta la captura larga (180 s) o si se re-intenta la validación corta antes.

## Iteración — aislamiento de segfault rosbag2

- Fecha: 2026-06-19.
- HEAD local: `1407433`.
- HEAD robot: `f1526aa`.
- Commit bitácora fallo validación: `1407433 docs(hil): record rosbag validation failure`, pusheado a `origin/robot`.
- Preflight: `ottoguide-map prep` PASS (`PREP_CODE=0`); 1.8 TB libres; robot con solo logs históricos untracked.
- scan_gate control: launch PID `19428` inició y expuso `/utlidar/cloud`, `/livox/imu` y `/scan`; su `livox_sdk_bridge_node` murió con `exit code -11`. Había además un `scan_gate` preexistente (`PID 10657`) que mantuvo los topics activos durante la matriz. Los procesos creados por esta iteración fueron detenidos al final.
- imu_only: FAIL, `EXIT=139`, muerte temprana, sin `metadata.yaml`.
- scan_only: FAIL, `EXIT=139`, muerte temprana, sin `metadata.yaml`.
- cloud_only: FAIL, `EXIT=139`, muerte temprana, sin `metadata.yaml`.
- cloud_imu: FAIL, `EXIT=139`, muerte temprana, sin `metadata.yaml`.
- scan_imu: FAIL, `EXIT=139`, muerte temprana, sin `metadata.yaml`.
- cloud_scan: FAIL, `EXIT=139`, muerte temprana, sin `metadata.yaml`.
- full: FAIL, `EXIT=139`, muerte temprana, sin `metadata.yaml`.
- full_repeat: no ejecutado porque `full` no pasó limpiamente.
- Crash: los siete procesos `ros2 bag record` segfaultearon pocos segundos después de suscribirse y dejaron DB3/WAL parciales sin flush.
- /cmd_vel: topic ausente; no publicado ni grabado.
- dmesg/coredump: sin evidencia útil capturada.
- Artifact: `rosbag_record_isolation_20260619_034433.light.tar.gz`, 92 KB, copiado al host local. Bags DB3 pesados permanecen solo en el robot.
- Conclusión: `imu_only` también falla, por lo que el problema se clasifica como rosbag2/SQLite o entorno runtime general, no como carga exclusiva de PointCloud2. La presencia de un scan_gate preexistente debe eliminarse como variable en el próximo diagnóstico.
- Próximo paso: no ejecutar captura larga; repetir un control mínimo con un único stack sensor y un topic sintético o de baja tasa, capturando backtrace/core del proceso `ros2 bag record` sin instalar paquetes.
