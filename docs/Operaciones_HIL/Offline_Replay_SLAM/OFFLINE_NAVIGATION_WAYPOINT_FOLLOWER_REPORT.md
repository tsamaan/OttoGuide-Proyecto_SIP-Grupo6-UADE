# Offline Navigation Sandbox — Waypoint Follower Report

**Fase**: Fase 2G — Waypoint Follower aislado (`FollowWaypoints` únicamente) integrado en el sandbox offline, sumado a `planner_server` + `controller_server` + `collision_monitor` + `behavior_server` + `bt_navigator` de fases previas.

`OFFLINE_ONLY` / `SYNTHETIC` / `NOT_FOR_HARDWARE` / `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`.

## Baseline

```text
INITIAL_BRANCH = robot
INITIAL_HEAD = 6fa9f8907bbe22b81ee8674b9c6f3a1f42a805b9
INITIAL_PARENT = 8b5e242c12a2fa490f085f2b3e7fd421550be874
INITIAL_COMMIT_MESSAGE = fix(nav): harden offline smoke contracts
INITIAL_WORKTREE = clean
```

Esta fase se ejecutó en dos tramos: un primer intento que quedó interrumpido a mitad de ejecución (worktree modificado, sin commit), y una reanudación controlada que auditó el estado existente antes de continuar, corrigió varios problemas identificados en la implementación provisional, y completó el resto del ciclo (validación ROS real, regresiones, documentación, commit, pushes).

## Objetivo

Integrar `nav2_waypoint_follower` exclusivamente dentro del sandbox offline, habilitar la acción `/offline_nav/follow_waypoints`, y validar la cadena completa:

```
FollowWaypoints -> Waypoint Follower -> NavigateToPose (uno por waypoint) -> BT Navigator -> ComputePathToPose -> Planner Server -> FollowPath -> Controller Server -> cmd_vel_raw -> Collision Monitor -> cmd_vel_safe -> Offline Runtime Simulator
```

## Alcance

- Waypoint Follower, acción `FollowWaypoints` únicamente, orquestando el `bt_navigator` ya validado en Fase 2F (un goal `NavigateToPose` por waypoint).
- Smoke test ROS real con tres escenarios (éxito, cancelación, waypoint inalcanzable), reproducible en dos corridas independientes.
- Allowlist expandido puntualmente, con autorización explícita, a dos archivos pre-Fase-2G que dejaron de ser correctos tras la integración (`smoke_test_offline_behavior_server.py`, `smoke_test_offline_bt_navigator.py`).

## Fuera de alcance

`NavigateThroughPoses`, Simple Commander, `BasicNavigator`, el orquestador de misión de la aplicación paralela (`src/navigation/nav2_bridge.py`, `src/core/tour_orchestrator.py`), `BackUp`/`DriveOnHeading`/`AssistedTeleop`, navegación física.

## Preflight local (ROS 2 Jazzy, WSL Ubuntu-24.04)

```text
ros2 pkg prefix nav2_waypoint_follower      -> /opt/ros/jazzy
ros2 pkg executables nav2_waypoint_follower -> nav2_waypoint_follower waypoint_follower
```

Contratos inspeccionados localmente (sin Internet, sin documentación web):

- `ros2 interface show nav2_msgs/action/FollowWaypoints`:
  - Goal: `uint32 number_of_loops`, `uint32 goal_index`, `geometry_msgs/PoseStamped[] poses`.
  - Result: `uint16 error_code` (`NONE=0`, `UNKNOWN=600`, `TASK_EXECUTOR_FAILED=601`), `string error_msg`, `MissedWaypoint[] missed_waypoints` (cada uno con `uint32 index`, `geometry_msgs/PoseStamped goal`, `uint16 error_code`).
  - Feedback: `uint32 current_waypoint` únicamente (sin lista de índices adicional).
