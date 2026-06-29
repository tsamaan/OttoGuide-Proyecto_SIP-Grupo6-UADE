"""Supervised JSONL interaction worker runtime.

The supervisor is stdlib-only and owns one child process that speaks the
versioned interaction protocol over stdin/stdout JSONL. stdout is protocol
only; stderr is drained as logs.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque

from src.interaction.runtime_port import (
    ERR_DUPLICATE_MESSAGE_ID,
    ERR_FRAMING,
    ERR_JSON,
    ERR_LINE_TOO_LARGE,
    ERR_MESSAGE_LIMIT,
    ERR_SEQUENCE,
    ERR_STALE_INTERACTION,
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
        self._command_lock = asyncio.Lock()
        self._event_stream_terminal = asyncio.Event()
        self._event_stream_terminal_error: str | None = None

    @property
    def termination(self) -> WorkerTermination | None:
        return self._termination

    @property
    def active_interaction_id(self) -> str | None:
        return self._active_interaction_id

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
            self._process = await asyncio.create_subprocess_exec(
                *self._config.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self._config.max_line_bytes + 1024,
            )
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
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break
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
        self._closing = True
        self._ready = False
        if self._process is None:
            self._state = InteractionRuntimeState.CLOSED
            self._record_termination(
                reason="GRACEFUL_CLOSE",
                unexpected=False,
                exit_code=None,
            )
            await self._signal_event_queue_closed("worker closed")
            return
        escalation: str | None = None
        try:
            if self._process.returncode is None and not self._emergency_latched:
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
            self._state = InteractionRuntimeState.CLOSED
            final_exit_code = self._process.returncode if self._process is not None else None
            if escalation is not None:
                self._record_termination(reason=escalation, unexpected=False, exit_code=final_exit_code)
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
            await self._cancel_tasks()
            await self._signal_event_queue_closed("worker closed")

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
            raise InteractionRuntimeUnavailableError("worker is closing")
        if self._emergency_latched and not allow_when_emergency:
            raise InteractionRuntimeUnavailableError("worker is in emergency")
        queue = self._command_queue
        if queue is None:
            raise InteractionRuntimeUnavailableError("worker not started")
        async with self._command_lock:
            sequence = self._outgoing_sequence
            self._outgoing_sequence += 1
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
            raise InteractionRuntimeUnavailableError("command queue full", code="ERR_QUEUE_FULL") from exc

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
            if should_publish:
                await self._publish_event(event)
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
        if event.interaction_id is not None and event.interaction_id != self._active_interaction_id:
            raise InteractionRuntimeProtocolError(ERR_STALE_INTERACTION, "stale interaction_id")
        if event.event in (WorkerEventType.READY, WorkerEventType.HEARTBEAT):
            self._last_heartbeat_monotonic_s = time.monotonic()
        if event.event == WorkerEventType.READY:
            if self._emergency_latched:
                return True
            self._capabilities = InteractionRuntimeCapabilities.from_payload(event.payload)
            self._state = InteractionRuntimeState.READY
            self._ready = True
            if self._ready_event is not None:
                self._ready_event.set()
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
                    code = event.payload.get("code")
                    message = event.payload.get("message")
                    self._state = InteractionRuntimeState.FAILED
                    self._ready = False
                    self._active_interaction_id = None
                    self._last_error = f"{code}: {message}"
                    self._record_termination(
                        reason="PROCESS_FAILED_EVENT",
                        unexpected=True,
                        exit_code=None,
                    )
                    if self._ready_event is not None:
                        self._ready_event.set()
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
            await self._fail("event queue full", unexpected=True, termination_reason="PROTOCOL_FAILURE")
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
        buffer = b""
        while True:
            try:
                chunk = await reader.read(_STDOUT_READ_CHUNK_BYTES)
            except Exception:
                return
            if chunk == b"":
                if buffer:
                    self._append_stderr_line(buffer.decode("utf-8", errors="replace"))
                return
            buffer += chunk
            while b"\n" in buffer:
                line_bytes, buffer = buffer.split(b"\n", 1)
                self._append_stderr_line(line_bytes.decode("utf-8", errors="replace").rstrip("\r"))

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
        if self._ready_event is not None:
            self._ready_event.set()
        await self._signal_event_queue_closed(reason)
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

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
        message = error_message if error_message is not None else (existing.reason if existing is not None else reason)
        self._termination = WorkerTermination(
            exit_code=resolved_exit_code,
            reason=message,
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

    async def _cancel_tasks(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


__all__ = [
    "JsonlInteractionWorkerSupervisor",
    "JsonlWorkerSupervisorConfig",
]
