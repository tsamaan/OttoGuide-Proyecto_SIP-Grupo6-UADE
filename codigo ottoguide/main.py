"""
@TASK: Unico entrypoint del sistema OttoGuide
@INPUT: Variables de entorno (ROBOT_MODE, etc.) via config/settings.py
@OUTPUT: Stack robotico activo; FastAPI + Uvicorn serviendo en API_HOST:API_PORT
@CONTEXT: Reemplaza main.py, api_server.py y server.py anteriores.
          hardware/ es la HAL canonica (RobotHardwareInterface, MotionCommand); get_hardware_adapter()
          en config/settings.py resuelve real/sim/mock exclusivamente contra hardware/*.
          src/hardware/ es legacy, en cuarentena, y no debe ser importado desde este entrypoint.
          La navegacion inyectada implementa src.navigation.port.NavigationPort. Fase 2H.2:
          el backend concreto (AsyncNav2Bridge legacy, DirectNav2ActionBridge, o un stub no
          operativo) se selecciona explicitamente via NAVIGATION_BACKEND/ROBOT_MODE en
          config/settings.py (_resolve_navigation_backend/_build_navigation_bridge en este
          archivo), nunca con un fallback silencioso a stub. DirectNav2ActionBridge sigue
          siendo offline-only (sandbox /offline_nav/*); contra hardware real esta bloqueado
          por el interlock NAVIGATION_DIRECT_REAL_ENABLED (cerrado por defecto).
@SECURITY: damp() garantizado en cualquier causa de shutdown (SIGINT/SIGTERM/excepcion).
           Graceful shutdown HIL-safe: EventBus -> FSM EMERGENCY -> MotionCommand(0) -> damp()
           -> close() del backend de navegacion (nunca silenciado).
@AI_CONTEXT: Cero sys.path.append; cero imports de unitree_sdk2py en el entrypoint.

STEP 1: Crear FastAPI con asynccontextmanager lifespan
STEP 2: lifespan: resolver backend de navegacion, validar config, chequear interlock,
        construir el bridge (sin iniciar ROS) ANTES de tocar hardware
STEP 3: lifespan: hardware = get_hardware_adapter(), await initialize(), await nav_bridge.start()
STEP 4: lifespan: app.state.orchestrator = TourOrchestrator(hardware, nav_bridge)
STEP 5: Instalar handlers SIGINT/SIGTERM con _install_signal_handlers()
STEP 6: lifespan yield; en shutdown: _run_shutdown_sequence() garantizado, luego close()
STEP 7: uvicorn.run con factory=True
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

from hardware.interface import RobotHardwareInterface

LOGGER = logging.getLogger("otto_guide.main")
STATIC_DIR = Path(__file__).resolve().parent / "static"
DASHBOARD_FILE = STATIC_DIR / "dashboard.html"

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
# Thin wrappers — lazy imports so main.py is importable without pydantic_settings.
# Exposed at module scope so tests can patch self.main.get_settings / get_hardware_adapter.
# ---------------------------------------------------------------------------

def get_settings():
    from config.settings import get_settings as _fn
    return _fn()


def _clear_settings_cache():
    try:
        from config.settings import get_settings as _fn
        if hasattr(_fn, "cache_clear"):
            _fn.cache_clear()
    except Exception:
        pass


get_settings.cache_clear = _clear_settings_cache


def get_hardware_adapter():
    from config.settings import get_hardware_adapter as _fn
    return _fn()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    @TASK: Gestionar ciclo de vida completo del sistema
    @INPUT: app — instancia FastAPI
    @OUTPUT: Stack inicializado durante yield; _run_shutdown_sequence() en shutdown
    @CONTEXT: asynccontextmanager — reemplaza on_startup/on_shutdown.
              Fase 2H.2: el backend de navegacion se resuelve y construye ANTES de tocar
              hardware/ROS (ver _resolve_navigation_backend/_check_direct_real_interlock/
              _build_navigation_bridge), nunca con un fallback silencioso a un stub.
    STEP 1: Instalar signal handlers SIGINT/SIGTERM
    STEP 2: Validar config de navegacion, resolver backend, chequear interlock, construir bridge
    STEP 3: hardware = get_hardware_adapter(); await initialize(); await nav_bridge.start()
    STEP 4: app.state.orchestrator = TourOrchestrator(hardware, nav_bridge)
    STEP 5: yield
    STEP 6: _run_shutdown_sequence() — garantizado en cualquier causa de shutdown; luego
            intento de cierre del bridge (parcial o completo), nunca silenciado.
    @SECURITY: damp() es el ultimo comando en _run_shutdown_sequence; siempre garantizado.
               Un fallo de arranque del backend de navegacion nunca degrada a un stub.
    """
    settings = get_settings()
    hardware: Optional[RobotHardwareInterface] = None
    nav_bridge = None
    resolved_backend: Optional[str] = None
    reached_yield = False
    station_trigger_coordinator = None

    # STEP 1: Instalar handlers de senales al arrancar el event loop
    _install_signal_handlers(asyncio.get_running_loop())

    app.state.navigation_backend_requested = settings.NAVIGATION_BACKEND
    app.state.navigation_backend_resolved = None
    app.state.navigation_started = False
    app.state.navigation_stub_tours_allowed = settings.NAVIGATION_ALLOW_STUB_TOURS
    app.state.navigation_startup_error = None
    app.state.navigation_shutdown_error = None
    app.state.nav_bridge = None
    app.state.station_trigger = None

    try:
        try:
            # STEP 2: Config, resolucion de backend e interlock — antes de tocar hardware/ROS
            settings.validate_navigation_config()
            settings.validate_web_ui_config()
            # getattr defensivo: compatibilidad con test doubles preexistentes (SimpleNamespace
            # en tests/unit/test_navigation_runtime_selection.py) que no implementan este metodo
            # nuevo de U2. config.settings.Settings real SIEMPRE lo expone y lo ejecuta; esto no
            # degrada el fail-closed productivo, solo evita romper fakes parciales fuera de scope.
            validate_qr_station_config = getattr(settings, "validate_qr_station_config", None)
            if validate_qr_station_config is not None:
                if not callable(validate_qr_station_config):
                    raise TypeError(
                        "QR_STATION_CONFIG_VALIDATOR_INVALID:validate_qr_station_config_not_callable"
                    )
                validate_qr_station_config()

            resolved_backend = _resolve_navigation_backend(settings)
            app.state.navigation_backend_resolved = resolved_backend
            _check_direct_real_interlock(settings, resolved_backend)

            nav_bridge = _build_navigation_bridge(settings, resolved_backend)
            app.state.nav_bridge = nav_bridge

            LOGGER.info(
                "[BOOT] Inicializando hardware. ROBOT_MODE=%s navigation_backend=%s",
                settings.ROBOT_MODE, resolved_backend,
            )
            hardware = get_hardware_adapter()
            await hardware.initialize()
            LOGGER.info("[BOOT] Hardware inicializado correctamente.")

            try:
                await nav_bridge.start()
            except Exception as exc:
                raise RuntimeError(
                    f"NAVIGATION_BACKEND_START_FAILED:{resolved_backend}:{exc}"
                ) from exc

            app.state.navigation_started = resolved_backend in ("legacy", "direct")
            LOGGER.info(
                "[BOOT] Backend de navegacion '%s' iniciado. navigation_started=%s",
                resolved_backend, app.state.navigation_started,
            )

            # Instanciar orquestador con dependencias congeladas
            # Los modulos congelados siguen usando src.* — no modificar sus imports
            from api.router import telemetry_manager
            from src.core import TourOrchestrator
            from src.core.event_bus import OttoEventBus
            from src.core.mission_audit import MissionAuditLogger
            from src.infrastructure.unitree import UnitreeFactoryRestClient
            mission_audit_logger = MissionAuditLogger()

            shared_event_bus = OttoEventBus.get_instance()
            vision_processor = _build_vision_processor(settings)

            orchestrator = TourOrchestrator(
                hardware_api=hardware,
                nav_bridge=nav_bridge,
                conversation_manager=_get_conversation_manager_stub(settings),
                vision_processor=vision_processor,
                telemetry_manager=telemetry_manager,
                mission_audit_logger=mission_audit_logger,
                robot_mode=settings.ROBOT_MODE,
                event_bus=shared_event_bus,
            )
            app.state.orchestrator = orchestrator
            await orchestrator.activate_initial_state()

            # QR Station Trigger (U2) — opcional; fail-closed si esta habilitado y algo falla
            # getattr defensivo: compatibilidad con test doubles preexistentes (ver
            # _build_vision_processor); config.settings.Settings real siempre lo expone.
            if getattr(settings, "QR_STATION_TRIGGER_ENABLED", False):
                try:
                    vision_processor.start(asyncio.get_running_loop())

                    from src.core.station_trigger_coordinator import StationTriggerCoordinator
                    from src.vision import VisionStationTrigger

                    vision_station_trigger = VisionStationTrigger(vision_processor)
                    station_trigger_coordinator = StationTriggerCoordinator(
                        station_trigger=vision_station_trigger,
                        event_bus=shared_event_bus,
                    )
                    await station_trigger_coordinator.start()
                    app.state.station_trigger = vision_station_trigger
                    LOGGER.info("[BOOT] QR Station Trigger iniciado.")
                except Exception as exc:
                    raise RuntimeError(f"QR_STATION_TRIGGER_START_FAILED:{exc}") from exc

            # CHANGE F: Track conversation runtime degradation
            _cm_boot = (
                getattr(orchestrator, "conversation_manager", None)
                or getattr(orchestrator, "_conversation_manager", None)
            )
            app.state.conversation_runtime_degraded = (
                _cm_boot is None or not hasattr(_cm_boot, "load_script_from_file")
            )
            app.state.conversation_runtime_error = getattr(_cm_boot, "degradation_error", None)
            if app.state.conversation_runtime_degraded:
                LOGGER.warning(
                    "[BOOT] ConversationManager degradado (stub activo). "
                    "CONVERSATION_RUNTIME_DEGRADED causa=%s",
                    app.state.conversation_runtime_error,
                )

            # CHANGE E: Cargar guion al arrancar
            app.state.script_loaded = False
            app.state.script_version = None
            app.state.script_waypoint_count = 0
            app.state.script_load_error = None
            _script_path = Path(__file__).resolve().parent / "data" / "mvp_tour_script.json"
            if _cm_boot is not None and hasattr(_cm_boot, "load_script_from_file"):
                if _script_path.exists():
                    try:
                        _boot_loop = asyncio.get_running_loop()
                        await _boot_loop.run_in_executor(None, _cm_boot.load_script_from_file, _script_path)
                        _loaded = getattr(_cm_boot, "loaded_script", None)
                        app.state.script_loaded = True
                        app.state.script_version = getattr(_loaded, "version", None)
                        app.state.script_waypoint_count = len(getattr(_loaded, "waypoints", []))
                        LOGGER.info(
                            "[BOOT] Script cargado. version='%s' waypoints=%d",
                            app.state.script_version,
                            app.state.script_waypoint_count,
                        )
                    except Exception as exc:
                        app.state.script_load_error = f"{type(exc).__name__}: {exc}"
                        if settings.ROBOT_MODE == "real":
                            raise RuntimeError(f"SCRIPT_LOAD_FAILED:{exc}") from exc
                        LOGGER.warning("[BOOT] Script no cargado (modo=%s): %s", settings.ROBOT_MODE, exc)
                elif settings.ROBOT_MODE == "real":
                    app.state.script_load_error = f"SCRIPT_NOT_FOUND:{_script_path}"
                    raise RuntimeError(f"SCRIPT_NOT_FOUND:{_script_path}")
                else:
                    app.state.script_load_error = f"SCRIPT_NOT_FOUND:{_script_path}"
                    LOGGER.info("[BOOT] Script ausente (%s); modo=%s — degradado aceptable.", _script_path, settings.ROBOT_MODE)

            app.state.factory_rest_client = UnitreeFactoryRestClient.get_instance(
                base_url=settings.UNITREE_FACTORY_BASE_URL,
                timeout_s=settings.UNITREE_FACTORY_TIMEOUT_S,
                enabled=settings.UNITREE_FACTORY_DIAGNOSTICS_ENABLED,
            )
            LOGGER.info(
                "[BOOT] TourOrchestrator instanciado. state_id='%s'",
                orchestrator.state_id,
            )

            reached_yield = True
            yield
        except Exception as exc:
            if not reached_yield:
                app.state.navigation_startup_error = str(exc)
                LOGGER.critical("[BOOT] Fallo critico de arranque: %s", exc)
            raise

    finally:
        # @SECURITY: La secuencia de shutdown HIL-safe se ejecuta siempre en el finally.
        #            El orden es critico: EventBus -> FSM -> hardware -> bridge de navegacion.
        LOGGER.info("[SHUTDOWN] Iniciando secuencia de cierre HIL-safe.")
        _orch_shutdown = getattr(app.state, "orchestrator", None)
        await _run_shutdown_sequence(
            hardware=hardware,
            orchestrator=_orch_shutdown,
        )

        # U2: cerrar StationTriggerCoordinator antes de continuar con el cierre existente
        if station_trigger_coordinator is not None:
            try:
                await station_trigger_coordinator.close()
                LOGGER.info("[SHUTDOWN] StationTriggerCoordinator cerrado.")
            except Exception as exc:
                LOGGER.warning("[SHUTDOWN] StationTriggerCoordinator.close() fallido: %s", exc)

        # CHANGE A: Close orchestrator + ConversationManager (extracted helper; ver
        #           _close_orchestrator_and_conversation_manager para el contrato productivo
        #           ejercido directamente por tests/unit/test_shutdown_sequence.py T-A04/T-A05).
        await _close_orchestrator_and_conversation_manager(_orch_shutdown)

        if nav_bridge is not None:
            try:
                await nav_bridge.close()
            except Exception as exc:
                shutdown_error = f"NAVIGATION_BACKEND_CLOSE_FAILED:{resolved_backend}:{exc}"
                app.state.navigation_shutdown_error = shutdown_error
                LOGGER.critical("[SHUTDOWN] %s", shutdown_error)

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
        from src.core.event_bus import OttoEventBus
        from src.core.events import EventType
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
    #            El resultado tipado (EmergencyStopResult.terminal_safe) es la UNICA fuente de
    #            verdad sobre exito — NUNCA se infiere de que emergency_stop() haya retornado
    #            sin excepcion. terminal_safe=True requiere damp_succeeded=True; solo entonces
    #            se omiten STEP 3+4 (ORCHESTRATOR_EMERGENCY_COMPLETED). En cualquier otro caso
    #            (incluyendo fallo de damp dentro de on_enter_emergency) se ejecuta el fallback
    #            directo (DIRECT_HARDWARE_FALLBACK_USED).
    _orchestrator_handled_shutdown = False
    if orchestrator is not None:
        try:
            emergency_fn = getattr(orchestrator, "emergency_stop", None)
            if callable(emergency_fn):
                emergency_result = await asyncio.wait_for(
                    emergency_fn(reason="graceful_shutdown"),
                    timeout=2.0,
                )
                terminal_safe = bool(getattr(emergency_result, "terminal_safe", False))
                if terminal_safe:
                    LOGGER.info(
                        "[SHUTDOWN] STEP 2: TourOrchestrator confirmo terminal_safe=True (damp_succeeded). "
                        "ORCHESTRATOR_EMERGENCY_COMPLETED"
                    )
                    _orchestrator_handled_shutdown = True
                else:
                    LOGGER.warning(
                        "[SHUTDOWN] STEP 2: emergency_stop() retorno sin excepcion pero terminal_safe=False "
                        "(errors=%s). DIRECT_HARDWARE_FALLBACK_USED.",
                        getattr(emergency_result, "errors", None),
                    )
        except asyncio.TimeoutError:
            LOGGER.warning("[SHUTDOWN] STEP 2: Timeout en emergency_stop(). DIRECT_HARDWARE_FALLBACK_USED. Continuando.")
        except Exception as exc:
            LOGGER.warning("[SHUTDOWN] STEP 2: Fallo en emergency_stop(): %s. DIRECT_HARDWARE_FALLBACK_USED. Continuando.", exc)
    else:
        LOGGER.info("[SHUTDOWN] STEP 2: No hay orchestrator activo — omitido.")

    if _orchestrator_handled_shutdown:
        LOGGER.info(
            "[SHUTDOWN] STEP 3+4: Omitidos — TourOrchestrator es la autoridad de motion; "
            "on_enter_emergency confirmo damp_succeeded=True (terminal_safe)."
        )
    else:
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


