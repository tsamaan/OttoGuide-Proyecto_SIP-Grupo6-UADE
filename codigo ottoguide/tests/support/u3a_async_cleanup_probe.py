"""U3AR10 outer-process probe. Runs a single named scenario to completion
inside THIS interpreter (intended to be launched as a fresh child process
by tests/integration/test_u3a_async_resource_cleanup.py), then prints
PROBE_RESULT:<forbidden_pattern_count> to stdout as the last line so the
parent can assert on it after the child interpreter has fully exited
(catching leaks that only surface at final interpreter/event-loop
teardown, which asyncio logs asynchronously outside any test's own
capture window).

Usage: python u3a_async_cleanup_probe.py <scenario>
Scenarios:
  no_process_close   -- R1/R2: no-process branch of _close_impl()
  real_close          -- R3: real subprocess graceful close
  real_start_failure:<name> -- R4: real subprocess start failure variants
"""
from __future__ import annotations

import asyncio
import gc
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.interaction.jsonl_worker_supervisor import (  # noqa: E402
    JsonlInteractionWorkerSupervisor,
    JsonlWorkerSupervisorConfig,
)

WORKER = Path(__file__).resolve().parent / "u3a_loopback_worker.py"

FORBIDDEN_SUBSTRINGS = (
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


def _config(scenario: str, **overrides: float) -> JsonlWorkerSupervisorConfig:
    base = dict(
        argv=(sys.executable, str(WORKER), scenario),
        startup_timeout_s=0.4,
        heartbeat_timeout_s=0.3,
        write_timeout_s=0.2,
        shutdown_timeout_s=0.15,
        terminate_timeout_s=0.1,
        command_queue_size=4,
        event_queue_size=64,
        max_line_bytes=2048,
        stderr_tail_lines=10,
        stderr_tail_max_chars=2048,
        max_seen_message_ids=4096,
    )
    base.update(overrides)
    return JsonlWorkerSupervisorConfig(**base)  # type: ignore[arg-type]


async def _run_no_process_close() -> None:
    import time as _time

    class _FakeStdin:
        def __init__(self) -> None:
            self._closing = False

        def write(self, data: bytes) -> None:
            pass

        async def drain(self) -> None:
            await asyncio.sleep(0)

        def is_closing(self) -> bool:
            return self._closing

        def close(self) -> None:
            self._closing = True

        async def wait_closed(self) -> None:
            await asyncio.sleep(0)

    class _FakeProcess:
        def __init__(self) -> None:
            self.stdin = _FakeStdin()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()
            self.returncode: int | None = None
            self._exited = asyncio.Event()
            caps = {
                "audio_capture": False, "wake_word": False, "vad": False, "stt": False,
                "local_llm": False, "spanish_tts": False, "physical_playback": False,
                "physical_playback_stop": False, "physical_playback_completion": False,
            }
            self.stdout.feed_data(
                b'{"protocol_version":1,"message_id":"worker:0","interaction_id":null,'
                b'"event":"command_accepted","sequence":0,"emitted_at_monotonic_s":0.0,'
                b'"payload":{"command":"start","message_id":"py:0"}}\n'
            )
            frame = {
                "protocol_version": 1, "message_id": "worker:1", "interaction_id": None,
                "event": "ready", "sequence": 1, "emitted_at_monotonic_s": _time.monotonic(),
                "payload": caps,
            }
            self.stdout.feed_data((json.dumps(frame) + "\n").encode("utf-8"))

        async def wait(self) -> int:
            await self._exited.wait()
            assert self.returncode is not None
            return self.returncode

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            self.returncode = -9
            self._exited.set()

    fake = _FakeProcess()

    class _FakeSup(JsonlInteractionWorkerSupervisor):
        async def _create_process(self) -> asyncio.subprocess.Process:
            return fake  # type: ignore[return-value]

    supervisor = _FakeSup(_config("normal"))
    await supervisor.start()
    await supervisor.next_event(timeout_s=0.2)
    await supervisor.next_event(timeout_s=0.2)
    supervisor._process = None  # noqa: SLF001
    await asyncio.wait_for(supervisor.close(), timeout=2.0)
    del supervisor
    gc.collect()


async def _run_real_close() -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config("normal"))
    await supervisor.start()
    try:
        await supervisor.next_event(timeout_s=0.5)
        await supervisor.next_event(timeout_s=0.5)
    finally:
        await asyncio.wait_for(supervisor.close(), timeout=5.0)
    del supervisor
    gc.collect()


async def _run_real_start_failure(scenario: str) -> None:
    supervisor = JsonlInteractionWorkerSupervisor(_config(scenario, startup_timeout_s=0.3))
    try:
        await asyncio.wait_for(supervisor.start(), timeout=5.0)
    except Exception:
        pass
    del supervisor
    gc.collect()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: u3a_async_cleanup_probe.py <scenario>", file=sys.stderr)
        return 2
    scenario = sys.argv[1]
    if scenario == "no_process_close":
        asyncio.run(_run_no_process_close())
    elif scenario == "real_close":
        asyncio.run(_run_real_close())
    elif scenario.startswith("real_start_failure:"):
        inner = scenario.split(":", 1)[1]
        asyncio.run(_run_real_start_failure(inner))
    else:
        print(f"unknown scenario: {scenario}", file=sys.stderr)
        return 2
    gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
