# REPORTE HIL - Auditoria dirigida de Odometer_service / UnitreeSlam / LIO-SAM - 20260527

## Alcance y seguridad

Sesion de inspeccion read-only para identificar fuentes historicas o instaladas de pose, odometria, twist o TF. No se ejecuto `Odometer_service`, `UnitreeSlam`, `lio_sam`, `scan_gate`, `slam_toolbox` ni Nav2. No se implemento `odom_bridge` y no se publicaron comandos, `/odom` ni TF.

## Baseline Git y runtime

- Repo robot: `/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE`.
- Rama: `robot`.
- HEAD inicial: `fef396a`.
- `origin/robot` inicial: `fef396a`.
- Ahead/behind inicial: `0 0`.
- Tracked dirty inicial: vacio.
- Untracked observados: solo `codigo ottoguide/logs/` y `codigo ottoguide/artifacts/`, permitidos.
- Runtime prohibido preexistente: no detectado.
- Notebook local: fast-forward de `181e475` a `fef396a` mediante el remoto canonico existente `target-uade`.

## Odometer_service

Ruta inspeccionada:

```text
/home/unitree/unitree/Odometer_service
```

Estado: existe.

El arbol corresponde a un workspace ROS 1/catkin compilado basado en SVO. Paquetes relevantes encontrados:

- `svo`: describe `Monocular Visual Odometry`.
- `svo_ros`: describe `Visual Odometry - ROS Nodes`, depende de `nav_msgs`, `sensor_msgs` y `tf`.
- `svo_pgo`: pose graph optimisation.
- `svo_global_map`, `svo_vio_common`, `svo_online_loopclosing`.
- `vikit_ros`: depende de `tf` y `sensor_msgs`.

Launch/config relevantes:

- `svo_ros/launch/live_nodelet.launch` carga `svo_ros/SvoNodelet`.
- `svo_ros/launch/euroc_vio_stereo.launch`, `euroc_vio_mono.launch` y `euroc_global_map_mono.launch` lanzan `svo_ros/svo_node` con camera e IMU inputs.
- `svo_ros/param/vio_mono.yaml`, `vio_stereo.yaml`, `global_map.yaml` y `backend.yaml` configuran VIO/global map/IMU.

Binarios ya construidos, no ejecutados:

- `devel/.private/svo_ros/lib/svo_ros/svo_node`.
- `devel/.private/svo_ros/lib/svo_ros/svo_benchmark`.
- `devel/.private/svo_ros/lib/libsvo_nodelet.so`.

## Salidas concretas halladas en codigo SVO ROS

En `svo_ros/src/visualizer.cpp` se encontraron publicaciones concretas:

- `pose_imu`: `geometry_msgs::PoseWithCovarianceStamped`.
- `pose_cam/<i>`: `geometry_msgs::PoseStamped`.
- `pose_graph` y `pose_graph_pointcloud`: point clouds de visualizacion/mapa.
- `pointcloud`, `keyframes`, `points` y otros topics de visualizacion.

Frames/TF:

- `Visualizer::kWorldFrame = "world"`.
- El codigo contiene `tf::TransformBroadcaster` y envia transform de `world` hacia `cam_pos` en las rutas de publicacion de pose de camara.

Hallazgo negativo importante:

- Aunque `visualizer.h` incluye `nav_msgs/Odometry.h`, la busqueda focalizada no encontro un `advertise` o publicacion concreta de `/odom` en `svo_ros`.
- El productor reutilizable identificado es de pose/TF visual, no un publicador `/odom` listo para SLAM.

## Evidencia historica UnitreeSlam / LIO-SAM

Se encontraron multiples logs historicos en `/home/unitree/.ros/log`:

- `UnitreeSlam_*`: presentes; sin lineas de topics utiles en las muestras leidas.
- `lio_sam_ros2_dogOdomForMapping_*`: registran `Dog Odom process for mapping Started.`.
- `lio_sam_ros2_dogOdomForReloc_*`: registra `Dog Odom process for reloc Started.`.
- `lio_sam_ros2_imuPreintegration_*`: registran `IMU Preintegration Started.`.
- `lio_sam_ros2_mapOptmization_*`: registran `Map Optimization Started.`.
- `lio_sam_ros2_globalLocalize_*`: presente.
- `high_rate_state_*`: presentes, sin contenido util observado.
- `map_management_*`: presente, sin topicos concretos extraidos.

La extraccion de tokens de topicos desde esos logs no produjo nombres `/odom`, pose, twist o TF verificables. Los logs demuestran una pila historica, no una fuente activa actual ni una interfaz reutilizable ya identificada.

## Grafo ROS 2 actual, solo lectura

La primera consulta ROS 2 sin el entorno DDS del workspace devolvio `std::bad_alloc`. Se repitio solo lectura usando las variables operativas existentes, sin modificar archivos:

```text
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ROS_DOMAIN_ID=0
CYCLONEDDS_URI=file:///home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/cyclonedds.xml
```

Resultado de la consulta valida:

- Nodes visibles: ninguno.
- Topics visibles: `/parameter_events`, `/rosout`.
- `/odom` activo: NO.
- Pose/twist activo: NO.
- `/tf` o `/tf_static` activo: NO.

## Decision

`Odometer_service` contiene un candidato concreto para obtener pose visual y TF (`svo_ros/svo_node` / `SvoNodelet`), pero no esta activo y no publica `/odom` de forma demostrada por la inspeccion. La pila historica LIO-SAM sugiere una ruta adicional de `dogOdomForMapping`, aun sin configuracion/topic recuperado.

Clasificacion final:

```text
ODOMETER_SERVICE_SOURCE_CANDIDATE_FOUND
```

`odom_bridge` implementado: NO.

## Proxima accion

Preparar una sesion separada y supervisada para determinar dependencias de entrada y compatibilidad del candidato `svo_ros` con los sensores presentes, o localizar binarios/configuracion originales de `dogOdomForMapping`, antes de autorizar cualquier ejecucion de fuente de pose.

## Safety invariants

- Publishers de diagnostico creados: NO.
- `ChannelPublisher` usado: NO.
- `LocoClient`, `SportClient` o `LowCmd` usados: NO.
- Comando de locomocion ejecutado: NO.
- `/cmd_vel` publicado: NO.
- Nav2 ejecutado: NO.
- `scan_gate` ejecutado: NO.
- `slam_toolbox` ejecutado: NO.
- `map_saver_cli` ejecutado: NO.
- Odometer_service/UnitreeSlam/LIO-SAM ejecutado: NO.
- Red o `cyclonedds.xml` modificados: NO.
- Paquetes instalados: NO.
- Logs stageados o borrados: NO.
- `git reset`, `git clean` o `git push` ejecutados: NO.