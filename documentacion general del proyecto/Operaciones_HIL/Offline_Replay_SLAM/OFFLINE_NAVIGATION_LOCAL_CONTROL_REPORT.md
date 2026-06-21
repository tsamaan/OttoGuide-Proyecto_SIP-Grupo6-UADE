# Offline Navigation Sandbox — Local Control Report

**Fecha**: 2026-06-20
**Fase**: 2C + corrección acotada de parámetros namespaced — control local closed-loop exclusivamente simulado (`controller_server` + local costmap + simulador con integración cinemática). No incluye BT Navigator, behavior server, waypoint follower, Simple Commander ni Collision Monitor.

## Resultado general

`RESULT=PARTIAL_NAMESPACED_NAV2_PARAMETERS`. La causa raíz original (carga incorrecta de parámetros anidados de plugin) está **resuelta**: `controller_server` ahora alcanza `ACTIVE` de forma reproducible y la acción `/offline_nav/follow_path` devuelve `SUCCEEDED`. Sin embargo, apareció un **problema runtime distinto y nuevo**, no relacionado con la carga de parámetros: el escenario de movimiento simulado no detecta avance de pose (`simulated_distance_moved: 0.0`) y el escenario de cancelación no confirma velocidad cero dentro de la ventana esperada (`stop_after_cancel: FAIL`). No se investigó la causa raíz de este problema nuevo ni se aplicó ningún workaround, conforme al alcance acotado de la corrección. No se intentó ni se aplicó ningún workaround que requiriera instalar o actualizar paquetes.

## Hallazgo de incompatibilidad local (causa raíz original — RESUELTA)

Se comprobó, de forma aislada y reproducible, que este ROS 2 Jazzy local **no aplicaba parámetros anidados bajo el namespace de un plugin** cuando se cargaban vía `--params-file` (ni tampoco vía `-p` en línea de comandos), porque el launch entregaba `parameters=[PARAMS_FILE]` directamente a nodos namespaced, sin reescribir el archivo con el namespace real como raíz:

- `planner_server` con `GridBased.tolerance: 0.20` en el YAML: `ros2 param get /offline_nav/planner_server GridBased.tolerance` devolvía `0.5` (el default de stock Nav2), no `0.20`. Esto no rompía nada porque el plugin que caía por default (`nav2_navfn_planner::NavfnPlanner`) coincidía con el solicitado, así que la Fase 2B funcionó "por casualidad" sin que se detectara este problema entonces.
- `controller_server` con `FollowPath.plugin: dwb_core::DWBLocalPlanner` (ya configurado como fallback exclusivo del sandbox): el parámetro `FollowPath.plugin` real, consultado con `ros2 param get`, seguía cayendo al default de stock Nav2 sin aplicar el valor del YAML, y `FollowPath.critics` quedaba "not initialized", causando el fallo de `configure`.
- Probado tanto a través de `ros2 launch` (el launch real del sandbox) como con `ros2 run nav2_controller controller_server --ros-args --params-file ...` en aislamiento total, con y sin namespace, con un YAML mínimo reducido a un solo nodo: el comportamiento era idéntico en todos los casos.

### Causa raíz confirmada y corrección aplicada

La causa no era un bug de ROS 2 Jazzy ni de los paquetes Nav2 instalados: era que `offline_nav_sandbox.launch.py` pasaba el archivo de parámetros sin reescritura de namespace (`parameters=[PARAMS_FILE]`), mientras los nodos se lanzaban con `namespace=namespace` (`/offline_nav`). Sin una reescritura explícita, los nodos namespaced no resuelven correctamente las claves anidadas bajo el nombre del plugin declaradas en la raíz del YAML.

Se corrigió agregando, en `offline_nav_sandbox.launch.py`:

```python
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml

configured_params = ParameterFile(
    RewrittenYaml(
        source_file=PARAMS_FILE,
        root_key=namespace,
        param_rewrites={},
        convert_types=True,
    ),
    allow_substs=True,
)
```

aplicado a `map_server`, `planner_server` y `controller_server` (`parameters=[configured_params, ...]`), preservando el override adicional `yaml_filename` en `map_server`. Se corrigió además `GridBased.plugin` en el YAML de `"nav2_navfn_planner/NavfnPlanner"` (alias estilo ROS 1, no reconocido por pluginlib en este Jazzy) a `"nav2_navfn_planner::NavfnPlanner"` (namespace C++ real), error que quedó expuesto recién al empezar a aplicarse realmente el parámetro.

### Valores efectivos verificados tras la corrección (domain ID 110, reproducido en 111/115/116)

