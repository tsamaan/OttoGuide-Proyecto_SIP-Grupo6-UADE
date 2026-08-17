# Reporte HIL ODOM Bridge / Timed Mapping - 2026-05-27

## Resultado ejecutivo

Se audito la disponibilidad de una fuente real de odometria Unitree para reemplazar el TF temporal validado anteriormente. La sesion no encontro `/odom`, TF ni topicos ROS de estado corporal. Se encontro SDK2 C++ HG instalado con canales candidatos de lectura, pero los tipos inspeccionados no proveen por si solos pose o velocidad planar suficiente para publicar odometria real.

Clasificacion: `UNITREE_STATE_SOURCE_AMBIGUOUS`.

Decision de seguridad: `NO MAPPING RUN`; no se implemento `odom_bridge`, no se publico TF provisional y no se ejecuto `scan_gate` ni `slam_toolbox`.

## Baseline Git y runtime

- Repositorio canonico: `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git`
- Rama: `robot`
- HEAD inicial: `e7e352f`
- `origin/robot` inicial: `e7e352f`
- Ahead/behind inicial: `0 0`
- Cambios tracked iniciales: ninguno.
- Untracked inicial permitido: `codigo ottoguide/logs/` y `codigo ottoguide/artifacts/`.
- Runtime inseguro inicial (`nav2`, movimiento, SLAM, TF temporal, scan gate u odom bridge): ninguno detectado.

## Auditoria ROS base

Entorno leido: ROS 2 Foxy con workspace instalado y configuracion DDS existente, sin modificarla.

- `slam_toolbox async_slam_toolbox_node`: disponible.
- `tf2_ros static_transform_publisher` y `tf2_echo`: disponibles.
- `nav2_map_server map_saver_cli`: disponible.
- Paquetes locales relacionados visibles: `ottoguide_livox_sdk_bridge`, `robot_localization`, `robot_state_publisher`.
- Nodos ROS base: ninguno.
- Topicos ROS base: `/parameter_events`, `/rosout` solamente.
- `/odom`, `/tf`, `/tf_static`, `/imu`, `/lowstate`, `/sportmodestate`, `/sport_state`, `/joint_states`, `/unitree/*`, `/robot_pose`, `/body_state`, `/base_state`, `/vel`: no visibles.

## Fuentes Unitree fuera del grafo ROS

### Procesos y SDK instalados

- Procesos Unitree observados: `/unitree/module/master_service/master_service`, `/unitree/ota/pipe/ota_pipe_service`, video hub del companion PC.
- SDK C++: `/home/unitree/unitree_sdk2` y `/usr/local/lib/libunitree_sdk2.a`.
- Headers HG disponibles: `LowState_.hpp`, `IMUState_.hpp`, `SportModeState_.hpp` bajo `/home/unitree/unitree_sdk2/include/unitree/idl/hg/`.
- Python SDK2: no disponible (`ModuleNotFoundError` para `unitree_sdk2py` y submodulos); por lo tanto no se creo ni ejecuto el probe Python temporal previsto.

### Canales candidatos documentados por SDK

- `rt/lowstate`: referenciado por ejemplos G1 y tipado como `unitree_hg::msg::dds_::LowState_`.
- `rt/secondary_imu`: referenciado en ejemplos humanoides como IMU secundaria.
- `rt/sportmodestate`: mencionado por ejemplo G1 para verificar FSM.
- Canales probados en vivo: ninguno; no se ejecuto binario C++ existente porque los ejemplos encontrados incluyen publishers/clientes de control, prohibidos en esta sesion.

### Adecuacion para odometria

- `LowState_` expone `tick`, `imu_state`, estados de 35 motores, control remoto y CRC.
- `IMUState_` expone quaternion, giroscopio, acelerometro y RPY.
- `SportModeState_` HG inspeccionado expone estado/modo FSM, no pose ni velocidad corporal.
- No se encontro en el contrato inspeccionado posición XY ni velocidad lineal corporal usable para integrar odometria 2D con confianza.
- Incluso si `rt/lowstate` estuviera activo, la evidencia actual seria como maximo IMU/joints; no habilita publicar `/odom` como odometria completa.

## Odom bridge y TF LiDAR

- Fuente seleccionada: ninguna validada.
- `odom_bridge` implementado: NO.
- `/odom` publicado: NO.
- `odom -> base_link` publicado: NO.
- TF `base_link -> utlidar_lidar` nueva: NO; no se crea extrinseca provisional sin pipeline odometrico apto para validar.
- La extrinseca del MID360 sigue requiriendo medicion fisica formal antes de navegacion final.

## Timed mapping gate

- Script `run_timed_mapping_gate.sh` creado: NO.
- Ejecucion cronometrada: NO.
- `scan_gate` ejecutado en esta sesion: NO.
- `slam_toolbox` ejecutado en esta sesion: NO.
- `map_saver_cli` ejecutado en esta sesion: NO.
- Motivo: no existe `/odom` real ni bridge validado; repetir SLAM con TF temporal ocultaria el bloqueo real ya demostrado por `e7e352f`.

## Proxima accion tecnica

1. Autorizar y desarrollar un probe C++ estrictamente subscriber-only en `/tmp`, basado en `ChannelSubscriber<unitree_hg::msg::dds_::LowState_>` para `rt/lowstate`, sin publishers ni clientes de locomocion.
2. Identificar si existe otro canal HG que entregue pose o velocidad corporal real; `LowState_` e IMU no bastan para odometria traslacional.
3. Solo despues de recibir mensajes repetidos con contrato suficiente, implementar `odom_bridge`, medir/calibrar `base_link -> utlidar_lidar` y reevaluar el gate cronometrado.

## Invariantes de seguridad

- Nav2 executed: NO
- nav2_bringup executed: NO
- navigation autonomous executed: NO
- locomotion command executed: NO
- `/cmd_vel` published: NO
- SportClient executed: NO
- LocoClient executed: NO
- `eth0` modified: NO
- network modified: NO
- `cyclonedds.xml` modified: NO
- packages installed: NO
- credentials modified: NO
- `git reset` executed: NO
- `git clean` executed: NO
- `git push` executed: NO
