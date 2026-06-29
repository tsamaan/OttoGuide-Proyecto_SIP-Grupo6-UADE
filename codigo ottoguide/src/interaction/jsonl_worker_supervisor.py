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
    ERR_JSON,
    ERR_LINE_TOO_LARGE,
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
        self._stderr_tail: Deque[str] = deque(maxlen=config.stderr_tail_lines)
        self._stderr_chars = 0
        self._command_lock = asyncio.Lock()

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
            if self._state != InteractionRuntimeState.READY:
                await self._fail("startup failed", unexpected=True)
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
        interaction_id = self._require_active_interaction()
        self._state = InteractionRuntimeState.PAUSED
        await self._enqueue_command(WorkerCommandType.PAUSE, interaction_id=interaction_id, payload={})

    async def resume(self) -> None:
        interaction_id = self._require_active_interaction()
        self._state = InteractionRuntimeState.ACTIVE
        await self._enqueue_command(WorkerCommandType.RESUME, interaction_id=interaction_id, payload={})

    async def stop(self) -> None:
        interaction_id = self._require_active_interaction()
        await self._enqueue_command(WorkerCommandType.STOP, interaction_id=interaction_id, payload={})

    async def emergency_stop(self) -> None:
        self._emergency_latched = True
        self._ready = False
        self._state = InteractionRuntimeState.EMERGENCY
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
            if timeout_s is None:
                item = await queue.get()
            else:
                item = await asyncio.wait_for(queue.get(), timeout=float(timeout_s))
            if item is None:
                raise InteractionRuntimeUnavailableError("worker closed or failed")
            return item
        finally:
            self._next_event_in_progress = False

    async def close(self) -> None:
        if self._state == InteractionRuntimeState.CLOSED:
            return
        self._closing = True
        self._ready = False
        if self._process is None:
            self._state = InteractionRuntimeState.CLOSED
            await self._signal_event_queue_closed()
            return
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
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=self._config.terminate_timeout_s)
                    except asyncio.TimeoutError:
                        self._process.kill()
                        await self._process.wait()
        finally:
            self._state = InteractionRuntimeState.CLOSED
            await self._cancel_tasks()
            await self._signal_event_queue_closed()

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
            await self._fail("stdin unavailable", unexpected=True)
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
                await self._fail("write failed", unexpected=True)
                break

    async def _stdout_reader(self) -> None:
        assert self._process is not None
        reader = self._process.stdout
        if reader is None:
            await self._fail("stdout unavailable", unexpected=True)
            return
        while True:
            try:
                raw_line = await reader.readline()
            except ValueError:
                await self._fail("line too large", unexpected=True, protocol_error_code=ERR_LINE_TOO_LARGE)
                return
            if raw_line == b"":
                if not self._closing and self._state not in (InteractionRuntimeState.CLOSED, InteractionRuntimeState.FAILED):
                    await self._fail("unexpected EOF", unexpected=True)
                return
            if len(raw_line) > self._config.max_line_bytes:
                await self._fail("line too large", unexpected=True, protocol_error_code=ERR_LINE_TOO_LARGE)
                return
            try:
                text = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                await self._fail("invalid utf-8", unexpected=True, protocol_error_code=ERR_UTF8)
                return
            text = text.rstrip("\r\n")
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                await self._fail("invalid json", unexpected=True, protocol_error_code=ERR_JSON)
                return
            if not isinstance(raw, dict):
                await self._fail("json top-level must be object", unexpected=True, protocol_error_code=ERR_TYPE)
                return
            try:
                event = WorkerEventEnvelope.from_wire_dict(raw)
                self._process_event(event)
            except InteractionRuntimeProtocolError as exc:
                await self._fail(str(exc), unexpected=True, protocol_error_code=exc.code)
                return
            await self._publish_event(event)

    def _process_event(self, event: WorkerEventEnvelope) -> None:
        if event.message_id in self._seen_message_ids:
            raise InteractionRuntimeProtocolError(ERR_DUPLICATE_MESSAGE_ID, "duplicate message_id")
        self._seen_message_ids.add(event.message_id)
        if event.sequence != self._incoming_sequence:
            raise InteractionRuntimeProtocolError(ERR_SEQUENCE, "incoming event sequence mismatch")
        self._incoming_sequence += 1
        if event.interaction_id is not None and event.interaction_id != self._active_interaction_id:
            raise InteractionRuntimeProtocolError(ERR_STALE_INTERACTION, "stale interaction_id")
        if event.event in (WorkerEventType.READY, WorkerEventType.HEARTBEAT):
            self._last_heartbeat_monotonic_s = time.monotonic()
        if event.event == WorkerEventType.READY:
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
        elif event.event == WorkerEventType.FAILED and event.interaction_id is not None:
            self._active_interaction_id = None
            self._state = InteractionRuntimeState.READY if not self._emergency_latched else InteractionRuntimeState.EMERGENCY
        elif event.event == WorkerEventType.CLOSED:
            if self._closed_event is not None:
                self._closed_event.set()
        elif event.event == WorkerEventType.STOPPED and self._emergency_latched:
            self._state = InteractionRuntimeState.EMERGENCY
            self._ready = False

    async def _publish_event(self, event: WorkerEventEnvelope) -> None:
        assert self._event_queue is not None
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            await self._fail("event queue full", unexpected=True)

    async def _stderr_drain(self) -> None:
        assert self._process is not None
        reader = self._process.stderr
        if reader is None:
            return
        while True:
            raw_line = await reader.readline()
            if raw_line == b"":
                return
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            self._stderr_tail.append(line)
            self._stderr_chars += len(line)
            while self._stderr_chars > self._config.stderr_tail_max_chars and self._stderr_tail:
                removed = self._stderr_tail.popleft()
                self._stderr_chars -= len(removed)

    async def _process_watcher(self) -> None:
        assert self._process is not None
        exit_code = await self._process.wait()
        if not self._closing and self._state not in (InteractionRuntimeState.CLOSED, InteractionRuntimeState.FAILED):
            await self._fail(f"worker exited with {exit_code}", unexpected=True, exit_code=exit_code)

    async def _heartbeat_monitor(self) -> None:
        interval = min(max(self._config.heartbeat_timeout_s / 4.0, 0.01), 0.1)
        while True:
            await asyncio.sleep(interval)
            if self._closing or self._state in (InteractionRuntimeState.NOT_STARTED, InteractionRuntimeState.STARTING, InteractionRuntimeState.CLOSED, InteractionRuntimeState.FAILED):
                continue
            if self._last_heartbeat_monotonic_s is None:
                continue
            if time.monotonic() - self._last_heartbeat_monotonic_s > self._config.heartbeat_timeout_s:
                await self._fail("heartbeat timeout", unexpected=True)
                return

    async def _fail(
        self,
        reason: str,
        *,
        unexpected: bool,
        protocol_error_code: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        if self._state in (InteractionRuntimeState.FAILED, InteractionRuntimeState.CLOSED):
            return
        self._state = InteractionRuntimeState.FAILED
        self._ready = False
        self._last_error = reason
        if self._process is not None and exit_code is None:
            exit_code = self._process.returncode
        self._termination = WorkerTermination(
            exit_code=exit_code,
            reason=reason,
            unexpected=unexpected,
            occurred_at_monotonic_s=time.monotonic(),
            protocol_error_code=protocol_error_code,
            stderr_tail=tuple(self._stderr_tail),
        )
        if self._ready_event is not None:
            self._ready_event.set()
        await self._signal_event_queue_closed()
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

    async def _signal_event_queue_closed(self) -> None:
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
