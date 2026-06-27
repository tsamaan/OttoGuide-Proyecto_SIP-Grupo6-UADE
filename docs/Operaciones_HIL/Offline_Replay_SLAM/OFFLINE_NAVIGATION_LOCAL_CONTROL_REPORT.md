# Offline Navigation Sandbox — Local Control Report

**Fecha**: 2026-06-21
**Fase**: Fase 2C + corrección acotada de parámetros namespaced — control local closed-loop exclusivamente simulado (`controller_server` + local costmap + simulador con integración cinemática). No incluye BT Navigator, behavior server, waypoint follower, Simple Commander ni Collision Monitor.

## Resultado general

`RESULT=PASS_OFFLINE_CONTROLLER_SMOKE_CORRECTED`. La causa raíz del fallo anterior fue identificada y corregida: el nodo cliente de smoke test se creaba sin namespace, lo que causaba que las suscripciones relativas resolvieran globalmente a `/odom` y `/cmd_vel_raw` en lugar de hacerlo en la ruta namespaced `/offline_nav/odom` y `/offline_nav/cmd_vel_raw`. 

Una vez corregidas las suscripciones para usar FQNs explícitos Namespaced (`/{namespace}/odom` y `/{namespace}/cmd_vel_raw`), la odometría y comandos se reciben correctamente. El escenario de éxito se completó con éxito confirmando que el simulador integra y avanza (con una distancia movida de 0.408 m y distancia final al objetivo de 0.092 m, cumpliendo holgadamente las tolerancias). El escenario de cancelación se ejecutó en runtimes independientes con dominios ROS separados y demostró la cancelación exitosa de la acción (`STATUS_CANCELED`) y la detención efectiva del robot mediante el watchdog del simulador (twist de odometría nulo y pose estable durante > 0.5s).

## Hallazgo de incompatibilidad local (causa raíz original — RESUELTA)

Se comprobó, de forma aislada y reproducible, que este ROS 2 Jazzy local **no aplicaba parámetros anidados bajo el namespace de un plugin** cuando se cargaban vía `--params-file` (ni tampoco vía `-p` en línea de comandos), porque el launch entregaba `parameters=[PARAMS_FILE]` directamente a nodos namespaced, sin reescribir el archivo con el namespace real como raíz:

- `planner_server` con `GridBased.tolerance: 0.20` en el YAML: `ros2 param get /offline_nav/planner_server GridBased.tolerance` devolvía `0.5` (el default de stock Nav2), no `0.20`. Esto no rompía nada porque el plugin que caía por default (`nav2_navfn_planner::NavfnPlanner`) coincidía con el solicitado, así que la Fase 2B funcionó "por casualidad" sin que se detectara este problema entonces.
- `controller_server` con `FollowPath.plugin: dwb_core::DWBLocalPlanner` (ya configurado como fallback exclusivo del sandbox): el parámetro `FollowPath.plugin` real, consultado con `ros2 param get`, seguía cayendo al default de stock Nav2 sin aplicar el valor del YAML, y `FollowPath.critics` quedaba "not initialized", causando el fallo de `configure`.

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

## Valores efectivos verificados tras la corrección (domain ID 110, reproducido en 111/115/116)

| Parámetro | Antes de la corrección | Después de la corrección | Esperado |
|---|---|---|---|
| `GridBased.tolerance` | `0.5` | `0.20` | `0.20` |
| `GridBased.plugin` | `nav2_navfn_planner::NavfnPlanner` (default, coincidencia casual) | `nav2_navfn_planner::NavfnPlanner` | `nav2_navfn_planner::NavfnPlanner` |
| `controller_frequency` | `20.0` | `10.0` | `10.0` |
| `FollowPath.plugin` | `dwb_core::DWBLocalPlanner` (default, no aplicado desde YAML) | `dwb_core::DWBLocalPlanner` (aplicado desde YAML) | `dwb_core::DWBLocalPlanner` |
| `FollowPath.critics` | no inicializado | `['RotateToGoal', 'Oscillation', 'BaseObstacle', 'GoalAlign', 'PathAlign', 'PathDist', 'GoalDist']` | lista no vacía |
| `FollowPath.max_vel_x` | `0.0` | `0.1` | `0.10` |

`map_server`, `planner_server` y `controller_server` alcanzan `active` de forma reproducible.

## Cambio de plugin del controller por compatibilidad local

Siguiendo la decisión explícita del usuario, se cambió la configuración de `FollowPath` para usar **`dwb_core::DWBLocalPlanner` con critics mínimos** en lugar de `RegulatedPurePursuitController`, ya que DWB es el plugin que este entorno realmente carga de todas formas.

## Aislamiento de lifecycle (corrección de regresión)

