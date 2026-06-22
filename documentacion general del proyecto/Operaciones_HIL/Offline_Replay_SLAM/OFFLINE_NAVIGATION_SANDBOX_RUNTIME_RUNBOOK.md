# Offline Navigation Sandbox — Runtime Runbook

**Fase**: Fase 2G — base de runtime ROS aislada + planificación global + control local closed-loop + Collision Monitor + Behavior Server (`Wait`/`Spin`) + BT Navigator (`NavigateToPose`) + Waypoint Follower (`FollowWaypoints`) aislados, todos con evidencia validada. Los smoke tests de planner, controller, collision monitor, behavior server, BT Navigator y Waypoint Follower pasan por completo con éxito. No incluye `NavigateThroughPoses`, Simple Commander, el orquestador de misión de la aplicación paralela, ni los plugins `BackUp`/`DriveOnHeading`/`AssistedTeleop` de behavior_server. Las Fases 2H.1/2H.1.2/2H.1.3 (ver sección dedicada más abajo) agregan `DirectNav2ActionBridge`, validado aislado y todavía no conectado a `main.py`.

## Alcance

Este runbook describe cómo levantar y verificar la base de runtime del sandbox offline de OttoGuide en WSL `Ubuntu-24.04` con ROS 2 `jazzy`, sin robot, sin red externa y sin comandos de velocidad globales.

## Comando exacto

```bash
cd "codigo ottoguide"
bash scripts/run_offline_navigation_runtime.sh
```

Argumentos adicionales se reenvían a `ros2 launch`, por ejemplo:

```bash
bash scripts/run_offline_navigation_runtime.sh sandbox_namespace:=offline_nav use_rviz:=false
```

## Variables de entorno

| Variable | Valor exigido | Notas |
|---|---|---|
| `ROS_LOCALHOST_ONLY` | `1` | Exportada automáticamente por el wrapper. No configurable a otro valor. |
| `ROS_DOMAIN_ID` | Distinto de `0`, default `77` | El wrapper usa `77` si la variable no está seteada. Si está seteada a `0`, el wrapper aborta con error. |

El wrapper ejecuta `verify_sandbox_isolation.py --runtime` antes de iniciar ROS. Si el verificador devuelve `FAIL`, el wrapper aborta sin iniciar ningún nodo.

## Namespace

| Elemento | Configuración |
|---|---|
| Namespace real | `offline_nav` |
| Tópico de velocidad raw | `/offline_nav/cmd_vel_raw` |
| Tópico de velocidad segura | `/offline_nav/cmd_vel_safe` |

## Topics esperados

| Topic | Tipo | Publicador / Consumidor |
|---|---|---|
| `/offline_nav/map` | `nav_msgs/OccupancyGrid` | `map_server` (vía `lifecycle_manager`) |
| `/offline_nav/odom` | `nav_msgs/Odometry` | `offline_runtime_simulator` |
| `/offline_nav/scan` | `sensor_msgs/LaserScan` | `offline_runtime_simulator` |
| `/offline_nav/cmd_vel_raw` | `geometry_msgs/Twist` | Publica: `controller_server`, `behavior_server` / Consume: `collision_monitor` |
| `/offline_nav/cmd_vel_safe` | `geometry_msgs/Twist` | Publica: `collision_monitor` / Consume: `offline_runtime_simulator` |
| `/offline_nav/navigate_to_pose` (acción) | `nav2_msgs/action/NavigateToPose` | Servida por: `bt_navigator`. Orquesta `ComputePathToPose` (`planner_server`) y `FollowPath` (`controller_server`); `bt_navigator` nunca publica velocidad. |
| `/offline_nav/follow_waypoints` (acción) | `nav2_msgs/action/FollowWaypoints` | Servida por: `waypoint_follower`. Envía un goal `NavigateToPose` por waypoint a `bt_navigator`; `waypoint_follower` nunca publica velocidad. |

`/tf` y `/tf_static` permanecen globales (sin namespace), lo cual es seguro porque el aislamiento real lo da `ROS_DOMAIN_ID` + `ROS_LOCALHOST_ONLY=1`, no el namespace de tópicos.

## Frames

