# OttoGuide — Frontera de Integracion ROS 2

Documento de arquitectura pasivo. Define exclusivamente la topologia
de capas y los limites de responsabilidad entre Python (Capa 4) y
ROS 2 (Capa 2). Auditado contra `codigo ottoguide/libs/unitree_ros2-master/`.

Nota RC1 SRE: el runtime HIL nativo esperado en la Companion PC del G1 EDU (`192.168.123.164`, Ubuntu 20.04) es `ROS 2 Foxy`. Las referencias a `ROS 2 Humble` solo son validas para host de desarrollo, SITL o documentacion historica, no para el despliegue HIL nativo del G1.

El audio nativo del G1 no requiere ROS 2 en RC1. El SDK Python expone `unitree_sdk2py.g1.audio.g1_audio_client.AudioClient`, servicio `voice`, con `TtsMaker`, `PlayStream`, `PlayStop`, `GetVolume` y `SetVolume`. Esta ruta usa SDK2/RPC sobre DDS y debe aislarse como adaptador de audio separado si se integra post-RC1.

---

## Arquitectura de Capas

```
┌─────────────────────────────────────────────────────────┐
│  Capa 4 — OttoGuide Python (este repositorio)           │
│  FastAPI + asyncio + UnitreeG1Adapter                   │
│  Comunicacion: DDS Unicast directo via unitree_sdk2py   │
│  Domain 0 (real) | Domain 1 (sim, loopback lo)          │
├─────────────────────────────────────────────────────────┤
│  Capa 3 — IA                                            │
│  Ollama daemon (localhost:11434) + ConversationManager  │
├─────────────────────────────────────────────────────────┤
│  Capa 2 — ROS 2 Foxy (proceso externo HIL G1)           │
│  Nav2 + AMCL + drivers de sensores                      │
│  Topicos clave (ver seccion mas abajo)                  │
├─────────────────────────────────────────────────────────┤
│  Capa 1 — Hardware fisico                               │
│  Robot Unitree G1 EDU 8 (IP 192.168.123.161)           │
│  LiDAR Livox MID360 | Camara RealSense D435i            │
└─────────────────────────────────────────────────────────┘
```

---

## Principio de Aislamiento de Capas

**El codigo Python (Capa 4) solo inicializa ROS 2 en el bridge dedicado de navegacion.**

La locomocion del G1 se controla via DDS Unicast directo
(`unitree_sdk2py.g1.loco.g1_loco_client.LocoClient`), sin
pasar por ningun nodo ROS 2. Este diseno es intencional y
replica el patron sim-to-real de Unitree SDK2:

```
Capa 4 (Python) ──DDS Unicast──► Capa 1 (G1 hardware)
                                   BYPASSES Capa 2 (ROS 2)
```

ROS 2 opera en paralelo gestionando sensores y navegacion,
publicando a los topicos que consume
`codigo ottoguide/src/navigation/nav2_bridge.py`
mediante `AsyncNav2Bridge` (cliente ROS 2 Python/rclpy — proceso externo).

---

## Topicos ROS 2 Relevantes (desde unitree_ros2-master)

Auditados en `codigo ottoguide/libs/unitree_ros2-master/README.md`.

### Subscripcion (datos entrantes al sistema)

| Topico | Tipo de mensaje | Productor | Consumidor OttoGuide |
|--------|----------------|-----------|----------------------|
| `/sportmodestate` | `unitree_go::msg::SportModeState` | G1 via DDS bridge | Nav2 (estado de posicion) |
| `lf/lowstate` | `unitree_go::msg::LowState` | G1 hardware | Diagnostico (solo lectura) |
| `/utlidar/cloud` | `sensor_msgs/PointCloud2` | LiDAR Livox MID360 | Nav2 / AMCL |
| `/wirelesscontroller` | `unitree_go::msg::WirelessController` | G1 hardware | No usado en MVP |

Para SLAM 2D, `slam_toolbox` requiere `/scan` (`sensor_msgs/LaserScan`). Si `livox_ros_driver2` solo publica `/utlidar/cloud`, la conversion `PointCloud2 -> LaserScan` mediante `pointcloud_to_laserscan` debe habilitarse despues de confirmar en HIL que `/utlidar/cloud` existe y antes de iniciar `slam_toolbox`.

### Publicacion (comandos desde el sistema)

| Topico | Tipo de mensaje | Publicador | Descripcion |
|--------|----------------|------------|-------------|
| `/goal_pose` | `geometry_msgs/PoseStamped` | `AsyncNav2Bridge` (`src/navigation/nav2_bridge.py`) | Waypoint objetivo para Nav2 |
| `/cmd_vel` | `geometry_msgs/Twist` | Nav2 (interno) | Velocidad de base → **NO desde Python** |