La primera integración agregó `controller_server` al mismo `lifecycle_manager_navigation` que ya gestionaba `map_server` y `planner_server`. Se corrigió separando el lifecycle en dos managers independientes:

- `lifecycle_manager_navigation`: gestiona únicamente `map_server` y `planner_server`.
- `lifecycle_manager_controller`: gestiona únicamente `controller_server`, de forma aislada.

## Lo que SÍ se completó y se puede verificar estáticamente

- `controller_server` agregado al launch bajo namespace real `offline_nav`, con `remappings=[('cmd_vel', 'cmd_vel_raw')]`.
- `lifecycle_manager_controller` dedicado y aislado, activando únicamente `controller_server`, independiente de `lifecycle_manager_navigation`.
- `local_costmap` configurado con `global_frame: odom`, `robot_base_frame: base_link`, `obstacle_layer` suscrito al tópico relativo `scan`, e `inflation_layer`.
- `offline_runtime_simulator.py`: suscripción relativa `cmd_vel_raw`, integración cinemática planar determinista (x, y, yaw), límites sintéticos (`max_linear_speed_mps=0.10`, `max_angular_speed_radps=0.30`), watchdog de 0.5s que pone velocidad cero sin comando nuevo.
- Verificador de aislamiento: política de allowlist que permite únicamente `cmd_vel_raw` (resuelve a `/offline_nav/cmd_vel_raw`) y rechaza `/cmd_vel`.
- `offline_nav_sandbox.launch.py` reescribe los parámetros con `ParameterFile(RewrittenYaml(source_file=PARAMS_FILE, root_key=namespace, convert_types=True), allow_substs=True)`, aplicado a `map_server`, `planner_server` y `controller_server`.
- 116 tests puros (104 previos + 12 tests nuevos acotados para suscripciones namespaced, telemetría y checks de cancelación), todos en `PASS` dentro del módulo `test_offline_navigation_sandbox_isolation`, ejecutables sin ROS.
- `smoke_test_offline_controller.py`: el escenario de `FollowPath` completa `SUCCEEDED` con `controller_server` en `ACTIVE` real.

## Lo que SÍ se validó en runtime (tras la corrección)

- `CONTROLLER_LIFECYCLE_ACTIVE`: **SÍ**. `controller_server` alcanza `active` de forma reproducible, confirmado en ejecuciones del smoke test de control, con `map_server_lifecycle_active: true`, `planner_server_lifecycle_active: true`, `controller_server_lifecycle_active: true`, y `orphan_processes: 0`.
- Resultado `SUCCEEDED` de `/offline_nav/follow_path`: **alcanzado**, en todas las ejecuciones de éxito.
- `FollowPath.plugin`, `FollowPath.critics`, `controller_frequency`, `GridBased.tolerance`, `GridBased.plugin`: todos verificados con el valor configurado en el YAML, no el default de stock Nav2.
- Movimiento simulado observable: **SÍ**. `simulated_distance_moved` de 0.408 m registrado tras el recorrido completo de la acción.
- Llegada confirmada al objetivo: **SÍ**. `final_distance_to_goal` de 0.092 m al finalizar, dentro del margen de la tolerancia de 0.12 m.
- Cancelación con parada confirmada: **SÍ**. `cancel_status: CANCELED` y `watchdog_effective_stop: true` validados. El twist de la odometría retorna a cero y la pose del simulador se estabiliza por completo (cambio de pose < 2mm durante al menos 0.5s) dentro de los 1.5s posteriores a la cancelación.

## Restricciones respetadas

No se conectó el robot físico, no se usa SSH/SCP, no se contactan IPs `192.168.123.*`, no se usó Internet, no se instalaron paquetes, no se abrieron bags, no se implementó BT Navigator, behavior server, waypoint follower ni Simple Commander (Collision Monitor se integró en la Fase 2D), no se crearon interfaces de usuario, no se modificó GT-MIN.

## Estado de readiness resultante

`LOCAL_CONTROL_SANDBOX` se promueve a **READY** (todos los escenarios de movimiento y cancelación pasan correctamente). `ROS_RUNTIME_SANDBOX` permanece `PARTIAL` (faltan behaviors, waypoint follower y Simple Commander; Collision Monitor está READY). `GLOBAL_PLANNING_SANDBOX` permanece `READY`. `L2_ODOMETRY`, `L3_LOCALIZATION_MAP` y `PHYSICAL_NAVIGATION` permanecen `NOT_READY` sin cambios. No se declara autonomía validada en ningún nivel.

## Próximo paso recomendado

Implementar y validar de forma aislada los componentes de misiones (Behavior Server y Waypoint Follower) bajo el mismo sandbox antes de realizar cualquier prueba física o integrar con hardware.
