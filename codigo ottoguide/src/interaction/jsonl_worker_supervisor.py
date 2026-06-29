"""Supervised JSONL interaction worker runtime.

The supervisor is stdlib-only and owns one child process that speaks the
versioned interaction protocol over stdin/stdout JSONL. stdout is protocol
only; stderr is drained as logs.
"""
from __future__ import annotations

import asyncio
import json
import math
import platform
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque

from src.interaction.runtime_port import (
    ERR_CLOSING,
    ERR_CORRELATION,
    ERR_DUPLICATE_MESSAGE_ID,
    ERR_EMERGENCY,
    ERR_FRAMING,
    ERR_JSON,
    ERR_LINE_TOO_LARGE,
    ERR_MESSAGE_LIMIT,
    ERR_PENDING_COMMAND_LIMIT,
    ERR_QUEUE_FULL,
    ERR_SEQUENCE,
    ERR_STALE_INTERACTION,
    ERR_STATE,
    ERR_TASK_SETTLEMENT_TIMEOUT,
    ERR_TERMINAL_STATE,
    ERR_TYPE,
    ERR_UTF8,
    INTERACTION_PROTOCOL_VERSION,
    InteractionContext,
    InteractionRuntimeCapabilities,
    InteractionRuntimeHealth,
    InteractionRuntimeProtocolError,
    InteractionRuntimeState,
    InteractionRuntimeUnavailableError,
    WorkerCommandEnvelope,
    WorkerCommandType,
    WorkerEventEnvelope,
    WorkerEventType,
)
from src.interaction.worker_supervisor import InteractionWorkerSupervisor, WorkerTermination


_STDOUT_READ_CHUNK_BYTES = 65536
TASK_SETTLEMENT_TIMEOUT = "TASK_SETTLEMENT_TIMEOUT"
_REAL_PRIMARY_TERMINATION_REASONS = frozenset(
    {
        "PROCESS_FAILED_EVENT",
        "PROTOCOL_FAILURE",
        "HEARTBEAT_TIMEOUT",
        "STARTUP_TIMEOUT",
        "WRITE_FAILURE",
        "EVENT_QUEUE_OVERFLOW",
        "COMMAND_ACK_BACKPRESSURE",
        "EMERGENCY_STOP",
        "UNEXPECTED_EXIT",
    }
)

def _is_real_primary_termination(termination: WorkerTermination | None) -> bool:
    if termination is None:
        return False
    return termination.reason in _REAL_PRIMARY_TERMINATION_REASONS


@dataclass(frozen=True, slots=True)
class OwnedTaskSettlement:
    settled_task_names: tuple[str, ...]
    cancelled_task_names: tuple[str, ...]
    pending_task_names: tuple[str, ...]
    timed_out: bool


