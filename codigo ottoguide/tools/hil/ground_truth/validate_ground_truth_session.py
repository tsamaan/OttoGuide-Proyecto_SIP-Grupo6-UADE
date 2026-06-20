#!/usr/bin/env python3
"""Validate an offline ground-truth session and emit a deterministic JSON report."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path, PurePosixPath

PHASES = {"CALIBRATION", "DEVELOPMENT", "VALIDATION-SAME-ROUTE", "VALIDATION-DOMAIN-SHIFT"}
GT_LEVELS = {"GT-MIN", "GT-CONT"}
COMPARABILITY = {"COMPARABLE", "NOT_COMPARABLE", "PENDING_REVIEW"}
EVENT_TYPES = {"SESSION_START", "SESSION_END", "STATIONARY_START", "STATIONARY_END", "SEGMENT_START", "SEGMENT_END", "SYNC_MARKER", "GROUND_TRUTH_GAP_START", "GROUND_TRUTH_GAP_END"}
EXPECTED_STATES = {"STATIONARY", "TRANSLATING", "ROTATING", "COMBINED", "UNKNOWN"}
EVENT_COLUMNS = ["timestamp_ns", "relative_time_s", "event_id", "event_type", "segment_id", "expected_state", "expected_x_m", "expected_y_m", "expected_yaw_rad", "measurement_tolerance", "source", "notes"]
REQUIRED_MANIFEST = ["session_id", "created_at", "operator", "location", "robot_model", "lidar", "capture_mode", "ground_truth_level", "time_base", "rosbag_path", "events_csv", "external_video", "external_pose_file", "coordinate_frame", "measurement_units", "expected_segments", "calibration_files", "notes", "experiment_phase", "route_id", "motion_domain", "origin_marker_id", "initial_orientation_marker", "comparability_status", "reference_accuracy", "clock_sync_method"]
REQUIRED_DIRS = ["ground_truth", "raw", "external", "calibration", "reports", "notes"]
PAIR_TYPES = {"STATIONARY_START": "STATIONARY_END", "SEGMENT_START": "SEGMENT_END", "GROUND_TRUTH_GAP_START": "GROUND_TRUTH_GAP_END"}


def relative_reference(session: Path, value: str, field: str, errors: list[str]) -> None:
    if not value:
        return
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        errors.append(f"{field}: reference must be session-relative: {value}")
    elif not (session / Path(*path.parts)).exists():
        errors.append(f"{field}: referenced path does not exist: {value}")


def parse_number(row: dict, field: str, line: int, errors: list[str], integer: bool = False, optional: bool = False):
    raw = row.get(field, "").strip()
    if optional and raw == "":
        return None
    try:
        value = int(raw) if integer else float(raw)
        if not integer and not math.isfinite(value):
            raise ValueError
        return value
    except ValueError:
        errors.append(f"events line {line}: {field} has invalid numeric value {raw!r}")
        return None


def validate_events(path: Path, expected_segments: list, errors: list[str]) -> dict:
    stats = {"event_count": 0, "segment_count": 0}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != EVENT_COLUMNS:
                errors.append("events_csv: columns do not match the required contract")
                return stats
            rows = list(reader)
    except (OSError, UnicodeError) as exc:
        errors.append(f"events_csv: cannot read: {exc}")
        return stats
    stats["event_count"] = len(rows)
    ids: set[str] = set(); previous_ns = None; previous_rel = None
    open_pairs: dict[tuple[str, str], tuple[int, float]] = {}; segment_intervals = []; seen_segments = set()
    session_starts = session_ends = 0
    reverse = {end: start for start, end in PAIR_TYPES.items()}
    for line, row in enumerate(rows, 2):
        event_id = row["event_id"].strip(); event_type = row["event_type"].strip(); segment = row["segment_id"].strip(); state = row["expected_state"].strip()
        if not event_id: errors.append(f"events line {line}: event_id is required")
        elif event_id in ids: errors.append(f"events line {line}: duplicate event_id {event_id}")
        ids.add(event_id)
        if event_type not in EVENT_TYPES: errors.append(f"events line {line}: unknown event_type {event_type}")
        if state not in EXPECTED_STATES: errors.append(f"events line {line}: unknown expected_state {state}")
        if not row["source"].strip(): errors.append(f"events line {line}: source is required")
        if event_type not in {"SESSION_START", "SESSION_END", "SYNC_MARKER"} and not segment: errors.append(f"events line {line}: segment_id is required for {event_type}")
        ns = parse_number(row, "timestamp_ns", line, errors, integer=True); rel = parse_number(row, "relative_time_s", line, errors)
        for field in ("expected_x_m", "expected_y_m", "expected_yaw_rad"):
            parse_number(row, field, line, errors, optional=True)
        tolerance = parse_number(row, "measurement_tolerance", line, errors, optional=True)
        if tolerance is not None and tolerance < 0: errors.append(f"events line {line}: measurement_tolerance must be non-negative")
        if ns is not None and previous_ns is not None and ns <= previous_ns: errors.append(f"events line {line}: timestamp_ns is not strictly monotonic")
        if rel is not None and previous_rel is not None and rel < previous_rel: errors.append(f"events line {line}: relative_time_s is not monotonic")
        if ns is not None: previous_ns = ns
        if rel is not None: previous_rel = rel
        if event_type == "SESSION_START": session_starts += 1
        if event_type == "SESSION_END": session_ends += 1
        if event_type in PAIR_TYPES:
            key = (event_type, segment)
            if key in open_pairs: errors.append(f"events line {line}: overlapping {event_type} for segment {segment}")
            elif rel is not None: open_pairs[key] = (line, rel)
        elif event_type in reverse:
            start_type = reverse[event_type]; key = (start_type, segment)
            if key not in open_pairs: errors.append(f"events line {line}: {event_type} without {start_type} for segment {segment}")
            else:
                _, start_rel = open_pairs.pop(key)
                if rel is not None and event_type == "SEGMENT_END": segment_intervals.append((start_rel, rel, segment)); seen_segments.add(segment)
    if session_starts != 1: errors.append(f"events_csv: expected exactly one SESSION_START, found {session_starts}")
    if session_ends != 1: errors.append(f"events_csv: expected exactly one SESSION_END, found {session_ends}")
    if rows and rows[0]["event_type"] != "SESSION_START": errors.append("events_csv: first event must be SESSION_START")
    if rows and rows[-1]["event_type"] != "SESSION_END": errors.append("events_csv: last event must be SESSION_END")
    for (start_type, segment), (line, _) in sorted(open_pairs.items()): errors.append(f"events line {line}: {start_type} without {PAIR_TYPES[start_type]} for segment {segment}")
    for current, following in zip(sorted(segment_intervals), sorted(segment_intervals)[1:]):
        if following[0] < current[1]: errors.append(f"events_csv: segments overlap: {current[2]} and {following[2]}")
    missing = sorted(set(expected_segments) - seen_segments)
    if missing: errors.append(f"events_csv: expected_segments missing completed intervals: {', '.join(missing)}")
    stats["segment_count"] = len(seen_segments)
    return stats


def validate(session: Path) -> dict:
    errors: list[str] = []; warnings: list[str] = []
    for name in REQUIRED_DIRS:
        if not (session / name).is_dir(): errors.append(f"structure: missing directory {name}")
    manifest_path = session / "session_manifest.json"
    try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"manifest: cannot read valid JSON: {exc}"], "warnings": [], "stats": {}}
    for field in REQUIRED_MANIFEST:
        if field not in manifest: errors.append(f"manifest: missing required field {field}")
    if manifest.get("experiment_phase") not in PHASES: errors.append("manifest: invalid experiment_phase")
    if manifest.get("ground_truth_level") not in GT_LEVELS: errors.append("manifest: invalid ground_truth_level")
    if manifest.get("comparability_status") not in COMPARABILITY: errors.append("manifest: invalid comparability_status")
    units = manifest.get("measurement_units")
    if units != {"distance": "m", "angle": "rad", "time": "s", "timestamp": "ns"}: errors.append("manifest: measurement_units must be SI contract m/rad/s/ns")
    for field in ("session_id", "created_at", "operator", "location", "robot_model", "lidar", "capture_mode", "time_base", "events_csv", "coordinate_frame", "route_id", "motion_domain", "origin_marker_id", "initial_orientation_marker", "reference_accuracy", "clock_sync_method"):
        if field in manifest and (not isinstance(manifest[field], str) or not manifest[field].strip()): errors.append(f"manifest: {field} must be a non-empty string")
    if not isinstance(manifest.get("expected_segments"), list): errors.append("manifest: expected_segments must be a list")
    if not isinstance(manifest.get("calibration_files"), list): errors.append("manifest: calibration_files must be a list")
    for field in ("rosbag_path", "events_csv", "external_video", "external_pose_file"):
        value = manifest.get(field, "")
        if isinstance(value, str): relative_reference(session, value, field, errors)
        else: errors.append(f"manifest: {field} must be a string")
    for index, value in enumerate(manifest.get("calibration_files", []) if isinstance(manifest.get("calibration_files"), list) else []):
        if isinstance(value, str): relative_reference(session, value, f"calibration_files[{index}]", errors)
        else: errors.append(f"manifest: calibration_files[{index}] must be a string")
    events_value = manifest.get("events_csv", "")
    stats = validate_events(session / events_value, manifest.get("expected_segments", []), errors) if isinstance(events_value, str) and events_value else {}
    if manifest.get("ground_truth_level") == "GT-CONT" and not manifest.get("external_pose_file"): warnings.append("GT-CONT has no external_pose_file yet")
    return {"ok": not errors, "errors": sorted(errors), "warnings": sorted(warnings), "stats": stats}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("session_dir", type=Path); p.add_argument("--output", type=Path); args = p.parse_args()
    report = validate(args.session_dir); payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