- `ros2 interface show action_msgs/srv/CancelGoal` — mismo contrato ya validado y endurecido en Fase 2F.1 (`return_code`, `goals_canceling[].goal_id.uuid`).
- `ros2 interface show nav2_msgs/action/ComputePathToPose` — confirma los códigos de error reales: `NONE=0`, `UNKNOWN=200`, `INVALID_PLANNER=201`, `TF_ERROR=202`, `START_OUTSIDE_MAP=203`, `GOAL_OUTSIDE_MAP=204`, `START_OCCUPIED=205`, `GOAL_OCCUPIED=206`, `TIMEOUT=207`, `NO_VALID_PATH=208`.
- `/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml` — confirma los nombres reales de parámetros de `waypoint_follower`: `loop_rate`, `stop_on_failure`, `action_server_result_timeout`, `waypoint_task_executor_plugin`, y la sección anidada del plugin seleccionado (`plugin`, `enabled`, `waypoint_pause_duration`).
- `/opt/ros/jazzy/share/nav2_waypoint_follower/plugins.xml` — confirma los tres plugins `WaypointTaskExecutor` disponibles vía `pluginlib`: `wait_at_waypoint` (`nav2_waypoint_follower::WaitAtWaypoint`), `photo_at_waypoint` (`nav2_waypoint_follower::PhotoAtWaypoint`), `input_at_waypoint` (`nav2_waypoint_follower::InputAtWaypoint`).

No se instaló ningún paquete. No se usó Internet ni navegador. No se asumieron parámetros de otras versiones de Nav2.

## Parámetros efectivos

```yaml
waypoint_follower:
  ros__parameters:
    use_sim_time: false
    loop_rate: 20
    stop_on_failure: true
    action_server_result_timeout: 900.0
    waypoint_task_executor_plugin: "wait_at_waypoint"
    wait_at_waypoint:
      plugin: "nav2_waypoint_follower::WaitAtWaypoint"
      enabled: true
      waypoint_pause_duration: 0
```

`stop_on_failure` queda explícito en `true`: un único waypoint inalcanzable debe abortar la ruta restante, no saltarlo y continuar. `waypoint_task_executor_plugin` usa el plugin estándar más simple disponible (`wait_at_waypoint`), sin efectos laterales: con `waypoint_pause_duration=0`, el propio nodo registra en su log `"Waypoint pause duration is set to zero, disabling task executor plugin."`, confirmando que ninguna tarea real (foto, interacción, audio) se ejecuta en cada waypoint. No se configuró ningún plugin personalizado.

## Namespace y lifecycle

`waypoint_follower` namespaced bajo `/offline_nav`, gestionado por `lifecycle_manager_waypoint_follower`, aislado del resto de lifecycle managers (`navigation`, `controller`, `collision_monitor`, `behavior_server`, `bt_navigator`). No remapea `cmd_vel`/`cmd_vel_raw`/`cmd_vel_safe`: nunca publica velocidad directamente. Confirmado en vivo (verificación de grafo ROS real, no solo escaneo de archivos): `ros2 lifecycle get /offline_nav/waypoint_follower` devuelve `active [3]`.

## Cadena FollowWaypoints y ausencia de bypass

Confirmado por introspección ROS (`ros2 topic info -v`) durante el smoke test y por verificación de grafo en vivo:

- `controller_server` es publisher confirmado de `/offline_nav/cmd_vel_raw`.
- `collision_monitor` es publisher confirmado de `/offline_nav/cmd_vel_safe`.
- `waypoint_follower` nunca aparece como publisher de `cmd_vel_raw` ni `cmd_vel_safe` (`direct_velocity_publisher: false` en todos los escenarios).
- Sin tópicos prohibidos (`/cmd_vel`, `/cmd_vel_nav`, `/offline_nav/cmd_vel`) en ningún momento, confirmado tanto por el escaneo estático de archivos como por `ros2 topic list` con el stack real corriendo.
- `/offline_nav/follow_waypoints` presente y servido exclusivamente por `waypoint_follower`; ningún otro nodo de misión (Simple Commander, `BasicNavigator`) presente en el grafo.

## Semántica de feedback y orden de waypoints

El feedback de `FollowWaypoints` expone únicamente `current_waypoint` (sin lista adicional de índices). Para acreditar que los waypoints se procesaron en orden, sin huecos ni retrocesos, se normaliza la secuencia cruda de feedback colapsando solo duplicados consecutivos:

```python
def _normalize_progress(raw_feedback_indices):
    normalized = []
    for index in raw_feedback_indices:
        if not normalized or normalized[-1] != index:
            normalized.append(index)
    return normalized
```

