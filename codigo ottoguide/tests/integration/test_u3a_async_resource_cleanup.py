"""U3AR10 — RED-first tests for async resource cleanup on the no-process
close path and real-subprocess transport teardown of
JsonlInteractionWorkerSupervisor. See docs/Arquitectura for the forensic
writeup; this file is scoped exclusively to the supervisor lifecycle, not
TourOrchestrator/U3C/hardware.
"""
from __future__ import annotations

import asyncio
import gc
import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from src.interaction.jsonl_worker_supervisor import (
    JsonlInteractionWorkerSupervisor,
    JsonlWorkerSupervisorConfig,
)
from src.interaction.runtime_port import InteractionRuntimeState

WORKER = Path(__file__).resolve().parents[1] / "support" / "u3a_loopback_worker.py"
PROBE = Path(__file__).resolve().parents[1] / "support" / "u3a_async_cleanup_probe.py"
REPO_ROOT = Path(__file__).resolve().parents[2]

_OWNED_TASK_PREFIX = "interaction-jsonl-"

_FORBIDDEN_SUBSTRINGS = (
    "PytestUnraisableExceptionWarning",
    "Task was destroyed but it is pending",
    "Task exception was never retrieved",
    "coroutine was never awaited",
    "Exception ignored in:",
    "Event loop is closed",
    "unclosed transport",
    "unclosed file",
    "ResourceWarning",
    "RuntimeWarning",
)


def _run_probe_in_fresh_process(scenario: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDEVMODE"] = "1"
    env["PYTHONASYNCIODEBUG"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, str(PROBE), scenario],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _assert_probe_clean(result: subprocess.CompletedProcess[str]) -> None:
    combined = result.stdout + result.stderr
    hits = [pattern for pattern in _FORBIDDEN_SUBSTRINGS if pattern in combined]
    assert result.returncode == 0, f"probe exited {result.returncode}; combined output:\n{combined}"
    assert hits == [], f"forbidden patterns {hits} found in probe output:\n{combined}"


def _config(
    scenario: str = "normal",
    *,
    startup_timeout_s: float = 0.4,
    shutdown_timeout_s: float = 0.15,
    terminate_timeout_s: float = 0.1,
) -> JsonlWorkerSupervisorConfig:
    return JsonlWorkerSupervisorConfig(
        argv=(sys.executable, str(WORKER), scenario),
        startup_timeout_s=startup_timeout_s,
        heartbeat_timeout_s=0.3,
        write_timeout_s=0.2,
        shutdown_timeout_s=shutdown_timeout_s,
        terminate_timeout_s=terminate_timeout_s,
        command_queue_size=4,
        event_queue_size=64,
        max_line_bytes=2048,
        stderr_tail_lines=10,
        stderr_tail_max_chars=2048,
        max_seen_message_ids=4096,
    )


def _owned_named_tasks() -> list[asyncio.Task[object]]:
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith(_OWNED_TASK_PREFIX)
    ]


class _FakeStdin:
    def __init__(self) -> None:
        self._closing = False
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        await asyncio.sleep(0)


class _FakeNoProcessCloseFixture:
    """Reaches READY, then holds open indefinitely (wait() never resolves
    on its own) so the no-process test can null `_process` out from under
    a supervisor with five live owned tasks, exactly mirroring
    test_close_no_process_clears_internal_interaction_id."""

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
        self._exited = asyncio.Event()
        self.stdout.feed_data(
            b'{"protocol_version":1,"message_id":"worker:0","interaction_id":null,'
            b'"event":"command_accepted","sequence":0,"emitted_at_monotonic_s":0.0,'
            b'"payload":{"command":"start","message_id":"py:0"}}\n'
        )
        import json as _json
        import time as _time

        ready_frame = {
            "protocol_version": 1,
            "message_id": "worker:1",
            "interaction_id": None,
            "event": "ready",
            "sequence": 1,
            "emitted_at_monotonic_s": _time.monotonic(),
            "payload": self._CAPS,
        }
        self.stdout.feed_data((_json.dumps(ready_frame) + "\n").encode("utf-8"))

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        self.returncode = -9
        self._exited.set()


@pytest.mark.asyncio
async def test_close_no_process_path_settles_all_owned_tasks() -> None:
    """R1 (RED against HEAD 0193d26d): the no-process branch of
    _close_impl() must settle every owned task, not bypass _cancel_tasks()."""
    fake = _FakeNoProcessCloseFixture()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    supervisor = _FakeSup(_config())
    await supervisor.start()

    # _stderr_drain settles on its own once stderr reaches EOF (fed at
    # fixture construction time), so only 4 of the 5 tasks spawned by
    # start() are still alive by the time start() returns; the other four
    # (command-writer, stdout-reader, process-watcher, heartbeat-monitor)
    # block on primitives that never resolve without cancellation -- see
    # docs/Arquitectura 03_lifecycle_ownership_analysis.md.
    await asyncio.sleep(0)
    live_before_null = _owned_named_tasks()
    assert len(live_before_null) == 4, f"expected 4 live owned tasks after start(), saw {live_before_null}"

    await supervisor.next_event(timeout_s=0.2)
    await supervisor.next_event(timeout_s=0.2)

    supervisor._state = InteractionRuntimeState.ACTIVE  # noqa: SLF001
    supervisor._active_interaction_id = "interaction:r1-test"  # noqa: SLF001
    supervisor._process = None  # noqa: SLF001

    await asyncio.wait_for(supervisor.close(), timeout=2.0)

    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
    assert supervisor._active_interaction_id is None  # noqa: SLF001

    for task in supervisor._tasks:  # noqa: SLF001
        assert task.done(), f"owned task {task.get_name()} still alive after close()"

    await asyncio.sleep(0)
    remaining = _owned_named_tasks()
    assert remaining == [], f"owned tasks leaked into asyncio.all_tasks(): {remaining}"

    assert supervisor._cleanup_task is None or supervisor._cleanup_task.done()  # noqa: SLF001
    assert supervisor._close_task is not None and supervisor._close_task.done()  # noqa: SLF001


