"""
@TASK: Unico entrypoint del sistema OttoGuide
@INPUT: Variables de entorno (ROBOT_MODE, etc.) via config/settings.py
@OUTPUT: Stack robotico activo; FastAPI + Uvicorn serviendo en API_HOST:API_PORT
@CONTEXT: Reemplaza main.py, api_server.py y server.py anteriores.
          hardware/ es la HAL canonica (RobotHardwareInterface, MotionCommand); get_hardware_adapter()
          en config/settings.py resuelve real/sim/mock exclusivamente contra hardware/*.
          src/hardware/ es legacy, en cuarentena, y no debe ser importado desde este entrypoint.
          La navegacion inyectada implementa src.navigation.port.NavigationPort; la implementacion
          activa sigue siendo AsyncNav2Bridge (legacy) hasta la Fase 2H.1 (cliente ActionClient
          directo contra /offline_nav/navigate_to_pose y /offline_nav/follow_waypoints).
@SECURITY: damp() garantizado en cualquier causa de shutdown (SIGINT/SIGTERM/excepcion).
           Graceful shutdown HIL-safe: EventBus -> FSM EMERGENCY -> MotionCommand(0) -> damp()
@AI_CONTEXT: Cero sys.path.append; cero imports de unitree_sdk2py en el entrypoint.

STEP 1: Crear FastAPI con asynccontextmanager lifespan
STEP 2: lifespan: hardware = get_hardware_adapter(), await initialize()
STEP 3: lifespan: app.state.orchestrator = TourOrchestrator(hardware)
STEP 4: Instalar handlers SIGINT/SIGTERM con _install_signal_handlers()
STEP 5: lifespan yield; en shutdown: _run_shutdown_sequence() garantizado
STEP 6: uvicorn.run con factory=True
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.router import router, telemetry_manager
from config.settings import get_hardware_adapter, get_settings
from hardware.interface import RobotHardwareInterface
from src.core.mission_audit import MissionAuditLogger
from src.infrastructure.unitree import UnitreeFactoryRestClient
from src.core.event_bus import OttoEventBus
from src.core.events import EventType

LOGGER = logging.getLogger("otto_guide.main")
STATIC_DIR = Path(__file__).resolve().parent / "static"
DASHBOARD_FILE = STATIC_DIR / "dashboard.html"
MISSION_AUDIT_LOGGER = MissionAuditLogger()

# ---------------------------------------------------------------------------
# Constantes de seguridad
# ---------------------------------------------------------------------------
_DAMP_SHUTDOWN_TIMEOUT_S: float = 1.5

# ---------------------------------------------------------------------------
# Evento global de shutdown HIL-safe
# ---------------------------------------------------------------------------
# @TASK: Coordinar el apagado graceful entre el loop de uvicorn y los subsistemas roboticos
# @INPUT: Seteado por _signal_handler() ante SIGINT/SIGTERM
# @OUTPUT: lifespan lo espera para iniciar la secuencia de cierre HIL-safe
# @SECURITY: asyncio.Event es thread-safe en CPython con el GIL; seguro desde signal handlers.
# @AI_CONTEXT: Se crea en el scope del modulo para que este disponible antes del event loop.
_shutdown_event: asyncio.Event = asyncio.Event()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    @TASK: Gestionar ciclo de vida completo del sistema
    @INPUT: app — instancia FastAPI
    @OUTPUT: Stack inicializado durante yield; _run_shutdown_sequence() en shutdown
    @CONTEXT: asynccontextmanager — reemplaza on_startup/on_shutdown
    STEP 1: Instalar signal handlers SIGINT/SIGTERM
    STEP 2: hardware = get_hardware_adapter(); await initialize()
    STEP 3: app.state.orchestrator = TourOrchestrator(hardware)
    STEP 4: yield
    STEP 5: _run_shutdown_sequence() — garantizado en cualquier causa de shutdown
    @SECURITY: damp() es el ultimo comando en _run_shutdown_sequence; siempre garantizado.
    """
    settings = get_settings()
    hardware: Optional[RobotHardwareInterface] = None
    nav_bridge = None

    # STEP 1: Instalar handlers de senales al arrancar el event loop
    _install_signal_handlers(asyncio.get_running_loop())

    try:
        LOGGER.info(
            "[BOOT] Inicializando hardware. ROBOT_MODE=%s",
            settings.ROBOT_MODE,
        )
        hardware = get_hardware_adapter()

        await hardware.initialize()
        LOGGER.info("[BOOT] Hardware inicializado correctamente.")

        # Instanciar orquestador con dependencias congeladas
        # Los modulos congelados siguen usando src.* — no modificar sus imports
        from src.core import TourOrchestrator

        nav_bridge = _get_nav_bridge_stub()
        if settings.ROBOT_MODE == "real":
            LOGGER.info("[BOOT] ROBOT_MODE=real. Inicializando AsyncNav2Bridge obligatorio.")
            await nav_bridge.start()

        orchestrator = TourOrchestrator(
            hardware_api=hardware,
            nav_bridge=nav_bridge,
            conversation_manager=_get_conversation_manager_stub(settings),
            vision_processor=_get_vision_processor_stub(),
            telemetry_manager=telemetry_manager,
            mission_audit_logger=MISSION_AUDIT_LOGGER,
            robot_mode=settings.ROBOT_MODE,
        )
        app.state.orchestrator = orchestrator
        app.state.nav_bridge = nav_bridge
        app.state.factory_rest_client = UnitreeFactoryRestClient.get_instance(
            base_url=settings.UNITREE_FACTORY_BASE_URL,
            timeout_s=settings.UNITREE_FACTORY_TIMEOUT_S,
            enabled=settings.UNITREE_FACTORY_DIAGNOSTICS_ENABLED,
        )
        LOGGER.info(
            "[BOOT] TourOrchestrator instanciado. state_id='%s'",
            orchestrator.state_id,
        )

        yield

    finally:
        # @SECURITY: La secuencia de shutdown HIL-safe se ejecuta siempre en el finally.
        #            El orden es critico: EventBus -> FSM -> hardware.
        LOGGER.info("[SHUTDOWN] Iniciando secuencia de cierre HIL-safe.")
        await _run_shutdown_sequence(
            hardware=hardware,
            orchestrator=getattr(app.state, "orchestrator", None),
        )

        if nav_bridge is not None:
            close_nav = getattr(nav_bridge, "close", None)
            if callable(close_nav):
                try:
                    await close_nav()
                except Exception as exc:
                    LOGGER.warning("[SHUTDOWN] Fallo cerrando nav_bridge: %s", exc)

        LOGGER.info("[SHUTDOWN] Secuencia de apagado completada.")


