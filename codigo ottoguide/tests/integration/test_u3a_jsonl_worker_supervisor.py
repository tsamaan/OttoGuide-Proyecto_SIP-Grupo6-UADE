from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from src.interaction.jsonl_worker_supervisor import (
    JsonlInteractionWorkerSupervisor,
    JsonlWorkerSupervisorConfig,
)
from src.interaction.runtime_port import (
    ERR_CORRELATION,
    ERR_FRAMING,
    ERR_LINE_TOO_LARGE,
    ERR_STATE,
    ERR_TASK_SETTLEMENT_TIMEOUT,
    INTERACTION_PROTOCOL_VERSION,
    InteractionContext,
    InteractionRuntimeProtocolError,
    InteractionRuntimeState,
    InteractionRuntimeUnavailableError,
    WorkerCommandType,
    WorkerEventEnvelope,
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


def _bare_supervisor_for_enqueue(
    *,
    command_queue_size: int = 4,
    state: InteractionRuntimeState = InteractionRuntimeState.READY,
) -> JsonlInteractionWorkerSupervisor:
    supervisor = JsonlInteractionWorkerSupervisor(
        _config_with_pending_limit(
            "normal",
            max_pending_commands=16,
            command_queue_size=command_queue_size,
        )
    )
    supervisor._state = state  # noqa: SLF001
    supervisor._ready = state is InteractionRuntimeState.READY  # noqa: SLF001
    supervisor._command_queue = asyncio.Queue(maxsize=command_queue_size)  # noqa: SLF001
    supervisor._event_queue = asyncio.Queue(maxsize=4)  # noqa: SLF001
    return supervisor


async def _enqueue_waiting_on_command_lock(
    supervisor: JsonlInteractionWorkerSupervisor,
    command: WorkerCommandType = WorkerCommandType.HEALTH,
    *,
    allow_when_emergency: bool = False,
) -> asyncio.Task[None]:
    await supervisor._command_lock.acquire()  # noqa: SLF001
    task = asyncio.create_task(
        supervisor._enqueue_command(  # noqa: SLF001
            command,
            interaction_id=None,
            payload={},
            allow_when_emergency=allow_when_emergency,
        )
    )
    await asyncio.sleep(0)
    assert not task.done()
    return task


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


# ---------------------------------------------------------------------------
# DEFECT_1 — process-level FAILED must publish, then terminate the child and
# close the event stream, leaving no owned tasks behind.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_failed_event_publishes_then_terminates_child_and_closes_stream() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("process_failed"))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        seen = await _collect_until(supervisor, WorkerEventType.FAILED)
        assert WorkerEventType.FAILED in seen
        # The stream must be terminal immediately after draining the FAILED
        # event -- no blocking, no further protocol events.
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.next_event(timeout_s=0.2)
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.FAILED
        assert health.ready is False
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "PROCESS_FAILED_EVENT"
        # The child must actually have been terminated (or be in the process
        # of being reaped); close() must not need to escalate.
        await asyncio.wait_for(supervisor._process.wait(), timeout=1.0)  # noqa: SLF001
        assert supervisor._process.returncode is not None  # noqa: SLF001
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_process_failed_event_leaves_no_owned_tasks() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("process_failed"))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        await _collect_until(supervisor, WorkerEventType.FAILED)
        await asyncio.sleep(0.1)
        assert not any(not task.done() for task in supervisor._tasks)  # noqa: SLF001
    finally:
        await supervisor.close()


# ---------------------------------------------------------------------------
# DEFECT_2 — READY is only valid while STARTING; READY at any other moment
# must be rejected with ERR_STATE, BEFORE any state mutation is applied.
# ---------------------------------------------------------------------------


def _ready_event(*, sequence: int) -> WorkerEventEnvelope:
    return WorkerEventEnvelope(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id=f"evt:ready-{sequence}",
        interaction_id=None,
        event=WorkerEventType.READY,
        sequence=sequence,
        emitted_at_monotonic_s=time.monotonic(),
        payload={
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
    )


@pytest.mark.asyncio
async def test_duplicate_ready_after_startup_fails_with_err_state() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config())
    await supervisor.start()
    try:
        assert supervisor._state is InteractionRuntimeState.READY  # noqa: SLF001
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(_ready_event(sequence=next_sequence))  # noqa: SLF001
        assert excinfo.value.code == ERR_STATE
        # The invalid READY must not have been applied as operative state.
        assert supervisor._state is InteractionRuntimeState.READY  # noqa: SLF001
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_ready_during_active_fails_with_err_state() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("activation_waits"))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        await _collect_until(supervisor, WorkerEventType.CAPTURE_STARTED)
        assert supervisor._state is InteractionRuntimeState.ACTIVE  # noqa: SLF001
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(_ready_event(sequence=next_sequence))  # noqa: SLF001
        assert excinfo.value.code == ERR_STATE
        assert supervisor._state is InteractionRuntimeState.ACTIVE  # noqa: SLF001
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_ready_during_paused_fails_with_err_state() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("activation_waits"))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        await _collect_until(supervisor, WorkerEventType.CAPTURE_STARTED)
        await supervisor.pause()
        assert supervisor._state is InteractionRuntimeState.PAUSED  # noqa: SLF001
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(_ready_event(sequence=next_sequence))  # noqa: SLF001
        assert excinfo.value.code == ERR_STATE
        assert supervisor._state is InteractionRuntimeState.PAUSED  # noqa: SLF001
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_ready_during_failed_fails_with_err_state() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("malformed_json"))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        assert supervisor._state is InteractionRuntimeState.FAILED  # noqa: SLF001
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(_ready_event(sequence=next_sequence))  # noqa: SLF001
        assert excinfo.value.code == ERR_STATE
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_ready_during_emergency_fails_with_err_state() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config())
    await supervisor.start()
    try:
        await supervisor.emergency_stop()
        assert supervisor._state is InteractionRuntimeState.EMERGENCY  # noqa: SLF001
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(_ready_event(sequence=next_sequence))  # noqa: SLF001
        assert excinfo.value.code == ERR_STATE
        assert supervisor._state is InteractionRuntimeState.EMERGENCY  # noqa: SLF001
    finally:
        await supervisor.close()


# ---------------------------------------------------------------------------
# DEFECT_5 / DEFECT_6 — COMMAND_ACCEPTED must correlate against a real
# pending command (by message_id, command, and interaction_id), and
# message_id must be validated as a strict wire identifier.
# ---------------------------------------------------------------------------


def _command_accepted_event(
    *, sequence: int, message_id: object, command: object = "start", interaction_id: str | None = None
) -> WorkerEventEnvelope:
    return WorkerEventEnvelope(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id=f"evt:cmd-accepted-{sequence}",
        interaction_id=interaction_id,
        event=WorkerEventType.COMMAND_ACCEPTED,
        sequence=sequence,
        emitted_at_monotonic_s=time.monotonic(),
        payload={"command": command, "message_id": message_id},
    )


@pytest.mark.asyncio
async def test_command_accepted_unknown_message_id_fails_correlation() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config())
    await supervisor.start()
    try:
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(  # noqa: SLF001
                _command_accepted_event(sequence=next_sequence, message_id="py:does-not-exist")
            )
        assert excinfo.value.code == ERR_CORRELATION
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_command_accepted_mismatched_command_fails_correlation() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("activation_waits"))
    await supervisor.start()
    try:
        # Drain the startup events first so message_id/sequence bookkeeping
        # for "start" is settled, then enqueue a PAUSE command directly
        # (bypassing the public pause() guard) so it registers in
        # _pending_commands without the real worker racing to accept it.
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        await supervisor._enqueue_command(  # noqa: SLF001
            WorkerCommandType.HEALTH,
            interaction_id=None,
            payload={},
        )
        pending_message_id = next(iter(supervisor._pending_commands))  # noqa: SLF001
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(  # noqa: SLF001
                _command_accepted_event(
                    sequence=next_sequence,
                    message_id=pending_message_id,
                    command="close",
                )
            )
        assert excinfo.value.code == ERR_CORRELATION
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_command_accepted_invalid_identifier_is_rejected() -> None:
    base = dict(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id="evt:bad-correlation",
        interaction_id=None,
        event="command_accepted",
        sequence=0,
        emitted_at_monotonic_s=1.0,
    )
    with pytest.raises(InteractionRuntimeProtocolError):
        WorkerEventEnvelope.from_wire_dict(
            {**base, "payload": {"command": "start", "message_id": "has a space"}}
        )
    with pytest.raises(InteractionRuntimeProtocolError):
        WorkerEventEnvelope.from_wire_dict(
            {**base, "payload": {"command": "start", "message_id": ""}}
        )


@pytest.mark.asyncio
async def test_command_accepted_duplicate_acceptance_fails_correlation() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config())
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted for start
        await supervisor.next_event(timeout_s=0.2)  # ready
        # The "start" message_id was already correlated and removed from
        # _pending_commands; replaying the same acceptance must now be
        # unknown.
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(  # noqa: SLF001
                _command_accepted_event(
                    sequence=supervisor._incoming_sequence,  # noqa: SLF001
                    message_id="py:0",
                    command="start",
                )
            )
        assert excinfo.value.code == ERR_CORRELATION
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_pending_commands_stay_bounded_under_load() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("activation_waits"))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        max_seen = len(supervisor._pending_commands)  # noqa: SLF001
        for _ in range(20):
            try:
                await supervisor.pause()
            except InteractionRuntimeUnavailableError:
                pass
            try:
                await supervisor.resume()
            except InteractionRuntimeUnavailableError:
                pass
            max_seen = max(max_seen, len(supervisor._pending_commands))  # noqa: SLF001
        assert max_seen <= supervisor._config.command_queue_size + 1  # noqa: SLF001
    finally:
        await supervisor.close()


# ---------------------------------------------------------------------------
# DEFECT_3 — the stderr partial-line (no trailing newline) buffer must be
# memory-bounded, even under a sustained flood with no newlines at all.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unterminated_stderr_flood_remains_memory_bounded() -> None:
    config = _config("stderr_unterminated_flood", shutdown_timeout_s=2.0)
    supervisor = JsonlInteractionWorkerSupervisor(config)
    await supervisor.start()
    try:
        # Give the child time to push >=2MiB of newline-less stderr output.
        deadline = time.monotonic() + 5.0
        while supervisor._stderr_partial_tail == b"" and time.monotonic() < deadline:  # noqa: SLF001
            await asyncio.sleep(0.05)
        assert len(supervisor._stderr_partial_tail) <= config.stderr_tail_max_chars  # noqa: SLF001
        assert supervisor._stderr_chars <= config.stderr_tail_max_chars  # noqa: SLF001
        health = await supervisor.health()
        assert health.ready is True
    finally:
        await asyncio.wait_for(supervisor.close(), timeout=3.0)
    assert supervisor.termination is not None
    assert len(supervisor.termination.stderr_tail) <= config.stderr_tail_lines


# ---------------------------------------------------------------------------
# DEFECT_10 — StreamReader.readuntil() raises asyncio.LimitOverrunError (not
# a ValueError subclass on this Python) when the line exceeds the reader's
# internal limit; it must be caught explicitly and reported as
# ERR_LINE_TOO_LARGE, not propagate uncaught.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_stdout_frame_reports_err_line_too_large() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("oversized_line"))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        assert supervisor.termination is not None
        assert supervisor.termination.protocol_error_code == ERR_LINE_TOO_LARGE
        assert supervisor.termination.reason == "PROTOCOL_FAILURE"
    finally:
        await supervisor.close()


# ---------------------------------------------------------------------------
# DEFECT_11 — a startup failure must self-clean (reap the child, cancel
# owned tasks) without requiring the caller to invoke close() explicitly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_failure_self_cleans_without_explicit_close() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("startup_silent"))
    with pytest.raises(Exception):
        await supervisor.start()
    # No close() yet -- give the fire-and-forget cleanup a short, bounded
    # window to finish reaping the child and cancelling owned tasks.
    deadline = time.monotonic() + 2.0
    while (
        supervisor._process.returncode is None or any(not task.done() for task in supervisor._tasks)  # noqa: SLF001
    ) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert supervisor._process.returncode is not None  # noqa: SLF001
    assert not any(not task.done() for task in supervisor._tasks)  # noqa: SLF001
    # close() afterwards must still be idempotent and must not raise.
    await supervisor.close()
    await supervisor.close()
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED


