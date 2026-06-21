# Offline Navigation Sandbox — Collision Monitor Report

**Fecha**: 2026-06-21
**Fase**: Fase 2D.1 — Auditoría y endurecimiento de la evidencia de Collision Monitor bajo el sandbox offline de OttoGuide, cerrando trabajo no commiteado de una ejecución previa interrumpida.

## Objetivo
Integrar `nav2_collision_monitor` exclusivamente dentro del sandbox offline para interceptar y validar la seguridad de los comandos de velocidad, garantizando la siguiente cadena aislada:
`controller_server` -> `cmd_vel_raw` -> `collision_monitor` -> `cmd_vel_safe` -> `offline_runtime_simulator`.

## Resultados Generales
`RESULT=PASS_COLLISION_SAFETY_EVIDENCE_HARDENED`. Todos los escenarios de seguridad ante obstáculos sintéticos (Clear, Slowdown, Stop, Recovery, Cancel) fueron validados con éxito, de forma independiente y reproducible, en dos corridas completas bajo domain IDs distintos: `200`-`204` y `210`-`214`. El emparejamiento de muestras `cmd_vel_raw`/`cmd_vel_safe` usado para calcular los ratios es causal (cada muestra safe se empareja con la muestra raw más reciente con timestamp anterior o igual, delta máximo `0.25s`, sin reutilizar muestras safe, descartando pares con `abs(raw) < 0.02`) e independiente del resultado esperado: no existe selección de pares por cercanía al ratio esperado. No existen bypasses directos de tópicos raw, y todos los procesos finalizan limpiamente con cero huérfanos. `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`: esta evidencia es exclusivamente sintética en simulación offline y no constituye una certificación de seguridad física ni autonomía real en hardware.

Durante la auditoría se corrigió un defecto localizado: `_run()` en `smoke_test_offline_collision_monitor.py` no capturaba `subprocess.TimeoutExpired`, por lo que un timeout transitorio de la CLI `ros2` (observado bajo carga acumulada de lanzamientos secuenciales) abortaba el escenario completo con una excepción en vez de permitir que el bucle de reintento existente (`_wait_for_lifecycle_active`) siguiera esperando hasta su propio deadline. Tras la corrección, ambas corridas (`200` y `210`) completaron los cinco escenarios sin reintentos ni cambios adicionales de código entre ellas.

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

> [!NOTE]
> La validación de Collision Monitor es puramente sintética en simulación offline (watchdog y lógica de desaceleración). `NOT_FOR_PHYSICAL_SAFETY_VALIDATION`: no constituye una certificación de seguridad física ni autonomía real en hardware físico.

Algoritmo de emparejamiento causal aplicado a CLEAR y SLOWDOWN: para cada muestra `cmd_vel_safe`, se busca la muestra `cmd_vel_raw` más reciente con timestamp `<=` al de la muestra safe y delta máximo `0.25s`; cada muestra safe se usa como máximo una vez; se descartan pares con `abs(raw.linear.x) < 0.02`; se exige un mínimo de 3 pares válidos antes de calcular la mediana de `abs(safe/raw)`. La mediana se calcula sobre el conjunto completo de pares válidos, nunca seleccionando pares por cercanía a un ratio esperado.

| Escenario | Domain IDs (run 1 / run 2) | Métricas medidas (run `200` / run `210`) | Resultado |
|---|---|---|---|
| **A. Clear** | 200 / 210 | raw=41/42, safe=20/20 mensajes; pares válidos causales=20/20; **mediana ratio safe/raw=0.9737/1.0** (esperado 0.90–1.10); avance simulado=0.261m/0.259m (>0.05m exigido) | PASS / PASS |
| **B. Slowdown** | 201 / 211 | raw=41/41, safe=20/17 mensajes; pares válidos causales=20/17; **mediana ratio safe/raw=0.40/0.4222** (esperado 0.35–0.45); avance simulado=0.113m/0.113m (>0.01m exigido) | PASS / PASS |
| **C. Stop** | 202 / 212 | raw=101/101, safe=3/3 mensajes (>0); `raw_speed_observed`=0.0895 (>0.01); `safe_zero_sample_observed`=true en ambas; avance simulado=0.0m (<0.005m exigido); pose final estable=true en ambas | PASS / PASS |
| **D. Recovery** | 203 / 213 | raw=34/26, safe=8/10 mensajes; `stop_safe_zero_observed`=true; `recovery_safe_nonzero_observed`=true; `recovery_resumed`=true; avance tras reanudar=0.0179m (>0.01m exigido) en ambas | PASS / PASS |
| **E. Cancel** | 204 / 214 | raw=5/6, safe=4/4 mensajes; `cancel_motion_observed`=true; `cancel_safe_nonzero_before_cancel`=true; `goal_status`=`CANCELED`; `cancel_safe_zero_after_cancel`=true; `cancel_odom_twist_zero`=true; `cancel_pose_stable`=true en ambas | PASS / PASS |

Resultado consolidado por corrida: `decision=PASS` en ambas (`run 200` y `run 210`), `ok=true` para los cinco escenarios en cada corrida, `forbidden_velocity_topics_detected=[]` y `orphan_processes=0` en los diez escenarios evaluados (5 por corrida × 2 corridas).

## Seguridad y Aislamiento del Runtime
- **Cero bypasses**: El simulador consume únicamente `/offline_nav/cmd_vel_safe` y carece de suscripción a `cmd_vel_raw`.
- **Allowlist estricta**: El verificador estático rechaza referencias directas a tópicos globales `/cmd_vel` y `/cmd_vel_nav` y variantes como `cmd_vel_unsafe` o `cmd_vel_filtered`, con tests negativos reales para ambas y para `/offline_nav/cmd_vel`.
- **Cero hardware**: Ausencia total de nodos Unitree/Livox/RealSense en ambas corridas.
- **Cero huérfanos**: Todos los process groups se limpian exitosamente al finalizar, en los diez escenarios evaluados.
- **Tests puros**: 129 tests `unittest` en `OK`, ejecutables sin ROS.
- **Verificadores**: estático y `--runtime` ambos en `PASS`; `smoke_test_offline_collision_monitor.py` está incluido en `RUNTIME_SCAN_FILES`.

## Readiness Resultante
```text
COLLISION_SAFETY_SANDBOX = READY
LOCAL_CONTROL_SANDBOX = READY
GLOBAL_PLANNING_SANDBOX = READY
ROS_RUNTIME_SANDBOX = PARTIAL (Faltan: BT Navigator, Behavior Server, Waypoint Follower; Collision Monitor sí está incluido)
L2_ODOMETRY = NOT_READY
L3_LOCALIZATION_MAP = NOT_READY
PHYSICAL_NAVIGATION = NOT_READY
```
