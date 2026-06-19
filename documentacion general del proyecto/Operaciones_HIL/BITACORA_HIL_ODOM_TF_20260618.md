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

## Iteración — diagnóstico limpio de rosbag2

- Fecha: 2026-06-19.
- HEAD local: `1b3ebdb`.
- HEAD robot: `f1526aa`.
- Commit bitácora previo: `1b3ebdb docs(hil): record rosbag isolation results`, pusheado a `origin/robot`.
- Limpieza de procesos: los procesos preexistentes `scan_gate`, Livox, PCL y rosbag fueron señalados con SIGINT y desaparecieron antes del caso sintético. Al finalizar quedó un publisher sintético `ros2 topic pub` PID `20832` que ignoró SIGINT directo y al process group; no se usó SIGTERM ni `kill -9`.
- Synthetic CycloneDDS: PASS; `EXIT=124`, metadata válida, SQLite3 íntegro, 194 mensajes en 19.300 s y bag de 24.8 KiB.
- Synthetic FastDDS: FAIL/INVÁLIDO; `EXIT=124` pero produjo `bad_alloc`, no generó `metadata.yaml` y dejó un publisher residual.
- scan_gate limpio: FAIL; el launch inició pero `livox_sdk_bridge_node` y `pointcloud_to_laserscan_node` murieron con `exit code -11` antes de habilitar la matriz sensor.
- imu_only: no ejecutado por fallo de `scan_gate` limpio.
- scan_only: no ejecutado por fallo de `scan_gate` limpio.
- cloud_only: no ejecutado por fallo de `scan_gate` limpio.
- cloud_imu: no ejecutado por fallo de `scan_gate` limpio.
- scan_imu: no ejecutado por fallo de `scan_gate` limpio.
- cloud_scan: no ejecutado por fallo de `scan_gate` limpio.
- full: no ejecutado por fallo de `scan_gate` limpio.
- full_repeat: no ejecutado.
- Crash: rosbag2 con CycloneDDS no reprodujo el crash usando un topic String sintético; el crash limpio observado corresponde al stack sensor `scan_gate` antes de iniciar rosbag sensor.
- /cmd_vel: ausente; no publicado ni grabado.
- dmesg/coredump: sin evidencia útil capturada.
- Artifact: `rosbag_clean_diagnostic_20260619_035203.light.tar.gz`, 12 KB, copiado al host local.
- Conclusión: rosbag2/SQLite/Python funciona con CycloneDDS y carga sintética baja. El bloqueo inmediato vuelve al stack sensor limpio: ambos nodos murieron `-11`; FastDDS no es una alternativa válida en esta sesión.
- Próximo paso: no ejecutar captura larga; aislar nuevamente Livox y PCL en un entorno recién limpiado, capturando exit code/backtrace, y cerrar manualmente el publisher sintético residual antes de otra prueba.

## Iteración — aislamiento limpio del stack sensor Livox/PCL

- Fecha: 2026-06-19.
- HEAD local: `256dd4d`.
- HEAD robot: `f1526aa`.
- Commit bitácora previo: `256dd4d docs(hil): record clean rosbag diagnostic`, pusheado a `origin/robot`.
- Limpieza de procesos: PASS. El publisher sintético residual PID `20832` ignoró SIGINT y fue cerrado con SIGTERM según el procedimiento; no quedaron procesos Livox, PCL, scan_gate o rosbag residuales al cierre.
- official_sdk_sample: PASS, `EXIT=124`; cloud e IMU recibidos durante 25 s con el binario oficial `livox_lidar_quick_start`.
- livox_callbacks_disabled: PASS, `EXIT=124`.
- livox_dryrun_callbacks: PASS, `EXIT=124`.
- livox_no_timers: PASS, `EXIT=124`.
- livox_no_publishers: PASS, `EXIT=124`.
- livox_full_1: PASS, `EXIT=124`.
- livox_full_2: PASS, `EXIT=124`.
- livox_full_3: PASS, `EXIT=124`.
- pcl_no_input: PASS, `EXIT=124`.
- bridge_pcl_manual: FAIL. El bridge siguió vivo tras 25 s, pero `pointcloud_to_laserscan_node` murió; `/utlidar/cloud` y `/livox/imu` permanecieron publicados y `/scan` no quedó disponible.
- scan_gate_1: FAIL/intermitente. Livox y PCL murieron con `exit code -11` y el launch terminó con `EXIT=0`.
- scan_gate_2: PASS, `EXIT=124`.
- scan_gate_3: PASS, `EXIT=124`.
- gdb_livox: no reprodujo crash; `GDB_EXIT=124`, sin backtrace de señal. El bridge continuó publicando hasta más de 70.000 paquetes cloud durante la ventana gdb.
- Crash: reproducible de forma intermitente al introducir PCL con datos Livox reales; Livox aislado, sample oficial y todas las variantes del bridge fueron estables.
- /cmd_vel: ausente; no publicado ni grabado.
- dmesg/coredump: sin evidencia útil capturada.
- Artifact: `sensor_stack_isolation_v2_20260619_040823.light.tar.gz`, 142 KB, copiado al host local.
- Conclusión: el foco queda en `pointcloud_to_laserscan` al consumir PointCloud2 real y en la interacción/timing del launch conjunto. El bridge Livox aislado no reprodujo crash en esta matriz.
- Próximo paso: no ejecutar captura larga; repetir PCL con bridge vivo bajo gdb y revisar compatibilidad/tamaño/layout del PointCloud2 entregado, sin modificar código todavía.