Ejemplo real observado en el escenario de éxito: cruda `[0, 0, 0, ..., 1, 1, ..., 2, 2]` (decenas de mensajes repetidos por waypoint) normaliza a `[0, 1, 2]`. El gate exige la igualdad exacta contra la secuencia esperada (`list(range(waypoints_requested))`), no solo que la secuencia esté ordenada: `[0]`, `[0, 2]`, `[1, 2]` o `[0, 1]` para una ruta de 3 waypoints se rechazan explícitamente, ya que una secuencia simplemente monotónica (`feedback_indices == sorted(feedback_indices)`) no demuestra cobertura completa.

`waypoints_reached` se deriva de evidencia real (`waypoints_requested - len(missed_waypoints)` cuando hay fallos, o igual a `waypoints_requested` cuando `missed_waypoints == []`), nunca asumido ni rellenado con `0` ante ausencia de medición.

## Escenario A — FollowWaypoints exitoso

Ruta de 3 waypoints sintéticos calculados por offsets fijos desde la pose inicial real observada (nunca asumida en `(0,0)`): `(+0.30, 0.0)`, `(+0.30, +0.20)`, `(0.0, +0.20)`, recortados a los límites del mapa sintético versionado.

Gates exigidos y observados (ambas corridas finales, dominios `200` y `210`):

| Métrica | Resultado |
|---|---|
| `waypoint_follower_active` | `true` |
| `follow_waypoints_action_available` | `true` |
| `goal_accepted` | `true` |
| `feedback_received` | `true` |
| `normalized_feedback_indices` | `[0, 1, 2]` (cobertura exacta, sin huecos ni retrocesos) |
| `waypoints_requested` / `waypoints_reached` | `3` / `3` |
| `missed_waypoints` | `[]` |
| `final_action_status` | `SUCCEEDED` |
| `raw_nonzero_observed` / `safe_nonzero_observed` | `true` / `true` |
| `odom_motion_observed` | `true` |
| `final_pose_within_tolerance` | `true` (`< 0.15 m` del último waypoint) |
| `safe_zero_after_terminal_state` / `odom_zero_after_terminal_state` | `true` / `true` |
| `pose_stable` | `true` |
| `forbidden_velocity_topics_detected` | `[]` |
| `direct_velocity_publisher` | `false` |
| `hardware_node_detected` / `mission_app_component_detected` | `false` / `false` |
| `orphan_processes` | `0` |

## Escenario B — Cancel FollowWaypoints

Ruta de 3 waypoints más larga (`(+0.30, 0.0)`, `(+0.40, 0.0)`, `(+0.30, 0.0)`), cancelada solo tras observar simultáneamente `raw` no cero, `safe` no cero, desplazamiento de pose `> 0.02 m`, **y** progreso del feedback más allá del primer waypoint (`current_waypoint >= 1`) — precondición más estricta que solo desplazamiento mínimo, para garantizar que la cancelación ocurre durante un tramo real de la ruta, no inmediatamente tras aceptar la meta.

`cancel_request_accepted` reutiliza el contrato real endurecido en Fase 2F.1: `response.return_code == CancelGoal.Response.ERROR_NONE` y el UUID del goal presente en `response.goals_canceling`, no solo la finalización del future.

Gates exigidos y observados (ambas corridas finales, dominios `201` y `211`):

| Métrica | Resultado |
|---|---|
| `waypoint_follower_active` | `true` |
| `follow_waypoints_action_available` | `true` |
| `goal_accepted` | `true` |
| `cancel_precondition_motion_observed` | `true` |
| `raw_nonzero_observed` / `safe_nonzero_observed` | `true` / `true` |
| `cancel_response_received` | `true` |
| `cancel_request_accepted` | `true` |
| `final_action_status` | `CANCELED` |
| `safe_message_after_cancel` / `odom_message_after_cancel` | `true` / `true` |
| `safe_zero_after_terminal_state` / `odom_zero_after_terminal_state` | `true` / `true` |
| `pose_stable` | `true` |
| `forbidden_velocity_topics_detected` | `[]` |
| `hardware_node_detected` / `mission_app_component_detected` | `false` / `false` |
| `orphan_processes` | `0` |

