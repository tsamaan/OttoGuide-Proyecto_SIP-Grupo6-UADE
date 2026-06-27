# Offline Navigation Sandbox — BT Navigator Report

**Fase**: Fase 2F — BT Navigator aislado (`NavigateToPose` únicamente) integrado en el sandbox offline, sumado a `planner_server` + `controller_server` + `collision_monitor` + `behavior_server` de fases previas.

`OFFLINE_ONLY` / `SYNTHETIC` / `NOT_FOR_HARDWARE` / `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`.

## Objetivo

Integrar `nav2_bt_navigator` exclusivamente dentro del sandbox offline, habilitar la acción `/offline_nav/navigate_to_pose`, y validar la cadena completa:

```
NavigateToPose -> BT Navigator -> ComputePathToPose -> Planner Server -> FollowPath -> Controller Server -> cmd_vel_raw -> Collision Monitor -> cmd_vel_safe -> Offline Runtime Simulator
```

## Alcance

- BT Navigator, navigator `NavigateToPose` únicamente.
- Árbol de comportamiento mínimo: `ComputePathToPose -> FollowPath`, sin recoveries.
- Smoke test ROS real con dos escenarios (éxito y cancelación), reproducible en dos corridas independientes.
- Correcciones menores explícitamente autorizadas: comentarios obsoletos del launch/YAML, formulación del readiness, detección planar del escenario Wait, validación de rango de domain IDs en los tres smoke tests multi-escenario.

## Fuera de alcance

`NavigateThroughPoses`, Waypoint Follower, Simple Commander, misiones multipunto, `BackUp`/`DriveOnHeading`/`AssistedTeleop`, recoveries complejos, interfaces gráficas, navegación física.

## Preflight local (ROS 2 Jazzy, WSL Ubuntu-24.04)

```
ros2 pkg prefix nav2_bt_navigator        -> /opt/ros/jazzy
ros2 pkg executables nav2_bt_navigator   -> nav2_bt_navigator bt_navigator
```

Archivos locales instalados usados como referencia (sin Internet, sin copiar XML web):

- `/opt/ros/jazzy/share/nav2_bt_navigator/navigator_plugins.xml` — confirma `nav2_bt_navigator::NavigateToPoseNavigator` y `nav2_bt_navigator::NavigateThroughPosesNavigator` como los dos navigators disponibles vía `pluginlib`.
- `/opt/ros/jazzy/share/nav2_bt_navigator/behavior_trees/navigate_to_pose_w_replanning_and_recovery.xml` — árbol default de stock Nav2 (`BTCPP_format="4"`), usado únicamente para confirmar formato XML, no copiado: contiene `RecoveryNode`, `PipelineSequence`, `RateController`, `Spin`, `Wait`, `BackUp`, todos fuera de alcance de esta fase.
- `/opt/ros/jazzy/share/nav2_behavior_tree/nav2_tree_nodes.xml` — puertos reales de `ComputePathToPose` (`goal`, `start`, `use_start`, `planner_id`, `server_name`, `server_timeout` / `path`, `error_code_id`) y `FollowPath` (`controller_id`, `path`, `goal_checker_id`, `progress_checker_id`, `server_name`, `server_timeout` / `error_code_id`).
- `/opt/ros/jazzy/lib/libnav2_compute_path_to_pose_action_bt_node.so` y `/opt/ros/jazzy/lib/libnav2_follow_path_action_bt_node.so` — confirman que ambos nodos BT son plugins built-in del executor de `bt_navigator` (no requieren `plugin_lib_names` adicional).
- `/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml` — confirma los nombres reales de parámetros de `bt_navigator` (`global_frame`, `robot_base_frame`, `odom_topic`, `bt_loop_duration`, `default_server_timeout`, `wait_for_service_timeout`, `action_server_result_timeout`, `navigators`, `<navigator>.plugin`, `default_nav_to_pose_bt_xml`, `error_code_names`).
- `ros2 interface show nav2_msgs/action/NavigateToPose` — confirma el contrato de la acción (`geometry_msgs/PoseStamped pose`, `string behavior_tree` en el goal; `uint16 error_code` en el result; `current_pose`, `navigation_time`, `estimated_time_remaining`, `number_of_recoveries`, `distance_remaining` en el feedback).

No se instaló ningún paquete. No se usó Internet ni navegador. No se copió XML de documentación web.

