from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from src.interaction.runtime_port import (
    ERR_CONTAINER_ITEMS,
    ERR_DEPTH,
    ERR_IDENTIFIER,
    ERR_JSON_UNSAFE,
    ERR_MISSING_KEY,
    ERR_NON_FINITE,
    ERR_RANGE,
    ERR_SIZE,
    ERR_TYPE,
    ERR_UNKNOWN_KEY,
    INTERACTION_PROTOCOL_VERSION,
    MAX_PAYLOAD_CONTAINER_ITEMS,
    MAX_PAYLOAD_DEPTH,
    MAX_PAYLOAD_SERIALIZED_BYTES,
    MAX_PAYLOAD_STRING_LENGTH,
    SIGNED_INTEGER_MAX,
    InteractionContext,
    InteractionRuntimeProtocolError,
    WorkerCommandEnvelope,
    WorkerCommandType,
    WorkerEventEnvelope,
    WorkerEventType,
)


def _command_wire(**overrides: object) -> dict[str, object]:
    wire: dict[str, object] = {
        "protocol_version": INTERACTION_PROTOCOL_VERSION,
        "message_id": "cmd:1",
        "interaction_id": "interaction:1",
        "command": "activate",
        "sequence": 0,
        "emitted_at_monotonic_s": 1.0,
        "payload": {"nested": {"items": [1, True, None]}},
    }
    wire.update(overrides)
    return wire


def _event_wire(**overrides: object) -> dict[str, object]:
    wire: dict[str, object] = {
        "protocol_version": INTERACTION_PROTOCOL_VERSION,
        "message_id": "evt:1",
        "interaction_id": None,
        "event": "ready",
        "sequence": 0,
        "emitted_at_monotonic_s": 1.0,
        "payload": {
            "audio_capture": False,
            "wake_word": False,
            "vad": False,
            "stt": False,
            "local_llm": False,
            "spanish_tts": False,
            "physical_playback": False,
            "physical_playback_stop": False,
            "physical_playback_completion": False,
        },
    }
    wire.update(overrides)
    return wire


def _raises_code(code: str, func, *args, **kwargs) -> None:
    with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
        func(*args, **kwargs)
    assert excinfo.value.code == code


def test_command_and_event_roundtrip() -> None:
    command = WorkerCommandEnvelope.from_wire_dict(_command_wire())
    assert WorkerCommandEnvelope.from_wire_dict(command.to_wire_dict()) == command
    event = WorkerEventEnvelope.from_wire_dict(_event_wire())
    assert WorkerEventEnvelope.from_wire_dict(event.to_wire_dict()) == event


@pytest.mark.parametrize("field", ["protocol_version", "sequence"])
def test_bool_as_int_rejected(field: str) -> None:
    _raises_code(ERR_TYPE, WorkerCommandEnvelope.from_wire_dict, _command_wire(**{field: True}))


@pytest.mark.parametrize("field", ["protocol_version", "sequence", "emitted_at_monotonic_s"])
def test_numeric_strings_rejected(field: str) -> None:
    _raises_code(ERR_TYPE, WorkerCommandEnvelope.from_wire_dict, _command_wire(**{field: "1"}))


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_timestamp_rejected(value: float) -> None:
    _raises_code(ERR_NON_FINITE, WorkerCommandEnvelope.from_wire_dict, _command_wire(emitted_at_monotonic_s=value))


@pytest.mark.parametrize("value", ["", "x" * 81, "ñ", "bad space"])
def test_invalid_identifiers_rejected(value: str) -> None:
    _raises_code(ERR_IDENTIFIER, WorkerCommandEnvelope.from_wire_dict, _command_wire(message_id=value))


def test_missing_and_unknown_keys_have_stable_codes() -> None:
    missing = _command_wire()
    del missing["payload"]
    _raises_code(ERR_MISSING_KEY, WorkerCommandEnvelope.from_wire_dict, missing)
    _raises_code(ERR_UNKNOWN_KEY, WorkerCommandEnvelope.from_wire_dict, _command_wire(extra=True))


def test_payload_must_be_mapping_and_json_safe() -> None:
    _raises_code(ERR_TYPE, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload=[]))
    _raises_code(ERR_JSON_UNSAFE, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload={"bad": object()}))
    _raises_code(ERR_JSON_UNSAFE, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload={"bad": {1, 2}}))


