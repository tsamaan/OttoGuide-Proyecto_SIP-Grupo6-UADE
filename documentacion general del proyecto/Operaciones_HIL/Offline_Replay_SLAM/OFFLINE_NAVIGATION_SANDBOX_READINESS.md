# Offline Navigation Sandbox — Readiness

**Fecha**: 2026-06-20
**Fase**: Fase 2B — base de runtime ROS aislada (map_server + lifecycle_manager + TF + odometría/scan sintéticos) más planificación global aislada (planner_server + global costmap). No incluye controller, behaviors, waypoint follower, Collision Monitor ni Simple Commander.

Este documento separa el estado de readiness del sandbox de navegación offline de OttoGuide en cuatro niveles independientes. Ningún nivel implica el siguiente.

## Niveles de readiness

| Nivel | Estado | Evidencia |
|---|---|---|
| `STATIC_BASELINE` | **READY** | Sandbox existente auditado (`offline_nav_sandbox.launch.py`, `nav2_offline_sandbox_params.yaml`); mapa sintético versionado creado y marcado `SYNTHETIC_TEST_MAP`/`NOT_UADE_MAP`/`NOT_METRICALLY_VALIDATED`/`NOT_FOR_PHYSICAL_NAVIGATION`; default del launch apunta al mapa versionado (no a `artifacts/`); verificador de aislamiento estático (`verify_sandbox_isolation.py`) implementado y en `PASS`; tests `unittest` puros sin ROS. |
| `LOCAL_ROS_CAPABILITIES` | **READY** | Matriz de paquetes ROS 2 locales verificada en WSL `Ubuntu-24.04` (ROS 2 `jazzy`) sin `apt`/`pip`/`rosdep`/Internet — ver [OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md](OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md). Todos los paquetes Nav2 base requeridos para fases posteriores están presentes, salvo `nav2_loopback_sim` (no instalado). |
| `ROS_RUNTIME_SANDBOX` | **PARTIAL** | Se levantó una base de runtime ROS real y aislada: `map_server` + `planner_server` + `lifecycle_manager` + `offline_runtime_simulator` (odometría y scan sintéticos) + TF estático (`map`→`odom`, `base_link`→`utlidar_lidar`) + TF dinámico (`odom`→`base_link`), todo bajo namespace real `offline_nav`, `ROS_LOCALHOST_ONLY=1` y `ROS_DOMAIN_ID` dedicado. Los smoke tests ROS (`smoke_test_offline_runtime.py`, `smoke_test_offline_planner.py`) pasaron, ambos iniciando el runtime mediante el wrapper aislado. Sigue `PARTIAL` porque no incluye `controller_server`, `behavior_server`, `waypoint_follower`, Collision Monitor ni Simple Commander — ver [OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md](OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md). |
| `GLOBAL_PLANNING_SANDBOX` | **READY** | `planner_server` con plugin `nav2_navfn_planner/NavfnPlanner` y `global_costmap` (static layer + inflation layer) activos bajo namespace real, sin `controller_server`. La acción `/offline_nav/compute_path_to_pose` devolvió `SUCCEEDED` con 59 poses en frame `map`, primera pose cerca del start `(-0.75, 0.0)` y última cerca del goal `(0.75, 0.0)`, en dos ejecuciones independientes (domain IDs 85 y 86), sin `/cmd_vel`/`/cmd_vel_nav`, sin nodos de hardware, y sin procesos huérfanos. Detalle completo en [OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md](OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md). No implica navegación autónoma: solo se calculan rutas candidatas, no se mueve nada. |
| `PHYSICAL_NAVIGATION` | **NOT_READY** | Sin cambios respecto al estado previo. Depende de L2 y L3 validados, de calibración TF física, de mapa navegable completo y de los criterios de la sección 7 del plan original. No se conectó el robot ni se usó hardware físico en esta fase. |

## Estado de capas del sistema (sin cambios en esta fase)

