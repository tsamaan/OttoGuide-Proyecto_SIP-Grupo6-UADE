# Offline Navigation Sandbox — Global Planning Report

**Fecha**: 2026-06-20
**Fase**: 2B — planificación global aislada (`planner_server` + global costmap). No incluye `controller_server`, `behavior_server`, `waypoint_follower`, Collision Monitor ni Simple Commander.

## Plugin utilizado

`nav2_navfn_planner/NavfnPlanner`, configurado como `GridBased` en `planner_server.ros__parameters.planner_plugins`. Ambos paquetes candidatos (`nav2_navfn_planner` y `nav2_smac_planner`) están disponibles localmente en WSL `Ubuntu-24.04` (ROS 2 `jazzy`); se usó el preferido (`NavfnPlanner`) según la instrucción de esta fase. No se instaló ningún paquete.

## Action

`/offline_nav/compute_path_to_pose` (`nav2_msgs/action/ComputePathToPose`), bajo el namespace real `offline_nav` aplicado al `planner_server`.

## Start y goal

- **Start**: `(x=-0.75, y=0.0)`, frame `map`, orientación identidad.
- **Goal**: `(x=0.75, y=0.0)`, frame `map`, orientación identidad.

Estas coordenadas coinciden con las propuestas originalmente en la instrucción de esta fase y resultaron libres de obstáculos según el mapa sintético versionado (`offline_sandbox_test_map.yaml`, origen `[-1.0, -0.75, 0.0]`, resolución `0.05`, dimensiones `40x30` px → límites de mundo `x ∈ [-1.0, 1.0]`, `y ∈ [-0.75, 0.75]`); no fue necesario ajustarlas.

## Resultado

| Ejecución | Domain ID | Resultado | Poses | Frame | Primera pose cerca del start | Última pose cerca del goal | Todas finitas |
|---|---|---|---|---|---|---|---|
| 1 | 85 | `SUCCEEDED` | 59 | `map` | Sí | Sí | Sí |
| 2 | 86 | `SUCCEEDED` | 59 | `map` | Sí | Sí | Sí |

Ambas ejecuciones se realizaron levantando el runtime mediante el wrapper aislado (`run_offline_navigation_runtime.sh`), no mediante `ros2 launch` directo. En ambas, `controller_server` no se inició, no se detectaron `/cmd_vel` ni `/cmd_vel_nav` globales, no se detectaron nodos de hardware, y el cierre no dejó procesos propios huérfanos (`orphan_processes: 0` en ambas, verificado mediante sondeo real del process group, no solo `wait()`).

## Configuración Nav2 agregada

`codigo ottoguide/config/navigation/nav2_offline_sandbox_params.yaml` ahora incluye, marcado `OFFLINE_ONLY` / `SYNTHETIC` / `NOT_FOR_HARDWARE`:

- `planner_server`: `use_sim_time: false`, plugin `GridBased` → `nav2_navfn_planner/NavfnPlanner`, `tolerance: 0.20`, `use_astar: false`, `allow_unknown: false`.
- `global_costmap`: `global_frame: map`, `robot_base_frame: base_link`, `resolution: 0.05`, `footprint` sintético rectangular (`0.30m x 0.20m`), capas `static_layer` (`nav2_costmap_2d::StaticLayer`) e `inflation_layer` (`nav2_costmap_2d::InflationLayer`, `inflation_radius: 0.30`, `cost_scaling_factor: 3.0`).

No se configuró `controller_server`, `local_costmap`, `velocity_smoother`, `behaviors`, `waypoint_follower` ni Collision Monitor; las secciones correspondientes fueron eliminadas del YAML en esta fase.

## Restricciones respetadas

- No se conectó al robot físico, no se usó SSH/SCP, no se contactaron IPs `192.168.123.*`.
- No se usó Internet, `apt`, `pip` ni `rosdep`.
- No se abrieron rosbags.
- No se inició `controller_server` en ningún momento.
- No se publicó `/cmd_vel` ni `/cmd_vel_nav` en ningún momento.
- No hubo locomoción ni movimiento real: la pose sintética del simulador (`offline_runtime_simulator.py`) permanece fija en el origen con velocidad cero durante todo el smoke test; el planner calcula una ruta global candidata sin mover nada.
- No se crearon interfaces de usuario.
- No se modificó GT-MIN.

## Estado físico sin cambios

Esta fase no aporta evidencia de L2 (odometría) ni L3 (localización/mapa): la pose y las TF siguen siendo sintéticas, y el mapa usado es el fixture de test versionado, no un mapa físico validado. `L2_ODOMETRY`, `L3_LOCALIZATION_MAP` y `PHYSICAL_NAVIGATION` permanecen `NOT_READY` sin cambios. El nuevo nivel `GLOBAL_PLANNING_SANDBOX` se declara `READY` exclusivamente para la capacidad de planificación global aislada validada aquí; no implica navegación autónoma, control, ni ningún nivel de autonomía física.
