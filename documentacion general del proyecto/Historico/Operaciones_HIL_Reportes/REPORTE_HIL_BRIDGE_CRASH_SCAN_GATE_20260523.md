# Reporte HIL - Bridge crash bloquea gate `/scan`

## Estado Git

- Rama: `robot`
- HEAD al inicio: `2c87f78`
- origin/robot: `2c87f78`
- Ahead/behind inicial: `0	0`
- Estado tracked: clean antes del reporte
- Logs untracked: presentes o permitidos, no stageados

## Clasificacion

`SCAN_GATE_BLOCKED_BY_BRIDGE_CRASH`

## Resumen

El bridge Livox SDK2 ya habia sido validado internamente y mediante DDS:

- callbacks Livox: confirmados
- enqueue: confirmado
- timer: confirmado
- publish interno: confirmado
- DDS graph: confirmado
- `/utlidar/cloud`: visible
- `/livox/imu`: visible
- subscriber QoS BEST_EFFORT/VOLATILE: recibio mensajes

El bloqueo de `ros2 topic hz` quedo clasificado como limitacion/QoS de CLI Foxy. Un subscriber temporal con QoS BEST_EFFORT/VOLATILE recibio 12134 clouds y 2000 IMUs en 10 s.

Sin embargo, al preparar el gate controlado hacia `pointcloud_to_laserscan`, el bridge volvio a caer antes de ejecutar el conversor. Por lo tanto, `/scan` no quedo validado.

## Decision documental

- Raiz documental encontrada: `documentacion general del proyecto`
- Carpetas consideradas: `Operaciones_HIL`, `Auditorias`, `Arquitectura`, `Historico`, `Investigacion`
- Carpeta elegida: `documentacion general del proyecto/Operaciones_HIL`
- Carpeta nueva creada: NO
- Motivo: `Operaciones_HIL` ya contiene runbooks, protocolos y reportes operativos HIL, por lo que es la ubicacion mas especifica.

## Evidencia conocida

- `pointcloud_to_laserscan` esta instalado.
- `pointcloud_to_laserscan` no llego a ejecutarse en el intento fallido final.
- El bridge cayo con `exit code -11` o dejo de estar vivo antes del check.
- Se observaron indicios previos de `std::bad_alloc`.
- Se observaron muchos `MARK_124`, asociados a presion de cola.
- Con `debug_log_lifecycle_markers:=false`, los logs siguieron mostrando flood de markers.
- El agente detecto que `mark_lifecycle()` imprimia por `std::cerr` aunque el flag debug estuviera apagado.
- Se detecto al menos un print directo `MARK_BAD_ALLOC`.

## Evidencia auditada en esta sesion

- Logs relevantes encontrados:

```text
logs/bridge_marker_gated_stability_clean_20260523_012441.log
logs/bridge_marker_gated_stability_clean_20260523_012441.log
logs/bridge_marker_gated_stability_20260523_012322.log
logs/bridge_scan_gate_retry_20260523_011408.log
logs/bridge_hz_probe_sensorqos_20260523_010001.log
logs/bridge_hz_probe_20260523_005847.log
```

- Evidencia `bad_alloc` / `MARK_BAD_ALLOC`: NO
- Evidencia `exit code -11` / segmentation: YES
- Evidencia `MARK_124`: YES
- Evidencia de marker flood: YES

Extracto acotado:

```text
52146:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52156:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52163:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52380:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52387:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52394:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52404:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52411:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52629:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52636:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52643:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52653:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52660:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52877:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52884:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52894:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52901:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
52908:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53125:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53132:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53142:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53149:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53156:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53373:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53380:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53390:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53397:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53404:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53621:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53628:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53638:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53645:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53862:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53869:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53879:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53886:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
53893:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
MARK_COUNT=53644
--- logs/bridge_scan_gate_retry_20260523_011408.log ---
9955:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10172:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10182:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10189:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10196:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10203:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10420:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10430:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10437:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10444:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10451:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10671:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10678:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10685:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10692:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10699:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10921:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10928:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10935:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
10942:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11159:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11169:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11176:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11183:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11190:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11407:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11417:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11424:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11431:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11438:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11655:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11665:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11672:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11679:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11686:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11903:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11913:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11920:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11927:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
11934:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12154:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12161:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12168:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12175:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12392:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12402:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12409:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12416:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12423:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12430:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12652:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12659:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12666:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12673:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12680:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12900:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12907:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12914:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
12921:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13138:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13148:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13155:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13162:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13169:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13386:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13396:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13403:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13410:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13417:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13634:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13644:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13651:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13658:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13665:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13885:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13892:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13899:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13906:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
13913:[livox_sdk_bridge_node-1] MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP
14057:[ERROR] [livox_sdk_bridge_node-1]: process has died [pid 13968, exit code -11, cmd '/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/ros2_ws/install/ottoguide_livox_sdk_bridge/lib/ottoguide_livox_sdk_bridge/livox_sdk_bridge_node --ros-args -r __node:=livox_sdk_bridge_node --params-file /tmp/launch_params_ov37vng4'].
MARK_COUNT=13990
```

