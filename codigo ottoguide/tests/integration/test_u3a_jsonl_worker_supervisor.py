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
    ERR_FRAMING,
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
    max_seen_message_ids: int = 4096,
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
        max_seen_message_ids=max_seen_message_ids,
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


@pytest.mark.asyncio
async def test_emergency_remains_latched_after_worker_exit_and_heartbeat_deadline() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config(heartbeat_timeout_s=0.15))
    await supervisor.start()
    try:
        await supervisor.emergency_stop()
        await asyncio.sleep(0.35)
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.EMERGENCY
        assert health.ready is False
        assert supervisor.active_interaction_id is None
        assert supervisor.termination is not None
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.activate(InteractionContext(interaction_id="interaction:after-emergency"))
        assert not any(task.get_name() == "interaction-jsonl-heartbeat-monitor" and not task.done() for task in supervisor._tasks)  # noqa: SLF001
    finally:
        await supervisor.close()
        assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED


@pytest.mark.asyncio
async def test_missing_newline_is_rejected_with_stable_framing_code() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("missing_newline"))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        assert supervisor.termination is not None
        assert supervisor.termination.protocol_error_code == ERR_FRAMING
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_event_queue_overflow_closes_stream_after_pending_events() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config(event_queue_size=1))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        drained: list[WorkerEventType] = []
        for _ in range(5):
            try:
                item = await supervisor.next_event(timeout_s=0.2)
            except InteractionRuntimeUnavailableError:
                break
            drained.append(item.event)
        assert drained
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.next_event(timeout_s=0.1)
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_graceful_emergency_and_forced_terminations_are_recorded() -> None:
    graceful = JsonlInteractionWorkerSupervisor(_config())
    await graceful.start()
    await graceful.close()
    assert graceful.termination is not None
    assert graceful.termination.unexpected is False

    emergency = JsonlInteractionWorkerSupervisor(_config())
    await emergency.start()
    try:
        await emergency.emergency_stop()
        await asyncio.sleep(0.1)
        assert emergency.termination is not None
        assert emergency.termination.unexpected is False
    finally:
        await emergency.close()

    stubborn = JsonlInteractionWorkerSupervisor(_config("ignore_close"))
    await stubborn.start()
    await stubborn.close()
    assert stubborn.termination is not None
    assert stubborn.termination.unexpected is False


@pytest.mark.asyncio
async def test_seen_message_id_limit_is_bounded_and_fail_closed() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("message_limit", max_seen_message_ids=8))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        with pytest.raises(InteractionRuntimeUnavailableError):
            for _ in range(40):
                await supervisor.next_event(timeout_s=0.3)
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.FAILED
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_process_level_failed_event_fails_runtime() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("process_failed"))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.FAILED
        assert supervisor.termination is not None
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_interaction_failed_returns_to_ready() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("interaction_failed"))
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        seen = await _collect_until(supervisor, WorkerEventType.FAILED)
        assert WorkerEventType.FAILED in seen
        assert supervisor.active_interaction_id is None
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.READY
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_oversized_stderr_line_is_drained_without_deadlock() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("stderr_long_line"))
    await supervisor.start()
    try:
        await asyncio.sleep(0.2)
        health = await supervisor.health()
        assert health.ready is True
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_command_accepted_requires_correlation_payload() -> None:
    from src.interaction.runtime_port import WorkerEventEnvelope

    base = dict(
        protocol_version=1,
        message_id="evt:bad",
        interaction_id=None,
        event="command_accepted",
        sequence=0,
        emitted_at_monotonic_s=1.0,
    )
    with pytest.raises(Exception):
        WorkerEventEnvelope.from_wire_dict({**base, "payload": {}})
    with pytest.raises(Exception):
        WorkerEventEnvelope.from_wire_dict({**base, "payload": {"command": "start"}})


@pytest.mark.asyncio
async def test_failed_requires_error_payload() -> None:
    from src.interaction.runtime_port import WorkerEventEnvelope

    base = dict(
        protocol_version=1,
        message_id="evt:bad-failed",
        interaction_id=None,
        event="failed",
        sequence=0,
        emitted_at_monotonic_s=1.0,
    )
    with pytest.raises(Exception):
        WorkerEventEnvelope.from_wire_dict({**base, "payload": {}})
    with pytest.raises(Exception):
        WorkerEventEnvelope.from_wire_dict({**base, "payload": {"code": "X"}})