| Frame | Publicador | Naturaleza |
|---|---|---|
| `map` → `odom` | `static_transform_publisher` (`map_to_odom_synthetic_tf`) | Identidad sintética. NO es una localización validada. |
| `odom` → `base_link` | `offline_runtime_simulator` (TF dinámico) | Integración cinemática planar 2D. NO representa al G1 real. |
| `base_link` → `utlidar_lidar` | `static_transform_publisher` (`base_link_to_utlidar_lidar_synthetic_tf`) | Identidad sintética de placeholder. NO es un extrínseco físico medido. |

## Timeout y cierre

- El wrapper no impone un timeout de ejecución propio; corre en foreground hasta `SIGINT`/`SIGTERM`.
- Ante `SIGINT` (`Ctrl+C`) o `SIGTERM`, el wrapper envía `SIGINT` al proceso `ros2 launch`, espera su cierre y propaga el exit code real.
- El smoke test (`smoke_test_offline_runtime.py`) sí impone timeout (`--timeout`, default 30s) y cierra el launch que él mismo inició mediante `SIGINT` a su process group, verificando 0 procesos huérfanos propios.

## Smoke test (foundation)

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_runtime.py --domain-id 78 --timeout 30
```

Usa un `ROS_DOMAIN_ID` dedicado (`78` por default, distinto del `77` del wrapper manual) para no interferir con otra sesión del sandbox que pueda estar corriendo. Inicia el runtime mediante el wrapper aislado (`run_offline_navigation_runtime.sh`), no mediante `ros2 launch` directo. Verifica: mensajes en `map`/`odom`/`scan`, presencia de `/tf` y `/tf_static`, ausencia de `/cmd_vel` y `/cmd_vel_nav` globales, ausencia de nodos con nombres asociados a hardware Unitree/Livox/RealSense, y cierre limpio sin procesos huérfanos. Devuelve JSON y exit code (`0`=PASS, `2`=FAIL).

## Planificación global (planner_server)

`planner_server` se activa junto con `map_server` bajo el mismo `lifecycle_manager`. Plugin configurado: `nav2_navfn_planner::NavfnPlanner` (alias `GridBased`). Expone la acción namespaced `/offline_nav/compute_path_to_pose` (`nav2_msgs/action/ComputePathToPose`).

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_planner.py --domain-id 85 --timeout 40
```

Inicia el runtime vía el mismo wrapper aislado, espera a que `planner_server` esté activo (verificado con `ros2 lifecycle get`, no solo descubrimiento del nodo), envía un goal `ComputePathToPose` con start `(-0.75, 0.0)` y goal `(0.75, 0.0)` en frame `map` (orientación identidad, sobre el mapa sintético versionado, tolerancia de endpoint `0.10m`), y verifica: planner activo, action server disponible, resultado `SUCCEEDED`, al menos 2 poses, primera pose cerca del start, última cerca del goal, todas las poses finitas, frame `map`, y cierre sin procesos huérfanos.

Nota: el launch ahora reescribe `nav2_offline_sandbox_params.yaml` con `RewrittenYaml`/`ParameterFile` usando el namespace del sandbox como `root_key`, de forma que los parámetros anidados de plugin (`GridBased.tolerance`, `GridBased.plugin`) se aplican realmente bajo `/offline_nav/planner_server`, en vez de caer silenciosamente al default de stock Nav2.

## Control local (controller_server) — READY

`controller_server` y `local_costmap` están implementados en el launch y los parámetros, con remap `cmd_vel` → `cmd_vel_raw` (resolviendo a `/offline_nav/cmd_vel_raw`). El `lifecycle_manager_navigation` activa `map_server`/`planner_server`, y un `lifecycle_manager_controller` dedicado activa `controller_server` de forma aislada.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_controller.py --domain-id 92 --timeout 60
```

**El control local está completamente validado.** `controller_server` alcanza `ACTIVE` de forma reproducible, sigue la ruta y el simulador avanza con éxito. La cancelación detiene de forma efectiva el movimiento.

## Seguridad ante colisiones (collision_monitor) — READY

`collision_monitor` y su lifecycle manager dedicado están integrados en el runtime, filtrando comandos en la cadena definitiva: `controller_server` -> `cmd_vel_raw` -> `collision_monitor` -> `cmd_vel_safe` -> `offline_runtime_simulator`.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_collision_monitor.py --base-domain-id 200 --timeout 60
```

