"""Tests for the offline lowstate replay tool (tools/offline_replay/lowstate_replay.py).

These tests exercise the replay entirely offline against the harvested
fixture at tests/fixtures/physical/lowstate_harvest_r1/. No robot, SDK,
DDS, ROS, or network access occurs anywhere in this file.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path
from types import MappingProxyType

import pytest

from tools.offline_replay.lowstate_replay import (
    LowStateSnapshotSource,
    snapshot_to_websocket_compatible,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "physical" / "lowstate_harvest_r1"
FIXTURE_PATH = FIXTURE_DIR / "lowstate_10hz.jsonl"
REPLAY_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "tools" / "offline_replay" / "lowstate_replay.py"
)

FORBIDDEN_MODULE_PREFIXES = (
    "unitree_sdk2",
    "cyclonedds",
    "rclpy",
    "PyQt5",
    "PyQt6",
    "fastapi",
    "socket",
    "requests",
    "httpx",
    "aiohttp",
)


@pytest.fixture()
def source() -> LowStateSnapshotSource:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    yield src
    src.close()


def test_fixture_has_299_records(source: LowStateSnapshotSource) -> None:
    assert len(source) == 299


def test_fixture_lines_are_all_valid_json() -> None:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        lines = [line for line in fh if line.strip()]
    assert len(lines) == 299
    for line in lines:
        json.loads(line)  # raises if invalid


def test_receipt_monotonic_ns_strictly_increasing(source: LowStateSnapshotSource) -> None:
    values = [s.raw["receipt_monotonic_ns"] for s in source.iter_samples(rate=0)]
    assert len(values) == 299
    assert all(values[i] < values[i + 1] for i in range(len(values) - 1))


def test_tick_strictly_increasing(source: LowStateSnapshotSource) -> None:
    values = [s.raw["tick"] for s in source.iter_samples(rate=0)]
    assert all(values[i] < values[i + 1] for i in range(len(values) - 1))


def test_rate_zero_has_no_sleeps(source: LowStateSnapshotSource) -> None:
    start = time.monotonic()
    count = sum(1 for _ in source.iter_samples(rate=0))
    elapsed = time.monotonic() - start
    assert count == 299
    assert elapsed < 1.0  # generous ceiling; a real replay at rate=0 finishes in milliseconds


def test_rate_one_reproduces_observed_timing_with_tolerance() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        start = time.monotonic()
        snaps = list(src.iter_samples(start_index=0, limit=5, rate=1))
        elapsed = time.monotonic() - start
    finally:
        src.close()

    assert [s.index for s in snaps] == [0, 1, 2, 3, 4]
    expected_ns = snaps[-1].raw["receipt_monotonic_ns"] - snaps[0].raw["receipt_monotonic_ns"]
    expected_s = expected_ns / 1e9
    # generous tolerance for scheduler jitter on a shared CI/dev host
    assert abs(elapsed - expected_s) < 0.25


def test_loop_restarts_explicitly_at_start_index() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        indices = [s.index for s in src.iter_samples(start_index=296, limit=6, rate=0, loop=True)]
    finally:
        src.close()
    assert indices == [296, 297, 298, 296, 297, 298]


def test_start_index_and_limit_are_honored() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        indices = [s.index for s in src.iter_samples(start_index=50, limit=3, rate=0)]
    finally:
        src.close()
    assert indices == [50, 51, 52]


def test_without_loop_iteration_stops_at_end_of_fixture() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        indices = [s.index for s in src.iter_samples(start_index=297, rate=0, loop=False)]
    finally:
        src.close()
    assert indices == [297, 298]


def test_latest_is_none_before_any_iteration() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        assert src.latest() is None
    finally:
        src.close()


def test_latest_returns_immutable_snapshot_matching_last_yielded() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        list(src.iter_samples(start_index=0, limit=10, rate=0))
        latest = src.latest()
        assert latest is not None
        assert latest.index == 9
        with pytest.raises(Exception):
            # frozen dataclass: attribute assignment must fail
            latest.index = 999  # type: ignore[misc]
    finally:
        src.close()


def test_close_is_idempotent() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    src.close()
    src.close()
    src.close()  # must not raise on repeated calls


def test_close_before_any_read_is_safe() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    src.close()
    assert src.latest() is None
    assert list(src.iter_samples(rate=0)) == []


def test_health_reports_state_count_index_and_field_availability() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        idle_health = src.health()
        assert idle_health["state"] == "idle"
        assert idle_health["record_count"] == 299
        assert idle_health["current_index"] == -1

        list(src.iter_samples(start_index=0, limit=1, rate=0))
        streaming_health = src.health()
        assert streaming_health["state"] == "streaming"
        assert streaming_health["current_index"] == 0
        assert streaming_health["field_availability"]["power_v"] is False
        assert streaming_health["field_availability"]["power_a"] is False
        assert streaming_health["field_availability"]["bms_state"] is False
        assert streaming_health["field_availability"]["foot_force"] is False
        assert streaming_health["field_availability"]["imu"] is True
        assert streaming_health["field_availability"]["motors"] is True
    finally:
        src.close()
        assert src.health()["state"] == "closed"


def test_35_motor_states_received_and_29_persisted_named() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snaps = list(src.iter_samples(rate=0))
    finally:
        src.close()
    received_counts = {s.raw["motor_count_received"] for s in snaps}
    persisted_counts = {s.raw["motor_count_persisted"] for s in snaps}
    motor_array_lengths = {len(s.raw["motors"]) for s in snaps}
    assert received_counts == {35}
    assert persisted_counts == {29}
    assert motor_array_lengths == {29}

    names = {m["name"] for s in snaps for m in s.raw["motors"]}
    assert len(names) == 29


def test_null_fields_are_preserved_never_zero_filled() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snaps = list(src.iter_samples(rate=0))
    finally:
        src.close()
    for field in ("power_v", "power_a", "bms_state", "foot_force"):
        values = {s.raw.get(field) for s in snaps}
        assert values == {None}, f"{field} must remain null in every record, never fabricated as 0"


def test_websocket_compatible_output_shape() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(start_index=0, limit=1, rate=0)))
    finally:
        src.close()
    envelope = snapshot_to_websocket_compatible(snap)
    assert envelope["type"] == "lowstate_frame"
    assert envelope["index"] == 0
    # payload is thawed to plain dict/list for JSON-serializability, so it is
    # value-equal to the frozen snap.raw tree but not the same object/type
    assert envelope["payload"]["tick"] == snap.raw["tick"]
    assert envelope["payload"]["motors"][0]["name"] == snap.raw["motors"][0]["name"]
    assert isinstance(envelope["payload"], dict)
    assert isinstance(envelope["payload"]["motors"], list)
    # mutating the returned envelope's payload must never touch the snapshot's frozen storage
    envelope["payload"]["tick"] = -1
    assert snap.raw["tick"] != -1
    # must be JSON-serializable (offline contract, never actually sent over a socket here)
    json.dumps(envelope)


def test_replay_module_imports_no_sdk_dds_ros_or_network() -> None:
    """Static check: the replay module source must not import any forbidden module."""
    source_text = REPLAY_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    for name in imported_names:
        for forbidden in FORBIDDEN_MODULE_PREFIXES:
            assert not name.startswith(forbidden), (
                f"lowstate_replay.py must not import '{name}' (forbidden prefix '{forbidden}')"
            )


def test_replay_module_does_not_load_forbidden_modules_at_runtime() -> None:
    """Dynamic check: actually running the replay must not pull in SDK/DDS/ROS/network modules."""
    forbidden_runtime_modules = (
        "unitree_sdk2",
        "cyclonedds",
        "rclpy",
        "PyQt5",
        "PyQt6",
        "fastapi",
    )
    pre_existing = {m for m in forbidden_runtime_modules if m in sys.modules}

    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        list(src.iter_samples(rate=0))
    finally:
        src.close()

    newly_loaded = {
        m for m in forbidden_runtime_modules if m in sys.modules
    } - pre_existing
    assert not newly_loaded, f"Replay must not load: {newly_loaded}"


def test_cli_jsonl_output_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    from tools.offline_replay.lowstate_replay import main

    exit_code = main(["--fixture", str(FIXTURE_PATH), "--rate", "0", "--limit", "2", "--output", "jsonl"])
    assert exit_code == 0
    out_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(out_lines) == 2
    for line in out_lines:
        parsed = json.loads(line)
        assert parsed["topic"] == "rt/lowstate"


def test_cli_websocket_compatible_output_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    from tools.offline_replay.lowstate_replay import main

    exit_code = main(
        ["--fixture", str(FIXTURE_PATH), "--rate", "0", "--limit", "1", "--output", "websocket-compatible"]
    )
    assert exit_code == 0
    out_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(out_lines) == 1
    parsed = json.loads(out_lines[0])
    assert parsed["type"] == "lowstate_frame"
    assert parsed["index"] == 0
    assert "payload" in parsed


# --- MASTER-OFFLINE-R1-CORRECTION-R1: immutability and fail-closed validation ---


def test_top_level_dict_mutation_is_rejected() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(limit=1)))
        original_tick = snap.raw["tick"]
        with pytest.raises(TypeError):
            snap.raw["tick"] = -999
        assert snap.raw["tick"] == original_tick
        assert src.latest().raw["tick"] == original_tick
    finally:
        src.close()


def test_nested_motor_dict_mutation_is_rejected() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(limit=1)))
        original_q = snap.raw["motors"][0]["q_rad"]
        with pytest.raises(TypeError):
            snap.raw["motors"][0]["q_rad"] = 999.0
        assert snap.raw["motors"][0]["q_rad"] == original_q
    finally:
        src.close()


def test_nested_list_mutation_is_rejected() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(limit=1)))
        # arrays are converted to tuples, which have no mutating methods at all
        # (a stronger guarantee than a frozenlist-style TypeError-on-mutation type)
        assert isinstance(snap.raw["motors"], tuple)
        assert not hasattr(snap.raw["motors"], "append")
        with pytest.raises(TypeError):
            snap.raw["motors"][0] = {"index": 99}  # tuples reject item assignment
        assert isinstance(snap.raw["imu"]["quaternion"], tuple)
        with pytest.raises(TypeError):
            snap.raw["imu"]["quaternion"][0] = 0.0  # nested list -> tuple, also immutable
    finally:
        src.close()


def test_raw_is_deeply_frozen_types() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(limit=1)))
        assert isinstance(snap.raw, MappingProxyType)
        assert isinstance(snap.raw["imu"], MappingProxyType)
        assert isinstance(snap.raw["motors"], tuple)
        assert isinstance(snap.raw["motors"][0], MappingProxyType)
        assert isinstance(snap.raw["imu"]["quaternion"], tuple)
    finally:
        src.close()


def test_attempted_mutation_does_not_contaminate_later_replay() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(limit=1)))
        try:
            snap.raw["tick"] = -999
        except TypeError:
            pass
        try:
            snap.raw["motors"][0]["q_rad"] = 999.0
        except TypeError:
            pass
        # a fresh iteration over the same source must show unpoisoned data
        replayed = list(src.iter_samples(start_index=0, limit=1, rate=0))
        assert replayed[0].raw["tick"] != -999
        assert replayed[0].raw["motors"][0]["q_rad"] != 999.0
        assert src.latest().raw["tick"] != -999
    finally:
        src.close()


def test_fixture_file_on_disk_is_never_modified_by_mutation_attempts() -> None:
    before = FIXTURE_PATH.read_bytes()
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(limit=1)))
        try:
            snap.raw["tick"] = -999
        except TypeError:
            pass
    finally:
        src.close()
    after = FIXTURE_PATH.read_bytes()
    assert before == after


def test_negative_start_index_raises_value_error() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        with pytest.raises(ValueError):
            src.iter_samples(start_index=-1, limit=3)
    finally:
        src.close()


def test_start_index_equal_to_record_count_raises_value_error() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        with pytest.raises(ValueError):
            src.iter_samples(start_index=len(src), limit=3)
    finally:
        src.close()


def test_start_index_greater_than_record_count_raises_value_error() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        with pytest.raises(ValueError):
            src.iter_samples(start_index=len(src) + 50, limit=3)
    finally:
        src.close()


def test_negative_limit_raises_value_error() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        with pytest.raises(ValueError):
            src.iter_samples(start_index=0, limit=-5)
    finally:
        src.close()


def test_limit_zero_yields_no_samples_without_error() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        result = list(src.iter_samples(start_index=0, limit=0))
        assert result == []
    finally:
        src.close()


def test_invalid_rate_raises_value_error() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        with pytest.raises(ValueError):
            src.iter_samples(start_index=0, limit=2, rate=0.5)
        with pytest.raises(ValueError):
            src.iter_samples(start_index=0, limit=2, rate=2)
        with pytest.raises(ValueError):
            src.iter_samples(start_index=0, limit=2, rate=-1)
    finally:
        src.close()


def test_validation_raises_at_call_time_not_at_first_next() -> None:
    """iter_samples() is not itself a generator function: bad arguments must
    raise synchronously when called, before the caller ever iterates."""
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        with pytest.raises(ValueError):
            src.iter_samples(start_index=-1)  # must raise here, not on first next()
    finally:
        src.close()


def test_loop_with_out_of_bounds_start_index_raises_instead_of_hanging() -> None:
    """Regression test for the infinite-loop defect: start_index >= record_count
    combined with loop=True and no limit used to hang forever. It must now
    raise ValueError before any iteration begins."""
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        with pytest.raises(ValueError):
            src.iter_samples(start_index=len(src), rate=0, loop=True)
    finally:
        src.close()


def test_websocket_compatible_payload_is_json_serializable_plain_data() -> None:
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snap = next(iter(src.iter_samples(limit=1)))
    finally:
        src.close()
    envelope = snapshot_to_websocket_compatible(snap)
    assert isinstance(envelope["payload"], dict)
    assert isinstance(envelope["payload"]["motors"], list)
    # mutating the thawed payload is fine (it's a fresh copy) and never affects the snapshot
    envelope["payload"]["motors"][0]["q_rad"] = -1.0
    assert snap.raw["motors"][0]["q_rad"] != -1.0
    json.dumps(envelope)  # must not raise


def test_still_299_records_and_null_fields_preserved_after_correction() -> None:
    """Re-confirms the pre-correction contract still holds exactly."""
    src = LowStateSnapshotSource(FIXTURE_PATH)
    try:
        snaps = list(src.iter_samples(rate=0))
    finally:
        src.close()
    assert len(snaps) == 299
    for field in ("power_v", "power_a", "bms_state", "foot_force"):
        values = {s.raw.get(field) for s in snaps}
        assert values == {None}


def test_subprocess_invalid_loop_arguments_do_not_hang_the_cli() -> None:
    """End-to-end proof (not just in-process) that no invalid input can hang
    the process: invoke the CLI with the exact hang-triggering arguments from
    the pre-correction defect, under a hard subprocess timeout. The process
    must exit (non-zero, since the arguments are invalid) well within the
    timeout, never be killed by it.
    """
    fixture_arg = str(FIXTURE_PATH)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.offline_replay.lowstate_replay",
            "--fixture",
            fixture_arg,
            "--start-index",
            "299",  # == record_count: the exact pre-correction hang trigger
            "--rate",
            "0",
            "--loop",
            # deliberately no --limit
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
        timeout=10,  # generous; a hang would exceed this and raise TimeoutExpired
    )
    assert proc.returncode != 0
    combined_output = (proc.stdout or "") + (proc.stderr or "")
    assert "start_index" in combined_output