async def _close_orchestrator_and_conversation_manager(orchestrator: object) -> None:
    """
    @TASK: Cerrar TourOrchestrator y su ConversationManager tras la secuencia HIL-safe
    @INPUT: orchestrator — instancia activa o None (modo mock/CI sin orquestador)
    @OUTPUT: orchestrator.close() awaited (cancela tareas de fondo, desuscribe EventBus);
             conversation_manager.close() invocado de forma SINCRONA (nunca awaited)
    @CONTEXT: Extraido del finally de lifespan() para que sea ejercido directamente por
              tests/unit/test_shutdown_sequence.py en lugar de que los tests reimplementen
              esta secuencia manualmente (codigo productivo real, no una copia paralela).
    @SECURITY: Fallos en cualquiera de los dos close() se absorben y loguean; nunca deben
               impedir el cierre del nav_bridge que ocurre despues en el finally del caller.

    STEP 1: No-op si orchestrator es None
    STEP 2: Invocar await orchestrator.close() con manejo de excepciones
    STEP 3: Resolver conversation_manager (publico o privado) e invocar su close() sincrono
    """
    if orchestrator is None:
        return

    try:
        orch_close = getattr(orchestrator, "close", None)
        if callable(orch_close):
            await orch_close()
            LOGGER.info("[SHUTDOWN] TourOrchestrator.close() completado.")
    except Exception as exc:
        LOGGER.warning("[SHUTDOWN] TourOrchestrator.close() fallido: %s", exc)

    cm = (
        getattr(orchestrator, "conversation_manager", None)
        or getattr(orchestrator, "_conversation_manager", None)
    )
    if cm is not None:
        cm_close = getattr(cm, "close", None)
        if callable(cm_close) and not asyncio.iscoroutinefunction(cm_close):
            try:
                cm_close()
                LOGGER.info("[SHUTDOWN] ConversationManager.close() completado.")
            except Exception as exc:
                LOGGER.warning("[SHUTDOWN] ConversationManager.close() fallido: %s", exc)