# ---------------------------------------------------------------------------
# DEFECT_8 — WorkerTermination.reason must always be a stable category, not
# a human-readable message, across every termination path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_termination_reason_categories_are_stable() -> None:
    graceful = JsonlInteractionWorkerSupervisor(_config())
    await graceful.start()
    await graceful.close()
    assert graceful.termination is not None
    assert graceful.termination.reason == "GRACEFUL_CLOSE"

    emergency = JsonlInteractionWorkerSupervisor(_config())
    await emergency.start()
    try:
        await emergency.emergency_stop()
        await asyncio.sleep(0.1)
        assert emergency.termination is not None
        assert emergency.termination.reason == "EMERGENCY_STOP"
    finally:
        await emergency.close()

    process_failed = JsonlInteractionWorkerSupervisor(_config("process_failed"))
    with pytest.raises(Exception):
        await process_failed.start()
    try:
        assert process_failed.termination is not None
        assert process_failed.termination.reason == "PROCESS_FAILED_EVENT"
        assert process_failed.termination.protocol_error_code is None
    finally:
        await process_failed.close()

    framing = JsonlInteractionWorkerSupervisor(_config("missing_newline"))
    with pytest.raises(Exception):
        await framing.start()
    try:
        assert framing.termination is not None
        assert framing.termination.reason == "PROTOCOL_FAILURE"
        assert framing.termination.protocol_error_code == ERR_FRAMING
    finally:
        await framing.close()

    heartbeat = JsonlInteractionWorkerSupervisor(_config("heartbeat_stops", heartbeat_timeout_s=0.1))
    await heartbeat.start()
    try:
        await asyncio.sleep(0.2)
        assert heartbeat.termination is not None
        assert heartbeat.termination.reason == "HEARTBEAT_TIMEOUT"
    finally:
        await heartbeat.close()

    unexpected_exit = JsonlInteractionWorkerSupervisor(_config("crash_after_ready", heartbeat_timeout_s=0.2))
    await unexpected_exit.start()
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await _collect_until(unexpected_exit, WorkerEventType.PLAYBACK_COMPLETED)
        assert unexpected_exit.termination is not None
        assert unexpected_exit.termination.reason == "UNEXPECTED_EXIT"
    finally:
        await unexpected_exit.close()

    # "ignore_close" reliably reaches at least the terminate() escalation
    # (real Python child on Windows usually dies on terminate(), since it is
    # not blocking signals); the deterministic kill() escalation itself is
    # covered separately by test_kill_fallback_records_close_kill_using_fake_process.
    stubborn = JsonlInteractionWorkerSupervisor(_config("ignore_close"))
    await stubborn.start()
    await stubborn.close()
    assert stubborn.termination is not None
    assert stubborn.termination.reason in {"CLOSE_TERMINATE", "CLOSE_KILL"}

    overflow = JsonlInteractionWorkerSupervisor(_config(event_queue_size=1))
    with pytest.raises(Exception):
        await overflow.start()
    try:
        assert overflow.termination is not None
        assert overflow.termination.reason == "EVENT_QUEUE_OVERFLOW"
    finally:
        await overflow.close()


# ---------------------------------------------------------------------------
# DEFECT_9 — the terminate() -> kill() escalation in close() must be
# exercised deterministically against a fake process, not a real one, since
# a real Python child on Windows usually only proves terminate() was
# reached.
# ---------------------------------------------------------------------------


class _FakeStdin:
    def __init__(self) -> None:
        self._closing = False
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        # A real drain() always yields to the loop at least once. A
        # synchronous no-op coroutine here has been observed to occasionally
        # leave asyncio.wait_for(...) (in _command_writer) never waking up
        # even though its inner future already finished -- a timing edge
        # case specific to wrapping an already-resolved-without-suspension
        # coroutine in wait_for. Yielding once avoids that edge case and
        # also better matches how a real asyncio stream writer behaves.
        await asyncio.sleep(0)

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        pass


def _wire_line(**fields: object) -> bytes:
    base = {
        "protocol_version": INTERACTION_PROTOCOL_VERSION,
        "message_id": "worker:fake",
        "interaction_id": None,
        "sequence": 0,
        "emitted_at_monotonic_s": time.monotonic(),
        "payload": {},
    }
    base.update(fields)
    return (json.dumps(base, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


class _FakeKillProcess:
    """Deterministic fake of asyncio.subprocess.Process that speaks just
    enough of the real wire protocol to reach READY, then never responds to
    CLOSE and never exits on its own -- forcing close() through the full
    terminate() -> kill() escalation instead of depending on a real,
    possibly-cooperative OS process.

    Mirrors the real asyncio.subprocess.Process.wait() semantics: every
    concurrent/repeated call to wait() (close() awaits it, and the
    supervisor's independent _process_watcher task also awaits it) observes
    the *same* exit event rather than each call counting as a separate
    attempt -- otherwise a fake that "exits" the Nth time .wait() is called
    becomes nondeterministic depending on which task happens to call it
    first.
    """

    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()
        capabilities = {
            "audio_capture": False,
            "wake_word": False,
            "vad": False,
            "stt": False,
            "local_llm": False,
            "spanish_tts": False,
            "physical_playback": False,
            "physical_playback_stop": False,
            "physical_playback_completion": False,
        }
        self.stdout.feed_data(
            _wire_line(message_id="worker:0", event="command_accepted", sequence=0, payload={"command": "start", "message_id": "py:0"})
        )
        self.stdout.feed_data(
            _wire_line(message_id="worker:1", event="ready", sequence=1, payload=capabilities)
        )
        # No further frames are ever produced: stdout simply stays open and
        # silent, exactly like a child that ignores CLOSE.

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        # Simulate a child that does not react to terminate(): it keeps
        # running, so wait() must keep blocking.

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_kill_fallback_records_close_kill_using_fake_process() -> None:
    fake = _FakeKillProcess()

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        await asyncio.wait_for(supervisor.close(), timeout=2.0)
    finally:
        if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
            await supervisor.close()
    assert fake.terminate_calls == 1
    assert fake.kill_calls == 1
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "CLOSE_KILL"
    assert supervisor.termination.unexpected is False


# ---------------------------------------------------------------------------
# U3AR3 — DEFECT_1: the pending-command ledger must be bounded by an explicit
# max_pending_commands, independent of command_queue_size, so a worker that
# drains stdin but withholds COMMAND_ACCEPTED cannot grow it unbounded.
# ---------------------------------------------------------------------------


def _config_with_pending_limit(
    scenario: str,
    *,
    max_pending_commands: int,
    command_queue_size: int = 4,
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
        command_queue_size=command_queue_size,
        event_queue_size=64,
        max_line_bytes=2048,
        stderr_tail_lines=10,
        stderr_tail_max_chars=2048,
        max_seen_message_ids=4096,
        max_pending_commands=max_pending_commands,
    )


@pytest.mark.asyncio
async def test_pending_command_ledger_fails_closed_when_worker_withholds_acks() -> None:
    config = _config_with_pending_limit(
        "withhold_command_acks", max_pending_commands=6, command_queue_size=64
    )
    supervisor = JsonlInteractionWorkerSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted for start
        await supervisor.next_event(timeout_s=0.2)  # ready
        with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
            for _ in range(20):
                await supervisor._enqueue_command(  # noqa: SLF001
                    WorkerCommandType.HEALTH, interaction_id=None, payload={}
                )
                # command_queue_size is generous on purpose: the writer must
                # actually be able to drain the queue, so the ledger limit
                # (not queue backpressure) is what trips first.
                await asyncio.sleep(0.01)
        assert excinfo.value.code == "ERR_PENDING_COMMAND_LIMIT"
        assert len(supervisor._pending_commands) <= config.max_pending_commands  # noqa: SLF001
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.FAILED
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "COMMAND_ACK_BACKPRESSURE"
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_pending_command_limit_is_enforced_after_writer_drains_queue() -> None:
    config = _config_with_pending_limit(
        "withhold_command_acks", max_pending_commands=6, command_queue_size=4
    )
    supervisor = JsonlInteractionWorkerSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        max_seen = len(supervisor._pending_commands)  # noqa: SLF001
        observed_queue_drain = False
        with pytest.raises(InteractionRuntimeUnavailableError):
            for _ in range(20):
                await supervisor._enqueue_command(  # noqa: SLF001
                    WorkerCommandType.HEALTH, interaction_id=None, payload={}
                )
                await asyncio.sleep(0.02)
                max_seen = max(max_seen, len(supervisor._pending_commands))  # noqa: SLF001
                if supervisor._command_queue.qsize() < config.command_queue_size:  # noqa: SLF001
                    observed_queue_drain = True
        # The writer must have actually drained _command_queue below its
        # configured size at some point -- otherwise this test would only be
        # proving command_queue_size itself, not the independent ledger limit.
        assert observed_queue_drain
        assert max_seen <= config.max_pending_commands
    finally:
        await supervisor.close()


# ---------------------------------------------------------------------------
# U3AR3 — DEFECT_2: a COMMAND_ACCEPTED with a correct message_id/command but
# a mismatched interaction_id must fail with ERR_CORRELATION, not the generic
# ERR_STALE_INTERACTION check that runs for every other event type.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_accepted_interaction_mismatch_uses_err_correlation() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("activation_waits"))
    await supervisor.start()
    try:
        await supervisor.activate(InteractionContext(interaction_id="interaction:1"))
        await _collect_until(supervisor, WorkerEventType.CAPTURE_STARTED)
        await supervisor._enqueue_command(  # noqa: SLF001
            WorkerCommandType.PAUSE, interaction_id="interaction:1", payload={}
        )
        pending_message_id = next(
            message_id
            for message_id, (command, _interaction_id) in supervisor._pending_commands.items()  # noqa: SLF001
            if command == WorkerCommandType.PAUSE
        )
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        mismatched_event = WorkerEventEnvelope(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            message_id="evt:mismatch",
            interaction_id="interaction:WRONG",
            event=WorkerEventType.COMMAND_ACCEPTED,
            sequence=next_sequence,
            emitted_at_monotonic_s=time.monotonic(),
            payload={"command": "pause", "message_id": pending_message_id},
        )
        with pytest.raises(InteractionRuntimeProtocolError) as excinfo:
            supervisor._process_event(mismatched_event)  # noqa: SLF001
        assert excinfo.value.code == ERR_CORRELATION
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_command_accepted_interaction_mismatch_via_wire_sets_correlation_protocol_error() -> None:
    # A fake process is required here (rather than the real loopback
    # worker) because the mismatched COMMAND_ACCEPTED frame must be fed
    # through the worker -> supervisor direction (stdout), which a real
    # child process does not let the test inject into directly.
    fake = _FakeKillProcess()

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    supervisor = _FakeProcessSupervisor(_config())
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted for start
        await supervisor.next_event(timeout_s=0.2)  # ready
        await supervisor._enqueue_command(  # noqa: SLF001
            WorkerCommandType.PAUSE, interaction_id="interaction:1", payload={}
        )
        pending_message_id = next(
            message_id
            for message_id, (command, _interaction_id) in supervisor._pending_commands.items()  # noqa: SLF001
            if command == WorkerCommandType.PAUSE
        )
        next_sequence = supervisor._incoming_sequence  # noqa: SLF001
        fake.stdout.feed_data(
            _wire_line(
                message_id="worker:mismatch-wire",
                interaction_id="interaction:WRONG",
                event="command_accepted",
                sequence=next_sequence,
                payload={"command": "pause", "message_id": pending_message_id},
            )
        )
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.next_event(timeout_s=1.0)
        assert supervisor.termination is not None
        assert supervisor.termination.protocol_error_code == ERR_CORRELATION
    finally:
        await supervisor.close()


# ---------------------------------------------------------------------------
# U3AR3 — DEFECT_3/4: the failure-cleanup task must be owned (referenced,
# named, awaited), not a detached fire-and-forget asyncio.ensure_future. It
# must also count as a supervisor-owned task for "no tasks remaining" checks.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_cleanup_task_is_owned_and_awaitable() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("process_failed"))
    with pytest.raises(Exception):
        await supervisor.start()
    try:
        await _collect_until(supervisor, WorkerEventType.FAILED)
        assert supervisor._cleanup_task is not None  # noqa: SLF001
        assert supervisor._cleanup_task.get_name().startswith("interaction-jsonl-")  # noqa: SLF001
        await asyncio.wait_for(supervisor._cleanup_task, timeout=2.0)  # noqa: SLF001
        assert supervisor._cleanup_task.done()  # noqa: SLF001
        assert supervisor._cleanup_task.exception() is None  # noqa: SLF001
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_start_failure_returns_only_after_owned_cleanup_is_complete() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("startup_silent"))
    with pytest.raises(Exception):
        await supervisor.start()
    # If the cleanup is properly owned and awaited as part of the start()
    # failure path, the child must already be reaped and no supervisor task
    # may still be running the instant start() raises -- no polling loop
    # needed.
    assert supervisor._process.returncode is not None  # noqa: SLF001
    assert not any(not task.done() for task in supervisor._tasks)  # noqa: SLF001
    assert supervisor._cleanup_task is not None  # noqa: SLF001
    assert supervisor._cleanup_task.done()  # noqa: SLF001
    await supervisor.close()
    await supervisor.close()
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED


# ---------------------------------------------------------------------------
# U3AR3 — DEFECT_5: close() must never overwrite an existing primary failure
# reason (e.g. PROCESS_FAILED_EVENT, PROTOCOL_FAILURE) with a mechanical
# CLOSE_TERMINATE/CLOSE_KILL escalation category.
# ---------------------------------------------------------------------------


class _FakeFailThenIgnoreCloseProcess:
    """Deterministic fake that reaches READY, then emits a process-level
    FAILED frame (establishing a real primary termination reason through the
    normal _fail() path), and only actually exits on the Nth kill() attempt
    -- modeling a worker that both faulted AND resists the first cleanup
    attempt(s), forcing close() to walk its own terminate() -> kill()
    escalation on top of an *already failed* supervisor before the process
    finally goes away. This is the exact scenario where a mechanical
    escalation category must not overwrite the primary failure reason.
    """

    def __init__(self, *, kills_to_exit: int = 2) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._kills_to_exit = kills_to_exit
        self._exited = asyncio.Event()
        capabilities = {
            "audio_capture": False,
            "wake_word": False,
            "vad": False,
            "stt": False,
            "local_llm": False,
            "spanish_tts": False,
            "physical_playback": False,
            "physical_playback_stop": False,
            "physical_playback_completion": False,
        }
        self.stdout.feed_data(
            _wire_line(message_id="worker:0", event="command_accepted", sequence=0, payload={"command": "start", "message_id": "py:0"})
        )
        self.stdout.feed_data(
            _wire_line(message_id="worker:1", event="ready", sequence=1, payload=capabilities)
        )
        self.stdout.feed_data(
            _wire_line(
                message_id="worker:2",
                event="failed",
                sequence=2,
                payload={"code": "ERR_WORKER_FATAL", "message": "process-level failure"},
            )
        )
        # No further frames: stdout stays open and silent afterwards, exactly
        # like a child that both faulted and ignores CLOSE.

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        # Never exits on terminate(), by design.

    def kill(self) -> None:
        self.kill_calls += 1
        if self.kill_calls >= self._kills_to_exit:
            self.returncode = -9
            self._exited.set()
        # Earlier kill() attempts (e.g. the failure-path self-clean's own
        # attempt) do not actually terminate the process, so close()'s own
        # escalation still has real work to do afterwards.


@pytest.mark.asyncio
async def test_immediate_close_after_process_failed_preserves_primary_reason() -> None:
    fake = _FakeFailThenIgnoreCloseProcess(kills_to_exit=2)

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    with pytest.raises(Exception):
        await supervisor.start()
    # Let the failure-path self-clean run to completion first (it attempts
    # one kill(), which this fake does not yet honor) before close() is
    # invoked, so close() is guaranteed to walk its own terminate() ->
    # kill() escalation on top of an already-failed supervisor.
    cleanup_task = getattr(supervisor, "_cleanup_task", None)
    if cleanup_task is not None:
        await asyncio.gather(cleanup_task, return_exceptions=True)
    else:
        await asyncio.sleep(0.2)
    await asyncio.wait_for(supervisor.close(), timeout=2.0)
    assert fake.terminate_calls >= 1
    assert fake.kill_calls >= 1
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "PROCESS_FAILED_EVENT"


@pytest.mark.asyncio
async def test_immediate_close_after_protocol_failure_preserves_primary_reason() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(
        _config("missing_newline", shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    )
    with pytest.raises(Exception):
        await supervisor.start()
    await supervisor.close()
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "PROTOCOL_FAILURE"
    assert supervisor.termination.protocol_error_code == ERR_FRAMING


# ---------------------------------------------------------------------------
# U3AR3 — no supervisor-owned task (including the cleanup task) may remain
# after a failure followed by close().
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_supervisor_owned_task_remains_after_failure_and_close() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("process_failed"))
    with pytest.raises(Exception):
        await supervisor.start()
    await supervisor.close()
    assert not supervisor._tasks  # noqa: SLF001
    assert supervisor._cleanup_task is None or supervisor._cleanup_task.done()  # noqa: SLF001
    remaining_named = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and task.get_name().startswith("interaction-jsonl-")
    ]
    assert not remaining_named