## Árbol de comportamiento

Archivo versionado: `codigo ottoguide/config/navigation/bt/offline_navigate_to_pose.xml`.

```xml
<root BTCPP_format="4" main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <Sequence name="NavigateToPoseOfflineSandbox">
      <ComputePathToPose goal="{goal}" path="{path}" planner_id="GridBased" error_code_id="{compute_path_error_code}"/>
      <FollowPath path="{path}" controller_id="FollowPath" error_code_id="{follow_path_error_code}"/>
    </Sequence>
  </BehaviorTree>
</root>
```

Marcadores `OFFLINE_ONLY`/`SYNTHETIC`/`NOT_FOR_HARDWARE`/`NOT_UADE_MAP`/`NOT_FOR_PHYSICAL_SAFETY_VALIDATION` en comentario inicial. Parseable (`xml.etree.ElementTree`), sin rutas temporales ni dependencia de `artifacts/`, sin rutas absolutas específicas del equipo. No contiene `BackUp`, `DriveOnHeading`, `AssistedTeleop`, `ClearEntireCostmap`, `RecoveryNode`, `RoundRobin`, Waypoint Follower ni `NavigateThroughPoses` — verificado tanto por el verificador estático (`check_bt_navigator_contract`) como por tests puros.

## Parámetros efectivos

```yaml
bt_navigator:
  ros__parameters:
    use_sim_time: false
    global_frame: "map"
    robot_base_frame: "base_link"
    odom_topic: "odom"
    bt_loop_duration: 10
    default_server_timeout: 20
    wait_for_service_timeout: 1000
    action_server_result_timeout: 900.0
    navigators: ["navigate_to_pose"]
    navigate_to_pose:
      plugin: "nav2_bt_navigator::NavigateToPoseNavigator"
    default_nav_to_pose_bt_xml: <ruta versionada, inyectada en el launch>
    error_code_names:
      - compute_path_error_code
      - follow_path_error_code
```

`navigators` contiene únicamente `navigate_to_pose`; `navigate_through_poses` no está declarado, por lo que `NavigateThroughPosesNavigator` nunca se carga ni publica acción.

### Resolución de ruta del XML

El YAML versionado nunca contiene la ruta real del XML (el valor `default_nav_to_pose_bt_xml` ahí es un placeholder textual, `"OVERRIDDEN_AT_LAUNCH_TIME_BY_PARAM_REWRITES"`, nunca leído por `bt_navigator`). El launch declara:

```python
BT_XML_FILE = str(CODE_ROOT / "config" / "navigation" / "bt" / "offline_navigate_to_pose.xml")

bt_navigator_params = ParameterFile(
    RewrittenYaml(
        source_file=PARAMS_FILE,
        root_key=namespace,
        param_rewrites={'default_nav_to_pose_bt_xml': BT_XML_FILE},
        convert_types=True,
    ),
    allow_substs=True,
)
```

`CODE_ROOT` se deriva de `Path(__file__).resolve().parents[1]`, por lo que la ruta es absoluta y correcta independientemente del directorio de trabajo actual. `param_rewrites` reescribe específicamente esa clave sin afectar el resto de la sección `bt_navigator`, que sigue usando el mismo mecanismo `root_key=namespace` que todos los demás nodos namespaced del sandbox.

## Plugins y navigator efectivos

- Navigator: `nav2_bt_navigator::NavigateToPoseNavigator` (único habilitado).
- Nodos BT del árbol: `ComputePathToPose` (plugin `libnav2_compute_path_to_pose_action_bt_node.so`), `FollowPath` (plugin `libnav2_follow_path_action_bt_node.so`). Ambos built-in, sin `plugin_lib_names` adicional.
- Acción disponible: `/offline_nav/navigate_to_pose` (`nav2_msgs/action/NavigateToPose`).
- `NavigateThroughPoses` no configurado, no disponible como acción.

## Namespace y lifecycle

`bt_navigator` namespaced bajo `/offline_nav`, gestionado por `lifecycle_manager_bt_navigator`, aislado del resto de lifecycle managers (`navigation`, `controller`, `collision_monitor`, `behavior_server`). No remapea `cmd_vel`/`cmd_vel_raw`/`cmd_vel_safe`: nunca publica velocidad directamente.

## Cadena NavigateToPose y ausencia de bypass

Confirmado por introspección ROS (`ros2 topic info -v`) durante el smoke test:

- `controller_server` es publisher confirmado de `/offline_nav/cmd_vel_raw`.
- `collision_monitor` es publisher confirmado de `/offline_nav/cmd_vel_safe`.
- `bt_navigator` nunca aparece como publisher de `cmd_vel_raw` ni `cmd_vel_safe` (`bt_navigator_direct_velocity_publisher: false` en ambas corridas).
- Sin tópicos prohibidos (`/cmd_vel`, `/cmd_vel_nav`, `/offline_nav/cmd_vel`) en ningún momento.

## Escenario A — NavigateToPose exitoso

Objetivo calculado dinámicamente a partir de la pose inicial real observada (nunca asumida en `(0,0)`): `0.50 m` por delante de la pose inicial, en la orientación inicial, recortado a los límites del mapa sintético.

Gates exigidos y observados (ambas corridas, dominios `180` y `190`):

| Métrica | Resultado |
|---|---|
| `goal_accepted` | `true` |
| `navigate_result` | `SUCCEEDED` |
| `odom_messages_received` | `34`–`35` (run 1), `25` (run 2) |
| `raw_messages_received` | `49`–`50` |
| `safe_messages_received` | `24` |
| `raw_nonzero_observed` / `safe_nonzero_observed` | `true` / `true` |
| `distance_moved` | `0.4284 m` (`> 0.05 m` exigido) |
| `final_distance_to_goal` | `0.0716 m` (`< 0.12 m` exigido) |
| `final_twist_zero` | `true` |
| `pose_stable` | `true` |
| `forbidden_velocity_topics_detected` | `[]` |
| `bt_navigator_direct_velocity_publisher` | `false` |
| `hardware_node_detected` / `mission_node_detected` | `false` / `false` |
| `orphan_processes` | `0` |

## Escenario B — Cancel NavigateToPose

Objetivo calculado a `1.5 m` por delante de la pose inicial (suficientemente lejano para no completar antes de cancelar). La cancelación solo se envía tras observar simultáneamente `raw` no cero, `safe` no cero, y movimiento real de pose `> 0.02 m` (precondición; nunca se cancela como sustituto de esta espera).

Defecto encontrado y corregido durante la validación: la primera implementación medía el twist final inmediatamente al recibir el primer mensaje posterior a la cancelación, antes de que `controller_server`/el watchdog del simulador (`0.5s`) realmente asentaran la velocidad en cero, produciendo `safe_zero_after_cancel: false` / `odom_zero_after_cancel: false` de forma espuria (no por bypass real: `cancel_result` ya era `CANCELED` correctamente). Se corrigió esperando el settle completo (`2.0s`) antes de medir, igual que el ajuste ya documentado para el escenario Spin de Behavior Server (`0.5s` -> `1.0s`).

Gates exigidos y observados tras la corrección (ambas corridas, dominios `181` y `191`):

| Métrica | Resultado |
|---|---|
| `goal_accepted` | `true` |
| `cancel_precondition_motion_observed` | `true` |
| `cancel_request_accepted` | `true` |
| `cancel_result` | `CANCELED` |
| `safe_message_after_cancel` / `odom_message_after_cancel` | `true` / `true` |
| `safe_zero_after_cancel` / `odom_zero_after_cancel` | `true` / `true` |
| `pose_stable` | `true` |
| `forbidden_velocity_topics_detected` | `[]` |
| `hardware_node_detected` / `mission_node_detected` | `false` / `false` |
| `orphan_processes` | `0` |

No se aceptó `SUCCEEDED`, `ABORTED`, timeout ni ausencia de mensajes como evidencia de cancelación o parada.

## Domain IDs

Política `1 <= domain_id <= 232` (FastDDS local no admite domain IDs superiores a `232`). Para IDs derivados de una base: `1 <= base` y `base + maximum_offset <= 232`.

| Componente | `maximum_offset` |
|---|---|
| Behavior Server | `2` |
| Collision Monitor | `4` |
| BT Navigator | `1` |

Pruebas negativas ejecutadas antes de iniciar cualquier nodo ROS:

| Comando | Resultado |
|---|---|
| `smoke_test_offline_behavior_server.py --base-domain-id 231` | `exit=2`, `DERIVED_DOMAIN_ID_OUT_OF_RANGE`, sin procesos iniciados |
| `smoke_test_offline_collision_monitor.py --base-domain-id 229` | `exit=2`, `DERIVED_DOMAIN_ID_OUT_OF_RANGE`, sin procesos iniciados |
| `smoke_test_offline_bt_navigator.py --base-domain-id 232` | `exit=2`, `DERIVED_DOMAIN_ID_OUT_OF_RANGE`, sin procesos iniciados |
| `smoke_test_offline_bt_navigator.py --base-domain-id 0` | `exit=2`, `INVALID_DOMAIN_ID`, sin procesos iniciados |
| `smoke_test_offline_bt_navigator.py --base-domain-id 233` | `exit=2`, `INVALID_DOMAIN_ID`, sin procesos iniciados |

Domain IDs efectivos usados en la secuencia final: foundation `141`, planner `142`, controller `143`, collision `151`–`155`, behavior `160`–`162`, BT run 1 `180`–`181`, BT run 2 `190`–`191`. (`150` se evitó tras una colisión con un proceso WSL residual transitorio de una corrida previa; se reasignó a `151`–`155`).

## Repetibilidad

BT run 1 (`base=180`) y BT run 2 (`base=190`) ejecutados sin ningún cambio de código entre ambas corridas: ambas en `PASS` completo, success y cancel, sin tópicos prohibidos, sin nodos de hardware/misión, sin procesos huérfanos.

## Regresiones ROS ejecutadas secuencialmente

| Smoke test | Domain ID(s) | Resultado |
|---|---|---|
| Foundation | `141` | `PASS` |
| Planner | `142` | `PASS` |
| Controller | `143` | `PASS` (un timeout transitorio de `ros2 lifecycle get` bajo carga acumulada, clasificado como `transient_timeout`; reproducido en PASS con `--timeout` mayor, sin cambios de código) |
| Collision Monitor | `151`–`155` | `PASS` |
| Behavior Server | `160`–`162` | `PASS` |
| BT Navigator run 1 | `180`–`181` | `PASS` |
| BT Navigator run 2 | `190`–`191` | `PASS` |

## Tests puros

Baseline previo: `144`. Final: `195` (`PASS`, `0` failures, `0` errors), ejecutado tanto en el entorno Windows (con `rclpy` no disponible: 9 tests que cargan módulos `rclpy` se saltan automáticamente) como en WSL con ROS 2 Jazzy sourceado (los 195 corren, incluidos esos 9).

## Verificadores

- `verify_sandbox_isolation.py` (modo estático): `PASS`.
- `verify_sandbox_isolation.py --runtime`: `PASS`.
- Nuevo `check_bt_navigator_contract`: valida namespace, lifecycle manager dedicado y aislado, ausencia de remaps de velocidad, existencia/parseabilidad del XML, marcadores sintéticos, presencia de `ComputePathToPose`/`FollowPath`, ausencia de nodos fuera de alcance.

## Defectos encontrados y correcciones aplicadas

1. **Wait — gate `safe_messages_received > 0` incorrecto.** La implementación de referencia local (`/opt/ros/jazzy/include/nav2_behaviors/timed_behavior.hpp`) muestra que `stopRobot()` (que publica el único `cmd_vel` explícito de un behavior) solo se invoca en las rutas de preempt/cancel, nunca en la finalización normal `SUCCEEDED`. Por lo tanto, un `Wait` exitoso produce legítimamente cero mensajes `cmd_vel_raw`/`cmd_vel_safe`. El gate `safe_messages_received > 0` agregado inicialmente para este escenario era una sobre-restricción incorrecta y se removió; la ausencia de movimiento se sigue verificando con evidencia real (`odom_twist_zero`, que depende del timer periódico del simulador, siempre activo) y no con la mera ausencia de mensajes `safe`.
2. **Cancel NavigateToPose — medición de twist prematura.** La primera implementación medía `cmd_vel_safe`/twist de odometría en el primer mensaje recibido tras la cancelación, antes de que el watchdog del simulador (`0.5s`) asentara la velocidad en cero, produciendo falsos negativos (`safe_zero_after_cancel`/`odom_zero_after_cancel` en `false` pese a `cancel_result == CANCELED` correcto). Se corrigió esperando el settle completo (`2.0s`) antes de medir.

Ambas correcciones fueron validadas repitiendo primero el gate afectado y luego la secuencia completa (tests puros, BT run 1, BT run 2) antes de proceder.

## Limitaciones sintéticas