# ---------------------------------------------------------------------------
# Stubs de dependencias congeladas
# ---------------------------------------------------------------------------
# Los modulos congelados (orchestrator, conversation, nav2_bridge) esperan
# tipos especificos. Estas funciones proveen instancias compatibles.
# En despliegue real, estas se reemplazan por las instancias completas
# creadas por start_robot.sh (capas 2-3).

# ---------------------------------------------------------------------------
# Seleccion fail-closed del backend de navegacion (Fase 2H.2)
# ---------------------------------------------------------------------------
# @SECURITY: Ninguna de estas tres funciones inicializa ROS 2, hardware, ni red.
#            _resolve_navigation_backend() y _check_direct_real_interlock() son
#            puro calculo sobre Settings; _build_navigation_bridge() construye
#            (__init__) la instancia elegida pero nunca invoca start()/rclpy.init().
#            Ninguna rama usa "except Exception: return _MinimalNavStub()" — un
#            fallo de import o construccion del backend solicitado SIEMPRE se
#            propaga como NAVIGATION_BACKEND_BUILD_FAILED, nunca degrada a stub.

def _resolve_navigation_backend(settings) -> str:
    """
    @TASK: Resolver el backend de navegacion concreto a partir de Settings
    @INPUT: settings — instancia de Settings con NAVIGATION_BACKEND/ROBOT_MODE
    @OUTPUT: "legacy" | "direct" | "stub"
    @CONTEXT: NAVIGATION_BACKEND="auto" resuelve a "legacy" en ROBOT_MODE=real
              (rollback explicito al stack ya validado) y a "stub" en cualquier
              otro modo. "legacy"/"direct" explicitos se devuelven tal cual,
              permitiendo overridear "auto" en cualquier ROBOT_MODE (incluido
              "legacy" como rollback manual incluso en real).
    @SECURITY: "stub" explicito en ROBOT_MODE=real esta prohibido: un tour
               autonomo nunca debe correr contra un backend no operativo
               mientras hay hardware real activo.

    STEP 1: NAVIGATION_BACKEND="auto" → legacy si real, stub en caso contrario
    STEP 2: NAVIGATION_BACKEND="stub" + ROBOT_MODE=real → error estable
    STEP 3: Cualquier otro valor explicito ("legacy"/"direct"/"stub" no-real)
            se devuelve sin modificar
    """
    requested = settings.NAVIGATION_BACKEND

    if requested == "auto":
        return "legacy" if settings.ROBOT_MODE == "real" else "stub"

    if requested == "stub" and settings.ROBOT_MODE == "real":
        raise RuntimeError("NAVIGATION_STUB_FORBIDDEN_IN_REAL_MODE")

    return requested


