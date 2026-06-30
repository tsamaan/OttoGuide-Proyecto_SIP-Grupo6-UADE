"""
@TASK: Implementar orquestador central de tour integrando todos los subsistemas HIL Fase 6
@INPUT: Instancias activas de RobotHardwareInterface, NavigationPort, ConversationManager,
        VisionProcessor
@OUTPUT: Maquina de estados asincrona con callbacks de integracion completa por estado;
         efectos de lado: movimiento del robot, TTS, inyeccion de odometria, telemetria WebSocket,
         persistencia de eventos de auditoria en JSON
@CONTEXT: Modulo central de control; unico coordinador de subsistemas durante el tour.
          python-statemachine AsyncEngine gestiona todos los callbacks de forma no bloqueante.
          configuration[0].id se usa para leer el estado activo (current_state esta deprecado).
          Fase 2H.0: TourOrchestrator depende de los contratos canonicos abstractos
          hardware.interface.RobotHardwareInterface y src.navigation.port.NavigationPort,
          no de implementaciones concretas. La implementacion de navegacion inyectada en
          main.py sigue siendo la del bridge Nav2 legacy hasta Fase 2H.1.
@SECURITY: EMERGENCY es la unica transicion con prioridad absoluta; Damp() es terminal.

STEP 1: Definir grafo de estados (IDLE, NAVIGATING, INTERACTING, EMERGENCY) en TourOrchestrator
STEP 2: Implementar callbacks on_enter/on_exit con logica de integracion real de subsistemas
STEP 3: Gestionar tareas background (odometria, nav) con cancelacion segura via CancelledError
STEP 4: Exponer dispatch_tour para integracion con FastAPI BackgroundTasks

Constantes operativas del modulo:
  DAMP_TIMEOUT_S (1.5 s)           — Cota dura de tiempo de reaccion ante EMERGENCY; no elevar
  AUDIO_CAPTURE_TIMEOUT_S (8.0 s)  — Timeout de interaccion NLP; ajustar segun duracion del wake-word
  ODOMETRY_INJECT_TIMEOUT_S (0.5 s)— Timeout de inyeccion de odometria en AsyncNav2Bridge
  WAYPOINT_POLL_INTERVAL_S (0.1 s) — Intervalo de ceder el event loop entre waypoints consecutivos
  NAV_TASK_SETTLE_S (0.05 s)       — Pausa tras cancel de tarea background para settledness del loop
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from numpy.typing import NDArray

from statemachine import State, StateMachine
from statemachine.engines.async_ import AsyncEngine

from hardware.interface import MotionCommand, RobotHardwareInterface
from src.api.websocket_manager import TelemetryManager
from src.core.mission_audit import MissionAuditLogger
from src.core.events import EventType
from src.core.event_bus import OttoEventBus
from src.interaction import ConversationManager, ConversationRequest, ConversationResponse
from src.interaction.runtime_port import (
    InteractionContext,
    InteractionRuntimePort,
    InteractionRuntimeUnavailableError,
    WorkerEventEnvelope,
    WorkerEventType,
)
from src.navigation.models import NavWaypoint
from src.navigation.port import NavigationPort
from src.vision import OdometryVector, QRStationDetected, VisionProcessor


# ---------------------------------------------------------------------------
# Constantes de operacion
# ---------------------------------------------------------------------------

DAMP_TIMEOUT_S: float = 1.5
AUDIO_CAPTURE_TIMEOUT_S: float = 8.0
ODOMETRY_INJECT_TIMEOUT_S: float = 0.5
WAYPOINT_POLL_INTERVAL_S: float = 0.1
NAV_TASK_SETTLE_S: float = 0.05
INTERACTION_TASK_SETTLE_S: float = 0.5

LOGGER = logging.getLogger(__name__)
ROBOT_MODE_REAL: str = "real"


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TourContext:
    """
    @TASK: Encapsular el estado mutable del tour activo para observabilidad externa
    @INPUT: Actualizaciones incrementales desde los callbacks del orquestador en cada transicion
    @OUTPUT: Snapshot del tour consultable por APIServer y broadcast WebSocket en cualquier instante
    @CONTEXT: Objeto mutable compartido entre todos los estados de la FSM; no thread-safe, destinado
              exclusivamente al event loop principal. Consultado via propiedad orchestrator.context.
    @SECURITY: No persistir en disco; solo en memoria durante la sesion activa del proceso.

    STEP 1: Registrar plan de waypoints, indice de posicion actual y ultima respuesta de interaccion
    STEP 2: Mantener last_error con la causa de la ultima emergencia para diagnostico post-mortem
    """

    waypoint_plan: list[NavWaypoint] = field(default_factory=list)
    current_waypoint_index: int = 0
    last_interaction: Optional[ConversationResponse] = None
    last_error: Optional[str] = None
    tour_id: Optional[str] = None
    last_station_id: Optional[str] = None
    last_station_qr_value: Optional[str] = None
    last_station_detected_at: Optional[str] = None
    last_station_matches_expected: Optional[bool] = None


@dataclass(slots=True)
class EmergencyStopResult:
    """
    @TASK: Tipar el resultado terminal de una secuencia de EMERGENCY para el caller de emergency_stop()
    @INPUT: Poblado incrementalmente por on_enter_emergency() durante cada fase de la secuencia
    @OUTPUT: Snapshot inmutable-por-convencion consultado por main._run_shutdown_sequence()
    @CONTEXT: Resuelve el falso positivo donde un retorno normal de emergency_stop() se interpretaba
              como exito terminal sin verificar si damp() realmente tuvo exito.
    @SECURITY: terminal_safe NO puede inferirse solo de la transicion FSM a EMERGENCY; requiere
               damp_succeeded=True como condicion necesaria. errors acumula cada excepcion absorbida
               para diagnostico post-mortem sin romper la garantia de no propagar excepciones.
    """

    nav_cancel_attempted: bool = False
    nav_cancel_succeeded: bool = False
    zero_velocity_attempted: bool = False
    zero_velocity_succeeded: bool = False
    damp_attempted: bool = False
    damp_succeeded: bool = False
    terminal_safe: bool = False
    already_emergency: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TourPlan:
    """
    @TASK: Encapsular el plan de un tour como una secuencia tipada e inmutable de waypoints
    @INPUT: Lista de NavWaypoint validados por el endpoint FastAPI y un identificador de sesion opcional
    @OUTPUT: Estructura frozen despachada como argumento unico a dispatch_tour()
    @CONTEXT: Contrato de entrada del endpoint POST /tour/start. tour_id permite correlacionar logs
              de auditoria JSON con sesiones HTTP especificas para trazabilidad end-to-end.
    @SECURITY: Frozen (inmutable tras construccion); no puede ser mutado por el caller tras el despacho.

    STEP 1: Definir lista de waypoints y tour_id para trazabilidad de la sesion
    """

    waypoints: list[NavWaypoint]
    tour_id: str = "unidentified"


# ---------------------------------------------------------------------------
# Orquestador central
# ---------------------------------------------------------------------------

class TourOrchestrator(StateMachine):
    """
    @TASK: Implementar la FSM central que coordina todos los subsistemas HIL del robot guia universitario
    @INPUT: Dependencias inyectadas via constructor DI: hardware_api, nav_bridge, conversation_manager,
            vision_processor, telemetry_manager, mission_audit_logger, damp_timeout_s, robot_mode
    @OUTPUT: FSM de 4 estados con callbacks async completos y los siguientes efectos de lado:
             movimiento del robot via HAL, reproduccion de audio TTS, inyeccion de odometria AMCL,
             broadcast de telemetria WebSocket, persistencia de eventos de auditoria en JSON
    @CONTEXT: Clase central del sistema; unica instancia en el lifespan de FastAPI referenciada via
              app.state.orchestrator. python-statemachine con AsyncEngine para callbacks no bloqueantes.
    @SECURITY: La transicion trigger_emergency tiene prioridad absoluta desde cualquier estado operativo.
               El estado EMERGENCY es final (python-statemachine final=True); no hay salida automatica.

    Grafo de estados:
      IDLE --(start_tour)--> NAVIGATING
      NAVIGATING --(pause_for_interaction)--> INTERACTING
      INTERACTING --(resume_tour)--> NAVIGATING
      NAVIGATING --(finish_tour)--> IDLE
      ANY --(trigger_emergency)--> EMERGENCY (final)

    Meta.engine = AsyncEngine garantiza que todos los on_enter_*/on_exit_* sean awaitable.
    """

    # ------------------------------------------------------------------
    # Definicion del grafo de estados
    # ------------------------------------------------------------------

    idle: State = State("IDLE", initial=True)
    navigating: State = State("NAVIGATING")
    interacting: State = State("INTERACTING")
    emergency: State = State("EMERGENCY", final=True)

    # ------------------------------------------------------------------
    # Definicion de transiciones
    # ------------------------------------------------------------------

    start_tour = idle.to(navigating)
    pause_for_interaction = navigating.to(interacting)
    resume_tour = interacting.to(navigating)
    finish_tour = navigating.to(idle)
    trigger_emergency = (
        idle.to(emergency)
        | navigating.to(emergency)
        | interacting.to(emergency)
    )

    class Meta:
        """
        @TASK: Configurar el motor asíncrono de python-statemachine para todos los callbacks de estado
        @INPUT: AsyncEngine importado desde statemachine.engines.async_
        @OUTPUT: Todos los metodos on_enter_*/on_exit_* ejecutados con await en el event loop activo
        @CONTEXT: Requisito critico para no bloquear el event loop principal de FastAPI/uvicorn.
                  Compatible con python-statemachine >= 0.9.
        @SECURITY: Sin AsyncEngine los callbacks sincronos bloquean el event loop; el sistema entero se congela.
        """

        engine = AsyncEngine

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        hardware_api: RobotHardwareInterface,
        nav_bridge: NavigationPort,
        conversation_manager: ConversationManager,
        vision_processor: VisionProcessor,
        telemetry_manager: Optional[TelemetryManager] = None,
        mission_audit_logger: Optional[MissionAuditLogger] = None,
        damp_timeout_s: float = DAMP_TIMEOUT_S,
        audio_capture_timeout_s: float = AUDIO_CAPTURE_TIMEOUT_S,
        robot_mode: str = "mock",
        event_bus: Optional[OttoEventBus] = None,
        interaction_runtime: Optional[InteractionRuntimePort] = None,
    ) -> None:
        """
        @TASK: Inyectar dependencias de todos los subsistemas e inicializar el estado interno de la FSM
        @INPUT: hardware_api — adaptador HAL activo (real/sim/mock) que implementa RobotHardwareInterface
                nav_bridge — implementacion de NavigationPort (AsyncNav2Bridge legacy o stub/mock)
                conversation_manager — gestor NLP con estrategia local/cloud intercambiable
                vision_processor — procesador de odometria visual via AprilTags y camara D435i
                telemetry_manager — gestor de broadcast WebSocket (opcional; None desactiva telemetria)
                mission_audit_logger — persistencia de eventos de mision en JSON (opcional)
                damp_timeout_s — timeout fisico de Damp() en segundos; debe ser >= 0.5 s
                audio_capture_timeout_s — timeout maximo del pipeline NLP completo en segundos
                robot_mode — "real" | "sim" | "mock"; inyectado desde config/settings.py (no de os.environ)
                event_bus — instancia de OttoEventBus para suscribirse a INTERACTION_STARTED;
                            si None, se usa OttoEventBus.get_instance() (Singleton global)
        @OUTPUT: Instancia de TourOrchestrator en estado IDLE con todos los atributos inicializados
                 y suscripción activa a EventType.INTERACTION_STARTED en el EventBus.
        @CONTEXT: Constructor DI; todos los subsistemas deben estar en estado ACTIVO antes de inyectar.
                  super().__init__() se invoca al final para que python-statemachine inicialice el grafo.
        @SECURITY: damp_timeout_s <= 0 lanza ValueError; por debajo de 0.5 s puede no propagarse via DDS.
                   LOGGER.critical al arrancar advierte del kill switch mecanico L1+A disponible.

        STEP 1: Validar parametros criticos de seguridad (ValueError si damp o audio timeout <= 0)
        STEP 2: Persistir referencias a todos los subsistemas inyectados como atributos privados
        STEP 3: Inicializar contexto del tour, handles de tareas background y atributos de interaccion pendiente
        STEP 4: Suscribirse a EventType.INTERACTION_STARTED en el EventBus
        STEP 5: Emitir advertencia CRITICAL de kill switch mecanico al arrancar
        STEP 6: Invocar super().__init__() para que python-statemachine inicialice el grafo de estados
        """
        if damp_timeout_s <= 0:
            raise ValueError("damp_timeout_s debe ser mayor que 0.")
        if audio_capture_timeout_s <= 0:
            raise ValueError("audio_capture_timeout_s debe ser mayor que 0.")

        self._hardware_api: RobotHardwareInterface = hardware_api
        self._nav_bridge: NavigationPort = nav_bridge
        self._conversation_manager: ConversationManager = conversation_manager
        self._vision_processor: VisionProcessor = vision_processor
        self._telemetry_manager: Optional[TelemetryManager] = telemetry_manager
        self._mission_audit_logger: Optional[MissionAuditLogger] = mission_audit_logger
        self._damp_timeout_s: float = damp_timeout_s
        self._audio_capture_timeout_s: float = audio_capture_timeout_s
        self._robot_mode: str = robot_mode.strip().lower()
        self._interaction_runtime: Optional[InteractionRuntimePort] = interaction_runtime

        self._context: TourContext = TourContext()
        self._odometry_task: Optional[asyncio.Task[None]] = None
        self._nav_task: Optional[asyncio.Task[None]] = None
        self._interaction_sequence: int = 0
        self._interaction_task: Optional[asyncio.Task[None]] = None
        self._interaction_emergency_task: Optional[asyncio.Task[None]] = None
        self._interaction_stop_task: Optional[asyncio.Task[None]] = None
        self._deferred_current_interaction_task: Optional[asyncio.Task[None]] = None
        self._active_runtime_interaction_id: Optional[str] = None
        self._interaction_terminal_outcome: Optional[str] = None
        self._runtime_stop_sent_for_interaction_id: Optional[str] = None
        self._interaction_done_event: asyncio.Event = asyncio.Event()
        self._pending_audio: np.ndarray = np.zeros(1, dtype=np.float32)
        self._pending_language: str = "es"
        self._last_emergency_result: Optional[EmergencyStopResult] = None
        self._closed: bool = False

        resolved_bus = event_bus if event_bus is not None else OttoEventBus.get_instance()
        self._event_bus: OttoEventBus = resolved_bus
        self._event_bus.subscribe(EventType.INTERACTION_STARTED, self._on_interaction_started)
        self._event_bus.subscribe(EventType.QR_STATION_DETECTED, self._on_qr_station_detected)
        LOGGER.info(
            "[Orchestrator] Suscripción a INTERACTION_STARTED y QR_STATION_DETECTED "
            "registrada en OttoEventBus."
        )

        LOGGER.critical(
            "[SAFETY] TourOrchestrator inicializado. "
            "L1+A en el mando fuerza Damp mecanico inmediato. "
            "Control manual y API simultaneos estan estrictamente prohibidos en NAVIGATING."
        )

        super().__init__()

    # ------------------------------------------------------------------
    # Propiedades de observabilidad
    # ------------------------------------------------------------------

    @property
    def context(self) -> TourContext:
        """
        @TASK: Exponer el contexto mutable del tour activo para telemetria y observabilidad externa
        @INPUT: Sin parametros
        @OUTPUT: Referencia al TourContext interno con tour_id, current_waypoint_index,
                 last_interaction, last_error y waypoint_plan
        @CONTEXT: Consumido por APIServer para responder a GET /status y por el broadcast WebSocket.
                  Los campos clave son tour_id, current_waypoint_index y last_error.
        @SECURITY: Solo lectura recomendada desde fuera del orquestador; mutar externamente puede
                   causar race conditions con los callbacks de estado de la FSM.
        """
        return self._context

    @property
    def state_id(self) -> str:
        """
        @TASK: Retornar el identificador canonico del estado activo actual de la FSM
        @INPUT: Sin parametros
        @OUTPUT: String con id del estado ("idle", "navigating", "interacting", "emergency");
                 "uninitialized" si la configuracion de la FSM esta vacia
        @CONTEXT: Reemplaza current_state (deprecado en python-statemachine); usa configuration[0].id.
                  Debe usarse en toda la codebase en lugar de acceder a current_state directamente.
        @SECURITY: Solo lectura; no activa transiciones ni tiene side-effects de ningun tipo.

        STEP 1: Leer la configuracion activa de la FSM; retornar "uninitialized" si la lista esta vacia
        """
        cfg = self.configuration
        if not cfg:
            return "uninitialized"
        return next(iter(cfg)).id

    # ------------------------------------------------------------------
    # API publica para FastAPI BackgroundTasks
    # ------------------------------------------------------------------

    async def dispatch_tour(self, plan: TourPlan) -> None:
        """
        @TASK: Despachar un plan de tour como tarea background no bloqueante para FastAPI
        @INPUT: plan — TourPlan con lista de NavWaypoint y tour_id de sesion
        @OUTPUT: _context actualizado con el plan; transicion a NAVIGATING ejecutada;
                 _navigation_loop lanzado como asyncio.Task; retorno inmediato sin bloquear el loop HTTP
        @CONTEXT: Punto de entrada del endpoint POST /tour/start. FastAPI debe invocarlo dentro
                  de BackgroundTasks para no bloquear la respuesta HTTP al cliente.
        @SECURITY: Si el orquestador no esta en IDLE, se rechaza con RuntimeError antes de cualquier
                   mutacion de estado, garantizando que no se despachan tours concurrentes.

        STEP 1: Validar que el estado actual es "idle"; RuntimeError con detalle si no lo es
        STEP 2: Persistir el plan en _context y resetear current_waypoint_index a 0
        STEP 3: Programar evento de auditoria TOUR_START via _schedule_audit_event
        STEP 4: Ejecutar transicion start_tour via AsyncEngine (activa on_enter_navigating)
        STEP 5: Lanzar _navigation_loop como asyncio.Task con nombre trazable "nav-loop-{tour_id}"
        """
        if self.state_id != "idle":
            raise RuntimeError(
                f"dispatch_tour() rechazado: estado actual es '{self.state_id}', se requiere 'idle'."
            )

        self._context.waypoint_plan = list(plan.waypoints)
        self._context.current_waypoint_index = 0
        self._context.tour_id = plan.tour_id
        self._context.last_error = None

        self._schedule_audit_event(
            event_type="TOUR_START",
            node_id=self._resolve_logical_waypoint_id_by_index(0),
            payload={
                "tour_id": plan.tour_id,
                "waypoints_total": len(plan.waypoints),
            },
        )

        await self.start_tour()

        LOGGER.info(
            "[Orchestrator] dispatch_tour aceptado. tour_id=%s waypoints=%d",
            plan.tour_id,
            len(plan.waypoints),
        )

    async def request_interaction(
        self,
        audio_buffer: NDArray[np.float32],
        language: str = "es",
    ) -> None:
        """
        @TASK: Solicitar transicion a INTERACTING desde una fuente externa (wake-word detector o API)
        @INPUT: audio_buffer — PCM float32 del wake-word ya capturado por el detector externo
                language — codigo ISO del idioma del audio (default "es")
        @OUTPUT: _pending_audio y _pending_language actualizados; transicion pause_for_interaction
                 ejecutada; control devuelto tras activar on_enter_interacting en el AsyncEngine
        @CONTEXT: Invocado por el detector de wake-word o por el endpoint POST /tour/pause.
                  on_enter_interacting consume _pending_audio y delega a process_interaction().
        @SECURITY: Solo transitable desde NAVIGATING; en cualquier otro estado se ignora con
                   logging.debug, evitando conflictos por multiples fuentes de activacion concurrentes.

        STEP 1: Verificar estado "navigating"; logging.debug y retorno inmediato si no corresponde
        STEP 2: Persistir audio_buffer en _pending_audio y language en _pending_language
        STEP 3: Ejecutar transicion pause_for_interaction via AsyncEngine
        """
        if self.state_id != "navigating":
            LOGGER.debug(
                "[Orchestrator] request_interaction ignorado: estado='%s'", self.state_id
            )
            return

        self._pending_audio = audio_buffer
        self._pending_language = language

        await self.pause_for_interaction()

    async def _on_interaction_started(
        self,
        event_type: EventType,
        data: Any,
    ) -> None:
        """
        @TASK: Reaccionar al evento INTERACTION_STARTED publicado por WakeWordDetector
        @INPUT: event_type — EventType.INTERACTION_STARTED (ignorado; el tipo ya está filtrado por el bus)
                data — dict con keys: 'transcript' (str), 'source' (str)
        @OUTPUT: Si el robot está en NAVIGATING:
                   1. Parada cinemática segura (cancel nav + velocidad 0)
                   2. Transición FSM NAVIGATING → INTERACTING via pause_for_interaction()
                 Si no está en NAVIGATING: logging.info y retorno sin acción
        @CONTEXT: Callback suscripto a OttoEventBus en __init__.
                  Invocado por OttoEventBus.publish() como coroutine concurrente con gather().
                  Este método implementa el desacoplamiento Observer:
                    WakeWordDetector publica → EventBus despacha → TourOrchestrator reacciona.
                  La lógica de diálogo real se ejecuta en on_enter_interacting() (STEP 3 de FSM).
        @SECURITY: El check de estado "navigating" antes de cualquier acción de hardware previene
                   race conditions si múltiples fuentes publican INTERACTION_STARTED concurrentemente.
        @AI_CONTEXT: _pending_audio = zeros(1) porque el audio del wake word ya fue procesado
                     por WakeWordDetector. on_enter_interacting usará STT fresco para la pregunta real.

        STEP 1: Extraer transcript del payload para logging de auditoría
        STEP 2: Verificar que el estado es "navigating"; retornar sin acción si no lo es
        STEP 3: Registrar evento de auditoría INTERACTION_STARTED
        STEP 4: Setear _pending_audio y _pending_language para on_enter_interacting
        STEP 5: Ejecutar transición pause_for_interaction() via AsyncEngine
        """
        safe_data = data if isinstance(data, dict) else {}
        transcript = safe_data.get("transcript", "")
        source = safe_data.get("source", "unknown")

        LOGGER.info(
            "[Orchestrator] INTERACTION_STARTED recibido desde '%s'. "
            "transcript='%s' estado_actual='%s'",
            source, transcript[:60], self.state_id,
        )

        if self.state_id != "navigating":
            LOGGER.info(
                "[Orchestrator] INTERACTION_STARTED ignorado: estado='%s' (se requiere 'navigating').",
                self.state_id,
            )
            return

        self._schedule_audit_event(
            event_type="INTERACTION_STARTED",
            node_id=self._resolve_logical_waypoint_id(),
            payload={
                "source": source,
                "transcript_preview": transcript[:80],
                "fsm_state_before": self.state_id,
            },
        )

        self._pending_audio = np.zeros(1, dtype=np.float32)
        self._pending_language = "es"

        try:
            await self.pause_for_interaction()
        except Exception as exc:
            LOGGER.error(
                "[Orchestrator] Fallo en transición pause_for_interaction desde EventBus: %s — %s",
                type(exc).__name__, exc,
            )

    async def _on_qr_station_detected(
        self,
        event_type: EventType,
        data: object,
    ) -> None:
        """
        @TASK: Registrar y auditar una observacion de estacion QR sin alterar control de tour
        @INPUT: event_type — EventType.QR_STATION_DETECTED (filtrado por el bus)
                data — se acepta exclusivamente una instancia de QRStationDetected
        @OUTPUT: TourContext actualizado con los cuatro campos last_station_*; evento de
                 auditoria QR_STATION_DETECTED registrado. Sin mutacion de FSM, navegacion,
                 interaccion, movimiento o LLM bajo ninguna circunstancia.
        @CONTEXT: U2 — Este handler es deliberadamente pasivo. La unica autoridad de control
                  del tour sigue siendo TourOrchestrator a traves de sus transiciones FSM
                  explicitas; QR es solo observacion auditada.
        @SECURITY: Ignora payload invalido, estado cerrado o EMERGENCY sin excepcion. Solo
                   actualiza el contexto operativo cuando el estado actual es NAVIGATING.

        STEP 1: Ignorar si el payload no es QRStationDetected, si _closed o si EMERGENCY
        STEP 2: Si el estado actual no es NAVIGATING, no actualizar contexto operativo
        STEP 3: Calcular expected_station_id y matches_expected
        STEP 4: Actualizar los cuatro campos last_station_* en TourContext
        STEP 5: Registrar evento de auditoria QR_STATION_DETECTED con payload completo
        """
        if not isinstance(data, QRStationDetected):
            LOGGER.debug(
                "[Orchestrator] QR_STATION_DETECTED ignorado: payload invalido (%s).",
                type(data).__name__,
            )
            return

        if self._closed:
            return

        if self.state_id == "emergency":
            LOGGER.debug("[Orchestrator] QR_STATION_DETECTED ignorado: estado=emergency.")
            return

        if self.state_id != "navigating":
            LOGGER.info(
                "[Orchestrator] QR_STATION_DETECTED observado fuera de NAVIGATING "
                "(estado='%s'); sin actualizacion de contexto operativo.",
                self.state_id,
            )
            return

        expected_station_id = self._resolve_logical_waypoint_id()
        matches_expected = data.station_id == expected_station_id

        self._context.last_station_id = data.station_id
        self._context.last_station_qr_value = data.qr_value
        self._context.last_station_detected_at = data.detected_at.isoformat()
        self._context.last_station_matches_expected = matches_expected

        self._schedule_audit_event(
            event_type="QR_STATION_DETECTED",
            node_id=expected_station_id,
            payload={
                "station_id": data.station_id,
                "qr_value": data.qr_value,
                "detected_at": data.detected_at.isoformat(),
                "confidence_or_stability": data.confidence_or_stability,
                "source": data.source,
                "expected_station_id": expected_station_id,
                "matches_expected": matches_expected,
            },
        )

        LOGGER.info(
            "[Orchestrator] QR_STATION_DETECTED registrado. station_id=%s "
            "expected=%s matches_expected=%s",
            data.station_id, expected_station_id, matches_expected,
        )

        self._schedule_telemetry_broadcast()

    async def emergency_stop(self, reason: str = "manual") -> EmergencyStopResult:
        """
        @TASK: Activar la transicion de emergencia desde cualquier estado operativo de la FSM
        @INPUT: reason — descripcion de la causa de emergencia para diagnostico y auditoria
        @OUTPUT: EmergencyStopResult tipado describiendo exactamente que fases de la secuencia
                 fisica tuvieron exito; _context.last_error actualizado con reason (salvo en el
                 camino idempotente, donde se preserva la causa original de la primera emergencia).
        @CONTEXT: Invocable desde APIServer, señal del OS, o cualquier excepcion no recuperable.
                  trigger_emergency acepta cualquier estado origen operativo. Si la FSM YA esta en
                  EMERGENCY (estado final), este metodo es idempotente: retorna el
                  self._last_emergency_result de la primera invocacion con already_emergency=True,
                  sin reintentar trigger_emergency() ni repetir ninguna fase fisica (move/damp ya
                  fueron terminales o fallaron terminalmente en la primera llamada).
        @SECURITY: Este metodo NO ejecuta Damp() directamente; delega en on_enter_emergency que lo hace
                   como STEP 5, garantizando la secuencia correcta de cancelacion antes que hardware.
                   terminal_safe del resultado retornado es la UNICA fuente de verdad sobre exito;
                   nunca debe inferirse de self.state_id por separado. La idempotencia es necesaria
                   porque EMERGENCY es un estado final de python-statemachine: una segunda transicion
                   trigger_emergency() siempre seria rechazada, independientemente de si la primera
                   parada fue terminal_safe=True o False.

        STEP 1: Si la FSM ya esta en EMERGENCY, retornar el resultado cacheado como idempotente
        STEP 2: Registrar reason en _context.last_error y emitir LOGGER.critical para trazabilidad
        STEP 3: Ejecutar trigger_emergency via AsyncEngine para activar el callback on_enter_emergency
        STEP 4: Leer self._last_emergency_result poblado por on_enter_emergency (AsyncEngine no
                propaga el valor de retorno del callback a traves de trigger_emergency())
        """
        if self.state_id == "emergency":
            cached = self._last_emergency_result
            if cached is not None:
                LOGGER.warning(
                    "[Orchestrator] emergency_stop() idempotente: FSM ya en EMERGENCY. "
                    "Retornando resultado terminal previo sin reintentar Damp(). Razon nueva: %s",
                    reason,
                )
                return EmergencyStopResult(
                    nav_cancel_attempted=cached.nav_cancel_attempted,
                    nav_cancel_succeeded=cached.nav_cancel_succeeded,
                    zero_velocity_attempted=cached.zero_velocity_attempted,
                    zero_velocity_succeeded=cached.zero_velocity_succeeded,
                    damp_attempted=cached.damp_attempted,
                    damp_succeeded=cached.damp_succeeded,
                    terminal_safe=cached.terminal_safe,
                    already_emergency=True,
                    errors=list(cached.errors),
                )

        self._context.last_error = reason
        LOGGER.critical("[Orchestrator] EMERGENCY STOP solicitado. Razon: %s", reason)

        self._claim_interaction_terminal_outcome("EMERGENCY")
        current_task = asyncio.current_task()
        if self._interaction_task is current_task:
            self._deferred_current_interaction_task = current_task
        if (
            self._interaction_task is not None
            and not self._interaction_task.done()
            and self._interaction_task is not current_task
            and self._interaction_task is not self._deferred_current_interaction_task
        ):
            self._interaction_task.cancel()
        self._ensure_runtime_emergency_task()

        try:
            await self.trigger_emergency()
        except Exception as exc:
            LOGGER.error(
                "[Orchestrator] trigger_emergency() rechazado o fallido: %s — %s",
                type(exc).__name__, exc,
            )
            return EmergencyStopResult(errors=[f"trigger_emergency_failed:{type(exc).__name__}:{exc}"])

        result = self._last_emergency_result
        if result is None:
            # on_enter_emergency no se ejecuto (no deberia ocurrir si trigger_emergency tuvo exito).
            return EmergencyStopResult(errors=["on_enter_emergency_did_not_run"])
        return result

    async def pause_navigation(self) -> None:
        """Cancela _nav_task y solicita cancelación explícita al backend Nav2 sin cambiar el estado FSM.

        Solo válido desde NAVIGATING; lanza RuntimeError desde cualquier otro estado.
        Idempotente: si ya está pausado, _cancel_nav_task_safe() es no-op y
        cancel_navigation() es seguro sobre un backend ya inactivo.
        Preserva current_waypoint_index.
        Orden cancel_nav_task → cancel_navigation() sigue el mismo contrato que on_enter_interacting().
        """
        if self.state_id != "navigating":
            raise RuntimeError(
                f"pause_navigation() rechazado: estado actual es '{self.state_id}', se requiere 'navigating'."
            )
        await self._cancel_nav_task_safe()
        await self._nav_bridge.cancel_navigation()

    @property
    def is_navigation_paused(self) -> bool:
        """True cuando el orquestador está en NAVIGATING sin una nav task activa.

        False en IDLE, INTERACTING, EMERGENCY o con navegación activa.
        No agrega un nuevo estado a la FSM; deriva del estado observable existente.
        """
        return (
            self.state_id == "navigating"
            and (self._nav_task is None or self._nav_task.done())
        )

    def resume_navigation(self) -> None:
        """Crea una nueva _nav_task desde current_waypoint_index sin transición FSM.

        Requiere estado NAVIGATING; lanza RuntimeError desde IDLE o EMERGENCY.
        Idempotente: si ya hay una tarea activa, es un no-op.
        """
        if self.state_id != "navigating":
            raise RuntimeError(
                f"resume_navigation() rechazado: estado actual es '{self.state_id}', se requiere 'navigating'."
            )
        if self._nav_task is not None and not self._nav_task.done():
            return
        tour_id = self._context.tour_id or "unknown"
        self._nav_task = self._create_supervised_task(
            self._navigation_loop(),
            name=f"nav-loop-{tour_id}",
        )

    # ------------------------------------------------------------------
    # Callbacks on_enter de estados
    # ------------------------------------------------------------------

    async def on_enter_navigating(self) -> None:
        """
        @TASK: Iniciar el bucle de inyeccion de odometria visual como background task al entrar a NAVIGATING
        @INPUT: Sin parametros directos; opera sobre _vision_processor y _nav_bridge inyectados
        @OUTPUT: _odometry_task creada y activa consumiendo OdometryVector de VisionProcessor.pose_queue
                 solo si _vision_processor.visual_odometry_enabled es True (default); broadcast de
                 telemetria programado para notificar el nuevo estado
        @CONTEXT: Callback invocado por AsyncEngine al completar start_tour o resume_tour.
                  _navigation_loop fue creado previamente en dispatch_tour; este callback solo inicia odometria.
                  U2R1: interlock de seguridad — si visual_odometry_enabled=False (p. ej. VisionProcessor
                  configurado en modo QR-only sin calibracion real de camara), no se crea _odometry_task,
                  no se invoca get_next_estimate() ni inject_absolute_pose(). Consumidores/mocks sin esta
                  propiedad usan default True via getattr, preservando el comportamiento historico.
        @SECURITY: La tarea se crea solo si _odometry_task es None o ya termino, previniendo duplicados.

        STEP 1: Resolver visual_odometry_enabled con default True para compatibilidad con mocks/stubs
        STEP 2: Crear asyncio.Task de _odometry_injection_loop solo si esta habilitado y no existe una activa
        STEP 3: Registrar la nueva tarea en _odometry_task para su cancelacion en on_exit_navigating
        STEP 4: Programar broadcast de telemetria para notificar el ingreso a NAVIGATING
        """
        visual_odometry_enabled = bool(
            getattr(self._vision_processor, "visual_odometry_enabled", True)
        )

        if not visual_odometry_enabled:
            LOGGER.info(
                "[Orchestrator] on_enter_navigating: odometria visual deshabilitada "
                "(visual_odometry_enabled=False); _odometry_task no se crea."
            )
        elif self._odometry_task is None or self._odometry_task.done():
            self._odometry_task = asyncio.create_task(
                self._odometry_injection_loop(),
                name="odometry-injection-loop",
            )
            LOGGER.info("[Orchestrator] on_enter_navigating: Tarea de odometria iniciada.")

        if self._nav_task is None or self._nav_task.done():
            self._nav_task = self._create_supervised_task(
                self._navigation_loop(),
                name=f"nav-loop-{self._context.tour_id}",
            )
            LOGGER.info("[Orchestrator] on_enter_navigating: Tarea de navegacion iniciada.")

        self._schedule_telemetry_broadcast()

    async def on_enter_idle(self) -> None:
        """
        @TASK: Ejecutar acciones de entrada al estado IDLE al completar un tour
        @INPUT: Sin parametros
        @OUTPUT: Broadcast de telemetria programado para notificar el retorno a IDLE
        @CONTEXT: Callback invocado por AsyncEngine al completar la transicion finish_tour.
                  Estado de reposo; no activa tareas background ni comandos de hardware.
        @SECURITY: Sin acciones de hardware; operacion de solo observabilidad y telemetria.
        """
        self._schedule_telemetry_broadcast()

    async def on_exit_navigating(self) -> None:
        """
        @TASK: Cancelar el bucle de inyeccion de odometria al salir del estado NAVIGATING
        @INPUT: Sin parametros; opera sobre el atributo _odometry_task
        @OUTPUT: _odometry_task cancelada y awaited; recursos del bucle liberados; _odometry_task = None
        @CONTEXT: Callback invocado por AsyncEngine antes de ejecutar cualquier transicion de salida
                  de NAVIGATING (hacia INTERACTING, IDLE o EMERGENCY).
                  La tarea de Nav2 (_navigation_loop) se cancela por separado en los callbacks de destino.
        @SECURITY: Garantiza que no haya inyeccion de odometria activa en estados no-NAVIGATING,
                   previniendo correcciones AMCL mientras el robot esta interactuando o en emergencia.

        STEP 1: Verificar que _odometry_task existe y no ha terminado; cancelar si esta activa
        STEP 2: Await con absorcion de CancelledError (es el mecanismo normal de terminacion del bucle)
        STEP 3: Asignar _odometry_task = None para estado limpio independientemente del resultado
        """
        if self._odometry_task is not None and not self._odometry_task.done():
            self._odometry_task.cancel()
            try:
                await self._odometry_task
            except asyncio.CancelledError:
                pass

        self._odometry_task = None
        LOGGER.info("[Orchestrator] on_exit_navigating: Tarea de odometria cancelada.")

    async def on_enter_interacting(self) -> None:
        """
        @TASK: Detener el robot, ejecutar el pipeline de dialogo completo y retornar automaticamente a NAVIGATING
        @INPUT: _pending_audio — PCM float32 seteado por request_interaction() (default zeros si ausente)
                _pending_language — idioma seteado por request_interaction() (default "es" si ausente)
        @OUTPUT: Robot detenido cinematicamente; respuesta TTS procesada; _context.last_interaction
                 actualizado; evento INTERACTION_COMPLETED auditado; transicion resume_tour ejecutada
        @CONTEXT: Callback de INTERACTING invocado por AsyncEngine. Sincrono hasta que el dialogo
                  termina; bloquea el callback hasta que resume_tour es ejecutado en STEP 5.
                  La reproduccion TTS es interna al ConversationManager (fire-and-forget).
        @SECURITY: STEP 1 (cancel Nav2) debe preceder siempre a STEP 2 (velocidad cero) para evitar
                   conflicto de comandos de movimiento entre Nav2 y el HAL directo.

        STEP 1: Cancelar _nav_task y enviar cancel_navigation() al bridge para detener cinematica
        STEP 2: Enviar MotionCommand(linear_x=0, angular_z=0) como failsafe cinematico adicional
        STEP 3: Resolver tipo de interaccion del waypoint y ejecutar pipeline (scripted o libre via STT)
        STEP 4: Registrar respuesta en _context.last_interaction y programar evento de auditoria
        STEP 5: Ejecutar transicion resume_tour; ante fallo, activar emergency_stop como fallback
        """
        audio_buffer: NDArray[np.float32] = getattr(
            self, "_pending_audio", np.zeros(1, dtype=np.float32)
        )
        language: str = getattr(self, "_pending_language", "es")
        waypoint_id = self._resolve_logical_waypoint_id()

        self._schedule_telemetry_broadcast()
        LOGGER.info("[Orchestrator] on_enter_interacting: Iniciando secuencia de dialogo.")

        await self._cancel_nav_task_safe()
        await self._nav_bridge.cancel_navigation()

        try:
            await asyncio.wait_for(
                self._hardware_api.move(MotionCommand(linear_x=0.0, angular_z=0.0, duration_ms=0)),
                timeout=0.5,
            )
        except Exception as exc:
            LOGGER.warning("[Orchestrator] Fallo al enviar velocidad cero: %s", exc)

        if self._interaction_runtime is not None:
            if self._interaction_task is None or self._interaction_task.done():
                self._interaction_sequence += 1
                self._interaction_task = asyncio.create_task(
                    self._run_supervised_runtime_interaction(waypoint_id),
                    name=f"interaction-runtime-interaction:{self._interaction_sequence}",
                )
            return

        await self._run_legacy_conversation_interaction(audio_buffer, language, waypoint_id)

    async def _run_legacy_conversation_interaction(
        self,
        audio_buffer: NDArray[np.float32],
        language: str,
        waypoint_id: str,
    ) -> None:
        try:
            interaction_type = self._conversation_manager.get_waypoint_interaction_type(waypoint_id)
            self._conversation_manager.set_active_zone(waypoint_id)
            if interaction_type == "scripted":
                response = await asyncio.wait_for(
                    self._conversation_manager.process_scripted_interaction(waypoint_id),
                    timeout=self._audio_capture_timeout_s,
                )
            else:
                response = await asyncio.wait_for(
                    self._conversation_manager.process_interaction(
                        audio_buffer,
                        language=language,
                    ),
                    timeout=self._audio_capture_timeout_s,
                )
        except (TimeoutError, asyncio.TimeoutError):
            LOGGER.error(
                "[Orchestrator] Timeout de proceso de interaccion (%.1f s). "
                "Retornando a NAVIGATING sin respuesta.",
                self._audio_capture_timeout_s,
            )
            response = ConversationResponse(
                answer_text="",
                source_pipeline="timeout",
                audio_stream_ready=False,
            )
        except Exception as exc:
            LOGGER.error(
                "[Orchestrator] Excepcion en ConversationManager: %s — %s",
                type(exc).__name__,
                exc,
            )
            response = ConversationResponse(
                answer_text="",
                source_pipeline="error",
                audio_stream_ready=False,
            )

        self._context.last_interaction = response
        self._schedule_audit_event(
            event_type="INTERACTION_COMPLETED",
            node_id=waypoint_id,
            payload={
                "source_pipeline": response.source_pipeline,
                "audio_stream_ready": response.audio_stream_ready,
            },
        )
        LOGGER.info(
            "[Orchestrator] Dialogo completado. pipeline=%s swap_count=%s",
            response.source_pipeline,
            getattr(self._conversation_manager, "swap_count", "?"),
        )

        try:
            await self.resume_tour()
        except Exception as exc:
            LOGGER.error(
                "[Orchestrator] Fallo en transicion resume_tour: %s — activando emergencia.",
                exc,
            )
            await self.emergency_stop(reason=f"resume_tour fallo: {exc}")
    async def _run_supervised_runtime_interaction(self, waypoint_id: str) -> None:
        runtime = self._interaction_runtime
        if runtime is None:
            return

        # interaction_id derived from the sequence already incremented by on_enter_interacting
        interaction_id = f"interaction:{self._interaction_sequence}"
        try:
            context = InteractionContext(
                interaction_id=interaction_id,
                tour_id=self._context.tour_id,
                waypoint_id=waypoint_id,
                locale="es-AR",
                timeout_s=self._audio_capture_timeout_s,
                metadata={
                    "source": "tour_orchestrator",
                    "fsm_state": "interacting",
                },
            )
        except Exception as exc:
            self._context.last_error = f"runtime_context_invalid:{type(exc).__name__}:{exc}"
            self._interaction_terminal_outcome = None
            self._active_runtime_interaction_id = None
            LOGGER.error("[Orchestrator] Contexto de runtime invalido: %s", exc)
            return

        self._active_runtime_interaction_id = context.interaction_id
        self._interaction_terminal_outcome = "ACTIVE"
        self._runtime_stop_sent_for_interaction_id = None
        try:
            await runtime.activate(context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._context.last_error = f"runtime_activate_failed:{type(exc).__name__}:{exc}"
            self._active_runtime_interaction_id = None
            self._interaction_terminal_outcome = None
            LOGGER.error("[Orchestrator] Runtime activate() fallo: %s", exc)
            return

        try:
            await self._consume_runtime_interaction_events(runtime, context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._context.last_error = f"runtime_lifecycle_failed:{type(exc).__name__}:{exc}"
            LOGGER.error("[Orchestrator] Excepcion inesperada en lifecycle de interaccion: %s", exc)
            current = asyncio.current_task()
            if self._interaction_task is current:
                self._deferred_current_interaction_task = current
            await self.emergency_stop(reason=f"runtime_lifecycle_failed:{type(exc).__name__}:{exc}")
        finally:
            current = asyncio.current_task()
            if self._interaction_task is current:
                self._interaction_task = None
            if self._deferred_current_interaction_task is current:
                self._deferred_current_interaction_task = None

    async def _consume_runtime_interaction_events(
        self,
        runtime: InteractionRuntimePort,
        context: InteractionContext,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + context.timeout_s
        transcript_text = ""
        response_text = ""

        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    await self._fail_runtime_interaction(
                        "runtime_deadline_expired",
                        stop_runtime=True,
                    )
                    return
                try:
                    event = await runtime.next_event(timeout_s=remaining)
                except asyncio.TimeoutError:
                    await self._fail_runtime_interaction(
                        "runtime_deadline_expired",
                        stop_runtime=True,
                    )
                    return
                except asyncio.CancelledError:
                    if self._interaction_terminal_outcome not in ("EMERGENCY", "CLOSING"):
                        await self._fail_runtime_interaction(
                            "runtime_consumer_cancelled",
                            stop_runtime=True,
                        )
                    raise
                except Exception as exc:
                    await self._fail_runtime_interaction(
                        f"runtime_next_event_failed:{type(exc).__name__}:{exc}",
                        stop_runtime=True,
                    )
                    return

                if not self._runtime_event_matches_interaction(event, context.interaction_id):
                    await self._fail_runtime_interaction(
                        f"runtime_wrong_interaction_id:{event.interaction_id}",
                        stop_runtime=True,
                    )
                    return

                event_type = event.event
                if event_type in (
                    WorkerEventType.READY,
                    WorkerEventType.HEARTBEAT,
                    WorkerEventType.WAKE_WORD_CONFIRMED,
                ):
                    continue
                if (
                    event_type is WorkerEventType.COMMAND_ACCEPTED
                    and event.interaction_id is None
                ):
                    continue
                if event_type is WorkerEventType.TRANSCRIPT_READY:
                    text = event.payload.get("text")
                    if isinstance(text, str):
                        transcript_text = text
                    continue
                if event_type is WorkerEventType.RESPONSE_READY:
                    text = event.payload.get("text")
                    if isinstance(text, str):
                        response_text = text
                    continue
                if event_type in (
                    WorkerEventType.CAPTURE_STARTED,
                    WorkerEventType.PLAYBACK_STARTED,
                    WorkerEventType.COMMAND_ACCEPTED,
                ):
                    continue
                if event_type is WorkerEventType.PLAYBACK_COMPLETED:
                    await self._complete_runtime_interaction(
                        context=context,
                        transcript_text=transcript_text,
                        response_text=response_text,
                    )
                    return
                if event_type in (
                    WorkerEventType.INTERACTION_TIMEOUT,
                    WorkerEventType.CANCELLED,
                    WorkerEventType.FAILED,
                    WorkerEventType.STOPPED,
                    WorkerEventType.CLOSED,
                ):
                    await self._fail_runtime_interaction(
                        f"runtime_terminal_event:{event_type.value}",
                        stop_runtime=event_type not in (WorkerEventType.STOPPED, WorkerEventType.CLOSED),
                    )
                    return

                await self._fail_runtime_interaction(
                    f"runtime_unexpected_event:{event_type.value}",
                    stop_runtime=True,
                )
                return
        finally:
            if self._active_runtime_interaction_id == context.interaction_id:
                self._active_runtime_interaction_id = None

    def _runtime_event_matches_interaction(
        self,
        event: WorkerEventEnvelope,
        expected_interaction_id: str,
    ) -> bool:
        if event.interaction_id is None:
            return True
        return event.interaction_id == expected_interaction_id

    async def _complete_runtime_interaction(
        self,
        *,
        context: InteractionContext,
        transcript_text: str,
        response_text: str,
    ) -> None:
        if self.state_id != "interacting":
            return
        if self._interaction_terminal_outcome != "ACTIVE":
            return
        if not self._claim_interaction_terminal_outcome("COMPLETED"):
            return
        response = ConversationResponse(
            answer_text=response_text,
            source_pipeline="supervised_runtime",
            audio_stream_ready=True,
        )
        self._context.last_interaction = response
        payload = {
            "interaction_id": context.interaction_id,
            "tour_id": context.tour_id,
            "waypoint_id": context.waypoint_id,
            "source_pipeline": response.source_pipeline,
            "playback_completed": True,
        }
        if transcript_text:
            payload["transcript_preview"] = transcript_text[:80]
        await self._event_bus.publish(EventType.INTERACTION_COMPLETED, payload)
        self._schedule_audit_event(
            event_type="INTERACTION_COMPLETED",
            node_id=context.waypoint_id or self._resolve_logical_waypoint_id(),
            payload=payload,
        )
        self._active_runtime_interaction_id = None
        try:
            await self.resume_tour()
        except Exception as exc:
            LOGGER.error(
                "[Orchestrator] Fallo en transicion resume_tour tras runtime: %s",
                exc,
            )
            current = asyncio.current_task()
            if self._interaction_task is current:
                self._deferred_current_interaction_task = current
            await self.emergency_stop(reason=f"resume_tour fallo: {exc}")

    async def _fail_runtime_interaction(self, reason: str, *, stop_runtime: bool) -> None:
        if not self._claim_interaction_terminal_outcome("FAILED"):
            stop_runtime = False
        self._context.last_error = reason
        LOGGER.error("[Orchestrator] Interaccion supervisada fallida: %s", reason)
        self._schedule_audit_event(
            event_type="INTERACTION_FAILED",
            node_id=self._resolve_logical_waypoint_id(),
            payload={
                "reason": reason,
                "interaction_id": self._active_runtime_interaction_id,
                "source_pipeline": "supervised_runtime",
            },
        )
        if stop_runtime:
            await self._runtime_stop_best_effort()

    def _claim_interaction_terminal_outcome(self, outcome: str) -> bool:
        if self._interaction_terminal_outcome is None:
            self._interaction_terminal_outcome = outcome
            return True
        if self._interaction_terminal_outcome == "ACTIVE" and outcome in {
            "COMPLETED",
            "FAILED",
            "EMERGENCY",
            "CLOSING",
        }:
            self._interaction_terminal_outcome = outcome
            return True
        return self._interaction_terminal_outcome == outcome

    def _ensure_runtime_emergency_task(self) -> Optional[asyncio.Task[None]]:
        if self._interaction_runtime is None:
            return None
        task = self._interaction_emergency_task
        if task is not None:
            return task
        self._interaction_emergency_task = asyncio.create_task(
            self._runtime_emergency_stop_best_effort(),
            name="interaction-runtime-emergency-stop",
        )
        return self._interaction_emergency_task

    async def _runtime_stop_best_effort(self) -> bool:
        runtime = self._interaction_runtime
        if runtime is None:
            return True
        interaction_id = self._active_runtime_interaction_id
        task = self._interaction_stop_task
        if task is not None and task.done():
            self._retrieve_done_task_result(task, "runtime stop task")
            self._interaction_stop_task = None
            return True
        if task is None:
            if interaction_id is not None and self._runtime_stop_sent_for_interaction_id == interaction_id:
                return True
            if interaction_id is not None:
                self._runtime_stop_sent_for_interaction_id = interaction_id
            task = asyncio.create_task(
                runtime.stop(),
                name=f"interaction-runtime-stop:{interaction_id or 'unknown'}",
            )
            self._interaction_stop_task = task

        done, _ = await asyncio.wait({task}, timeout=0.5)
        if task in done:
            self._retrieve_done_task_result(task, "runtime stop task")
            self._interaction_stop_task = None
            return True

        task.cancel()
        LOGGER.warning("[Orchestrator] runtime.stop() no asento en timeout; se preserva handle para reintento.")
        self._context.last_error = "runtime stop settlement timeout"
        return False

    async def _runtime_emergency_stop_best_effort(self) -> None:
        runtime = self._interaction_runtime
        if runtime is None:
            return
        try:
            await runtime.emergency_stop()
        except InteractionRuntimeUnavailableError:
            return
        except Exception as exc:
            LOGGER.warning("[Orchestrator] runtime.emergency_stop() fallo: %s", exc)

    async def _cancel_interaction_task_safe(self) -> str:
        task = self._interaction_task
        if task is None:
            self._interaction_task = None
            return "NO_TASK"
        if task.done():
            self._retrieve_done_task_result(task, "interaction task")
            self._interaction_task = None
            return "DONE"
        if task is asyncio.current_task() or task is self._deferred_current_interaction_task:
            return "DEFERRED_CURRENT_TASK"
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=INTERACTION_TASK_SETTLE_S)
        if task in done:
            self._retrieve_done_task_result(task, "interaction task")
            self._interaction_task = None
            return "SETTLED"
        else:
            LOGGER.warning("[Orchestrator] interaction runtime task no asento en timeout.")
            self._context.last_error = "interaction task settlement timeout"
            raise RuntimeError("interaction task settlement timeout")

    async def _cancel_interaction_emergency_task_safe(self) -> str:
        task = self._interaction_emergency_task
        if task is None:
            self._interaction_emergency_task = None
            return "NO_TASK"
        if task.done():
            self._retrieve_done_task_result(task, "interaction emergency task")
            self._interaction_emergency_task = None
            return "DONE"
        if task is asyncio.current_task():
            return "DEFERRED_CURRENT_TASK"
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=INTERACTION_TASK_SETTLE_S)
        if task in done:
            self._retrieve_done_task_result(task, "interaction emergency task")
            self._interaction_emergency_task = None
            return "SETTLED"
        else:
            LOGGER.warning("[Orchestrator] runtime emergency task no asento en timeout.")
            self._context.last_error = "interaction emergency task settlement timeout"
            raise RuntimeError("interaction emergency task settlement timeout")

    def _retrieve_done_task_result(self, task: asyncio.Task[Any], label: str) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except InteractionRuntimeUnavailableError:
            return
        except Exception as exc:
            LOGGER.warning("[Orchestrator] %s finalizo con excepcion recuperada: %s", label, exc)

    async def on_enter_emergency(self) -> None:
        """
        @TASK: Ejecutar la secuencia de emergencia perentoria e irreversible ante cualquier fallo critico
        @INPUT: Sin parametros directos; _context.last_error contiene la causa registrada por emergency_stop()
        @OUTPUT: Todas las tareas background canceladas; Nav2 detenido; Damp() ejecutado en hardware;
                 VisionProcessor cerrado; eventos de auditoria y telemetria registrados;
                 self._last_emergency_result poblado con un EmergencyStopResult tipado
        @CONTEXT: Callback del estado final EMERGENCY invocado por AsyncEngine. Irreversible desde esta clase
                  (python-statemachine final=True; no hay transicion de salida automatica).
                  Todos los errores se absorben (nunca propagan, ver verificacion empirica: una excepcion
                  no absorbida aqui hace que AsyncEngine revierta la transicion a EMERGENCY) pero se
                  registran en EmergencyStopResult.errors para que el caller pueda diagnosticar la causa
                  exacta de una falla terminal sin depender de logs.
        @SECURITY: Damp() es el ULTIMO comando de locomocion (STEP 5); ninguna operacion de
                   movimiento o velocidad ocurre despues de Damp() para garantizar el estado terminal
                   seguro. Secuencia: cancel_navigation -> zero velocity -> damp -> sin locomocion.
                   terminal_safe=True requiere damp_succeeded=True como condicion necesaria; un fallo
                   de logging o de VisionProcessor.close() posterior a un damp exitoso NUNCA repite
                   comandos fisicos ni revierte terminal_safe a False.

        STEP 1: Persistir evento EMERGENCY_TRIGGERED en MissionAuditLogger con await directo
        STEP 2: Cancelar _nav_task y _odometry_task via _cancel_*_safe() sin propagar excepciones
        STEP 3: Enviar cancel_navigation() al Nav2Bridge con timeout de 1.0 s
        STEP 4: Enviar MotionCommand de velocidad cero antes de Damp() como reduccion cinematica
        STEP 5: Invocar Damp() en hardware con timeout _damp_timeout_s (comando terminal de locomocion)
        STEP 6: Invocar VisionProcessor.close() para liberar el bus USB y el thread de captura
        STEP 7: Registrar estado final del sistema via LOGGER.critical para diagnostico post-mortem
        """
        result = EmergencyStopResult()
        self._last_emergency_result = result

        LOGGER.critical(
            "[Orchestrator] EMERGENCY activado. Causa: %s",
            self._context.last_error,
        )
        self._schedule_telemetry_broadcast()

        emergency_node_id = self._resolve_logical_waypoint_id()
        emergency_payload = {
            "reason": self._context.last_error or "unknown",
            "state": self.state_id,
        }

        if self._mission_audit_logger is not None:
            try:
                await self._mission_audit_logger.log_event(
                    event_type="EMERGENCY_TRIGGERED",
                    node_id=emergency_node_id,
                    payload=emergency_payload,
                )
            except Exception as exc:
                LOGGER.error(
                    "[Orchestrator] Fallo al persistir auditoria EMERGENCY: %s", exc
                )
                result.errors.append(f"mission_audit_failed:{type(exc).__name__}:{exc}")
        else:
            LOGGER.warning(
                "[Orchestrator] MissionAuditLogger no configurado; EMERGENCY sin persistencia de auditoria."
            )

        self._claim_interaction_terminal_outcome("EMERGENCY")
        current_task = asyncio.current_task()
        if (
            self._interaction_task is not None
            and not self._interaction_task.done()
            and self._interaction_task is not current_task
            and self._interaction_task is not self._deferred_current_interaction_task
        ):
            self._interaction_task.cancel()
        self._ensure_runtime_emergency_task()

        await self._cancel_nav_task_safe()
        await self._cancel_odometry_task_safe()

        result.nav_cancel_attempted = True
        try:
            await asyncio.wait_for(
                self._nav_bridge.cancel_navigation(),
                timeout=1.0,
            )
            result.nav_cancel_succeeded = True
        except Exception as exc:
            LOGGER.error("[Orchestrator] Fallo al cancelar Nav2 en emergencia: %s", exc)
            result.errors.append(f"nav_cancel_failed:{type(exc).__name__}:{exc}")

        result.zero_velocity_attempted = True
        try:
            await asyncio.wait_for(
                self._hardware_api.move(MotionCommand(linear_x=0.0, angular_z=0.0, duration_ms=0)),
                timeout=0.5,
            )
            result.zero_velocity_succeeded = True
        except Exception as exc:
            result.errors.append(f"zero_velocity_failed:{type(exc).__name__}:{exc}")

        LOGGER.critical(
            "[Orchestrator] Emitiendo Damp() al hardware (timeout=%.1f s).",
            self._damp_timeout_s,
        )
        result.damp_attempted = True
        try:
            await asyncio.wait_for(
                self._hardware_api.damp(),
                timeout=self._damp_timeout_s,
            )
            result.damp_succeeded = True
            LOGGER.critical("[Orchestrator] Damp() ejecutado correctamente.")
        except (TimeoutError, asyncio.TimeoutError) as exc:
            LOGGER.critical(
                "[Orchestrator] TIMEOUT en Damp() durante EMERGENCY. "
                "Verificar estado mecanico manualmente."
            )
            result.errors.append(f"damp_timeout:{type(exc).__name__}:{exc}")
        except Exception as exc:
            LOGGER.critical(
                "[Orchestrator] Excepcion inesperada en Damp(): %s — %s",
                type(exc).__name__,
                exc,
            )
            result.errors.append(f"damp_failed:{type(exc).__name__}:{exc}")

        # @SECURITY: terminal_safe se fija inmediatamente despues de Damp() y nunca se revierte
        #            por fallos posteriores (logging, VisionProcessor). damp_succeeded=True es
        #            condicion necesaria; ninguna rama posterior ejecuta comandos de locomocion.
        result.terminal_safe = result.damp_succeeded

        try:
            await self._cancel_interaction_task_safe()
        except RuntimeError as exc:
            result.errors.append(f"interaction_task_settlement_timeout:{exc}")

        if self._interaction_emergency_task is not None:
            emerg_task = self._interaction_emergency_task
            done, _ = await asyncio.wait({emerg_task}, timeout=INTERACTION_TASK_SETTLE_S)
            if emerg_task in done:
                try:
                    emerg_task.result()
                except (asyncio.CancelledError, Exception) as exc:
                    result.errors.append(f"runtime_emergency_stop_failed:{type(exc).__name__}:{exc}")
                self._interaction_emergency_task = None
            else:
                emerg_task.cancel()
                result.errors.append("runtime_emergency_stop_timeout")
        self._active_runtime_interaction_id = None

        try:
            self._vision_processor.close()
            LOGGER.info("[Orchestrator] VisionProcessor cerrado en EMERGENCY.")
        except Exception as exc:
            LOGGER.error("[Orchestrator] Fallo al cerrar VisionProcessor: %s", exc)
            result.errors.append(f"vision_close_failed:{type(exc).__name__}:{exc}")

        LOGGER.critical(
            "[Orchestrator] Secuencia de EMERGENCY completada. "
            "Estado: %s | Causa: %s | terminal_safe=%s",
            self.state_id,
            self._context.last_error,
            result.terminal_safe,
        )

    # ------------------------------------------------------------------
    # Bucles de background (no bloquean el event loop)
    # ------------------------------------------------------------------

    async def _navigation_loop(self) -> None:
        """
        @TASK: Ejecutar el plan de navegacion enviando waypoints secuencialmente a AsyncNav2Bridge
        @INPUT: _context.waypoint_plan — lista de NavWaypoint del TourPlan activo
        @OUTPUT: Robot desplazado hasta cada waypoint del plan; _context.current_waypoint_index
                 actualizado en cada iteracion; evento NODE_REACHED auditado por waypoint exitoso;
                 finish_tour y TOUR_END ejecutados al completar el plan completo
        @CONTEXT: asyncio.Task creada en dispatch_tour con nombre "nav-loop-{tour_id}".
                  Cancelable en cualquier momento via _cancel_nav_task_safe() desde on_enter_interacting
                  o on_enter_emergency. CancelledError es el mecanismo normal de terminacion anticipada.
        @SECURITY: asyncio.CancelledError se re-propaga siempre para que asyncio contabilice la cancelacion.
                   Fallos de Nav2 en waypoints individuales se logean con LOGGER.error y se continua con
                   el siguiente waypoint sin abortar el tour completo.

        STEP 1: Iterar sobre el plan con enumerate; actualizar _context.current_waypoint_index en cada ciclo
        STEP 2: Resolver NavWaypoint de destino via _resolve_navigation_target (pose real o fallback)
        STEP 3: Enviar waypoint a Nav2Bridge (send_goal en modo real; navigate_to_waypoints en mock/sim)
        STEP 4: Registrar NODE_REACHED si success; LOGGER.warning si fallo sin abortar
        STEP 5: Ceder al event loop con asyncio.sleep(WAYPOINT_POLL_INTERVAL_S) entre waypoints
        STEP 6: Al completar todos los waypoints, invocar finish_tour y registrar TOUR_END
        STEP 7: Re-propagar CancelledError desde el bloque except externo para terminacion limpia
        """
        plan = self._context.waypoint_plan
        start_idx = self._context.current_waypoint_index
        if start_idx < 0:
            start_idx = 0
        elif start_idx >= len(plan):
            start_idx = len(plan)

        LOGGER.info(
            "[Orchestrator] _navigation_loop iniciado. %d waypoints, empezando desde indice %d.",
            len(plan), start_idx,
        )

        try:
            for idx in range(start_idx, len(plan)):
                waypoint = plan[idx]
                self._context.current_waypoint_index = idx
                logical_waypoint_id = self._resolve_logical_waypoint_id_by_index(idx)
                nav_target = self._resolve_navigation_target(
                    logical_waypoint_id=logical_waypoint_id,
                    fallback_waypoint=waypoint,
                )
                LOGGER.info(
                    "[Orchestrator] Navegando a waypoint %d/%d (x=%.2f y=%.2f yaw=%.2f).",
                    idx + 1, len(plan),
                    nav_target.x, nav_target.y, nav_target.yaw_rad,
                )

                try:
                    if self._robot_mode == ROBOT_MODE_REAL and hasattr(self._nav_bridge, "send_goal"):
                        success = await self._nav_bridge.send_goal(nav_target)
                    else:
                        success = await self._nav_bridge.navigate_to_waypoints([nav_target])
                except asyncio.CancelledError:
                    LOGGER.info(
                        "[Orchestrator] _navigation_loop cancelado en waypoint %d.", idx
                    )
                    raise
                except Exception as exc:
                    LOGGER.error(
                        "[Orchestrator] Nav2 fallo en waypoint %d: %s — continuando.", idx, exc
                    )
                    success = False

                if not success:
                    LOGGER.warning(
                        "[Orchestrator] Waypoint %d no completado. Nav2 result=FAILED.", idx
                    )
                else:
                    self._schedule_audit_event(
                        event_type="NODE_REACHED",
                        node_id=logical_waypoint_id,
                        payload={
                            "x": nav_target.x,
                            "y": nav_target.y,
                            "yaw_rad": nav_target.yaw_rad,
                        },
                    )

                await asyncio.sleep(WAYPOINT_POLL_INTERVAL_S)

            LOGGER.info("[Orchestrator] Plan de navegacion completado.")
            if self.state_id == "navigating":
                await self.finish_tour()
            self._schedule_audit_event(
                event_type="TOUR_END",
                node_id=self._resolve_logical_waypoint_id_by_index(len(plan) - 1),
                payload={
                    "tour_id": self._context.tour_id,
                    "waypoints_total": len(plan),
                },
            )

        except asyncio.CancelledError:
            LOGGER.info("[Orchestrator] _navigation_loop terminado por cancelacion.")
            raise

    async def _odometry_injection_loop(self) -> None:
        """
        @TASK: Consumir OdometryVector de VisionProcessor y despacharlos a AsyncNav2Bridge para correccion AMCL
        @INPUT: _vision_processor.pose_queue — asyncio.Queue[OdometryVector] alimentada por el hilo de vision
        @OUTPUT: Estimaciones de pose AMCL inyectadas continuamente en /initialpose via inject_absolute_pose();
                 sin retorno; terminacion via CancelledError desde on_exit_navigating
        @CONTEXT: asyncio.Task activa exclusivamente durante el estado NAVIGATING.
                  Si la cola esta vacia (sin AprilTags detectados), el loop cede el event loop y reintenta.
                  El timeout de 0.5 s en get_next_estimate evita bloqueo indefinido ante ausencia de tags.
        @SECURITY: CancelledError se re-propaga siempre para terminacion limpia de la tarea.
                   Excepciones de inject_absolute_pose se absorben con logging.error sin abortar el loop.

        STEP 1: Esperar el proximo OdometryVector con timeout de 0.5 s; ceder si no hay estimacion
        STEP 2: Inyectar la estimacion de pose via inject_absolute_pose con timeout ODOMETRY_INJECT_TIMEOUT_S
        STEP 3: Ceder el event loop con asyncio.sleep(0.0) tras cada inyeccion exitosa
        STEP 4: Re-propagar CancelledError en el bloque except externo para terminacion limpia
        """
        LOGGER.info("[Orchestrator] Bucle de inyeccion odometrica iniciado.")

        try:
            while True:
                odometry: Optional[OdometryVector] = await self._vision_processor.get_next_estimate(
                    timeout_s=0.5
                )

                if odometry is None:
                    await asyncio.sleep(0.0)
                    continue

                try:
                    await asyncio.wait_for(
                        self._nav_bridge.inject_absolute_pose(odometry.pose_estimate),
                        timeout=ODOMETRY_INJECT_TIMEOUT_S,
                    )
                    LOGGER.debug(
                        "[Orchestrator] Odometria inyectada: marker=%d x=%.3f y=%.3f theta=%.3f",
                        odometry.marker_id,
                        odometry.x,
                        odometry.y,
                        odometry.theta,
                    )
                except (TimeoutError, asyncio.TimeoutError):
                    LOGGER.warning("[Orchestrator] Timeout inyectando odometria AMCL.")
                except Exception as exc:
                    LOGGER.error(
                        "[Orchestrator] Fallo inyectando odometria: %s — %s",
                        type(exc).__name__, exc,
                    )

                await asyncio.sleep(0.0)

        except asyncio.CancelledError:
            LOGGER.info("[Orchestrator] Bucle de odometria terminado por cancelacion.")
            raise

    # ------------------------------------------------------------------
    # Ciclo de vida del orquestador
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """
        @TASK: Liberar todos los recursos del orquestador de forma idempotente
        @INPUT: Sin parametros
        @OUTPUT: _nav_task y _odometry_task canceladas; suscripcion a INTERACTION_STARTED
                 removida del OttoEventBus; estado interno marcado como cerrado
        @CONTEXT: Invocado desde el finally del lifespan de FastAPI. Debe ser seguro invocar
                  mas de una vez (p. ej. shutdown manual seguido del finally automatico).
        @SECURITY: Sin esta desuscripcion, OttoEventBus.get_instance() (singleton de proceso)
                   retiene una referencia a self._on_interaction_started indefinidamente,
                   filtrando el orquestador cerrado como suscriptor activo.

        STEP 1: No-op si close() ya fue invocado previamente
        STEP 2: Cancelar tareas de fondo via los helpers _safe existentes (ya idempotentes)
        STEP 3: Desuscribir _on_interaction_started usando la misma referencia de subscribe()
        STEP 4: Marcar _closed=True para que invocaciones posteriores sean no-op
        """
        if self._closed:
            return
        self._claim_interaction_terminal_outcome("CLOSING")
        active_before_cancel = (
            self._active_runtime_interaction_id is not None
            and self._interaction_terminal_outcome != "EMERGENCY"
        )
        if active_before_cancel:
            stop_settled = await self._runtime_stop_best_effort()
            if not stop_settled:
                return
        await self._cancel_interaction_task_safe()
        await self._cancel_interaction_emergency_task_safe()
        if self._interaction_stop_task is not None:
            stop_task = self._interaction_stop_task
            if stop_task.done():
                self._retrieve_done_task_result(stop_task, "runtime stop task")
                self._interaction_stop_task = None
            else:
                return
        self._active_runtime_interaction_id = None
        self._interaction_terminal_outcome = None
        self._runtime_stop_sent_for_interaction_id = None
        await self._cancel_nav_task_safe()
        await self._cancel_odometry_task_safe()
        self._event_bus.unsubscribe(EventType.INTERACTION_STARTED, self._on_interaction_started)
        self._event_bus.unsubscribe(EventType.QR_STATION_DETECTED, self._on_qr_station_detected)
        self._closed = True

    def _create_supervised_task(self, coro, name: str) -> asyncio.Task[None]:
        """Crea una asyncio.Task que activa emergency_stop ante excepciones no controladas."""
        async def _wrapper() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                LOGGER.info("[Orchestrator] Tarea de fondo %s cancelada.", name)
                raise
            except Exception as exc:
                LOGGER.error(
                    "[Orchestrator] ERROR NO CONTROLADO en tarea de fondo %s: %s",
                    name, exc, exc_info=True,
                )
                await self.emergency_stop(reason=f"Fallo critico en {name}: {exc}")

        return asyncio.create_task(_wrapper(), name=name)

    # ------------------------------------------------------------------
    # Utilidades internas de cancelacion segura
    # ------------------------------------------------------------------

    async def _cancel_nav_task_safe(self) -> None:
        """
        @TASK: Cancelar _nav_task de forma segura sin propagar CancelledError al caller
        @INPUT: Sin parametros; opera sobre el atributo de instancia _nav_task
        @OUTPUT: _nav_task.cancel() invocado; tarea awaited; _nav_task = None para estado limpio
        @CONTEXT: Utilitario invocado desde on_enter_interacting y on_enter_emergency.
                  La tarea Nav2 interna de navigate_to_waypoints se cancela por separado en Nav2Bridge.
        @SECURITY: La absorcion de CancelledError es intencional; la tarea fue cancelada explicitamente.
                   No enmascara errores reales: solo CancelledError es absorbido.

        STEP 1: Verificar que _nav_task no es None y no ha terminado; no-op si la tarea ya concluyo
        STEP 2: Invocar cancel() y await absorbiendo CancelledError
        STEP 3: Asignar _nav_task = None independientemente del resultado del await
        """
        if self._nav_task is not None and not self._nav_task.done():
            self._nav_task.cancel()
            try:
                await self._nav_task
            except asyncio.CancelledError:
                pass
        self._nav_task = None

    async def _cancel_odometry_task_safe(self) -> None:
        """
        @TASK: Cancelar _odometry_task de forma segura sin propagar CancelledError al caller
        @INPUT: Sin parametros; opera sobre el atributo de instancia _odometry_task
        @OUTPUT: _odometry_task.cancel() invocado; tarea awaited; _odometry_task = None para estado limpio
        @CONTEXT: Utilitario invocado exclusivamente desde on_enter_emergency.
                  Separado de _cancel_nav_task_safe para claridad de proposito en la secuencia de emergencia.
        @SECURITY: CancelledError es el mecanismo de terminacion normal de _odometry_injection_loop;
                   su absorcion aqui es intencional y no enmascara errores reales.

        STEP 1: Verificar que _odometry_task no es None y no ha terminado; no-op si ya concluyo
        STEP 2: Invocar cancel() y await absorbiendo CancelledError
        STEP 3: Asignar _odometry_task = None independientemente del resultado del await
        """
        if self._odometry_task is not None and not self._odometry_task.done():
            self._odometry_task.cancel()
            try:
                await self._odometry_task
            except asyncio.CancelledError:
                pass
        self._odometry_task = None

    def _resolve_logical_waypoint_id(self) -> str:
        """
        @TASK: Obtener el id logico del waypoint actualmente activo segun el indice del contexto
        @INPUT: Sin parametros; lee _context.current_waypoint_index internamente
        @OUTPUT: String con id logico del waypoint activo ("I", "1", "2", "3", "F")
        @CONTEXT: Alias delegador a _resolve_logical_waypoint_id_by_index con el indice actual.
                  Usado en callbacks de estado para identificar el nodo logico en eventos de auditoria.
        """
        index = self._context.current_waypoint_index
        return self._resolve_logical_waypoint_id_by_index(index)

    def _resolve_logical_waypoint_id_by_index(self, index: int) -> str:
        """
        @TASK: Mapear un indice numerico de waypoint a su identificador logico canonico del tour
        @INPUT: index — indice entero del waypoint en el plan (0-based)
        @OUTPUT: String con id logico del punto de interes ("I", "1", "2", "3", "F");
                 "I" para index < 0 y "F" para index fuera del rango de la lista
        @CONTEXT: Los ids logicos corresponden a los puntos de interes del guion del tour universitario.
                  Usan como clave para consultar ConversationManager y para eventos de auditoria JSON.
        """
        logical_ids = ["I", "1", "2", "3", "F"]
        if index < 0:
            return "I"
        if index >= len(logical_ids):
            return "F"
        return logical_ids[index]

    def _resolve_navigation_target(
        self,
        *,
        logical_waypoint_id: str,
        fallback_waypoint: NavWaypoint,
    ) -> NavWaypoint:
        """
        @TASK: Resolver el NavWaypoint de destino real usando la pose calibrada del guion o el fallback
        @INPUT: logical_waypoint_id — id logico del waypoint activo ("I", "1", "2", "3", "F")
                fallback_waypoint — NavWaypoint de fallback proveniente del TourPlan original
        @OUTPUT: NavWaypoint con coordenadas reales del guion si _robot_mode == "real" y pose disponible;
                 fallback_waypoint en modo mock/sim o si ConversationManager no tiene pose para el id
        @CONTEXT: En modo "real" consulta ConversationManager.get_waypoint_pose_2d() para la pose
                  calibrada del mapa real. En otros modos usa el waypoint del plan directamente.
        """
        if self._robot_mode != ROBOT_MODE_REAL:
            return fallback_waypoint
        pose_getter = getattr(self._conversation_manager, "get_waypoint_pose_2d", None)
        if not callable(pose_getter):
            return fallback_waypoint
        pose = pose_getter(logical_waypoint_id)
        if pose is None:
            return fallback_waypoint
        x, y, theta = pose
        return NavWaypoint(
            x=x,
            y=y,
            yaw_rad=theta,
            frame_id=fallback_waypoint.frame_id,
        )

    # ------------------------------------------------------------------
    # Compatibilidad con TourOrchestrator anterior (respond via ConversationManager)
    # ------------------------------------------------------------------

    async def handle_user_question(self, user_text: str) -> ConversationResponse:
        """
        @TASK: Despachar una pregunta de texto al ConversationManager como alias de compatibilidad
        @INPUT: user_text — texto ya transcripto por el caller; sin ejecucion de STT en este metodo
        @OUTPUT: ConversationResponse desde la estrategia activa (local o cloud);
                 _context.last_interaction actualizado para trazabilidad de la sesion
        @CONTEXT: Conservado para compatibilidad con el endpoint POST /question del APIServer.
                  Preferir process_interaction() cuando hay audio PCM disponible (incluye STT completo).
        @SECURITY: No ejecuta STT; el caller es responsable de la validacion y saneado del texto.

        STEP 1: Construir ConversationRequest con user_text y delegar a conversation_manager.respond()
        STEP 2: Guardar la respuesta en _context.last_interaction para trazabilidad de la sesion activa
        """
        request = ConversationRequest(user_text=user_text)
        response = await self._conversation_manager.respond(request)
        self._context.last_interaction = response
        return response

    async def build_telemetry_payload(self) -> dict[str, Any]:
        """
        @TASK: Construir el payload de telemetria con el estado actual del sistema para broadcast WebSocket
        @INPUT: Sin parametros; lee state_id, _context y llama a _read_battery_level() internamente
        @OUTPUT: dict con claves: timestamp (ISO UTC), fsm_state (uppercase), current_waypoint_id,
                 battery_level (float 0-100 o fallback 100.0), nlp_intent y nlp_source_pipeline
        @CONTEXT: Invocado por _broadcast_telemetry_state() y por websocket_telemetry para snapshot inicial.
                  battery_level se obtiene con timeout de 0.2 s para no bloquear el broadcast.
        """
        battery_level = await self._read_battery_level()
        if self._context.waypoint_plan:
            waypoint_id = self._resolve_logical_waypoint_id()
        else:
            waypoint_id = "N/A"

        nlp_intent = "UNKNOWN"
        intent_getter = getattr(self._conversation_manager, "get_waypoint_interaction_type", None)
        if callable(intent_getter) and waypoint_id != "N/A":
            try:
                nlp_intent = str(intent_getter(waypoint_id)).upper()
            except Exception:
                nlp_intent = "UNKNOWN"

        last_interaction = self._context.last_interaction
        nlp_source_pipeline = "N/A"
        nlp_answer_preview = ""
        if last_interaction is not None:
            nlp_source_pipeline = str(getattr(last_interaction, "source_pipeline", "N/A")).upper()
            nlp_answer_preview = str(getattr(last_interaction, "answer_text", ""))[:180]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fsm_state": self.state_id.upper(),
            "current_waypoint_id": waypoint_id,
            "battery_level": battery_level,
            "nlp_intent": nlp_intent,
            "nlp_source_pipeline": nlp_source_pipeline,
            "nlp_answer_preview": nlp_answer_preview,
        }

    def _schedule_telemetry_broadcast(self) -> None:
        """
        @TASK: Programar un broadcast de telemetria asíncronico como asyncio.Task fire-and-forget
        @INPUT: Sin parametros; usa _telemetry_manager internamente
        @OUTPUT: asyncio.Task "telemetry-broadcast-{state_id}" creada y registrada con done_callback;
                 no-op si _telemetry_manager es None (telemetria desactivada)
        @CONTEXT: Invocado desde todos los callbacks on_enter_* para notificar cambios de estado FSM.
                  Errores de broadcast se absorben silenciosamente via _handle_telemetry_result.
        """
        if self._telemetry_manager is None:
            return
        task = asyncio.create_task(
            self._broadcast_telemetry_state(),
            name=f"telemetry-broadcast-{self.state_id}",
        )
        task.add_done_callback(self._handle_telemetry_result)

    async def _broadcast_telemetry_state(self) -> None:
        """
        @TASK: Construir y enviar el payload de telemetria a todos los clientes WebSocket suscritos
        @INPUT: Sin parametros; delega en build_telemetry_payload() y _telemetry_manager.broadcast()
        @OUTPUT: Payload JSON enviado a todos los WebSockets activos en el pool del TelemetryManager;
                 no-op si _telemetry_manager es None
        @CONTEXT: Corrutina invocada como Task desde _schedule_telemetry_broadcast (fire-and-forget).
        """
        if self._telemetry_manager is None:
            return
        payload = await self.build_telemetry_payload()
        await self._telemetry_manager.broadcast(payload)

    async def _read_battery_level(self) -> Any:
        """
        @TASK: Leer el nivel de bateria del hardware con timeout estricto y fallback seguro a 100.0
        @INPUT: Sin parametros; accede a _hardware_api.get_state() si el metodo esta disponible
        @OUTPUT: Valor numerico del nivel de bateria (float 0-100); 100.0 como fallback ante
                 timeout, excepcion o adaptador sin soporte para get_state()
        @CONTEXT: Invocado por build_telemetry_payload(); compatible con adaptadores real/mock/sim.
                  Fallback a 100.0 evita alertas falsas de bateria baja ante adaptadores sin soporte.
        @SECURITY: asyncio.wait_for con timeout 0.2 s previene bloqueo del broadcast de telemetria.
        """
        state_reader = getattr(self._hardware_api, "get_state", None)
        if callable(state_reader):
            try:
                state = await asyncio.wait_for(state_reader(), timeout=0.2)
                if isinstance(state, dict):
                    for key in ("battery_level", "battery", "soc", "battery_soc"):
                        if key in state:
                            return state[key]
            except Exception:
                return 100.0
        return 100.0

    @staticmethod
    def _handle_telemetry_result(task: asyncio.Task[None]) -> None:
        """
        @TASK: Absorber silenciosamente excepciones de la tarea de broadcast de telemetria
        @INPUT: task — asyncio.Task completada (exito o fallo) de _broadcast_telemetry_state
        @OUTPUT: LOGGER.warning si la tarea fallo; sin re-propagacion de excepciones al caller
        @CONTEXT: done_callback registrado en _schedule_telemetry_broadcast; invocado por asyncio
                  automaticamente cuando la tarea termina. Un fallo de telemetria no es critico para el tour.
        """
        try:
            task.result()
        except Exception as exc:
            LOGGER.warning("[Orchestrator] Telemetria no enviada: %s", exc)

    def _schedule_audit_event(
        self,
        *,
        event_type: str,
        node_id: str,
        payload: dict[str, Any],
    ) -> None:
        """
        @TASK: Programar la persistencia de un evento de auditoria como asyncio.Task fire-and-forget
        @INPUT: event_type — tipo del evento (debe pertenecer a MissionAuditLogger._ALLOWED_EVENTS)
                node_id — identificador logico del waypoint o nodo activo en el momento del evento
                payload — dict con datos adicionales especificos del tipo de evento
        @OUTPUT: asyncio.Task "audit-{event_type.lower()}" creada y registrada con done_callback;
                 no-op si _mission_audit_logger es None (auditoria desactivada)
        @CONTEXT: Invocado desde dispatch_tour, on_enter_interacting, on_enter_emergency y
                  _navigation_loop. Errores de persistencia se absorben via _handle_audit_result.
        """
        if self._mission_audit_logger is None:
            return
        task = asyncio.create_task(
            self._mission_audit_logger.log_event(event_type, node_id, payload),
            name=f"audit-{event_type.lower()}",
        )
        task.add_done_callback(self._handle_audit_result)

    @staticmethod
    def _handle_audit_result(task: asyncio.Task[None]) -> None:
        """
        @TASK: Absorber silenciosamente excepciones de la tarea de persistencia de auditoria
        @INPUT: task — asyncio.Task completada (exito o fallo) de MissionAuditLogger.log_event
        @OUTPUT: LOGGER.warning si la tarea fallo; sin re-propagacion de excepciones al caller
        @CONTEXT: done_callback registrado en _schedule_audit_event; invocado por asyncio automaticamente.
                  Un fallo de auditoria no es critico para la operacion del tour en curso.
        """
        try:
            task.result()
        except Exception as exc:
            LOGGER.warning("[Orchestrator] Auditoria no persistida: %s", exc)


# ---------------------------------------------------------------------------
# Exportaciones
# ---------------------------------------------------------------------------

__all__ = [
    "TourContext",
    "TourOrchestrator",
    "TourPlan",
]
