# REPORTE HIL - Preparacion de validacion supervisada SVO/Odometer_service - 20260527

## Alcance

Preparacion de una futura validacion cronometrada de `svo_ros` para observar pose visual y TF. Esta sesion solo inspecciono configuracion y creo un gate autocerrado no ejecutado.

No se ejecuto SVO, Odometer_service, RealSense, mapeo, navegacion ni locomocion. No se publicaron `/odom`, TF manuales ni comandos.

## Baseline Git y runtime

- Repo robot: `/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE`, rama `robot`.
- HEAD inicial remoto: `a092002`.
- `origin/robot` inicial: `a092002`.
- Ahead/behind inicial: `0 0`.
- Tracked dirty inicial: vacio.
- Untracked iniciales: solo `codigo ottoguide/logs/` y `codigo ottoguide/artifacts/`.
- Runtime prohibido detectado al preflight: ninguno.
- Notebook local: actualizada por fast-forward de `fef396a` a `a092002` usando `target-uade`.

## Ambiente ROS y workspace

- ROS 1 Noetic disponible: YES (`/opt/ros/noetic/setup.bash`).
- ROS 2 Foxy disponible: YES (`/opt/ros/foxy/setup.bash`).
- Setup de Odometer_service disponible: YES (`/home/unitree/unitree/Odometer_service/devel/setup.bash`).
- `rospack find svo_ros`: `/home/unitree/unitree/Odometer_service/src/rpg_svo_pro_open/svo_ros`.
- Ejecutables presentes, solo inspeccionados: `svo_node`, `svo_benchmark`, `libsvo_nodelet.so`.
- `rosrun svo_ros svo_node --help`: omitido deliberadamente porque ejecutaria el binario en una sesion de preparacion.

## Launch seleccionado y entradas requeridas

Launch candidato:

```text
svo_ros/launch/rs_camera.launch
```

Evidencia inspeccionada:

- Lanza unicamente `svo_ros/svo_node` con nombre `svo`.
- No lanza driver RealSense ni roscore.
- Topic de entrada requerido: `/camera/infra1/image_rect_raw`.
- Calibracion: `param/calib/rs_camera_calib.yaml`, monocular pinhole `640x480`.
- Parametros: `param/rs_camera_param.yaml`.
- `pipeline_is_stereo: False`.
- `use_imu: False`; el launch seleccionado no requiere topic IMU.
- Orientacion inicial configurada con `init_rx=3.14`, `init_ry=0.00`, `init_rz=0.00`.

Referencias de seguridad:

- El launch y los YAML seleccionados no contienen instrucciones de movimiento.
- Archivos auxiliares de RViz/rqt dentro del paquete contienen referencias a objetivos/interfaz de control y quedan fuera del script: no se lanzan ni se usan en la validacion preparada.

## ROS 1 actual, solo lectura

Ambiente consultado:

```text
ROS_MASTER_URI=http://localhost:11311
```

Resultado:

- Proceso `roscore`/`rosmaster` activo: NO.
- `rosnode list`: no pudo comunicarse con master.
- `rostopic list`: no pudo comunicarse con master.
- Topics actuales de camara/infra/imagen/IMU: no observables; no existe master activo.

Esto no es un fallo del gate preparado: una ejecucion posterior debera decidir explicitamente si iniciar un `roscore` propio y confirmar o exceptuar la ausencia de la entrada de imagen.

## Outputs esperados de SVO

La auditoria de codigo previa y la seleccion de launch sustentan los siguientes outputs potenciales, solo a validar en una futura ejecucion:

- `/svo/pose_imu`: `geometry_msgs/PoseWithCovarianceStamped`.
- `/svo/pose_cam/0`: `geometry_msgs/PoseStamped`.
- `/svo/info`: informacion del pipeline SVO.
- `/svo/pointcloud`: nube de puntos de visualizacion.
- `/tf`: transformacion `world -> cam_pos` generada por `tf::TransformBroadcaster`.

No se encontro un publicador `/odom` listo. Si las poses anteriores son continuas, con frecuencia medible y semantica de frames verificable, podrian alimentar el diseno posterior de un bridge, pero no constituyen odometria validada aun.

## Script preparado y no ejecutado

Archivo creado:

```text
codigo ottoguide/scripts/run_svo_supervised_validation.sh
```

Contrato del script:

- `RUN_SECONDS` default `30`.
- `ALLOW_START_ROSCORE` default `NO`.
- `ALLOW_NO_INPUT_TEST` default `NO`.
- `SVO_LAUNCH_MODE` default y unico modo preparado: `rs_camera`.
- Requiere por defecto `/camera/infra1/image_rect_raw` antes de lanzar SVO.
- Puede iniciar un `roscore` propio solo con `ALLOW_START_ROSCORE=YES` en una ejecucion posterior autorizada.
- Puede permitir una prueba de arranque sin entrada solo con `ALLOW_NO_INPUT_TEST=YES` en una ejecucion posterior autorizada.
- Crea logs bajo `codigo ottoguide/logs/svo_validation_<RUN_ID>/` solo al ser ejecutado.
- Monitorea nodos/topics, frecuencia y una muestra de `/svo/pose_imu`, `/svo/pose_cam/0`, `/svo/info`, `/svo/pointcloud` y `/tf`.
- Usa `trap` y termina exclusivamente PIDs propios.
- Se niega a iniciar si detecta un runtime SVO ya activo o patrones de runtime inseguros.

Validacion estatica efectuada:

- `bash -n codigo ottoguide/scripts/run_svo_supervised_validation.sh`: PASS.
- Chequeo de patrones prohibidos requerido para el script: NONE.
- Script ejecutado: NO.

## Condiciones para ejecucion posterior

Antes de autorizar una corrida de `30` segundos se debe resolver explicitamente:

```text
RUN_SECONDS=30
ALLOW_START_ROSCORE=YES o NO
ALLOW_NO_INPUT_TEST=YES o NO
```

Ademas, debe confirmarse supervision fisica, runtime seguro vacio y si el topic `/camera/infra1/image_rect_raw` existe o si la prueba sera solo de arranque sin input.

## Riesgos y decision

- SVO es un candidato visual inactivo y no un `/odom` validado.
- Sin imagen de entrada no producira pose util.
- El frame esperado es `world -> cam_pos`, no el contrato SLAM `odom -> base_link`.
- Las referencias auxiliares RViz/rqt no forman parte del gate preparado y no deben ejecutarse.

Resultado:

```text
READY_FOR_SUPERVISED_SVO_VALIDATION_NOT_EXECUTED
```

## Safety invariants

- SVO/Odometer_service ejecutado: NO.
- `roscore` iniciado: NO.
- RealSense iniciado: NO.
- Publishers manuales creados: NO.
- `ChannelPublisher`, `LocoClient`, `SportClient` o `LowCmd` usados: NO.
- Comando de locomocion ejecutado: NO.
- `/cmd_vel` publicado: NO.
- Nav2, `scan_gate`, `slam_toolbox` o `map_saver_cli` ejecutados: NO.
- Red o `cyclonedds.xml` modificados: NO.
- Paquetes instalados: NO.
- Logs stageados o borrados: NO.
- `git reset`, `git clean` o `git push` ejecutados: NO.