def _check_direct_real_interlock(settings, resolved_backend: str) -> None:
    """
    @TASK: Bloquear el backend "direct" contra hardware real sin habilitacion explicita
    @INPUT: settings — Settings con ROBOT_MODE/NAVIGATION_DIRECT_REAL_ENABLED;
            resolved_backend — valor ya resuelto por _resolve_navigation_backend()
    @OUTPUT: None si el interlock permite continuar; RuntimeError si no
    @CONTEXT: Debe invocarse ANTES de get_hardware_adapter(), hardware.initialize()
              y de cualquier construccion que pueda iniciar ROS 2 (rclpy.init()).
              Esta fase (2H.2) solo autoriza construccion y tests unitarios de la
              combinacion direct+real+latch=true; nunca autoriza ejecutarla
              contra hardware.
    @SECURITY: NAVIGATION_DIRECT_REAL_ENABLED default False es el interlock
               cerrado por defecto exigido por esta fase.
    """
    if (
        resolved_backend == "direct"
        and settings.ROBOT_MODE == "real"
        and not settings.NAVIGATION_DIRECT_REAL_ENABLED
    ):
        raise RuntimeError("DIRECT_NAVIGATION_REAL_MODE_NOT_AUTHORIZED")


def _build_navigation_bridge(settings, resolved_backend: str):
    """
    @TASK: Construir la instancia concreta del backend de navegacion ya resuelto
    @INPUT: settings — Settings con los parametros NAVIGATION_* configurables;
            resolved_backend — "legacy" | "direct" | "stub"
    @OUTPUT: Instancia construida (sin start()) que conforma NavigationPort
    @CONTEXT: Imports de AsyncNav2Bridge/DirectNav2ActionBridge son lazy (solo
              se importa rclpy/ROS si el backend resuelto realmente lo requiere).
    @SECURITY: Fail-closed: si el import o la construccion del backend
               solicitado fallan, se propaga NAVIGATION_BACKEND_BUILD_FAILED.
               Nunca se sustituye por otro backend ni por un stub.

    STEP 1: "legacy" → import lazy de AsyncNav2Bridge, instancia con defaults
    STEP 2: "direct" → import lazy de DirectNav2ActionBridge, instancia con
            todos los valores NAVIGATION_* de Settings
    STEP 3: "stub" → _MinimalNavStub, sin imports de ROS
    """
    if resolved_backend == "legacy":
        try:
            from src.navigation import AsyncNav2Bridge
            return AsyncNav2Bridge()
        except Exception as exc:
            raise RuntimeError(f"NAVIGATION_BACKEND_BUILD_FAILED:legacy:{exc}") from exc

    if resolved_backend == "direct":
        try:
            from src.navigation import DirectNav2ActionBridge
            return DirectNav2ActionBridge(
                node_name=settings.NAVIGATION_NODE_NAME,
                namespace=settings.NAVIGATION_NAMESPACE,
                navigate_to_pose_action=settings.NAVIGATION_NTP_ACTION,
                follow_waypoints_action=settings.NAVIGATION_FW_ACTION,
                initial_pose_topic=settings.NAVIGATION_INITIAL_POSE_TOPIC,
                server_timeout_s=settings.NAVIGATION_SERVER_TIMEOUT_S,
                goal_response_timeout_s=settings.NAVIGATION_GOAL_RESPONSE_TIMEOUT_S,
                result_timeout_s=settings.NAVIGATION_RESULT_TIMEOUT_S,
                cancel_response_timeout_s=settings.NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S,
                cancel_terminal_timeout_s=settings.NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S,
            )
        except Exception as exc:
            raise RuntimeError(f"NAVIGATION_BACKEND_BUILD_FAILED:direct:{exc}") from exc

    if resolved_backend == "stub":
        return _MinimalNavStub()

    raise RuntimeError(f"NAVIGATION_BACKEND_BUILD_FAILED:{resolved_backend}:unknown backend")