Prueba cinco escenarios de seguridad (Clear, Slowdown, Stop, Recovery, Cancel) bajo domain IDs independientes (un domain por escenario, derivado del `--base-domain-id`; ej. `200`-`204` y `210`-`214` en dos corridas independientes reproducidas), confirmando:
- Reducción de velocidad en la zona slowdown (mediana de ratio safe/raw observada `0.40`/`0.4222`, esperado `0.35`-`0.45`).
- Velocidad sin filtrar en zona clear (mediana de ratio `0.9737`/`1.0`, esperado `0.90`-`1.10`).
- Parada total (velocidad safe cero) en la zona stop, con pose estable.
- Recuperación automática del avance tras remover obstáculos (`stop_safe_zero_observed` → `recovery_safe_nonzero_observed` → avance `>0.01m`).
- Cancelación limpia de metas tras inicio de movimiento, con parada confirmada (`STATUS_CANCELED`, `cmd_vel_safe` y twist de odometría en cero, pose estable).

El emparejamiento raw/safe es causal e independiente del resultado esperado: para cada muestra `cmd_vel_safe` se busca la muestra `cmd_vel_raw` más reciente con timestamp anterior o igual y delta máximo `0.25s`, sin reutilizar muestras safe, descartando pares con `abs(raw.linear.x) < 0.02`, y exigiendo al menos 3 pares válidos antes de calcular la mediana. `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`: esta validación es exclusivamente sintética en simulación offline.

## Behavior Server (`Wait`, `Spin`) — READY

`behavior_server` y su `lifecycle_manager_behavior_server` dedicado están integrados en el runtime, con remap `cmd_vel` → `cmd_vel_raw` idéntico al de `controller_server`, de forma que toda salida de `behavior_server` también pasa por `collision_monitor` antes de llegar al simulador. Solo los plugins `Wait` y `Spin` están configurados; `BackUp`, `DriveOnHeading` y `AssistedTeleop` quedan fuera de alcance.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_behavior_server.py --base-domain-id 160 --timeout 60
```

El CLI deriva tres domain IDs consecutivos desde `--base-domain-id` (uno por escenario: Wait, Spin, Cancel Spin). Prueba:
- **Wait**: acción `SUCCEEDED`, pose estable, twist de odometría cero, y ningún comando `cmd_vel_safe` angular no-cero observado.
- **Spin** (`target_yaw=0.50 rad`): observa `cmd_vel_raw` y `cmd_vel_safe` angular no-cero (ambos `0.30 rad/s`, igual a `max_rotational_vel`), `SUCCEEDED`, error angular final dentro de tolerancia (`0.15 rad`), traslación mínima, twist final cero, pose estable después.
- **Cancel Spin** (`target_yaw=3.0 rad`): observa movimiento angular real antes de cancelar, exige `CANCELED`, `cmd_vel_safe` angular cero, twist de odometría cero, y pose estable durante al menos `0.5s` tras cancelar.

Validado en dos corridas completas e independientes (domain IDs `160`-`162` y `170`-`172`), sin cambios de código entre ellas, ambas con los tres escenarios en `PASS`, sin tópicos prohibidos, sin nodos de hardware/misiones, y sin procesos huérfanos. `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`. Detalle completo en [OFFLINE_NAVIGATION_BEHAVIOR_SERVER_REPORT.md](OFFLINE_NAVIGATION_BEHAVIOR_SERVER_REPORT.md).

## BT Navigator (`NavigateToPose`) — READY

`bt_navigator` y su `lifecycle_manager_bt_navigator` dedicado están integrados en el runtime. Configurado únicamente con el navigator `nav2_bt_navigator::NavigateToPoseNavigator` y el árbol mínimo versionado `config/navigation/bt/offline_navigate_to_pose.xml` (`ComputePathToPose -> FollowPath`, sin recoveries). `bt_navigator` no remapea ningún tópico de velocidad y nunca publica `cmd_vel_raw`/`cmd_vel_safe` directamente; el movimiento real proviene exclusivamente de `controller_server`, igual que cualquier otro `FollowPath`. `NavigateThroughPoses` no está habilitado.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_bt_navigator.py --base-domain-id 180 --timeout 60
```