@pytest.mark.asyncio
async def test_real_subprocess_graceful_close_leaves_no_owned_tasks_or_unraisable() -> None:
    """R3 (RED against HEAD 0193d26d on platforms where the transport
    teardown pattern reproduces): after close() against a REAL subprocess,
    the child must be reaped, zero owned tasks may remain, and forcing GC
    must not raise anything via sys.unraisablehook."""
    supervisor = JsonlInteractionWorkerSupervisor(_config("normal"))
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.5)
        await supervisor.next_event(timeout_s=0.5)
    finally:
        await asyncio.wait_for(supervisor.close(), timeout=5.0)

    assert (await supervisor.health()).state is InteractionRuntimeState.CLOSED
    assert supervisor._process is not None  # noqa: SLF001
    assert supervisor._process.returncode is not None  # noqa: SLF001

    await asyncio.sleep(0)
    remaining = _owned_named_tasks()
    assert remaining == [], f"owned tasks leaked after real-subprocess close(): {remaining}"

    unraisable: list[str] = []
    previous_hook = sys.unraisablehook

    def _hook(unraisable_obj: object) -> None:
        unraisable.append(repr(unraisable_obj))

    sys.unraisablehook = _hook
    try:
        del supervisor
        gc.collect()
        gc.collect()
    finally:
        sys.unraisablehook = previous_hook

    assert unraisable == [], f"unraisable exceptions during forced GC: {unraisable}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    ["startup_silent", "crash_before_ready", "malformed_json", "process_failed"],
)
async def test_real_subprocess_start_failure_leaves_no_owned_tasks_or_pipes(scenario: str) -> None:
    """R4 (RED against HEAD 0193d26d where reproducible): after start()
    raises for a REAL subprocess start failure, the self-clean path must
    have already reaped the child and settled every owned task before
    start() returns -- without the caller ever invoking close()."""
    supervisor = JsonlInteractionWorkerSupervisor(_config(scenario, startup_timeout_s=0.3))

    with pytest.raises(Exception):
        await asyncio.wait_for(supervisor.start(), timeout=5.0)

    if supervisor._process is not None:  # noqa: SLF001
        assert supervisor._process.returncode is not None  # noqa: SLF001

    await asyncio.sleep(0)
    remaining = _owned_named_tasks()
    assert remaining == [], f"owned tasks leaked after start() failure ({scenario}): {remaining}"

    unraisable: list[str] = []
    previous_hook = sys.unraisablehook

    def _hook(unraisable_obj: object) -> None:
        unraisable.append(repr(unraisable_obj))

    sys.unraisablehook = _hook
    try:
        del supervisor
        gc.collect()
        gc.collect()
    finally:
        sys.unraisablehook = previous_hook

    assert unraisable == [], f"unraisable exceptions during forced GC after start failure: {unraisable}"


@pytest.mark.asyncio
async def test_no_process_close_path_does_not_emit_resource_warnings(recwarn: pytest.WarningsRecorder) -> None:
    """Companion to R1: forcing the no-process path must not surface
    ResourceWarning/RuntimeWarning even under default warning filters."""
    fake = _FakeNoProcessCloseFixture()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    supervisor = _FakeSup(_config())
    await supervisor.start()
    await supervisor.next_event(timeout_s=0.2)
    await supervisor.next_event(timeout_s=0.2)
    supervisor._process = None  # noqa: SLF001

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await asyncio.wait_for(supervisor.close(), timeout=2.0)
        await asyncio.sleep(0)
        gc.collect()

    forbidden = [
        str(w.message)
        for w in caught
        if issubclass(w.category, (ResourceWarning, RuntimeWarning))
    ]
    assert forbidden == [], f"forbidden warnings after no-process close(): {forbidden}"


def test_outer_process_no_process_close_leaves_no_forbidden_patterns() -> None:
    """R2/R6: run the R1 scenario in a fresh interpreter under
    PYTHONDEVMODE=1/PYTHONASYNCIODEBUG=1 and scan its stdout+stderr AFTER
    the interpreter has fully exited -- this is the only way to catch
    'Task was destroyed but it is pending!' messages that asyncio logs
    during final interpreter/event-loop teardown, which never surface
    inside the parent test's own capture window (see 01_evidence_forensics.md
    for why in-process pytest attribution is misleading)."""
    result = _run_probe_in_fresh_process("no_process_close")
    _assert_probe_clean(result)


def test_outer_process_real_subprocess_close_leaves_no_forbidden_patterns() -> None:
    """R6: real-subprocess variant of the outer-process scanner."""
    result = _run_probe_in_fresh_process("real_close")
    _assert_probe_clean(result)


@pytest.mark.parametrize(
    "scenario",
    ["startup_silent", "crash_before_ready", "malformed_json", "process_failed"],
)
def test_outer_process_real_subprocess_start_failure_leaves_no_forbidden_patterns(scenario: str) -> None:
    """R6: real-subprocess start-failure variant of the outer-process scanner."""
    result = _run_probe_in_fresh_process(f"real_start_failure:{scenario}")
    _assert_probe_clean(result)
