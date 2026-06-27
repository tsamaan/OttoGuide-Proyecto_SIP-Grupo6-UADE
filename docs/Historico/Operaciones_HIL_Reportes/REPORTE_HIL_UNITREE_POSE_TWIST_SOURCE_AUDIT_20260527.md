# REPORTE HIL - Auditoria de fuentes Unitree pose/twist/odometry - 20260527

## Alcance

Auditoria read-only orientada a localizar una fuente traslacional real para un futuro `odom_bridge`. Esta sesion no implemento `odom_bridge`, no publico DDS ni ROS y no ejecuto mapping.

## Baseline Git y gate de seguridad

- Repositorio canonico robot: `tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE`, rama `robot`.
- HEAD al iniciar auditoria remota: `181e475`.
- `origin/robot` al iniciar: `181e475`.
- Ahead/behind al iniciar: `0 0`.
- Tracked dirty al iniciar: vacio.
- Untracked observados: solo `codigo ottoguide/logs/` y `codigo ottoguide/artifacts/`, permitidos para esta sesion.
- Runtime inseguro preexistente: no detectado.
- Copia notebook: actualizada en fast-forward desde `224df18` a `181e475` usando el remoto canonico existente `target-uade`.

## Contexto previo no repetido

El probe HG documentado en `REPORTE_HIL_UNITREE_HG_STATE_PROBE_20260527.md` ya valido mensajes en:

- `rt/lowstate`: aproximadamente 1052 Hz, IMU y motor state.
- `rt/secondary_imu`: aproximadamente 1052 Hz, IMU.
- `rt/sportmodestate`: aproximadamente 100 Hz, estado/FSM.

Ese resultado no demostro pose XY ni velocidad corporal. Estos canales no se repitieron como fuente principal en esta sesion.

## Tipos y headers SDK encontrados

La inspeccion read-only encontro tipos potencialmente relevantes instalados:

- `unitree/idl/ros2/Odometry_.hpp`
- `unitree/idl/ros2/Pose2D_.hpp`
- `unitree/idl/ros2/PoseStamped_.hpp`
- `unitree/idl/ros2/PoseWithCovariance*.hpp`
- `unitree/idl/ros2/Twist_.hpp`
- `unitree/idl/ros2/TwistStamped_.hpp`
- `unitree/idl/ros2/TwistWithCovarianceStamped_.hpp`
- `unitree/idl/go2/LidarState_.hpp`
- `unitree/idl/go2/VoxelMapCompressed_.hpp`
- `unitree/idl/go2/UwbState_.hpp`

La existencia de IDL no prueba que el G1 publique esos mensajes en un canal accesible actualmente.

## Procesos, servicios y logs inspeccionados

Procesos Unitree visibles durante la inspeccion:

- `/unitree/module/master_service/master_service`
- `/unitree/ota/pipe/ota_pipe_service`
- procesos `videohub_pc4`

Unidades relevantes visibles:

- `master_service.service` activo.
- `ota_pipe.service` activo.
- `unitree-upgrade.service` activo.

Evidencia de configuracion:

- Se encontro configuracion de `master_service` con `slam_nav: 0`.

Logs historicos encontrados:

- logs `UnitreeSlam_*` sin nombres de topics utiles en las muestras inspeccionadas.
- logs `lio_sam_ros2_dogOdomForMapping_*` y `lio_sam_ros2_dogOdomForReloc_*` que evidencian ejecuciones historicas.
- logs `lio_sam_ros2_mapOptmization_*` y `lio_sam_ros2_globalLocalize_*`.
- archivos `high_rate_state_*` encontrados sin contenido util observado.
- workspace historico `/home/unitree/unitree/Odometer_service`, no validado como productor activo actual.

## Canales DDS y decision de probe

Referencias de canales concretas detectadas en SDK/binarios se limitaron a fuentes ya conocidas o no aplicables como fuente G1 validada:

- `rt/lowstate`, `rt/secondary_imu`, `rt/sportmodestate`: ya auditados, sin traslacion demostrada.
- referencias Go2/A2 como `rt/lf/sportmodestate`: no constituyen evidencia de publicacion G1 HG actual.
- referencias de comandos/control fueron excluidas por seguridad.

No se descubrio un par concreto de canal y tipo DDS actual para pose, twist, odometry o localization del G1 que justificara compilar y ejecutar un nuevo subscriber.

- Probe `/tmp/ottoguide_unitree_pose_twist_probe.cpp` creado: NO.
- Motivo: no inventar topics ni probar tipos solo por existir headers.
- Canales probados en esta sesion: ninguno.
- Mensajes pose/twist/odometry recibidos: no evaluables; no hubo canal concreto seguro para probar.

## Resultado tecnico

- Pose XY disponible: no validada.
- Body velocity disponible: no validada.
- Odometry disponible: no validada.
- Fuente util para futuro `odom_bridge`: NO validada.
- `odom_bridge` implementado: NO.

Clasificacion final:

```text
CANDIDATE_CHANNELS_FOUND_NOT_VALIDATED
```

La proxima investigacion debe profundizar en `master_service`, artefactos de `UnitreeSlam`/`lio_sam` y su configuracion de topics o IPC para obtener un canal concreto antes de cualquier probe DDS adicional.

## Safety invariants

- Publishers DDS/ROS creados: NO.
- `ChannelPublisher` usado: NO.
- `LocoClient` usado: NO.
- `SportClient` usado: NO.
- `LowCmd` usado: NO.
- Comando de locomocion ejecutado: NO.
- `/cmd_vel` publicado: NO.
- Nav2 ejecutado: NO.
- `scan_gate` ejecutado: NO.
- `slam_toolbox` ejecutado: NO.
- `map_saver_cli` ejecutado: NO.
- Red o `cyclonedds.xml` modificados: NO.
- Paquetes instalados: NO.
- `git reset`, `git clean` o `git push` ejecutados: NO.