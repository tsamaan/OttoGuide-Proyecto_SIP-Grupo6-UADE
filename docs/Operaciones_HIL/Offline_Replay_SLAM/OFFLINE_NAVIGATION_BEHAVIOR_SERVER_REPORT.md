# Offline Navigation Sandbox — Behavior Server Report

**Fecha**: 2026-06-21
**Fase**: Fase 2E — Behavior Server aislado en el sandbox offline de OttoGuide. Solo plugins `Wait` y `Spin`. No incluye `BackUp`, `DriveOnHeading`, `AssistedTeleop`, BT Navigator, Waypoint Follower ni Simple Commander.

## Objetivo

Integrar `nav2_behaviors/behavior_server` exclusivamente dentro del sandbox offline, manteniendo la cadena de seguridad obligatoria:

```text
controller_server o behavior_server
→ /offline_nav/cmd_vel_raw
→ collision_monitor
→ /offline_nav/cmd_vel_safe
→ offline_runtime_simulator
```

## Resultado general

`RESULT=PASS_OFFLINE_BEHAVIOR_SERVER`. `behavior_server` alcanza `ACTIVE` de forma reproducible con los plugins `Wait` y `Spin` reales (confirmados vía `ros2 param get`), publica exclusivamente en `cmd_vel_raw` (remap idéntico al de `controller_server`), y los tres escenarios (`Wait`, `Spin`, `Cancel Spin`) pasan en dos corridas completas e independientes (domain IDs `160`-`162` y `170`-`172`), sin tópicos prohibidos, sin nodos de hardware, sin BT Navigator/Waypoint Follower/Simple Commander, y sin procesos huérfanos.

## Preflight (sin instalar nada)

```bash
ros2 pkg prefix nav2_behaviors        # /opt/ros/jazzy
ros2 pkg executables nav2_behaviors   # nav2_behaviors behavior_server
```

Nombres pluginlib reales confirmados en `/opt/ros/jazzy/share/nav2_behaviors/behavior_plugin.xml`:

- `nav2_behaviors::Wait` (acción `nav2_msgs/action/Wait`)
- `nav2_behaviors::Spin` (acción `nav2_msgs/action/Spin`)

Parámetros reales descubiertos lanzando `behavior_server` en aislamiento (domain ID de descubrimiento, sin tocar el sandbox): `behavior_plugins`, `wait.plugin`, `spin.plugin`, `global_frame` (default `map`), `robot_base_frame` (default `base_link`), `local_frame` (default `odom`), `max_rotational_vel` (default `1.0`), `min_rotational_vel` (default `0.4`), `rotational_acc_lim`, `simulate_ahead_time`, `enable_stamped_cmd_vel` (default `false` → publica `geometry_msgs/Twist` plano, compatible con `collision_monitor`), `local_costmap_topic` (default `local_costmap/costmap_raw`), `local_footprint_topic` (default `local_costmap/published_footprint`).

## Configuración Efectiva (`nav2_offline_sandbox_params.yaml`)

```yaml
behavior_server:
  ros__parameters:
    use_sim_time: false
    enable_stamped_cmd_vel: false
    cycle_frequency: 10.0
    behavior_plugins: ["wait", "spin"]
    wait:
      plugin: "nav2_behaviors::Wait"
    spin:
      plugin: "nav2_behaviors::Spin"
    global_frame: "odom"
    robot_base_frame: "base_link"
    local_frame: "odom"
    transform_tolerance: 0.2
    simulate_ahead_time: 1.0
    max_rotational_vel: 0.30
    min_rotational_vel: 0.05
    rotational_acc_lim: 1.0
```

`max_rotational_vel: 0.30` cumple el límite conservador exigido (`<= 0.30 rad/s`). `global_frame`/`local_frame` se fijaron en `odom` (frame sintético existente) en vez del default `map`, conforme a la instrucción de reutilizar los frames sintéticos ya disponibles. `local_costmap_topic`/`local_footprint_topic` se dejaron en su default porque resuelven correctamente bajo namespace a `/offline_nav/local_costmap/costmap_raw` y `/offline_nav/local_costmap/published_footprint`, ya publicados por el `local_costmap` de `controller_server` (confirmado con `ros2 topic list` en el runtime integrado).