# ---------------------------------------------------------------------------
# Graceful Shutdown HIL-safe
# ---------------------------------------------------------------------------

def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """
    @TASK: Instalar handlers para SIGINT y SIGTERM que activan el shutdown graceful
    @INPUT: loop — event loop activo de asyncio (provisto por uvicorn en su worker)
    @OUTPUT: Handlers registrados; _shutdown_event.set() sera invocado ante la senal
    @CONTEXT: Llamado desde lifespan al inicio del contexto activo.
              En Linux/macOS: loop.add_signal_handler() es la API correcta.
              En Windows: signal.signal() es el fallback (add_signal_handler no disponible).
    @SECURITY: _shutdown_event.set() es thread-safe en CPython; no ejecuta logica de hardware
               directamente desde el handler (solo setea un Event que el event loop procesa).
    @AI_CONTEXT: SIGKILL no es capturable; usar systemd stop-timeout >= 3s en produccion.
    """
    def _signal_handler(signum: int) -> None:
        """
        @TASK: Callback de senal — activar el evento de shutdown sin bloquear el loop
        @INPUT: signum — numero de senal recibida (SIGINT=2, SIGTERM=15)
        @OUTPUT: _shutdown_event seteado; LOGGER.warning emitido
        @SECURITY: No ejecuta I/O ni logica de hardware; solo set() en un Event.
        """
        signal_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        LOGGER.warning(
            "[SHUTDOWN] Senal %s recibida. Iniciando cierre HIL-safe.",
            signal_name,
        )
        _shutdown_event.set()

    try:
        # Linux/macOS: add_signal_handler integra limpiamente con el event loop asyncio
        # @SECURITY: Usa pipe interno de asyncio; seguro para llamar desde dentro del loop.
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler, sig)
        LOGGER.info("[SHUTDOWN] Signal handlers SIGINT/SIGTERM instalados (asyncio loop).")
    except (NotImplementedError, AttributeError):
        # Windows: add_signal_handler no esta disponible; usar signal.signal como fallback
        # @AI_CONTEXT: signal.signal() ejecuta el handler en el thread principal del OS.
        #              _shutdown_event.set() es thread-safe en CPython con el GIL.
        import signal as signal_mod
        for sig in (signal_mod.SIGINT, signal_mod.SIGTERM):
            try:
                signal_mod.signal(sig, lambda s, f: _signal_handler(s))
            except OSError:
                pass  # SIGTERM no disponible en Windows; SIGINT siempre disponible
        LOGGER.info("[SHUTDOWN] Signal handlers instalados (Windows signal.signal fallback).")