## Escenario C — FollowWaypoints con waypoint inalcanzable

### Hipótesis original descartada con evidencia real

La implementación provisional (antes de la reanudación) usaba como punto inalcanzable una celda interior ocupada del mapa fixture, derivada de inspección directa del `.pgm` (`offline_sandbox_test_map.pgm`, pixel fila `3`, columna `20`, mundo `(0.025, 0.575)`). Una corrida ROS diagnóstica real (dominio `222`, no una de las corridas finales) mostró que la acción terminaba `SUCCEEDED` con `missed_waypoints: []` y `normalized_feedback_indices: [0, 1, 2]` — es decir, esa celda **sí está ocupada** (confirmado por los datos del `.pgm`), pero a la resolución de este mapa (`0.05 m`) un solo píxel ocupado es más fino que el footprint+inflation efectivos del planner/costmap, que la rodea exitosamente. La hipótesis de ocupación era correcta; la hipótesis de inalcanzabilidad a partir de esa sola ocupación no lo era.

### Punto sustituido y confirmado

Se sustituyó por un punto fuera de los límites reales del mapa: `UNREACHABLE_WAYPOINT_XY = (5.0, 5.0)`, siendo el mapa fixture `x ∈ [-1.0, 1.0]`, `y ∈ [-0.75, 0.75]` (40×30 px, resolución `0.05 m`, origen `[-1.0, -0.75]`, confirmado por lectura directa del `.pgm`/`.yaml`, no asumido). Una corrida ROS diagnóstica real (dominio `221`) confirmó la semántica exacta: `final_action_status: ABORTED`, `missed_waypoints: [1]`, `MissedWaypoint.error_code: 204` (`nav2_msgs/action/ComputePathToPose::GOAL_OUTSIDE_MAP`, confirmado contra el contrato local), `normalized_feedback_indices: [0, 1]` (nunca progresa al waypoint índice `2`).

### Diseño del escenario

Ruta de 3 waypoints: índice `0` reachable (offset `+0.20` en x desde la pose inicial), índice `1` = `UNREACHABLE_WAYPOINT_XY`, índice `2` reachable (offset `+0.20`/`-0.20`). El waypoint reachable posterior al fallido existe exclusivamente para demostrar que `stop_on_failure=true` impide que la ruta continúe después del punto de fallo.

Gates exigidos y observados (ambas corridas finales, dominios `202` y `212`):

| Métrica | Resultado |
|---|---|
| `waypoint_follower_active` | `true` |
| `follow_waypoints_action_available` | `true` |
| `goal_accepted` | `true` |
| `final_action_status` | `ABORTED` (nunca `RESULT_TIMEOUT`, que jamás se reinterpreta como evidencia de fallo) |
| `unreachable_waypoint_index` | `1` |
| `missed_waypoints` | `[1]` |
| `missed_waypoint_error_code` | `204` (`GOAL_OUTSIDE_MAP`) |
| `normalized_feedback_indices` | `[0, 1]` — nunca alcanza el índice `2` |
| `stop_on_failure_proven` | `true` |
| `safe_zero_after_terminal_state` / `odom_zero_after_terminal_state` | `true` / `true` |
| `pose_stable` | `true` |
| `forbidden_velocity_topics_detected` | `[]` |
| `hardware_node_detected` / `mission_app_component_detected` | `false` / `false` |
| `orphan_processes` | `0` |

No se aceptó ningún `ABORTED` genérico ni timeout como evidencia: el gate exige específicamente el índice de waypoint fallido esperado (`1`) y el código de error exacto confirmado localmente (`204`).

## Defectos encontrados y correcciones aplicadas durante la reanudación