El CLI deriva dos domain IDs consecutivos desde `--base-domain-id` (uno por escenario: éxito y cancelación). Prueba:
- **Éxito**: objetivo calculado dinámicamente `~0.5m` por delante de la pose inicial real (nunca asumida en `(0,0)`), acción `SUCCEEDED`, telemetría real (`odom`/`cmd_vel_raw`/`cmd_vel_safe` no vacíos, con muestras no-cero observadas), distancia recorrida `>0.05m`, distancia final al objetivo `<0.12m`, twist final cero, pose estable.
- **Cancelación**: objetivo más lejano (`~1.5m`), cancelación enviada solo tras observar movimiento real (`raw`/`safe` no cero y pose desplazada `>0.02m`). `cancel_request_accepted` exige la respuesta real de `action_msgs/srv/CancelGoal` (`return_code == ERROR_NONE` y el UUID de la meta presente en `goals_canceling`), no solo que el future de `cancel_goal_async()` haya terminado (corrección de Fase 2F.1). Exige además `CANCELED`, mensaje `cmd_vel_safe` y `odom` posteriores a la cancelación, ambos asentados en cero, y pose estable tras cancelar.

Validado en dos corridas completas e independientes (domain IDs `180`-`181` y `190`-`191`), sin cambios de código entre ellas, ambos escenarios en `PASS`, sin tópicos prohibidos, sin nodos de hardware/misiones, y sin procesos huérfanos. `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`. Detalle completo en [OFFLINE_NAVIGATION_BT_NAVIGATOR_REPORT.md](OFFLINE_NAVIGATION_BT_NAVIGATOR_REPORT.md).

## Waypoint Follower (`FollowWaypoints`) — READY

`waypoint_follower` y su `lifecycle_manager_waypoint_follower` dedicado están integrados en el runtime. Configurado con `stop_on_failure=true` y `waypoint_task_executor_plugin="wait_at_waypoint"` (`nav2_waypoint_follower::WaitAtWaypoint`, `waypoint_pause_duration=0`, deshabilitando explícitamente cualquier efecto lateral del plugin). `waypoint_follower` no remapea ningún tópico de velocidad y nunca publica `cmd_vel_raw`/`cmd_vel_safe` directamente; envía un goal `NavigateToPose` por waypoint a `bt_navigator`, reutilizando íntegramente la cadena ya validada en Fase 2F.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_waypoint_follower.py --base-domain-id 200 --timeout 90
```

El CLI deriva tres domain IDs consecutivos desde `--base-domain-id` (uno por escenario: éxito, cancelación, inalcanzable). Prueba:
- **Éxito**: ruta de 3 waypoints sintéticos calculados por offsets desde la pose inicial real (nunca asumida en `(0,0)`), dentro de los límites del mapa. Exige `follow_waypoints_action_available`, `goal_accepted`, feedback recibido, progresión normalizada de `current_waypoint` exactamente `[0, 1, 2]` (sin huecos ni retrocesos — `_normalize_progress` colapsa solo duplicados consecutivos, nunca trata `[0, 2]` o `[0]` como equivalentes a la cobertura completa), `waypoints_reached == waypoints_requested == 3`, `missed_waypoints == []`, acción `SUCCEEDED`, telemetría real no-cero, distancia recorrida observada, llegada dentro de tolerancia, y twist/pose finales estables.
- **Cancelación**: ruta de 3 waypoints más larga, cancelada solo tras observar movimiento real *pasado el primer waypoint* (`current_waypoint >= 1` en el feedback, no solo desplazamiento mínimo). `cancel_request_accepted` exige la respuesta real de `action_msgs/srv/CancelGoal` (`return_code == ERROR_NONE` y el UUID de la meta presente en `goals_canceling`), mismo contrato endurecido en Fase 2F.1. Exige además `CANCELED`, mensajes `cmd_vel_safe`/`odom` posteriores a la cancelación asentados en cero, y pose estable.
- **Inalcanzable**: ruta de 3 waypoints donde el segundo (índice `1`) está deliberadamente fuera de los límites del mapa fixture (`UNREACHABLE_WAYPOINT_XY = (5.0, 5.0)`; los límites reales son `x ∈ [-1.0, 1.0]`, `y ∈ [-0.75, 0.75]`, confirmados por inspección directa de `offline_sandbox_test_map.pgm`/`.yaml`, no asumidos). Exige acción `ABORTED` (nunca `RESULT_TIMEOUT`, que jamás se reinterpreta como evidencia de fallo), `missed_waypoints == [1]`, `MissedWaypoint.error_code == 204` (`nav2_msgs/action/ComputePathToPose::GOAL_OUTSIDE_MAP`, confirmado localmente vía `ros2 interface show`), y que el feedback nunca progrese al waypoint índice `2` — prueba concreta de que `stop_on_failure=true` detiene la ruta en el punto de fallo.

Validado en dos corridas completas e independientes (domain IDs `200`-`202` y `210`-`212`), sin cambios de código entre ellas, los tres escenarios en `PASS` en ambas corridas, sin tópicos prohibidos, sin nodos de hardware/Simple Commander, y sin procesos huérfanos. Cada escenario escribe su log de `ros2 launch` a un archivo dedicado bajo `/tmp` (`/tmp/ottoguide_waypoint_<escenario>_<domain>.log`) en vez de `stdout=subprocess.PIPE` sin consumidor, evitando que el buffer del pipe se llene y bloquee el proceso lanzado. `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`. Detalle completo en [OFFLINE_NAVIGATION_WAYPOINT_FOLLOWER_REPORT.md](OFFLINE_NAVIGATION_WAYPOINT_FOLLOWER_REPORT.md).

## DirectNav2ActionBridge — validado aislado, no conectado a `main.py`

`DirectNav2ActionBridge` (`src/navigation/direct_nav2_action_bridge.py`) es un cliente `rclpy.action.ActionClient` directo contra `/offline_nav/navigate_to_pose` y `/offline_nav/follow_waypoints`, sin `BasicNavigator`/Simple Commander y sin publicar velocidad (solo `/initialpose`). Implementado y validado de forma aislada en las Fases 2H.1/2H.1.2/2H.1.3; **no está conectado** a `main.py`/`TourOrchestrator` (`MAIN_RUNTIME_MIGRATED=NO`). Esa conexión es trabajo exclusivo de la Fase 2H.2, todavía no autorizada.

La Fase 2H.1.3 cerró brechas puntuales de evidencia: `close()` ahora detecta degradación preexistente (no solo fallos reactivos de cancelación), el smoke ya no silencia errores de cierre del bridge/observer, el escenario `FollowWaypoints` inalcanzable nunca acepta `REJECTED` como sustituto de `ABORTED`, y los JSON de los procesos hijos del smoke usan una ruta única por invocación con validación de identidad y exit code.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_direct_nav2_action_bridge.py --base-domain-id 212 --timeout 120
```