| Parámetro | Antes de la corrección | Después de la corrección | Esperado |
|---|---|---|---|
| `GridBased.tolerance` | `0.5` | `0.20` | `0.20` |
| `GridBased.plugin` | `nav2_navfn_planner::NavfnPlanner` (default, coincidencia casual) | `nav2_navfn_planner::NavfnPlanner` | `nav2_navfn_planner::NavfnPlanner` |
| `controller_frequency` | `20.0` | `10.0` | `10.0` |
| `FollowPath.plugin` | `dwb_core::DWBLocalPlanner` (default, no aplicado desde YAML) | `dwb_core::DWBLocalPlanner` (aplicado desde YAML) | `dwb_core::DWBLocalPlanner` |
| `FollowPath.critics` | no inicializado | `['RotateToGoal', 'Oscillation', 'BaseObstacle', 'GoalAlign', 'PathAlign', 'PathDist', 'GoalDist']` | lista no vacía |
| `FollowPath.max_vel_x` | `0.0` | `0.1` | `0.10` |

`map_server`, `planner_server` y `controller_server` alcanzan `active` de forma reproducible (confirmado con `ros2 lifecycle get` en dos ejecuciones independientes, domain IDs `115` y `116`).

## Cambio de plugin del controller por compatibilidad local

Siguiendo la decisión explícita del usuario, se cambió la configuración de `FollowPath` para usar **`dwb_core::DWBLocalPlanner` con critics mínimos** en lugar de `RegulatedPurePursuitController`, ya que DWB es el plugin que este entorno realmente carga de todas formas:

- **Plugin solicitado originalmente**: `nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController`.
- **Plugin efectivo en este ROS 2 Jazzy local**: `dwb_core::DWBLocalPlanner`.
- **Motivo**: incompatibilidad comprobada del entorno local con parámetros anidados bajo el namespace de un plugin (ver sección anterior).
- **Esta elección es exclusiva de este sandbox offline** y no define ni recomienda ningún controlador para el robot físico.

## Resultado de la validación con DWB + critics mínimos

Se agregó `FollowPath.critics: ["RotateToGoal", "Oscillation", "BaseObstacle", "GoalAlign", "PathAlign", "PathDist", "GoalDist"]` y `default_critic_namespaces: ["dwb_critics"]` al YAML. Inicialmente (antes de la corrección de namespaced parameters) se confirmó mediante `ros2 param get /offline_nav/controller_server FollowPath.critics` que el parámetro era **"is not initialized"**: la misma incompatibilidad de carga de parámetros anidados afectaba también a `critics`, no solo a `plugin`. `controller_server` caía al estado por default sin critics, lo cual provocaba `Couldn't load critics! Caught exception: No critics defined for FollowPath` y la transición `configure` fallaba con `FATAL`.

**Tras aplicar la corrección de namespaced parameters (`ParameterFile`/`RewrittenYaml`), `FollowPath.critics` se carga correctamente** con la lista completa de 7 critics, y `controller_server` completa `configure` y `activate` sin error.

## Aislamiento de lifecycle (corrección de regresión)

La primera integración agregó `controller_server` al mismo `lifecycle_manager_navigation` que ya gestionaba `map_server` y `planner_server`. Esto causó una regresión real: como `controller_server` falla al `configure`, el `lifecycle_manager` abortaba el bringup completo antes de activar `map_server`/`planner_server`, rompiendo los smoke tests de Fase 2A/2B que ya pasaban. Se corrigió separando el lifecycle en dos managers independientes:

- `lifecycle_manager_navigation`: gestiona únicamente `map_server` y `planner_server` (como en la Fase 2B).
- `lifecycle_manager_controller`: gestiona únicamente `controller_server`, de forma aislada.

Con este aislamiento, `map_server` y `planner_server` vuelven a activarse correctamente sin importar el estado de `controller_server`. Se confirmó en runtime: el smoke test de foundation y el de planificación global volvieron a `PASS` tras la separación, y el smoke test de control confirma `map_server_lifecycle_active: true` y `planner_server_lifecycle_active: true` incluso mientras `controller_server_lifecycle_active: false`.

## Lo que SÍ se completó y se puede verificar estáticamente