- El mapa, la odometría, los frames TF y los límites cinemáticos del simulador son sintéticos, deterministas y no representan al robot físico ni a la UADE.
- `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`: ningún resultado de esta fase valida seguridad física.
- No se conectó el robot físico, no se usó SSH/SCP, no se contactaron IPs `192.168.123.*`, no se abrieron rosbags, no se instaló ningún paquete.
- No se cambió el readiness físico (`L2_ODOMETRY`, `L3_LOCALIZATION_MAP`, `PHYSICAL_NAVIGATION` permanecen `NOT_READY`).

## Readiness resultante

```
GLOBAL_PLANNING_SANDBOX = READY
LOCAL_CONTROL_SANDBOX = READY
COLLISION_SAFETY_SANDBOX = READY
BEHAVIOR_SERVER_SANDBOX = READY
BT_NAVIGATOR_SANDBOX = READY
NAVIGATE_TO_POSE_SANDBOX = READY
ROS_RUNTIME_SANDBOX = PARTIAL (Waypoint Follower y Simple Commander pendientes)
```

## Próximo incremento

Waypoint Follower aislado (`nav2_waypoint_follower`) o diseño de misión con `nav2_simple_commander`, ambos bajo el mismo aislamiento (`ROS_LOCALHOST_ONLY=1`, `ROS_DOMAIN_ID` dedicado). No se implementó en esta fase.

---

## Fase 2F.1 — Hardening posterior a auditoría

**Commit auditado**: `8b5e242c12a2fa490f085f2b3e7fd421550be874` (`feat(nav): add isolated bt navigator`).

Esta fase no agrega ninguna capacidad nueva. Cierra tres hallazgos detectados durante la auditoría de ese commit, todos en el harness de validación offline (no en el robot físico ni en la lógica de navegación real).

### Hallazgo 1 — `--base-domain-id` no entero producía traceback

**Causa raíz**: los tres smoke tests multi-escenario (`smoke_test_offline_bt_navigator.py`, `smoke_test_offline_behavior_server.py`, `smoke_test_offline_collision_monitor.py`) convertían el argumento con `base = int(args.base_domain_id)` sin capturar `ValueError`. Una entrada como `"abc"`, `"12.5"`, `""` o `"   "` escapaba como traceback no controlado en vez de un resultado estructurado.

**Corrección**: se agregó `parse_base_domain_id(raw_value)` en los tres scripts, que envuelve la conversión en `try/except (TypeError, ValueError)` y devuelve `(int, None)` en éxito o `(None, "INVALID_DOMAIN_ID")` en fallo, sin lanzar nunca una excepción. `main()` invoca primero `parse_base_domain_id`, y solo si no hay error de parseo pasa a `validate_domain_id_range`. La validación completa ocurre antes de `subprocess.Popen`, `rclpy.init`, el wrapper de runtime o cualquier comando `ros2`.

**Contrato JSON para domain IDs inválidos**:

```json
{
  "ok": false,
  "decision": "FAIL",
  "errors": [
    "INVALID_DOMAIN_ID"
  ]
}
```

**Pruebas negativas ejecutadas** (los tres scripts, vía CLI real bajo WSL/ROS 2 Jazzy, no solo el helper en aislamiento):

| Entrada | Resultado (los tres scripts) |
|---|---|
| `"abc"` | `exit=2`, `INVALID_DOMAIN_ID`, sin traceback, sin proceso ROS iniciado |
| `"12.5"` | `exit=2`, `INVALID_DOMAIN_ID`, sin traceback, sin proceso ROS iniciado |
| `""` | `exit=2`, `INVALID_DOMAIN_ID`, sin traceback, sin proceso ROS iniciado |
| `"   "` | `exit=2`, `INVALID_DOMAIN_ID`, sin traceback, sin proceso ROS iniciado |
| `"0"` | `exit=2`, `INVALID_DOMAIN_ID`, sin traceback, sin proceso ROS iniciado |
| `"233"` | `exit=2`, `INVALID_DOMAIN_ID`, sin traceback, sin proceso ROS iniciado |

Y los casos derivados fuera de rango (preexistentes, re-verificados tras el cambio):