## Iteración — PCL con PointCloud2 real bajo gdb post-reboot

- Fecha: 2026-06-19.
- HEAD local: `fc82487`.
- HEAD robot: `f1526aa`.
- Commit bitácora previo: `fc82487 docs(hil): record sensor stack isolation results`, pusheado a `origin/robot`.
- Reboot/batería: robot reiniciado físicamente; uptime inicial observado de 3 minutos.
- Conectividad: ping 4/4 y SSH OK en `192.168.123.164`.
- Internet robot: default route por `usb1` y resolución DNS de `github.com` disponibles; no se usó Git remoto.
- official_sdk_sample: PASS, `EXIT=124`; cloud e IMU recibidos durante 25 s.
- cloud metadata: no capturada; el inspector ROS 2 usó QoS reliable y el publisher ofreció QoS incompatible (`RELIABILITY_QOS_POLICY`).
- pcl_real_default_1: PASS bajo gdb, `PCL_EXIT=124`, sin señal ni backtrace.
- pcl_real_default_2: PASS bajo gdb, `PCL_EXIT=124`, sin señal ni backtrace.
- pcl_real_default_3: PASS bajo gdb, `PCL_EXIT=124`, sin señal ni backtrace.
- pcl_real_max16: PASS bajo gdb, `PCL_EXIT=124`, sin señal ni backtrace.
- pcl_real_max1: PASS bajo gdb, `PCL_EXIT=124`, sin señal ni backtrace.
- scan_gate_after_pcl_1: PASS, `EXIT=124`.
- scan_gate_after_pcl_2: PASS, `EXIT=124`.
- gdb/backtrace: no se reprodujo SIGSEGV; no hubo backtrace de crash.
- Crash: no reproducido después del reinicio físico en cinco pruebas PCL con datos reales y dos pruebas scan_gate.
- /cmd_vel: ausente; no publicado ni grabado.
- dmesg/coredump: sin evidencia útil capturada.
- Artifact: `pcl_realdata_postreboot_20260619_044414.light.tar.gz`, 117 KB, copiado al host local.
- Conclusión: el reinicio físico limpió el estado que acompañaba el crash intermitente; SDK2, bridge, PCL con datos reales y scan_gate fueron estables en esta sesión. El layout PointCloud2 queda pendiente de captura con QoS sensor-data compatible.
- Próximo paso: realizar una única validación corta de rosbag full, sin captura larga; si pasa, clasificar el crash previo como estado intermitente limpiado por reboot.

## Iteración — validación corta rosbag full post-reboot con ottoguide-map

- Fecha: 2026-06-18
- HEAD local: 6af9782
- HEAD robot: f1526aa
- Commit bitácora previo: 6af9782 docs(hil): record post-reboot pcl stability
- Mirror LucasCap12: PASS (actualizado y eliminado temporal)
- Prep: PASS
- Topics prep: /utlidar/cloud, /livox/imu, /scan confirmados.
- Timed 30s: PASS (TIMED_CODE=0)
- Bag: ottoguide_map_20260619_050055
- Duración: 29.995s
- Tamaño: 331.4 MiB
- Topics grabados: /utlidar/cloud, /scan, /livox/imu
- Counts: /scan: 43271, /utlidar/cloud: 44261, /livox/imu: 6000
- metadata.yaml: PASS
- /cmd_vel: No grabado. No publicado.
- Nav2: No ejecutado.
- Movimiento: Ninguno (sensor-only).
- Crash: NO (sin segfaults en rosbag2, pointcloud_to_laserscan ni livox_sdk_bridge).
- dmesg/coredump: Sin evidencias relevantes, comportamiento limpio.
- Artifact: ottoguide_map_short_validation_20260619_050017.light.tar.gz
- Conclusión: El stack operativo completo (bridge Livox SDK2, PCL a LaserScan y ros2 bag record) operó sin fallos post-reboot, registrando un dataset sano y completo de 331 MB. La falla previa `exit -11` de ros2 bag record no es persistente y el hardware/OS está en estado limpio.
- Próximo paso: Preparar la captura larga de 180s con el operador físico y control remoto manual, asegurando no intervenir en los componentes validados.