- `controller_server` agregado al launch bajo namespace real `offline_nav`, con `remappings=[('cmd_vel', 'cmd_vel_raw')]`.
- `lifecycle_manager_controller` dedicado y aislado, activando únicamente `controller_server`, independiente de `lifecycle_manager_navigation`.
- `local_costmap` configurado con `global_frame: odom`, `robot_base_frame: base_link`, `obstacle_layer` suscrito al tópico relativo `scan`, e `inflation_layer`.
- `offline_runtime_simulator.py`: suscripción relativa `cmd_vel_raw`, integración cinemática planar determinista (x, y, yaw), límites sintéticos (`max_linear_speed_mps=0.10`, `max_angular_speed_radps=0.30`), watchdog de 0.5s que pone velocidad cero sin comando nuevo, todo sin imports de hardware, sin red, sin topics globales.
- Verificador de aislamiento: política de allowlist que permite únicamente `cmd_vel_raw` (resuelve a `/offline_nav/cmd_vel_raw`) y rechaza `/cmd_vel`, `/cmd_vel_nav`, `/offline_nav/cmd_vel` y cualquier otra variante que contenga `cmd_vel`. Distingue identificadores Python (`cmd_vel_watchdog_timeout_s`) de literales de tópico real.
- `offline_nav_sandbox.launch.py` reescribe los parámetros con `ParameterFile(RewrittenYaml(source_file=PARAMS_FILE, root_key=namespace, convert_types=True), allow_substs=True)`, aplicado a `map_server`, `planner_server` y `controller_server`.
- 104 tests puros (97 previos + corrección + 10 tests nuevos acotados para la reescritura namespaced, con 3 fallos preexistentes no relacionados removidos del conteo por ser módulos faltantes ajenos a este sandbox: `httpx`, `pydantic_settings`), todos en `OK` dentro del módulo `test_offline_navigation_sandbox_isolation`, ejecutables sin ROS.
- `smoke_test_offline_controller.py`: el escenario de `FollowPath` ahora completa `SUCCEEDED` con `controller_server` en `ACTIVE` real.

## Lo que SÍ se validó en runtime (tras la corrección)

- `CONTROLLER_LIFECYCLE_ACTIVE`: **SÍ**. `controller_server` alcanza `active` de forma reproducible, confirmado en dos ejecuciones del smoke test de control con domain IDs distintos (`115`, `116`), ambas con `map_server_lifecycle_active: true`, `planner_server_lifecycle_active: true`, `controller_server_lifecycle_active: true`, y `orphan_processes: 0`.
- Resultado `SUCCEEDED` de `/offline_nav/follow_path`: **alcanzado**, en ambas ejecuciones.
- `FollowPath.plugin`, `FollowPath.critics`, `controller_frequency`, `GridBased.tolerance`, `GridBased.plugin`: todos verificados con el valor configurado en el YAML, no el default de stock Nav2.

## Lo que NO se pudo validar en runtime (problema nuevo, fuera del alcance de esta corrección)

- Movimiento simulado observable: **NO**. `simulated_distance_moved: 0.0` en ambas ejecuciones, pese a que `FollowPath` completa `SUCCEEDED`.
- Llegada confirmada al objetivo: **NO**. `final_distance_to_goal: null` (no calculable porque no hubo cambio de pose detectado).
- Cancelación con parada confirmada: **NO**. `cancel_test: GOAL_STATUS_4` y `stop_after_cancel: FAIL` / `nonzero_command_after_cancel: true` en ambas ejecuciones; no se confirma velocidad cero dentro de la ventana de 1.0s tras cancelar.
- No se investigó la causa raíz de este problema nuevo (posibles hipótesis no confirmadas: timing de `client.spin_for()` en el cliente de smoke test, comportamiento del simulador ante el primer ciclo de `cmd_vel_raw`, o configuración del `goal_checker`/`progress_checker`), conforme al alcance acotado de "corrección de parámetros namespaced" de esta tarea.

## Restricciones respetadas

No se conectó el robot físico, no se usó SSH/SCP, no se contactaron IPs `192.168.123.*`, no se usó Internet, no se instalaron paquetes, no se abrieron bags, no se implementó BT Navigator, behavior server, waypoint follower, Simple Commander ni Collision Monitor, no se crearon interfaces de usuario, no se modificó GT-MIN.

## Estado de readiness resultante

`LOCAL_CONTROL_SANDBOX` no se declara `READY` (el escenario de movimiento simulado y el de cancelación no están confirmados). `ROS_RUNTIME_SANDBOX` permanece `PARTIAL`. `GLOBAL_PLANNING_SANDBOX` permanece `READY`. `L2_ODOMETRY`, `L3_LOCALIZATION_MAP` y `PHYSICAL_NAVIGATION` permanecen `NOT_READY` sin cambios. No se declara autonomía validada en ningún nivel.

## Próximo paso recomendado

Investigar, en una sesión separada, por qué `FollowPath` completa `SUCCEEDED` sin que el simulador (`offline_runtime_simulator.py`) registre avance de pose, y por qué la cancelación no produce velocidad cero confirmada dentro de la ventana esperada. No se trata de un bug de empaquetado de ROS 2 Jazzy ni requiere reinstalar paquetes: es un comportamiento a diagnosticar en la lógica de integración cinemática del simulador y/o en el timing del cliente de smoke test (`smoke_test_offline_controller.py`).