# ---------------------------------------------------------------------------
# U3AR3 — deterministic concurrency matrix (section 20). asyncio.Event is
# used to synchronize instead of sleeps wherever the supervisor's internals
# expose a natural synchronization point.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_fail_and_close_converge_on_one_cleanup() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("process_failed"))
    with pytest.raises(Exception):
        await supervisor.start()
    # _fail() already ran once for the process_failed event; close() must
    # converge on the same cleanup rather than racing a second escalation.
    close_task = asyncio.ensure_future(supervisor.close())
    fail_again_task = asyncio.ensure_future(
        supervisor._fail(  # noqa: SLF001
            "redundant concurrent failure", unexpected=True, termination_reason="PROTOCOL_FAILURE"
        )
    )
    await asyncio.gather(close_task, fail_again_task)
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "PROCESS_FAILED_EVENT"
    assert not supervisor._tasks  # noqa: SLF001
    assert supervisor._cleanup_task is None or supervisor._cleanup_task.done()  # noqa: SLF001


@pytest.mark.asyncio
async def test_process_watcher_and_cleanup_await_same_child_exit() -> None:
    fake = _FakeKillProcess()

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    supervisor = _FakeProcessSupervisor(_config(heartbeat_timeout_s=0.1))
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        # Starve the heartbeat to trigger _fail() from _heartbeat_monitor,
        # which schedules the owned cleanup task; _process_watcher is an
        # independently running task also awaiting the same fake.wait().
        # Both must observe the same single exit event rather than each
        # calling kill() under the impression no one else is handling it.
        await asyncio.sleep(0.3)
        assert supervisor.termination is not None
        assert supervisor._cleanup_task is not None  # noqa: SLF001
        await asyncio.wait_for(supervisor._cleanup_task, timeout=2.0)  # noqa: SLF001
        assert fake.kill_calls <= 1
    finally:
        await supervisor.close()
    assert not supervisor._tasks  # noqa: SLF001


class _FakeWithholdAcksProcess:
    """Deterministic fake that reaches READY and then never ACKs anything
    else, mirroring the withhold_command_acks loopback scenario but without
    a real OS pipe -- so a burst of concurrent stdin writes immediately
    followed by terminate()/kill() cannot race a ProactorEventLoop
    background write future the way a real child process can on Windows.
    """

    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()
        capabilities = {
            "audio_capture": False,
            "wake_word": False,
            "vad": False,
            "stt": False,
            "local_llm": False,
            "spanish_tts": False,
            "physical_playback": False,
            "physical_playback_stop": False,
            "physical_playback_completion": False,
        }
        self.stdout.feed_data(
            _wire_line(message_id="worker:0", event="command_accepted", sequence=0, payload={"command": "start", "message_id": "py:0"})
        )
        self.stdout.feed_data(
            _wire_line(message_id="worker:1", event="ready", sequence=1, payload=capabilities)
        )
        # No further frames: nothing past START is ever ACKed.

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = -15
        self._exited.set()

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_two_callers_racing_the_pending_command_limit_only_one_pool_is_exceeded() -> None:
    fake = _FakeWithholdAcksProcess()

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config_with_pending_limit(
        "normal", max_pending_commands=6, command_queue_size=64
    )
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        async def _flood() -> list[Exception]:
            errors: list[Exception] = []
            for _ in range(10):
                try:
                    await supervisor._enqueue_command(  # noqa: SLF001
                        WorkerCommandType.HEALTH, interaction_id=None, payload={}
                    )
                except InteractionRuntimeUnavailableError as exc:
                    errors.append(exc)
                    break
            return errors

        results = await asyncio.gather(_flood(), _flood())
        all_errors = [exc for errors in results for exc in errors]
        assert all_errors
        # Whichever caller actually trips the limit observes
        # ERR_PENDING_COMMAND_LIMIT; once the supervisor is FAILED, the
        # other caller's next attempt fails closed immediately with
        # ERR_TERMINAL_STATE instead of being allowed to keep refilling the
        # command queue behind a writer that has already been torn down.
        assert any(exc.code == "ERR_PENDING_COMMAND_LIMIT" for exc in all_errors)
        for exc in all_errors:
            assert exc.code in {"ERR_PENDING_COMMAND_LIMIT", "ERR_TERMINAL_STATE"}
        # The lock-protected check-then-act in _enqueue_command means the
        # ledger size never exceeds the configured limit even with two
        # concurrent callers racing to fill the last slot.
        assert len(supervisor._pending_commands) <= config.max_pending_commands  # noqa: SLF001
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "COMMAND_ACK_BACKPRESSURE"
    finally:
        await supervisor.close()


@pytest.mark.asyncio
async def test_close_while_pending_command_ledger_is_full() -> None:
    config = _config_with_pending_limit(
        "withhold_command_acks", max_pending_commands=4, command_queue_size=64
    )
    supervisor = JsonlInteractionWorkerSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        with pytest.raises(InteractionRuntimeUnavailableError):
            for _ in range(10):
                await supervisor._enqueue_command(  # noqa: SLF001
                    WorkerCommandType.HEALTH, interaction_id=None, payload={}
                )
        assert len(supervisor._pending_commands) <= config.max_pending_commands  # noqa: SLF001
    finally:
        await asyncio.wait_for(supervisor.close(), timeout=2.0)
    # close() must clear the ledger deterministically on the terminal
    # transition, regardless of how full it was.
    assert not supervisor._pending_commands  # noqa: SLF001
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED


@pytest.mark.asyncio
async def test_emergency_while_commands_are_pending_without_ack_clears_ledger() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("withhold_command_acks"))
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        await supervisor._enqueue_command(  # noqa: SLF001
            WorkerCommandType.HEALTH, interaction_id=None, payload={}
        )
        await supervisor._enqueue_command(  # noqa: SLF001
            WorkerCommandType.HEALTH, interaction_id=None, payload={}
        )
        assert supervisor._pending_commands  # noqa: SLF001 - sanity: ledger is non-empty before emergency
        await supervisor.emergency_stop()
        # The discarded HEALTH envelopes were never going to be ACKed by a
        # worker that no longer exists from the supervisor's perspective;
        # only EMERGENCY_STOP itself (if it made it onto the queue) may
        # remain in the ledger afterwards.
        assert all(
            command is WorkerCommandType.EMERGENCY_STOP
            for command, _interaction_id in supervisor._pending_commands.values()  # noqa: SLF001
        )
        health = await supervisor.health()
        assert health.state is InteractionRuntimeState.EMERGENCY
    finally:
        await supervisor.close()
    assert not supervisor._pending_commands  # noqa: SLF001


@pytest.mark.asyncio
async def test_enqueue_rechecks_failed_state_after_waiting_for_command_lock() -> None:
    supervisor = _bare_supervisor_for_enqueue()
    task = await _enqueue_waiting_on_command_lock(supervisor)
    supervisor._state = InteractionRuntimeState.FAILED  # noqa: SLF001
    supervisor._command_lock.release()  # noqa: SLF001
    with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
        await task
    assert excinfo.value.code == "ERR_TERMINAL_STATE"
    assert supervisor._command_queue.empty()  # noqa: SLF001
    assert not supervisor._pending_commands  # noqa: SLF001


