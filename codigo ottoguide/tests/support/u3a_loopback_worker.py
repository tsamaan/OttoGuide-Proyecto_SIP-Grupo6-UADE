from __future__ import annotations

import json
import sys
import threading
import time


PROTOCOL_VERSION = 1
CAPABILITIES = {
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


class Worker:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.sequence = 0
        self.message_index = 0
        self.running = True
        self.active_interaction_id: str | None = None
        self.lock = threading.Lock()
        self.heartbeat_enabled = False

    def emit(self, event: str, *, interaction_id: str | None = None, payload: dict[str, object] | None = None, duplicate: bool = False, sequence_delta: int = 1) -> None:
        with self.lock:
            message_id = f"worker:{self.message_index}"
            if not duplicate:
                self.message_index += 1
            frame = {
                "protocol_version": PROTOCOL_VERSION,
                "message_id": message_id,
                "interaction_id": interaction_id,
                "event": event,
                "sequence": self.sequence,
                "emitted_at_monotonic_s": time.monotonic(),
                "payload": payload or {},
            }
            self.sequence += sequence_delta
            sys.stdout.write(json.dumps(frame, allow_nan=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def heartbeat_loop(self) -> None:
        while self.running:
            time.sleep(0.05)
            if self.heartbeat_enabled:
                self.emit("heartbeat")

    def command_accepted(self, command: dict[str, object]) -> None:
        self.emit(
            "command_accepted",
            interaction_id=command.get("interaction_id"),  # type: ignore[arg-type]
            payload={"command": command.get("command"), "message_id": command.get("message_id")},
        )

    def start(self) -> int:
        if self.scenario == "crash_before_ready":
            return 3
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        for raw_line in sys.stdin.buffer:
            if self.scenario == "invalid_utf8":
                sys.stdout.buffer.write(b"\xff\n")
                sys.stdout.buffer.flush()
                time.sleep(1)
                return 4
            try:
                command = json.loads(raw_line.decode("utf-8"))
            except Exception:
                return 5
            name = command.get("command")
            if name == "start":
                if self.scenario == "startup_silent":
                    time.sleep(5)
                    return 6
                if self.scenario == "malformed_json":
                    sys.stdout.write("{not-json\n")
                    sys.stdout.flush()
                    time.sleep(1)
                    return 7
                if self.scenario == "oversized_line":
                    sys.stdout.write("{" + '"x":"' + ("a" * 70000) + '"}' + "\n")
                    sys.stdout.flush()
                    time.sleep(1)
                    return 8
                if self.scenario == "missing_newline":
                    frame = {
                        "protocol_version": PROTOCOL_VERSION,
                        "message_id": "worker:missing-newline",
                        "interaction_id": None,
                        "event": "command_accepted",
                        "sequence": self.sequence,
                        "emitted_at_monotonic_s": time.monotonic(),
                        "payload": {"command": name, "message_id": command.get("message_id")},
                    }
                    sys.stdout.write(json.dumps(frame, allow_nan=False, separators=(",", ":")))
                    sys.stdout.flush()
                    sys.stdout.close()
                    return 10
                self.command_accepted(command)
                if self.scenario == "duplicate_message_id":
                    self.emit("ready", payload=CAPABILITIES, duplicate=True)
                elif self.scenario == "out_of_order_sequence":
                    self.emit("ready", payload=CAPABILITIES, sequence_delta=2)
                else:
                    self.emit("ready", payload=CAPABILITIES)
                if self.scenario == "crash_after_ready":
                    time.sleep(0.05)
                    return 9
                if self.scenario == "stderr_flood":
                    for idx in range(500):
                        print(f"log-line-{idx}", file=sys.stderr, flush=True)
                if self.scenario == "stderr_long_line":
                    print("x" * 200000, file=sys.stderr, flush=True)
                    print("after-long-line", file=sys.stderr, flush=True)
                if self.scenario == "stderr_unterminated_flood":
                    chunk = "z" * 65536
                    written = 0
                    target = 2 * 1024 * 1024 + 1
                    while written < target:
                        sys.stderr.write(chunk)
                        sys.stderr.flush()
                        written += len(chunk)
                if self.scenario == "process_failed":
                    self.emit(
                        "failed",
                        interaction_id=None,
                        payload={"code": "ERR_WORKER_FATAL", "message": "process-level failure"},
                    )
                if self.scenario not in {"heartbeat_stops", "ignore_close"}:
                    self.heartbeat_enabled = True
            elif name == "activate":
                self.active_interaction_id = command.get("interaction_id")  # type: ignore[assignment]
                self.command_accepted(command)
                interaction_id = self.active_interaction_id
                if self.scenario == "stale_interaction":
                    interaction_id = "stale-id"
                self.emit("capture_started", interaction_id=interaction_id)
                if self.scenario == "activation_waits":
                    continue
                if self.scenario == "interaction_failed":
                    self.emit(
                        "failed",
                        interaction_id=interaction_id,
                        payload={"code": "ERR_INTERACTION_FAILED", "message": "interaction failure"},
                    )
                    self.active_interaction_id = None
                    continue
                if self.scenario == "message_limit":
                    for idx in range(64):
                        self.emit("heartbeat")
                    continue
                self.emit("transcript_ready", interaction_id=interaction_id, payload={"text": "hola"})
                self.emit("response_ready", interaction_id=interaction_id, payload={"text": "respuesta"})
                self.emit("playback_started", interaction_id=interaction_id)
                self.emit("playback_completed", interaction_id=interaction_id, payload={"duration_s": 0.01})
                self.active_interaction_id = None
            elif name == "pause":
                self.command_accepted(command)
            elif name == "resume":
                self.command_accepted(command)
            elif name == "stop":
                self.command_accepted(command)
                self.emit("cancelled", interaction_id=command.get("interaction_id"))  # type: ignore[arg-type]
                self.emit("stopped")
                self.active_interaction_id = None
            elif name == "emergency_stop":
                self.heartbeat_enabled = False
                self.running = False
                self.emit("stopped")
                return 0
            elif name == "close":
                if self.scenario == "ignore_close":
                    while True:
                        time.sleep(1)
                self.command_accepted(command)
                self.running = False
                self.emit("closed")
                return 0
        return 0


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"
    return Worker(scenario).start()


if __name__ == "__main__":
    raise SystemExit(main())
