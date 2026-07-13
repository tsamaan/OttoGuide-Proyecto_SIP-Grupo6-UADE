"""
@TASK: Definir router FastAPI con endpoints de control, observabilidad y gestion de contenido
@INPUT: TourOrchestrator y ConversationManager inyectados via app.state en el lifespan de FastAPI
@OUTPUT: APIRouter con POST /tour/start, /tour/pause, /emergency, GET /status,
         GET /content/script, POST /content/script/reload, WS /ws/telemetry
@CONTEXT: Capa de interfaz HTTP; cero logica de negocio en este archivo.
          Todos los efectos de dominio se delegan al TourOrchestrator o ConversationManager.
@SECURITY: TransitionNotAllowed → HTTP 409; docs de OpenAPI desactivadas en produccion.

STEP 1: Registrar endpoints de mutacion de estado FSM (POST)
STEP 2: Registrar endpoints de observabilidad de solo lectura (GET, WS)
STEP 3: Registrar endpoints de gestion de contenido de guion (GET/POST)
"""
from __future__ import annotations

import asyncio
import functools
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from statemachine.exceptions import TransitionNotAllowed
from config.settings import get_settings
from src.api.websocket_manager import TelemetryManager

from .schemas import (
    EmergencyRequest,
    EmergencyResponse,
    PauseTourRequest,
    QuestionRequest,
    QuestionResponse,
    ScriptReloadResponse,
    StartTourRequest,
    StartTourResponse,
    StatusResponse,
    TourScript,
)

LOGGER = logging.getLogger("otto_guide.api.router")

router = APIRouter()


# ---------------------------------------------------------------------------
# Singleton de TelemetryManager (patron formal)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def get_telemetry_manager() -> TelemetryManager:
    """
    @TASK: Obtener instancia singleton del TelemetryManager de WebSocket
    @INPUT: Sin parametros
    @OUTPUT: Unica instancia de TelemetryManager por proceso
    @CONTEXT: lru_cache garantiza una sola instancia incluso ante reimports
    @SECURITY: Sin estado mutable global expuesto; acceso via esta funcion
    """
    return TelemetryManager()


# Alias de compatibilidad para main.py (from api.router import telemetry_manager)
telemetry_manager: TelemetryManager = get_telemetry_manager()



# ---------------------------------------------------------------------------
# Dependencia de inyeccion
# ---------------------------------------------------------------------------

def _get_orchestrator(request: Request):
    """
    @TASK: Resolver TourOrchestrator desde app.state
    @INPUT: request
    @OUTPUT: Instancia activa o HTTP 503
    @CONTEXT: Mecanismo de DI para todos los endpoints
    @SECURITY: Falla antes de cualquier mutacion si no hay orquestador
    """
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TourOrchestrator no disponible. El sistema no esta inicializado.",
        )
    return orchestrator


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/tour/start",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=StartTourResponse,
    summary="Iniciar tour de navegacion autonoma",
)
async def endpoint_start_tour(
    request: Request,
    payload: StartTourRequest,
    orchestrator=Depends(_get_orchestrator),
) -> StartTourResponse:
    """
    @TASK: Despachar plan de tour al orchestrator de forma atomica
    @INPUT: payload con waypoints y tour_id
    @OUTPUT: HTTP 202 Accepted tras confirmar la transicion FSM
    @CONTEXT: await dispatch_tour() garantiza que la transicion idle->navigating
              ocurre antes de retornar; errores de transicion producen HTTP 409
    @SECURITY: TransitionNotAllowed → HTTP 409
    """
    from src.navigation import NavWaypoint
    from src.core import TourPlan

    settings = get_settings()
    if (
        settings.ROBOT_MODE == "real"
        and not settings.ROBOT_OPERATOR_READY_FOR_MOTION
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "operator_action_required",
                "operator_action_required": True,
                "errors": ["ROBOT_OPERATOR_READY_FOR_MOTION=false"],
            },
        )

    readiness_errors = await _resolve_readiness_errors(request, orchestrator)
    if readiness_errors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Sistema no listo para iniciar tour.",
                "errors": readiness_errors,
            },
        )

    domain_waypoints = [
        NavWaypoint(x=wp.x, y=wp.y, yaw_rad=wp.yaw_rad, frame_id=wp.frame_id)
        for wp in payload.waypoints
    ]
    plan = TourPlan(waypoints=domain_waypoints, tour_id=payload.tour_id)

    try:
        await orchestrator.dispatch_tour(plan)
    except TransitionNotAllowed as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transicion rechazada: {exc}",
        )
    except Exception as exc:
        LOGGER.error("[API] Excepcion en dispatch_tour: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al despachar tour: {exc}",
        )

    LOGGER.info(
        "[API] POST /tour/start aceptado. tour_id=%s waypoints=%d",
        payload.tour_id, len(payload.waypoints),
    )
    return StartTourResponse(
        accepted=True,
        detail=f"Tour '{payload.tour_id}' aceptado. {len(payload.waypoints)} waypoint(s).",
        tour_id=payload.tour_id,
    )


