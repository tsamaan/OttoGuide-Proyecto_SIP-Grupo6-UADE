# Offline Navigation Sandbox — Readiness

**Fecha**: 2026-06-21
**Fase**: Fase 2D.1: Endurecimiento de la evidencia de Collision Monitor — control local closed-loop y monitoreo de colisiones simulado (`controller_server` + `collision_monitor` + local costmap). La causa raíz original (parámetros namespaced) y los problemas runtime de telemetría y detención están **resueltos** y validados con éxito. Sí incluye Collision Monitor. No incluye BT Navigator, behavior server, waypoint follower, Simple Commander ni misiones.

Este documento separa el estado de readiness del sandbox de navegación offline de OttoGuide en cuatro niveles independientes. Ningún nivel implica el siguiente.

## Niveles de readiness

| Nivel | Estado | Evidencia |
|---|---|---|
| `STATIC_BASELINE` | **READY** | Sandbox existente auditado (`offline_nav_sandbox.launch.py`, `nav2_offline_sandbox_params.yaml`); mapa sintético versionado creado y marcado `SYNTHETIC_TEST_MAP`/`NOT_UADE_MAP`/`NOT_METRICALLY_VALIDATED`/`NOT_FOR_PHYSICAL_NAVIGATION`; default del launch apunta al mapa versionado (no a `artifacts/`); verificador de aislamiento estático (`verify_sandbox_isolation.py`) implementado y en `PASS`; tests `unittest` puros sin ROS. |
| `LOCAL_ROS_CAPABILITIES` | **READY** | Matriz de paquetes ROS 2 locales verificada en WSL `Ubuntu-24.04` (ROS 2 `jazzy`) sin `apt`/`pip`/`rosdep`/Internet — ver [OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md](OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md). Todos los paquetes Nav2 base requeridos para fases posteriores están presentes, salvo `nav2_loopback_sim` (no instalado). |
| `ROS_RUNTIME_SANDBOX` | **PARTIAL** | Se levantó una base de runtime ROS real y aislada: `map_server` + `planner_server` + `controller_server` + `collision_monitor` + lifecycle managers separados + `offline_runtime_simulator` (odometría y scan sintéticos) + TF estático y dinámico completo, todo bajo namespace real `offline_nav`, `ROS_LOCALHOST_ONLY=1` y `ROS_DOMAIN_ID` dedicado. Los smoke tests ROS pasaron. Sigue `PARTIAL` porque no incluye `behavior_server`, `waypoint_follower` ni `Simple Commander` (Collision Monitor está incluido y verificado) — ver [OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md](OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md). |
| `GLOBAL_PLANNING_SANDBOX` | **READY** | `planner_server` con plugin `nav2_navfn_planner::NavfnPlanner` y `global_costmap` (static layer + inflation layer) activos bajo namespace real. Global Planning fue validado originalmente sin Controller, pero el runtime integrado actual sí lo contiene. La acción `/offline_nav/compute_path_to_pose` devolvió `SUCCEEDED` con 59 poses en frame `map`, en dos ejecuciones independientes, sin `/cmd_vel`/`/cmd_vel_nav`, sin nodos de hardware, y sin procesos huérfanos. Detalle completo en [OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md](OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md). No implica navegación autónoma. |
| `LOCAL_CONTROL_SANDBOX` | **READY** | `controller_server` + `local_costmap` + simulador con integración cinemática y allowlist de velocidad (`cmd_vel_raw` y `cmd_vel_safe` permitidos) están implementados. Local Control ya utiliza la cadena `cmd_vel_raw` -> `collision_monitor` -> `cmd_vel_safe` -> `offline_runtime_simulator`, donde el simulador consume `cmd_vel_safe` y no `cmd_vel_raw`. La carga incorrecta de parámetros anidados de plugin y la observación incorrecta de topics de odometría/comandos están completamente resueltas. El escenario de éxito confirma avance de pose simulada y llegada al objetivo. El escenario de cancelación confirma parada cinemática exitosa (`STATUS_CANCELED`), detención efectiva por watchdog y estabilidad de pose. Detalle completo en [OFFLINE_NAVIGATION_LOCAL_CONTROL_REPORT.md](OFFLINE_NAVIGATION_LOCAL_CONTROL_REPORT.md). |
| `COLLISION_SAFETY_SANDBOX` | **READY** | `collision_monitor` configurado y activo bajo namespace real, filtrando comandos en la cadena `controller_server` -> `cmd_vel_raw` -> `collision_monitor` -> `cmd_vel_safe` -> `offline_runtime_simulator`. Cinco escenarios (Clear, Slowdown, Stop, Recovery, Cancel) validados de forma independiente y reproducible en dos corridas completas (domain IDs `200`-`204` y `210`-`214`), con emparejamiento causal raw/safe (no basado en el resultado esperado): mediana CLEAR `0.9737`/`1.0`, mediana SLOWDOWN `0.40`/`0.4222`, ambas con ≥17 pares válidos. `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`. Detalle completo en [OFFLINE_NAVIGATION_COLLISION_MONITOR_REPORT.md](OFFLINE_NAVIGATION_COLLISION_MONITOR_REPORT.md). |
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
- No declara odometría validada (la odometría es sintética e integrada deterministamente en 2D en el simulador del sandbox, no representa validación física de L2).
- No declara localización ni mapa validados (las TF `map`→`odom` y `base_link`→`utlidar_lidar` son identidades sintéticas, no extrínsecos medidos).
- No declara Nav2 listo para el robot.
- No declara navegación autónoma: `GLOBAL_PLANNING_SANDBOX = READY` significa exclusivamente que `planner_server` calcula rutas candidatas sobre un mapa sintético (validado originalmente sin control). Actualmente, aunque el runtime incluye `controller_server`, el control local está READY solo dentro del sandbox y la odometría es sintética; `PHYSICAL_NAVIGATION` continúa `NOT_READY`.
- No declara `PHYSICAL_NAVIGATION` como `READY` or `PARTIAL`.
- No declara `ROS_RUNTIME_SANDBOX` como `READY` (permanece `PARTIAL`: faltan behaviors, waypoint follower y Simple Commander; Collision Monitor sí está incluido y validado).
- No declara que `RegulatedPurePursuitController` fue probado o está activo; el plugin que este entorno carga realmente es `dwb_core::DWBLocalPlanner`, configurado y activo exclusivamente en este sandbox.

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
- Se agregó `controller_server` + `local_costmap` al launch y a los parámetros, con remap `cmd_vel` → `cmd_vel_raw`, y se extendió el simulador con suscripción a `cmd_vel_raw`, integración cinemática planar, límites sintéticos y watchdog (Fase 2C).
- Se separó el lifecycle de `controller_server` en un `lifecycle_manager_controller` dedicado, independiente de `lifecycle_manager_navigation` (`map_server`/`planner_server`), para que una falla de activación del controller no regresione el resto del sandbox ya validado (Fase 2C).
- Se descubrió y documentó una incompatibilidad real en el launch (Fase 2C): los parámetros anidados bajo el namespace de un plugin (`FollowPath.plugin`, `FollowPath.critics`, y también `GridBased.tolerance` de la Fase 2B sin que se notara antes) no se aplicaban desde `--params-file` ni desde `-p` porque el launch no reescribía el archivo de parámetros con el namespace real como raíz.
- Se corrigió la causa raíz (corrección posterior a la Fase 2C): `offline_nav_sandbox.launch.py` ahora reescribe los parámetros con `ParameterFile(RewrittenYaml(source_file=PARAMS_FILE, root_key=namespace, convert_types=True), allow_substs=True)`, aplicado a `map_server`, `planner_server` y `controller_server`. `controller_server` alcanza `active` de forma reproducible y `/offline_nav/follow_path` devuelve `SUCCEEDED`. Se corrigió además `GridBased.plugin` en el YAML al namespace C++ real (`nav2_navfn_planner::NavfnPlanner` en vez del alias `nav2_navfn_planner/NavfnPlanner`), error que quedó expuesto recién al aplicarse realmente el parámetro.
- El verificador de aislamiento ahora exige una allowlist estricta de velocidad: solo `cmd_vel_raw` (resuelve a `/offline_nav/cmd_vel_raw`) está permitido; `/cmd_vel`, `/cmd_vel_nav` y `/offline_nav/cmd_vel` quedan rechazados explícitamente (Fase 2C).
- Se integró `nav2_collision_monitor` bajo namespace real `/offline_nav` y un `lifecycle_manager_collision_monitor` aislado, configurado con zonas slowdown y stop sintéticas. El verificador estático y los unit tests se actualizaron para validar la cadena de tópicos raw y safe, prohibir bypasses directos y comprobar las suscripciones correctas del simulador (Fase 2D).
- Se creó `smoke_test_offline_collision_monitor.py` para validar de forma automatizada e independiente en domain IDs aislados los escenarios de Clear, Slowdown (velocidad segura reducida al 40%), Stop (velocidad segura cero, pose estable), Recovery (stop -> clear) y Cancel (Fase 2D).
- Se endureció el emparejamiento causal raw/safe del smoke test de Collision Monitor: cada muestra `cmd_vel_safe` se empareja con la muestra `cmd_vel_raw` más reciente con timestamp anterior o igual (delta máximo `0.25s`), sin reutilizar muestras safe y descartando pares con `abs(raw) < 0.02`; la mediana de ratios se calcula sobre el conjunto completo de pares válidos, nunca seleccionando muestras por cercanía al resultado esperado. Se corrigió además que un timeout transitorio de `ros2 lifecycle get` (bajo carga acumulada de lanzamientos secuenciales) abortara el escenario con una excepción en vez de permitir que el bucle de reintento existente continuara hasta su propio deadline (Fase 2D.1). 129 tests puros en `OK`.

## Próximo incremento

Habilitar `ROS_RUNTIME_SANDBOX = READY` requiere, con decisión explícita de aislamiento, levantar `behavior_server`/`waypoint_follower` y realizar misiones con `nav2_simple_commander`, todo bajo el mismo aislamiento (`ROS_LOCALHOST_ONLY=1`, `ROS_DOMAIN_ID` dedicado, sin `/cmd_vel` real hacia hardware). Esa fase no se ejecutó en este incremento y queda fuera de su alcance.