> **IMPORTANTE**: `cmd_vel` es publicado por Nav2, NO por el codigo
> Python de OttoGuide. La locomocion se controla exclusivamente via
> `LocoClient.Move()` sobre DDS, no via `/cmd_vel`.

---

## IDL de Mensajes — Frontera G1 vs Go2/B2/H1

Auditado en `codigo ottoguide/libs/unitree_ros2-master/README.md:34` y
`codigo ottoguide/libs/unitree_mujoco-main/readme.md:32-33`:

| Robot | IDL | Notas |
|-------|-----|-------|
| G1, H1-2 | `unitree_hg` | IDL bajo nivel del G1 EDU 8 |
| Go2, B2, H1, B2w, Go2w | `unitree_go` | **NO usar para G1** |

El paquete `unitree_ros2` en `codigo ottoguide/libs/unitree_ros2-master/cyclonedds_ws/`
expone los mensajes `unitree_go::msg` y `unitree_api::msg` para
control de alto nivel via ROS 2. Para el G1, el control de
locomocion se hace via `unitree_sdk2py` (Capa 4), no via estos topicos.

---

## unitree_sim_isaaclab — Alcance y Limitaciones

`codigo ottoguide/libs/unitree_sim_isaaclab-main/` esta presente en el repositorio
pero queda **completamente excluido del MVP** por las siguientes razones:

1. **Requiere GPU NVIDIA**: Isaac Lab necesita CUDA para entrenamiento RL.
   La Companion PC (Ubuntu) no dispone de GPU dedicada.
2. **Proposito diferente**: Es un framework de entrenamiento por
   Reinforcement Learning (RL), no un simulador de control directo.
3. **Fuera del alcance**: El MVP de OttoGuide usa control de alto nivel
   (LocoClient FSM), no politicas RL entrenadas.

Para validacion de trayectorias y colisiones en pasillo universitario
con GPU, Isaac Lab queda documentado como trabajo futuro post-MVP.

---

## Restricciones de Codigo

- `rclpy` solo esta permitido en `codigo ottoguide/src/navigation/nav2_bridge.py`.
- El resto de modulos de aplicacion no debe inicializar nodos ROS 2.
- `ament_index_python` no forma parte del runtime de OttoGuide MVP.
- `real_adapter.py`, `sim_adapter.py` y `mock_adapter.py` no importan ROS 2.
- Cualquier integracion futura de `AudioClient` debe vivir fuera de `nav2_bridge.py` y no puede compartir responsabilidad con locomocion.

---

## EventBus — Mensajeria Intra-Proceso (FASE R2)

A partir de la FASE R2, la comunicacion entre la capa de interaccion (Capa 3)
y el orquestador (Capa 4) se realiza exclusivamente a traves de `OttoEventBus`.
Esto elimina la dependencia directa entre `WakeWordDetector` y `TourOrchestrator`.

```
[Capa 3] WakeWordDetector
    └─► OttoEventBus.publish(INTERACTION_STARTED)
              │
              ▼  (asyncio.gather — concurrente, sin bloqueo)
[Capa 4] TourOrchestrator._on_interaction_started()
    └─► pause_for_interaction()  →  nav_bridge.cancel_navigation()
                                 →  hardware.move(MotionCommand(v=0))
```

**Modulos relevantes:**
- `src/core/event_bus.py` — Singleton `OttoEventBus` (subscribe / publish / fire-and-forget)
- `src/core/events.py` — Catalogo canonico de `EventType` (8 eventos)

**Restriccion:** El `EventBus` opera exclusivamente dentro del proceso Python (asyncio).
No debe usarse para comunicacion inter-proceso; para eso existe DDS/ROS2.

---

## Graceful Shutdown HIL-safe (FASE R3)

Ante `SIGINT` o `SIGTERM`, `main.py` ejecuta la siguiente secuencia antes de terminar
el proceso, garantizando que el hardware fisico quede en estado elastico (damp):

```
Senal OS (SIGINT/SIGTERM)
    │
    ▼  _install_signal_handlers()  →  _shutdown_event.set()
    │
    ▼  main.lifespan.finally  →  _run_shutdown_sequence()
    │
    ├─ STEP 1: OttoEventBus.publish(EMERGENCY_STOP)         [notifica subsistemas]
    ├─ STEP 2: TourOrchestrator.emergency_stop()  timeout=2s [cancela nav+odometry]
    ├─ STEP 3: hardware.move(MotionCommand(v=0))  timeout=0.5s [failsafe cinematico]
    └─ STEP 4: hardware.damp()                   timeout=1.5s [PRIORIDAD ABSOLUTA]
```

**Nota operativa:** `SIGKILL` no es capturable. Configurar `TimeoutStopSec=5` en
la unidad systemd del robot. Si el robot no responde, activar `L1+A` en el mando.