def test_integer_range_depth_items_and_string_limits() -> None:
    _raises_code(ERR_RANGE, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload={"x": SIGNED_INTEGER_MAX + 1}))
    deep: object = "leaf"
    for _ in range(MAX_PAYLOAD_DEPTH + 1):
        deep = {"x": deep}
    _raises_code(ERR_DEPTH, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload={"deep": deep}))
    _raises_code(
        ERR_CONTAINER_ITEMS,
        WorkerCommandEnvelope.from_wire_dict,
        _command_wire(payload={str(i): i for i in range(MAX_PAYLOAD_CONTAINER_ITEMS + 1)}),
    )
    _raises_code(ERR_SIZE, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload={"x": "a" * (MAX_PAYLOAD_STRING_LENGTH + 1)}))
    _raises_code(ERR_SIZE, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload={"x": "a" * MAX_PAYLOAD_SERIALIZED_BYTES}))


def test_circular_payload_rejected() -> None:
    payload: dict[str, object] = {}
    payload["self"] = payload
    _raises_code(ERR_JSON_UNSAFE, WorkerCommandEnvelope.from_wire_dict, _command_wire(payload=payload))


def test_recursive_freeze_and_deep_thaw_are_independent() -> None:
    env = WorkerCommandEnvelope.from_wire_dict(_command_wire(payload={"a": {"b": [1, {"c": "d"}]}}))
    assert isinstance(env.payload, MappingProxyType)
    assert isinstance(env.payload["a"], MappingProxyType)
    assert isinstance(env.payload["a"]["b"], tuple)  # type: ignore[index]
    wire = env.to_wire_dict()
    assert isinstance(wire["payload"], dict)
    wire["payload"]["a"]["b"][1]["c"] = "changed"  # type: ignore[index]
    assert env.payload["a"]["b"][1]["c"] == "d"  # type: ignore[index]
    with pytest.raises(TypeError):
        env.payload["a"] = "x"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        env.sequence = 4  # type: ignore[misc]


def test_interaction_context_metadata_is_recursively_frozen() -> None:
    ctx = InteractionContext(interaction_id="interaction:1", metadata={"a": {"b": [1]}})
    assert isinstance(ctx.metadata, MappingProxyType)
    assert isinstance(ctx.metadata["a"], MappingProxyType)
    assert ctx.metadata["a"]["b"] == (1,)  # type: ignore[index]


def test_command_interaction_id_rules() -> None:
    for command in ("start", "health", "close", "emergency_stop"):
        WorkerCommandEnvelope.from_wire_dict(_command_wire(command=command, interaction_id=None))
        _raises_code(ERR_IDENTIFIER, WorkerCommandEnvelope.from_wire_dict, _command_wire(command=command, interaction_id="interaction:1"))
    for command in ("activate", "pause", "resume", "stop"):
        WorkerCommandEnvelope.from_wire_dict(_command_wire(command=command, interaction_id="interaction:1"))
        _raises_code(ERR_IDENTIFIER, WorkerCommandEnvelope.from_wire_dict, _command_wire(command=command, interaction_id=None))


def test_event_interaction_id_rules_and_no_worker_completed_event() -> None:
    for event in ("ready", "heartbeat", "wake_word_confirmed", "stopped", "closed"):
        WorkerEventEnvelope.from_wire_dict(_event_wire(event=event, interaction_id=None, payload={} if event != "ready" else _event_wire()["payload"]))
        _raises_code(ERR_IDENTIFIER, WorkerEventEnvelope.from_wire_dict, _event_wire(event=event, interaction_id="interaction:1", payload={}))
    for event in ("capture_started", "transcript_ready", "response_ready", "playback_started", "playback_completed", "interaction_timeout", "cancelled"):
        WorkerEventEnvelope.from_wire_dict(_event_wire(event=event, interaction_id="interaction:1", payload={}))
        _raises_code(ERR_IDENTIFIER, WorkerEventEnvelope.from_wire_dict, _event_wire(event=event, interaction_id=None, payload={}))
    assert not hasattr(WorkerEventType, "INTERACTION_COMPLETED")


def test_command_and_event_values_must_be_strings() -> None:
    _raises_code(ERR_TYPE, WorkerCommandEnvelope.from_wire_dict, _command_wire(command=WorkerCommandType.ACTIVATE))
    _raises_code(ERR_TYPE, WorkerEventEnvelope.from_wire_dict, _event_wire(event=WorkerEventType.READY))