def _get_conversation_manager_stub(settings):
    """
    @TASK: Obtener stub o instancia real de ConversationManager con interlock cloud
    @INPUT: settings — Settings con OLLAMA_HOST, OLLAMA_MODEL y CLOUD_FALLBACK_ENABLED
    @OUTPUT: Instancia de ConversationManager; cloud solo si cloud_fallback_effective
    @CONTEXT: Ollama daemon es Capa 3; puede no estar disponible en CI
    @SECURITY: cloud_fallback_effective bloquea cloud en ROBOT_MODE=real o CLOUD_FALLBACK_ENABLED=False
    """
    cloud_enabled = settings.cloud_fallback_effective
    if settings.ROBOT_MODE == "real" and settings.CLOUD_FALLBACK_ENABLED:
        LOGGER.warning("[BOOT] Cloud fallback solicitado pero bloqueado en ROBOT_MODE=real.")
    try:
        from src.interaction import ConversationManager, CloudNLPPipeline, LocalNLPPipeline
        cloud_strategy = (
            CloudNLPPipeline(enabled=True, timeout_s=1.0)
            if cloud_enabled else None
        )
        return ConversationManager(
            cloud_strategy=cloud_strategy,
            local_strategy=LocalNLPPipeline(
                model_name=settings.OLLAMA_MODEL,
                ollama_base_url=settings.OLLAMA_HOST,
            ),
            cloud_fallback_enabled=cloud_enabled,
        )
    except Exception as exc:
        LOGGER.warning(
            "[BOOT] ConversationManager no disponible. Usando stub minimo. Causa: %s — %s",
            type(exc).__name__, exc,
            exc_info=True,
        )
        return _MinimalConversationStub(
            degradation_error=f"{type(exc).__name__}: {exc}"
        )