El CLI público acepta únicamente `--base-domain-id`, `--timeout` y `--output`. Internamente, el proceso padre deriva cuatro `ROS_DOMAIN_ID` (offsets `0`-`3`) y lanza un proceso hijo aislado por escenario (flag interno `--scenario`, no expuesto en uso normal); cada hijo inicializa `rclpy` una sola vez, levanta el sandbox vía el wrapper, crea un `DirectNav2ActionBridge` y un observador de telemetría independiente (contexto/nodo/thread propios), y cierra todo antes de terminar. Prueba:
- **NavigateToPose éxito** (offset `0`): objetivo dinámico `~0.50m` por delante de la pose inicial real. Exige `goal_accepted`, UUID no vacío, `feedback_count>0`, `>=2` muestras de `distance_remaining` con reducción neta, `SUCCEEDED`, telemetría `raw`/`safe` no-cero, `distance_moved>0.05m`, `final_goal_distance<0.12m`, twists finales en cero, pose estable.
- **NavigateToPose cancelación** (offset `1`): objetivo `~1.5m`. No cancela hasta observar feedback, reducción de `distance_remaining>=0.02m` y desplazamiento real `>0.02m`. Exige `cancel_requested`/`cancel_accepted`, UUID coincidente con `goals_canceling`, terminal `CANCELED`, twists finales en cero, pose estable.
- **FollowWaypoints éxito** (offset `2`): tres waypoints relativos `(0.30,0.00)`, `(0.30,0.20)`, `(0.00,0.20)`, interpretados como desplazamientos acumulativos (cada offset relativo al waypoint anterior) — misma resolución que usa, sin cambios, `smoke_test_offline_waypoint_follower.py` para idéntica tupla. Exige progresión de feedback normalizada exactamente `[0,1,2]`, `SUCCEEDED`, `missed_waypoints=[]`, telemetría no-cero, twists finales en cero, pose estable.
- **FollowWaypoints inalcanzable** (offset `3`): waypoint 0 alcanzable, waypoint 1 absoluto `(5.0, 5.0)` (fuera del mapa), waypoint 2 alcanzable. Exige `ABORTED`, `missed_waypoints=[1]`, `error_code=204`/`GOAL_OUTSIDE_MAP`, feedback que nunca progresa al índice 2.

