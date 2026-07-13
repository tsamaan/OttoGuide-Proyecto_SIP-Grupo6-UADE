from __future__ import annotations

# @TASK: Definir schemas Pydantic para la API REST de OttoGuide
# @INPUT: Sin dependencias de hardware ni SDK
# @OUTPUT: Modelos de request/response serializables en JSON
# @CONTEXT: Contratos de API para endpoints de control, observabilidad y contenido de tour
# @SECURITY: extra="forbid" en todos los modelos de entrada de control
# STEP 1: Contratos de hardware/control (sin cambios)
# STEP 2: Contratos de contenido — ZoneContent y TourScript (nuevos)
# STEP 3: Contratos de recarga de script (nuevos)

import math
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_COORD_M = 1_000.0
_MAX_WAYPOINTS = 50


class NavWaypointDTO(BaseModel):
    """Waypoint serializable en JSON para POST /tour/start."""
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    yaw_rad: float
    frame_id: str = "map"

    @field_validator("x", "y", "yaw_rad", mode="before")
    @classmethod
    def _reject_nan_inf(cls, v: float, info) -> float:
        if not isinstance(v, (int, float)):
            return v
        if math.isnan(v):
            raise ValueError(f"{info.field_name} must not be NaN")
        if math.isinf(v):
            raise ValueError(f"{info.field_name} must not be infinite")
        return v

    @field_validator("x", "y", mode="after")
    @classmethod
    def _check_coord_bounds(cls, v: float, info) -> float:
        if abs(v) > _MAX_COORD_M:
            raise ValueError(
                f"{info.field_name}={v} exceeds ±{_MAX_COORD_M} m map bounds"
            )
        return v

    @field_validator("frame_id", mode="after")
    @classmethod
    def _frame_id_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("frame_id must not be empty")
        return v


class StartTourRequest(BaseModel):
    """Payload para POST /tour/start."""
    model_config = ConfigDict(extra="forbid")

    waypoints: list[NavWaypointDTO] = Field(min_length=1, max_length=_MAX_WAYPOINTS)
    tour_id: str = Field(default="tour-001", min_length=1)


class StartTourResponse(BaseModel):
    """Respuesta HTTP 202 para inicio de tour."""
    accepted: bool
    detail: str
    tour_id: str


class PauseTourRequest(BaseModel):
    """Payload para POST /tour/pause."""
    model_config = ConfigDict(extra="forbid")

    audio_b64: Optional[str] = None
    language: str = "es"


class EmergencyRequest(BaseModel):
    """Payload para POST /emergency."""
    model_config = ConfigDict(extra="forbid")

    reason: str = "emergency-stop-api"


class EmergencyResponse(BaseModel):
    """
    @TASK: Tipar la respuesta de POST /emergency reflejando el EmergencyStopResult real
    @INPUT: Poblado desde TourOrchestrator.emergency_stop()
    @OUTPUT: Resultado de parada de locomocion con preservacion postural
    @CONTEXT: executed indica que la secuencia se ejecuto (o ya estaba ejecutada via
              already_emergency); terminal_safe es compatibilidad software-only y no sustituye
              la verificacion fisica del operador.
    """
    executed: bool
    terminal_safe: bool
    already_emergency: bool
    reason: str
    state: str
    mission_locked: bool
    software_motion_terminal: bool
    posture_preserved: bool
    operator_intervention_required: bool
    nav_cancel_succeeded: bool
    zero_velocity_succeeded: bool
    stop_motion_succeeded: bool
    posture_change_attempted: bool
    damp_attempted: bool = False
    damp_succeeded: bool = False
    errors: list[str] = Field(default_factory=list)