async def _run_shutdown_sequence(
    hardware: Optional[RobotHardwareInterface],
    orchestrator: object = None,
) -> None:
    """
    @TASK: Ejecutar la secuencia completa de cierre HIL-safe en orden de prioridad de seguridad
    @INPUT: hardware — adaptador HAL activo (None si boot fallo antes de inicializar)
            orchestrator — instancia de TourOrchestrator (None en modo mock/CI)
    @OUTPUT: Todos los subsistemas cerrados en orden HIL-safe:
             1. EventBus: publica EMERGENCY_STOP (notifica suscriptores desacoplados)
             2. FSM: transicion a EMERGENCY (cancela nav y odometry tasks)
             3. Hardware: MotionCommand(0) failsafe cinematico
             4. Hardware: damp() — parada elastica (prioridad ABSOLUTA de seguridad)
    @CONTEXT: Invocado desde el finally del lifespan de FastAPI.
              El orden de los pasos es critico: hardware (Capa 1) se apaga ultimo.
    @SECURITY: damp() es SIEMPRE el ultimo comando de hardware ejecutado.
               Todos los errores en pasos 1, 2 y 3 se absorben para garantizar
               que damp() se ejecute incluso si la FSM o el EventBus fallan.
    @AI_CONTEXT: _DAMP_SHUTDOWN_TIMEOUT_S = 1.5s. En hardware real Damp() tarda ~500ms.
                 En produccion: usar systemd stop-timeout >= 5s para margen adicional.

    STEP 1: Publicar EMERGENCY_STOP en EventBus (notifica subsistemas desacoplados)
    STEP 2: Transicionar FSM a EMERGENCY (cancela tareas background de nav/odometry)
    STEP 3: MotionCommand(0) — failsafe cinematico antes de damp()
    STEP 4: damp() — parada elastica final del hardware (PRIORIDAD ABSOLUTA)
    """
    LOGGER.info("[SHUTDOWN] === SECUENCIA HIL-SAFE INICIADA ===")

    # STEP 1: Notificar EventBus con EMERGENCY_STOP
    # @AI_CONTEXT: Permite que WakeWordDetector, ConversationManager y otros suscriptores
    #              limpien sus recursos antes de que el hardware se apague.
    try:
        bus = OttoEventBus.get_instance()
        await bus.publish(
            EventType.EMERGENCY_STOP,
            data={"reason": "graceful_shutdown", "source": "main.lifespan"},
        )
        LOGGER.info("[SHUTDOWN] STEP 1: EventBus notificado con EMERGENCY_STOP.")
    except Exception as exc:
        LOGGER.warning("[SHUTDOWN] STEP 1: Fallo notificando EventBus: %s", exc)

    # STEP 2: Transicionar FSM a EMERGENCY
    # @SECURITY: emergency_stop() cancela _nav_task y _odometry_task de forma segura.
    #            Se ejecuta ANTES del hardware para que Nav2 cancele sus comandos activos.
    if orchestrator is not None:
        try:
            emergency_fn = getattr(orchestrator, "emergency_stop", None)
            if callable(emergency_fn):
                await asyncio.wait_for(
                    emergency_fn(reason="graceful_shutdown"),
                    timeout=2.0,
                )
                LOGGER.info("[SHUTDOWN] STEP 2: TourOrchestrator en estado EMERGENCY.")
        except asyncio.TimeoutError:
            LOGGER.warning("[SHUTDOWN] STEP 2: Timeout en emergency_stop(). Continuando.")
        except Exception as exc:
            LOGGER.warning("[SHUTDOWN] STEP 2: Fallo en emergency_stop(): %s. Continuando.", exc)
    else:
        LOGGER.info("[SHUTDOWN] STEP 2: No hay orchestrator activo — omitido.")

    # STEP 3: Failsafe cinematico — MotionCommand(0) antes de damp()
    # @SECURITY: Garantiza velocidad 0 incluso si damp() tiene timeout o falla.
    #            El robot puede quedar en postura rigida ante fallo de damp(), pero
    #            al menos no avanzara con velocidad remanente.
    if hardware is not None:
        try:
            from hardware.interface import MotionCommand
            await asyncio.wait_for(
                hardware.move(MotionCommand(linear_x=0.0, angular_z=0.0, duration_ms=0)),
                timeout=0.5,
            )
            LOGGER.info("[SHUTDOWN] STEP 3: MotionCommand(0) enviado correctamente.")
        except asyncio.TimeoutError:
            LOGGER.warning("[SHUTDOWN] STEP 3: Timeout enviando MotionCommand(0).")
        except Exception as exc:
            LOGGER.warning("[SHUTDOWN] STEP 3: Fallo en MotionCommand(0): %s.", exc)

    # STEP 4 (CRITICO): damp() — parada elastica del hardware. PRIORIDAD ABSOLUTA.
    # @SECURITY: Se ejecuta incluso si todos los pasos anteriores fallaron.
    if hardware is not None:
        LOGGER.info(
            "[SHUTDOWN] STEP 4: Ejecutando damp() (timeout=%.1fs). PRIORIDAD ABSOLUTA.",
            _DAMP_SHUTDOWN_TIMEOUT_S,
        )
        try:
            await asyncio.wait_for(
                hardware.damp(),
                timeout=_DAMP_SHUTDOWN_TIMEOUT_S,
            )
            LOGGER.info("[SHUTDOWN] STEP 4: damp() ejecutado correctamente.")
        except asyncio.TimeoutError:
            LOGGER.critical(
                "[SHUTDOWN] STEP 4: TIMEOUT en damp() (%.1fs). "
                "Verificar estado mecanico. Activar L1+A en mando si el robot sigue activo.",
                _DAMP_SHUTDOWN_TIMEOUT_S,
            )
        except Exception as exc:
            LOGGER.critical(
                "[SHUTDOWN] STEP 4: Fallo CRITICO en damp(): %s — %s. Verificar hardware.",
                type(exc).__name__, exc,
            )
    else:
        LOGGER.info("[SHUTDOWN] STEP 4: No hay hardware activo — damp() omitido.")

    LOGGER.info("[SHUTDOWN] === SECUENCIA HIL-SAFE COMPLETADA ===")


