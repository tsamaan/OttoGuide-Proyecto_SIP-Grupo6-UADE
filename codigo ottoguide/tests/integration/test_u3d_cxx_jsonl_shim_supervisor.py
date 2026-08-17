from __future__ import annotations

import os

import pytest

from src.interaction.jsonl_worker_supervisor import (
    JsonlInteractionWorkerSupervisor,
    JsonlWorkerSupervisorConfig,
)
from src.interaction.runtime_port import (
    InteractionContext,
    InteractionRuntimeState,
    WorkerEventEnvelope,
    WorkerEventType,
)


OTTO_JSONL_SHIM_BIN_ENV = "OTTO_JSONL_SHIM_BIN"


def _resolve_shim_binary() -> str | None:
    path = os.environ.get(OTTO_JSONL_SHIM_BIN_ENV)
    if not path:
        return None
    if not os.path.isfile(path):
        return None
    return path


pytestmark = pytest.mark.skipif(
    _resolve_shim_binary() is None,
    reason=(
        f"{OTTO_JSONL_SHIM_BIN_ENV} not set or binary missing; "
        "IA-CXX-R12A supervisor<->otto_jsonl_shim integration tests require an "
        "offline-compiled binary"
    ),
)


def _config(shim_path: str) -> JsonlWorkerSupervisorConfig:
    return JsonlWorkerSupervisorConfig(
        argv=(shim_path,),
        startup_timeout_s=2.0,
        heartbeat_timeout_s=5.0,
        write_timeout_s=1.0,
        shutdown_timeout_s=1.0,
        terminate_timeout_s=1.0,
        command_queue_size=4,
        event_queue_size=32,
        max_line_bytes=4096,
        stderr_tail_lines=10,
        stderr_tail_max_chars=2048,
    )


async def _collect_until(
    supervisor: JsonlInteractionWorkerSupervisor, event: WorkerEventType, *, limit: int = 20
) -> list[WorkerEventEnvelope]:
    seen: list[WorkerEventEnvelope] = []
    for _ in range(limit):
        item = await supervisor.next_event(timeout_s=2.0)
        seen.append(item)
        if item.event == event:
            return seen
    seen_types = [envelope.event for envelope in seen]
    raise AssertionError(f"did not see {event}; saw {seen_types}")


@pytest.mark.asyncio
async def test_start_reaches_ready_with_mock_capabilities() -> None:
    shim_path = _resolve_shim_binary()
    assert shim_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(shim_path))
    await supervisor.start()
    try:
        health = await supervisor.health()
        assert health.ready is True
        assert health.state is InteractionRuntimeState.READY
        # otto_jsonl_shim (IA-CXX-R11) reports every capability as false: it is a
        # mocked dispatch loop, not a real audio/STT/LLM/TTS runtime.
        assert health.capabilities.audio_capture is False
        assert health.capabilities.stt is False
        assert health.capabilities.local_llm is False
        assert health.capabilities.spanish_tts is False
        assert health.capabilities.physical_playback is False
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_health_command_accepted() -> None:
    shim_path = _resolve_shim_binary()
    assert shim_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(shim_path))
    await supervisor.start()
    try:
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.READY
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_activate_reaches_mock_playback_completed() -> None:
    shim_path = _resolve_shim_binary()
    assert shim_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(shim_path))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="itx-r12a-1"))
        seen = await _collect_until(supervisor, WorkerEventType.PLAYBACK_COMPLETED)
        seen_types = [envelope.event for envelope in seen]
        assert WorkerEventType.WAKE_WORD_CONFIRMED in seen_types
        assert WorkerEventType.CAPTURE_STARTED in seen_types
        assert WorkerEventType.TRANSCRIPT_READY in seen_types
        assert WorkerEventType.RESPONSE_READY in seen_types
        assert WorkerEventType.PLAYBACK_STARTED in seen_types
        assert seen_types[-1] == WorkerEventType.PLAYBACK_COMPLETED

        # otto_jsonl_shim (IA-CXX-R11) hardcodes these exact mock payloads for
        # transcript_ready/response_ready; assert the literal text, not just event presence,
        # per the observation raised in R12B (OBSERVATION_PAYLOAD_TEXT_NOT_ASSERTED).
        transcript_ready = next(
            envelope for envelope in seen if envelope.event is WorkerEventType.TRANSCRIPT_READY
        )
        assert transcript_ready.payload["text"] == "hola otto"

        response_ready = next(
            envelope for envelope in seen if envelope.event is WorkerEventType.RESPONSE_READY
        )
        assert response_ready.payload["text"] == "respuesta mock"

        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.READY
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_close_reaches_closed_state() -> None:
    shim_path = _resolve_shim_binary()
    assert shim_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(shim_path))
    await supervisor.start()
    await supervisor.close()
    health = await supervisor.health()
    assert health.state is InteractionRuntimeState.CLOSED


@pytest.mark.asyncio
async def test_activate_with_reserved_id_emits_semantic_rejection() -> None:
    # IA-CXX-R14B (ALT_2_INTERACTION_ID_RESERVED): the shim recognizes the reserved
    # interaction_id "itx-r14-semantic-reject" and deterministically emits a `failed` event
    # scoped to that interaction (non-null interaction_id) instead of the happy path.
    shim_path = _resolve_shim_binary()
    assert shim_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(shim_path))
    await supervisor.start()
    try:
        await supervisor.activate(
            InteractionContext(interaction_id="itx-r14-semantic-reject")
        )
        seen = await _collect_until(supervisor, WorkerEventType.FAILED)
        seen_types = [envelope.event for envelope in seen]
        assert WorkerEventType.TRANSCRIPT_READY not in seen_types
        assert WorkerEventType.RESPONSE_READY not in seen_types
        assert WorkerEventType.PLAYBACK_COMPLETED not in seen_types

        failed = seen[-1]
        assert failed.interaction_id == "itx-r14-semantic-reject"
        assert failed.payload["code"] == "ERR_SEMANTIC_REJECTED"
        assert isinstance(failed.payload["message"], str)
        assert failed.payload["message"] != ""

        # Interaction-scoped FAILED must return the supervisor to READY, not terminate the
        # worker (that only happens for process-level FAILED, interaction_id=None).
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.READY
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_activate_with_reserved_id_emits_interaction_timeout() -> None:
    # IA-CXX-R14B (ALT_2_INTERACTION_ID_RESERVED): the shim recognizes the reserved
    # interaction_id "itx-r14-timeout" and deterministically emits `interaction_timeout`
    # immediately (simulated, not awaited via sleep) instead of the happy path.
    shim_path = _resolve_shim_binary()
    assert shim_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(shim_path))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="itx-r14-timeout"))
        seen = await _collect_until(supervisor, WorkerEventType.INTERACTION_TIMEOUT)
        seen_types = [envelope.event for envelope in seen]
        assert WorkerEventType.TRANSCRIPT_READY not in seen_types
        assert WorkerEventType.RESPONSE_READY not in seen_types
        assert WorkerEventType.PLAYBACK_COMPLETED not in seen_types

        timeout_envelope = seen[-1]
        assert timeout_envelope.interaction_id == "itx-r14-timeout"

        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.READY
    finally:
        await supervisor.close()
