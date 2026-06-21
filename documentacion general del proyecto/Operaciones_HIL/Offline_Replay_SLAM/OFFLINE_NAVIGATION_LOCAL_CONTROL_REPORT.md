# Offline Navigation Sandbox — Local Control Report

**Fecha**: 2026-06-20
**Fase**: 2C — control local closed-loop exclusivamente simulado (`controller_server` + local costmap + simulador con integración cinemática). No incluye BT Navigator, behavior server, waypoint follower, Simple Commander ni Collision Monitor.

## Resultado general

`RESULT=PARTIAL_OFFLINE_LOCAL_CONTROL`. La implementación quedó completa (parámetros, launch, simulador extendido, verificador, tests puros, smoke test de control con escenario de éxito y de cancelación), pero **una incompatibilidad real de este entorno ROS 2 Jazzy local impide que `controller_server` complete su transición de lifecycle `configure`**, por lo que el escenario de éxito y el de cancelación no pudieron validarse en runtime. No se intentó ni se aplicó ningún workaround que requiriera instalar o actualizar paquetes.

## Hallazgo de incompatibilidad local (causa raíz)

Se comprobó, de forma aislada y reproducible, que este ROS 2 Jazzy local **no aplica parámetros anidados bajo el namespace de un plugin** cuando se cargan vía `--params-file` (ni tampoco vía `-p` en línea de comandos):

- `planner_server` con `GridBased.tolerance: 0.20` en el YAML: `ros2 param get /offline_nav/planner_server GridBased.tolerance` devuelve `0.5` (el default de stock Nav2), no `0.20`. Esto no rompe nada porque el plugin que cae por default (`nav2_navfn_planner::NavfnPlanner`) coincide con el solicitado, así que la Fase 2B funcionó "por casualidad" sin que se detectara este problema entonces.
- `controller_server` con `FollowPath.plugin: nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController`: el parámetro `FollowPath.plugin` real, consultado con `ros2 param get`, sigue siendo `dwb_core::DWBLocalPlanner` (el default de stock Nav2). El plugin solicitado nunca se carga.
- Probado tanto a través de `ros2 launch` (el launch real del sandbox) como con `ros2 run nav2_controller controller_server --ros-args --params-file ...` en aislamiento total, con y sin namespace, con un YAML mínimo reducido a un solo nodo: el comportamiento es idéntico en todos los casos.

## Cambio de plugin del controller por compatibilidad local

Siguiendo la decisión explícita del usuario, se cambió la configuración de `FollowPath` para usar **`dwb_core::DWBLocalPlanner` con critics mínimos** en lugar de `RegulatedPurePursuitController`, ya que DWB es el plugin que este entorno realmente carga de todas formas:

- **Plugin solicitado originalmente**: `nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController`.
- **Plugin efectivo en este ROS 2 Jazzy local**: `dwb_core::DWBLocalPlanner`.
- **Motivo**: incompatibilidad comprobada del entorno local con parámetros anidados bajo el namespace de un plugin (ver sección anterior).
- **Esta elección es exclusiva de este sandbox offline** y no define ni recomienda ningún controlador para el robot físico.

## Resultado de la validación con DWB + critics mínimos

Se agregó `FollowPath.critics: ["RotateToGoal", "Oscillation", "BaseObstacle", "GoalAlign", "PathAlign", "PathDist", "GoalDist"]` y `default_critic_namespaces: ["dwb_critics"]` al YAML. Se confirmó mediante `ros2 param get /offline_nav/controller_server FollowPath.critics` que el parámetro **"is not initialized"**: la misma incompatibilidad de carga de parámetros anidados afecta también a `critics`, no solo a `plugin`. `controller_server` sigue cayendo al estado por default sin critics, lo cual provoca `Couldn't load critics! Caught exception: No critics defined for FollowPath` y la transición `configure` falla con `FATAL`.

Conforme al criterio fail-safe acordado: **los critics tampoco se aplican → DWB vuelve a defaults no verificables → se detiene la implementación** sin instalar ni modificar paquetes.

## Aislamiento de lifecycle (corrección de regresión)

La primera integración agregó `controller_server` al mismo `lifecycle_manager_navigation` que ya gestionaba `map_server` y `planner_server`. Esto causó una regresión real: como `controller_server` falla al `configure`, el `lifecycle_manager` abortaba el bringup completo antes de activar `map_server`/`planner_server`, rompiendo los smoke tests de Fase 2A/2B que ya pasaban. Se corrigió separando el lifecycle en dos managers independientes:

