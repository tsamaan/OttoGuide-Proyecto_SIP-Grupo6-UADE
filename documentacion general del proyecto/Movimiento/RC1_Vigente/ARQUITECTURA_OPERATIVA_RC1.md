# Arquitectura Operativa RC1 - OttoGuide MVP

## 1. Definicion de arquitectura vigente

OttoGuide RC1 opera con una arquitectura de control en borde orientada a HIL:

- Control de aplicacion: FastAPI + asyncio estricto.
- Orquestacion de dominio: FSM asincrona (TourOrchestrator).
- Integracion robotica: ROS 2/Nav2 por bridge dedicado + control locomocion via SDK Unitree.
- Transporte: CycloneDDS Unicast.
- Interaccion: pipeline local STT/LLM/TTS.
- Observabilidad: REST status, WebSocket telemetria, auditoria JSON por mision.
- Diagnostico factory Unitree: `UnitreeFactoryRestClient` read-only contra `192.168.12.1:9991/con_check`, gobernado por `UNITREE_FACTORY_DIAGNOSTICS_ENABLED`.
- Audio nativo Unitree: SDK2 expone `AudioClient.TtsMaker` y `AudioClient.PlayStream`; RC1 lo documenta como backlog, no como ruta operativa primaria.

## 2. Capas funcionales

| Capa | Componente | Responsabilidad |
|---|---|---|
| Capa 4 | main.py + api/router.py | Exponer interfaces HTTP/WS y ciclo de vida seguro |
| Capa 4 | src/infrastructure/unitree/factory_rest_client.py | Diagnosticar reachability del plano factory Unitree sin emitir comandos |
| Capa 4 | src/core/tour_orchestrator.py | Coordinar estados, tareas asincronas y seguridad operativa |
| Capa 3 | src/interaction/conversation_manager.py | Ejecutar estrategia NLP local/cloud y devolver respuesta |
| Capa 3 | unitree_sdk2py.g1.audio.g1_audio_client.AudioClient | API SDK2 de TTS/PCM nativa del G1 para evaluacion post-RC1 |
| Capa 2 | src/navigation/nav2_bridge.py | Conectar con Nav2/AMCL y clamping de comandos de movimiento |
| Capa 1 | hardware/*.py + unitree_sdk2 | Ejecutar acciones sobre hardware real/sim/mock |

## 3. Flujo de datos E2E

```text
Operador/API -> FastAPI router -> TourOrchestrator FSM
TourOrchestrator -> AsyncNav2Bridge -> ROS 2 Nav2/AMCL
TourOrchestrator -> Hardware Adapter -> Unitree SDK2 (DDS Unicast)
TourOrchestrator -> ConversationManager -> Ollama local -> TTS
TourOrchestrator -> TelemetryManager -> Dashboard WebSocket
TourOrchestrator -> MissionAuditLogger -> logs/mission_*.json
FastAPI /status -> UnitreeFactoryRestClient -> GET 192.168.12.1:9991/con_check (diagnostico)
```

## 3.1 Plano factory Unitree

`UnitreeFactoryRestClient` es un singleton de conexion de diagnostico. Su unico endpoint permitido en RC1 es `GET /con_check` sobre `UNITREE_FACTORY_BASE_URL`, por defecto `http://192.168.12.1:9991`.

Reglas operativas:

1. `UNITREE_FACTORY_DIAGNOSTICS_ENABLED=false` por defecto.
2. El cliente no ejecuta `POST /rest/remote/packet/post/startup`.
3. El cliente no ejecuta `POST /rest/remote/packet/post`.
4. El cliente no ejecuta `GET /rest/remote/packet/pull`.
5. El resultado se expone como fuente secundaria en `/status.factory_rest`.
6. El plano `192.168.12.x` no reemplaza DDS/SDK2 ni ROS2/Nav2.

## 4. Contrato de estados

| Estado | Descripcion | Salidas permitidas |
|---|---|---|
| IDLE | Sistema listo sin mision activa | NAVIGATING, EMERGENCY |
| NAVIGATING | Ejecucion de waypoints y monitoreo de ruta | INTERACTING, IDLE, EMERGENCY |
| INTERACTING | Ventana conversacional en curso | NAVIGATING, EMERGENCY |
| EMERGENCY | Estado final de seguridad con damp() | Sin salida automatica |

### Gate de `/tour/start`

`POST /tour/start` no debe aceptarse si el sistema no esta operacionalmente listo. El router ejecuta un gate previo con estas reglas:

1. La FSM debe estar en `idle`.
2. En `ROBOT_MODE=real`, `AsyncNav2Bridge` debe estar inicializado mediante `await start()`.
3. En `ROBOT_MODE=real`, la abstraccion de hardware debe reportar inicializacion valida via `get_state()`.
4. Si el gate falla, el endpoint retorna `HTTP 503` con `readiness_errors`.
5. `/status` expone `operational_ready` y `readiness_errors` para diagnostico previo al despacho.

## 5. Controles de seguridad vigentes

1. damp() garantizado en shutdown del lifecycle de aplicacion.
2. Endpoint de emergencia de maxima prioridad.
3. Intercepcion y clamping de velocidad en bridge de navegacion.
4. Barrera de preflight antes de inicializar hardware.
5. Confirmacion operatoria obligatoria de modos seguros del robot.
6. Gate de readiness en `/tour/start` para bloquear tours sin Nav2/hardware real inicializados.
7. Diagnostico factory Unitree limitado a `GET /con_check`, sin control remoto propietario.

## 6. Alcance de documentos referenciales

- Los documentos SITL/simulacion se consideran de apoyo historico.
- La operacion RC1 oficial se define por runbooks y protocolos HIL.