Marcadores `OFFLINE_ONLY` / `SYNTHETIC` / `NOT_FOR_HARDWARE` documentados en el comentario que precede la sección `behavior_server` del YAML. Estos valores son exclusivos de este sandbox y no representan al Unitree G1 físico.

## Integración del launch

`behavior_server` se agregó bajo namespace real `offline_nav`, usando los mismos `configured_params` (`ParameterFile(RewrittenYaml(...))`) que el resto de los nodos namespaced, con remap `('cmd_vel', 'cmd_vel_raw')` — idéntico al de `controller_server` — y un `lifecycle_manager_behavior_server` dedicado y aislado, siguiendo el mismo patrón que `lifecycle_manager_controller` y `lifecycle_manager_collision_monitor`: si `behavior_server` falla al activarse, queda aislado sin degradar Map, Planner, Controller o Collision Monitor.

Verificado en runtime: `controller_server` y `behavior_server` son los únicos dos publishers de `/offline_nav/cmd_vel_raw`, y `collision_monitor` es su único suscriptor (`ros2 topic info -v`). No existe ningún remap directo de `behavior_server` a `cmd_vel_safe`; el verificador estático (`check_collision_monitor_contract`) lo confirma con la regla `BEHAVIOR_SERVER_DIRECT_SAFE_BYPASS` (nunca disparada) y `BEHAVIOR_SERVER_MISSING_CMD_VEL_RAW_REMAP` (confirma que el remap correcto existe).

## Smoke test

`codigo ottoguide/tools/hil/offline_navigation/smoke_test_offline_behavior_server.py`. El CLI acepta `--base-domain-id` y deriva tres domain IDs consecutivos (`base`, `base+1`, `base+2`) para Wait, Spin y Cancel Spin respectivamente; no hay IDs hardcodeados que ignoren el argumento.

### Escenario A — Wait (`WAIT_DURATION_S = 1.0`)

Confirma `behavior_server` `ACTIVE`, envía la acción `Wait` (`/offline_nav/wait`), exige `SUCCEEDED`, y comprueba pose estable (`diff < 0.002m` tras 0.5s), `odom` twist cero, y ningún comando `cmd_vel_safe` angular no-cero observado en ningún momento del escenario.

### Escenario B — Spin (`SPIN_TARGET_YAW_RAD = 0.50`, tolerancia `0.15 rad`)

Envía `Spin` (`/offline_nav/spin`) con `target_yaw=0.50`, observa `raw_angular_observed` y `safe_angular_observed` no nulos (ambos iguales a `max_rotational_vel=0.30`, confirmando que el comando pasa íntegro por `collision_monitor` en ausencia de obstáculo), exige `SUCCEEDED`, y comprueba error angular final (`|yaw_change - 0.50|`) dentro de tolerancia, traslación mínima (`<0.02m`), twist final cero (tras dejar 1.0s para que el watchdog del simulador expire y se asiente el `cmd_vel=0` explícito que `behavior_server` publica al completar), y pose estable después.

### Escenario C — Cancel Spin (`CANCEL_SPIN_TARGET_YAW_RAD = 3.0`)

Envía `Spin` con un ángulo amplio, espera a observar `raw`/`safe` angular no-cero y cambio real de yaw (`>0.02 rad`) antes de cancelar, cancela, exige `CANCELED`, y comprueba `cmd_vel_safe` angular cero, twist de odometría cero, y pose estable durante al menos `0.5s` tras la cancelación.

## Resultados medidos (dos corridas independientes, sin cambios de código entre ellas)

