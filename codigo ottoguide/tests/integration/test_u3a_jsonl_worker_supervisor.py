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
        pass

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