Inspección real del grafo del nodo del bridge vía `ros2 node info /offline_nav/direct_nav2_action_bridge`: se exige que no tenga publishers/subscribers de ningún tópico de velocidad (`cmd_vel`/`cmd_vel_nav`/`cmd_vel_raw`/`cmd_vel_safe`), y se confirma disponibilidad de ambas acciones vía `ros2 action list`.

Validado en dos corridas completas e independientes (domain IDs `220`-`223` y `224`-`227`), sin cambios de código entre ellas, los cuatro escenarios en `PASS` en ambas corridas, sin procesos huérfanos. Un intento intermedio sufrió una carrera de timing transitoria bajo carga WSL (mismo patrón documentado más abajo para otros componentes), resuelta repitiendo la corrida sin tocar código. `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`. Detalle completo en [DIRECT_NAV2_ACTION_BRIDGE_2H1_REPORT.md](../../Arquitectura/DIRECT_NAV2_ACTION_BRIDGE_2H1_REPORT.md).

## Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| El wrapper aborta con `ERROR este wrapper debe ejecutarse dentro de WSL` | Se ejecutó desde PowerShell/cmd nativo de Windows en vez de WSL | Ejecutar desde una shell `wsl -d Ubuntu-24.04`. |
| El wrapper aborta con `ERROR ROS_DOMAIN_ID=0 no esta permitido` | Variable de entorno heredada de otra sesión | `unset ROS_DOMAIN_ID` antes de correr el wrapper, o exportar un valor explícito distinto de `0`. |
| El verificador runtime devuelve `FAIL` antes de iniciar ROS | Aislamiento incompleto (`ROS_LOCALHOST_ONLY` no es `1`, o referencia prohibida en algún archivo nuevo) | Revisar el campo `errors` del JSON impreso por el wrapper; no forzar la ejecución. |
| El smoke test no recibe mensaje de `map`/`odom`/`scan` dentro del timeout | `nav2_map_server`/`lifecycle_manager` no llegaron a `ACTIVE`, o el simulador no arrancó | Aumentar `--timeout`, revisar el log de `ros2 launch` por errores de `map_server`/`lifecycle_manager`. |
| `ros2 topic list` no devuelve nada | `ROS_DOMAIN_ID`/`ROS_LOCALHOST_ONLY` distintos entre el publicador y el cliente que lista | Confirmar que la shell que ejecuta `ros2 topic`/`ros2 node` tiene las mismas variables que el wrapper o el smoke test. |
| `ACTION_SERVER_NOT_AVAILABLE` en el smoke test del planner | `planner_server` no llegó a `active` dentro del timeout, o el cliente de la acción no sourceó ROS antes de `rclpy.init()` | Aumentar `--timeout`; confirmar `ros2 lifecycle get /offline_nav/planner_server` devuelve `active`. |
| `GOAL_REJECTED` o `path_result` distinto de `SUCCEEDED` | Start/goal fuera del mapa, dentro de un obstáculo, o plugin de planner mal configurado en el YAML | Revisar `tolerance`/`allow_unknown` en `nav2_offline_sandbox_params.yaml`; confirmar que las coordenadas caen dentro de los límites del mapa sintético (`x ∈ [-1.0, 1.0]`, `y ∈ [-0.75, 0.75]`). |
| `CONTROLLER_SERVER_LIFECYCLE_ACTIVE_NOT_CONFIRMED` o `controller_server` en `FATAL`/`Couldn't load critics!` | Carga de parámetros anidados de plugin sin reescritura namespaced (`ParameterFile`/`RewrittenYaml` ausente en el launch) | Resuelto: el launch ahora usa `configured_params = ParameterFile(RewrittenYaml(source_file=PARAMS_FILE, root_key=namespace, convert_types=True), allow_substs=True)`. Si reaparece, confirmar que esta reescritura no fue removida. |
| `collision_monitor` falla al iniciar con `Wrong parameter type` | Parámetro `points` configurado como `double_array` en vez de `string` | Resuelto: en el ROS 2 Jazzy de este entorno, la propiedad `points` de las zonas de colisión debe ser de tipo `string` (ej. `"[[x1,y1],...]"`) y no un arreglo de números dobles. |
| El smoke test de Collision Monitor falla con `EXCEPTION: Command ['ros2', 'lifecycle', 'get', ...] timed out after 5.0 seconds` | Timeout transitorio de la CLI `ros2` (carga acumulada tras varios lanzamientos secuenciales en la misma sesión WSL); `_run()` no capturaba `subprocess.TimeoutExpired`, por lo que escapaba como excepción en vez de permitir que el bucle de reintento (`_wait_for_lifecycle_active`) siguiera esperando hasta su propio deadline | Resuelto: `_run()` ahora captura `subprocess.TimeoutExpired` y devuelve un `CompletedProcess` con `returncode=1`, dejando que los bucles de reintento existentes manejen la espera normalmente. |
| Cualquier smoke test falla con todos los componentes en `*_NOT_CONFIRMED` y error RTPS `Calculated port number is too high` | `ROS_DOMAIN_ID` (o el derivado de `--base-domain-id`) excede el límite de FastDDS (`> 232`) | Usar un `--base-domain-id` tal que ningún domain ID derivado supere `232`. |
| El smoke test de Behavior Server falla con `ODOM_NOT_RECEIVED` aunque todos los nodos estén `ACTIVE` | El cliente de smoke test se suscribió a un tópico relativo (`odom`) sin namespace aplicado al propio proceso cliente, resolviendo a `/odom` global en vez de `/offline_nav/odom` | Resuelto: el cliente se suscribe explícitamente a `f"/{namespace}/odom"`, `f"/{namespace}/cmd_vel_raw"` y `f"/{namespace}/cmd_vel_safe"`. |
| El escenario Spin del smoke test de Behavior Server falla con `final_twist_zero: false` | La medición del twist final ocurrió antes de que el watchdog del simulador (`0.5s`) expirara y se asentara el `cmd_vel=0` explícito que `behavior_server` publica al completar `SUCCEEDED` | Resuelto: se espera `1.0s` (en vez de `0.5s`) entre el resultado `SUCCEEDED` y la medición del twist final. |
| El escenario Wait del smoke test de Behavior Server reporta `safe_messages_received: 0` | Esperado, no es un defecto: `nav2_behaviors::Wait` (`/opt/ros/jazzy/include/nav2_behaviors/timed_behavior.hpp`) solo llama a `stopRobot()` (el único `cmd_vel` explícito de un behavior) en las rutas de preempt/cancel, nunca en la finalización normal `SUCCEEDED`, por lo que un Wait exitoso produce legítimamente cero mensajes `cmd_vel_raw`/`cmd_vel_safe` | No se requiere acción; el gate de éxito usa `odom_twist_zero` (siempre disponible vía el timer periódico del simulador) en vez de exigir `safe_messages_received > 0`. |
| El escenario de cancelación del smoke test de BT Navigator falla con `safe_zero_after_cancel: false` u `odom_zero_after_cancel: false` pese a `cancel_result: CANCELED` | La medición del twist ocurrió en el primer mensaje recibido tras la cancelación, antes de que el watchdog del simulador (`0.5s`) asentara la velocidad en cero | Resuelto: se espera el settle completo (`2.0s`) tras el resultado `CANCELED` antes de medir `cmd_vel_safe`/twist de odometría. |
| Cualquier smoke test multi-escenario falla con `DERIVED_DOMAIN_ID_OUT_OF_RANGE` o `INVALID_DOMAIN_ID` antes de iniciar ningún nodo | `--base-domain-id` (o el ID derivado de un offset) cae fuera de `1..232`, o el valor suministrado no es un entero (`"abc"`, `"12.5"`, cadena vacía, solo espacios) | Comportamiento esperado: usar un `--base-domain-id` entero tal que `base` y `base + maximum_offset` del componente (`2` Behavior Server, `4` Collision Monitor, `1` BT Navigator, `2` Waypoint Follower) queden dentro de `1..232`. Desde Fase 2F.1, un `--base-domain-id` no entero devuelve `INVALID_DOMAIN_ID` con `exit=2` y JSON estructurado, nunca un traceback. |
| El escenario de éxito del smoke test de Waypoint Follower falla con `WAYPOINT_FOLLOWER_ACTIVE_NOT_CONFIRMED` y `orphan_processes: 1`, mientras los otros dos escenarios de la misma corrida pasan sin problema | Carrera de timing real observada bajo carga WSL: el log mostró `[WARN] [...waypoint_follower.rclcpp]: failed to send response to /offline_nav/waypoint_follower/change_state (timeout)` — la respuesta del servicio de `change_state` para la transición Configure se perdió/expiró, por lo que `lifecycle_manager_waypoint_follower` nunca recibió confirmación y nunca emitió la transición Activate, quedando bloqueado hasta el timeout del smoke test. No es un defecto de diseño: los otros lifecycle managers de la misma corrida activaron sus nodos normalmente segundos después | Reproducido como transitorio: una repetición de la corrida completa, sin ningún cambio de código, completó los tres escenarios en `PASS`. Si reaparece de forma persistente (no aislada a una sola corrida), investigar contención de CPU en WSL durante el bringup simultáneo de ~18 procesos ROS. |
| El escenario inalcanzable del smoke test de Waypoint Follower no falla (acción `SUCCEEDED`, `missed_waypoints: []`) al usar un punto dentro de una celda ocupada interior del mapa fixture | Hipótesis original incorrecta: a la resolución de este mapa (`0.05m`), un solo píxel ocupado es más fino que el footprint+inflation efectivos del planner/costmap, que lo rodea exitosamente; la celda sí está ocupada (confirmado por inspección directa del `.pgm`), pero la ocupación de un solo píxel no implica inalcanzabilidad | Resuelto: se sustituyó el punto por uno fuera de los límites reales del mapa (`UNREACHABLE_WAYPOINT_XY = (5.0, 5.0)`), confirmado mediante una corrida ROS diagnóstica real que produjo `ABORTED`/`missed_waypoints=[1]`/`error_code=204` (`GOAL_OUTSIDE_MAP`). Si se necesita en el futuro un punto inalcanzable *dentro* de los límites del mapa, usar un obstáculo de varias celdas de espesor, no un solo píxel. |
| Una regresión de Behavior Server o BT Navigator falla con `mission_node_detected: true` tras integrar Waypoint Follower, aunque el nodo descubierto sea exactamente el `/offline_nav/waypoint_follower` aprobado | `FORBIDDEN_MISSION_NODE_SUBSTRINGS` en `smoke_test_offline_behavior_server.py` y `smoke_test_offline_bt_navigator.py` (archivos de fases previas a la 2G) incluía el substring genérico `"waypoint_follower"`, escrito cuando ese componente todavía no existía en el sandbox | Resuelto (autorización puntual durante la reanudación de Fase 2G): se eliminó `"waypoint_follower"` de `FORBIDDEN_MISSION_NODE_SUBSTRINGS` en ambos archivos, conservando `"simple_commander"`. La aceptación específica de `/offline_nav/waypoint_follower` (package, executable, namespace, lifecycle aislado) sigue siendo responsabilidad exclusiva de `check_waypoint_follower_contract` en `verify_sandbox_isolation.py`; este cambio no afecta esa validación. |