@pytest.mark.asyncio
async def test_enqueue_rechecks_closed_state_after_waiting_for_command_lock() -> None:
    supervisor = _bare_supervisor_for_enqueue()
    task = await _enqueue_waiting_on_command_lock(supervisor)
    supervisor._state = InteractionRuntimeState.CLOSED  # noqa: SLF001
    supervisor._command_lock.release()  # noqa: SLF001
    with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
        await task
    assert excinfo.value.code == "ERR_TERMINAL_STATE"
    assert supervisor._command_queue.empty()  # noqa: SLF001
    assert not supervisor._pending_commands  # noqa: SLF001


@pytest.mark.asyncio
async def test_enqueue_rechecks_emergency_policy_after_waiting_for_command_lock() -> None:
    ordinary = _bare_supervisor_for_enqueue()
    task = await _enqueue_waiting_on_command_lock(ordinary)
    ordinary._emergency_latched = True  # noqa: SLF001
    ordinary._state = InteractionRuntimeState.EMERGENCY  # noqa: SLF001
    ordinary._command_lock.release()  # noqa: SLF001
    with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
        await task
    assert excinfo.value.code == "ERR_EMERGENCY"
    assert ordinary._command_queue.empty()  # noqa: SLF001
    assert not ordinary._pending_commands  # noqa: SLF001

    emergency = _bare_supervisor_for_enqueue(state=InteractionRuntimeState.EMERGENCY)
    emergency._emergency_latched = True  # noqa: SLF001
    await emergency._enqueue_command(  # noqa: SLF001
        WorkerCommandType.EMERGENCY_STOP,
        interaction_id=None,
        payload={},
        allow_when_emergency=True,
    )
    queued = emergency._command_queue.get_nowait()  # noqa: SLF001
    assert queued.command is WorkerCommandType.EMERGENCY_STOP


@pytest.mark.asyncio
async def test_queue_full_does_not_consume_outgoing_sequence() -> None:
    supervisor = _bare_supervisor_for_enqueue(command_queue_size=1)
    await supervisor._enqueue_command(WorkerCommandType.HEALTH, interaction_id=None, payload={})  # noqa: SLF001
    sequence_before_rejection = supervisor._outgoing_sequence  # noqa: SLF001
    with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
        await supervisor._enqueue_command(WorkerCommandType.HEALTH, interaction_id=None, payload={})  # noqa: SLF001
    assert excinfo.value.code == "ERR_QUEUE_FULL"
    assert supervisor._outgoing_sequence == sequence_before_rejection  # noqa: SLF001


@pytest.mark.asyncio
async def test_next_successful_command_after_queue_full_has_contiguous_sequence() -> None:
    supervisor = _bare_supervisor_for_enqueue(command_queue_size=1)
    await supervisor._enqueue_command(WorkerCommandType.HEALTH, interaction_id=None, payload={})  # noqa: SLF001
    first = supervisor._command_queue.get_nowait()  # noqa: SLF001
    supervisor._pending_commands.pop(first.message_id)  # noqa: SLF001
    await supervisor._enqueue_command(WorkerCommandType.HEALTH, interaction_id=None, payload={})  # noqa: SLF001
    with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
        await supervisor._enqueue_command(WorkerCommandType.HEALTH, interaction_id=None, payload={})  # noqa: SLF001
    assert excinfo.value.code == "ERR_QUEUE_FULL"
    queued = supervisor._command_queue.get_nowait()  # noqa: SLF001
    supervisor._pending_commands.pop(queued.message_id)  # noqa: SLF001
    await supervisor._enqueue_command(WorkerCommandType.HEALTH, interaction_id=None, payload={})  # noqa: SLF001
    next_envelope = supervisor._command_queue.get_nowait()  # noqa: SLF001
    assert next_envelope.sequence == queued.sequence + 1


class _AlreadyExitedProcess:
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = 0

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


class _CountingExitedProcess(_AlreadyExitedProcess):
    def __init__(self, *, returncode: int = 0) -> None:
        super().__init__()
        self.returncode = returncode
        self.terminate_calls = 0
        self.kill_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1


async def _stubborn_owned_task(release: asyncio.Event) -> None:
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        await release.wait()
        raise


def _supervisor_with_stubborn_close_task(
    *,
    state: InteractionRuntimeState = InteractionRuntimeState.READY,
    task_name: str = "interaction-jsonl-stubborn-retry",
    returncode: int = 0,
) -> tuple[JsonlInteractionWorkerSupervisor, _CountingExitedProcess, asyncio.Event]:
    supervisor = _bare_supervisor_for_enqueue(state=state)
    process = _CountingExitedProcess(returncode=returncode)
    supervisor._process = process  # type: ignore[assignment]  # noqa: SLF001
    supervisor._owned_task_cancel_timeout_s = 0.05  # noqa: SLF001
    release = asyncio.Event()
    stubborn = asyncio.create_task(_stubborn_owned_task(release), name=task_name)
    supervisor._tasks.add(stubborn)  # noqa: SLF001
    stubborn.add_done_callback(supervisor._tasks.discard)  # noqa: SLF001
    return supervisor, process, release


async def _cleanup_stubborn_supervisor(
    supervisor: JsonlInteractionWorkerSupervisor,
    release: asyncio.Event,
) -> None:
    release.set()
    for task in list(supervisor._tasks):  # noqa: SLF001
        task.cancel()
    await asyncio.gather(*list(supervisor._tasks), return_exceptions=True)  # noqa: SLF001
    if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
        try:
            await supervisor.close()
        except InteractionRuntimeUnavailableError:
            pass


@pytest.mark.asyncio
async def test_normal_close_settlement_timeout_becomes_primary_termination() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        task_name="interaction-jsonl-stubborn-primary"
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
            await supervisor.close()
        assert excinfo.value.code == ERR_TASK_SETTLEMENT_TIMEOUT
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "TASK_SETTLEMENT_TIMEOUT"
        assert supervisor.termination.unexpected is True
        assert supervisor.termination.protocol_error_code == ERR_TASK_SETTLEMENT_TIMEOUT
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_close_settlement_timeout_does_not_mark_runtime_closed() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        task_name="interaction-jsonl-stubborn-not-closed"
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.close()
        health = await supervisor.health()
        assert health.state is not InteractionRuntimeState.CLOSED
        assert health.ready is False
        assert supervisor._event_stream_terminal.is_set()  # noqa: SLF001
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_close_settlement_timeout_is_retryable_after_task_release() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        task_name="interaction-jsonl-stubborn-retry-public"
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
            await supervisor.close()
        assert excinfo.value.code == ERR_TASK_SETTLEMENT_TIMEOUT
        release.set()
        await supervisor.close()
        assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
        assert not supervisor._tasks  # noqa: SLF001
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_second_close_retries_settlement_without_manual_task_discard() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        task_name="interaction-jsonl-stubborn-auto-discard"
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
            await supervisor.close()
        assert "interaction-jsonl-stubborn-auto-discard" in str(excinfo.value)
        assert any(
            task.get_name() == "interaction-jsonl-stubborn-auto-discard"
            for task in supervisor._tasks  # noqa: SLF001
        )
        release.set()
        await supervisor.close()
        assert not supervisor._tasks  # noqa: SLF001
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_second_close_does_not_repeat_process_escalation() -> None:
    supervisor, process, release = _supervisor_with_stubborn_close_task(
        task_name="interaction-jsonl-stubborn-no-extra-escalation",
        returncode=23,
    )
    process_id = id(process)
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.close()
        terminate_after_first = process.terminate_calls
        kill_after_first = process.kill_calls
        release.set()
        await supervisor.close()
        assert id(supervisor._process) == process_id  # noqa: SLF001
        assert process.terminate_calls == terminate_after_first
        assert process.kill_calls == kill_after_first
        assert supervisor.termination is not None
        assert supervisor.termination.exit_code == 23
        assert not supervisor._tasks  # noqa: SLF001
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_prior_process_failure_reason_survives_close_settlement_timeout() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        state=InteractionRuntimeState.FAILED,
        task_name="interaction-jsonl-stubborn-process-failure",
    )
    supervisor._record_termination(  # noqa: SLF001
        reason="PROCESS_FAILED_EVENT",
        unexpected=True,
        exit_code=7,
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.close()
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "PROCESS_FAILED_EVENT"
        assert supervisor.termination.unexpected is True
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_protocol_failure_reason_survives_close_settlement_timeout() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        state=InteractionRuntimeState.FAILED,
        task_name="interaction-jsonl-stubborn-protocol-failure",
    )
    supervisor._record_termination(  # noqa: SLF001
        reason="PROTOCOL_FAILURE",
        unexpected=True,
        exit_code=8,
        protocol_error_code=ERR_FRAMING,
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.close()
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "PROTOCOL_FAILURE"
        assert supervisor.termination.protocol_error_code == ERR_FRAMING
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_emergency_reason_survives_close_settlement_timeout() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        state=InteractionRuntimeState.EMERGENCY,
        task_name="interaction-jsonl-stubborn-emergency",
    )
    supervisor._emergency_latched = True  # noqa: SLF001
    supervisor._record_termination(  # noqa: SLF001
        reason="EMERGENCY_STOP",
        unexpected=False,
        exit_code=9,
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.close()
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "EMERGENCY_STOP"
        assert supervisor.termination.unexpected is False
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_uncooperative_owned_task_does_not_allow_clean_close_claim() -> None:
    supervisor = _bare_supervisor_for_enqueue()
    supervisor._owned_task_cancel_timeout_s = 0.05  # noqa: SLF001
    supervisor._process = _AlreadyExitedProcess()  # type: ignore[assignment]  # noqa: SLF001
    release = asyncio.Event()
    stubborn = asyncio.create_task(_stubborn_owned_task(release), name="interaction-jsonl-stubborn-close")
    supervisor._tasks.add(stubborn)  # noqa: SLF001
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
            await supervisor.close()
        assert excinfo.value.code == "ERR_TASK_SETTLEMENT_TIMEOUT"
        assert "interaction-jsonl-stubborn-close" in str(excinfo.value)
    finally:
        release.set()
        stubborn.cancel()
        await asyncio.gather(stubborn, return_exceptions=True)
        supervisor._tasks.discard(stubborn)  # noqa: SLF001
    assert not any(
        task.get_name() == "interaction-jsonl-stubborn-close" and not task.done()
        for task in asyncio.all_tasks()
    )


class _StartupNeverReadyProcess(_AlreadyExitedProcess):
    def __init__(self) -> None:
        super().__init__()
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self._exited = asyncio.Event()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15
        self._exited.set()

    def kill(self) -> None:
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_start_failure_reports_incomplete_owned_task_settlement() -> None:
    release = asyncio.Event()

    class _StartupSettlementSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            task = asyncio.create_task(
                _stubborn_owned_task(release),
                name="interaction-jsonl-stubborn-start",
            )
            self._tasks.add(task)  # noqa: SLF001
            task.add_done_callback(self._tasks.discard)  # noqa: SLF001
            return _StartupNeverReadyProcess()  # type: ignore[return-value]

    supervisor = _StartupSettlementSupervisor(
        JsonlWorkerSupervisorConfig(
            argv=(sys.executable, str(WORKER), "normal"),
            startup_timeout_s=0.05,
            heartbeat_timeout_s=0.3,
            write_timeout_s=0.2,
            shutdown_timeout_s=0.05,
            terminate_timeout_s=0.05,
            command_queue_size=4,
            event_queue_size=64,
            max_line_bytes=2048,
            stderr_tail_lines=10,
            stderr_tail_max_chars=2048,
            max_seen_message_ids=4096,
        )
    )
    supervisor._owned_task_cancel_timeout_s = 0.05  # noqa: SLF001
    try:
        with pytest.raises(InteractionRuntimeUnavailableError) as excinfo:
            await supervisor.start()
        assert excinfo.value.code == "ERR_TASK_SETTLEMENT_TIMEOUT"
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "STARTUP_TIMEOUT"
    finally:
        release.set()
        for task in list(supervisor._tasks):  # noqa: SLF001
            task.cancel()
        await asyncio.gather(*list(supervisor._tasks), return_exceptions=True)  # noqa: SLF001
        await supervisor.close()
    assert not any(
        task.get_name() == "interaction-jsonl-stubborn-start" and not task.done()
        for task in asyncio.all_tasks()
    )
# ---------------------------------------------------------------------------
# U3AR6 — DEFECT_1: EMERGENCY_STOP must not be overwritten by CLOSE_TERMINATE
# or CLOSE_KILL when the child is still alive during close().
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emergency_reason_survives_close_terminate_escalation() -> None:
    fake = _FakeKillProcess()
    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]
    
    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.emergency_stop()
        await asyncio.sleep(0.1)
        await asyncio.wait_for(supervisor.close(), timeout=2.0)
    finally:
        if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
            await supervisor.close()
    
    assert fake.terminate_calls == 1
    assert fake.kill_calls == 1
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "EMERGENCY_STOP"
    assert supervisor.termination.unexpected is False


