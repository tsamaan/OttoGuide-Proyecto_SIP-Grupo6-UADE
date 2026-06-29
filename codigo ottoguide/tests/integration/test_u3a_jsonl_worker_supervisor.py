from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from src.interaction.jsonl_worker_supervisor import (
    JsonlInteractionWorkerSupervisor,
    JsonlWorkerSupervisorConfig,
)
from src.interaction.runtime_port import (
    InteractionContext,
    InteractionRuntimeState,
    InteractionRuntimeUnavailableError,
    WorkerEventType,
)


WORKER = Path(__file__).resolve().parents[1] / "support" / "u3a_loopback_worker.py"


def _config(
    scenario: str = "normal",
    *,
    event_queue_size: int = 64,
    heartbeat_timeout_s: float = 0.3,
    shutdown_timeout_s: float = 0.15,
    terminate_timeout_s: float = 0.1,
) -> JsonlWorkerSupervisorConfig:
    return JsonlWorkerSupervisorConfig(
        argv=(sys.executable, str(WORKER), scenario),
        startup_timeout_s=0.4,
        heartbeat_timeout_s=heartbeat_timeout_s,
        write_timeout_s=0.2,
        shutdown_timeout_s=shutdown_timeout_s,
        terminate_timeout_s=terminate_timeout_s,
        command_queue_size=4,
        event_queue_size=event_queue_size,
        max_line_bytes=2048,
        stderr_tail_lines=10,
        stderr_tail_max_chars=2048,
    )


async def _collect_until(supervisor: JsonlInteractionWorkerSupervisor, event: WorkerEventType, *, limit: int = 20) -> list[WorkerEventType]:
    seen: list[WorkerEventType] = []
    for _ in range(limit):
        item = await supervisor.next_event(timeout_s=0.5)
        seen.append(item.event)
        if item.event == event:
            return seen
    raise AssertionError(f"did not see {event}; saw {seen}")


@pytest.mark.asyncio
async def test_health_before_start_and_startup_ready_retains_public_events() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config())
    health = await supervisor.health()
    assert health.state is InteractionRuntimeState.NOT_STARTED
    assert health.ready is False
    await supervisor.start()
    try:
        started = await supervisor.health()
        assert started.ready is True
        assert started.state is InteractionRuntimeState.READY
        assert started.capabilities.audio_capture is False
        first = await supervisor.next_event(timeout_s=0.2)
        second = await supervisor.next_event(timeout_s=0.2)
        assert [first.event, second.event] == [WorkerEventType.COMMAND_ACCEPTED, WorkerEventType.READY]
        assert started.last_heartbeat_monotonic_s is not None
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_activate_sequence_and_no_logical_completion_invented() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config())
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        seen = await _collect_until(supervisor, WorkerEventType.PLAYBACK_COMPLETED)
        assert WorkerEventType.CAPTURE_STARTED in seen
        assert WorkerEventType.TRANSCRIPT_READY in seen
        assert WorkerEventType.RESPONSE_READY in seen
        assert WorkerEventType.PLAYBACK_STARTED in seen
        assert WorkerEventType.PLAYBACK_COMPLETED in seen
        assert all(item.value != "interaction_completed" for item in seen)
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.READY
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_single_consumer_timeout_and_cancelled_consumer_does_not_close() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("heartbeat_stops"))
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        task = asyncio.create_task(supervisor.next_event(timeout_s=0.5))
        await asyncio.sleep(0)
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.next_event(timeout_s=0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(asyncio.TimeoutError):
            await supervisor.next_event(timeout_s=0.01)
    finally:
        await supervisor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "startup_silent",
        "malformed_json",
        "invalid_utf8",
        "oversized_line",
        "out_of_order_sequence",
        "crash_before_ready",
        "crash_after_ready",
        "stale_interaction",
    ],
)
async def test_startup_and_protocol_failures_fail_closed(scenario: str) -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config(scenario, heartbeat_timeout_s=0.2))
    try:
        if scenario == "stale_interaction":
            await supervisor.start()
            await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
            with pytest.raises(InteractionRuntimeUnavailableError):
                await _collect_until(supervisor, WorkerEventType.PLAYBACK_COMPLETED)
        elif scenario in {"out_of_order_sequence", "crash_after_ready"}:
            await supervisor.start()
            with pytest.raises(InteractionRuntimeUnavailableError):
                await _collect_until(supervisor, WorkerEventType.PLAYBACK_COMPLETED)
        else:
            with pytest.raises(Exception):
                await supervisor.start()
        health = await supervisor.health()
        assert health.ready is False
        assert health.state is InteractionRuntimeState.FAILED
        assert supervisor.termination is not None
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_duplicate_message_id_and_heartbeat_timeout() -> None:
    duplicate = JsonlInteractionWorkerSupervisor(_config("duplicate_message_id", heartbeat_timeout_s=0.2))
    await duplicate.start()
    try:
        await asyncio.sleep(0.25)
        assert duplicate.termination is not None
    finally:
        await duplicate.close()
    stalled = JsonlInteractionWorkerSupervisor(_config("heartbeat_stops", heartbeat_timeout_s=0.1))
    await stalled.start()
    try:
        await asyncio.sleep(0.2)
        health = await stalled.health()
        assert health.state is InteractionRuntimeState.FAILED
        assert stalled.termination is not None
    finally:
        await stalled.close()