1. **Riesgo de deadlock por `stdout=subprocess.PIPE` sin consumidor.** Cada escenario iniciaba el wrapper de runtime con `stdout=subprocess.PIPE`/`stderr=subprocess.STDOUT` sin leer continuamente ese pipe (mismo patrón preexistente, no corregido aquí, en los demás smoke tests del sandbox). Bajo suficiente volumen de log de `ros2 launch`, el buffer del pipe puede llenarse y bloquear el proceso lanzado, produciendo timeouts artificiales o cierres incompletos. Se corrigió exclusivamente en `smoke_test_offline_waypoint_follower.py`: cada escenario abre un archivo de log dedicado bajo `/tmp` (`/tmp/ottoguide_waypoint_<escenario>_<domain>.log`) y pasa ese archivo como `stdout`, cerrándolo siempre en el bloque `finally`.
2. **`waypoints_reached` declarado pero nunca completado ni exigido.** La implementación provisional declaraba el campo en el JSON pero no lo calculaba ni lo incluía en el gate final. Se corrigió derivándolo de `missed_waypoints` real y exigiendo `waypoints_reached == waypoints_requested` en el escenario de éxito.
3. **Gate de orden insuficiente (`sorted()` no prueba cobertura).** `feedback_indices == sorted(feedback_indices)` acepta secuencias como `[0]`, `[0, 2]` o `[0, 1]` para una ruta de 3 waypoints, ninguna de las cuales demuestra que los tres waypoints fueron procesados. Se corrigió con `_normalize_progress` + `_progress_covers_expected_indices`, exigiendo igualdad exacta contra `[0, 1, ..., N-1]`.
4. **Hipótesis de waypoint inalcanzable no verificada empíricamente.** Ver sección "Escenario C" arriba: se descubrió mediante una corrida ROS diagnóstica real (no asumido) que la celda ocupada original era reachable en la práctica, y se sustituyó por un punto fuera de los límites del mapa, también confirmado empíricamente.
5. **`follow_waypoints_action_available` no exigido en los tres escenarios.** La implementación provisional medía el campo pero no lo incluía en el gate final de los tres escenarios; se corrigió agregándolo explícitamente a las tres condiciones `ok`.
6. **Regresión real en `smoke_test_offline_behavior_server.py` y `smoke_test_offline_bt_navigator.py` (archivos pre-Fase-2G, fuera del allowlist original).** Ambos archivos definían `FORBIDDEN_MISSION_NODE_SUBSTRINGS = ("waypoint_follower", "simple_commander")`, escrito en fases anteriores cuando ese componente no existía en el sandbox. Tras integrar `waypoint_follower` legítimamente, ambas regresiones fallaban detectando el nodo aprobado como una violación de aislamiento (`mission_node_detected: true`). Verificado mediante búsqueda de solo lectura en todos los `smoke_test_offline_*.py` que estos eran los únicos dos archivos con el patrón. Con autorización explícita puntual, se eliminó `"waypoint_follower"` de ambas listas, conservando `"simple_commander"`; la aceptación específica del nodo aprobado sigue siendo responsabilidad exclusiva de `check_waypoint_follower_contract` en `verify_sandbox_isolation.py`, no de estas regresiones.
7. **Procesos huérfanos detectados durante la sesión de reanudación.** Dos procesos `lifecycle_manager` (uno de un primer intento abandonado de la corrida final 1, afectado por la carrera de timing del hallazgo 8; otro de la regresión Foundation) quedaron vivos tras `SIGINT`/`SIGTERM` sin responder. Verificados individualmente (PID, PPID, PGID, comando completo, ejecutable, tiempo de vida, ausencia de hardware/procesos ajenos) antes de terminarlos con `kill -9` sobre los PIDs exactos, con autorización explícita puntual para cada caso. No se usó `pkill`, `killall` ni patrones.
8. **Carrera de timing transitoria en la activación de `lifecycle_manager_waypoint_follower`.** Un primer intento de la corrida final 1 falló con `WAYPOINT_FOLLOWER_ACTIVE_NOT_CONFIRMED`. El log mostró `[WARN] [...waypoint_follower.rclcpp]: failed to send response to /offline_nav/waypoint_follower/change_state (timeout)`: la respuesta del servicio de la transición Configure se perdió/expiró bajo carga WSL, dejando a `lifecycle_manager_waypoint_follower` esperando indefinidamente sin emitir la transición Activate. Los otros dos escenarios de la misma corrida activaron el mismo nodo normalmente segundos después, confirmando que no es un defecto de diseño. Se investigó (no se etiquetó como transitorio sin evidencia), y se reprodujo `PASS` repitiendo la corrida completa sin ningún cambio de código.