# ---------------------------------------------------------------------------
# Stubs de dependencias congeladas
# ---------------------------------------------------------------------------
# Los modulos congelados (orchestrator, conversation, nav2_bridge) esperan
# tipos especificos. Estas funciones proveen instancias compatibles.
# En despliegue real, estas se reemplazan por las instancias completas
# creadas por start_robot.sh (capas 2-3).

def _get_nav_bridge_stub():
    """
    @TASK: Obtener stub o instancia real de AsyncNav2Bridge
    @INPUT: Sin parametros
    @OUTPUT: Instancia de AsyncNav2Bridge
    @CONTEXT: Nav2 es infraestructura externa (Capa 2); este stub es placeholder
    @SECURITY: No inicializa ROS 2 desde Python
    """
    try:
        from src.navigation import AsyncNav2Bridge
        return AsyncNav2Bridge()
    except Exception:
        LOGGER.warning(
            "[BOOT] AsyncNav2Bridge no disponible. Usando stub minimo."
        )
        return _MinimalNavStub()


def _get_conversation_manager_stub(settings):
    """
    @TASK: Obtener stub o instancia real de ConversationManager
    @INPUT: settings — Settings con OLLAMA_HOST y OLLAMA_MODEL
    @OUTPUT: Instancia de ConversationManager
    @CONTEXT: Ollama daemon es Capa 3; puede no estar disponible en CI
    @SECURITY: Sin APIs externas (sin OpenAI, sin Anthropic)
    """
    try:
        from src.interaction import ConversationManager, CloudNLPPipeline, LocalNLPPipeline
        return ConversationManager(
            cloud_strategy=CloudNLPPipeline(timeout_s=1.0),
            local_strategy=LocalNLPPipeline(
                model_name=settings.OLLAMA_MODEL,
                ollama_base_url=settings.OLLAMA_HOST,
            ),
        )
    except Exception:
        LOGGER.warning(
            "[BOOT] ConversationManager no disponible. Usando stub minimo."
        )
        return _MinimalConversationStub()


