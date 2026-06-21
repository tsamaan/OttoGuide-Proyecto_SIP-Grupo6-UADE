# Offline Navigation Sandbox — Collision Monitor Report

**Fecha**: 2026-06-21
**Fase**: Fase 2D — Integración de Collision Monitor aislado bajo el sandbox offline de OttoGuide.

## Objetivo
Integrar `nav2_collision_monitor` exclusivamente dentro del sandbox offline para interceptar y validar la seguridad de los comandos de velocidad, garantizando la siguiente cadena aislada:
`controller_server` -> `cmd_vel_raw` -> `collision_monitor` -> `cmd_vel_safe` -> `offline_runtime_simulator`.

## Resultados Generales
`RESULT=PASS_OFFLINE_COLLISION_SAFETY`. Todos los escenarios de seguridad ante obstáculos sintéticos (Clear, Slowdown, Stop, Recovery, Cancel) fueron validados con éxito bajo domain IDs independientes. No existen bypasses directos de tópicos raw, y todos los procesos finalizan limpiamente con cero huérfanos.

## Configuración Técnica del Sandbox
- **Paquete**: `nav2_collision_monitor`
- **Ejecutable**: `collision_monitor`
- **Namespace**: `/offline_nav`
- **Tópico de entrada**: `cmd_vel_raw`
- **Tópico de salida**: `cmd_vel_safe`
- **Lifecycle Manager**: `lifecycle_manager_collision_monitor` (dedicado y aislado).
- **Zonas sintéticas configuradas**:
  1. **Slowdown zone** (`slowdown_polygon`): Polígono frontal de 1.5m de largo. Ratio de reducción: `0.4` (reduce velocidad a un 40% del comando raw).
  2. **Stop zone** (`stop_polygon`): Polígono frontal cercano de 0.5m. Ratio de velocidad: `0.0` (fuerza parada total).
- **Fuente de observación**: LaserScan `/offline_nav/scan` simulado.

### Configuración Efectiva (`nav2_offline_sandbox_params.yaml`)
```yaml
collision_monitor:
  ros__parameters:
    use_sim_time: false
    base_frame_id: "base_link"
    odom_frame_id: "odom"
    cmd_vel_in_topic: "cmd_vel_raw"
    cmd_vel_out_topic: "cmd_vel_safe"
    transform_tolerance: 0.2
    source_timeout: 2.0
    stop_pub_timeout: 0.5
    polygons: ["slowdown_polygon", "stop_polygon"]
    slowdown_polygon:
      type: "polygon"
      points: "[[1.5, 0.5], [1.5, -0.5], [0.0, -0.5], [0.0, 0.5]]"
      action_type: "slowdown"
      min_points: 1
      slowdown_ratio: 0.4
      visualize: false
    stop_polygon:
      type: "polygon"
      points: "[[0.5, 0.5], [0.5, -0.5], [0.0, -0.5], [0.0, 0.5]]"
      action_type: "stop"
      min_points: 1
      visualize: false
    observation_sources: ["scan"]
    scan:
      type: "scan"
      topic: "scan"
      min_height: -2.0
      max_height: 2.0
```

## Definición de Escenarios y Resultados

| Escenario | Condición del Scan | cmd_vel_raw | cmd_vel_safe | Resultado Pose | Domain IDs |
|---|---|---|---|---|---|
| **A. Clear** | Sin obstáculos | No cero | No cero (igual a raw) | Avanza libremente | 121 / 150 |
| **B. Slowdown** | Obstáculo a 1.0 m | No cero (0.10 m/s) | No cero (0.04 m/s) | Avanza al 40% de velocidad | 122 / 151 |
| **C. Stop** | Obstáculo a 0.3 m | No cero (0.089 m/s) | Exactamente cero | Completamente estable | 123 / 152 |
| **D. Recovery** | Stop -> Clear | No cero | Cero -> No cero | Reanuda movimiento tras remover | 124 / 153 |
| **E. Cancel** | Goal cancelado | Cero | Cero | Estable, GoalStatus=CANCELED | 125 / 154 |

## Seguridad y Aislamiento del Runtime
- **Cero bypasses**: El simulador consume únicamente `/offline_nav/cmd_vel_safe` y carece de suscripción a `cmd_vel_raw`.
- **Allowlist estricta**: El verificador estático rechaza referencias directas a tópicos globales `/cmd_vel` y `/cmd_vel_nav`.
- **Cero hardware**: Ausencia total de nodos Unitree/Livox/RealSense.
- **Cero huérfanos**: Todos los process groups se limpian exitosamente al finalizar.

## Readiness Resultante
```text
COLLISION_SAFETY_SANDBOX = READY
LOCAL_CONTROL_SANDBOX = READY
GLOBAL_PLANNING_SANDBOX = READY
ROS_RUNTIME_SANDBOX = PARTIAL (Faltan: BT Navigator, Behavior Server, Waypoint Follower)
L2_ODOMETRY = NOT_READY
L3_LOCALIZATION_MAP = NOT_READY
PHYSICAL_NAVIGATION = NOT_READY
```