@dataclass(frozen=True, slots=True)
class JsonlWorkerSupervisorConfig:
    argv: tuple[str, ...]
    startup_timeout_s: float = 3.0
    heartbeat_timeout_s: float = 5.0
    write_timeout_s: float = 1.0
    shutdown_timeout_s: float = 2.0
    terminate_timeout_s: float = 1.0
    command_queue_size: int = 32
    event_queue_size: int = 64
    max_line_bytes: int = 65536
    stderr_tail_lines: int = 50
    stderr_tail_max_chars: int = 16384
    max_seen_message_ids: int = 4096
    max_pending_commands: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.argv, tuple):
            object.__setattr__(self, "argv", tuple(self.argv))
        if not self.argv:
            raise ValueError("argv must not be empty")
        for item in self.argv:
            if type(item) is not str or not item:
                raise ValueError("argv entries must be non-empty strings")
        for name in (
            "startup_timeout_s",
            "heartbeat_timeout_s",
            "write_timeout_s",
            "shutdown_timeout_s",
            "terminate_timeout_s",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
            object.__setattr__(self, name, float(value))
        for name in (
            "command_queue_size",
            "event_queue_size",
            "max_line_bytes",
            "stderr_tail_lines",
            "stderr_tail_max_chars",
            "max_seen_message_ids",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        if self.max_pending_commands is None:
            object.__setattr__(self, "max_pending_commands", self.command_queue_size + 1)
        elif type(self.max_pending_commands) is not int or self.max_pending_commands <= 0:
            raise ValueError("max_pending_commands must be a positive int")


class JsonlInteractionWorkerSupervisor(InteractionWorkerSupervisor):
    def __init__(self, config: JsonlWorkerSupervisorConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._command_queue: asyncio.Queue[WorkerCommandEnvelope | None] | None = None
        self._event_queue: asyncio.Queue[WorkerEventEnvelope | None] | None = None
        self._tasks: set[asyncio.Task[object]] = set()
        self._state = InteractionRuntimeState.NOT_STARTED
        self._ready = False
        self._capabilities = InteractionRuntimeCapabilities()
        self._last_heartbeat_monotonic_s: float | None = None
        self._last_error: str | None = None
        self._termination: WorkerTermination | None = None
        self._active_interaction_id: str | None = None
        self._closing = False
        self._emergency_latched = False
        self._ready_event: asyncio.Event | None = None
        self._closed_event: asyncio.Event | None = None
        self._next_event_in_progress = False
        self._outgoing_sequence = 0
        self._incoming_sequence = 0
        self._seen_message_ids: set[str] = set()
        self._stderr_tail: Deque[str] = deque()
        self._stderr_chars = 0
        self._stderr_partial_tail: bytes = b""
        self._command_lock = asyncio.Lock()
        self._event_stream_terminal = asyncio.Event()
        self._event_stream_terminal_error: str | None = None
        self._pending_commands: dict[str, tuple[WorkerCommandType, str | None]] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._owned_task_cancel_timeout_s = 2.0
        self._close_task: asyncio.Task[None] | None = None

    @property
    def termination(self) -> WorkerTermination | None:
        return self._termination

    @property
    def active_interaction_id(self) -> str | None:
        return self._active_interaction_id

    async def _create_process(self) -> asyncio.subprocess.Process:
        """Spawn the child process. Overridable by tests to inject a fake
        process object without going through a real OS process, e.g. to
        deterministically exercise the terminate -> kill escalation path."""
        return await asyncio.create_subprocess_exec(
            *self._config.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self._config.max_line_bytes + 1024,
        )

    async def start(self) -> None:
        if self._process is not None:
            raise InteractionRuntimeUnavailableError("worker already started")
        self._state = InteractionRuntimeState.STARTING
        self._ready = False
        self._ready_event = asyncio.Event()
        self._closed_event = asyncio.Event()
        self._command_queue = asyncio.Queue(maxsize=self._config.command_queue_size)
        self._event_queue = asyncio.Queue(maxsize=self._config.event_queue_size)
        try:
            self._process = await self._create_process()
            self._spawn_task(self._command_writer(), "interaction-jsonl-command-writer")
            self._spawn_task(self._stdout_reader(), "interaction-jsonl-stdout-reader")
            self._spawn_task(self._stderr_drain(), "interaction-jsonl-stderr-drain")
            self._spawn_task(self._process_watcher(), "interaction-jsonl-process-watcher")
            self._spawn_task(self._heartbeat_monitor(), "interaction-jsonl-heartbeat-monitor")
            await self._enqueue_command(WorkerCommandType.START, interaction_id=None, payload={})
            await asyncio.wait_for(self._ready_event.wait(), timeout=self._config.startup_timeout_s)
            if self._state != InteractionRuntimeState.READY:
                raise InteractionRuntimeUnavailableError("worker did not become ready")
        except Exception:
            if self._state not in (InteractionRuntimeState.READY, InteractionRuntimeState.EMERGENCY):
                await self._fail(
                    "startup failed",
                    unexpected=True,
                    termination_reason="STARTUP_TIMEOUT",
                )
            # _fail() (above, or already triggered by one of the owned
            # tasks racing with this except block) schedules an owned
            # cleanup task. start() must not return/raise until that
            # cleanup has actually finished, so a caller that never invokes
            # close() still observes a fully reaped child and zero owned
            # tasks the instant start() raises.
            if self._cleanup_task is not None:
                cleanup_results = await asyncio.gather(self._cleanup_task, return_exceptions=True)
                for cleanup_result in cleanup_results:
                    if (
                        isinstance(cleanup_result, InteractionRuntimeUnavailableError)
                        and cleanup_result.code == ERR_TASK_SETTLEMENT_TIMEOUT
                    ):
                        raise cleanup_result
            raise

    async def health(self) -> InteractionRuntimeHealth:
        return InteractionRuntimeHealth(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            state=self._state,
            ready=self._ready,
            capabilities=self._capabilities,
            last_heartbeat_monotonic_s=self._last_heartbeat_monotonic_s,
            last_error=self._last_error,
        )

    async def activate(self, context: InteractionContext) -> None:
        if self._state != InteractionRuntimeState.READY or self._active_interaction_id is not None:
            raise InteractionRuntimeUnavailableError("activation requires READY state and no active interaction")
        self._active_interaction_id = context.interaction_id
        self._state = InteractionRuntimeState.ACTIVE
        try:
            await self._enqueue_command(
                WorkerCommandType.ACTIVATE,
                interaction_id=context.interaction_id,
                payload={"locale": context.locale, "timeout_s": context.timeout_s},
            )
        except Exception:
            self._active_interaction_id = None
            self._state = InteractionRuntimeState.READY
            raise

    async def pause(self) -> None:
        if self._state != InteractionRuntimeState.ACTIVE:
            raise InteractionRuntimeUnavailableError("pause requires ACTIVE state")
        interaction_id = self._require_active_interaction()
        self._state = InteractionRuntimeState.PAUSED
        try:
            await self._enqueue_command(WorkerCommandType.PAUSE, interaction_id=interaction_id, payload={})
        except Exception:
            self._state = InteractionRuntimeState.ACTIVE
            raise

    async def resume(self) -> None:
        if self._state != InteractionRuntimeState.PAUSED:
            raise InteractionRuntimeUnavailableError("resume requires PAUSED state")
        interaction_id = self._require_active_interaction()
        self._state = InteractionRuntimeState.ACTIVE
        try:
            await self._enqueue_command(WorkerCommandType.RESUME, interaction_id=interaction_id, payload={})
        except Exception:
            self._state = InteractionRuntimeState.PAUSED
            raise

    async def stop(self) -> None:
        if self._state not in (InteractionRuntimeState.ACTIVE, InteractionRuntimeState.PAUSED):
            raise InteractionRuntimeUnavailableError("stop requires ACTIVE or PAUSED state")
        interaction_id = self._require_active_interaction()
        await self._enqueue_command(WorkerCommandType.STOP, interaction_id=interaction_id, payload={})

    async def emergency_stop(self) -> None:
        if self._state == InteractionRuntimeState.CLOSED:
            return
        self._emergency_latched = True
        self._ready = False
        self._state = InteractionRuntimeState.EMERGENCY
        self._active_interaction_id = None
        queue = self._command_queue
        if queue is not None:
            while True:
                try:
                    discarded = queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break
                if discarded is not None:
                    # This envelope was queued but never written by
                    # _command_writer (it is being discarded here instead),
                    # so it must not remain in the pending-command ledger as
                    # an acknowledgement the worker will never send.
                    self._pending_commands.pop(discarded.message_id, None)
        try:
            await self._enqueue_command(
                WorkerCommandType.EMERGENCY_STOP,
                interaction_id=None,
                payload={},
                allow_when_emergency=True,
            )
        except InteractionRuntimeUnavailableError:
            pass

    async def next_event(self, *, timeout_s: float | None = None) -> WorkerEventEnvelope:
        if timeout_s is not None and (
            type(timeout_s) not in (int, float) or not math.isfinite(float(timeout_s)) or timeout_s <= 0
        ):
            raise ValueError("timeout_s must be positive and finite")
        if self._next_event_in_progress:
            raise InteractionRuntimeUnavailableError("exactly one next_event consumer is allowed")
        queue = self._event_queue
        if queue is None:
            raise InteractionRuntimeUnavailableError("worker not started")
        self._next_event_in_progress = True
        try:
            if not queue.empty():
                item = queue.get_nowait()
                if item is None:
                    raise InteractionRuntimeUnavailableError(
                        self._event_stream_terminal_error or "worker closed or failed"
                    )
                return item
            if self._event_stream_terminal.is_set():
                raise InteractionRuntimeUnavailableError(
                    self._event_stream_terminal_error or "worker closed or failed"
                )
            get_task = asyncio.ensure_future(queue.get())
            terminal_task = asyncio.ensure_future(self._event_stream_terminal.wait())
            try:
                if timeout_s is None:
                    done, pending = await asyncio.wait(
                        {get_task, terminal_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                else:
                    done, pending = await asyncio.wait(
                        {get_task, terminal_task},
                        timeout=float(timeout_s),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                if not done:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    raise asyncio.TimeoutError()
                if get_task in done:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    item = get_task.result()
                    if item is None:
                        raise InteractionRuntimeUnavailableError(
                            self._event_stream_terminal_error or "worker closed or failed"
                        )
                    return item
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if not queue.empty():
                    item = queue.get_nowait()
                    if item is None:
                        raise InteractionRuntimeUnavailableError(
                            self._event_stream_terminal_error or "worker closed or failed"
                        )
                    return item
                raise InteractionRuntimeUnavailableError(
                    self._event_stream_terminal_error or "worker closed or failed"
                )
            except asyncio.CancelledError:
                get_task.cancel()
                terminal_task.cancel()
                await asyncio.gather(get_task, terminal_task, return_exceptions=True)
                raise
        finally:
            self._next_event_in_progress = False

    async def close(self) -> None:
        if self._state == InteractionRuntimeState.CLOSED:
            return
        if self._close_task is not None and self._close_task.done():
            exc = self._close_task.exception()
            if isinstance(exc, InteractionRuntimeUnavailableError) and exc.code == ERR_TASK_SETTLEMENT_TIMEOUT:
                self._close_task = None

        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_impl(), name="interaction-jsonl-close")

        await asyncio.shield(self._close_task)

    async def _close_impl(self) -> None:
        self._closing = True
        self._ready = False
        # If a failure-path cleanup is already in flight, let it finish first
        # instead of racing two independent terminate()/kill() escalations
        # against the same child process.
        if self._cleanup_task is not None:
            cleanup_results = await asyncio.gather(self._cleanup_task, return_exceptions=True)
            for cleanup_result in cleanup_results:
                if (
                    isinstance(cleanup_result, InteractionRuntimeUnavailableError)
                    and cleanup_result.code == ERR_TASK_SETTLEMENT_TIMEOUT
                    and any(not task.done() for task in self._tasks)
                ):
                    raise cleanup_result
        if self._process is None:
            self._state = InteractionRuntimeState.CLOSED
            if self._termination is None:
                self._record_termination(
                    reason="GRACEFUL_CLOSE",
                    unexpected=False,
                    exit_code=None,
                )
            self._pending_commands.clear()
            await self._signal_event_queue_closed("worker closed")
            return
        # A primary failure reason already recorded before close() was
        # invoked (e.g. PROCESS_FAILED_EVENT, PROTOCOL_FAILURE,
        # HEARTBEAT_TIMEOUT, COMMAND_ACK_BACKPRESSURE) must never be
        # overwritten by the mechanical CLOSE_TERMINATE/CLOSE_KILL escalation
        # below. CLOSE_TERMINATE/CLOSE_KILL only apply when close() itself is
        # the one establishing the termination from a non-failed state.
        had_primary_failure_reason = _is_real_primary_termination(self._termination)
        escalation: str | None = None
        try:
            if self._process.returncode is None and not self._emergency_latched and not had_primary_failure_reason:
                try:
                    await self._enqueue_command(WorkerCommandType.CLOSE, interaction_id=None, payload={}, allow_when_closing=True)
                    if self._closed_event is not None:
                        await asyncio.wait_for(self._closed_event.wait(), timeout=self._config.shutdown_timeout_s)
                except Exception:
                    pass
            if self._process.stdin is not None and not self._process.stdin.is_closing():
                self._process.stdin.close()
                try:
                    await self._process.stdin.wait_closed()
                except Exception:
                    pass
            if self._process.returncode is None:
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=self._config.shutdown_timeout_s)
                except asyncio.TimeoutError:
                    escalation = "CLOSE_TERMINATE"
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=self._config.terminate_timeout_s)
                    except asyncio.TimeoutError:
                        escalation = "CLOSE_KILL"
                        self._process.kill()
                        await self._process.wait()
        finally:
            final_exit_code = self._process.returncode if self._process is not None else None
            if had_primary_failure_reason:
                # Only backfill exit_code/protocol_error_code; the primary
                # reason and its unexpected/protocol_error_code metadata are
                # preserved verbatim, regardless of whether close() also had
                # to terminate/kill the child afterwards.
                if self._termination is not None and self._termination.exit_code is None:
                    self._record_termination(
                        reason=self._termination.reason,
                        unexpected=self._termination.unexpected,
                        exit_code=final_exit_code,
                        protocol_error_code=self._termination.protocol_error_code,
                    )
            elif escalation is not None:
                reason_to_record = "EMERGENCY_STOP" if self._emergency_latched else escalation
                self._record_termination(reason=reason_to_record, unexpected=False, exit_code=final_exit_code)
            elif self._termination is None:
                reason = "EMERGENCY_STOP" if self._emergency_latched else "GRACEFUL_CLOSE"
                self._record_termination(reason=reason, unexpected=False, exit_code=final_exit_code)
            elif self._termination.exit_code is None:
                self._record_termination(
                    reason=self._termination.reason,
                    unexpected=self._termination.unexpected,
                    exit_code=final_exit_code,
                    protocol_error_code=self._termination.protocol_error_code,
                )
            self._pending_commands.clear()
            task_settlement = await self._cancel_tasks()
            await self._signal_event_queue_closed("worker closed")
            await self._let_event_loop_close_subprocess_transports()
            if task_settlement.timed_out:
                self._raise_task_settlement_timeout(task_settlement)
            self._state = InteractionRuntimeState.CLOSED

    async def _let_event_loop_close_subprocess_transports(self) -> None:
        """Idempotent, centralized hook for deterministic subprocess
        transport finalization once the child process is known to have
        exited. On CPython/Windows this applies a documented compatibility
        workaround (see _close_subprocess_transport_windows_workaround);
        every other platform/runtime simply relies on asyncio's normal
        public transport lifecycle and does nothing extra here."""
        if self._process is None or self._process.returncode is None:
            return
        if self._is_cpython_windows_subprocess_workaround_applicable():
            self._close_subprocess_transport_windows_workaround()
            await asyncio.sleep(0.01)

    @staticmethod
    def _is_cpython_windows_subprocess_workaround_applicable() -> bool:
        return sys.platform == "win32" and platform.python_implementation() == "CPython"

    def _close_subprocess_transport_windows_workaround(self) -> None:
        """On Windows' ProactorEventLoop (CPython 3.10), asyncio.subprocess
        transports schedule their connection_lost callback via call_soon
        once the underlying process has exited; that callback is what
        actually drops the last strong reference to the pipe transport. If
        the test's event loop closes before that callback runs, the
        transport's __del__ fires later (during GC, possibly after the loop
        is closed) and raises an unraisable RuntimeError/ResourceWarning.

        This is a documented, version/platform-scoped compatibility
        workaround, not a general-purpose lifecycle step: it deliberately
        reaches into the private `_transport` attribute of
        asyncio.subprocess.Process (CPython implementation detail, not part
        of the public API) to close the underlying pipe transport
        explicitly and deterministically, instead of depending on
        GC timing. It must stay centralized here and gated to
        CPython+Windows so it is never reached on platforms/runtimes where
        it is unnecessary or where `_transport` may not exist at all."""
        if self._process is None:
            return
        transport = getattr(self._process, "_transport", None)
        if transport is None:
            return
        try:
            transport.close()
        except Exception:
            pass

    def _require_active_interaction(self) -> str:
        if self._active_interaction_id is None:
            raise InteractionRuntimeUnavailableError("command requires active interaction")
        return self._active_interaction_id

    def _spawn_task(self, coro: object, name: str) -> None:
        task = asyncio.create_task(coro, name=name)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _enqueue_command(
        self,
        command: WorkerCommandType,
        *,
        interaction_id: str | None,
        payload: dict[str, object],
        allow_when_closing: bool = False,
        allow_when_emergency: bool = False,
    ) -> None:
        if self._closing and not allow_when_closing:
            raise InteractionRuntimeUnavailableError("worker is closing", code=ERR_CLOSING)
        if self._emergency_latched and not allow_when_emergency:
            raise InteractionRuntimeUnavailableError("worker is in emergency", code=ERR_EMERGENCY)
        if self._state in (InteractionRuntimeState.FAILED, InteractionRuntimeState.CLOSED):
            # A terminal state must fail closed immediately: continuing to
            # enqueue commands here would keep refilling _command_queue
            # after _command_writer has already been cancelled by the
            # failure-path cleanup, making that cancellation never able to
            # observe an empty/quiescent queue.
            raise InteractionRuntimeUnavailableError(
                "worker is in a terminal state", code=ERR_TERMINAL_STATE
            )
        queue = self._command_queue
        if queue is None:
            raise InteractionRuntimeUnavailableError("worker not started")
        # The limit check, sequence assignment, queue enqueue, and ledger
        # registration are a single atomic unit under _command_lock: a
        # rejected command must not consume a sequence number, and two
        # concurrent callers racing to fill the last ledger slot must not
        # both succeed.
        async with self._command_lock:
            if self._closing and not allow_when_closing:
                raise InteractionRuntimeUnavailableError("worker is closing", code=ERR_CLOSING)
            if self._emergency_latched and not allow_when_emergency:
                raise InteractionRuntimeUnavailableError("worker is in emergency", code=ERR_EMERGENCY)
            if (
                allow_when_emergency
                and self._emergency_latched
                and command is not WorkerCommandType.EMERGENCY_STOP
            ):
                raise InteractionRuntimeUnavailableError("worker is in emergency", code=ERR_EMERGENCY)
            if self._state in (InteractionRuntimeState.FAILED, InteractionRuntimeState.CLOSED):
                raise InteractionRuntimeUnavailableError(
                    "worker is in a terminal state", code=ERR_TERMINAL_STATE
                )
            if len(self._pending_commands) >= self._config.max_pending_commands:
                await self._fail(
                    "pending command ledger limit exceeded; worker is withholding acknowledgements",
                    unexpected=True,
                    protocol_error_code=ERR_PENDING_COMMAND_LIMIT,
                    termination_reason="COMMAND_ACK_BACKPRESSURE",
                )
                raise InteractionRuntimeUnavailableError(
                    "pending command ledger limit exceeded", code=ERR_PENDING_COMMAND_LIMIT
                )
            sequence = self._outgoing_sequence
            envelope = WorkerCommandEnvelope(
                protocol_version=INTERACTION_PROTOCOL_VERSION,
                message_id=f"py:{sequence}",
                interaction_id=interaction_id,
                command=command,
                sequence=sequence,
                emitted_at_monotonic_s=time.monotonic(),
                payload=payload,
            )
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull as exc:
                raise InteractionRuntimeUnavailableError("command queue full", code=ERR_QUEUE_FULL) from exc
            self._outgoing_sequence = sequence + 1
            self._pending_commands[envelope.message_id] = (command, interaction_id)

    async def _command_writer(self) -> None:
        assert self._process is not None
        assert self._command_queue is not None
        writer = self._process.stdin
        if writer is None:
            await self._fail("stdin unavailable", unexpected=True, termination_reason="WRITE_FAILURE")
            return
        while True:
            envelope = await self._command_queue.get()
            if envelope is None:
                break
            line = json.dumps(
                envelope.to_wire_dict(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            try:
                writer.write(line)
                await asyncio.wait_for(writer.drain(), timeout=self._config.write_timeout_s)
            except Exception:
                await self._fail("write failed", unexpected=True, termination_reason="WRITE_FAILURE")
                break

    async def _stdout_reader(self) -> None:
        assert self._process is not None
        reader = self._process.stdout
        if reader is None:
            await self._fail("stdout unavailable", unexpected=True, termination_reason="PROTOCOL_FAILURE")
            return
        while True:
            try:
                raw_line = await reader.readuntil(b"\n")
            except asyncio.IncompleteReadError as exc:
                if exc.partial:
                    await self._fail(
                        "frame missing trailing newline",
                        unexpected=True,
                        protocol_error_code=ERR_FRAMING,
                        termination_reason="PROTOCOL_FAILURE",
                    )
                    return
                if not self._closing and self._state not in (
                    InteractionRuntimeState.CLOSED,
                    InteractionRuntimeState.FAILED,
                    InteractionRuntimeState.EMERGENCY,
                ):
                    await self._fail("unexpected EOF", unexpected=True, termination_reason="UNEXPECTED_EXIT")
                elif self._state is InteractionRuntimeState.EMERGENCY:
                    self._record_termination(
                        reason="EMERGENCY_STOP",
                        unexpected=False,
                        exit_code=self._process.returncode if self._process is not None else None,
                    )
                return
            except asyncio.LimitOverrunError:
                await self._fail(
                    "line too large",
                    unexpected=True,
                    protocol_error_code=ERR_LINE_TOO_LARGE,
                    termination_reason="PROTOCOL_FAILURE",
                )
                return
            except ValueError:
                await self._fail(
                    "line too large",
                    unexpected=True,
                    protocol_error_code=ERR_LINE_TOO_LARGE,
                    termination_reason="PROTOCOL_FAILURE",
                )
                return
            if len(raw_line) > self._config.max_line_bytes:
                await self._fail(
                    "line too large",
                    unexpected=True,
                    protocol_error_code=ERR_LINE_TOO_LARGE,
                    termination_reason="PROTOCOL_FAILURE",
                )
                return
            try:
                text = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                await self._fail(
                    "invalid utf-8",
                    unexpected=True,
                    protocol_error_code=ERR_UTF8,
                    termination_reason="PROTOCOL_FAILURE",
                )
                return
            text = text.rstrip("\r\n")
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                await self._fail(
                    "invalid json",
                    unexpected=True,
                    protocol_error_code=ERR_JSON,
                    termination_reason="PROTOCOL_FAILURE",
                )
                return
            if not isinstance(raw, dict):
                await self._fail(
                    "json top-level must be object",
                    unexpected=True,
                    protocol_error_code=ERR_TYPE,
                    termination_reason="PROTOCOL_FAILURE",
                )
                return
            try:
                event = WorkerEventEnvelope.from_wire_dict(raw)
                should_publish = self._process_event(event)
            except InteractionRuntimeProtocolError as exc:
                await self._fail(str(exc), unexpected=True, protocol_error_code=exc.code, termination_reason="PROTOCOL_FAILURE")
                return
            is_process_failed_event = (
                event.event == WorkerEventType.FAILED and event.interaction_id is None
            )
            if should_publish:
                await self._publish_event(event)
            if is_process_failed_event and not self._emergency_latched:
                code = event.payload.get("code")
                message = event.payload.get("message")
                await self._fail(
                    f"{code}: {message}",
                    unexpected=True,
                    termination_reason="PROCESS_FAILED_EVENT",
                )
                return
            if self._state is InteractionRuntimeState.FAILED:
                return

    def _process_event(self, event: WorkerEventEnvelope) -> bool:
        if event.message_id in self._seen_message_ids:
            raise InteractionRuntimeProtocolError(ERR_DUPLICATE_MESSAGE_ID, "duplicate message_id")
        if len(self._seen_message_ids) >= self._config.max_seen_message_ids:
            raise InteractionRuntimeProtocolError(ERR_MESSAGE_LIMIT, "seen message_id limit exceeded")
        self._seen_message_ids.add(event.message_id)
        if event.sequence != self._incoming_sequence:
            raise InteractionRuntimeProtocolError(ERR_SEQUENCE, "incoming event sequence mismatch")
        self._incoming_sequence += 1
        # COMMAND_ACCEPTED is correlated against the interaction_id recorded
        # in the pending-command ledger at enqueue time, not against
        # _active_interaction_id -- a PAUSE/RESUME/STOP accepted while
        # _active_interaction_id is still populated is legitimate. Letting
        # the generic stale-interaction check run first would preempt that
        # correlation with the wrong error code, so it is skipped here and
        # COMMAND_ACCEPTED does its own interaction_id comparison below.
        if (
            event.event is not WorkerEventType.COMMAND_ACCEPTED
            and event.interaction_id is not None
            and event.interaction_id != self._active_interaction_id
        ):
            raise InteractionRuntimeProtocolError(ERR_STALE_INTERACTION, "stale interaction_id")
        if event.event == WorkerEventType.READY:
            if not (
                self._state == InteractionRuntimeState.STARTING
                and self._ready is False
                and self._active_interaction_id is None
                and not self._emergency_latched
                and not self._closing
            ):
                raise InteractionRuntimeProtocolError(ERR_STATE, "ready event received outside STARTING")
            self._last_heartbeat_monotonic_s = time.monotonic()
            self._capabilities = InteractionRuntimeCapabilities.from_payload(event.payload)
            self._state = InteractionRuntimeState.READY
            self._ready = True
            if self._ready_event is not None:
                self._ready_event.set()
        elif event.event == WorkerEventType.HEARTBEAT:
            self._last_heartbeat_monotonic_s = time.monotonic()
        elif event.event == WorkerEventType.COMMAND_ACCEPTED:
            payload_message_id = event.payload.get("message_id")
            payload_command = event.payload.get("command")
            pending = self._pending_commands.get(payload_message_id)  # type: ignore[arg-type]
            if pending is None:
                raise InteractionRuntimeProtocolError(
                    ERR_CORRELATION, "command_accepted references unknown message_id"
                )
            expected_command, expected_interaction_id = pending
            if payload_command != expected_command.value:
                raise InteractionRuntimeProtocolError(ERR_CORRELATION, "command_accepted command mismatch")
            if event.interaction_id != expected_interaction_id:
                raise InteractionRuntimeProtocolError(ERR_CORRELATION, "command_accepted interaction_id mismatch")
            del self._pending_commands[payload_message_id]  # type: ignore[arg-type]
        elif event.event == WorkerEventType.PLAYBACK_COMPLETED:
            self._active_interaction_id = None
            if not self._emergency_latched:
                self._state = InteractionRuntimeState.READY
                self._ready = True
        elif event.event in (WorkerEventType.INTERACTION_TIMEOUT, WorkerEventType.CANCELLED):
            self._active_interaction_id = None
            if not self._emergency_latched:
                self._state = InteractionRuntimeState.READY
        elif event.event == WorkerEventType.FAILED:
            if event.interaction_id is not None:
                self._active_interaction_id = None
                if not self._emergency_latched:
                    self._state = InteractionRuntimeState.READY
                    self._ready = True
                else:
                    self._state = InteractionRuntimeState.EMERGENCY
            else:
                if not self._emergency_latched:
                    # Process-level FAILED: leave state mutation and child
                    # termination to _stdout_reader, which calls _fail(...)
                    # AFTER this event has been published, so the consumer can
                    # still drain it via next_event() before the stream closes.
                    return True
        elif event.event == WorkerEventType.CLOSED:
            if self._closed_event is not None:
                self._closed_event.set()
        elif event.event == WorkerEventType.STOPPED and self._emergency_latched:
            self._state = InteractionRuntimeState.EMERGENCY
            self._ready = False
        return True

    async def _publish_event(self, event: WorkerEventEnvelope) -> None:
        assert self._event_queue is not None
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            await self._fail("event queue full", unexpected=True, termination_reason="EVENT_QUEUE_OVERFLOW")
            if self._process is not None and self._process.returncode is None:
                try:
                    self._process.terminate()
                except ProcessLookupError:
                    pass

    async def _stderr_drain(self) -> None:
        assert self._process is not None
        reader = self._process.stderr
        if reader is None:
            return
        self._stderr_partial_tail = b""
        while True:
            try:
                chunk = await reader.read(_STDOUT_READ_CHUNK_BYTES)
            except Exception:
                return
            if chunk == b"":
                if self._stderr_partial_tail:
                    self._append_stderr_line(self._stderr_partial_tail.decode("utf-8", errors="replace"))
                    self._stderr_partial_tail = b""
                return
            buffer = self._stderr_partial_tail + chunk
            while b"\n" in buffer:
                line_bytes, buffer = buffer.split(b"\n", 1)
                self._append_stderr_line(line_bytes.decode("utf-8", errors="replace").rstrip("\r"))
            max_tail_bytes = self._config.stderr_tail_max_chars
            if len(buffer) > max_tail_bytes:
                buffer = buffer[-max_tail_bytes:]
            self._stderr_partial_tail = buffer

    def _append_stderr_line(self, line: str) -> None:
        self._stderr_tail.append(line)
        self._stderr_chars += len(line)
        while len(self._stderr_tail) > self._config.stderr_tail_lines:
            removed = self._stderr_tail.popleft()
            self._stderr_chars -= len(removed)
        while self._stderr_chars > self._config.stderr_tail_max_chars and self._stderr_tail:
            removed = self._stderr_tail.popleft()
            self._stderr_chars -= len(removed)

    async def _process_watcher(self) -> None:
        assert self._process is not None
        exit_code = await self._process.wait()
        if self._emergency_latched:
            self._record_termination(
                reason="EMERGENCY_STOP",
                unexpected=False,
                exit_code=exit_code,
            )
            return
        if not self._closing and self._state not in (InteractionRuntimeState.CLOSED, InteractionRuntimeState.FAILED):
            await self._fail(
                f"worker exited with {exit_code}",
                unexpected=True,
                exit_code=exit_code,
                termination_reason="UNEXPECTED_EXIT",
            )
            return
        if self._termination is not None and self._termination.exit_code is None:
            self._record_termination(
                reason=self._termination.reason,
                unexpected=self._termination.unexpected,
                exit_code=exit_code,
                protocol_error_code=self._termination.protocol_error_code,
            )

    async def _heartbeat_monitor(self) -> None:
        interval = min(max(self._config.heartbeat_timeout_s / 4.0, 0.01), 0.1)
        while True:
            await asyncio.sleep(interval)
            if self._state in (
                InteractionRuntimeState.NOT_STARTED,
                InteractionRuntimeState.STARTING,
                InteractionRuntimeState.CLOSED,
                InteractionRuntimeState.FAILED,
                InteractionRuntimeState.EMERGENCY,
            ):
                if self._state in (
                    InteractionRuntimeState.CLOSED,
                    InteractionRuntimeState.FAILED,
                    InteractionRuntimeState.EMERGENCY,
                ):
                    return
                continue
            if self._closing:
                return
            if self._last_heartbeat_monotonic_s is None:
                continue
            if time.monotonic() - self._last_heartbeat_monotonic_s > self._config.heartbeat_timeout_s:
                await self._fail("heartbeat timeout", unexpected=True, termination_reason="HEARTBEAT_TIMEOUT")
                return

    async def _fail(
        self,
        reason: str,
        *,
        unexpected: bool,
        protocol_error_code: str | None = None,
        exit_code: int | None = None,
        termination_reason: str = "PROTOCOL_FAILURE",
    ) -> None:
        if self._emergency_latched:
            return
        if self._state in (InteractionRuntimeState.FAILED, InteractionRuntimeState.CLOSED):
            return
        self._state = InteractionRuntimeState.FAILED
        self._ready = False
        self._active_interaction_id = None
        self._last_error = reason
        if self._process is not None and exit_code is None:
            exit_code = self._process.returncode
        self._record_termination(
            reason=termination_reason,
            unexpected=unexpected,
            exit_code=exit_code,
            protocol_error_code=protocol_error_code,
            error_message=reason,
        )
        self._pending_commands.clear()
        if self._ready_event is not None:
            self._ready_event.set()
        await self._signal_event_queue_closed(reason)
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
        self._schedule_cleanup_task()

    def _schedule_cleanup_task(self) -> None:
        # Best-effort self-clean so a caller of start() that never invokes
        # close() does not leak a running child process or owned tasks. This
        # is an explicitly owned task (referenced via self._cleanup_task,
        # named, and not added to self._tasks) because _fail() itself may be
        # running inside one of those owned tasks (e.g. _stdout_reader,
        # _heartbeat_monitor) -- cancelling the current task from within
        # itself would abort this cleanup before it finishes. Only one
        # cleanup task may be active at a time: concurrent/repeated calls to
        # _fail() (from _fail() itself returning early once FAILED, from
        # close(), and from _process_watcher()) must converge on the same
        # cleanup rather than racing multiple independent ones.
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(
            self._self_clean_after_failure(), name="interaction-jsonl-failure-cleanup"
        )

    async def _self_clean_after_failure(self) -> None:
        try:
            if self._process is not None and self._process.returncode is None:
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=self._config.terminate_timeout_s)
                except asyncio.TimeoutError:
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=self._config.terminate_timeout_s)
                    except asyncio.TimeoutError:
                        pass
            task_settlement = await self._cancel_tasks()
            await self._let_event_loop_close_subprocess_transports()
            if task_settlement.timed_out:
                self._raise_task_settlement_timeout(task_settlement)
        except asyncio.CancelledError:
            raise
        except InteractionRuntimeUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - recovered and recorded, never left unretrieved
            self._last_error = f"failure cleanup raised: {exc!r}"

    def _record_termination(
        self,
        *,
        reason: str,
        unexpected: bool,
        exit_code: int | None,
        protocol_error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        existing = self._termination
        preserved_code = protocol_error_code
        if preserved_code is None and existing is not None:
            preserved_code = existing.protocol_error_code
        resolved_exit_code = exit_code
        if resolved_exit_code is None and existing is not None:
            resolved_exit_code = existing.exit_code
        # `reason` is always a stable category (e.g. "GRACEFUL_CLOSE",
        # "PROTOCOL_FAILURE", "UNEXPECTED_EXIT"). When a caller only intends
        # to refill exit_code/protocol_error_code on an existing termination,
        # it re-passes the existing category instead of inventing a new one,
        # so this never overwrites a more specific category with a generic
        # one. The human-readable message goes to self._last_error, never
        # into WorkerTermination.reason.
        if error_message is not None:
            self._last_error = error_message
        self._termination = WorkerTermination(
            exit_code=resolved_exit_code,
            reason=reason,
            unexpected=unexpected,
            occurred_at_monotonic_s=time.monotonic(),
            protocol_error_code=preserved_code,
            stderr_tail=tuple(self._stderr_tail),
        )

    async def _signal_event_queue_closed(self, error: str) -> None:
        self._event_stream_terminal_error = error
        self._event_stream_terminal.set()
        queue = self._event_queue
        if queue is None:
            return
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def _raise_task_settlement_timeout(self, settlement: OwnedTaskSettlement) -> None:
        pending = ", ".join(settlement.pending_task_names)
        message = f"owned task settlement timed out; pending tasks: {pending}"
        self._last_error = message
        if not _is_real_primary_termination(self._termination):
            self._record_termination(
                reason=TASK_SETTLEMENT_TIMEOUT,
                unexpected=True,
                exit_code=self._process.returncode if self._process is not None else None,
                protocol_error_code=ERR_TASK_SETTLEMENT_TIMEOUT,
                error_message=message,
            )
        elif self._termination.protocol_error_code is None:
            self._record_termination(
                reason=self._termination.reason,
                unexpected=self._termination.unexpected,
                exit_code=self._termination.exit_code,
                protocol_error_code=ERR_TASK_SETTLEMENT_TIMEOUT,
                error_message=message,
            )
        raise InteractionRuntimeUnavailableError(message, code=ERR_TASK_SETTLEMENT_TIMEOUT)

    async def _cancel_tasks(self) -> OwnedTaskSettlement:
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if not tasks:
            return OwnedTaskSettlement((), (), (), False)
        deadline = asyncio.get_running_loop().time() + self._owned_task_cancel_timeout_s
        pending = {task for task in tasks if not task.done()}
        settled_names: set[str] = set()
        cancelled_names: set[str] = set()
        while pending and asyncio.get_running_loop().time() < deadline:
            done, pending = await asyncio.wait(pending, timeout=0.05)
            for task in done:
                settled_names.add(task.get_name())
                if task.cancelled():
                    cancelled_names.add(task.get_name())
                    continue
                exc = task.exception()
                if exc is not None:
                    # Recovered, never left as an unretrieved task exception.
                    self._last_error = f"owned task {task.get_name()} raised during cancellation: {exc!r}"
        for task in tasks:
            if task.done() and task.get_name() not in settled_names:
                settled_names.add(task.get_name())
                if task.cancelled():
                    cancelled_names.add(task.get_name())
                else:
                    exc = task.exception()
                    if exc is not None:
                        self._last_error = f"owned task {task.get_name()} raised during cancellation: {exc!r}"
        pending_names = tuple(sorted(task.get_name() for task in pending if not task.done()))
        for task in pending:
            # A task that still refuses to settle within the deadline is a
            # bug elsewhere (e.g. an await point that swallows
            # CancelledError), not something close()/the failure-path
            # cleanup should block on indefinitely; record it instead of
            # hanging forever.
            self._last_error = f"owned task {task.get_name()} did not settle after cancellation"
        return OwnedTaskSettlement(
            settled_task_names=tuple(sorted(settled_names)),
            cancelled_task_names=tuple(sorted(cancelled_names)),
            pending_task_names=pending_names,
            timed_out=bool(pending_names),
        )


__all__ = [
    "JsonlInteractionWorkerSupervisor",
    "JsonlWorkerSupervisorConfig",
    "OwnedTaskSettlement",
]