## Restricciones

- No se publica `/cmd_vel` ni `/cmd_vel_nav` ni `/offline_nav/cmd_vel` en ningún momento; los únicos tópicos de velocidad permitidos son `/offline_nav/cmd_vel_raw` y `/offline_nav/cmd_vel_safe`.
- No se inicia Simple Commander en esta fase. `planner_server`, `controller_server`, `collision_monitor`, `behavior_server` (solo `Wait`/`Spin`), `bt_navigator` (solo `NavigateToPose`) y `waypoint_follower` (solo `FollowWaypoints`) sí están incluidos y activos.
- No se conecta al robot físico, no se usa SSH/SCP, no se contactan IPs `192.168.123.*`.
- No se abren rosbags ni se instala ningún paquete.
- El simulador (`offline_runtime_simulator.py`) integra `cmd_vel_safe` en una pose 2D determinista con límites sintéticos (`0.10 m/s`, `0.30 rad/s`) y watchdog de `0.5s`; no representa odometría validada y no debe usarse como evidencia de L2/L3.
- El planner calcula rutas candidatas sobre el mapa sintético; por sí solo no mueve nada y no constituye evidencia de navegación autónoma.
- `controller_server` con `dwb_core::DWBLocalPlanner` es una elección exclusiva de este sandbox por la incompatibilidad de parámetros detectada; no define ni recomienda el controlador del robot físico.
- `behavior_server` con `max_rotational_vel=0.30 rad/s` y frames sintéticos `odom`/`base_link` es una elección exclusiva de este sandbox; no define ni recomienda parámetros para el robot físico. No se configuraron `BackUp`, `DriveOnHeading` ni `AssistedTeleop`.
- `waypoint_follower` con `waypoint_task_executor_plugin="wait_at_waypoint"` y `waypoint_pause_duration=0` es una elección exclusiva de este sandbox (el plugin estándar más simple, sin efectos laterales); no representa ninguna tarea de misión real (foto, interacción, audio) en cada waypoint.