| Script | Base | Resultado |
|---|---|---|
| Behavior Server | `231` (offset `2`) | `exit=2`, `DERIVED_DOMAIN_ID_OUT_OF_RANGE` |
| Collision Monitor | `229` (offset `4`) | `exit=2`, `DERIVED_DOMAIN_ID_OUT_OF_RANGE` |
| BT Navigator | `232` (offset `1`) | `exit=2`, `DERIVED_DOMAIN_ID_OUT_OF_RANGE` |

Las 18 combinaciones (6 entradas inválidas × 3 scripts) y las 3 combinaciones de rango derivado se verificaron con `stdout`/`stderr` completos: ningún caso produjo `Traceback`, todos los `stdout` son JSON parseable, y `pgrep` confirmó cero procesos ROS iniciados en cualquier caso.

### Hallazgo 2 — `cancel_request_accepted` no acreditaba aceptación real

**Causa raíz**: en `smoke_test_offline_bt_navigator.py`, la lógica original era:

```python
cancel_future = goal_handle.cancel_goal_async()
cancel_accepted = client.spin_until_future_complete_custom(cancel_future, timeout_s=15.0)
result["cancel_request_accepted"] = bool(cancel_accepted)
```

Esto solo confirma que el future terminó (`future.done()`), no que el servidor de acciones haya aceptado realmente cancelar la meta. Un future puede completarse con cualquier respuesta, incluido un rechazo explícito.

**Contrato real inspeccionado localmente** (`ros2 interface show action_msgs/srv/CancelGoal` contra la instalación de ROS 2 Jazzy en `/opt/ros/jazzy`):

```text
int8 ERROR_NONE=0          # request accepted, goals_canceling no vacío
int8 ERROR_REJECTED=1
int8 ERROR_UNKNOWN_GOAL_ID=2
int8 ERROR_GOAL_TERMINATED=3
int8 return_code
GoalInfo[] goals_canceling  # metas que aceptaron la cancelacion (cada una con goal_id)
```

Se confirmó además, inspeccionando `rclpy.action.client.ActionClient._cancel_goal_async` y `ClientGoalHandle` localmente instalados, que `cancel_goal_async()` devuelve un `Future[CancelGoal.Response]`, y que `goal_handle.goal_id` expone el UUID del goal originalmente aceptado (`ClientGoalHandle.goal_id`).

**Corrección**: se agregó `_BtNavigatorSmokeClient.request_cancel_and_check_acceptance(goal_handle, timeout_s)`, que:

1. envía la cancelación y espera el future (con timeout);
2. si el future no termina o `future.result()` es `None`, marca `cancel_response_received=False` y agrega `CANCEL_RESPONSE_TIMEOUT`;
3. si `response.return_code != CancelGoal.Response.ERROR_NONE`, marca `cancel_response_received=True`, `cancel_request_accepted=False` y agrega `CANCEL_REQUEST_NOT_ACCEPTED`;
4. si el `goal_id` (UUID) del `goal_handle` original no aparece en `response.goals_canceling`, igual agrega `CANCEL_REQUEST_NOT_ACCEPTED`;
5. solo si `return_code == ERROR_NONE` **y** el UUID coincide, marca `cancel_request_accepted=True`.

El resultado del escenario ahora separa explícitamente `cancel_response_received`, `cancel_request_accepted` y `cancel_result` (este último sigue siendo el estado final de la acción, `CANCELED`/`SUCCEEDED`/etc., verificado independientemente). El gate final exige las tres condiciones simultáneamente, además de las preexistentes (precondición de movimiento real, telemetría no-cero, asentamiento a cero, pose estable).

**Consistencia revisada en los otros dos smoke tests**: `smoke_test_offline_behavior_server.py` (`cancel_and_wait`) y `smoke_test_offline_collision_monitor.py` (escenario `cancel`) nunca declaran un campo de "aceptación" derivado solo de la finalización del future; ambos esperan únicamente el resultado final de la acción (`CANCELED`/`STATUS_<n>`) sin afirmar haber comprobado una aceptación intermedia que en realidad no verificaron. No se modificó ninguno de los dos: no presentan el antipatrón.

**Patrón eliminado**: la línea `result["cancel_request_accepted"] = bool(cancel_accepted)` ya no existe en el repositorio; se reemplazó por la inspección real de `response.return_code` y `goal_handle.goal_id.uuid` contra `response.goals_canceling`.

### Hallazgo 3 — Comentario obsoleto en el launch