| Nivel | Estado | Fuente |
|---|---|---|
| L0 sensores | READY | [PROGRESO_ODOMETRIA_OFFLINE.md](PROGRESO_ODOMETRIA_OFFLINE.md) |
| L1 intención/movimiento | READY | [PROGRESO_ODOMETRIA_OFFLINE.md](PROGRESO_ODOMETRIA_OFFLINE.md) |
| L2 odometría | **NOT_READY** | No existe trayectoria offline confiable; sin cambios en esta fase |
| L3 localización/mapa | **NOT_READY** | Depende de L2 validado; sin cambios en esta fase |
| Navegación física | **NOT_READY** | Depende de L2, L3, calibración TF y criterios de la sección 7 del plan |

## Lo que esta fase NO declara

- No declara autonomía validada.
- No declara mapa físico validado (el mapa sintético es exclusivamente para tests offline, no representa la UADE).
- No declara odometría validada (la odometría publicada es sintética, pose fija, velocidad cero — no es evidencia de L2).
- No declara localización ni mapa validados (las TF `map`→`odom` y `base_link`→`utlidar_lidar` son identidades sintéticas, no extrínsecos medidos).
- No declara Nav2 listo para el robot.
- No declara navegación autónoma: `GLOBAL_PLANNING_SANDBOX = READY` significa exclusivamente que `planner_server` calcula rutas candidatas sobre un mapa sintético; no hay control, no hay movimiento, no hay `controller_server`.
- No declara `PHYSICAL_NAVIGATION` como `READY` o `PARTIAL`.
- No declara `ROS_RUNTIME_SANDBOX` como `READY` (permanece `PARTIAL`: faltan controller, behaviors, waypoint follower, Collision Monitor y Simple Commander).

## Qué cambió respecto a la fase previa

- Se documentó por primera vez, con evidencia verificada localmente, qué paquetes Nav2 existen en el entorno de desarrollo (Fase 1).
- Se reemplazó la dependencia del launch en un artefacto local no versionado (`artifacts/maps/ottoguide_hil_stationary_map.yaml`) por un mapa sintético versionado y explícitamente no apto para navegación física (Fase 1).
- Se agregó un verificador de aislamiento estático reproducible y tests puros asociados (Fase 1).
- Se levantó por primera vez runtime ROS real bajo aislamiento (`ROS_LOCALHOST_ONLY=1`, `ROS_DOMAIN_ID` dedicado), con namespace real `offline_nav` aplicado a los nodos, un simulador sintético de odometría/scan, y TF estático/dinámico completo (Fase 2A).
- Se agregó un verificador de aislamiento en modo `--runtime` (variables de entorno ausentes o incorrectas pasan de warning a error) y un smoke test ROS que confirmó mensajes en los tres tópicos esperados y cierre sin procesos huérfanos (Fase 2A).
- Se agregó `planner_server` (plugin `nav2_navfn_planner/NavfnPlanner`) y `global_costmap` (static + inflation layer) bajo el mismo namespace real y aislamiento, activados por el mismo `lifecycle_manager` que `map_server`, sin `controller_server` ni componentes de movimiento (Fase 2B).
- El verificador de aislamiento ahora valida namespace/remapping por entidad individual (cada `Node`/`ExecuteProcess` requerido, no solo un conteo `>0`) y distingue código que *detecta* `/cmd_vel`/`/cmd_vel_nav` como ausentes de código que los *usa* realmente (Fase 2B).
- El wrapper corrige la captura del exit code del launch para que se propague correctamente incluso si es distinto de cero (Fase 2B).
- El smoke test de foundation ahora inicia el runtime mediante el wrapper aislado (no `ros2 launch` directo) y verifica el cierre del process group propio mediante sondeo real, no solo `wait()` (Fase 2B).
- Se agregó un smoke test ROS real de planificación (`smoke_test_offline_planner.py`) que envía un goal `ComputePathToPose` y valida el path resultante; pasó en dos ejecuciones independientes con domain IDs distintos (Fase 2B).

## Próximo incremento

Habilitar `ROS_RUNTIME_SANDBOX = READY` requiere, como mínimo y con decisión explícita de aislamiento: `controller_server`/`behavior_server`/`waypoint_follower`/`collision_monitor`, además de scripting con `nav2_simple_commander`, todo sobre el mapa sintético versionado y bajo el mismo aislamiento (`ROS_LOCALHOST_ONLY=1`, `ROS_DOMAIN_ID` dedicado, sin `/cmd_vel` real hacia hardware). Esa fase de misiones/control no se ejecutó en este incremento y queda fuera de su alcance.