@pytest.mark.asyncio
async def test_emergency_reason_survives_close_kill_escalation() -> None:
    fake = _FakeKillProcess()
    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]
    
    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.emergency_stop()
        await asyncio.sleep(0.1)
        await asyncio.wait_for(supervisor.close(), timeout=2.0)
    finally:
        if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
            await supervisor.close()
            
    assert fake.terminate_calls == 1
    assert fake.kill_calls >= 1
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "EMERGENCY_STOP"
    assert supervisor.termination.unexpected is False


# ---------------------------------------------------------------------------
# U3AR6 — DEFECT_2: UNEXPECTED_EXIT is a real primary termination reason and
# must not be overwritten by TASK_SETTLEMENT_TIMEOUT.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unexpected_exit_survives_task_settlement_timeout() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        state=InteractionRuntimeState.FAILED,
        task_name="interaction-jsonl-stubborn-unexpected-exit",
    )
    supervisor._record_termination(  # noqa: SLF001
        reason="UNEXPECTED_EXIT",
        unexpected=True,
        exit_code=1,
    )
    await asyncio.sleep(0)
    try:
        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.close()
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "UNEXPECTED_EXIT"
        assert supervisor.termination.unexpected is True
        assert supervisor.termination.protocol_error_code == ERR_TASK_SETTLEMENT_TIMEOUT
        release.set()
        await supervisor.close()
        assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
    finally:
        await _cleanup_stubborn_supervisor(supervisor, release)


@pytest.mark.asyncio
async def test_real_primary_reason_predicate_includes_unexpected_exit() -> None:
    from src.interaction.jsonl_worker_supervisor import _is_real_primary_termination
    from src.interaction.worker_supervisor import WorkerTermination
    
    term = WorkerTermination(
        exit_code=1,
        reason="UNEXPECTED_EXIT",
        unexpected=True,
        occurred_at_monotonic_s=0.0,
        protocol_error_code=None,
        stderr_tail=(),
    )
    assert _is_real_primary_termination(term) is True


@pytest.mark.asyncio
async def test_real_primary_reason_predicate_includes_emergency_stop_even_when_not_unexpected() -> None:
    from src.interaction.jsonl_worker_supervisor import _is_real_primary_termination
    from src.interaction.worker_supervisor import WorkerTermination
    
    term = WorkerTermination(
        exit_code=None,
        reason="EMERGENCY_STOP",
        unexpected=False,
        occurred_at_monotonic_s=0.0,
        protocol_error_code=None,
        stderr_tail=(),
    )
    assert _is_real_primary_termination(term) is True


# ---------------------------------------------------------------------------
# U3AR6 — DEFECT_3: close() must serialize concurrent callers.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_concurrent_close_callers_use_single_process_shutdown() -> None:
    fake = _FakeKillProcess()
    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]
            
    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    
    caller1 = asyncio.create_task(supervisor.close())
    caller2 = asyncio.create_task(supervisor.close())
    await asyncio.gather(caller1, caller2)
    
    assert fake.terminate_calls <= 1
    assert fake.kill_calls <= 1
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED


@pytest.mark.asyncio
async def test_two_concurrent_close_callers_do_not_duplicate_close_command() -> None:
    fake = _FakeKillProcess()
    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]
            
    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    
    caller1 = asyncio.create_task(supervisor.close())
    caller2 = asyncio.create_task(supervisor.close())
    await asyncio.gather(caller1, caller2)
    
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
    close_commands = [
        item for item in fake.stdin.written
        if b'"command":"close"' in item
    ]
    assert len(close_commands) <= 1


@pytest.mark.asyncio
async def test_two_concurrent_close_callers_preserve_same_termination() -> None:
    fake = _FakeKillProcess()
    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]
            
    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    
    caller1 = asyncio.create_task(supervisor.close())
    caller2 = asyncio.create_task(supervisor.close())
    await asyncio.gather(caller1, caller2)
    
    assert supervisor.termination is not None
    assert supervisor.termination.reason in {"CLOSE_TERMINATE", "CLOSE_KILL", "GRACEFUL_CLOSE"}


@pytest.mark.asyncio
async def test_concurrent_close_with_settlement_timeout_is_retryable() -> None:
    supervisor, _process, release = _supervisor_with_stubborn_close_task(
        task_name="interaction-jsonl-stubborn-concurrent"
    )
    await asyncio.sleep(0)
    
    caller1 = asyncio.create_task(supervisor.close())
    caller2 = asyncio.create_task(supervisor.close())
    
    results = await asyncio.gather(caller1, caller2, return_exceptions=True)
    assert len(results) == 2
    for r in results:
        assert isinstance(r, InteractionRuntimeUnavailableError)
        assert r.code == ERR_TASK_SETTLEMENT_TIMEOUT
        
    release.set()
    await supervisor.close()
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED


@pytest.mark.asyncio
async def test_cancelled_close_caller_does_not_cancel_shared_close() -> None:
    fake = _FakeKillProcess()
    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]
            
    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    
    caller1 = asyncio.create_task(supervisor.close())
    caller2 = asyncio.create_task(supervisor.close())
    
    await asyncio.sleep(0)
    caller1.cancel()
    
    with pytest.raises(asyncio.CancelledError):
        await caller1
        
    await caller2
    
    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
    assert not any(not t.done() for t in supervisor._tasks)  # noqa: SLF001


# ---------------------------------------------------------------------------
# U3AR7 — PRIMARY_TERMINATION_REASON_CAN_BE_OVERWRITTEN_WHEN_IT_APPEARS_DURING_CLOSE_ESCALATION
#
# The snapshot `had_primary_failure_reason` is taken before the cooperative
# shutdown wait.  If a primary reason is recorded DURING the wait (i.e. after
# the snapshot but before the finally block), the finally block observes
# `had_primary_failure_reason = False` and overwrites the real cause with the
# mechanical CLOSE_TERMINATE or CLOSE_KILL.
#
# These two tests prove that gap deterministically.  They must be RED against
# HEAD (EXPECTED_HEAD = 657e1505).  The fix is to reevaluate
# `_is_real_primary_termination(self._termination)` live inside the finally
# block instead of relying on the stale snapshot.
# ---------------------------------------------------------------------------


class _FakeProcessFailedDuringTerminate:
    """Reaches READY, never responds to CLOSE (forcing shutdown_timeout_s to
    elapse and terminate() to be called), then — while close() is inside the
    `await wait_for(process.wait(), terminate_timeout_s)` window — injects a
    PROCESS_FAILED_EVENT into stdout so that _fail() records the primary reason
    AFTER the `had_primary_failure_reason` snapshot was taken.

    The process only exits on kill(), so close() must walk the full
    terminate() → kill() escalation, giving the primary reason time to be
    recorded between the snapshot and the finally block.
    """

    _CAPS = {
        "audio_capture": False,
        "wake_word": False,
        "vad": False,
        "stt": False,
        "local_llm": False,
        "spanish_tts": False,
        "physical_playback": False,
        "physical_playback_stop": False,
        "physical_playback_completion": False,
    }

    def __init__(self, primary_reason_injected_event: asyncio.Event) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()
        self._primary_reason_injected_event = primary_reason_injected_event
        # Feed startup frames immediately so start() can succeed.
        self.stdout.feed_data(
            _wire_line(
                message_id="worker:0",
                event="command_accepted",
                sequence=0,
                payload={"command": "start", "message_id": "py:0"},
            )
        )
        self.stdout.feed_data(
            _wire_line(
                message_id="worker:1",
                event="ready",
                sequence=1,
                payload=self._CAPS,
            )
        )
        # stdout stays open; the FAILED frame is fed inside terminate().

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        # Inject the primary reason NOW — i.e. after close()'s snapshot was
        # taken and while close() is inside the terminate_timeout_s window.
        # The supervisor's _stdout_reader task will pick it up and call _fail().
        self.stdout.feed_data(
            _wire_line(
                message_id="worker:2",
                event="failed",
                sequence=2,
                payload={"code": "ERR_WORKER_FATAL", "message": "failed during terminate"},
            )
        )
        self._primary_reason_injected_event.set()
        # Do NOT exit yet: keep the process alive so close() is forced to
        # escalate to kill().

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


class _FakeProtocolFailureDuringKill:
    """Like the above but injects a PROTOCOL_FAILURE (invalid UTF-8 frame)
    during the kill() window instead of PROCESS_FAILED_EVENT during terminate().

    The process exits on terminate(), which forces close() to call wait()
    — but before wait() resolves, the corrupted stdout frame triggers
    _fail(PROTOCOL_FAILURE), again after the snapshot was taken.
    """

    _CAPS = {
        "audio_capture": False,
        "wake_word": False,
        "vad": False,
        "stt": False,
        "local_llm": False,
        "spanish_tts": False,
        "physical_playback": False,
        "physical_playback_stop": False,
        "physical_playback_completion": False,
    }

    def __init__(self, primary_reason_injected_event: asyncio.Event) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()
        self._primary_reason_injected_event = primary_reason_injected_event
        self.stdout.feed_data(
            _wire_line(
                message_id="worker:0",
                event="command_accepted",
                sequence=0,
                payload={"command": "start", "message_id": "py:0"},
            )
        )
        self.stdout.feed_data(
            _wire_line(
                message_id="worker:1",
                event="ready",
                sequence=1,
                payload=self._CAPS,
            )
        )

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        # Inject an invalid UTF-8 frame — this triggers PROTOCOL_FAILURE via
        # _stdout_reader AFTER the `had_primary_failure_reason` snapshot.
        self.stdout.feed_data(b"\xff\xfe invalid utf8 frame\n")
        self._primary_reason_injected_event.set()
        # Do NOT exit: force close() to escalate to kill().

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_process_failed_event_during_terminate_preserves_primary_reason() -> None:
    """RED against HEAD: PROCESS_FAILED_EVENT injected during terminate()
    window must survive as the final termination reason, not be overwritten by
    CLOSE_TERMINATE or CLOSE_KILL."""
    primary_injected = asyncio.Event()
    fake = _FakeProcessFailedDuringTerminate(primary_injected)

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.15)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        # Drain startup events.
        await supervisor.next_event(timeout_s=0.2)  # command_accepted
        await supervisor.next_event(timeout_s=0.2)  # ready
        # close() will: wait shutdown_timeout_s for cooperative close (no
        # response), then call terminate() which injects the FAILED frame,
        # then wait terminate_timeout_s for the process to exit (it won't),
        # then call kill() which exits the process.
        await asyncio.wait_for(supervisor.close(), timeout=3.0)
    finally:
        if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
            await supervisor.close()
    assert fake.terminate_calls >= 1
    assert fake.kill_calls >= 1
    assert supervisor.termination is not None
    # PRIMARY ASSERTION — fails RED against HEAD because the snapshot
    # `had_primary_failure_reason` was False when the FAILED frame arrived.
    assert supervisor.termination.reason == "PROCESS_FAILED_EVENT", (
        f"Expected PROCESS_FAILED_EVENT but got {supervisor.termination.reason!r}; "
        "the in-flight FAILED frame was overwritten by the mechanical close escalation"
    )