@router.post(
    "/tour/pause",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pausar navegacion para interaccion NLP",
)
async def endpoint_pause_tour(
    payload: PauseTourRequest,
    orchestrator=Depends(_get_orchestrator),
) -> dict:
    """
    @TASK: Activar transicion NAVIGATING→INTERACTING
    @INPUT: payload con audio_b64 opcional
    @OUTPUT: HTTP 202
    @CONTEXT: Trigger externo para ventana de dialogo
    @SECURITY: Audio decodificado en memoria; nunca escrito a disco
    """
    import base64
    import numpy as np

    if payload.audio_b64:
        try:
            audio_bytes = base64.b64decode(payload.audio_b64)
            audio_pcm = np.frombuffer(audio_bytes, dtype=np.float32)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"audio_b64 invalido: {exc}",
            )
    else:
        audio_pcm = np.zeros(1, dtype=np.float32)

    current_state = getattr(orchestrator, "state_id", None)
    if current_state != "navigating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "La pausa solo es valida en estado NAVIGATING.",
                "current_state": current_state,
                "reason": f"Estado actual: '{current_state}'; se requiere 'navigating'.",
            },
        )

    try:
        await orchestrator.request_interaction(audio_pcm, language=payload.language)
    except TransitionNotAllowed as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transicion rechazada: {exc}",
        )

    return {"accepted": True, "detail": "Solicitud de interaccion despachada."}