## Domain IDs

Política `1 <= domain_id <= 232` (FastDDS local no admite domain IDs superiores a `232`). Para IDs derivados de una base: `1 <= base` y `base + maximum_offset <= 232`.

| Componente | `maximum_offset` |
|---|---|
| Behavior Server | `2` |
| Collision Monitor | `4` |
| BT Navigator | `1` |
| Waypoint Follower | `2` |

Domain IDs efectivos usados en la secuencia final: foundation `141`, planner `142`, controller `143`, collision `151`, behavior `160`, BT Navigator `180`, Waypoint Follower run 1 `200`–`202`, Waypoint Follower run 2 `210`–`212`. Diagnósticos descartados (no contados como evidencia final): `220`, `222` (hipótesis de celda ocupada interior, descartada), `221` (confirmación del punto fuera de límites), `190`, `191`, `192` (verificación de grafo en vivo).

## Repetibilidad

Waypoint Follower run 1 (`base=200`) y run 2 (`base=210`) ejecutados sin ningún cambio de código ni de configuración entre ambas corridas: ambas en `PASS` completo, los tres escenarios (éxito, cancelación, inalcanzable), sin tópicos prohibidos, sin nodos de hardware/Simple Commander, sin procesos huérfanos.

## Verificación de grafo ROS en vivo (distinta del escaneo estático de archivos)

Además del escaneo estático (`verify_sandbox_isolation.py` y `--runtime`, que solo inspeccionan archivos), se verificó el grafo ROS real con el stack corriendo (dominio `192`, sesión separada de las corridas finales):

```text
ros2 node list                                    -> /offline_nav/waypoint_follower presente
ros2 lifecycle get /offline_nav/waypoint_follower -> active [3]
ros2 action list | grep follow_waypoints          -> /offline_nav/follow_waypoints presente
ros2 topic list | grep cmd_vel                    -> /offline_nav/cmd_vel_raw, /offline_nav/cmd_vel_safe (sin /cmd_vel ni /cmd_vel_nav)
ros2 node list | grep -iE "unitree|livox|realsense|simple_commander" -> ninguno encontrado
```

`RUNTIME_FILE_SCAN` (escaneo estático) y `RUNTIME_LIVE_GRAPH_VERIFICATION` (grafo real) son evidencia distinta y ambas en `PASS`; no se presentan como la misma prueba.

## Regresiones ROS ejecutadas secuencialmente

| Smoke test | Domain ID(s) | Resultado |
|---|---|---|
| Foundation | `141` | `PASS` (un primer intento falló con `orphan_processes: 1` por contención de un proceso `lifecycle_manager_bt_navigator` residual de esta misma sesión, no del código; tras el cleanup descrito en el hallazgo 7, se reprodujo `PASS` sin cambios de código) |
| Planner | `142` | `PASS` |
| Controller | `143` | `PASS` |
| Collision Monitor | `151`–`155` | `PASS` (5 escenarios: Clear, Slowdown, Stop, Recovery, Cancel) |
| Behavior Server | `160`–`162` | `PASS` tras el hallazgo 6 (falló inicialmente con `mission_node_detected: true`, no relacionado con timing) |
| BT Navigator | `180`–`181` | `PASS` tras el hallazgo 6 (mismo defecto, mismo archivo de fase previa) |
| Waypoint Follower run 1 | `200`–`202` | `PASS` (tras un primer intento fallido por el hallazgo 8, reproducido en `PASS`) |
| Waypoint Follower run 2 | `210`–`212` | `PASS`, sin cambios de código respecto a run 1 |

## Tests puros

Baseline previo a la Fase 2G: `189` (Windows, `38` `skipped` por ausencia de `rclpy`). Final tras la reanudación completa: `235` (Windows, `48` `skipped`) / `259` (WSL con ROS 2 Jazzy sourceado, `0` `skipped`). Ningún test existente fue eliminado ni debilitado; dos tests pre-Fase-2G que afirmaban la ausencia absoluta de `waypoint_follower` (`test_no_waypoint_follower_in_launch`, `test_no_waypoint_follower_simple_commander_or_collision_detector_executables`) se actualizaron para reflejar la excepción namespaced autorizada, renombrándolos para describir correctamente lo que ahora verifican (ausencia de Simple Commander), sin perder cobertura.