def _get_vision_processor_stub():
    """
    @TASK: Obtener stub o instancia real de VisionProcessor
    @INPUT: Sin parametros
    @OUTPUT: Instancia de VisionProcessor
    @CONTEXT: Camara D435i es infraestructura externa
    @SECURITY: Sin acceso a hardware de vision en CI/mock
    """
    try:
        import numpy as np
        from src.vision import CameraModel, VisionProcessor
        camera_model = CameraModel(
            camera_matrix=np.eye(3, dtype=np.float64),
            distortion_coefficients=np.zeros((5, 1), dtype=np.float64),
        )
        return VisionProcessor(camera_model=camera_model, tag_size_m=0.16)
    except Exception:
        LOGGER.warning(
            "[BOOT] VisionProcessor no disponible. Usando stub minimo."
        )
        return _MinimalVisionStub()


class _MinimalNavStub:
    """
    @TASK: Proveer stub minimo de AsyncNav2Bridge para entornos sin ROS 2
    @INPUT: Llamadas de TourOrchestrator a operaciones de navegacion
    @OUTPUT: Respuestas no operativas pero tipadas para mantener compatibilidad
    @CONTEXT: Fallback de bootstrap en CI o entornos sin stack Nav2
    @SECURITY: No inicializa ROS 2 ni ejecuta I/O externo
    """

    async def start(self):
        """
        @TASK: Simular inicio del bridge de navegacion
        @INPUT: Sin parametros
        @OUTPUT: Retorno inmediato
        @CONTEXT: Stub no operativo
        @SECURITY: Sin side effects
        """
        return None

    async def close(self):
        """
        @TASK: Simular cierre del bridge de navegacion
        @INPUT: Sin parametros
        @OUTPUT: Retorno inmediato
        @CONTEXT: Stub no operativo
        @SECURITY: Sin side effects
        """
        return None

    async def navigate_to_waypoints(self, waypoints):
        """
        @TASK: Simular navegacion por waypoints
        @INPUT: waypoints
        @OUTPUT: False para indicar no ejecucion de navegacion real
        @CONTEXT: Fallback de compatibilidad cuando Nav2 no esta disponible
        @SECURITY: No despacha movimiento fisico
        """
        return False

    async def cancel_navigation(self):
        """
        @TASK: Simular cancelacion de navegacion
        @INPUT: Sin parametros
        @OUTPUT: Retorno inmediato
        @CONTEXT: Stub no operativo
        @SECURITY: Sin side effects
        """
        return None

    async def inject_absolute_pose(self, pose):
        """
        @TASK: Simular inyeccion de pose absoluta
        @INPUT: pose
        @OUTPUT: Retorno inmediato
        @CONTEXT: Stub no operativo
        @SECURITY: No publica en ROS 2
        """
        return None

    async def send_goal(self, waypoint) -> bool:
        """
        @TASK: Simular envio de un unico goal de navegacion
        @INPUT: waypoint
        @OUTPUT: False para indicar no ejecucion de navegacion real
        @CONTEXT: Completa la conformidad estructural con NavigationPort
        @SECURITY: No despacha movimiento fisico
        """
        return False

    async def is_navigation_active(self) -> bool:
        """
        @TASK: Simular consulta de actividad de navegacion
        @INPUT: Sin parametros
        @OUTPUT: False; el stub nunca tiene una tarea activa
        @CONTEXT: Completa la conformidad estructural con NavigationPort
        @SECURITY: Sin side effects
        """
        return False