## Auditoria de markers en codigo

La auditoria de solo lectura confirma que el fuente actual conserva llamadas a `mark_lifecycle(...)`, el parametro `debug_log_lifecycle_markers`, escritura por `std::cerr` y al menos un print directo `MARK_BAD_ALLOC`.

```text
71:    mark_lifecycle("MARK_001_NODE_CONSTRUCT_START");
107:    debug_log_lifecycle_markers_ = declare_parameter<bool>("debug_log_lifecycle_markers", true);
109:    mark_lifecycle("MARK_010_PARAMS_LOADED");
143:    mark_lifecycle("MARK_020_PUBLISHERS_CREATED");
154:    mark_lifecycle("MARK_030_TIMER_CREATED");
161:      mark_lifecycle("MARK_039_SDK_DISABLED");
165:    mark_lifecycle("MARK_040_SDK_INIT_START");
175:    mark_lifecycle("MARK_041_SDK_INIT_OK");
182:      mark_lifecycle("MARK_050_CALLBACK_REGISTER_START");
185:      mark_lifecycle("MARK_051_CALLBACK_REGISTER_OK");
187:      mark_lifecycle("MARK_052_CALLBACK_REGISTER_DISABLED");
194:    mark_lifecycle("MARK_060_SDK_START_START");
204:    mark_lifecycle("MARK_061_SDK_START_OK");
215:    mark_lifecycle("MARK_070_SPIN_READY");
228:    mark_lifecycle("MARK_999_SHUTDOWN");
237:  void mark_lifecycle(const std::string & marker)
244:    if (debug_log_lifecycle_markers_) {
247:    std::cerr << marker << std::endl;
260:    mark_lifecycle("MARK_STAGE_STOP_" + reason);
307:      node->mark_lifecycle("MARK_080_CALLBACK_POINTCLOUD_ENTER");
327:      node->mark_lifecycle("MARK_090_CALLBACK_IMU_ENTER");
438:    std::cerr << "MARK_BAD_ALLOC context=" << context << " last_marker=" << marker
454:    mark_lifecycle("MARK_120_ENQUEUE_CARTESIAN_ENTER");
457:      mark_lifecycle("MARK_121_ENQUEUE_CARTESIAN_RETURN_UNSAFE_DOT_NUM");
466:      mark_lifecycle("MARK_081_CALLBACK_POINTCLOUD_DROP_DRY_RUN");
467:      mark_lifecycle("MARK_122_ENQUEUE_CARTESIAN_DRYRUN_DROP");
486:    mark_lifecycle("MARK_123_ENQUEUE_CARTESIAN_FRAME_BUILT");
490:      mark_lifecycle("MARK_124_ENQUEUE_CARTESIAN_QUEUE_FULL_DROP");
495:    mark_lifecycle("MARK_125_ENQUEUE_CARTESIAN_QUEUE_PUSH_DONE");
500:    mark_lifecycle("MARK_110_ENQUEUE_POINTCLOUD_ENTER");
502:      mark_lifecycle("MARK_111_ENQUEUE_POINTCLOUD_RETURN_DISABLED");
506:      mark_lifecycle("MARK_112_ENQUEUE_POINTCLOUD_RETURN_NULL_PACKET");
510:      mark_lifecycle("MARK_113_ENQUEUE_POINTCLOUD_RETURN_ZERO_DOT_NUM");
516:        mark_lifecycle("MARK_114_ENQUEUE_POINTCLOUD_HIGH_DATA");
521:        mark_lifecycle("MARK_115_ENQUEUE_POINTCLOUD_LOW_DATA");
526:        mark_lifecycle("MARK_116_ENQUEUE_POINTCLOUD_UNSUPPORTED_TYPE");
537:    mark_lifecycle("MARK_150_PUBLISH_CLOUD_FRAME_ENTER");
539:      mark_lifecycle("MARK_151_PUBLISH_CLOUD_RETURN_DISABLED");
543:      mark_lifecycle("MARK_152_PUBLISH_CLOUD_RETURN_DRYRUN");
547:      mark_lifecycle("MARK_153_PUBLISH_CLOUD_RETURN_NO_PUBLISHER");
551:      mark_lifecycle("MARK_154_PUBLISH_CLOUD_RETURN_EMPTY_FRAME");
556:      mark_lifecycle("MARK_082_CALLBACK_POINTCLOUD_BUILD_START");
599:      mark_lifecycle("MARK_083_CALLBACK_POINTCLOUD_BUILD_DONE");
600:      mark_lifecycle("MARK_084_CALLBACK_POINTCLOUD_PUBLISH_ATTEMPT");
602:      mark_lifecycle("MARK_085_CALLBACK_POINTCLOUD_PUBLISH_DONE");
604:      mark_lifecycle("MARK_086_CALLBACK_POINTCLOUD_EXCEPTION");
621:    mark_lifecycle("MARK_130_ENQUEUE_IMU_ENTER");
623:      mark_lifecycle("MARK_131_ENQUEUE_IMU_RETURN_DISABLED");
627:      mark_lifecycle("MARK_132_ENQUEUE_IMU_RETURN_NULL_PACKET");
632:      mark_lifecycle("MARK_133_ENQUEUE_IMU_RETURN_NON_IMU_DATA");
643:      mark_lifecycle("MARK_134_ENQUEUE_IMU_RETURN_UNSAFE_DOT_NUM");
652:      mark_lifecycle("MARK_091_CALLBACK_IMU_DROP_DRY_RUN");
653:      mark_lifecycle("MARK_135_ENQUEUE_IMU_DRYRUN_DROP");
664:        mark_lifecycle("MARK_136_ENQUEUE_IMU_QUEUE_FULL_DROP");
669:      mark_lifecycle("MARK_137_ENQUEUE_IMU_QUEUE_PUSH_DONE");
675:    mark_lifecycle("MARK_160_PUBLISH_IMU_SAMPLE_ENTER");
677:      mark_lifecycle("MARK_161_PUBLISH_IMU_RETURN_DISABLED");
681:      mark_lifecycle("MARK_162_PUBLISH_IMU_RETURN_DRYRUN");
685:      mark_lifecycle("MARK_163_PUBLISH_IMU_RETURN_NO_PUBLISHER");
690:      mark_lifecycle("MARK_092_CALLBACK_IMU_BUILD_START");
701:      mark_lifecycle("MARK_093_CALLBACK_IMU_BUILD_DONE");
702:      mark_lifecycle("MARK_094_CALLBACK_IMU_PUBLISH_ATTEMPT");
704:      mark_lifecycle("MARK_095_CALLBACK_IMU_PUBLISH_DONE");
706:      mark_lifecycle("MARK_096_CALLBACK_IMU_EXCEPTION");
722:    mark_lifecycle("MARK_140_PUBLISH_TIMER_ENTER");
732:      mark_lifecycle("MARK_141_PUBLISH_TIMER_CLOUD_QUEUE_NONEMPTY");
735:      mark_lifecycle("MARK_142_PUBLISH_TIMER_IMU_QUEUE_NONEMPTY");
738:      mark_lifecycle("MARK_143_PUBLISH_TIMER_EMPTY_QUEUES");
743:        mark_lifecycle("MARK_144_PUBLISH_TIMER_CALL_CLOUD_PUBLISH");
751:        mark_lifecycle("MARK_145_PUBLISH_TIMER_CALL_IMU_PUBLISH");
780:  bool debug_log_lifecycle_markers_{true};
```