class InteractionCapabilitiesResponse(BaseModel):
    """
    @TASK: Exponer capacidades booleanas del runtime de interaccion real (U1)
    @CONTEXT: Todas False por defecto; un runtime real declarara explicitamente
              las capacidades que soporta. Aditivo, sin impacto en endpoints existentes.
    """
    audio_capture: bool = False
    wake_word: bool = False
    vad: bool = False
    stt: bool = False
    local_llm: bool = False
    spanish_tts: bool = False
    physical_playback: bool = False
    physical_playback_stop: bool = False
    physical_playback_completion: bool = False


class InteractionRuntimeStatusResponse(BaseModel):
    """
    @TASK: Exponer el estado observable del runtime de interaccion real (U1/MVP-R0)
    @CONTEXT: configured=False indica que no hay app.state.interaction_runtime
              configurado; el router degrada conservadoramente ante timeout o error.
              mock=True/physical=False deben ser siempre visibles cuando el backend
              configurado es cxx_jsonl_mock (test double de protocolo, nunca audio fisico).
    """
    configured: bool = False
    protocol_version: int = 1
    state: str = "not_configured"
    ready: bool = False
    mock: bool = False
    physical: bool = False
    capabilities: InteractionCapabilitiesResponse = Field(
        default_factory=InteractionCapabilitiesResponse
    )
    last_heartbeat_monotonic_s: Optional[float] = None
    last_error: Optional[str] = None
    termination_reason: Optional[str] = None


class InteractionSessionStatusResponse(BaseModel):
    """
    @TASK: Exponer el estado observable de la sesion de interaccion standalone (MVP-R0)
    @CONTEXT: active=False cuando no hay sesion standalone en curso. Independiente del
              estado FSM de mision (StatusResponse.state).
    """
    active: bool = False
    session_id: Optional[str] = None
    state: str = "idle"
    last_event: Optional[str] = None


class StationTriggerStatusResponse(BaseModel):
    """
    @TASK: Exponer el estado observable del sensor de estaciones por QR (U1)
    @CONTEXT: configured=False indica que no hay app.state.station_trigger
              configurado; el router degrada conservadoramente ante timeout o error.
    """
    configured: bool = False
    state: str = "not_configured"
    ready: bool = False
    source: str = ""
    last_error: Optional[str] = None


class StatusResponse(BaseModel):
    """Snapshot consolidado del estado del sistema."""
    state: str
    tour_id: Optional[str] = None
    current_waypoint_index: int = 0
    last_error: Optional[str] = None
    operational_ready: bool = False
    readiness_errors: list[str] = Field(default_factory=list)
    factory_rest: dict = Field(default_factory=dict)

    # --- Observabilidad del backend de navegacion (Fase 2H.2) ---
    navigation_backend_requested: str = "unknown"
    navigation_backend_resolved: str = "unknown"
    navigation_started: bool = False
    navigation_remote_state_unknown: bool = False
    navigation_action_name: Optional[str] = None
    navigation_goal_uuid: Optional[str] = None

    # --- Readiness por servidor (Commit 5) ---
    navigation_ntp_available: Optional[bool] = None
    navigation_fw_available: Optional[bool] = None

    # --- Observabilidad del runtime de conversacion y guion (Section 10) ---
    conversation_runtime_degraded: bool = False
    conversation_runtime_error: Optional[str] = None
    script_loaded: bool = False
    script_version: Optional[str] = None
    script_waypoint_count: int = 0
    script_load_error: Optional[str] = None

    # --- Observabilidad de contratos canonicos de integracion (U1) ---
    interaction_runtime: InteractionRuntimeStatusResponse = Field(
        default_factory=InteractionRuntimeStatusResponse
    )
    station_trigger: StationTriggerStatusResponse = Field(
        default_factory=StationTriggerStatusResponse
    )
    interaction_session: InteractionSessionStatusResponse = Field(
        default_factory=InteractionSessionStatusResponse
    )


class StartInteractionRequest(BaseModel):
    """Payload para POST /interaction/start."""
    model_config = ConfigDict(extra="forbid")

    locale: str = Field(default="es", min_length=1)
    timeout_s: float = Field(default=15.0, gt=0.0, le=300.0)


