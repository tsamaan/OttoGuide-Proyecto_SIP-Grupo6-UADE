#!/usr/bin/env python3
"""Prepare an offline ground-truth session without ROS, network, or robot access."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

PHASES = ("CALIBRATION", "DEVELOPMENT", "VALIDATION-SAME-ROUTE", "VALIDATION-DOMAIN-SHIFT")
GT_LEVELS = ("GT-MIN", "GT-CONT")
COMPARABILITY = ("COMPARABLE", "NOT_COMPARABLE", "PENDING_REVIEW")
EVENT_COLUMNS = (
    "timestamp_ns", "relative_time_s", "event_id", "event_type", "segment_id",
    "expected_state", "expected_x_m", "expected_y_m", "expected_yaw_rad",
    "measurement_tolerance", "source", "notes",
)
SESSION_DIRS = ("ground_truth", "raw", "external", "calibration", "reports", "notes")


def build_manifest(args: argparse.Namespace) -> dict:
    return {
        "session_id": args.session_id,
        "created_at": args.created_at or datetime.now(timezone.utc).isoformat(),
        "operator": args.operator,
        "location": args.location,
        "robot_model": "Unitree G1 EDU 8",
        "lidar": "Livox MID360",
        "capture_mode": "OFFLINE_GROUND_TRUTH_PREPARATION",
        "ground_truth_level": args.ground_truth_level,
        "time_base": "RELATIVE_WITH_RECORDED_OFFSETS",
        "rosbag_path": "",
        "events_csv": "ground_truth/ground_truth_events.csv",
        "external_video": "",
        "external_pose_file": "",
        "coordinate_frame": "gt_world",
        "measurement_units": {"distance": "m", "angle": "rad", "time": "s", "timestamp": "ns"},
        "expected_segments": [],
        "calibration_files": [],
        "notes": "Prepared offline; no physical capture has been performed.",
        "experiment_phase": args.experiment_phase,
        "route_id": args.route_id,
        "motion_domain": args.motion_domain,
        "origin_marker_id": args.origin_marker_id,
        "initial_orientation_marker": args.initial_orientation_marker,
        "comparability_status": args.comparability_status,
        "reference_accuracy": "PENDING_PHYSICAL_MEASUREMENT",
        "clock_sync_method": "PENDING_PROTOCOL_EXECUTION",
    }


def prepare(root: Path, args: argparse.Namespace) -> Path:
    if Path(args.session_id).name != args.session_id or args.session_id in {"", ".", ".."}:
        raise ValueError("session_id must be a single safe path component")
    target = root / args.session_id
    if target.exists():
        if not args.force:
            raise FileExistsError(f"session already exists: {target}")
        shutil.rmtree(target)
    for name in SESSION_DIRS:
        (target / name).mkdir(parents=True, exist_ok=True)
    (target / "session_manifest.json").write_text(
        json.dumps(build_manifest(args), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (target / "ground_truth" / "ground_truth_events.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(EVENT_COLUMNS)
    (target / "notes" / "README.txt").write_text(
        "Record origin placement, deviations, instrument tolerances, and operator observations here.\n",
        encoding="utf-8",
    )
    return target


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session_root", type=Path)
    p.add_argument("--session-id", required=True)
    p.add_argument("--experiment-phase", choices=PHASES, required=True)
    p.add_argument("--ground-truth-level", choices=GT_LEVELS, default="GT-MIN")
    p.add_argument("--comparability-status", choices=COMPARABILITY, default="PENDING_REVIEW")
    p.add_argument("--route-id", required=True)
    p.add_argument("--motion-domain", required=True)
    p.add_argument("--origin-marker-id", default="PENDING_HARDWARE_CONFIRMATION")
    p.add_argument("--initial-orientation-marker", default="PENDING_HARDWARE_CONFIRMATION")
    p.add_argument("--operator", default="OPERATOR_PLACEHOLDER")
    p.add_argument("--location", default="LOCATION_PLACEHOLDER")
    p.add_argument("--created-at", help="ISO-8601 timestamp; useful for deterministic preparation")
    p.add_argument("--force", action="store_true", help="replace an existing session directory")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        target = prepare(args.session_root, args)
    except (FileExistsError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "session_dir": str(target)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