@router.post(
    "/emergency",
    response_model=EmergencyResponse,
    summary="Activar parada de emergencia (maxima prioridad)",
)
async def endpoint_emergency(
    payload: EmergencyRequest,
    response: Response,
    orchestrator=Depends(_get_orchestrator),
) -> EmergencyResponse:
    """
    @TASK: Trigger de emergencia con StopMove y preservacion postural
    @INPUT: payload con reason
    @OUTPUT: HTTP 200 si la parada terminal de software fue confirmada; 503 si StopMove fallo;
             504 ante timeout del endpoint; 500 ante excepcion no controlada
    @CONTEXT: Maxima prioridad; acepta cualquier estado origen. Nunca infiere exito de que la
              FSM haya alcanzado EMERGENCY ni de que la llamada haya retornado sin excepcion.
    @SECURITY: await directo para que StopMove complete antes de retornar. La respuesta declara
               operator_intervention_required; no afirma seguridad mecanica total.
    """
    LOGGER.critical("[API] POST /emergency recibido. Razon: %s", payload.reason)

    try:
        result = await asyncio.wait_for(
            orchestrator.emergency_stop(reason=payload.reason),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        LOGGER.critical("[API] Timeout en emergency_stop via API.")
        response.status_code = status.HTTP_504_GATEWAY_TIMEOUT
        return EmergencyResponse(
            executed=False,
            terminal_safe=False,
            already_emergency=False,
            reason=payload.reason,
            state=orchestrator.state_id,
            mission_locked=True,
            software_motion_terminal=False,
            posture_preserved=True,
            operator_intervention_required=True,
            nav_cancel_succeeded=False,
            zero_velocity_succeeded=False,
            stop_motion_succeeded=False,
            posture_change_attempted=False,
            damp_attempted=False,
            damp_succeeded=False,
            errors=["emergency_endpoint_timeout"],
        )
    except Exception as exc:
        LOGGER.critical("[API] Excepcion en emergency_stop via API: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error ejecutando emergency_stop: {exc}",
        )

    body = EmergencyResponse(
        executed=True,
        terminal_safe=result.terminal_safe,
        already_emergency=result.already_emergency,
        reason=payload.reason,
        state=orchestrator.state_id,
        mission_locked=getattr(result, "mission_locked", True),
        software_motion_terminal=getattr(result, "software_motion_terminal", result.terminal_safe),
        posture_preserved=getattr(result, "posture_preserved", True),
        operator_intervention_required=getattr(result, "operator_intervention_required", True),
        nav_cancel_succeeded=result.nav_cancel_succeeded,
        zero_velocity_succeeded=result.zero_velocity_succeeded,
        stop_motion_succeeded=getattr(result, "stop_motion_succeeded", result.terminal_safe),
        posture_change_attempted=getattr(result, "posture_change_attempted", False),
        damp_attempted=False,
        damp_succeeded=False,
        errors=list(result.errors),
    )
    response.status_code = (
        status.HTTP_200_OK if result.terminal_safe else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return body






_WS_POLICY_VIOLATION_CLOSE_CODE = 1008


def _is_websocket_origin_allowed(websocket: WebSocket) -> bool:
    """
    @TASK: Validar manualmente el header Origin de una conexion WebSocket entrante
    @INPUT: websocket — instancia WebSocket aun no aceptada; lee request.app.state.settings
    @OUTPUT: True si el origen esta autorizado (o ausente y explicitamente permitido)
    @CONTEXT: CORSMiddleware NO protege WebSockets (es middleware ASGI HTTP-only); esta
              validacion manual usa la misma fuente de configuracion (Settings.web_ui_allowed_origins_list)
              que el CORS HTTP para mantener una unica fuente de verdad de origenes confiables.
    @SECURITY: Origin ausente solo se permite si WEB_UI_ALLOW_MISSING_ORIGIN=True (pruebas
               controladas); en caso contrario se rechaza junto con cualquier origen no listado.
    """
    settings = get_settings()
    origin = websocket.headers.get("origin")
    if origin is None:
        return settings.WEB_UI_ALLOW_MISSING_ORIGIN
    allowed = settings.web_ui_allowed_origins_list
    return origin in allowed or "*" in allowed


@router.websocket("/ws/telemetry")
async def websocket_telemetry(
    websocket: WebSocket,
) -> None:
    """
    @TASK: Gestionar conexion WebSocket para transmision de telemetria FSM en tiempo real
    @INPUT: websocket — instancia WebSocket de FastAPI gestionada por el framework;
            telemetry_manager — Singleton del broadcast pool (accedido via closure del modulo)
    @OUTPUT: Stream de payloads JSON de telemetria enviados al cliente; ninguna mutacion de estado FSM.
             Side-effect: conexion registrada y desregistrada del pool de broadcast.
    @CONTEXT: El cliente recibe un snapshot inicial del estado FSM al conectarse
              (build_telemetry_payload), luego permanece suscrito hasta la desconexion.
              telemetry_manager.broadcast() es invocado por el orquestador para propagar
              cambios de estado a todos los clientes suscritos de forma concurrente.
    @SECURITY: El header Origin se valida ANTES de aceptar la conexion (websocket.close() en
               lugar de accept() ante origen no autorizado), usando la misma fuente de
               configuracion que CORSMiddleware HTTP.

    STEP 1: Validar Origin; cerrar con codigo 1008 (policy violation) si no esta autorizado
    STEP 2: Registrar el WebSocket en el TelemetryManager (pool de broadcast activo)
    STEP 3: Enviar snapshot inicial del estado FSM si el orquestador esta disponible en app.state
    STEP 4: Mantener el loop de recepcion activo; desconectar limpiamente ante WebSocketDisconnect
            o cualquier excepcion no controlada
    """
    if not _is_websocket_origin_allowed(websocket):
        LOGGER.warning(
            "[API] WS /ws/telemetry rechazado: Origin no autorizado (%s).",
            websocket.headers.get("origin"),
        )
        await websocket.close(code=_WS_POLICY_VIOLATION_CLOSE_CODE)
        return

    await telemetry_manager.connect(websocket)
    try:
        orchestrator = getattr(websocket.app.state, "orchestrator", None)
        if orchestrator is not None and hasattr(orchestrator, "build_telemetry_payload"):
            payload = await orchestrator.build_telemetry_payload()
            await websocket.send_json(payload)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await telemetry_manager.disconnect(websocket)
    except Exception:
        await telemetry_manager.disconnect(websocket)
        raise


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Consultar estado completo del sistema",
)
async def endpoint_status(
    request: Request,
    orchestrator=Depends(_get_orchestrator),
) -> StatusResponse:
    """
    @TASK: Snapshot del estado del sistema
    @INPUT: orchestrator
    @OUTPUT: StatusResponse serializado
    @CONTEXT: Solo lectura; sin efectos secundarios
    @SECURITY: Endpoint de observabilidad sin mutacion de estado
    """
    ctx = orchestrator.context
    readiness_errors = await _resolve_readiness_errors(request, orchestrator)
    factory_rest = await _resolve_factory_rest_status(request)
    nav_observability = await _resolve_navigation_observability(request)
    interaction_runtime_status = await _resolve_interaction_runtime_status(request)
    station_trigger_status = await _resolve_station_trigger_status(request)
    return StatusResponse(
        state=orchestrator.state_id,
        tour_id=ctx.tour_id,
        current_waypoint_index=ctx.current_waypoint_index,
        last_error=ctx.last_error,
        operational_ready=not readiness_errors,
        readiness_errors=readiness_errors,
        factory_rest=factory_rest,
        conversation_runtime_degraded=bool(getattr(request.app.state, "conversation_runtime_degraded", False)),
        conversation_runtime_error=getattr(request.app.state, "conversation_runtime_error", None),
        script_loaded=bool(getattr(request.app.state, "script_loaded", False)),
        script_version=getattr(request.app.state, "script_version", None),
        script_waypoint_count=int(getattr(request.app.state, "script_waypoint_count", 0)),
        script_load_error=getattr(request.app.state, "script_load_error", None),
        interaction_runtime=interaction_runtime_status,
        station_trigger=station_trigger_status,
        **nav_observability,
    )


async def _resolve_interaction_runtime_status(request: Request) -> dict:
    """
    @TASK: Construir el snapshot observable del runtime de interaccion real (U1)
    @INPUT: request.app.state.interaction_runtime opcional
    @OUTPUT: dict con las claves de InteractionRuntimeStatusResponse
    @CONTEXT: La ausencia del port no debe bloquear tours en U1; degrada a
              not_configured. health() se invoca con timeout estricto y cualquier
              excepcion o ausencia del metodo degrada conservadoramente sin romper
              el endpoint.
    @SECURITY: Solo se exponen campos primitivos (state, ready, capabilities,
               heartbeat, error); nunca PID, transporte, socket o credenciales.
    """
    runtime = getattr(request.app.state, "interaction_runtime", None)
    if runtime is None:
        return {
            "configured": False,
            "protocol_version": 1,
            "state": "not_configured",
            "ready": False,
            "capabilities": {},
            "last_heartbeat_monotonic_s": None,
            "last_error": None,
        }

    health_fn = getattr(runtime, "health", None)
    if not callable(health_fn):
        return {
            "configured": True,
            "protocol_version": 1,
            "state": "failed",
            "ready": False,
            "capabilities": {},
            "last_heartbeat_monotonic_s": None,
            "last_error": "health_method_missing",
        }

    try:
        health = await asyncio.wait_for(health_fn(), timeout=0.25)
    except asyncio.TimeoutError:
        return {
            "configured": True,
            "protocol_version": 1,
            "state": "failed",
            "ready": False,
            "capabilities": {},
            "last_heartbeat_monotonic_s": None,
            "last_error": "health_timeout",
        }
    except Exception as exc:
        return {
            "configured": True,
            "protocol_version": 1,
            "state": "failed",
            "ready": False,
            "capabilities": {},
            "last_heartbeat_monotonic_s": None,
            "last_error": f"health_error:{type(exc).__name__}",
        }

    capabilities = getattr(health, "capabilities", None)
    capabilities_dict = (
        {
            "audio_capture": bool(getattr(capabilities, "audio_capture", False)),
            "wake_word": bool(getattr(capabilities, "wake_word", False)),
            "vad": bool(getattr(capabilities, "vad", False)),
            "stt": bool(getattr(capabilities, "stt", False)),
            "local_llm": bool(getattr(capabilities, "local_llm", False)),
            "spanish_tts": bool(getattr(capabilities, "spanish_tts", False)),
            "physical_playback": bool(getattr(capabilities, "physical_playback", False)),
            "physical_playback_stop": bool(getattr(capabilities, "physical_playback_stop", False)),
            "physical_playback_completion": bool(getattr(capabilities, "physical_playback_completion", False)),
        }
        if capabilities is not None
        else {}
    )
    state_value = getattr(health, "state", None)
    state_str = state_value.value if hasattr(state_value, "value") else str(state_value)

    return {
        "configured": True,
        "protocol_version": int(getattr(health, "protocol_version", 1)),
        "state": state_str,
        "ready": bool(getattr(health, "ready", False)),
        "capabilities": capabilities_dict,
        "last_heartbeat_monotonic_s": getattr(health, "last_heartbeat_monotonic_s", None),
        "last_error": getattr(health, "last_error", None),
    }


async def _resolve_station_trigger_status(request: Request) -> dict:
    """
    @TASK: Construir el snapshot observable del sensor de estaciones por QR (U1)
    @INPUT: request.app.state.station_trigger opcional
    @OUTPUT: dict con las claves de StationTriggerStatusResponse
    @CONTEXT: La ausencia del port no debe bloquear tours en U1; degrada a
              not_configured. health() se invoca con timeout estricto.
    @SECURITY: Solo se exponen campos primitivos (state, ready, source, error).
    """
    trigger = getattr(request.app.state, "station_trigger", None)
    if trigger is None:
        return {
            "configured": False,
            "state": "not_configured",
            "ready": False,
            "source": "",
            "last_error": None,
        }

    health_fn = getattr(trigger, "health", None)
    if not callable(health_fn):
        return {
            "configured": True,
            "state": "failed",
            "ready": False,
            "source": "",
            "last_error": "health_method_missing",
        }

    try:
        health = await asyncio.wait_for(health_fn(), timeout=0.25)
    except asyncio.TimeoutError:
        return {
            "configured": True,
            "state": "failed",
            "ready": False,
            "source": "",
            "last_error": "health_timeout",
        }
    except Exception as exc:
        return {
            "configured": True,
            "state": "failed",
            "ready": False,
            "source": "",
            "last_error": f"health_error:{type(exc).__name__}",
        }

    state_value = getattr(health, "state", None)
    state_str = state_value.value if hasattr(state_value, "value") else str(state_value)

    return {
        "configured": True,
        "state": state_str,
        "ready": bool(getattr(health, "ready", False)),
        "source": str(getattr(health, "source", "") or ""),
        "last_error": getattr(health, "last_error", None),
    }


async def _resolve_navigation_observability(request: Request) -> dict:
    """
    @TASK: Construir los campos de observabilidad del backend de navegacion para GET /status
    @INPUT: request.app.state (navigation_backend_requested/resolved/started) y nav_bridge
    @OUTPUT: dict con las claves de StatusResponse navigation_*; nunca expone objetos ROS
    @CONTEXT: Si nav_bridge.get_status() falla, no rompe el endpoint: usa valores conservadores
              (remote_state_unknown=True, action_name/goal_uuid=None) y deja que el fallo se
              refleje por separado en readiness_errors via _resolve_readiness_errors.
    @SECURITY: Solo se exponen los campos primitivos de NavigationStatus, nunca el handle/uuid
               interno de ROS ni la instancia del bridge.
    """
    state = request.app.state
    requested = str(getattr(state, "navigation_backend_requested", "unknown") or "unknown")
    resolved = str(getattr(state, "navigation_backend_resolved", "unknown") or "unknown")
    started = bool(getattr(state, "navigation_started", False))

    nav_bridge = getattr(state, "nav_bridge", None)
    remote_state_unknown = False
    action_name: Optional[str] = None
    goal_uuid: Optional[str] = None
    ntp_available: Optional[bool] = None
    fw_available: Optional[bool] = None

    get_status_fn = getattr(nav_bridge, "get_status", None)
    if not callable(get_status_fn):
        remote_state_unknown = True
    else:
        try:
            nav_status = await asyncio.wait_for(get_status_fn(), timeout=0.25)
            remote_state_unknown = bool(getattr(nav_status, "remote_state_unknown", False))
            action_name = getattr(nav_status, "action_name", None)
            goal_uuid = getattr(nav_status, "goal_uuid", None)
        except Exception:
            remote_state_unknown = True

    get_readiness_fn = getattr(nav_bridge, "get_readiness", None)
    if callable(get_readiness_fn):
        try:
            readiness = get_readiness_fn()
            ntp_available = bool(readiness.ntp_available)
            fw_available = bool(readiness.fw_available)
        except Exception:
            pass

    return {
        "navigation_backend_requested": requested,
        "navigation_backend_resolved": resolved,
        "navigation_started": started,
        "navigation_remote_state_unknown": remote_state_unknown,
        "navigation_action_name": action_name,
        "navigation_goal_uuid": goal_uuid,
        "navigation_ntp_available": ntp_available,
        "navigation_fw_available": fw_available,
    }


async def _resolve_readiness_errors(request: Request, orchestrator) -> list[str]:
    """
    @TASK: Calcular errores de readiness antes de aceptar tours
    @INPUT: request.app.state y orquestador activo
    @OUTPUT: Lista de errores bloqueantes; vacia indica GO
    @CONTEXT: Gate operativo para no despachar tours sin un backend de navegacion operativo
              ni hardware critico. Fase 2H.2: el backend stub solo permite tours si
              NAVIGATION_ALLOW_STUB_TOURS=true; legacy/direct deben estar realmente iniciados
              (navigation_started en app.state, nunca solo _started); y un estado remoto
              desconocido (NavigationStatus.remote_state_unknown) bloquea nuevos tours, igual
              que en el contrato ya aceptado de DirectNav2ActionBridge.
    STEP 1: Validar estado FSM idle
    STEP 2: Validar backend de navegacion: presente, resuelto, no-stub-no-autorizado,
            iniciado si es legacy/direct, y con estado remoto confirmado (no desconocido)
    STEP 3: En modo real, validar tambien hardware inicializado
    @SECURITY: Bloquea movimiento autonomo ante inicializacion incompleta o backend degradado
    """
    errors: list[str] = []

    if orchestrator.state_id != "idle":
        errors.append(f"fsm_state={orchestrator.state_id}; se requiere idle")

    robot_mode = str(getattr(orchestrator, "_robot_mode", "mock")).lower()
    hardware = getattr(orchestrator, "_hardware_api", None)

    state = request.app.state
    nav_bridge = getattr(state, "nav_bridge", None)
    backend_resolved = getattr(state, "navigation_backend_resolved", None)
    navigation_started = bool(getattr(state, "navigation_started", False))
    stub_tours_allowed = bool(getattr(state, "navigation_stub_tours_allowed", False))

    if nav_bridge is None or backend_resolved is None:
        errors.append("navigation backend unavailable")
    else:
        if backend_resolved == "disabled":
            errors.append("navigation disabled: status-only real runtime")
        elif backend_resolved == "stub" and not stub_tours_allowed:
            errors.append("navigation backend stub: autonomous tours disabled")
        elif backend_resolved in ("legacy", "direct") and not navigation_started:
            errors.append("navigation backend not started")

        get_status_fn = getattr(nav_bridge, "get_status", None)
        if not callable(get_status_fn):
            errors.append("navigation status unavailable:missing")
        else:
            try:
                nav_status = await asyncio.wait_for(get_status_fn(), timeout=0.25)
                if getattr(nav_status, "remote_state_unknown", False):
                    errors.append("navigation remote state unknown")
            except Exception as exc:
                errors.append(f"navigation status unavailable:{type(exc).__name__}")

    if robot_mode == "real":
        state_reader = getattr(hardware, "get_state", None)
        if callable(state_reader):
            try:
                hardware_state = await asyncio.wait_for(state_reader(), timeout=0.25)
                if isinstance(hardware_state, dict) and hardware_state.get("initialized") is False:
                    errors.append("hardware no inicializado")
            except Exception as exc:
                errors.append(f"hardware state no disponible: {type(exc).__name__}")

        if bool(getattr(state, "conversation_runtime_degraded", False)):
            errors.append("conversation_manager degradado: stub activo en modo real")

    return errors


async def _resolve_factory_rest_status(request: Request) -> dict:
    """
    @TASK: Obtener healthcheck REST read-only del plano de fabrica
    @INPUT: request.app.state.factory_rest_client opcional
    @OUTPUT: dict serializable para StatusResponse.factory_rest
    @CONTEXT: Diagnostico secundario de 192.168.12.1:9991/con_check
    @SECURITY: Solo GET /con_check; no emite paquetes de control
    """
    client = getattr(request.app.state, "factory_rest_client", None)
    if client is None:
        return {
            "enabled": False,
            "reachable": False,
            "error": "factory_rest_client not configured",
        }
    health = await client.con_check()
    return health.to_dict()


@router.post(
    "/question",
    response_model=QuestionResponse,
    summary="Enviar pregunta de texto al ConversationManager",
)
async def endpoint_question(
    payload: QuestionRequest,
    orchestrator=Depends(_get_orchestrator),
) -> QuestionResponse:
    """
    @TASK: Procesar pregunta de texto via ConversationManager
    @INPUT: payload con text y language
    @OUTPUT: QuestionResponse con respuesta y pipeline utilizado
    @CONTEXT: Compatibilidad con interfaz de texto directa
    @SECURITY: Sin ejecucion de STT; texto plano
    """
    try:
        response = await orchestrator.handle_user_question(payload.text)
        return QuestionResponse(
            answer=response.answer_text,
            source_pipeline=response.source_pipeline,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando pregunta: {exc}",
        )


# ---------------------------------------------------------------------------
# Endpoints de Gestion de Contenido (TAREA 3)
# ---------------------------------------------------------------------------

_SCRIPT_DEFAULT_PATH = Path("data/mvp_tour_script.json")


def _get_conversation_manager(request: Request):
    """
    @TASK: Resolver ConversationManager desde app.state
    @INPUT: request
    @OUTPUT: Instancia activa de ConversationManager o HTTP 503
    @CONTEXT: Dependencia de inyeccion para endpoints de contenido
    @SECURITY: Falla antes de cualquier operacion de contenido
    """
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sistema no inicializado: orchestrator no disponible.",
        )
    cm = getattr(orchestrator, "conversation_manager", None)
    if cm is None:
        cm = getattr(orchestrator, "_conversation_manager", None)
    if cm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ConversationManager no accesible desde el orquestador.",
        )
    return cm