def _build_vision_processor(settings):
    """
    @TASK: Construir la unica instancia de VisionProcessor del proceso, con o sin lane QR
    @INPUT: settings — Settings con QR_STATION_TRIGGER_ENABLED y parametros QR_*
    @OUTPUT: Instancia de VisionProcessor (o stub minimo si VisionProcessor no esta disponible
             y QR esta deshabilitado); la misma instancia se inyecta en TourOrchestrator y,
             si QR esta habilitado, en VisionStationTrigger — nunca se construyen dos.
    @CONTEXT: U2 — Si QR_STATION_TRIGGER_ENABLED=True, cualquier fallo al construir el
              StationRegistry, el decoder o el VisionProcessor con lane QR debe propagarse
              (fail-closed); no se sustituye silenciosamente por el stub legado.
              U2R1: el CameraModel usado aqui es un placeholder (camera_matrix=np.eye(3),
              distortion_coefficients=np.zeros) y NO es calibracion productiva de la D435i.
              Por eso, cuando QR esta habilitado, el VisionProcessor se construye con
              visual_odometry_enabled=False: la captura de frames y el lane QR siguen
              activos, pero el lane AprilTag/odometria visual permanece inactivo hasta que
              una etapa futura provea calibracion real e inyecte esa odometria.
    @SECURITY: Si QR esta deshabilitado, el comportamiento es identico al previo a U2:
               no se importa cv2 por causa de QR, no se abre camara por causa de QR.
    """
    # getattr defensivo: compatibilidad con test doubles preexistentes que no declaran
    # QR_STATION_TRIGGER_ENABLED (config.settings.Settings real siempre lo expone, default False).
    if getattr(settings, "QR_STATION_TRIGGER_ENABLED", False):
        import numpy as np
        from pathlib import Path as _Path

        from src.stations.station_registry import StationRegistry
        from src.vision import CameraModel, OpenCVQRCodeDecoder, StableQRFrameDetector, VisionProcessor

        registry = StationRegistry.from_yaml(_Path(settings.QR_STATION_CONFIG_PATH))
        decoder = OpenCVQRCodeDecoder()
        qr_detector = StableQRFrameDetector(
            decoder,
            stable_frames=settings.QR_STABLE_FRAMES,
            release_frames=settings.QR_RELEASE_FRAMES,
        )
        camera_model = CameraModel(
            camera_matrix=np.eye(3, dtype=np.float64),
            distortion_coefficients=np.zeros((5, 1), dtype=np.float64),
        )
        return VisionProcessor(
            camera_model=camera_model,
            tag_size_m=0.16,
            qr_detector=qr_detector,
            station_registry=registry,
            station_queue_maxsize=settings.QR_STATION_QUEUE_MAX_SIZE,
            visual_odometry_enabled=False,
        )

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

    def __init__(self):
        from src.navigation.models import NavigationStatus, NavigationResult, NavigationTerminalStatus
        self._status = NavigationStatus(
            task_active=False,
            last_result_succeeded=False,
            last_result=NavigationResult(
                action_name="_MinimalNavStub",
                status=NavigationTerminalStatus.ERROR,
                succeeded=False,
                error_msg="NAVIGATION_UNAVAILABLE"
            )
        )

    async def start(self):
        return None

    async def close(self):
        return None

    async def navigate_to_waypoints(self, waypoints):
        return False

    async def cancel_navigation(self):
        return None

    async def inject_absolute_pose(self, pose):
        return None

    async def send_goal(self, waypoint) -> bool:
        return False

    async def is_navigation_active(self) -> bool:
        return self._status.task_active

    async def get_status(self) -> "NavigationStatus":
        from dataclasses import replace
        return replace(self._status)

    async def get_last_result(self) -> "NavigationResult":
        return self._status.last_result