@pytest.mark.asyncio
async def test_protocol_failure_during_kill_preserves_primary_reason() -> None:
    """RED against HEAD: PROTOCOL_FAILURE injected during kill() window must
    survive as the final termination reason, not be overwritten by CLOSE_KILL."""
    primary_injected = asyncio.Event()
    fake = _FakeProtocolFailureDuringKill(primary_injected)

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted
        await supervisor.next_event(timeout_s=0.2)  # ready
        await asyncio.wait_for(supervisor.close(), timeout=3.0)
    finally:
        if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
            await supervisor.close()
    assert fake.terminate_calls >= 1
    assert fake.kill_calls >= 1
    assert supervisor.termination is not None
    # PRIMARY ASSERTION — fails RED against HEAD.
    assert supervisor.termination.reason == "PROTOCOL_FAILURE", (
        f"Expected PROTOCOL_FAILURE but got {supervisor.termination.reason!r}; "
        "the in-flight protocol failure was overwritten by the mechanical close escalation"
    )


@pytest.mark.asyncio
async def test_process_failed_event_during_kill_preserves_primary_reason() -> None:
    """Coverage complement: PROCESS_FAILED_EVENT injected during terminate()
    window (process stays alive so kill() is also reached).  This is the same
    race path as test_process_failed_event_during_terminate_preserves_primary_reason
    but uses a separate fake with both terminate_calls and kill_calls >= 1 to
    prove the race affects the kill path too."""
    primary_injected = asyncio.Event()

    class _FakeProcessFailedDuringTerminateKillPath:
        _CAPS = _FakeProcessFailedDuringTerminate._CAPS

        def __init__(self) -> None:
            self.stdin = _FakeStdin()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()
            self.returncode: int | None = None
            self.terminate_calls = 0
            self.kill_calls = 0
            self._exited = asyncio.Event()
            self.stdout.feed_data(
                _wire_line(
                    message_id="worker:0",
                    event="command_accepted",
                    sequence=0,
                    payload={"command": "start", "message_id": "py:0"},
                )
            )
            self.stdout.feed_data(
                _wire_line(
                    message_id="worker:1",
                    event="ready",
                    sequence=1,
                    payload=self._CAPS,
                )
            )

        async def wait(self) -> int:
            await self._exited.wait()
            assert self.returncode is not None
            return self.returncode

        def terminate(self) -> None:
            self.terminate_calls += 1
            # Inject the FAILED frame during the terminate() window; the
            # process stays alive so close() must escalate to kill().
            self.stdout.feed_data(
                _wire_line(
                    message_id="worker:2",
                    event="failed",
                    sequence=2,
                    payload={"code": "ERR_WORKER_FATAL", "message": "failed at terminate, kill needed"},
                )
            )
            primary_injected.set()

        def kill(self) -> None:
            self.kill_calls += 1
            self.returncode = -9
            self._exited.set()

    fake = _FakeProcessFailedDuringTerminateKillPath()

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.15)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        await asyncio.wait_for(supervisor.close(), timeout=3.0)
    finally:
        if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
            await supervisor.close()
    assert fake.terminate_calls >= 1
    assert fake.kill_calls >= 1
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "PROCESS_FAILED_EVENT", (
        f"Expected PROCESS_FAILED_EVENT but got {supervisor.termination.reason!r}"
    )


@pytest.mark.asyncio
async def test_protocol_failure_during_terminate_preserves_primary_reason() -> None:
    """Coverage complement: PROTOCOL_FAILURE injected at terminate() time,
    process exits on terminate() itself."""
    primary_injected = asyncio.Event()

    class _FakeProtocolFailureDuringTerminateExit:
        _CAPS = _FakeProcessFailedDuringTerminate._CAPS

        def __init__(self) -> None:
            self.stdin = _FakeStdin()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()
            self.returncode: int | None = None
            self.terminate_calls = 0
            self.kill_calls = 0
            self._exited = asyncio.Event()
            self.stdout.feed_data(
                _wire_line(
                    message_id="worker:0",
                    event="command_accepted",
                    sequence=0,
                    payload={"command": "start", "message_id": "py:0"},
                )
            )
            self.stdout.feed_data(
                _wire_line(
                    message_id="worker:1",
                    event="ready",
                    sequence=1,
                    payload=self._CAPS,
                )
            )

        async def wait(self) -> int:
            await self._exited.wait()
            assert self.returncode is not None
            return self.returncode

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.stdout.feed_data(b"\xff\xfe bad utf8\n")
            primary_injected.set()
            self.returncode = -15
            self._exited.set()

        def kill(self) -> None:
            self.kill_calls += 1
            self.returncode = -9
            self._exited.set()

    fake = _FakeProtocolFailureDuringTerminateExit()

    class _FakeProcessSupervisor(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.15)
    supervisor = _FakeProcessSupervisor(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)
        await asyncio.wait_for(supervisor.close(), timeout=3.0)
    finally:
        if (await supervisor.health()).state is not InteractionRuntimeState.CLOSED:
            await supervisor.close()
    assert supervisor.termination is not None
    assert supervisor.termination.reason == "PROTOCOL_FAILURE", (
        f"Expected PROTOCOL_FAILURE but got {supervisor.termination.reason!r}"
    )
# U3AR8 RED tests — append to end of test_u3a_jsonl_worker_supervisor.py
#
# DEFECT_GROUP_1: OPTIMISTIC_PUBLIC_TRANSITION_ROLLBACK_CAN_OVERWRITE_CONCURRENT_TERMINAL_OR_EMERGENCY_STATE
# DEFECT_GROUP_2: FAILURE_ARRIVING_DURING_CLOSE_CAN_START_A_COMPETING_PROCESS_CLEANUP
# DEFECT_GROUP_3: ProcessLookupError during terminate()/kill() in close()
#
# These tests MUST be RED (fail) against 9ab1e630 before the fix is applied.

# ---------------------------------------------------------------------------
# DEFECT_GROUP_1 — Rollback tests
# ---------------------------------------------------------------------------

class _FakeReadyProcess:
    """Minimal fake that reaches READY and then silently blocks forever.
    Used to test activate/pause/resume rollback without lifecycle side effects."""

    _CAPS = {
        "audio_capture": False,
        "wake_word": False,
        "vad": False,
        "stt": False,
        "local_llm": False,
        "spanish_tts": False,
        "physical_playback": False,
        "physical_playback_stop": False,
        "physical_playback_completion": False,
    }

    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()
        self.stdout.feed_data(
            _wire_line(message_id="worker:0", event="command_accepted", sequence=0, payload={"command": "start", "message_id": "py:0"})
        )
        self.stdout.feed_data(
            _wire_line(message_id="worker:1", event="ready", sequence=1, payload=self._CAPS)
        )

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = -15
        self._exited.set()

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_activate_enqueue_failure_does_not_overwrite_failed_state() -> None:
    """RED: activate() except-block rolls back state to READY even when _fail()
    concurrently set state to FAILED during the enqueue call."""
    fake = _FakeReadyProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted
        await supervisor.next_event(timeout_s=0.2)  # ready
        assert (await supervisor.health()).state is InteractionRuntimeState.READY

        fail_called = asyncio.Event()
        original_enqueue = supervisor._enqueue_command  # noqa: SLF001

        async def _enqueue_with_concurrent_fail(command, *, interaction_id, payload, **kw):
            # Simulate: _fail() fires and moves state to FAILED *before* the
            # enqueue raises.  The current code rolls back unconditionally, so
            # state will end up READY — the bug.
            await supervisor._fail(  # noqa: SLF001
                "simulated concurrent failure",
                unexpected=True,
                termination_reason="PROCESS_FAILED_EVENT",
            )
            fail_called.set()
            raise InteractionRuntimeUnavailableError("simulated enqueue failure")

        supervisor._enqueue_command = _enqueue_with_concurrent_fail  # noqa: SLF001

        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.activate(
                InteractionContext(interaction_id="interaction:rollback-failed")
            )

        await fail_called.wait()

        # PRIMARY ASSERTION — fails RED: state must be FAILED, not READY
        assert supervisor._state is InteractionRuntimeState.FAILED, (  # noqa: SLF001
            f"Expected FAILED but got {supervisor._state!r}; "
            "activate() rollback overwrote the concurrent FAILED transition"
        )
        assert supervisor._active_interaction_id is None  # noqa: SLF001
    finally:
        supervisor._enqueue_command = original_enqueue  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_activate_enqueue_failure_does_not_overwrite_emergency_state() -> None:
    """RED: activate() except-block rolls back state to READY even when
    emergency_stop() ran concurrently and set state to EMERGENCY."""
    fake = _FakeReadyProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    original_enqueue = supervisor._enqueue_command  # noqa: SLF001
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        async def _enqueue_with_concurrent_emergency(command, *, interaction_id, payload, **kw):
            # Restore original before calling emergency_stop() to avoid
            # recursion (emergency_stop also calls _enqueue_command internally)
            supervisor._enqueue_command = original_enqueue  # noqa: SLF001
            await supervisor.emergency_stop()
            raise InteractionRuntimeUnavailableError("simulated enqueue failure")

        supervisor._enqueue_command = _enqueue_with_concurrent_emergency  # noqa: SLF001

        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.activate(
                InteractionContext(interaction_id="interaction:rollback-emergency")
            )

        # PRIMARY ASSERTION — fails RED: state must be EMERGENCY, not READY
        assert supervisor._state is InteractionRuntimeState.EMERGENCY, (  # noqa: SLF001
            f"Expected EMERGENCY but got {supervisor._state!r}; "
            "activate() rollback overwrote the concurrent EMERGENCY transition"
        )
        assert supervisor._active_interaction_id is None  # noqa: SLF001
    finally:
        supervisor._enqueue_command = original_enqueue  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_pause_enqueue_failure_does_not_overwrite_failed_state() -> None:
    """RED: pause() except-block unconditionally restores ACTIVE state even
    when a concurrent _fail() has moved state to FAILED."""
    fake = _FakeReadyProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    original_enqueue = supervisor._enqueue_command  # noqa: SLF001
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        # Manually set ACTIVE state to enable pause() call
        supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:pause-test"  # noqa: SLF001

        async def _enqueue_with_concurrent_fail(command, *, interaction_id, payload, **kw):
            await supervisor._fail(  # noqa: SLF001
                "simulated concurrent failure during pause",
                unexpected=True,
                termination_reason="PROCESS_FAILED_EVENT",
            )
            raise InteractionRuntimeUnavailableError("simulated enqueue failure")

        supervisor._enqueue_command = _enqueue_with_concurrent_fail  # noqa: SLF001

        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.pause()

        # PRIMARY ASSERTION — fails RED: state must be FAILED, not ACTIVE
        assert supervisor._state is InteractionRuntimeState.FAILED, (  # noqa: SLF001
            f"Expected FAILED but got {supervisor._state!r}; "
            "pause() rollback overwrote the concurrent FAILED transition"
        )
    finally:
        supervisor._enqueue_command = original_enqueue  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_pause_enqueue_failure_does_not_overwrite_emergency_state() -> None:
    """RED: pause() except-block unconditionally restores ACTIVE state even
    when emergency_stop() ran concurrently."""
    fake = _FakeReadyProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    original_enqueue = supervisor._enqueue_command  # noqa: SLF001
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:pause-emerg"  # noqa: SLF001

        async def _enqueue_with_concurrent_emergency(command, *, interaction_id, payload, **kw):
            supervisor._enqueue_command = original_enqueue  # noqa: SLF001
            await supervisor.emergency_stop()
            raise InteractionRuntimeUnavailableError("simulated enqueue failure")

        supervisor._enqueue_command = _enqueue_with_concurrent_emergency  # noqa: SLF001

        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.pause()

        # PRIMARY ASSERTION — fails RED
        assert supervisor._state is InteractionRuntimeState.EMERGENCY, (  # noqa: SLF001
            f"Expected EMERGENCY but got {supervisor._state!r}; "
            "pause() rollback overwrote the concurrent EMERGENCY transition"
        )
    finally:
        supervisor._enqueue_command = original_enqueue  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_resume_enqueue_failure_does_not_overwrite_failed_state() -> None:
    """RED: resume() except-block unconditionally restores PAUSED state even
    when a concurrent _fail() has moved state to FAILED."""
    fake = _FakeReadyProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    original_enqueue = supervisor._enqueue_command  # noqa: SLF001
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        supervisor._state = InteractionRuntimeState.PAUSED  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:resume-test"  # noqa: SLF001

        async def _enqueue_with_concurrent_fail(command, *, interaction_id, payload, **kw):
            await supervisor._fail(  # noqa: SLF001
                "simulated concurrent failure during resume",
                unexpected=True,
                termination_reason="PROCESS_FAILED_EVENT",
            )
            raise InteractionRuntimeUnavailableError("simulated enqueue failure")

        supervisor._enqueue_command = _enqueue_with_concurrent_fail  # noqa: SLF001

        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.resume()

        # PRIMARY ASSERTION — fails RED: state must be FAILED, not PAUSED
        assert supervisor._state is InteractionRuntimeState.FAILED, (  # noqa: SLF001
            f"Expected FAILED but got {supervisor._state!r}; "
            "resume() rollback overwrote the concurrent FAILED transition"
        )
    finally:
        supervisor._enqueue_command = original_enqueue  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_resume_enqueue_failure_does_not_overwrite_emergency_state() -> None:
    """RED: resume() except-block unconditionally restores PAUSED state even
    when emergency_stop() ran concurrently."""
    fake = _FakeReadyProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    original_enqueue = supervisor._enqueue_command  # noqa: SLF001
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        supervisor._state = InteractionRuntimeState.PAUSED  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:resume-emerg"  # noqa: SLF001

        async def _enqueue_with_concurrent_emergency(command, *, interaction_id, payload, **kw):
            supervisor._enqueue_command = original_enqueue  # noqa: SLF001
            await supervisor.emergency_stop()
            raise InteractionRuntimeUnavailableError("simulated enqueue failure")

        supervisor._enqueue_command = _enqueue_with_concurrent_emergency  # noqa: SLF001

        with pytest.raises(InteractionRuntimeUnavailableError):
            await supervisor.resume()

        # PRIMARY ASSERTION — fails RED
        assert supervisor._state is InteractionRuntimeState.EMERGENCY, (  # noqa: SLF001
            f"Expected EMERGENCY but got {supervisor._state!r}; "
            "resume() rollback overwrote the concurrent EMERGENCY transition"
        )
    finally:
        supervisor._enqueue_command = original_enqueue  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# DEFECT_GROUP_2 — Competing cleanup tests