@router.get(
    "/content/script",
    response_model=TourScript,
    summary="Consultar el guion de tour cargado actualmente",
)
async def endpoint_get_script(
    cm=Depends(_get_conversation_manager),
) -> TourScript:
    """
    @TASK: Retornar el guion de tour actualmente cargado en ConversationManager
    @INPUT: Sin parametros de request; cm — ConversationManager resuelto via Depends
    @OUTPUT: TourScript serializado en JSON; HTTP 404 si no hay guion cargado
    @CONTEXT: Observabilidad del estado de contenido; sin efectos secundarios ni mutacion de estado.
              El script se carga previamente via POST /content/script/reload.

    STEP 1: Verificar que cm.loaded_script no es None; HTTP 404 si es el caso
    STEP 2: Retornar el objeto TourScript; Pydantic gestiona la serializacion automaticamente
    @SECURITY: Solo lectura; sin mutacion de estado
    """
    script = cm.loaded_script
    if script is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay guion cargado. Usar POST /content/script/reload para cargar.",
        )
    return script


@router.post(
    "/content/script/reload",
    response_model=ScriptReloadResponse,
    status_code=status.HTTP_200_OK,
    summary="Recargar el guion de tour desde disco de forma asíncrona",
)
async def endpoint_reload_script(
    cm=Depends(_get_conversation_manager),
) -> ScriptReloadResponse:
    """
    @TASK: Forzar recarga del guion de tour desde data/mvp_tour_script.json
    @INPUT: Sin payload de request; cm — ConversationManager resuelto via Depends
    @OUTPUT: ScriptReloadResponse con version y cantidad de waypoints cargados;
             HTTP 422 ante archivo inexistente o error de validacion Pydantic
    @CONTEXT: Permite actualizacion de contenido en caliente sin reiniciar el proceso.
              load_script_from_file() es sincrona (I/O de disco + validacion Pydantic);
              se ejecuta en executor de IO para no bloquear el event loop de FastAPI.

    STEP 1: Verificar existencia del archivo en la ruta default (_SCRIPT_DEFAULT_PATH)
    STEP 2: Invocar load_script_from_file() en executor de IO via run_in_executor
    STEP 3: Leer el script recargado desde cm.loaded_script y retornar confirmacion
    @SECURITY: Ruta de archivo fija en el servidor; sin parametro de ruta en la API.
               FileNotFoundError y ValidationError retornan HTTP 422.
    """
    script_path = _SCRIPT_DEFAULT_PATH

    if not script_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Archivo no encontrado: {script_path}. "
                   "Crear data/mvp_tour_script.json a partir de la plantilla.",
        )

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, cm.load_script_from_file, script_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Error al cargar el guion: {exc}",
        )

    script = cm.loaded_script
    LOGGER.info(
        "[API] POST /content/script/reload exitoso. version='%s' waypoints=%d",
        script.version,
        len(script.waypoints),
    )
    return ScriptReloadResponse(
        reloaded=True,
        version=script.version,
        waypoints_loaded=len(script.waypoints),
        detail=f"Guion version '{script.version}' cargado con {len(script.waypoints)} waypoint(s).",
    )


__all__ = ["router", "telemetry_manager"]
