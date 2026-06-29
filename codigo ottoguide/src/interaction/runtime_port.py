"""
Canonical interaction runtime contract.

This module is intentionally stdlib-only and side-effect free. It defines the
wire protocol shared by the Python control plane and a supervised interaction
worker. It does not create processes, run audio, access models, or touch robot
hardware.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, runtime_checkable


INTERACTION_PROTOCOL_VERSION: Final[int] = 1
MAX_IDENTIFIER_LENGTH: Final[int] = 80
MAX_PAYLOAD_DEPTH: Final[int] = 8
MAX_PAYLOAD_STRING_LENGTH: Final[int] = 4096
MAX_PAYLOAD_CONTAINER_ITEMS: Final[int] = 256
MAX_PAYLOAD_SERIALIZED_BYTES: Final[int] = 32768
SIGNED_INTEGER_MIN: Final[int] = -9223372036854775808
SIGNED_INTEGER_MAX: Final[int] = 9223372036854775807

ERR_MISSING_KEY: Final[str] = "ERR_MISSING_KEY"
ERR_UNKNOWN_KEY: Final[str] = "ERR_UNKNOWN_KEY"
ERR_TYPE: Final[str] = "ERR_TYPE"
ERR_VERSION: Final[str] = "ERR_VERSION"
ERR_IDENTIFIER: Final[str] = "ERR_IDENTIFIER"
ERR_RANGE: Final[str] = "ERR_RANGE"
ERR_NON_FINITE: Final[str] = "ERR_NON_FINITE"
ERR_SIZE: Final[str] = "ERR_SIZE"
ERR_DEPTH: Final[str] = "ERR_DEPTH"
ERR_CONTAINER_ITEMS: Final[str] = "ERR_CONTAINER_ITEMS"
ERR_JSON_UNSAFE: Final[str] = "ERR_JSON_UNSAFE"
ERR_JSON: Final[str] = "ERR_JSON"
ERR_UTF8: Final[str] = "ERR_UTF8"
ERR_DUPLICATE_MESSAGE_ID: Final[str] = "ERR_DUPLICATE_MESSAGE_ID"
ERR_SEQUENCE: Final[str] = "ERR_SEQUENCE"
ERR_STALE_INTERACTION: Final[str] = "ERR_STALE_INTERACTION"
ERR_LINE_TOO_LARGE: Final[str] = "ERR_LINE_TOO_LARGE"
ERR_FRAMING: Final[str] = "ERR_FRAMING"
ERR_MESSAGE_LIMIT: Final[str] = "ERR_MESSAGE_LIMIT"
ERR_STATE: Final[str] = "ERR_STATE"
ERR_CORRELATION: Final[str] = "ERR_CORRELATION"

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:-]+$")
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


class InteractionRuntimeError(Exception):
    """Base error for the interaction runtime contract."""


class InteractionRuntimeUnavailableError(InteractionRuntimeError):
    """The interaction runtime is unavailable, failed, or closed."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class InteractionRuntimeProtocolError(InteractionRuntimeError, ValueError):
    """A wire message violates the versioned protocol."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


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


_PROCESS_COMMANDS: Final[frozenset[WorkerCommandType]] = frozenset(
    {
        WorkerCommandType.START,
        WorkerCommandType.HEALTH,
        WorkerCommandType.CLOSE,
        WorkerCommandType.EMERGENCY_STOP,
    }
)
_INTERACTION_COMMANDS: Final[frozenset[WorkerCommandType]] = frozenset(
    {
        WorkerCommandType.ACTIVATE,
        WorkerCommandType.PAUSE,
        WorkerCommandType.RESUME,
        WorkerCommandType.STOP,
    }
)
_PROCESS_EVENTS: Final[frozenset[WorkerEventType]] = frozenset(
    {
        WorkerEventType.READY,
        WorkerEventType.HEARTBEAT,
        WorkerEventType.WAKE_WORD_CONFIRMED,
        WorkerEventType.STOPPED,
        WorkerEventType.CLOSED,
    }
)
_INTERACTION_EVENTS: Final[frozenset[WorkerEventType]] = frozenset(
    {
        WorkerEventType.CAPTURE_STARTED,
        WorkerEventType.TRANSCRIPT_READY,
        WorkerEventType.RESPONSE_READY,
        WorkerEventType.PLAYBACK_STARTED,
        WorkerEventType.PLAYBACK_COMPLETED,
        WorkerEventType.INTERACTION_TIMEOUT,
        WorkerEventType.CANCELLED,
    }
)
_FLEXIBLE_EVENTS: Final[frozenset[WorkerEventType]] = frozenset(
    {
        WorkerEventType.COMMAND_ACCEPTED,
        WorkerEventType.FAILED,
    }
)


def _protocol_error(code: str, message: str) -> InteractionRuntimeProtocolError:
    return InteractionRuntimeProtocolError(code, message)


def _ensure_strict_int(value: object, *, field_name: str, non_negative: bool) -> int:
    if type(value) is not int:
        raise _protocol_error(ERR_TYPE, f"{field_name} must be an int")
    if value < SIGNED_INTEGER_MIN or value > SIGNED_INTEGER_MAX:
        raise _protocol_error(ERR_RANGE, f"{field_name} outside signed int64")
    if non_negative and value < 0:
        raise _protocol_error(ERR_RANGE, f"{field_name} must not be negative")
    return value


def _ensure_monotonic(value: object, *, field_name: str) -> float:
    if type(value) not in (int, float):
        raise _protocol_error(ERR_TYPE, f"{field_name} must be int or float")
    result = float(value)
    if not math.isfinite(result):
        raise _protocol_error(ERR_NON_FINITE, f"{field_name} must be finite")
    if result < 0:
        raise _protocol_error(ERR_RANGE, f"{field_name} must not be negative")
    return result


def _ensure_identifier(value: object, *, field_name: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str:
        raise _protocol_error(ERR_TYPE, f"{field_name} must be a string")
    if not value:
        raise _protocol_error(ERR_IDENTIFIER, f"{field_name} must not be empty")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise _protocol_error(ERR_IDENTIFIER, f"{field_name} is too long")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _protocol_error(ERR_IDENTIFIER, f"{field_name} must be ASCII") from exc
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise _protocol_error(ERR_IDENTIFIER, f"{field_name} has invalid characters")
    return value


def _freeze_json_value(value: object, *, depth: int, seen: set[int]) -> object:
    if depth > MAX_PAYLOAD_DEPTH:
        raise _protocol_error(ERR_DEPTH, "payload exceeds maximum depth")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        _ensure_strict_int(value, field_name="payload integer", non_negative=False)
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _protocol_error(ERR_NON_FINITE, "payload float must be finite")
        return value
    if type(value) is str:
        if len(value) > MAX_PAYLOAD_STRING_LENGTH:
            raise _protocol_error(ERR_SIZE, "payload string too large")
        return value
    if type(value) is dict or type(value) is MappingProxyType:
        marker = id(value)
        if marker in seen:
            raise _protocol_error(ERR_JSON_UNSAFE, "payload contains a cycle")
        seen.add(marker)
        if len(value) > MAX_PAYLOAD_CONTAINER_ITEMS:
            raise _protocol_error(ERR_CONTAINER_ITEMS, "payload mapping too large")
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _protocol_error(ERR_TYPE, "payload keys must be strings")
            if len(key) > MAX_PAYLOAD_STRING_LENGTH:
                raise _protocol_error(ERR_SIZE, "payload key too large")
            frozen[key] = _freeze_json_value(item, depth=depth + 1, seen=seen)
        seen.remove(marker)
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        marker = id(value)
        if marker in seen:
            raise _protocol_error(ERR_JSON_UNSAFE, "payload contains a cycle")
        seen.add(marker)
        if len(value) > MAX_PAYLOAD_CONTAINER_ITEMS:
            raise _protocol_error(ERR_CONTAINER_ITEMS, "payload sequence too large")
        frozen_items = tuple(
            _freeze_json_value(item, depth=depth + 1, seen=seen)
            for item in value
        )
        seen.remove(marker)
        return frozen_items
    raise _protocol_error(ERR_JSON_UNSAFE, f"payload value is not JSON-safe: {type(value).__name__}")


def _thaw_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


def _validate_payload_size(payload: Mapping[str, object]) -> None:
    try:
        encoded = json.dumps(
            _thaw_json_value(payload),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _protocol_error(ERR_JSON, f"payload is not JSON serializable: {exc}") from exc
    if len(encoded) > MAX_PAYLOAD_SERIALIZED_BYTES:
        raise _protocol_error(ERR_SIZE, "payload serialized size too large")


def _freeze_payload(payload: object) -> Mapping[str, object]:
    if type(payload) is not dict:
        raise _protocol_error(ERR_TYPE, "payload must be a dict")
    frozen = _freeze_json_value(payload, depth=0, seen=set())
    if not isinstance(frozen, MappingProxyType):
        raise _protocol_error(ERR_TYPE, "payload must freeze to a mapping")
    _validate_payload_size(frozen)
    return frozen


def _validate_common(
    *,
    protocol_version: object,
    message_id: object,
    interaction_id: object,
    sequence: object,
    emitted_at_monotonic_s: object,
) -> tuple[int, str, str | None, int, float]:
    version = _ensure_strict_int(protocol_version, field_name="protocol_version", non_negative=True)
    if version != INTERACTION_PROTOCOL_VERSION:
        raise _protocol_error(ERR_VERSION, f"protocol_version must be {INTERACTION_PROTOCOL_VERSION}")
    return (
        version,
        _ensure_identifier(message_id, field_name="message_id"),
        _ensure_identifier(interaction_id, field_name="interaction_id", allow_none=True),
        _ensure_strict_int(sequence, field_name="sequence", non_negative=True),
        _ensure_monotonic(emitted_at_monotonic_s, field_name="emitted_at_monotonic_s"),
    )


def _validate_command_interaction_id(command: WorkerCommandType, interaction_id: str | None) -> None:
    if command in _PROCESS_COMMANDS and interaction_id is not None:
        raise _protocol_error(ERR_IDENTIFIER, f"{command.value} requires interaction_id=None")
    if command in _INTERACTION_COMMANDS and interaction_id is None:
        raise _protocol_error(ERR_IDENTIFIER, f"{command.value} requires interaction_id")


def _validate_event_interaction_id(event: WorkerEventType, interaction_id: str | None) -> None:
    if event in _PROCESS_EVENTS and interaction_id is not None:
        raise _protocol_error(ERR_IDENTIFIER, f"{event.value} requires interaction_id=None")
    if event in _INTERACTION_EVENTS and interaction_id is None:
        raise _protocol_error(ERR_IDENTIFIER, f"{event.value} requires interaction_id")
    if event not in _PROCESS_EVENTS and event not in _INTERACTION_EVENTS and event not in _FLEXIBLE_EVENTS:
        raise _protocol_error(ERR_IDENTIFIER, f"unknown event interaction_id policy: {event.value}")


def _validate_event_payload(event: WorkerEventType, payload: Mapping[str, object]) -> None:
    if event is WorkerEventType.COMMAND_ACCEPTED:
        command = payload.get("command")
        if type(command) is not str or command not in {item.value for item in WorkerCommandType}:
            raise _protocol_error(ERR_MISSING_KEY, "command_accepted payload requires a valid command")
        if "message_id" not in payload:
            raise _protocol_error(ERR_MISSING_KEY, "command_accepted payload requires message_id")
        _ensure_identifier(payload.get("message_id"), field_name="command_accepted.message_id")
    elif event is WorkerEventType.FAILED:
        code = payload.get("code")
        if type(code) is not str or not code or len(code) > MAX_IDENTIFIER_LENGTH:
            raise _protocol_error(ERR_MISSING_KEY, "failed payload requires a bounded non-empty code")
        message = payload.get("message")
        if type(message) is not str or not message or len(message) > MAX_PAYLOAD_STRING_LENGTH:
            raise _protocol_error(ERR_MISSING_KEY, "failed payload requires a bounded non-empty message")


@dataclass(frozen=True, slots=True)
class InteractionContext:
    interaction_id: str
    tour_id: str | None = None
    waypoint_id: str | None = None
    locale: str = "es-AR"
    timeout_s: float = 30.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "interaction_id",
            _ensure_identifier(self.interaction_id, field_name="interaction_id"),
        )
        if self.tour_id is not None:
            object.__setattr__(self, "tour_id", _ensure_identifier(self.tour_id, field_name="tour_id"))
        if self.waypoint_id is not None:
            object.__setattr__(
                self,
                "waypoint_id",
                _ensure_identifier(self.waypoint_id, field_name="waypoint_id"),
            )
        if type(self.locale) is not str or not self.locale:
            raise ValueError("locale must be a non-empty string")
        if type(self.timeout_s) not in (int, float) or not math.isfinite(float(self.timeout_s)) or self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive and finite")
        object.__setattr__(self, "timeout_s", float(self.timeout_s))
        object.__setattr__(self, "metadata", _freeze_payload(self.metadata))


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

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "InteractionRuntimeCapabilities":
        fields = cls.__dataclass_fields__.keys()
        missing = set(fields) - set(payload.keys())
        extra = set(payload.keys()) - set(fields)
        if missing:
            raise _protocol_error(ERR_MISSING_KEY, f"missing capability keys: {sorted(missing)}")
        if extra:
            raise _protocol_error(ERR_UNKNOWN_KEY, f"unknown capability keys: {sorted(extra)}")
        values: dict[str, bool] = {}
        for key in fields:
            value = payload[key]
            if type(value) is not bool:
                raise _protocol_error(ERR_TYPE, f"capability {key} must be bool")
            values[key] = value
        return cls(**values)


@dataclass(frozen=True, slots=True)
class InteractionRuntimeHealth:
    protocol_version: int
    state: InteractionRuntimeState
    ready: bool
    capabilities: InteractionRuntimeCapabilities
    last_heartbeat_monotonic_s: float | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int or self.protocol_version != INTERACTION_PROTOCOL_VERSION:
            raise ValueError(f"protocol_version must be {INTERACTION_PROTOCOL_VERSION}")
        if type(self.ready) is not bool:
            raise ValueError("ready must be bool")
        if self.last_heartbeat_monotonic_s is not None:
            heartbeat = _ensure_monotonic(
                self.last_heartbeat_monotonic_s,
                field_name="last_heartbeat_monotonic_s",
            )
            object.__setattr__(self, "last_heartbeat_monotonic_s", heartbeat)
        if self.last_error is not None and (type(self.last_error) is not str or not self.last_error):
            raise ValueError("last_error must be a non-empty string when provided")


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
        if not isinstance(self.command, WorkerCommandType):
            raise _protocol_error(ERR_TYPE, "command must be WorkerCommandType")
        version, message_id, interaction_id, sequence, emitted_at = _validate_common(
            protocol_version=self.protocol_version,
            message_id=self.message_id,
            interaction_id=self.interaction_id,
            sequence=self.sequence,
            emitted_at_monotonic_s=self.emitted_at_monotonic_s,
        )
        _validate_command_interaction_id(self.command, interaction_id)
        object.__setattr__(self, "protocol_version", version)
        object.__setattr__(self, "message_id", message_id)
        object.__setattr__(self, "interaction_id", interaction_id)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "emitted_at_monotonic_s", emitted_at)
        object.__setattr__(self, "payload", _freeze_payload(self.payload))

    def to_wire_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "interaction_id": self.interaction_id,
            "command": self.command.value,
            "sequence": self.sequence,
            "emitted_at_monotonic_s": self.emitted_at_monotonic_s,
            "payload": _thaw_json_value(self.payload),
        }

    @classmethod
    def from_wire_dict(cls, raw: Mapping[str, object]) -> "WorkerCommandEnvelope":
        required = _ENVELOPE_REQUIRED_KEYS | {"command"}
        _validate_keys(raw, required)
        raw_command = raw["command"]
        if type(raw_command) is not str:
            raise _protocol_error(ERR_TYPE, "command must be a string")
        try:
            command = WorkerCommandType(raw_command)
        except ValueError as exc:
            raise _protocol_error(ERR_TYPE, f"invalid command value: {raw_command!r}") from exc
        return cls(
            protocol_version=raw["protocol_version"],  # type: ignore[arg-type]
            message_id=raw["message_id"],  # type: ignore[arg-type]
            interaction_id=raw["interaction_id"],  # type: ignore[arg-type]
            command=command,
            sequence=raw["sequence"],  # type: ignore[arg-type]
            emitted_at_monotonic_s=raw["emitted_at_monotonic_s"],  # type: ignore[arg-type]
            payload=raw["payload"],  # type: ignore[arg-type]
        )


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
        if not isinstance(self.event, WorkerEventType):
            raise _protocol_error(ERR_TYPE, "event must be WorkerEventType")
        version, message_id, interaction_id, sequence, emitted_at = _validate_common(
            protocol_version=self.protocol_version,
            message_id=self.message_id,
            interaction_id=self.interaction_id,
            sequence=self.sequence,
            emitted_at_monotonic_s=self.emitted_at_monotonic_s,
        )
        _validate_event_interaction_id(self.event, interaction_id)
        frozen_payload = _freeze_payload(self.payload)
        _validate_event_payload(self.event, frozen_payload)
        object.__setattr__(self, "protocol_version", version)
        object.__setattr__(self, "message_id", message_id)
        object.__setattr__(self, "interaction_id", interaction_id)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "emitted_at_monotonic_s", emitted_at)
        object.__setattr__(self, "payload", frozen_payload)

    def to_wire_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "interaction_id": self.interaction_id,
            "event": self.event.value,
            "sequence": self.sequence,
            "emitted_at_monotonic_s": self.emitted_at_monotonic_s,
            "payload": _thaw_json_value(self.payload),
        }

    @classmethod
    def from_wire_dict(cls, raw: Mapping[str, object]) -> "WorkerEventEnvelope":
        required = _ENVELOPE_REQUIRED_KEYS | {"event"}
        _validate_keys(raw, required)
        raw_event = raw["event"]
        if type(raw_event) is not str:
            raise _protocol_error(ERR_TYPE, "event must be a string")
        try:
            event = WorkerEventType(raw_event)
        except ValueError as exc:
            raise _protocol_error(ERR_TYPE, f"invalid event value: {raw_event!r}") from exc
        return cls(
            protocol_version=raw["protocol_version"],  # type: ignore[arg-type]
            message_id=raw["message_id"],  # type: ignore[arg-type]
            interaction_id=raw["interaction_id"],  # type: ignore[arg-type]
            event=event,
            sequence=raw["sequence"],  # type: ignore[arg-type]
            emitted_at_monotonic_s=raw["emitted_at_monotonic_s"],  # type: ignore[arg-type]
            payload=raw["payload"],  # type: ignore[arg-type]
        )


def _validate_keys(raw: Mapping[str, object], required: frozenset[str]) -> None:
    missing = required - set(raw.keys())
    if missing:
        raise _protocol_error(ERR_MISSING_KEY, f"missing required keys: {sorted(missing)}")
    unknown = set(raw.keys()) - required
    if unknown:
        raise _protocol_error(ERR_UNKNOWN_KEY, f"unknown keys: {sorted(unknown)}")


@runtime_checkable
class InteractionRuntimePort(Protocol):
    """Minimum interface for a supervised interaction runtime."""

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

    async def next_event(self, *, timeout_s: float | None = None) -> WorkerEventEnvelope:
        ...

    async def close(self) -> None:
        ...


__all__ = [
    "ERR_CONTAINER_ITEMS",
    "ERR_CORRELATION",
    "ERR_DEPTH",
    "ERR_DUPLICATE_MESSAGE_ID",
    "ERR_FRAMING",
    "ERR_IDENTIFIER",
    "ERR_JSON",
    "ERR_JSON_UNSAFE",
    "ERR_LINE_TOO_LARGE",
    "ERR_MESSAGE_LIMIT",
    "ERR_MISSING_KEY",
    "ERR_NON_FINITE",
    "ERR_RANGE",
    "ERR_SEQUENCE",
    "ERR_SIZE",
    "ERR_STALE_INTERACTION",
    "ERR_STATE",
    "ERR_TYPE",
    "ERR_UNKNOWN_KEY",
    "ERR_UTF8",
    "ERR_VERSION",
    "INTERACTION_PROTOCOL_VERSION",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_PAYLOAD_CONTAINER_ITEMS",
    "MAX_PAYLOAD_DEPTH",
    "MAX_PAYLOAD_SERIALIZED_BYTES",
    "MAX_PAYLOAD_STRING_LENGTH",
    "SIGNED_INTEGER_MAX",
    "SIGNED_INTEGER_MIN",
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