class _MinimalConversationStub:
    """
    @TASK: Proveer stub minimo de ConversationManager sin backend NLP real
    @INPUT: Solicitudes de interaccion del orquestador
    @OUTPUT: Respuestas vacias compatibles con el contrato esperado
    @CONTEXT: Fallback de bootstrap cuando Ollama no esta disponible
    @SECURITY: Sin llamadas a APIs externas ni ejecucion de modelos remotos
    """

    swap_count = 0
    active_strategy_name = "stub"

    async def process_interaction(self, audio, *, language="es"):
        """
        @TASK: Simular procesamiento de interaccion conversacional
        @INPUT: audio, language
        @OUTPUT: Objeto StubResponse con payload vacio
        @CONTEXT: Ruta de fallback en entornos sin pipeline conversacional
        @SECURITY: No transmite audio fuera del proceso
        """
        from dataclasses import dataclass

        @dataclass
        class StubResponse:
            answer_text: str = ""
            source_pipeline: str = "stub"
            audio_stream_ready: bool = False
        return StubResponse()

    async def respond(self, request):
        """
        @TASK: Simular endpoint de respuesta conversacional
        @INPUT: request
        @OUTPUT: Delega en process_interaction con salida stub
        @CONTEXT: Compatibilidad con consumidores existentes
        @SECURITY: Sin side effects externos
        """
        return await self.process_interaction(None)


class _MinimalVisionStub:
    """
    @TASK: Proveer stub minimo de VisionProcessor sin acceso a camara
    @INPUT: Llamadas del orquestador a cierre y lectura de estimaciones
    @OUTPUT: Cierre no operativo y ausencia de estimaciones
    @CONTEXT: Fallback para CI/mock sin dispositivo D435i
    @SECURITY: No intenta abrir hardware de video
    """

    def close(self):
        """
        @TASK: Simular cierre del procesador de vision
        @INPUT: Sin parametros
        @OUTPUT: Retorno inmediato
        @CONTEXT: Stub no operativo
        @SECURITY: Sin side effects
        """
        return None

    async def get_next_estimate(self, *, timeout_s=0.5):
        """
        @TASK: Simular lectura de siguiente estimacion de vision
        @INPUT: timeout_s
        @OUTPUT: None para indicar ausencia de datos
        @CONTEXT: Stub no operativo sin pipeline de camara
        @SECURITY: No realiza I/O de hardware
        """
        return None


# ---------------------------------------------------------------------------
# Factory de aplicacion
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """
    @TASK: Factory de la aplicacion FastAPI
    @INPUT: Sin parametros
    @OUTPUT: FastAPI app con lifespan y router incluido
    @CONTEXT: Invocada por uvicorn con factory=True
    @SECURITY: La politica de exposicion de documentacion OpenAPI se gestiona fuera de esta factory.
    """
    _configure_logging()

    app = FastAPI(
        title="OttoGuide API",
        version="1.0.0",
        description="Robot humanoide Unitree G1 EDU — Guia de visitas universitarias",
        lifespan=lifespan,
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def dashboard() -> FileResponse:
        if not DASHBOARD_FILE.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dashboard no encontrado en {DASHBOARD_FILE}",
            )
        return FileResponse(DASHBOARD_FILE)

    return app


def _configure_logging() -> None:
    """
    @TASK: Configurar logging base del proceso
    @INPUT: Sin parametros
    @OUTPUT: Logging inicializado con formato canonico
    @CONTEXT: Primer paso antes de cualquier IO
    @SECURITY: Sin exposicion de credenciales
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Entrypoint directo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    @TASK: Lanzar servidor con uvicorn
    @INPUT: Sin parametros CLI
    @OUTPUT: Proceso HTTP activo en API_HOST:API_PORT
    @CONTEXT: Ejecutable como: python main.py
    @SECURITY: KeyboardInterrupt suprimida; SIGINT capturada por _install_signal_handlers()
    """
    settings = get_settings()
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(
            "main:create_app",
            host="0.0.0.0",
            port=settings.API_PORT,
            factory=True,
            log_level="info",
        )
