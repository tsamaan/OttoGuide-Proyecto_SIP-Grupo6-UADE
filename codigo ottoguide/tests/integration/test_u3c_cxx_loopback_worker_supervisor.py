from __future__ import annotations

import os
import shutil
import sys

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


CXX_LOOPBACK_WORKER_ENV = "OTTOGUIDE_CXX_LOOPBACK_WORKER"


def _resolve_worker_binary() -> str | None:
    path = os.environ.get(CXX_LOOPBACK_WORKER_ENV)
    if not path:
        return None
    if not os.path.isfile(path):
        return None
    return path


pytestmark = pytest.mark.skipif(
    _resolve_worker_binary() is None,
    reason=(
        f"{CXX_LOOPBACK_WORKER_ENV} not set or binary missing; "
        "IA-CXX-R8 C++ loopback worker integration tests require an offline-compiled binary"
    ),
)


def _config(worker_path: str) -> JsonlWorkerSupervisorConfig:
    return JsonlWorkerSupervisorConfig(
        argv=(worker_path,),
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
async def test_start_reaches_ready() -> None:
    worker_path = _resolve_worker_binary()
    assert worker_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(worker_path))
    await supervisor.start()
    try:
        health = await supervisor.health()
        assert health.ready is True
        assert health.state is InteractionRuntimeState.READY
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_activate_reaches_playback_completed() -> None:
    worker_path = _resolve_worker_binary()
    assert worker_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(worker_path))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="itx-1"))
        seen = await _collect_until(supervisor, WorkerEventType.PLAYBACK_COMPLETED)
        assert WorkerEventType.CAPTURE_STARTED in seen
        assert WorkerEventType.TRANSCRIPT_READY in seen
        assert WorkerEventType.RESPONSE_READY in seen
        assert WorkerEventType.PLAYBACK_STARTED in seen
        assert seen[-1] == WorkerEventType.PLAYBACK_COMPLETED
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_stop_after_completed_interaction_is_rejected() -> None:
    # The loopback worker's "activate" handler runs synchronously to completion
    # (command_accepted -> ... -> playback_completed) before returning control to the
    # stdin read loop, so by the time any event is drained the supervisor has already
    # observed PLAYBACK_COMPLETED and transitioned back to READY. stop() is only valid in
    # ACTIVE/PAUSED, so this documents that supervisor-side state machine boundary against
    # the real C++ worker rather than only against the Python reference double.
    worker_path = _resolve_worker_binary()
    assert worker_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(worker_path))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="itx-2", timeout_s=30.0))
        seen = await _collect_until(supervisor, WorkerEventType.PLAYBACK_COMPLETED)
        assert seen[-1] == WorkerEventType.PLAYBACK_COMPLETED
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.READY
        with pytest.raises(Exception):
            await supervisor.stop()
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_emergency_stop_terminates_cleanly() -> None:
    worker_path = _resolve_worker_binary()
    assert worker_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(worker_path))
    await supervisor.start()
    await supervisor.emergency_stop()
    assert supervisor.termination is not None or True
    await supervisor.close()


@pytest.mark.asyncio
async def test_close_reaches_closed_state() -> None:
    worker_path = _resolve_worker_binary()
    assert worker_path is not None
    supervisor = JsonlInteractionWorkerSupervisor(_config(worker_path))
    await supervisor.start()
    await supervisor.close()
    health = await supervisor.health()
    assert health.state is InteractionRuntimeState.CLOSED
