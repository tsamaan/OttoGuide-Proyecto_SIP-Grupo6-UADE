#!/usr/bin/env python3
"""Prepare a schema-1.0 ground-truth session without ROS, network, or robot access."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
TOOLING_VERSION = "1.1"
PHASES = ("CALIBRATION", "DEVELOPMENT", "VALIDATION-SAME-ROUTE", "VALIDATION-DOMAIN-SHIFT")
GT_LEVELS = ("GT-MIN", "GT-CONT")
COMPARABILITY = ("COMPARABLE", "NOT_COMPARABLE", "PENDING_REVIEW")
EVENT_COLUMNS = ("timestamp_ns", "relative_time_s", "event_id", "event_type", "segment_id", "expected_state", "expected_x_m", "expected_y_m", "expected_yaw_rad", "position_tolerance_m", "yaw_tolerance_rad", "time_tolerance_s", "source", "notes")
SESSION_DIRS = ("ground_truth", "raw", "external", "calibration", "reports", "notes")


def load_route_spec(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes(); spec = json.loads(raw.decode("utf-8"))
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"route spec schema_version must be {SCHEMA_VERSION}")
    if not isinstance(spec.get("route_id"), str) or not spec["route_id"].strip(): raise ValueError("route spec route_id is required")
    if not isinstance(spec.get("route_revision"), str) or not spec["route_revision"].strip(): raise ValueError("route spec route_revision is required")
    for field in ("coordinate_frame", "motion_domain", "origin_marker_id", "origin_reference", "distance_instrument", "angle_instrument"):
        if not isinstance(spec.get(field), str) or not spec[field].strip(): raise ValueError(f"route spec {field} is required")
    for field in ("distance_accuracy_m", "angle_accuracy_rad"):
        value=spec.get(field)
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<0: raise ValueError(f"route spec {field} must be finite and non-negative")
    if not isinstance(spec.get("segments"), list) or not spec["segments"]: raise ValueError("route spec segments are required")
    for segment in spec["segments"]:
        if not isinstance(segment,dict) or not isinstance(segment.get("segment_id"),str) or not segment["segment_id"].strip(): raise ValueError("every route segment requires segment_id")
    return spec, raw


def build_manifest(args: argparse.Namespace, route: dict, route_sha256: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "tooling_version": TOOLING_VERSION,
        "session_id": args.session_id, "created_at": args.created_at or datetime.now(timezone.utc).isoformat(),
        "operator": args.operator, "location": args.location, "robot_model": "Unitree G1 EDU 8", "lidar": "Livox MID360",
        "capture_mode": "OFFLINE_GROUND_TRUTH_PREPARATION", "ground_truth_level": args.ground_truth_level,
        "time_base": "RELATIVE_WITH_RECORDED_OFFSETS", "rosbag_path": "", "events_csv": "ground_truth/ground_truth_events.csv",
        "external_video": "", "external_pose_file": "", "coordinate_frame": route["coordinate_frame"],
        "hardware_inventory": "", "hardware_inventory_sha256": "", "hardware_inventory_id": "", "hardware_inventory_revision": "",
        "human_review": "", "human_review_sha256": "", "human_review_id": "", "human_review_revision": "",
        "measurement_units": {"distance": "m", "angle": "rad", "time": "s", "timestamp": "ns"},
        "expected_segments": [segment["segment_id"] for segment in route["segments"]], "calibration_files": ["calibration/route_spec.json"],
        "notes": "Prepared offline; no physical capture has been performed.", "experiment_phase": args.experiment_phase,
        "route_id": route["route_id"], "route_spec": "calibration/route_spec.json", "route_spec_sha256": route_sha256,
        "route_revision": route["route_revision"], "motion_domain": route["motion_domain"],
        "origin_marker_id": route["origin_marker_id"], "origin_reference": route["origin_reference"],
        "initial_orientation_marker": args.initial_orientation_marker, "comparability_status": args.comparability_status,
        "reference_accuracy": "PENDING_PHYSICAL_MEASUREMENT", "clock_sync_method": "PENDING_PROTOCOL_EXECUTION",
        "distance_instrument": route["distance_instrument"], "distance_accuracy_m": route["distance_accuracy_m"],
        "angle_instrument": route["angle_instrument"], "angle_accuracy_rad": route["angle_accuracy_rad"],
        "sync_method": args.sync_method, "sync_expected_accuracy_s": args.sync_expected_accuracy_s,
        "physical_readiness_status": "NOT_REVIEWED",
    }


def prepare(root: Path, args: argparse.Namespace) -> Path:
    if Path(args.session_id).name != args.session_id or args.session_id in {"", ".", ".."}: raise ValueError("session_id must be a single safe path component")
    if not math.isfinite(args.sync_expected_accuracy_s) or args.sync_expected_accuracy_s<0: raise ValueError("sync_expected_accuracy_s must be finite and non-negative")
    route, route_raw = load_route_spec(args.route_spec)
    target = root / args.session_id
    if target.exists():
        if not args.force: raise FileExistsError(f"session already exists: {target}")
        shutil.rmtree(target)
    for name in SESSION_DIRS: (target / name).mkdir(parents=True, exist_ok=True)
    route_copy = target / "calibration" / "route_spec.json"; route_copy.write_bytes(route_raw)
    digest = hashlib.sha256(route_raw).hexdigest()
    (target / "session_manifest.json").write_text(json.dumps(build_manifest(args, route, digest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (target / "ground_truth" / "ground_truth_events.csv").open("w", newline="", encoding="utf-8") as handle: csv.writer(handle).writerow(EVENT_COLUMNS)
    (target / "notes" / "README.txt").write_text("Record placement, deviations, instrument accuracies, sync evidence, and human review here.\n", encoding="utf-8")
    return target


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("session_root",type=Path); p.add_argument("--session-id",required=True); p.add_argument("--route-spec",type=Path,required=True)
    p.add_argument("--experiment-phase",choices=PHASES,required=True); p.add_argument("--ground-truth-level",choices=GT_LEVELS,default="GT-MIN"); p.add_argument("--comparability-status",choices=COMPARABILITY,default="PENDING_REVIEW")
    p.add_argument("--initial-orientation-marker",default="PENDING_HARDWARE_CONFIRMATION"); p.add_argument("--operator",default="OPERATOR_PLACEHOLDER"); p.add_argument("--location",default="LOCATION_PLACEHOLDER"); p.add_argument("--created-at")
    p.add_argument("--sync-method",default="VISIBLE_AND_RECORDED_SYNC_MARKERS"); p.add_argument("--sync-expected-accuracy-s",type=float,default=0.05); p.add_argument("--force",action="store_true"); return p


def main() -> int:
    args=parser().parse_args()
    try: target=prepare(args.session_root,args)
    except (FileExistsError,OSError,ValueError,json.JSONDecodeError) as exc: print(json.dumps({"ok":False,"error":str(exc)},sort_keys=True)); return 2
    print(json.dumps({"ok":True,"session_dir":str(target)},sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