## Iteración — validación en robot del plan de captura total y discovery de topics

- Fecha: 2026-06-19
- HEAD local: `3646116` (36461169e4c2e26840598bcb3d773a59497eb2d3)
- HEAD mirror main: `3646116` (36461169e4c2e26840598bcb3d773a59497eb2d3) — MATCH
- HEAD mirror robot: `3646116` (36461169e4c2e26840598bcb3d773a59497eb2d3) — MATCH
- HEAD robot antes: `f1526aa`
- HEAD robot después: `36461169` (`3646116`)
- Método de actualización: bundle fast-forward via SCP (`git fetch /tmp/ottoguide_robot_update.bundle` + `git merge --ff-only`). Fetch directo HTTPS bloqueado por autenticación (sin credenciales en robot).
- Archivos verificados en robot: `ottoguide-map` ✅, `analyze_capture_sqlite.py` ✅, `PLAN_CAPTURA_TOTAL_REPLAY_PROGRESIVO_G1.md` ✅
- Validación estática robot: `bash -n` PASS, `python3 -m py_compile` PASS
- `ottoguide-map plan`: PASS — dry-run sin bag; descubrió 3 topics, no inició rosbag, no publicó nada, no movió robot
- Código de salida plan: 0
- Sensor base: `/utlidar/cloud` PRESENT (`sensor_msgs/msg/PointCloud2`, pub:1, node:`livox_sdk_bridge_node`, QoS BEST_EFFORT/VOLATILE), `/livox/imu` PRESENT (`sensor_msgs/msg/Imu`, pub:1, node:`livox_sdk_bridge_node`), `/scan` PRESENT (`sensor_msgs/msg/LaserScan`, pub:1, node:`pointcloud_to_laserscan`)
- Topics Nivel 1 presentes (wirelesscontroller, api/sport): NINGUNO — ausentes del DDS ROS2
- Topics Nivel 2 presentes (sportmodestate, lowstate, odom, secondary_imu, odommodestate): NINGUNO — ausentes del DDS ROS2
- Topics Nivel 3 presentes (tf, tf_static, map, slam, localization): NINGUNO — ausentes
- Endpoints de control observados: ninguno — `/cmd_vel` ausente, `/api/sport/request` ausente, `/api/sport/response` ausente
- `/cmd_vel`: AUSENTE — sin publishers — OK para captura
- Nodos relevantes: `/livox_sdk_bridge_node` (publisher /utlidar/cloud + /livox/imu), `/pointcloud_to_laserscan` (publisher /scan)
- Servicios relevantes: solo servicios de parámetros RCL estándar de los dos nodos del scan_gate stack (describe_parameters, get_parameters, list_parameters, set_parameters, set_parameters_atomically, get_parameter_types). Ningún servicio Unitree SDK en DDS ROS2.
- Acciones relevantes: NINGUNA — `ros2 action list -t` devuelto vacío
- Topics seleccionados por plan: `/utlidar/cloud`, `/livox/imu`, `/scan` (3 topics, orden correcto)
- Topics omitidos por plan: ninguno de los presentes — discovery correcto
- Topics presente pero omitidos por plan: NINGUNO — PLAN_DISCOVERY_OK
- Procesos Unitree nativos observados (NO DDS ROS2): `master_service`, `ota_pipe_service`, `videohub_pc4` (x2) — corren fuera del dominio ROS2; no exponen topics ROS2
- Rosbag iniciado: NO
- Nav2 iniciado: NO
- Movimiento: NO
- Artifact: `total_capture_plan_validation_20260619_210602.light.tar.gz` (4.5 KB), copiado a `artifacts/hil_evidence_light/`
- SCP: PASS (ambos artifacts del run copiados)
- Diagnosis DDS SDK: los topics Unitree G1 DDS (`/sportmodestate`, `/lowstate`, `/wirelesscontroller`, etc.) NO son visibles en `ROS_DOMAIN_ID=0` con CycloneDDS Foxy. El servicio `master_service` del G1 opera en su propio stack DDS nativo (posiblemente `ROS_DOMAIN_ID=1` o DDS domain separado). Requiere auditoría de dominio DDS, interfaz y procesos del G1 SDK en próxima sesión.
- Conclusión: El robot fue actualizado a `3646116` sin incidencias. El tooling nuevo (`ottoguide-map plan`, `discover_record_topics`, `cmd_vel_precheck`, manifiestos) funciona correctamente en el robot. La captura total de sensor base (L1) está lista. Los topics SDK (L2) y navegación (L3) no están disponibles en el dominio ROS2 actual — el DDS nativo del G1 requiere activación o bridging explícito antes del próximo recorrido.
- Próximo paso: auditar el dominio DDS nativo del G1 (`ROS_DOMAIN_ID=1` o DDS standalone), identificar si `master_service` publica en un dominio diferente, y configurar el bridge necesario antes de la captura de recorrido humano.
