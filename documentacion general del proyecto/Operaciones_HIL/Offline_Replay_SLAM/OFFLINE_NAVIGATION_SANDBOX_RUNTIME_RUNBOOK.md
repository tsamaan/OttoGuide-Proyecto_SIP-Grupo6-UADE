# Offline Navigation Sandbox — Runtime Runbook

**Fecha**: 2026-06-21
**Fase**: 2D — base de runtime ROS aislada + planificación global + control local closed-loop + Collision Monitor aislado. Los smoke tests de planner, controller, y collision monitor pasan por completo con éxito. No incluye BT Navigator, behavior server, waypoint follower ni Simple Commander.

## Alcance

Este runbook describe cómo levantar y verificar la base de runtime del sandbox offline de OttoGuide en WSL `Ubuntu-24.04` con ROS 2 `jazzy`, sin robot, sin red externa y sin comandos de velocidad.

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

Argumento de launch `sandbox_namespace`, default `offline_nav`. Se aplica como namespace real de ROS (`namespace=` en cada `Node`), no solo como texto.

## Topics esperados

| Topic | Tipo | Publicador / Consumidor |
|---|---|---|
| `/offline_nav/map` | `nav_msgs/OccupancyGrid` | `map_server` (vía `lifecycle_manager`) |
| `/offline_nav/odom` | `nav_msgs/Odometry` | `offline_runtime_simulator` |
| `/offline_nav/scan` | `sensor_msgs/LaserScan` | `offline_runtime_simulator` |
| `/offline_nav/cmd_vel_raw` | `geometry_msgs/Twist` | Publica: `controller_server` / Consume: `collision_monitor` |
| `/offline_nav/cmd_vel_safe` | `geometry_msgs/Twist` | Publica: `collision_monitor` / Consume: `offline_runtime_simulator` |

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

Usa un `ROS_DOMAIN_ID` dedicado (`78` por default, distinto del `77` del wrapper manual) para no interferir con otra sesión del sandbox que pueda estar corriendo. Inicia el runtime mediante el wrapper aislado (`run_offline_navigation_runtime.sh`), no mediante `ros2 launch` directo. Verifica: mensajes en `map`/`odom`/`scan`, presencia de `/tf` y `/tf_static`, ausencia de `/cmd_vel` y `/cmd_vel_nav` globales, ausencia de nodos con nombres asociados a hardware Unitree/Livox/RealSense, y cierre limpio sin procesos huérfanos (verificado sondeando el process group real, no solo `wait()`). Devuelve JSON y exit code (`0`=PASS, `2`=FAIL).

## Planificación global (planner_server)

`planner_server` se activa junto con `map_server` bajo el mismo `lifecycle_manager`. Plugin configurado: `nav2_navfn_planner/NavfnPlanner` (alias `GridBased`). Expone la acción namespaced `/offline_nav/compute_path_to_pose` (`nav2_msgs/action/ComputePathToPose`).

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_planner.py --domain-id 85 --timeout 40
```

Inicia el runtime vía el mismo wrapper aislado, espera a que `planner_server` esté activo (verificado con `ros2 lifecycle get`, no solo descubrimiento del nodo), envía un goal `ComputePathToPose` con start `(-0.75, 0.0)` y goal `(0.75, 0.0)` en frame `map` (orientación identidad, sobre el mapa sintético versionado, tolerancia de endpoint `0.10m`), y verifica: planner activo, action server disponible, resultado `SUCCEEDED`, al menos 2 poses, primera pose cerca del start, última cerca del goal, todas las poses finitas, frame `map`, ausencia de `controller_server` activo, ausencia de `/cmd_vel`/`/cmd_vel_nav` globales, ausencia de nodos de hardware, y cierre sin procesos huérfanos. Ver detalle completo en [OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md](OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md).

Nota: el launch ahora reescribe `nav2_offline_sandbox_params.yaml` con `RewrittenYaml`/`ParameterFile` usando el namespace del sandbox como `root_key`, de forma que los parámetros anidados de plugin (`GridBased.tolerance`, `GridBased.plugin`) se aplican realmente bajo `/offline_nav/planner_server`, en vez de caer silenciosamente al default de stock Nav2.

## Control local (controller_server) — READY

`controller_server` y `local_costmap` están implementados en el launch y los parámetros, con remap `cmd_vel` → `cmd_vel_raw` (resolviendo a `/offline_nav/cmd_vel_raw`). El `lifecycle_manager_navigation` activa `map_server`/`planner_server`, y un `lifecycle_manager_controller` dedicado activa `controller_server` de forma aislada.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_controller.py --domain-id 92 --timeout 60
```

**El control local está completamente validado.** `controller_server` alcanza `ACTIVE` de forma reproducible, sigue la ruta y el simulador avanza con éxito (distancia movida ~0.4m y distancia final <0.1m). La cancelación detiene de forma efectiva el movimiento (pose estable <2mm, twist de odometría cero) en todas las ejecuciones (domain IDs 117-120).

## Seguridad ante colisiones (collision_monitor) — READY

`collision_monitor` y su lifecycle manager dedicado están integrados en el runtime, filtrando comandos en la cadena `controller_server` -> `cmd_vel_raw` -> `collision_monitor` -> `cmd_vel_safe` -> `offline_runtime_simulator`.

```bash
cd "codigo ottoguide"
python3 tools/hil/offline_navigation/smoke_test_offline_collision_monitor.py --base-domain-id 121 --timeout 60
```

Prueba cinco escenarios de seguridad (Clear, Slowdown, Stop, Recovery, Cancel) bajo domain IDs independientes (121-125 y 150-154), confirmando:
- Reducción de velocidad en la zona slowdown (a un 40% del comando raw).
- Parada total (velocidad safe cero) en la zona stop.
- Recuperación automática del avance tras remover obstáculos.
- Cancelación limpia de metas con parada inmediata.

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

## Restricciones

- No se publica `/cmd_vel` ni `/cmd_vel_nav` ni `/offline_nav/cmd_vel` en ningún momento; los únicos tópicos de velocidad permitidos son `/offline_nav/cmd_vel_raw` y `/offline_nav/cmd_vel_safe`.
- No se inicia `behavior_server`, `waypoint_follower` ni Simple Commander en esta fase. `planner_server`, `controller_server` y `collision_monitor` sí están incluidos y activos.
- No se conecta al robot físico, no se usa SSH/SCP, no se contactan IPs `192.168.123.*`.
- No se abren rosbags ni se instala ningún paquete.
- El simulador (`offline_runtime_simulator.py`) integra `cmd_vel_safe` en una pose 2D determinista con límites sintéticos (`0.10 m/s`, `0.30 rad/s`) y watchdog de `0.5s`; no representa odometría validada y no debe usarse como evidencia de L2/L3.
- El planner calcula rutas candidatas sobre el mapa sintético; por sí solo no mueve nada y no constituye evidencia de navegación autónoma.
- `controller_server` con `dwb_core::DWBLocalPlanner` es una elección exclusiva de este sandbox por la incompatibilidad de parámetros detectada; no define ni recomienda el controlador del robot físico.