- `lifecycle_manager_navigation`: gestiona únicamente `map_server` y `planner_server` (como en la Fase 2B).
- `lifecycle_manager_controller`: gestiona únicamente `controller_server`, de forma aislada.

Con este aislamiento, `map_server` y `planner_server` vuelven a activarse correctamente sin importar el estado de `controller_server`. Se confirmó en runtime: el smoke test de foundation y el de planificación global volvieron a `PASS` tras la separación, y el smoke test de control confirma `map_server_lifecycle_active: true` y `planner_server_lifecycle_active: true` incluso mientras `controller_server_lifecycle_active: false`.

## Lo que SÍ se completó y se puede verificar estáticamente

- `controller_server` agregado al launch bajo namespace real `offline_nav`, con `remappings=[('cmd_vel', 'cmd_vel_raw')]`.
- `lifecycle_manager_controller` dedicado y aislado, intentando activar únicamente `controller_server`.
- `local_costmap` configurado con `global_frame: odom`, `robot_base_frame: base_link`, `obstacle_layer` suscrito al tópico relativo `scan`, e `inflation_layer`.
- `offline_runtime_simulator.py` extendido: suscripción relativa `cmd_vel_raw`, integración cinemática planar determinista (x, y, yaw), límites sintéticos (`max_linear_speed_mps=0.10`, `max_angular_speed_radps=0.30`), watchdog de 0.5s que pone velocidad cero sin comando nuevo, todo sin imports de hardware, sin red, sin topics globales.
- Verificador de aislamiento actualizado: política de allowlist que permite únicamente `cmd_vel_raw` (resuelve a `/offline_nav/cmd_vel_raw`) y rechaza `/cmd_vel`, `/cmd_vel_nav`, `/offline_nav/cmd_vel` y cualquier otra variante que contenga `cmd_vel`. Distingue identificadores Python (`cmd_vel_watchdog_timeout_s`) de literales de tópico real.
- 28 tests puros nuevos (93 totales), todos en `OK`, ejecutables sin ROS.
- `smoke_test_offline_controller.py` implementado con ambos escenarios (éxito y cancelación) y verificación de lifecycle real, pero no pudo completar ninguno de los dos por el bloqueo de `controller_server` descripto arriba.

## Lo que NO se pudo validar en runtime

- `CONTROLLER_LIFECYCLE_ACTIVE`: NO. `controller_server` nunca alcanza `active`; queda en `FATAL` tras fallar `configure`. Confirmado de forma reproducible en dos ejecuciones del smoke test de control con domain IDs distintos (`107`, `108`), ambas con `map_server_lifecycle_active: true`, `planner_server_lifecycle_active: true`, `controller_server_lifecycle_active: false`, y `orphan_processes: 0`.
- Resultado `SUCCEEDED` de `/offline_nav/follow_path`: no alcanzado (el action server de `controller_server` nunca llega a estar disponible).
- Movimiento simulado observable y llegada al objetivo: no alcanzado.
- Cancelación y parada simulada: no alcanzado (no hay goal activo que cancelar).

## Restricciones respetadas

No se conectó el robot físico, no se usó SSH/SCP, no se contactaron IPs `192.168.123.*`, no se usó Internet, no se instalaron paquetes, no se abrieron bags, no se implementó BT Navigator, behavior server, waypoint follower, Simple Commander ni Collision Monitor, no se crearon interfaces de usuario, no se modificó GT-MIN.

## Estado de readiness resultante

`LOCAL_CONTROL_SANDBOX` no se declara `READY`. `ROS_RUNTIME_SANDBOX` permanece `PARTIAL`. `L2_ODOMETRY`, `L3_LOCALIZATION_MAP` y `PHYSICAL_NAVIGATION` permanecen `NOT_READY` sin cambios. No se declara autonomía validada en ningún nivel.

## Próximo paso recomendado

Antes de reintentar esta fase, se necesita una de estas dos cosas fuera del alcance actual: (a) autorización explícita para instalar o reinstalar el paquete `nav2_controller`/`dwb_core` en este entorno WSL para descartar un bug de empaquetado local, o (b) una sesión separada de investigación que determine si el problema es específico de la versión `jazzy` empaquetada en este sistema o reproducible en cualquier instalación estándar de ROS 2 Jazzy (lo cual indicaría un bug upstream a reportar, no una particularidad de esta máquina).
