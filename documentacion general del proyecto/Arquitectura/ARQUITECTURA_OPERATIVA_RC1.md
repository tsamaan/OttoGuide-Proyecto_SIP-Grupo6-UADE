# Arquitectura Operativa RC1 - OttoGuide MVP

## 1. Definicion de arquitectura vigente

OttoGuide RC1 opera con una arquitectura de control en borde orientada a HIL:

- Control de aplicacion: FastAPI + asyncio estricto.
- Orquestacion de dominio: FSM asincrona (TourOrchestrator).
- Mensajeria intra-proceso: EventBus Observer (OttoEventBus Singleton async).
- Integracion robotica: ROS 2/Nav2 por bridge dedicado + control locomocion via SDK Unitree.
- Transporte: CycloneDDS Unicast.
- Interaccion: pipeline local STT/LLM/TTS.
- Observabilidad: REST status, WebSocket telemetria, auditoria JSON por mision.
- Diagnostico factory Unitree: `UnitreeFactoryRestClient` read-only contra `192.168.12.1:9991/con_check`, gobernado por `UNITREE_FACTORY_DIAGNOSTICS_ENABLED`.
- Audio nativo Unitree: SDK2 expone `AudioClient.TtsMaker` y `AudioClient.PlayStream`; activo en ROBOT_MODE=real via UnitreeTTSAdapter.

## 2. Capas funcionales

