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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from statemachine.exceptions import TransitionNotAllowed
from src.api.websocket_manager import TelemetryManager

from .schemas import (
    EmergencyRequest,
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
    background_tasks: BackgroundTasks,
    orchestrator=Depends(_get_orchestrator),
) -> StartTourResponse:
    """
    @TASK: Despachar plan de tour al orchestrator en background
    @INPUT: payload con waypoints y tour_id
    @OUTPUT: HTTP 202 Accepted
    @CONTEXT: El endpoint retorna inmediatamente; dispatch corre en background
    @SECURITY: TransitionNotAllowed → HTTP 409
    """
    from src.navigation import NavWaypoint
    from src.core import TourPlan

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

    async def _dispatch():
        try:
            await orchestrator.dispatch_tour(plan)
        except TransitionNotAllowed as exc:
            LOGGER.error("[API] dispatch_tour rechazado: %s", exc)
        except Exception as exc:
            LOGGER.error("[API] Excepcion en dispatch_tour: %s", exc)

    background_tasks.add_task(_dispatch)

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

    try:
        asyncio.create_task(
            orchestrator.request_interaction(audio_pcm, language=payload.language),
            name="api-pause-interaction",
        )
    except TransitionNotAllowed as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transicion rechazada: {exc}",
        )

    return {"accepted": "true", "detail": "Solicitud de interaccion despachada."}


@router.post(
    "/emergency",
    status_code=status.HTTP_200_OK,
    summary="Activar parada de emergencia (maxima prioridad)",
)
async def endpoint_emergency(
    payload: EmergencyRequest,
    orchestrator=Depends(_get_orchestrator),
) -> dict:
    """
    @TASK: Trigger de emergencia con Damp() inmediato
    @INPUT: payload con reason
    @OUTPUT: HTTP 200 tras despacho
    @CONTEXT: Maxima prioridad; acepta cualquier estado origen
    @SECURITY: await directo para que Damp() inicie antes de retornar
    """
    LOGGER.critical("[API] POST /emergency recibido. Razon: %s", payload.reason)

    try:
        await asyncio.wait_for(
            orchestrator.emergency_stop(reason=payload.reason),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        LOGGER.critical("[API] Timeout en emergency_stop.")
    except Exception as exc:
        LOGGER.critical("[API] Excepcion en emergency_stop: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error ejecutando emergency_stop: {exc}",
        )

    return {
        "executed": "true",
        "reason": payload.reason,
        "state": orchestrator.state_id,
    }






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

    STEP 1: Registrar el WebSocket en el TelemetryManager (pool de broadcast activo)
    STEP 2: Enviar snapshot inicial del estado FSM si el orquestador esta disponible en app.state
    STEP 3: Mantener el loop de recepcion activo; desconectar limpiamente ante WebSocketDisconnect
            o cualquier excepcion no controlada
    """
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
    return StatusResponse(
        state=orchestrator.state_id,
        tour_id=ctx.tour_id,
        current_waypoint_index=ctx.current_waypoint_index,
        last_error=ctx.last_error,
        operational_ready=not readiness_errors,
        readiness_errors=readiness_errors,
        factory_rest=factory_rest,
        **nav_observability,
    )


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
        if backend_resolved == "stub" and not stub_tours_allowed:
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