| Escenario | Domain IDs (run 1 / run 2) | Métricas | Resultado |
|---|---|---|---|
| **Wait** | 160 / 170 | `wait_result=SUCCEEDED`; `pose_stable=true`; `odom_twist_zero=true`; `safe_nonzero_detected=false` (nunca se observó angular safe no-cero) | PASS / PASS |
| **Spin** | 161 / 171 | `spin_result=SUCCEEDED`; `raw_angular_observed=0.30`; `safe_angular_observed=0.30`; `yaw_change=0.62/0.64 rad`; `final_angular_error=0.12/0.14 rad` (tolerancia `0.15`); `translation=0.0m`; `final_twist_zero=true`; `pose_stable_after=true` | PASS / PASS |
| **Cancel Spin** | 162 / 172 | `motion_observed=true`; `raw_angular_observed=0.30`; `safe_angular_observed=0.30`; `cancel_result=CANCELED`; `safe_angular_zero_after_cancel=true`; `odom_twist_zero=true`; `pose_stable=true` | PASS / PASS |

`forbidden_velocity_topics_detected=[]`, `hardware_node_detected=false`, `mission_node_detected=false` (sin BT Navigator, Waypoint Follower ni Simple Commander) y `orphan_processes=0` en los seis escenarios evaluados (3 por corrida × 2 corridas).

`NOT_FOR_PHYSICAL_SAFETY_VALIDATION`: esta evidencia es exclusivamente sintética en simulación offline.

## Verificador y tests

`verify_sandbox_isolation.py` ahora incluye `smoke_test_offline_behavior_server.py` en `RUNTIME_SCAN_FILES`, exige `behavior_server` namespaced y con `lifecycle_manager_behavior_server` dedicado en `REQUIRED_NODE_NAMES`, valida el contrato de no-bypass (`check_collision_monitor_contract` extendido), y agrega `check_no_mission_components` para rechazar cualquier referencia a `bt_navigator`, `waypoint_follower` o `simple_commander` en el launch. La allowlist de velocidad (`check_velocity_topic_allowlist`) ya aceptaba el remap genérico `('cmd_vel', 'cmd_vel_raw')` para cualquier nodo, por lo que `behavior_server` queda cubierto sin requerir cambios adicionales en esa función.

144 tests puros (129 previos + 15 nuevos), todos en `OK`, ejecutables sin ROS. Dos tests previos que prohibían `behavior_server` como ejecutable del launch quedaron desactualizados por esta fase y se corrigieron para mantener la prohibición de `bt_navigator`/`waypoint_follower`/`collision_detector`/`simple_commander` sin bloquear la integración explícitamente autorizada de `behavior_server`.

## Restricciones respetadas

No se conectó el robot físico, no se usó SSH/SCP, no se contactaron IPs `192.168.123.*`, no se usó Internet, no se instalaron paquetes, no se abrieron bags, no se implementó BT Navigator, Waypoint Follower ni Simple Commander, no se configuraron `BackUp`/`DriveOnHeading`/`AssistedTeleop`, no se crearon interfaces de usuario, no se modificó GT-MIN, no se modificaron los estados de readiness física (`L2_ODOMETRY`, `L3_LOCALIZATION_MAP`, `PHYSICAL_NAVIGATION` permanecen `NOT_READY`).

## Readiness resultante

```text
BEHAVIOR_SERVER_SANDBOX = READY
GLOBAL_PLANNING_SANDBOX = READY
LOCAL_CONTROL_SANDBOX = READY
COLLISION_SAFETY_SANDBOX = READY
ROS_RUNTIME_SANDBOX = PARTIAL
L2_ODOMETRY = NOT_READY
L3_LOCALIZATION_MAP = NOT_READY
PHYSICAL_NAVIGATION = NOT_READY
```

`ROS_RUNTIME_SANDBOX` permanece `PARTIAL` porque faltan BT Navigator, Waypoint Follower, Simple Commander y misiones completas — explícitamente fuera de alcance de esta fase.

## Próximo incremento

Antes de avanzar a BT Navigator/Waypoint Follower/Simple Commander, decidir explícitamente el árbol de comportamiento mínimo del sandbox y el alcance de las misiones a validar, manteniendo la misma cadena de seguridad `cmd_vel_raw → collision_monitor → cmd_vel_safe` para cualquier nuevo publisher de velocidad.
