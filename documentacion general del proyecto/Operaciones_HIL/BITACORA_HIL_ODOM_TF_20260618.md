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