class _MinimalConversationStub:
    """
    @TASK: Proveer stub minimo de ConversationManager sin backend NLP real
    @INPUT: Solicitudes de interaccion del orquestador
    @OUTPUT: Respuestas vacias compatibles con el contrato esperado
    @CONTEXT: Fallback de bootstrap cuando Ollama no esta disponible
    @SECURITY: Sin llamadas a APIs externas ni ejecucion de modelos remotos
    @AI_CONTEXT: degradation_error opcional preserva tipo y mensaje de la excepcion que causo
                 el fallback a este stub, para exponerla en app.state.conversation_runtime_error
                 sin requerir que el caller parsee logs (Section 10 de la remediacion).
    """

    swap_count = 0
    active_strategy_name = "stub"

    def __init__(self, degradation_error: Optional[str] = None) -> None:
        self.degradation_error = degradation_error

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
    @OUTPUT: FastAPI app con lifespan, CORS, router incluido y dashboard legacy/redirect
    @CONTEXT: Invocada por uvicorn con factory=True
    @SECURITY: La politica de exposicion de documentacion OpenAPI se gestiona fuera de esta factory.
               CORSMiddleware usa Settings.web_ui_allowed_origins_list como unica fuente de
               verdad (la misma que valida /ws/telemetry); allow_credentials=False siempre.
    """
    from fastapi import FastAPI, HTTPException, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from api.router import router
    _configure_logging()

    settings = get_settings()

    app = FastAPI(
        title="OttoGuide API",
        version="1.0.0",
        description="Robot humanoide Unitree G1 EDU — Guia de visitas universitarias",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_ui_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        # @SECURITY: Si WEB_UI_PUBLIC_URL esta configurado, React es la interfaz principal y
        #            el dashboard HTML legacy nunca se sirve desde este proceso; redirige.
        #            Sin configurar, sirve static/dashboard.html como fallback transicional,
        #            identificado como legacy via header de respuesta.
        public_url = settings.WEB_UI_PUBLIC_URL.strip()
        if public_url:
            return RedirectResponse(url=public_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

        if not DASHBOARD_FILE.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dashboard no encontrado en {DASHBOARD_FILE}",
            )
        return FileResponse(DASHBOARD_FILE, headers={"X-OttoGuide-Dashboard": "legacy-fallback"})

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
    import uvicorn
    settings = get_settings()
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(
            "main:create_app",
            host="0.0.0.0",
            port=settings.API_PORT,
            factory=True,
            log_level="info",
        )