## Intento de correccion descartado

Se intento un patch minimo para gatear markers de diagnostico. El build paso, pero la prueba de estabilidad fallo igualmente y el agente restauro el archivo fuente. No se realizo commit de codigo.

## Hipotesis principal

El problema actual no es DDS ni `pointcloud_to_laserscan`.

La hipotesis principal es inestabilidad del bridge bajo carga diagnostica o desalineacion entre codigo fuente parcheado, binario ejecutado y parametros runtime.

Posibles causas a investigar:

1. `mark_lifecycle()` o prints directos siguen escribiendo aunque `debug_log_lifecycle_markers:=false`.
2. El parametro efectivo en runtime no coincide con el valor pasado por launch.
3. El binario ejecutado por `ros2 launch` no corresponde al source recien recompilado.
4. Hay flood de logs en `stderr` que genera presion de memoria.
5. La cola de pointcloud se llena (`MARK_124`) y aumenta presion en memoria.
6. Existe un crash independiente del logging, oculto por el volumen de markers.

## Que NO se ejecuto

- `/scan`
- `pointcloud_to_laserscan` en el intento fallido final
- SLAM
- Nav2
- navegacion
- locomocion
- `/cmd_vel`
- SportClient
- LocoClient

## Proximo plan recomendado

Antes de repetir `/scan`:

1. Auditar con precision el valor runtime de `debug_log_lifecycle_markers`.
2. Confirmar que binario exacto ejecuta `ros2 launch`.
3. Confirmar timestamps/checksum de source, build e install.
4. Crear una prueba minima del nodo con `debug_log_lifecycle_markers:=false` y sin hardware si es posible.
5. Corregir gating de markers en un commit chico.
6. Verificar que el log queda sin flood con el bridge vivo al menos 20 s.
7. Recien despues repetir el gate `pointcloud_to_laserscan`.
8. No avanzar a SLAM/Nav2 hasta que `/scan` exista y tenga rangos finitos.

## Criterio de desbloqueo

Se puede reintentar el gate `/scan` solo cuando:

- bridge vivo al menos 20 s
- `debug_log_lifecycle_markers:=false`
- `grep -c "MARK_" log` sea 0 o bajo
- sin `std::bad_alloc`
- sin `exit -11`
- `/utlidar/cloud` visible
- subscriber QoS recibe clouds