**Causa raíz**: el comentario de `planner_server_node` en `offline_nav_sandbox.launch.py` todavía decía *"Sin controller_server, sin local_costmap, sin behaviors, sin waypoint follower, sin Collision Monitor"*, una afirmación falsa desde la Fase 2C/2D/2E (todos esos componentes ya estaban activos).

**Corrección**: el comentario ahora enumera correctamente los componentes presentes (`controller_server`, `local_costmap`, `collision_monitor`, `behavior_server`, `bt_navigator`) y los genuinamente ausentes (Waypoint Follower, Simple Commander). Se revisó el resto del archivo (`grep` de "Sin "/"sin BT"/"sin behaviors"/"sin Collision"/"sin waypoint"/"sin local_costmap"/"sin controller") y no se encontraron otras afirmaciones contradictorias: las menciones restantes de "sin Waypoint Follower, sin Simple Commander" (en el bloque de `bt_navigator_node` y en el comentario final de la `LaunchDescription`) siguen siendo ciertas y no se modificaron.

### Tests agregados

Se agregaron, sin eliminar ningún test existente:

- `BaseDomainIdParsingTests`: prueba funcional de `parse_base_domain_id` (no solo búsqueda de texto) en los tres scripts, con entradas no enteras, válidas, y una verificación estructural de que `main()` usa el parser seguro antes de `validate_domain_id_range`.
- `BaseDomainIdCliContractTests`: invoca la CLI real vía `subprocess` (no solo el helper) con las seis entradas inválidas en los tres scripts, verificando `exit=2`, JSON parseable, ausencia de `Traceback`, y `INVALID_DOMAIN_ID` en `errors`.
- `CancelAcceptanceSemanticsTests`: ejercita `request_cancel_and_check_acceptance` con dobles de prueba ligeros (`Future`/`goal_handle` falsos, sin `rclpy.init()`) cubriendo: future no completado, respuesta nula, respuesta con rechazo explícito, respuesta con `goals_canceling` vacío, respuesta que confirma una meta distinta, respuesta que confirma la meta esperada (sola y entre varias), y verificación estática de que el antipatrón fue eliminado del código fuente.

Tests puros: baseline `195` -> final `209` (Windows, 38 `skipped` por ausencia de `rclpy`) / `209` (WSL con ROS 2 Jazzy sourceado, sin skips). Ningún test fue eliminado ni debilitado.

### Regresiones ROS ejecutadas

| Smoke test | Domain ID(s) | Resultado |
|---|---|---|
| Foundation | `141` | `PASS` (un primer intento con `--timeout 30`/`45` falló con `map_message_received: false`; se confirmó manualmente vía introspección ROS que `map_server` publicaba correctamente con QoS `TRANSIENT_LOCAL` y que el fallo era una condición de carrera de tiempo de asentamiento bajo carga acumulada de WSL, no un defecto de código; se reprodujo `PASS` con `--timeout 90`, sin cambios de código) |
| Planner | `142` | `PASS` (mismo patrón de timing transitorio, reproducido en `PASS` con `--timeout 90`) |
| Controller | `143` | `PASS` (`--timeout 90`, sin reintentos) |
| Collision Monitor | `151`-`155` | `PASS` |
| Behavior Server | `160`-`162` | `PASS` |
| BT Navigator run 1 | `180`-`181` | `PASS` |
| BT Navigator run 2 | `190`-`191` | `PASS`, sin cambios de código respecto a run 1 |

Ambas corridas de BT Navigator confirmaron explícitamente `cancel_response_received: true` y `cancel_request_accepted: true`, verificados contra la respuesta real de `CancelGoal`, además de todos los gates preexistentes (`SUCCEEDED`/`CANCELED`, telemetría real, asentamiento a cero, pose estable, cero procesos huérfanos).

### Verificadores

- `verify_sandbox_isolation.py` (estático): `PASS`.
- `verify_sandbox_isolation.py --runtime`: `PASS`.

### Commit final

```text
fix(nav): harden offline smoke contracts
```

Parent: `8b5e242c12a2fa490f085f2b3e7fd421550be874`.

### Readiness físico

Sin cambios. `L2_ODOMETRY`, `L3_LOCALIZATION_MAP` y `PHYSICAL_NAVIGATION` permanecen `NOT_READY`. `ROS_RUNTIME_SANDBOX` permanece `PARTIAL`. Esta fase es exclusivamente correctiva sobre el harness de validación offline; no valida seguridad física ni agrega capacidades de navegación.
