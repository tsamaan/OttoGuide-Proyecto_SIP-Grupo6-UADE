#!/usr/bin/env python3
"""Offline synthetic emitter for the Unitree capture bridge AF_UNIX protocol.

Emits the same protocol-version-1 datagrams the native tap produces
(lowstate, secondary_imu, sport_state, health) so the ROS2 bridge node and
the protocol parser can be exercised without a robot, without ROS, and
without the Unitree SDK. Pure standard library, no external dependencies.
"""

import argparse
import json
import math
import signal
import socket
import sys
import time

PROTOCOL_VERSION = 1

NEGATIVE_CASES = (
    "truncated",
    "invalid-json",
    "invalid-version",
    "nan",
    "missing-field",
    "wrong-type",
)


def _now_ns() -> int:
    return time.monotonic_ns()


def build_lowstate(now_ns: int, tick: int) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "k": "lowstate",
        "t": now_ns,
        "ch": "rt/lowstate",
        "tick": tick,
        "mm": 0,
        "lx": 0.0,
        "ly": 0.0,
        "rx": 0.0,
        "ry": 0.0,
        "keys": 0,
        "q": [1.0, 0.0, 0.0, 0.0],
        "g": [0.0, 0.0, 0.0],
        "a": [0.0, 0.0, 9.81],
        "rpy": [0.0, 0.0, 0.0],
    }


def build_secondary_imu(now_ns: int) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "k": "secondary_imu",
        "t": now_ns,
        "q": [1.0, 0.0, 0.0, 0.0],
        "g": [0.0, 0.0, 0.0],
        "a": [0.0, 0.0, 9.81],
        "rpy": [0.0, 0.0, 0.0],
    }


def build_sport_state(now_ns: int, fsm: int = 0) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "k": "sport_state",
        "t": now_ns,
        "fsm": fsm,
    }


def build_health(now_ns: int, start_ns: int, counters: dict) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "k": "health",
        "t": now_ns,
        "up": (now_ns - start_ns) / 1e9,
        "n_ls": counters["lowstate"],
        "n_lf_ls": 0,
        "n_simu": counters["secondary_imu"],
        "n_sport": counters["sport_state"],
        "n_sent": counters["sent"],
        "n_drop": 0,
    }


def build_negative_payload(case: str) -> bytes:
    if case == "truncated":
        payload = json.dumps(build_lowstate(1, 1)).encode("utf-8")
        return payload[: len(payload) // 2]
    if case == "invalid-json":
        return b"{not-json"
    if case == "invalid-version":
        packet = build_lowstate(1, 1)
        packet["v"] = 2
        return json.dumps(packet).encode("utf-8")
    if case == "nan":
        # json.dumps default emits NaN as the literal `NaN`, which json.loads
        # on the receiving side accepts as a Python float('nan'); the
        # protocol parser must then reject it on the math.isfinite() check.
        packet = build_lowstate(1, 1)
        packet["a"] = [0.0, 0.0, float("nan")]
        return json.dumps(packet).encode("utf-8")
    if case == "missing-field":
        packet = build_lowstate(1, 1)
        del packet["tick"]
        return json.dumps(packet).encode("utf-8")
    if case == "wrong-type":
        packet = build_lowstate(1, 1)
        packet["keys"] = "not-an-int"
        return json.dumps(packet).encode("utf-8")
    raise ValueError("unknown negative case: {}".format(case))


class RateScheduler:
    """Deterministic fixed-period scheduler, independent of wall clock drift."""

    def __init__(self, hz: float, start_ns: int):
        self.period_ns = None if hz <= 0 else int(1_000_000_000 / hz)
        self.next_ns = start_ns

    def due(self, now_ns: int) -> bool:
        if self.period_ns is None:
            return False
        if now_ns < self.next_ns:
            return False
        self.next_ns += self.period_ns
        if self.next_ns <= now_ns:
            self.next_ns = now_ns + self.period_ns
        return True


def run_emitter(args) -> int:
    counters = {"lowstate": 0, "secondary_imu": 0, "sport_state": 0, "sent": 0}
    start_ns = _now_ns()
    end_ns = None if args.duration <= 0 else start_ns + int(args.duration * 1e9)

    lowstate_sched = RateScheduler(args.lowstate_hz, start_ns)
    imu_sched = RateScheduler(args.secondary_imu_hz, start_ns)
    sport_sched = RateScheduler(args.sport_hz, start_ns)
    health_sched = RateScheduler(args.health_hz, start_ns)

    sock = None
    if not args.dry_run:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    stop = {"flag": False}

    def handle_sigint(_signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    def emit(packet: dict) -> None:
        payload = json.dumps(packet).encode("utf-8")
        if args.dry_run:
            json.loads(payload.decode("utf-8"))  # round-trip validation only
            return
        try:
            sock.sendto(payload, args.socket)
            counters["sent"] += 1
        except OSError as exc:
            print("[synthetic-emitter] send failed: {}".format(exc), file=sys.stderr)

    tick = 0
    try:
        while not stop["flag"]:
            now_ns = _now_ns()
            if end_ns is not None and now_ns >= end_ns:
                break
            if lowstate_sched.due(now_ns):
                tick += 1
                counters["lowstate"] += 1
                emit(build_lowstate(now_ns, tick))
            if imu_sched.due(now_ns):
                counters["secondary_imu"] += 1
                emit(build_secondary_imu(now_ns))
            if sport_sched.due(now_ns):
                counters["sport_state"] += 1
                emit(build_sport_state(now_ns))
            if health_sched.due(now_ns):
                emit(build_health(now_ns, start_ns, counters))
            time.sleep(0.001)
    finally:
        if sock is not None:
            sock.close()

    print(
        "[synthetic-emitter] stopped lowstate={lowstate} secondary_imu={secondary_imu} "
        "sport_state={sport_state} sent={sent}".format(**counters)
    )
    return 0


def run_negative(args) -> int:
    payload = build_negative_payload(args.negative_case)
    if args.dry_run:
        print(
            "[synthetic-emitter] dry-run negative case '{}' payload={!r}".format(
                args.negative_case, payload
            )
        )
        return 0
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(payload, args.socket)
    finally:
        sock.close()
    print("[synthetic-emitter] sent negative case '{}'".format(args.negative_case))
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--socket", default="/tmp/ottoguide_unitree_capture.sock",
        help="AF_UNIX SOCK_DGRAM target path",
    )
    parser.add_argument("--duration", type=float, default=10.0,
                         help="seconds to run; <=0 means run until SIGINT")
    parser.add_argument("--lowstate-hz", type=float, default=50.0)
    parser.add_argument("--secondary-imu-hz", type=float, default=100.0)
    parser.add_argument("--sport-hz", type=float, default=10.0)
    parser.add_argument("--health-hz", type=float, default=1.0)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="generate and validate packets locally without opening a socket",
    )
    parser.add_argument(
        "--negative-case", choices=NEGATIVE_CASES, default=None,
        help="send exactly one malformed datagram instead of the normal stream",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.negative_case is not None:
        return run_negative(args)
    return run_emitter(args)


if __name__ == "__main__":
    sys.exit(main())