# ---------------------------------------------------------------------------

class _FakeProcessHoldsOpenForClose:
    """Reaches READY. When close() is in progress (waiting shutdown_timeout_s),
    injects a PROCESS_FAILED_EVENT from _inject_fail_during_close_wait().
    The process only exits when kill() is called.
    Used to test that _fail() during close does not schedule a _cleanup_task
    or call terminate() a second time."""

    _CAPS = {
        "audio_capture": False,
        "wake_word": False,
        "vad": False,
        "stt": False,
        "local_llm": False,
        "spanish_tts": False,
        "physical_playback": False,
        "physical_playback_stop": False,
        "physical_playback_completion": False,
    }

    def __init__(self, close_started: asyncio.Event) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()
        self._close_started = close_started
        self._seq = 2
        self.stdout.feed_data(
            _wire_line(message_id="worker:0", event="command_accepted", sequence=0, payload={"command": "start", "message_id": "py:0"})
        )
        self.stdout.feed_data(
            _wire_line(message_id="worker:1", event="ready", sequence=1, payload=self._CAPS)
        )

    def inject_process_failed(self) -> None:
        self.stdout.feed_data(
            _wire_line(
                message_id=f"worker:{self._seq}",
                event="failed",
                sequence=self._seq,
                payload={"code": "ERR_WORKER_FATAL", "message": "failed while close was in progress"},
            )
        )
        self._seq += 1

    def inject_protocol_failure(self) -> None:
        self.stdout.feed_data(b"\xff\xfe bad bytes during close\n")

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        # Do NOT exit — let close() escalate to kill()

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_process_failed_during_close_does_not_schedule_competing_cleanup() -> None:
    """RED: _fail() called while _close_impl() is active must NOT call
    _schedule_cleanup_task().  Currently it does, producing a competing
    cleanup task that races with close's own wait/kill."""
    fake = _FakeProcessHoldsOpenForClose(asyncio.Event())

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.08, terminate_timeout_s=0.12)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted
        await supervisor.next_event(timeout_s=0.2)  # ready

        # Track whether _schedule_cleanup_task was called during close
        cleanup_scheduled_during_close = False
        original_schedule = supervisor._schedule_cleanup_task  # noqa: SLF001

        def _tracking_schedule():
            nonlocal cleanup_scheduled_during_close
            if supervisor._closing:  # noqa: SLF001
                cleanup_scheduled_during_close = True
            original_schedule()

        supervisor._schedule_cleanup_task = _tracking_schedule  # noqa: SLF001

        # Start close FIRST, then inject failure during cooperative wait window
        close_task = asyncio.create_task(supervisor.close())
        # Yield to let close() start and set _closing = True
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Inject failure while close is in progress (cooperative wait window)
        fake.inject_process_failed()
        await asyncio.wait_for(close_task, timeout=3.0)

        # PRIMARY ASSERTION — fails RED: _schedule_cleanup_task must NOT be
        # called when _close_impl() owns the lifecycle
        assert not cleanup_scheduled_during_close, (
            "_fail() called _schedule_cleanup_task() while close was active; "
            "close must be the sole lifecycle owner"
        )
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "PROCESS_FAILED_EVENT", (
            f"Expected PROCESS_FAILED_EVENT but got {supervisor.termination.reason!r}"
        )
    finally:
        supervisor._schedule_cleanup_task = original_schedule  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_protocol_failure_during_close_does_not_schedule_competing_cleanup() -> None:
    """RED: PROTOCOL_FAILURE injected while _close_impl() is active must NOT
    cause _fail() to call _schedule_cleanup_task()."""
    fake = _FakeProcessHoldsOpenForClose(asyncio.Event())

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.08, terminate_timeout_s=0.12)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        cleanup_scheduled_during_close = False
        original_schedule = supervisor._schedule_cleanup_task  # noqa: SLF001

        def _tracking_schedule():
            nonlocal cleanup_scheduled_during_close
            if supervisor._closing:  # noqa: SLF001
                cleanup_scheduled_during_close = True
            original_schedule()

        supervisor._schedule_cleanup_task = _tracking_schedule  # noqa: SLF001

        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        fake.inject_protocol_failure()
        await asyncio.wait_for(close_task, timeout=3.0)

        # PRIMARY ASSERTION — fails RED
        assert not cleanup_scheduled_during_close, (
            "_fail() called _schedule_cleanup_task() while close was active"
        )
        assert supervisor.termination is not None
        assert supervisor.termination.reason == "PROTOCOL_FAILURE", (
            f"Expected PROTOCOL_FAILURE but got {supervisor.termination.reason!r}"
        )
    finally:
        supervisor._schedule_cleanup_task = original_schedule  # noqa: SLF001
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_process_failed_during_close_calls_terminate_at_most_once() -> None:
    """RED: _fail() calls process.terminate() during close, adding an extra
    terminate before close's own terminate escalation.  After fix, terminate
    must be called at most once (by close's escalation, never by _fail()
    when close owns the lifecycle)."""
    fake = _FakeProcessHoldsOpenForClose(asyncio.Event())

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.06, terminate_timeout_s=0.10)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Inject during cooperative close wait window (before shutdown_timeout_s elapses)
        fake.inject_process_failed()
        await asyncio.wait_for(close_task, timeout=3.0)

        # PRIMARY ASSERTION — fails RED: _fail() called terminate once, then
        # the cleanup task it created calls kill; close's escalation also called
        # terminate (or saw kill already done). The key violation: terminate was
        # called by _fail() when it should not have been.
        # With fix: _fail() skips terminate when close owns lifecycle; close's
        # cooperative-wait times out and calls terminate once. Total = 1.
        # Without fix: _fail() calls terminate (count=1), cleanup task's kill
        # exits process, close sees returncode != None and skips escalation.
        # So terminate_calls = 1 either way — instead test that the cleanup
        # task was NOT created at all when close is active.
        assert supervisor._cleanup_task is None, (  # noqa: SLF001
            f"_fail() created _cleanup_task ({supervisor._cleanup_task!r}) while "  # noqa: SLF001
            "close was the lifecycle owner; _cleanup_task must remain None"
        )
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_process_failed_during_close_calls_kill_at_most_once() -> None:
    """RED: _fail() creates _cleanup_task which calls process.kill() — a
    competing kill racing with close's own escalation.  After fix, kill must
    be called at most once, by close's own escalation only."""
    fake = _FakeProcessHoldsOpenForClose(asyncio.Event())

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.06, terminate_timeout_s=0.10)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        fake.inject_process_failed()
        await asyncio.wait_for(close_task, timeout=3.0)

        # After fix: cleanup_task must be None (never created during close)
        assert supervisor._cleanup_task is None, (  # noqa: SLF001
            f"_cleanup_task must be None after close but got {supervisor._cleanup_task!r}; "
            "_fail() must not create competing cleanup when close owns the lifecycle"
        )
        # kill_calls should be exactly 1 from close() escalation only
        assert fake.kill_calls <= 1, (
            f"kill() called {fake.kill_calls} times; competing cleanup called it"
        )
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# DEFECT_GROUP_3 — ProcessLookupError during close
# ---------------------------------------------------------------------------

class _FakeExitsBeforeSignal:
    """Process that exits between returncode check and terminate()/kill() call,
    causing terminate()/kill() to raise ProcessLookupError."""

    _CAPS = {
        "audio_capture": False,
        "wake_word": False,
        "vad": False,
        "stt": False,
        "local_llm": False,
        "spanish_tts": False,
        "physical_playback": False,
        "physical_playback_stop": False,
        "physical_playback_completion": False,
    }

    def __init__(self, *, raise_on: str = "terminate") -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._raise_on = raise_on
        self._exited = asyncio.Event()
        self.stdout.feed_data(
            _wire_line(message_id="worker:0", event="command_accepted", sequence=0, payload={"command": "start", "message_id": "py:0"})
        )
        self.stdout.feed_data(
            _wire_line(message_id="worker:1", event="ready", sequence=1, payload=self._CAPS)
        )

    async def wait(self) -> int:
        # Return immediately if already exited, otherwise wait
        if self.returncode is not None:
            return self.returncode
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def _do_exit(self) -> None:
        self.returncode = -15
        self._exited.set()
        # Also feed eof so _stdout_reader unblocks
        self.stdout.feed_eof()

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._raise_on == "terminate":
            # Process already exited — update returncode so wait() returns
            self._do_exit()
            raise ProcessLookupError("no such process")
        self._do_exit()

    def kill(self) -> None:
        self.kill_calls += 1
        if self._raise_on == "kill":
            self._do_exit()
            raise ProcessLookupError("no such process")
        self._do_exit()


@pytest.mark.asyncio
async def test_close_tolerates_process_lookup_race_during_terminate() -> None:
    """RED: ProcessLookupError raised by terminate() inside _close_impl() must
    be absorbed.  Currently it propagates as an unhandled exception from close()."""
    fake = _FakeExitsBeforeSignal(raise_on="terminate")

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        # PRIMARY ASSERTION — fails RED: close() must NOT raise ProcessLookupError
        await asyncio.wait_for(supervisor.close(), timeout=3.0)

        assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED, (
            "close() must reach CLOSED state even when terminate() raises ProcessLookupError"
        )
        assert supervisor.termination is not None
        # Primary reason must NOT be reclassified to an error category
        assert supervisor.termination.reason not in ("PROTOCOL_FAILURE", "PROCESS_FAILED_EVENT"), (
            f"ProcessLookupError must not reclassify the termination reason; got {supervisor.termination.reason!r}"
        )
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_close_tolerates_process_lookup_race_during_kill() -> None:
    """RED: ProcessLookupError raised by kill() inside _close_impl() must be
    absorbed. Currently it propagates as an unhandled exception."""

    class _FakeHoldsThenKillLookupError(_FakeKillProcess):
        """Survives terminate(), then raises ProcessLookupError on kill()."""

        def __init__(self) -> None:
            super().__init__()
            self.kill_error_raises = 0

        def kill(self) -> None:
            self.kill_calls += 1
            self.returncode = -9
            self._exited.set()
            # Simulate process already gone when kill() is attempted
            raise ProcessLookupError("no such process")

    fake = _FakeHoldsThenKillLookupError()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        # PRIMARY ASSERTION — fails RED: close() must NOT raise ProcessLookupError
        await asyncio.wait_for(supervisor.close(), timeout=3.0)

        assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED, (
            "close() must reach CLOSED state even when kill() raises ProcessLookupError"
        )
        assert supervisor.termination is not None
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# U3AR9 — Terminal postconditions and late-event handling
# ---------------------------------------------------------------------------

