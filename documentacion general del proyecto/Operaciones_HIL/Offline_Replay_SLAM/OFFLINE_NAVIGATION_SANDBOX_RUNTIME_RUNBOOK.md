# Offline Navigation Sandbox — Runtime Runbook

**Fecha**: 2026-06-20
**Fase**: 2B — base de runtime ROS aislada (map_server + lifecycle_manager + TF + odometría/scan sintéticos) más planificación global aislada (`planner_server` + global costmap). No incluye controller, behaviors, waypoint follower, Collision Monitor ni Simple Commander.

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

| Topic | Tipo | Publicador |
|---|---|---|
| `/offline_nav/map` | `nav_msgs/OccupancyGrid` | `map_server` (vía `lifecycle_manager`) |
| `/offline_nav/odom` | `nav_msgs/Odometry` | `offline_runtime_simulator` |
| `/offline_nav/scan` | `sensor_msgs/LaserScan` | `offline_runtime_simulator` |

`/tf` y `/tf_static` permanecen globales (sin namespace), lo cual es seguro porque el aislamiento real lo da `ROS_DOMAIN_ID` + `ROS_LOCALHOST_ONLY=1`, no el namespace de tópicos.

## Frames

| Frame | Publicador | Naturaleza |
|---|---|---|
| `map` → `odom` | `static_transform_publisher` (`map_to_odom_synthetic_tf`) | Identidad sintética. NO es una localización validada. |
| `odom` → `base_link` | `offline_runtime_simulator` (TF dinámico) | Pose fija sintética, velocidad cero. NO representa al G1 real. |
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

Inicia el runtime vía el mismo wrapper aislado, espera a que `planner_server` esté activo, envía un goal `ComputePathToPose` con start `(-0.75, 0.0)` y goal `(0.75, 0.0)` en frame `map` (orientación identidad, sobre el mapa sintético versionado), y verifica: planner activo, action server disponible, resultado `SUCCEEDED`, al menos 2 poses, primera pose cerca del start, última cerca del goal, todas las poses finitas, frame `map`, ausencia de `controller_server`, ausencia de `/cmd_vel`/`/cmd_vel_nav` globales, ausencia de nodos de hardware, y cierre sin procesos huérfanos. Ver detalle completo en [OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md](OFFLINE_NAVIGATION_GLOBAL_PLANNING_REPORT.md).

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

## Restricciones

- No se publica `/cmd_vel` ni `/cmd_vel_nav` en ningún momento.
- No se inicia `controller_server`, `behavior_server`, `waypoint_follower`, `collision_monitor` ni Simple Commander en esta fase. `planner_server` sí está incluido desde la Fase 2B, exclusivamente para planificación global.
- No se conecta al robot físico, no se usa SSH/SCP, no se contactan IPs `192.168.123.*`.
- No se abren rosbags ni se instala ningún paquete.
- El simulador (`offline_runtime_simulator.py`) publica una pose fija con velocidad cero; no es una estimación de odometría validada y no debe usarse como evidencia de L2/L3.
- El planner calcula rutas candidatas sobre el mapa sintético; no mueve nada y no constituye evidencia de navegación autónoma.
