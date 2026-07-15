"""Offline replay of a harvested rt/lowstate JSONL fixture.

No robot, no Unitree SDK, no DDS, no ROS, no PyQt, no network, and no
dependency on the robot's filesystem. This module only reads a local JSONL
fixture and replays it in-process or over stdout. It must never be wired to
a production runtime, FastAPI app, or WebSocket transport -- it is an
offline consolidation and inspection tool only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Optional


def _deep_freeze(value: Any) -> Any:
    """Recursively convert dicts to read-only MappingProxyType and lists/tuples
    to tuples of frozen elements, so no nested structure remains mutable.

    Scalars (str, int, float, bool, None) are returned unchanged -- they are
    already immutable in Python. This is what makes LowStateSnapshot.raw
    genuinely immutable, not just its own top-level attribute: a frozen
    dataclass alone only stops `snapshot.raw = ...`, it does nothing to
    prevent `snapshot.raw["tick"] = ...` on a plain dict.
    """
    if isinstance(value, dict):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


def _deep_thaw(value: Any) -> Any:
    """Recursively convert a deep-frozen structure back to plain dict/list.

    Required for JSON serialization: json.dumps() raises TypeError on
    MappingProxyType directly (it is not a dict subclass), so this
    conversion is not optional. It builds brand-new plain containers, so
    the result never aliases the frozen structure's own backing storage.
    """
    if isinstance(value, MappingProxyType):
        return {k: _deep_thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class LowStateSnapshot:
    """An immutable single rt/lowstate sample as read from the fixture.

    `raw` is a deeply frozen view of the parsed JSON object for this record
    (MappingProxyType for objects, tuple for arrays) -- unmodified content,
    but genuinely immutable at every nesting level, not just at the top.
    Fields absent or null in the source (e.g. power_v, power_a, bms_state,
    foot_force) remain null here. Nothing is defaulted to zero.
    """

    index: int
    raw: Mapping[str, Any]


class LowStateSnapshotSource:
    """Replays a harvested lowstate_10hz.jsonl fixture, in-memory and read-only."""

    def __init__(self, fixture_path: str | Path) -> None:
        self._fixture_path = Path(fixture_path)
        self._records: list[dict[str, Any]] = self._load(self._fixture_path)
        self._closed = False
        self._latest_index = -1

    @staticmethod
    def _load(fixture_path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with fixture_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    def __len__(self) -> int:
        return len(self._records)

    def latest(self) -> Optional[LowStateSnapshot]:
        """Return an immutable snapshot of the most recently iterated record.

        Returns None if no record has been produced yet (before the first
        iter_samples() advance) or if the source is closed. The returned
        snapshot's `raw` is deeply frozen: mutating it can never corrupt
        this source's internal state, and calling latest() again always
        returns the same, unpoisoned content.
        """
        if self._closed or self._latest_index < 0:
            return None
        return LowStateSnapshot(
            index=self._latest_index, raw=_deep_freeze(self._records[self._latest_index])
        )

    def health(self) -> dict[str, Any]:
        """Report replay state, record count, current index, and field availability.

        `freshness_simulated` reflects only the replay's own progress through
        the fixture (whether the latest snapshot is the final record), not a
        wall-clock staleness measurement against a live robot -- there is no
        live robot here.
        """
        total = len(self._records)
        state = "closed" if self._closed else ("idle" if self._latest_index < 0 else "streaming")
        latest = self._records[self._latest_index] if 0 <= self._latest_index < total else None
        field_availability = None
        if latest is not None:
            field_availability = {
                field: latest.get(field) is not None
                for field in ("power_v", "power_a", "bms_state", "foot_force", "imu", "motors")
            }
        return {
            "state": state,
            "record_count": total,
            "current_index": self._latest_index,
            "freshness_simulated": (
                self._latest_index == total - 1 if 0 <= self._latest_index else None
            ),
            "field_availability": field_availability,
        }

    def iter_samples(
        self,
        start_index: int = 0,
        limit: Optional[int] = None,
        rate: float = 0.0,
        loop: bool = False,
    ) -> Iterator[LowStateSnapshot]:
        """Yield snapshots from the fixture, honoring start/limit/rate/loop.

        rate=0   -> no sleeps between yields (as fast as the caller consumes).
        rate=1   -> reproduces the timing observed in the source capture
                    (using each record's receipt_monotonic_ns delta to the
                    previous record).
        loop     -> after exhausting the fixture, restarts explicitly from
                    start_index and continues; iteration otherwise stops
                    when the fixture is exhausted or `limit` is reached.

        All arguments are validated fail-closed *before* iteration begins.
        This method is deliberately not itself a generator function: a
        generator function's body (including validation code preceding any
        `yield`) does not execute until the first `next()` call, so bad
        arguments would otherwise only surface once the caller starts
        consuming the result, not when they call iter_samples(). Here,
        validation runs synchronously at call time and raises immediately;
        only the actual replay loop is delegated to an internal generator.

        Raises ValueError for:
          - start_index not an int, or negative, or >= record_count for a
            non-empty fixture (no silent Python negative-index wraparound);
          - limit not None and not a non-negative int;
          - rate not exactly 0 or 1 (as int or float; e.g. 0.5 is rejected;
            bool is also rejected even though True == 1 and False == 0 in
            Python, since a bool is not a numeric literal 0/0.0/1/1.0).

        Behavior for an empty fixture (record_count == 0): start_index=0 is
        accepted (there is no valid non-zero start_index either way) and the
        generator yields nothing and returns immediately, loop or not --
        looping over zero records is a no-op, never a hang.

        loop=True combined with start_index >= record_count can no longer
        occur: start_index is validated against record_count above, so the
        loop-reset target is always in-bounds by construction, eliminating
        the infinite-loop hang that existed before this validation was added.
        """
        total = len(self._records)

        if not isinstance(start_index, int) or isinstance(start_index, bool):
            raise ValueError(f"start_index must be an int, got {type(start_index).__name__}")
        if total == 0:
            if start_index != 0:
                raise ValueError(f"start_index must be 0 for an empty fixture, got {start_index}")
        elif not (0 <= start_index < total):
            raise ValueError(
                f"start_index must satisfy 0 <= start_index < {total} (record_count); got {start_index}"
            )

        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool):
                raise ValueError(f"limit must be None or a non-negative int, got {type(limit).__name__}")
            if limit < 0:
                raise ValueError(f"limit must be >= 0, got {limit}")

        if isinstance(rate, bool) or rate not in (0, 0.0, 1, 1.0):
            raise ValueError(f"rate must be exactly 0 or 1 (numeric, not bool), got {rate!r}")

        return self._iter_samples_impl(start_index, limit, rate, loop)

    def _iter_samples_impl(
        self,
        start_index: int,
        limit: Optional[int],
        rate: float,
        loop: bool,
    ) -> Iterator[LowStateSnapshot]:
        """Actual replay loop. Only reachable with already-validated arguments."""
        if self._closed:
            return
        total = len(self._records)
        if total == 0 or limit == 0:
            return

        emitted = 0
        idx = start_index
        prev_ns: Optional[int] = None

        while True:
            if idx >= total:
                if loop:
                    idx = start_index
                    prev_ns = None
                    continue
                return

            if limit is not None and emitted >= limit:
                return

            record = self._records[idx]
            if rate == 1.0 and prev_ns is not None:
                curr_ns = record.get("receipt_monotonic_ns")
                if isinstance(curr_ns, int) and curr_ns >= prev_ns:
                    delay_s = (curr_ns - prev_ns) / 1e9
                    if delay_s > 0:
                        time.sleep(delay_s)

            self._latest_index = idx
            prev_ns = record.get("receipt_monotonic_ns") if rate == 1.0 else prev_ns
            yield LowStateSnapshot(index=idx, raw=_deep_freeze(record))

            emitted += 1
            idx += 1

    def close(self) -> None:
        """Idempotent: safe to call multiple times, including before any read."""
        self._closed = True


def snapshot_to_websocket_compatible(snapshot: LowStateSnapshot) -> dict[str, Any]:
    """Shape a snapshot into an offline websocket-compatible contract payload.

    This is an offline data contract only. It is never sent over a real
    socket or connected to the production WebSocket transport by this tool.

    `payload` is thawed to a plain dict/list tree for JSON-serializability;
    `_deep_thaw` builds brand-new plain containers, so this never hands back
    a reference into the snapshot's own frozen backing storage -- mutating
    the returned envelope's `payload` cannot corrupt the snapshot or source.
    """
    return {
        "type": "lowstate_frame",
        "index": snapshot.index,
        "payload": _deep_thaw(snapshot.raw),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lowstate_replay",
        description="Offline replay of a harvested rt/lowstate JSONL fixture (no robot, no SDK, no DDS, no ROS, no network).",
    )
    parser.add_argument("--fixture", required=True, help="Path to lowstate_10hz.jsonl")
    parser.add_argument("--rate", type=float, default=0.0, choices=[0.0, 1.0], help="0 = no sleeps, 1 = reproduce observed timing")
    parser.add_argument("--loop", action="store_true", help="Restart from --start-index after exhausting the fixture")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--output",
        choices=["jsonl", "websocket-compatible"],
        default="jsonl",
        help="jsonl = raw record per line; websocket-compatible = offline contract envelope per line",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    source = LowStateSnapshotSource(args.fixture)
    try:
        for snapshot in source.iter_samples(
            start_index=args.start_index,
            limit=args.limit,
            rate=args.rate,
            loop=args.loop,
        ):
            if args.output == "websocket-compatible":
                out = snapshot_to_websocket_compatible(snapshot)
            else:
                out = _deep_thaw(snapshot.raw)
            print(json.dumps(out), flush=True)
    finally:
        source.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