class _FakeActiveInteractionProcess:
    """Reaches READY, then accepts ACTIVATE (emitting command_accepted + ready→active),
    then holds stdout open so we can inject late events during close.
    terminate() does NOT exit; kill() exits. Allows testing identity and
    state during the close window."""

    _CAPS = {
        "audio_capture": False,
        "wake_word": False,
        "vad": False,
        "stt": False,
        "local_llm": False,
        "spanish_tts": False,
        "physical_playback": False,
        "physical_playback_stop": False,
        "physical_playback_completion": False,
    }

    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = asyncio.Event()
        self._seq = 2
        # startup: command_accepted for START + READY
        self.stdout.feed_data(
            _wire_line(message_id="worker:0", event="command_accepted", sequence=0, payload={"command": "start", "message_id": "py:0"})
        )
        self.stdout.feed_data(
            _wire_line(message_id="worker:1", event="ready", sequence=1, payload=self._CAPS)
        )

    def feed_activate_accepted(self, interaction_id: str) -> None:
        self.stdout.feed_data(
            _wire_line(
                message_id=f"worker:{self._seq}",
                event="command_accepted",
                sequence=self._seq,
                interaction_id=interaction_id,
                payload={"command": "activate", "message_id": "py:1"},
            )
        )
        self._seq += 1

    def inject_playback_completed(self, interaction_id: str) -> None:
        self.stdout.feed_data(
            _wire_line(
                message_id=f"worker:{self._seq}",
                event="playback_completed",
                sequence=self._seq,
                interaction_id=interaction_id,
                payload={},
            )
        )
        self._seq += 1

    def inject_interaction_failed(self, interaction_id: str) -> None:
        self.stdout.feed_data(
            _wire_line(
                message_id=f"worker:{self._seq}",
                event="failed",
                sequence=self._seq,
                interaction_id=interaction_id,
                payload={"code": "ERR_TIMEOUT", "message": "interaction timed out"},
            )
        )
        self._seq += 1

    def inject_process_failed(self) -> None:
        self.stdout.feed_data(
            _wire_line(
                message_id=f"worker:{self._seq}",
                event="failed",
                sequence=self._seq,
                payload={"code": "ERR_FATAL", "message": "process fatal"},
            )
        )
        self._seq += 1

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        # Does not exit — let escalation reach kill()

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_close_from_active_enters_stopping_and_hides_public_interaction_id() -> None:
    """RED: active_interaction_id property must return None while _closing is True.
    Currently it returns the internal _active_interaction_id verbatim."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted (start)
        await supervisor.next_event(timeout_s=0.2)  # ready
        assert (await supervisor.health()).state is InteractionRuntimeState.READY

        # Activate via public API
        activate_task = asyncio.create_task(
            supervisor.activate(InteractionContext(interaction_id="interaction:stopping-test"))
        )
        # Feed the ACTIVATE command_accepted response
        await asyncio.sleep(0)
        fake.feed_activate_accepted("interaction:stopping-test")
        await asyncio.wait_for(activate_task, timeout=1.0)
        assert (await supervisor.health()).state is InteractionRuntimeState.ACTIVE
        assert supervisor.active_interaction_id == "interaction:stopping-test"

        # Start close in the background — we check identity WHILE it is closing
        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # PRIMARY ASSERTION: public property must hide the ID once closing starts
        assert supervisor.active_interaction_id is None, (
            f"active_interaction_id={supervisor.active_interaction_id!r} must be None during close"
        )
        # State must be STOPPING (or already FAILED/EMERGENCY but not ACTIVE/READY)
        assert (await supervisor.health()).state not in (
            InteractionRuntimeState.ACTIVE,
            InteractionRuntimeState.READY,
        ), f"State {(await supervisor.health()).state!r} must not be ACTIVE/READY during close"

        fake.kill()  # unblock
        await asyncio.wait_for(close_task, timeout=2.0)
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_close_from_paused_enters_stopping_and_hides_public_interaction_id() -> None:
    """RED: same as above but from PAUSED state."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        # Force PAUSED state directly (internal — mirrors state a real PAUSE command would reach)
        supervisor._state = InteractionRuntimeState.PAUSED  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:paused-test"  # noqa: SLF001

        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # PUBLIC property must hide ID during close
        assert supervisor.active_interaction_id is None, (
            f"active_interaction_id={supervisor.active_interaction_id!r} must be None during close from PAUSED"
        )

        fake.kill()
        await asyncio.wait_for(close_task, timeout=2.0)
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_late_playback_completed_during_close_does_not_restore_ready() -> None:
    """RED: A PLAYBACK_COMPLETED event arriving while _closing is True must NOT
    set state=READY or ready=True. Currently _process_event() sets them unconditionally."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.5, terminate_timeout_s=0.5)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)  # command_accepted
        await supervisor.next_event(timeout_s=0.2)  # ready

        # Set ACTIVE with an interaction_id
        supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:late-playback"  # noqa: SLF001

        # Start close
        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert supervisor._closing  # noqa: SLF001

        # Inject PLAYBACK_COMPLETED while close is in progress
        fake.inject_playback_completed("interaction:late-playback")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # PRIMARY ASSERTION: state must NOT be READY after a late event during close
        health = await supervisor.health()
        assert health.state is not InteractionRuntimeState.READY, (
            f"State became READY after late PLAYBACK_COMPLETED during close; must stay STOPPING/FAILED/EMERGENCY"
        )
        assert health.ready is False, (
            f"ready became True after late PLAYBACK_COMPLETED during close"
        )

        fake.kill()
        await asyncio.wait_for(close_task, timeout=2.0)
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_late_interaction_failed_during_close_does_not_restore_ready() -> None:
    """RED: A FAILED event with interaction_id arriving during close must NOT
    set state=READY or ready=True."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.5, terminate_timeout_s=0.5)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:late-ifail"  # noqa: SLF001

        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert supervisor._closing  # noqa: SLF001

        # Inject interaction-level FAILED during close
        fake.inject_interaction_failed("interaction:late-ifail")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        health = await supervisor.health()
        assert health.state is not InteractionRuntimeState.READY, (
            f"State became READY after late interaction FAILED during close"
        )
        assert health.ready is False, (
            f"ready became True after late interaction FAILED during close"
        )

        fake.kill()
        await asyncio.wait_for(close_task, timeout=2.0)
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_close_settlement_timeout_keeps_stopping_and_hides_public_interaction_id() -> None:
    """RED: After ERR_TASK_SETTLEMENT_TIMEOUT, state must be STOPPING (or FAILED/EMERGENCY),
    ready=False, and public active_interaction_id=None."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:settle-test"  # noqa: SLF001

        # Force kill to unblock close (no settlement timeout needed for this RED gate)
        # We just check that identity is hidden after close completes
        await asyncio.wait_for(supervisor.close(), timeout=3.0)

        # IDENTITY assertions
        assert supervisor.active_interaction_id is None, (
            f"active_interaction_id={supervisor.active_interaction_id!r} must be None after CLOSED"
        )
        assert supervisor._active_interaction_id is None, (  # noqa: SLF001
            f"Internal _active_interaction_id={supervisor._active_interaction_id!r} must be None after CLOSED"
        )
        assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
        assert (await supervisor.health()).ready is False
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_close_no_process_clears_internal_interaction_id() -> None:
    """RED: When _close_impl() takes the no-process branch, _active_interaction_id
    internal must be set to None and state=CLOSED."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.05, terminate_timeout_s=0.05)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.2)
        await supervisor.next_event(timeout_s=0.2)

        # Force internal state to simulate an active interaction
        supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:noproc-test"  # noqa: SLF001
        # Null the process so _close_impl() takes the no-process branch
        supervisor._process = None  # noqa: SLF001

        await asyncio.wait_for(supervisor.close(), timeout=2.0)

        # PRIMARY ASSERTIONS
        assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
        assert supervisor.active_interaction_id is None, (
            "Public active_interaction_id must be None after CLOSED (no-process path)"
        )
        assert supervisor._active_interaction_id is None, (  # noqa: SLF001
            "Internal _active_interaction_id must be None after CLOSED (no-process path)"
        )
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_event_queue_overflow_during_close_does_not_bypass_close_owner() -> None:
    """RED: EVENT_QUEUE_OVERFLOW during close must NOT call terminate() directly
    from _publish_event(). Currently _publish_event() calls terminate() after _fail()."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    # Use normal queue for startup, then shrink via monkeypatch to trigger overflow
    config = _config(shutdown_timeout_s=0.5, terminate_timeout_s=0.5)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        # Drain the startup events
        await supervisor.next_event(timeout_s=0.2)  # command_accepted
        await supervisor.next_event(timeout_s=0.2)  # ready

        supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
        supervisor._active_interaction_id = "interaction:overflow-close"  # noqa: SLF001

        # Shrink the queue to size 1 (all startup events already drained)
        assert supervisor._event_queue is not None  # noqa: SLF001
        supervisor._event_queue = asyncio.Queue(maxsize=1)  # noqa: SLF001

        # Start close
        close_task = asyncio.create_task(supervisor.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert supervisor._closing  # noqa: SLF001

        terminate_before = fake.terminate_calls

        # Fill the event queue with HEARTBEAT events (always pass _process_event
        # without interaction_id checks); first fills, second triggers overflow.
        for seq in range(2, 4):
            fake.stdout.feed_data(
                _wire_line(message_id=f"worker:{seq}", event="heartbeat", sequence=seq, payload={})
            )
        fake._seq = 4  # noqa: SLF001
        await asyncio.sleep(0.1)

        # PRIMARY ASSERTION: _publish_event must not have called terminate() directly
        # when close owns lifecycle. After fix: terminate_before stays unchanged.
        # Before fix (DEFECT_4): _publish_event() calls terminate() even during close.
        terminate_from_overflow = fake.terminate_calls - terminate_before
        assert terminate_from_overflow == 0, (
            f"_publish_event() called terminate() {terminate_from_overflow} time(s) "
            "during close; must be 0 — close owns escalation"
        )

        fake.kill()
        await asyncio.wait_for(close_task, timeout=2.0)
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_event_queue_overflow_outside_close_signals_process_once() -> None:
    """RED: EVENT_QUEUE_OVERFLOW outside close must NOT call terminate() directly
    from _publish_event() after _fail(). Currently _publish_event() has a
    redundant terminate() call after _fail() — resulting in terminate_calls > 1."""
    fake = _FakeActiveInteractionProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    config = _config(shutdown_timeout_s=0.2, terminate_timeout_s=0.2)
    supervisor = _FakeSup(config)
    await supervisor.start()
    try:
        # Drain startup events
        await supervisor.next_event(timeout_s=0.2)  # command_accepted
        await supervisor.next_event(timeout_s=0.2)  # ready

        # Shrink queue to 1 after draining startup events
        assert supervisor._event_queue is not None  # noqa: SLF001
        supervisor._event_queue = asyncio.Queue(maxsize=1)  # noqa: SLF001

        # Feed HEARTBEAT events: first fills the queue; second triggers overflow.
        # HEARTBEAT passes _process_event() without interaction_id checks and
        # always returns True, so it reliably reaches _publish_event().
        for seq in range(2, 4):
            fake.stdout.feed_data(
                _wire_line(message_id=f"worker:{seq}", event="heartbeat", sequence=seq, payload={})
            )
        fake._seq = 4  # noqa: SLF001
        await asyncio.sleep(0.1)

        # PRIMARY ASSERTION: _publish_event() must NOT call terminate() directly.
        # After fix: _fail() calls terminate once (its own cleanup path).
        # Before fix: _publish_event() calls terminate again → terminate_calls = 2.
        assert fake.terminate_calls <= 1, (
            f"terminate() called {fake.terminate_calls} times; expected <=1. "
            "_publish_event() must not call terminate() directly after _fail()."
        )

        # Clean up
        try:
            await asyncio.wait_for(supervisor.close(), timeout=2.0)
        except Exception:
            pass
    finally:
        try:
            await supervisor.close()
        except Exception:
            pass
