"""
@TASK: Definir el contrato canonico de runtime de interaccion real (U1)
@INPUT: Sin dependencias externas — solo biblioteca estandar
@OUTPUT: Protocol InteractionRuntimePort, envelopes de comando/evento versionados,
         modelos de dominio inmutables y errores del contrato
@CONTEXT: U1 — Unificacion de OttoGuide. Este modulo define la frontera que separara
          el control plane Python (FastAPI, TourOrchestrator) de un futuro worker
          dedicado y supervisado de interaccion real (captura de audio, wake word,
          STT, LLM local, TTS, reproduccion fisica). No implementa ese worker; solo
          el contrato que U3 implementara.
@SECURITY: Modulo importable sin audio, red, hardware o modelos de IA instalados.
           Cero efectos de lado. No otorga autoridad de movimiento.
@AI_CONTEXT: invariantes documentadas en InteractionRuntimePort son contractuales:
             una respuesta textual no prueba que el audio haya comenzado;
             PLAYBACK_STARTED no prueba finalizacion; PLAYBACK_COMPLETED es la unica
             senal de finalizacion fisica confirmada; timeout y emergencia no son
             completion. La navegacion no debe reanudarse sin completion fisico o
             cancelacion explicita. Modo real no puede degradar silenciosamente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, runtime_checkable


INTERACTION_PROTOCOL_VERSION: Final[int] = 1


# ---------------------------------------------------------------------------
# Errores del contrato
# ---------------------------------------------------------------------------


class InteractionRuntimeError(Exception):
    """Error base del contrato de runtime de interaccion."""


class InteractionRuntimeUnavailableError(InteractionRuntimeError):
    """El runtime de interaccion no esta disponible o no fue configurado."""


class InteractionRuntimeProtocolError(InteractionRuntimeError):
    """El mensaje wire no cumple el contrato de protocolo versionado."""


# ---------------------------------------------------------------------------
# Enums de estado y mensajeria
# ---------------------------------------------------------------------------


class InteractionRuntimeState(str, Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPING = "stopping"
    FAILED = "failed"
    EMERGENCY = "emergency"
    CLOSED = "closed"


class WorkerCommandType(str, Enum):
    START = "start"
    HEALTH = "health"
    ACTIVATE = "activate"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    EMERGENCY_STOP = "emergency_stop"
    CLOSE = "close"


class WorkerEventType(str, Enum):
    READY = "ready"
    HEARTBEAT = "heartbeat"
    COMMAND_ACCEPTED = "command_accepted"
    WAKE_WORD_CONFIRMED = "wake_word_confirmed"
    CAPTURE_STARTED = "capture_started"
    TRANSCRIPT_READY = "transcript_ready"
    RESPONSE_READY = "response_ready"
    PLAYBACK_STARTED = "playback_started"
    PLAYBACK_COMPLETED = "playback_completed"
    INTERACTION_TIMEOUT = "interaction_timeout"
    CANCELLED = "cancelled"
    FAILED = "failed"
    STOPPED = "stopped"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Modelos de dominio inmutables
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InteractionContext:
    interaction_id: str
    tour_id: str | None = None
    waypoint_id: str | None = None
    locale: str = "es-AR"
    timeout_s: float = 30.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.interaction_id:
            raise ValueError("interaction_id must not be empty")
        if self.tour_id is not None and not self.tour_id:
            raise ValueError("tour_id must not be empty when provided")
        if self.waypoint_id is not None and not self.waypoint_id:
            raise ValueError("waypoint_id must not be empty when provided")
        if not self.locale:
            raise ValueError("locale must not be empty")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class InteractionRuntimeCapabilities:
    audio_capture: bool = False
    wake_word: bool = False
    vad: bool = False
    stt: bool = False
    local_llm: bool = False
    spanish_tts: bool = False
    physical_playback: bool = False
    physical_playback_stop: bool = False
    physical_playback_completion: bool = False


@dataclass(frozen=True, slots=True)
class InteractionRuntimeHealth:
    protocol_version: int
    state: InteractionRuntimeState
    ready: bool
    capabilities: InteractionRuntimeCapabilities
    last_heartbeat_monotonic_s: float | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.protocol_version != INTERACTION_PROTOCOL_VERSION:
            raise ValueError(
                f"protocol_version must be {INTERACTION_PROTOCOL_VERSION}, "
                f"got {self.protocol_version}"
            )
        if self.last_heartbeat_monotonic_s is not None and self.last_heartbeat_monotonic_s < 0:
            raise ValueError("last_heartbeat_monotonic_s must not be negative")
        if self.last_error is not None and not self.last_error:
            raise ValueError("last_error must not be empty when provided")


# ---------------------------------------------------------------------------
# Envelopes wire — comando y evento
# ---------------------------------------------------------------------------

_ENVELOPE_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "protocol_version",
        "message_id",
        "interaction_id",
        "sequence",
        "emitted_at_monotonic_s",
        "payload",
    }
)


def _validate_envelope_common(
    *,
    protocol_version: int,
    message_id: str,
    interaction_id: str | None,
    sequence: int,
    emitted_at_monotonic_s: float,
) -> None:
    if protocol_version != INTERACTION_PROTOCOL_VERSION:
        raise ValueError(
            f"protocol_version must be {INTERACTION_PROTOCOL_VERSION}, got {protocol_version}"
        )
    if not message_id:
        raise ValueError("message_id must not be empty")
    if interaction_id is not None and not interaction_id:
        raise ValueError("interaction_id must not be empty when provided")
    if sequence < 0:
        raise ValueError("sequence must not be negative")
    if emitted_at_monotonic_s < 0:
        raise ValueError("emitted_at_monotonic_s must not be negative")


@dataclass(frozen=True, slots=True)
class WorkerCommandEnvelope:
    protocol_version: int
    message_id: str
    interaction_id: str | None
    command: WorkerCommandType
    sequence: int
    emitted_at_monotonic_s: float
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_envelope_common(
            protocol_version=self.protocol_version,
            message_id=self.message_id,
            interaction_id=self.interaction_id,
            sequence=self.sequence,
            emitted_at_monotonic_s=self.emitted_at_monotonic_s,
        )
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_wire_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "interaction_id": self.interaction_id,
            "command": self.command.value,
            "sequence": self.sequence,
            "emitted_at_monotonic_s": self.emitted_at_monotonic_s,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_wire_dict(cls, raw: Mapping[str, object]) -> "WorkerCommandEnvelope":
        required = _ENVELOPE_REQUIRED_KEYS | {"command"}
        missing = required - set(raw.keys())
        if missing:
            raise InteractionRuntimeProtocolError(
                f"missing required keys: {sorted(missing)}"
            )
        unknown = set(raw.keys()) - required
        if unknown:
            raise InteractionRuntimeProtocolError(
                f"unknown keys: {sorted(unknown)}"
            )
        try:
            command = WorkerCommandType(raw["command"])
        except ValueError as exc:
            raise InteractionRuntimeProtocolError(
                f"invalid command value: {raw['command']!r}"
            ) from exc
        try:
            return cls(
                protocol_version=int(raw["protocol_version"]),  # type: ignore[arg-type]
                message_id=str(raw["message_id"]),
                interaction_id=raw["interaction_id"],  # type: ignore[arg-type]
                command=command,
                sequence=int(raw["sequence"]),  # type: ignore[arg-type]
                emitted_at_monotonic_s=float(raw["emitted_at_monotonic_s"]),  # type: ignore[arg-type]
                payload=raw["payload"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise InteractionRuntimeProtocolError(
                f"malformed wire payload: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class WorkerEventEnvelope:
    protocol_version: int
    message_id: str
    interaction_id: str | None
    event: WorkerEventType
    sequence: int
    emitted_at_monotonic_s: float
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_envelope_common(
            protocol_version=self.protocol_version,
            message_id=self.message_id,
            interaction_id=self.interaction_id,
            sequence=self.sequence,
            emitted_at_monotonic_s=self.emitted_at_monotonic_s,
        )
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_wire_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "interaction_id": self.interaction_id,
            "event": self.event.value,
            "sequence": self.sequence,
            "emitted_at_monotonic_s": self.emitted_at_monotonic_s,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_wire_dict(cls, raw: Mapping[str, object]) -> "WorkerEventEnvelope":
        required = _ENVELOPE_REQUIRED_KEYS | {"event"}
        missing = required - set(raw.keys())
        if missing:
            raise InteractionRuntimeProtocolError(
                f"missing required keys: {sorted(missing)}"
            )
        unknown = set(raw.keys()) - required
        if unknown:
            raise InteractionRuntimeProtocolError(
                f"unknown keys: {sorted(unknown)}"
            )
        try:
            event = WorkerEventType(raw["event"])
        except ValueError as exc:
            raise InteractionRuntimeProtocolError(
                f"invalid event value: {raw['event']!r}"
            ) from exc
        try:
            return cls(
                protocol_version=int(raw["protocol_version"]),  # type: ignore[arg-type]
                message_id=str(raw["message_id"]),
                interaction_id=raw["interaction_id"],  # type: ignore[arg-type]
                event=event,
                sequence=int(raw["sequence"]),  # type: ignore[arg-type]
                emitted_at_monotonic_s=float(raw["emitted_at_monotonic_s"]),  # type: ignore[arg-type]
                payload=raw["payload"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise InteractionRuntimeProtocolError(
                f"malformed wire payload: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Protocol del runtime de interaccion
# ---------------------------------------------------------------------------


@runtime_checkable
class InteractionRuntimePort(Protocol):
    """
    @TASK: Declarar el contrato minimo de un runtime de interaccion real
    @CONTEXT: Implementado en el futuro por un cliente que hable con el worker
              supervisado de interaccion (U3). No implementado en U1.
    @AI_CONTEXT: Invariantes contractuales:
                 - toda interaccion se correlaciona mediante interaction_id;
                 - una respuesta textual (RESPONSE_READY) no prueba que el audio
                   haya comenzado;
                 - PLAYBACK_STARTED no prueba que el audio haya finalizado;
                 - PLAYBACK_COMPLETED representa el final fisico confirmado por
                   el runtime, y es la unica senal valida de finalizacion;
                 - timeout no equivale a completion;
                 - emergencia no equivale a completion;
                 - la navegacion no debe reanudarse hasta completion fisico
                   confirmado o cancelacion explicita;
                 - el modo real no puede degradar silenciosamente a mock,
                   audio del host o cloud;
                 - este Protocol no concede autoridad de movimiento.
    """

    async def start(self) -> None:
        ...

    async def health(self) -> InteractionRuntimeHealth:
        ...

    async def activate(self, context: InteractionContext) -> None:
        ...

    async def pause(self) -> None:
        ...

    async def resume(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def emergency_stop(self) -> None:
        ...

    async def close(self) -> None:
        ...


__all__ = [
    "INTERACTION_PROTOCOL_VERSION",
    "InteractionContext",
    "InteractionRuntimeCapabilities",
    "InteractionRuntimeError",
    "InteractionRuntimeHealth",
    "InteractionRuntimePort",
    "InteractionRuntimeProtocolError",
    "InteractionRuntimeState",
    "InteractionRuntimeUnavailableError",
    "WorkerCommandEnvelope",
    "WorkerCommandType",
    "WorkerEventEnvelope",
    "WorkerEventType",
]