class StartInteractionResponse(BaseModel):
    """
    @TASK: Tipar la respuesta de POST /interaction/start (202 Accepted)
    @CONTEXT: runtime_mock=True indica explicitamente worker de protocolo C++ (test double),
              nunca audio fisico. Nunca reportar runtime_mock=False sin que el runtime
              configurado realmente declare capacidades fisicas.
    """
    accepted: bool
    interaction_id: str
    runtime_backend: str
    runtime_mock: bool


class QuestionRequest(BaseModel):
    """Payload para POST /question."""
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    language: str = "es"


class QuestionResponse(BaseModel):
    """Respuesta a pregunta de usuario."""
    answer: str
    source_pipeline: str



# ---------------------------------------------------------------------------
# Contratos de Contenido de Tour (TAREA 1)
# ---------------------------------------------------------------------------

class WaypointContent(BaseModel):
    """
    @TASK: Definir contenido de una zona del tour universitario
    @INPUT: JSON editado por el equipo de contenido
    @OUTPUT: Modelo validado consumido por ConversationManager
    @CONTEXT: Unidad atomica de contenido con prompt de sistema para Ollama
    @SECURITY: extra=ignore permite al equipo de contenido agregar metadatos
                sin romper la validacion del schema
    """
    model_config = ConfigDict(extra="ignore")

    waypoint_id: str = Field(
        min_length=1,
        description="Identificador logico del waypoint (I, 1, 2, 3, F).",
    )
    interaction_type: Literal["scripted", "llm_qa"] = Field(
        description="Tipo de interaccion para el waypoint.",
    )
    script_text: Optional[str] = Field(
        default=None,
        description="Texto determinista para TTS offline cuando interaction_type='scripted'.",
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Prompt base para LLM cuando interaction_type='llm_qa'.",
    )
    pose_2d: dict[str, float] = Field(
        min_length=3,
        description="Coordenadas 2D del mapa para navegacion fisica: {x, y, theta}.",
    )


class TourScript(BaseModel):
    """
    @TASK: Definir el guion completo del tour con todas las zonas
    @INPUT: Archivo JSON editado offline por el equipo de contenido
    @OUTPUT: Modelo validado con lista ordenada de zonas
    @CONTEXT: Archivo maestro de contenido; recargable en caliente via /content/script/reload
    @SECURITY: Validacion estricta de zonas; version como campo auditable
    """
    model_config = ConfigDict(extra="ignore")

    version: str = Field(
        min_length=1,
        description="Version semantica del guion (e.g. '1.0.0'). Usada para auditorias.",
    )
    waypoints: list[WaypointContent] = Field(
        min_length=1,
        description="Lista ordenada de waypoints logicos del tour. Minimo 1.",
    )


class ScriptReloadResponse(BaseModel):
    """
    @TASK: Confirmar resultado de la recarga del guion desde disco
    @INPUT: Sin parametros
    @OUTPUT: Estado de la operacion, version cargada y zonas disponibles
    @CONTEXT: Respuesta de POST /content/script/reload
    @SECURITY: No expone rutas del sistema de archivos del servidor
    """
    reloaded: bool
    version: str
    waypoints_loaded: int
    detail: str


__all__ = [
    "EmergencyRequest",
    "EmergencyResponse",
    "InteractionCapabilitiesResponse",
    "InteractionRuntimeStatusResponse",
    "InteractionSessionStatusResponse",
    "NavWaypointDTO",
    "PauseTourRequest",
    "QuestionRequest",
    "QuestionResponse",
    "ScriptReloadResponse",
    "StartInteractionRequest",
    "StartInteractionResponse",
    "StartTourRequest",
    "StartTourResponse",
    "StationTriggerStatusResponse",
    "StatusResponse",
    "TourScript",
    "WaypointContent",
]