## Verificadores

- `verify_sandbox_isolation.py` (modo estático): `PASS`.
- `verify_sandbox_isolation.py --runtime` (escaneo de archivos en modo runtime): `PASS`.
- Nuevo `check_waypoint_follower_contract`: valida namespace, package/executable correctos (`nav2_waypoint_follower`/`waypoint_follower`), lifecycle manager dedicado y aislado (`node_names == ["waypoint_follower"]`), ausencia de remaps de velocidad, ausencia de nodos duplicados.
- `FORBIDDEN_MISSION_COMPONENT_PATTERN` se redujo a `nav2_simple_commander|simple_commander|BasicNavigator` (antes incluía también `waypoint_follower`/`nav2_waypoint_follower`); se agregó `FORBIDDEN_WAYPOINT_FOLLOWER_DUPLICATE_PATTERN` para rechazar referencias a `followWaypoints`/`nav2_bridge` (la aplicación paralela) en el launch.

## Diferencia entre el servidor del sandbox y el cliente de la aplicación

`waypoint_follower` (este reporte) es un **servidor de acción real** (`nav2_waypoint_follower`) integrado y validado dentro del sandbox offline aislado, exponiendo `/offline_nav/follow_waypoints`. `BasicNavigator.followWaypoints()`, presente en `codigo ottoguide/src/navigation/nav2_bridge.py` de la aplicación paralela, es un **cliente** de `nav2_simple_commander` que asume un bringup completo de Nav2 externo y nunca fue ejercitado contra ningún servidor real en ningún test de este repositorio (solo contra mocks). Esta fase no integra, modifica ni valida esa aplicación paralela; ambas arquitecturas permanecen no conectadas entre sí. La decisión de reconciliarlas (o no) es explícitamente responsabilidad de una fase posterior (2H.0).

## Limitaciones sintéticas

- El mapa, la odometría, los frames TF y los límites cinemáticos del simulador son sintéticos, deterministas y no representan al robot físico ni a la UADE.
- `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`: ningún resultado de esta fase valida seguridad física.
- No se conectó el robot físico, no se usó SSH/SCP, no se contactaron IPs `192.168.123.*`, no se abrieron rosbags, no se instaló ningún paquete.
- No se cambió el readiness físico (`L2_ODOMETRY`, `L3_LOCALIZATION_MAP`, `PHYSICAL_NAVIGATION` permanecen `NOT_READY`).
- El plugin `wait_at_waypoint` con `waypoint_pause_duration=0` no ejecuta ninguna tarea real en cada waypoint (confirmado por el propio log del nodo); esta fase no valida ningún comportamiento de espera, foto o interacción en waypoints.

## Readiness resultante

```text
GLOBAL_PLANNING_SANDBOX = READY
LOCAL_CONTROL_SANDBOX = READY
COLLISION_SAFETY_SANDBOX = READY
BEHAVIOR_SERVER_SANDBOX = READY
BT_NAVIGATOR_SANDBOX = READY
NAVIGATE_TO_POSE_SANDBOX = READY
WAYPOINT_FOLLOWER_SANDBOX = READY
FOLLOW_WAYPOINTS_SANDBOX = READY
ROS_RUNTIME_SANDBOX = PARTIAL (Simple Commander/orquestador de misión pendiente)
L2_ODOMETRY = NOT_READY
L3_LOCALIZATION_MAP = NOT_READY
PHYSICAL_NAVIGATION = NOT_READY
PHYSICAL_READINESS_CHANGED = NO
```

## Próximo incremento

Reconciliación de arquitecturas de navegación entre el sandbox offline (este, y el `bt_navigator`/`waypoint_follower` ya validados) y la aplicación paralela (`TourOrchestrator`/`AsyncNav2Bridge`/`BasicNavigator.followWaypoints()`), incluyendo la resolución del choque de nombres en `cmd_vel_nav` y el puente actualmente inexistente entre la salida de velocidad de Nav2 y `RobotHardwareInterface.move()`. No se implementó en esta fase.
