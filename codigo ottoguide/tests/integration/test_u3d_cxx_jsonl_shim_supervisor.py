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
) -> list[WorkerEventType]:
    seen: list[WorkerEventType] = []
    for _ in range(limit):
        item = await supervisor.next_event(timeout_s=2.0)
        seen.append(item.event)
        if item.event == event:
            return seen
    raise AssertionError(f"did not see {event}; saw {seen}")


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
        assert WorkerEventType.WAKE_WORD_CONFIRMED in seen
        assert WorkerEventType.CAPTURE_STARTED in seen
        assert WorkerEventType.TRANSCRIPT_READY in seen
        assert WorkerEventType.RESPONSE_READY in seen
        assert WorkerEventType.PLAYBACK_STARTED in seen
        assert seen[-1] == WorkerEventType.PLAYBACK_COMPLETED
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