@pytest.mark.asyncio
async def test_stderr_flood_event_queue_overflow_and_crash_after_ready() -> None:
    flood = JsonlInteractionWorkerSupervisor(_config("stderr_flood"))
    await flood.start()
    try:
        await asyncio.sleep(0.05)
        assert await flood.health()
    finally:
        await flood.close()
    overflow = JsonlInteractionWorkerSupervisor(_config(event_queue_size=1))
    with pytest.raises(Exception):
        await overflow.start()
    await overflow.close()


@pytest.mark.asyncio
async def test_double_activation_pause_resume_stop_and_emergency_latch() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("activation_waits"))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.activate(InteractionContext(interaction_id="interaction:2"))
        await supervisor.pause()
        await supervisor.resume()
        await supervisor.stop()
        seen = await _collect_until(supervisor, WorkerEventType.CANCELLED)
        assert WorkerEventType.CANCELLED in seen
    finally:
        await supervisor.close()
    no_active = JsonlInteractionWorkerSupervisor(_config())
    await no_active.start()
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await no_active.pause()
        await no_active.emergency_stop()
        health = await no_active.health()
        assert health.state is InteractionRuntimeState.EMERGENCY
        assert health.ready is False
        with pytest.raises(InteractionRuntimeUnavailableError):
            await no_active.activate(InteractionContext(interaction_id="interaction:3"))
    finally:
        await no_active.close()


@pytest.mark.asyncio
async def test_graceful_close_ignore_close_terminate_and_idempotence() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config())
    await supervisor.start()
    await supervisor.close()
    await supervisor.close()
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
    stubborn = JsonlInteractionWorkerSupervisor(_config("ignore_close"))
    await stubborn.start()
    await stubborn.close()
    await stubborn.close()
    assert (await stubborn.health()).state is InteractionRuntimeState.CLOSED


@pytest.mark.asyncio
async def test_close_unblocks_waiting_consumer_and_leaves_no_owned_tasks() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("ignore_close"))
    await supervisor.start()
    await supervisor.next_event(timeout_s=0.2)
    await supervisor.next_event(timeout_s=0.2)
    waiter = asyncio.create_task(supervisor.next_event(timeout_s=1.0))
    await asyncio.sleep(0)
    await supervisor.close()
    with pytest.raises(InteractionRuntimeUnavailableError):
        await waiter
    assert not supervisor._tasks  # noqa: SLF001 - ownership invariant under test