| Capa | Componente | Responsabilidad |
|---|---|---|
| Capa 4 | main.py + api/router.py | Exponer interfaces HTTP/WS, ciclo de vida seguro y graceful shutdown HIL-safe |
| Capa 4 | src/infrastructure/unitree/factory_rest_client.py | Diagnosticar reachability del plano factory Unitree sin emitir comandos |
| Capa 4 | src/core/tour_orchestrator.py | Coordinar estados, tareas asincronas y seguridad operativa |
| Capa 4 | src/core/event_bus.py | Bus de mensajeria intra-proceso (OttoEventBus Singleton async) |
| Capa 4 | src/core/events.py | Catalogo canonico de tipos de eventos (EventType enum) |
| Capa 3 | src/interaction/conversation_manager.py | Ejecutar estrategia NLP local/cloud y devolver respuesta |
| Capa 3 | src/interaction/wake_word_detector.py | Detectar "Hola Otto" y publicar INTERACTION_STARTED en EventBus |
| Capa 3 | src/interaction/tts_unitree_client.py | Adapter TTS dual (Piper/Docker o SDK Unitree AudioClient) |
| Capa 2 | src/navigation/nav2_bridge.py | Conectar con Nav2/AMCL y clamping de comandos de movimiento (legacy; implementa `src.navigation.port.NavigationPort`) |
| Capa 1 | hardware/*.py + unitree_sdk2 | Ejecutar acciones sobre hardware real/sim/mock (HAL canonica via `hardware.interface.RobotHardwareInterface`; `src/hardware/` es legacy y en cuarentena) |

## 3. Flujo de datos E2E

### 3.1 Flujo de tour nominal

```text
Operador/API -> FastAPI router -> TourOrchestrator FSM
TourOrchestrator -> AsyncNav2Bridge -> ROS 2 Nav2/AMCL
TourOrchestrator -> Hardware Adapter -> Unitree SDK2 (DDS Unicast)
TourOrchestrator -> ConversationManager -> Ollama local -> TTS
TourOrchestrator -> TelemetryManager -> Dashboard WebSocket
TourOrchestrator -> MissionAuditLogger -> logs/mission_*.json
FastAPI /status -> UnitreeFactoryRestClient -> GET 192.168.12.1:9991/con_check (diagnostico)
```

> **Fase 2H.0:** este flujo no cambio en comportamiento. `TourOrchestrator` ahora
> tipa sus dependencias contra los contratos canonicos abstractos
> `hardware.interface.RobotHardwareInterface` y `src.navigation.port.NavigationPort`
> en lugar de `RobotHardwareAPI`/`AsyncNav2Bridge` concretos. La instancia
> inyectada en runtime sigue siendo la misma (`AsyncNav2Bridge` legacy, adaptador
> de `hardware/` canonico). Ver
> `documentacion general del proyecto/Arquitectura/ADR_002_RECONCILIACION_NAVEGACION_HARDWARE.md`.

### 3.2 Flujo Event-Driven (FASE R2): Interaccion -> Locomocion

El EventBus desacopla la capa de interaccion de la capa de locomocion.
No existe referencia directa entre WakeWordDetector y TourOrchestrator.

```text
[CAPA 3] WakeWordDetector.detect_cycle()
    |-- Detecta "Hola Otto" en ciclo de audio
    |-- await OttoEventBus.publish(INTERACTION_STARTED, {transcript, source})
              |
              v (asyncio.gather — concurrente)
[CAPA 4] TourOrchestrator._on_interaction_started(event_type, data)
    |-- Guard: state_id == "navigating" (si no, no-op)
    |-- _schedule_audit_event("INTERACTION_STARTED", ...)
    |-- _pending_audio = zeros(1)  [STT fresco en on_enter_interacting]
    |-- await pause_for_interaction()  [AsyncEngine FSM]
              |
              v
    on_exit_navigating(): cancela _odometry_task
    on_enter_interacting():
        |-- _cancel_nav_task_safe()  -> cancela goroutine de navegacion
        |-- nav_bridge.cancel_navigation()  -> cancela goal de Nav2
        |-- hardware.move(MotionCommand(linear_x=0))  -> ROBOT SE DETIENE
        |-- ConversationManager.process_interaction()  -> STT + LLM + TTS
        |-- resume_tour()  -> retoma navegacion
```

### 3.3 Plano factory Unitree

`UnitreeFactoryRestClient` es un singleton de conexion de diagnostico. Su unico endpoint permitido en RC1 es `GET /con_check` sobre `UNITREE_FACTORY_BASE_URL`, por defecto `http://192.168.12.1:9991`.

Reglas operativas:

1. `UNITREE_FACTORY_DIAGNOSTICS_ENABLED=false` por defecto.
2. El cliente no ejecuta `POST /rest/remote/packet/post/startup`.
3. El cliente no ejecuta `POST /rest/remote/packet/post`.
4. El cliente no ejecuta `GET /rest/remote/packet/pull`.
5. El resultado se expone como fuente secundaria en `/status.factory_rest`.
6. El plano `192.168.12.x` no reemplaza DDS/SDK2 ni ROS2/Nav2.

## 4. Catalogo de eventos del EventBus (src/core/events.py)

| Evento | Publicado por | Suscripto por | Descripcion |
|---|---|---|---|
| INTERACTION_STARTED | WakeWordDetector | TourOrchestrator | Wake word detectado; robot debe pausar navegacion |
| INTERACTION_COMPLETED | ConversationManager / TourOrchestrator | WakeWordDetector | Pipeline TTS completado; reactivar escucha |
| INTERACTION_TIMEOUT | WakeWordDetector | TourOrchestrator | Timeout sin respuesta; retornar a NAVIGATING |
| WAYPOINT_REACHED | TourOrchestrator | ConversationManager | Robot alcanzo un waypoint; cambiar zona activa |
| TOUR_COMPLETED | TourOrchestrator | Analytics / Dashboard | Tour completo finalizado |
| TOUR_STARTED | TourOrchestrator | MissionAuditLogger | Nuevo tour iniciado |
| EMERGENCY_STOP | main.lifespan / TourOrchestrator | Todos los subsistemas | Shutdown de emergencia; limpiar recursos |
| FACTORY_UNREACHABLE | Preflight / FactoryRestClient | Dashboard | Perdida de conectividad al plano factory |

## 5. Contrato de estados FSM

| Estado | Descripcion | Salidas permitidas |
|---|---|---|
| IDLE | Sistema listo sin mision activa | NAVIGATING, EMERGENCY |
| NAVIGATING | Ejecucion de waypoints y monitoreo de ruta | INTERACTING (via EventBus INTERACTION_STARTED o POST /tour/pause), IDLE, EMERGENCY |
| INTERACTING | Ventana conversacional en curso | NAVIGATING, EMERGENCY |
| EMERGENCY | Estado final de seguridad con damp() | Sin salida automatica |

### Gate de `/tour/start`

`POST /tour/start` no debe aceptarse si el sistema no esta operacionalmente listo. El router ejecuta un gate previo con estas reglas:

1. La FSM debe estar en `idle`.
2. En `ROBOT_MODE=real`, `AsyncNav2Bridge` debe estar inicializado mediante `await start()`.
3. En `ROBOT_MODE=real`, la abstraccion de hardware debe reportar inicializacion valida via `get_state()`.
4. Si el gate falla, el endpoint retorna `HTTP 503` con `readiness_errors`.
5. `/status` expone `operational_ready` y `readiness_errors` para diagnostico previo al despacho.

## 6. Graceful Shutdown HIL-safe (FASE R3)

Ante SIGINT (Ctrl+C) o SIGTERM (systemd/docker stop), el proceso ejecuta la siguiente secuencia en orden estricto de prioridad de seguridad:

```text
SIGINT/SIGTERM
    |
    v
_signal_handler() -> _shutdown_event.set()
    |
    v
main.lifespan finally: _run_shutdown_sequence()
    |
    STEP 1: OttoEventBus.publish(EMERGENCY_STOP)    <- notifica subsistemas desacoplados
    STEP 2: TourOrchestrator.emergency_stop()       <- cancela nav + odometry tasks
    STEP 3: hardware.move(MotionCommand(linear_x=0)) <- failsafe cinematico
    STEP 4: hardware.damp()  [timeout=1.5s]          <- PARADA ELASTICA (PRIORIDAD ABSOLUTA)
    |
    v
nav_bridge.close()   <- cierre del bridge ROS2/Nav2
    |
    v
Proceso terminado
```

> **NOTA DE SEGURIDAD:** SIGKILL (-9) no es capturable. Configurar `TimeoutStopSec=5` en la unidad systemd del robot para dar margen a la secuencia de shutdown. Si el robot no responde, activar L1+A en el mando para forzar Damp mecanico inmediato.

## 7. Patch de Bug SDK Unitree (FASE R3)

**Bug identificado:** `AudioClient.TtsMaker()` en `libs/unitree_sdk2_python-master/unitree_sdk2py/g1/audio/g1_audio_client.py` tenia `self.tts_index += self.tts_index` (crecimiento exponencial del indice DDS → crash en sesiones largas).

**Resolucion en dos capas:**

1. **Patch directo** en `g1_audio_client.py`: `+= 1` con guard de overflow en INT32_MAX (2,147,483,647).
2. **Wrapper defensivo** en `UnitreeTTSAdapter._speak_sync()`: detecta y autocorrige el crecimiento anomalo del indice si un future update del SDK revierte el patch. Emite `LOGGER.critical` como alerta inmediata.

## 8. Controles de seguridad vigentes

1. damp() garantizado en shutdown del lifecycle de aplicacion (STEP 4 de _run_shutdown_sequence).
2. MotionCommand(0) failsafe cinematico antes de damp() (STEP 3 de _run_shutdown_sequence).
3. Endpoint de emergencia de maxima prioridad (POST /emergency).
4. Intercepcion y clamping de velocidad en bridge de navegacion.
5. Barrera de preflight antes de inicializar hardware.
6. Confirmacion operatoria obligatoria de modos seguros del robot.
7. Gate de readiness en `/tour/start` para bloquear tours sin Nav2/hardware real inicializados.
8. Diagnostico factory Unitree limitado a `GET /con_check`, sin control remoto propietario.
9. SIGINT/SIGTERM capturados con _install_signal_handlers() → secuencia HIL-safe garantizada.
10. Wrapper defensivo en UnitreeTTSAdapter contra bug de indice exponencial del SDK.

## 9. Alcance de documentos referenciales

- Los documentos SITL/simulacion se consideran de apoyo historico.
- La operacion RC1 oficial se define por runbooks y protocolos HIL.
