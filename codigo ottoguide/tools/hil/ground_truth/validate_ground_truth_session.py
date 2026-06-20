#!/usr/bin/env python3
"""Validate sealed GT-MIN evidence and compute fail-safe physical readiness."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = "1.0"
PHASES = {"CALIBRATION", "DEVELOPMENT", "VALIDATION-SAME-ROUTE", "VALIDATION-DOMAIN-SHIFT"}
GT_LEVELS = {"GT-MIN", "GT-CONT"}
COMPARABILITY = {"COMPARABLE", "NOT_COMPARABLE", "PENDING_REVIEW"}
READINESS = {"NOT_REVIEWED", "NO_GO", "GO"}
INVENTORY_STATUS = {"NOT_REVIEWED", "REVIEWED_NO_GO", "REVIEWED_READY"}
REVIEW_DECISIONS = {"NO_GO", "GO"}
ORIGIN_STATUS = {"NOT_CHECKED", "IN_TOLERANCE", "OUT_OF_TOLERANCE"}
EVENT_TYPES = {"SESSION_START", "SESSION_END", "STATIONARY_START", "STATIONARY_END", "SEGMENT_START", "SEGMENT_END", "SYNC_MARKER", "GROUND_TRUTH_GAP_START", "GROUND_TRUTH_GAP_END"}
EXPECTED_STATES = {"STATIONARY", "TRANSLATING", "ROTATING", "COMBINED", "UNKNOWN"}
PLACEHOLDER_TOKENS = ("PENDING", "PLACEHOLDER", "EXAMPLE", "UNKNOWN", "TBD", "NOT_REVIEWED")
EVENT_COLUMNS = ["timestamp_ns", "relative_time_s", "event_id", "event_type", "segment_id", "expected_state", "expected_x_m", "expected_y_m", "expected_yaw_rad", "position_tolerance_m", "yaw_tolerance_rad", "time_tolerance_s", "source", "notes"]
REQUIRED_DIRS = ["ground_truth", "raw", "external", "calibration", "reports", "notes"]
PAIRS = {"STATIONARY_START": "STATIONARY_END", "SEGMENT_START": "SEGMENT_END", "GROUND_TRUTH_GAP_START": "GROUND_TRUTH_GAP_END"}
REQUIRED_MANIFEST = ["schema_version", "tooling_version", "session_id", "created_at", "operator", "location", "robot_model", "lidar", "capture_mode", "ground_truth_level", "time_base", "rosbag_path", "events_csv", "external_video", "external_pose_file", "coordinate_frame", "measurement_units", "expected_segments", "calibration_files", "notes", "experiment_phase", "route_id", "route_spec", "route_spec_sha256", "route_revision", "motion_domain", "origin_marker_id", "origin_reference", "initial_orientation_marker", "comparability_status", "reference_accuracy", "clock_sync_method", "distance_instrument", "distance_accuracy_m", "angle_instrument", "angle_accuracy_rad", "sync_method", "sync_expected_accuracy_s", "physical_readiness_status", "hardware_inventory", "hardware_inventory_sha256", "hardware_inventory_id", "hardware_inventory_revision", "human_review", "human_review_sha256", "human_review_id", "human_review_revision"]
REQUIRED_ROUTE = ["schema_version", "route_id", "route_revision", "title", "motion_domain", "coordinate_frame", "origin_marker_id", "origin_reference", "initial_yaw_rad", "origin_position_tolerance_m", "origin_yaw_tolerance_rad", "segments", "stationary_intervals", "measurement_method", "distance_instrument", "distance_accuracy_m", "angle_instrument", "angle_accuracy_rad", "approved_for_phase", "approved_by_role", "approval_date", "notes"]
REQUIRED_HARDWARE = ["schema_version", "inventory_id", "inventory_revision", "inventory_status", "reviewed_by_role", "reviewed_at", "location_scope", "valid_for_route_ids", "valid_until", "distance_instrument_available", "distance_instrument", "distance_accuracy_m", "angle_instrument_available", "angle_instrument", "angle_accuracy_rad", "floor_markers_available", "orientation_marker_available", "sync_marker_available", "sync_method", "sync_expected_accuracy_s", "external_camera_available", "camera_support_available", "fiducial_marker_available", "storage_confirmed", "supervised_area_confirmed", "safety_observer_confirmed", "notes"]
REQUIRED_REVIEW = ["schema_version", "review_id", "review_revision", "reviewed_at", "reviewed_by_role", "decision", "session_id", "route_id", "route_revision", "route_spec_sha256", "hardware_inventory_id", "hardware_inventory_revision", "hardware_inventory_sha256", "origin_placement_status", "origin_position_error_m", "origin_yaw_error_rad", "sync_plan_reviewed", "safety_protocol_reviewed", "movement_authorization_reference", "notes"]


def finite_nonnegative(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def placeholder(value):
    return not isinstance(value, str) or not value.strip() or any(token in value.upper() for token in PLACEHOLDER_TOKENS)


def is_valid_hash(value):
    return isinstance(value, str) and len(value) == 64 and not isinstance(value, bool) and all(c in "0123456789abcdef" for c in value)


def parse_iso(value, label, errors, required=True):
    if not isinstance(value, str) or not value.strip():
        if required: errors.append(f"{label}: timezone-aware ISO-8601 value required")
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        errors.append(f"{label}: invalid ISO-8601 value")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label}: timezone-aware ISO-8601 value required")
        return None
    return parsed


def load_json(path, label, errors):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label}: cannot read valid JSON: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append(f"{label}: root must be an object")
        return None
    return data


def resolve_ref(session, value, label, errors):
    if not isinstance(value, str):
        errors.append(f"manifest: {label} must be a string")
        return None
    if not value:
        return None
    ref = PurePosixPath(value)
    if ref.is_absolute() or ".." in ref.parts:
        errors.append(f"{label}: reference must be session-relative")
        return None
    path = session / Path(*ref.parts)
    if not path.is_file():
        errors.append(f"{label}: referenced file does not exist: {value}")
        return None
    return path


def verify_hash(path, expected, label, errors, evidence):
    if path is None:
        return None
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence[label] = actual
    if not isinstance(expected, str) or actual != expected:
        errors.append(f"manifest: {label} SHA-256 mismatch")
    return actual


def validate_route(route, errors):
    if route is None:
        return {}

    # Validar strings no vacíos
    route_strings = [
        "schema_version", "route_id", "route_revision", "title", "motion_domain",
        "coordinate_frame", "origin_marker_id", "origin_reference", "measurement_method",
        "distance_instrument", "angle_instrument", "approved_by_role", "notes"
    ]
    for field in route_strings:
        if field not in route:
            errors.append(f"route_spec: missing required field {field}")
        else:
            val = route.get(field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"route_spec: {field} must be a non-empty string")

    if route.get("schema_version") != SCHEMA_VERSION:
        errors.append("route_spec: unsupported schema_version")

    # Validar números
    number_fields = [
        "initial_yaw_rad", "origin_position_tolerance_m", "origin_yaw_tolerance_rad",
        "distance_accuracy_m", "angle_accuracy_rad"
    ]
    for field in number_fields:
        if field not in route:
            errors.append(f"route_spec: missing number field {field}")
        else:
            val = route.get(field)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                errors.append(f"route_spec: {field} must be a finite number")
            elif field != "initial_yaw_rad" and val < 0:
                errors.append(f"route_spec: {field} must be non-negative")

    # approved_for_phase
    if "approved_for_phase" not in route:
        errors.append("route_spec: missing approved_for_phase")
    else:
        approved = route.get("approved_for_phase")
        if not isinstance(approved, list):
            errors.append("route_spec: approved_for_phase must be a list")
        else:
            for item in approved:
                if item not in PHASES:
                    errors.append(f"route_spec: approved_for_phase contains invalid phase {item}")
            if len(approved) != len(set(approved)):
                errors.append("route_spec: approved_for_phase contains duplicate phases")

    # approval_date
    if "approval_date" not in route:
        errors.append("route_spec: missing approval_date")
    else:
        app_date = route.get("approval_date")
        if not isinstance(app_date, str):
            errors.append("route_spec: approval_date must be a string")
        elif app_date.strip():
            try:
                # format YYYY-MM-DD
                parsed_date = datetime.strptime(app_date, "%Y-%m-%d").date()
                now_date = datetime.now(timezone.utc).date()
                if parsed_date > now_date:
                    errors.append("route_spec: approval_date cannot be in the future")
            except ValueError:
                errors.append("route_spec: approval_date must be in YYYY-MM-DD format")

    # Segments
    route_segments = {}
    segment_ids = set()
    orders = []

    if "segments" not in route:
        errors.append("route_spec: missing segments")
    else:
        segments = route.get("segments")
        if not isinstance(segments, list) or not segments:
            errors.append("route_spec: segments must be a non-empty list")
        else:
            for index, segment in enumerate(segments):
                if not isinstance(segment, dict):
                    errors.append(f"route_spec: segments[{index}] must be an object")
                    continue

                # Cada segmento debe contener:
                seg_fields = [
                    "segment_id", "order", "expected_state", "start_marker", "end_marker",
                    "expected_distance_m", "expected_yaw_change_rad", "position_tolerance_m",
                    "yaw_tolerance_rad", "minimum_duration_s", "notes"
                ]
                for field in seg_fields:
                    if field not in segment:
                        errors.append(f"route_spec: segments[{index}] missing {field}")

                sid = segment.get("segment_id")
                if not isinstance(sid, str) or not sid.strip():
                    errors.append(f"route_spec: segments[{index}] segment_id must be a non-empty string")
                else:
                    if sid in segment_ids:
                        errors.append(f"route_spec: duplicate segment_id {sid}")
                    segment_ids.add(sid)
                    route_segments[sid] = segment

                order = segment.get("order")
                if not isinstance(order, int) or isinstance(order, bool):
                    errors.append(f"route_spec: segments[{index}] order must be an integer")
                else:
                    orders.append(order)

                # expected_state conocido (not UNKNOWN)
                state = segment.get("expected_state")
                if state not in EXPECTED_STATES - {"UNKNOWN"}:
                    errors.append(f"route_spec: segment {sid} expected_state must be a known state (STATIONARY, TRANSLATING, ROTATING, COMBINED)")

                # start_marker, end_marker
                for marker_field in ("start_marker", "end_marker"):
                    marker = segment.get(marker_field)
                    if not isinstance(marker, str) or not marker.strip():
                        errors.append(f"route_spec: segment {sid} {marker_field} must be a non-empty string")

                # expected_distance_m, expected_yaw_change_rad
                dist = segment.get("expected_distance_m")
                if not finite_nonnegative(dist):
                    errors.append(f"route_spec: segment {sid} expected_distance_m must be finite and non-negative")

                yaw = segment.get("expected_yaw_change_rad")
                if not isinstance(yaw, (int, float)) or isinstance(yaw, bool) or not math.isfinite(yaw):
                    errors.append(f"route_spec: segment {sid} expected_yaw_change_rad must be a finite number")

                # position_tolerance_m, yaw_tolerance_rad, minimum_duration_s
                for tol_field in ("position_tolerance_m", "yaw_tolerance_rad", "minimum_duration_s"):
                    val = segment.get(tol_field)
                    if not finite_nonnegative(val):
                        errors.append(f"route_spec: segment {sid} {tol_field} must be finite and non-negative")

            # Orders contiguos desde 1
            if orders:
                orders_sorted = sorted(orders)
                if orders_sorted != list(range(1, len(orders) + 1)):
                    errors.append(f"route_spec: segment orders must be contiguous starting from 1, got {orders_sorted}")

    # stationary_intervals
    if "stationary_intervals" not in route:
        errors.append("route_spec: missing stationary_intervals")
    else:
        intervals = route.get("stationary_intervals")
        if not isinstance(intervals, list):
            errors.append("route_spec: stationary_intervals must be a list")
        else:
            seen_interval_sids = set()
            for index, interval in enumerate(intervals):
                if not isinstance(interval, dict):
                    errors.append(f"route_spec: stationary_intervals[{index}] must be an object")
                    continue
                if "segment_id" not in interval or "minimum_duration_s" not in interval:
                    errors.append(f"route_spec: stationary_intervals[{index}] missing required fields")
                    continue
                sid = interval.get("segment_id")
                dur = interval.get("minimum_duration_s")

                if not isinstance(sid, str) or not sid.strip():
                    errors.append(f"route_spec: stationary_intervals[{index}] segment_id must be a non-empty string")
                    continue

                if sid not in segment_ids:
                    errors.append(f"route_spec: stationary_interval segment_id {sid} does not exist in segments")
                    continue

                if sid in seen_interval_sids:
                    errors.append(f"route_spec: duplicate stationary_interval for segment_id {sid}")
                seen_interval_sids.add(sid)

                seg = route_segments.get(sid)
                if seg and seg.get("expected_state") != "STATIONARY":
                    errors.append(f"route_spec: stationary_interval references non-STATIONARY segment {sid}")

                if not finite_nonnegative(dur):
                    errors.append(f"route_spec: stationary_interval for segment {sid} has invalid minimum_duration_s")
                elif seg and dur > seg.get("minimum_duration_s", 0.0):
                    errors.append(f"route_spec: stationary_interval duration {dur} exceeds segment duration {seg.get('minimum_duration_s')}")

    return route_segments


def event_number(row, field, line, errors, integer=False, optional=False):
    raw = row.get(field, "").strip()
    if optional and raw == "": return None
    try: value = int(raw) if integer else float(raw)
    except ValueError: errors.append(f"events line {line}: {field} invalid"); return None
    if not integer and not math.isfinite(value): errors.append(f"events line {line}: {field} must be finite"); return None
    return value


def validate_events(path, expected_segments, route_segments, errors):
    summary = {"count": 0, "initial_present": False, "final_present": False, "max_tolerance_s": None, "sources": []}
    stats = {"event_count": 0, "segment_count": 0}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle); fields = reader.fieldnames; rows = list(reader)
    except (OSError, UnicodeError) as exc:
        errors.append(f"events_csv: cannot read: {exc}"); return stats, summary
    if fields != EVENT_COLUMNS:
        errors.append("events_csv: columns do not match schema 1.0"); return stats, summary
    stats["event_count"] = len(rows); ids = set(); prev_ns = prev_rel = None; opens = {}; completed = {}; intervals = []; reverse = {v: k for k, v in PAIRS.items()}; starts = ends = 0
    parsed = []
    for line, row in enumerate(rows, 2):
        eid=row["event_id"].strip(); typ=row["event_type"].strip(); sid=row["segment_id"].strip(); state=row["expected_state"].strip(); source=row["source"].strip()
        if not eid: errors.append(f"events line {line}: event_id required")
        elif eid in ids: errors.append(f"events line {line}: duplicate event_id {eid}")
        ids.add(eid)
        if typ not in EVENT_TYPES: errors.append(f"events line {line}: unknown event_type {typ}")
        if state not in EXPECTED_STATES: errors.append(f"events line {line}: unknown expected_state {state}")
        if not source: errors.append(f"events line {line}: source required")
        if typ not in {"SESSION_START", "SESSION_END", "SYNC_MARKER"} and not sid: errors.append(f"events line {line}: segment_id required")
        ns=event_number(row,"timestamp_ns",line,errors,integer=True); rel=event_number(row,"relative_time_s",line,errors)
        pose={f:event_number(row,f,line,errors,optional=True) for f in ("expected_x_m","expected_y_m","expected_yaw_rad")}
        tol={f:event_number(row,f,line,errors,optional=True) for f in ("position_tolerance_m","yaw_tolerance_rad","time_tolerance_s")}
        for field,value in tol.items():
            if value is not None and value < 0: errors.append(f"events line {line}: {field} must be non-negative")
        if (pose["expected_x_m"] is not None or pose["expected_y_m"] is not None) and tol["position_tolerance_m"] is None: errors.append(f"events line {line}: expected position requires position_tolerance_m")
        if pose["expected_yaw_rad"] is not None and tol["yaw_tolerance_rad"] is None: errors.append(f"events line {line}: expected yaw requires yaw_tolerance_rad")
        if typ == "SYNC_MARKER" and tol["time_tolerance_s"] is None: errors.append(f"events line {line}: SYNC_MARKER requires time_tolerance_s")
        if ns is not None and prev_ns is not None and ns <= prev_ns: errors.append(f"events line {line}: timestamp_ns not strictly monotonic")
        if rel is not None and prev_rel is not None and rel < prev_rel: errors.append(f"events line {line}: relative_time_s not monotonic")
        if ns is not None: prev_ns=ns
        if rel is not None: prev_rel=rel
        parsed.append({"type":typ,"id":eid,"source":source,"time_tolerance":tol["time_tolerance_s"]})
        if typ == "SESSION_START": starts += 1
        if typ == "SESSION_END": ends += 1
        if typ in PAIRS:
            key=(typ,sid)
            if key in opens: errors.append(f"events line {line}: overlapping {typ} for {sid}")
            elif rel is not None: opens[key]=(line,rel)
        elif typ in reverse:
            key=(reverse[typ],sid)
            if key not in opens: errors.append(f"events line {line}: {typ} without {reverse[typ]} for {sid}")
            else:
                _,begin=opens.pop(key)
                if typ == "SEGMENT_END" and rel is not None:
                    completed[sid]=completed.get(sid,0)+1; intervals.append((begin,rel,sid))
                    if sid in route_segments and rel-begin < route_segments[sid]["minimum_duration_s"]: errors.append(f"events line {line}: segment {sid} shorter than route minimum")
        if typ == "SEGMENT_START" and sid in route_segments and state != route_segments[sid]["expected_state"]: errors.append(f"events line {line}: {sid} state differs from route")
    if starts != 1: errors.append(f"events_csv: expected one SESSION_START, found {starts}")
    if ends != 1: errors.append(f"events_csv: expected one SESSION_END, found {ends}")
    if rows and rows[0]["event_type"] != "SESSION_START": errors.append("events_csv: first event must be SESSION_START")
    if rows and rows[-1]["event_type"] != "SESSION_END": errors.append("events_csv: last event must be SESSION_END")
    for (typ,sid),(line,_) in sorted(opens.items()): errors.append(f"events line {line}: {typ} without {PAIRS[typ]} for {sid}")
    for first,second in zip(sorted(intervals),sorted(intervals)[1:]):
        if second[0] < first[1]: errors.append(f"events_csv: segments overlap: {first[2]} and {second[2]}")
    declared=set(expected_segments)
    for sid in sorted(declared):
        if completed.get(sid,0) != 1: errors.append(f"events_csv: segment {sid} must complete exactly once, found {completed.get(sid,0)}")
    for sid in sorted(set(completed)-declared): errors.append(f"events_csv: completed undeclared segment {sid}")
    stats["segment_count"] = sum(count == 1 for count in completed.values())
    segment_starts=[i for i,e in enumerate(parsed) if e["type"]=="SEGMENT_START"]; segment_ends=[i for i,e in enumerate(parsed) if e["type"]=="SEGMENT_END"]
    syncs=[(i,e) for i,e in enumerate(parsed) if e["type"]=="SYNC_MARKER"]
    summary["count"]=len(syncs); summary["sources"]=[e["source"] for _,e in syncs]
    tolerances=[e["time_tolerance"] for _,e in syncs if e["time_tolerance"] is not None]; summary["max_tolerance_s"]=max(tolerances) if tolerances else None
    if segment_starts: summary["initial_present"]=any(0 < i < min(segment_starts) for i,_ in syncs)
    if segment_ends: summary["final_present"]=any(max(segment_ends) < i < len(parsed)-1 for i,_ in syncs)
    return stats, summary


def validate_inventory(data, errors):
    if data is None:
        return

    for field in REQUIRED_HARDWARE:
        if field not in data:
            errors.append(f"hardware_inventory: missing field {field}")

    # Validar strings no vacíos
    inv_strings = ["schema_version", "inventory_id", "inventory_revision", "inventory_status", "location_scope", "notes"]
    for field in inv_strings:
        if field in data:
            val = data.get(field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"hardware_inventory: {field} must be a non-empty string")

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("hardware_inventory: unsupported schema_version")

    status = data.get("inventory_status")
    if status not in INVENTORY_STATUS:
        errors.append("hardware_inventory: invalid inventory_status")

    # Check boolean fields
    bool_fields = [
        "distance_instrument_available", "angle_instrument_available", "floor_markers_available",
        "orientation_marker_available", "sync_marker_available", "external_camera_available",
        "camera_support_available", "fiducial_marker_available", "storage_confirmed",
        "supervised_area_confirmed", "safety_observer_confirmed"
    ]
    for field in bool_fields:
        if field in data:
            val = data.get(field)
            if not isinstance(val, bool):
                errors.append(f"hardware_inventory: {field} must be boolean")

    # Instrument and sync details
    if data.get("distance_instrument_available") is True:
        dist_inst = data.get("distance_instrument")
        if not isinstance(dist_inst, str) or not dist_inst.strip():
            errors.append("hardware_inventory: distance_instrument must be a non-empty string when distance_instrument_available is true")
        if not finite_nonnegative(data.get("distance_accuracy_m")):
            errors.append("hardware_inventory: distance_accuracy_m must be finite and non-negative when distance_instrument_available is true")

    if data.get("angle_instrument_available") is True:
        ang_inst = data.get("angle_instrument")
        if not isinstance(ang_inst, str) or not ang_inst.strip():
            errors.append("hardware_inventory: angle_instrument must be a non-empty string when angle_instrument_available is true")
        if not finite_nonnegative(data.get("angle_accuracy_rad")):
            errors.append("hardware_inventory: angle_accuracy_rad must be finite and non-negative when angle_instrument_available is true")

    if data.get("sync_marker_available") is True:
        sync_m = data.get("sync_method")
        if not isinstance(sync_m, str) or not sync_m.strip():
            errors.append("hardware_inventory: sync_method must be a non-empty string when sync_marker_available is true")
        if not finite_nonnegative(data.get("sync_expected_accuracy_s")):
            errors.append("hardware_inventory: sync_expected_accuracy_s must be finite and non-negative when sync_marker_available is true")

    # Review checks
    if status != "NOT_REVIEWED":
        # reviewed_by_role obligatorio
        rev_by = data.get("reviewed_by_role")
        if not isinstance(rev_by, str) or not rev_by.strip():
            errors.append("hardware_inventory: reviewed_by_role is required when status is reviewed")

        # reviewed_at obligatorio, timezone-aware, no futuro
        rev_at_str = data.get("reviewed_at")
        rev_at = parse_iso(rev_at_str, "hardware_inventory: reviewed_at", errors, required=True)
        if rev_at:
            if rev_at > datetime.now(timezone.utc):
                errors.append("hardware_inventory: reviewed_at cannot be in the future")

    if status == "REVIEWED_READY":
        # valid_until obligatorio, timezone-aware, posterior a reviewed_at
        valid_until_str = data.get("valid_until")
        valid_until = parse_iso(valid_until_str, "hardware_inventory: valid_until", errors, required=True)

        # We need reviewed_at parsed to check ordering
        rev_at_str = data.get("reviewed_at")
        rev_at = parse_iso(rev_at_str, "hardware_inventory: reviewed_at", [], required=False)

        if valid_until and rev_at:
            if valid_until <= rev_at:
                errors.append("hardware_inventory: valid_until must be posterior to reviewed_at")

        # valid_for_route_ids no vacío, sin duplicados
        valid_routes = data.get("valid_for_route_ids")
        if not isinstance(valid_routes, list) or not valid_routes:
            errors.append("hardware_inventory: valid_for_route_ids must be a non-empty list when status is REVIEWED_READY")
        else:
            for idx, rid in enumerate(valid_routes):
                if not isinstance(rid, str) or not rid.strip():
                    errors.append(f"hardware_inventory: valid_for_route_ids[{idx}] must be a non-empty string")
            if len(valid_routes) != len(set(valid_routes)):
                errors.append("hardware_inventory: valid_for_route_ids contains duplicate IDs")


def validate_review(data, errors):
    if data is None:
        return

    for field in REQUIRED_REVIEW:
        if field not in data:
            errors.append(f"human_review: missing field {field}")

    # Validar strings no vacíos
    rev_strings = [
        "schema_version", "review_id", "review_revision", "decision", "session_id",
        "route_id", "route_revision", "route_spec_sha256", "hardware_inventory_id",
        "hardware_inventory_revision", "hardware_inventory_sha256", "origin_placement_status",
        "reviewed_by_role", "notes"
    ]
    for field in rev_strings:
        if field in data:
            val = data.get(field)
            if not isinstance(val, str):
                errors.append(f"human_review: {field} must be a string")
            elif field != "notes" and not val.strip():
                errors.append(f"human_review: {field} must be a non-empty string")

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("human_review: unsupported schema_version")

    dec = data.get("decision")
    if dec not in REVIEW_DECISIONS:
        errors.append("human_review: invalid decision")

    # Validar hashes
    for field in ("route_spec_sha256", "hardware_inventory_sha256"):
        if field in data:
            val = data.get(field)
            if isinstance(val, str) and val.strip():
                if dec == "GO":
                    if not is_valid_hash(val):
                        errors.append(f"human_review: {field} must be a valid 64-character lowercase hexadecimal hash when decision is GO")
                else:
                    if not placeholder(val) and not is_valid_hash(val):
                        errors.append(f"human_review: {field} must be a valid 64-character lowercase hexadecimal hash or a placeholder when decision is NO_GO")

    # Check boolean flags
    for field in ("sync_plan_reviewed", "safety_protocol_reviewed"):
        if field in data:
            val = data.get(field)
            if not isinstance(val, bool):
                errors.append(f"human_review: {field} must be boolean")

    if dec == "GO":
        # reviewed_at obligatorio, timezone-aware, no futuro
        rev_at_str = data.get("reviewed_at")
        rev_at = parse_iso(rev_at_str, "human_review: reviewed_at", errors, required=True)
        if rev_at:
            if rev_at > datetime.now(timezone.utc):
                errors.append("human_review: reviewed_at cannot be in the future")

        # movement_authorization_reference obligatorio, sin placeholders
        auth = data.get("movement_authorization_reference")
        if not isinstance(auth, str) or not auth.strip():
            errors.append("human_review: movement_authorization_reference is required when decision is GO")

        # sync_plan_reviewed y safety_protocol_reviewed bool
        # origin_placement_status in ORIGIN_STATUS

        # errors de origen finitos y no negativos
        for field in ("origin_position_error_m", "origin_yaw_error_rad"):
            if not finite_nonnegative(data.get(field)):
                errors.append(f"human_review: {field} must be finite and non-negative when decision is GO")

    elif dec == "NO_GO":
        # reviewed_at vacío o timezone-aware no futuro
        rev_at_str = data.get("reviewed_at")
        if isinstance(rev_at_str, str) and rev_at_str.strip():
            rev_at = parse_iso(rev_at_str, "human_review: reviewed_at", errors, required=False)
            if rev_at and rev_at > datetime.now(timezone.utc):
                errors.append("human_review: reviewed_at cannot be in the future")

        # errors de origen null o finitos no negativos
        for field in ("origin_position_error_m", "origin_yaw_error_rad"):
            val = data.get(field)
            if val is not None and not finite_nonnegative(val):
                errors.append(f"human_review: {field} must be null or finite and non-negative when decision is NO_GO")


def same(a,b):
    if isinstance(a,(int,float)) and isinstance(b,(int,float)): return math.isclose(a,b,rel_tol=0,abs_tol=1e-12)
    return a == b


def validate(session):
    errors = []
    warnings = []
    blockers = []
    evidence = {}
    stats = {}
    sync_summary = {"count": 0, "initial_present": False, "final_present": False, "max_tolerance_s": None, "sources": []}
    origin_summary = {}
    review_summary = {}

    for directory in REQUIRED_DIRS:
        if not (session / directory).is_dir():
            errors.append(f"structure: missing directory {directory}")

    manifest = load_json(session / "session_manifest.json", "manifest", errors)
    if manifest is None:
        return {
            "ok": False,
            "physical_ready": False,
            "decision": "INVALID",
            "errors": sorted(errors),
            "warnings": [],
            "blocking_reasons": ["STRUCTURAL_CONTRACT_INVALID"],
            "evidence_hashes": {},
            "sync_summary": sync_summary,
            "origin_summary": {},
            "review_summary": {},
            "stats": {}
        }

    # 1. Manifest field validations (Section 11)
    required_manifest_strings = [
        "schema_version", "tooling_version", "session_id", "created_at",
        "operator", "location", "robot_model", "lidar", "capture_mode",
        "ground_truth_level", "time_base", "events_csv", "coordinate_frame",
        "notes", "experiment_phase", "route_id", "route_spec", "route_spec_sha256",
        "route_revision", "motion_domain", "origin_marker_id", "origin_reference",
        "initial_orientation_marker", "comparability_status", "reference_accuracy",
        "clock_sync_method", "distance_instrument", "angle_instrument", "sync_method",
        "physical_readiness_status"
    ]
    for field in required_manifest_strings:
        if field not in manifest:
            errors.append(f"manifest: missing required field {field}")
        else:
            val = manifest.get(field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"manifest: {field} must be a non-empty string")

    # Optional paths
    optional_paths = ["rosbag_path", "external_video", "external_pose_file"]
    for field in optional_paths:
        if field not in manifest:
            errors.append(f"manifest: missing field {field}")
        else:
            val = manifest.get(field)
            if not isinstance(val, str):
                errors.append(f"manifest: {field} must be a string")
            elif val.strip():
                ref = PurePosixPath(val)
                if ref.is_absolute() or ".." in ref.parts:
                    errors.append(f"manifest: {field} must be session-relative")
                else:
                    path = session / Path(*ref.parts)
                    if not path.is_file():
                        errors.append(f"manifest: {field} referenced file does not exist: {val}")

    manifest_hw = manifest.get("hardware_inventory")
    manifest_rev = manifest.get("human_review")
    has_sealed = False
    if (isinstance(manifest_hw, str) and manifest_hw.strip()) or (isinstance(manifest_rev, str) and manifest_rev.strip()):
        has_sealed = True

    if has_sealed:
        sealed_strings = [
            "hardware_inventory", "hardware_inventory_sha256", "hardware_inventory_id", "hardware_inventory_revision",
            "human_review", "human_review_sha256", "human_review_id", "human_review_revision"
        ]
        for field in sealed_strings:
            if field not in manifest:
                errors.append(f"manifest: missing required sealed field {field}")
            else:
                val = manifest.get(field)
                if not isinstance(val, str) or not val.strip():
                    errors.append(f"manifest: {field} must be a non-empty string when sealed evidence is present")

        if (manifest_hw and not manifest_rev) or (manifest_rev and not manifest_hw):
            errors.append("manifest: sealed evidence must be complete (both hardware_inventory and human_review must be present)")

    # Hashes validation
    for field in ("route_spec_sha256", "hardware_inventory_sha256", "human_review_sha256"):
        if field in manifest:
            val = manifest.get(field)
            if isinstance(val, str) and val.strip():
                if not is_valid_hash(val):
                    errors.append(f"manifest: {field} must be a valid 64-character lowercase hexadecimal hash")

    # Units validation
    expected_units = {
        "distance": "m",
        "angle": "rad",
        "time": "s",
        "timestamp": "ns"
    }
    if "measurement_units" not in manifest:
        errors.append("manifest: missing measurement_units")
    elif manifest.get("measurement_units") != expected_units:
        errors.append("manifest: measurement_units must be exactly the expected schema")

    # expected_segments
    if "expected_segments" not in manifest:
        errors.append("manifest: missing expected_segments")
    else:
        expected = manifest.get("expected_segments")
        if not isinstance(expected, list):
            errors.append("manifest: expected_segments must be a list")
        else:
            for idx, item in enumerate(expected):
                if not isinstance(item, str) or not item.strip():
                    errors.append(f"manifest: expected_segments[{idx}] must be a non-empty string")
            if len(expected) != len(set(expected)):
                errors.append("manifest: expected_segments contains duplicate segments")

    # calibration_files
    if "calibration_files" not in manifest:
        errors.append("manifest: missing calibration_files")
    else:
        cal_files = manifest.get("calibration_files")
        if not isinstance(cal_files, list):
            errors.append("manifest: calibration_files must be a list")
        else:
            for idx, item in enumerate(cal_files):
                if not isinstance(item, str) or not item.strip():
                    errors.append(f"manifest: calibration_files[{idx}] must be a non-empty string")
                else:
                    ref = PurePosixPath(item)
                    if ref.is_absolute() or ".." in ref.parts:
                        errors.append(f"manifest: calibration_files[{idx}] reference must be session-relative")
                    else:
                        path = session / Path(*ref.parts)
                        if not path.is_file():
                            errors.append(f"manifest: calibration_files[{idx}] referenced file does not exist: {item}")
            if len(cal_files) != len(set(cal_files)):
                errors.append("manifest: calibration_files contains duplicate files")

            # must include route spec
            route_spec_path_str = manifest.get("route_spec")
            if isinstance(route_spec_path_str, str) and route_spec_path_str:
                if route_spec_path_str not in cal_files:
                    errors.append("manifest: calibration_files must include route_spec")

            # if sealed, must include inventory and review
            if has_sealed:
                hw_path_str = manifest.get("hardware_inventory")
                if isinstance(hw_path_str, str) and hw_path_str:
                    if hw_path_str not in cal_files:
                        errors.append("manifest: calibration_files must include hardware_inventory")
                rev_path_str = manifest.get("human_review")
                if isinstance(rev_path_str, str) and rev_path_str:
                    if rev_path_str not in cal_files:
                        errors.append("manifest: calibration_files must include human_review")

    # Check schema_version & session_id matches name
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("manifest: unsupported schema_version")
    if manifest.get("session_id") != session.name:
        errors.append("manifest: session_id must equal directory name")

    # Dates
    parse_iso(manifest.get("created_at"), "manifest: created_at", errors)
    if manifest.get("experiment_phase") not in PHASES:
        errors.append("manifest: invalid experiment_phase")
    if manifest.get("ground_truth_level") not in GT_LEVELS:
        errors.append("manifest: invalid ground_truth_level")
    if manifest.get("comparability_status") not in COMPARABILITY:
        errors.append("manifest: invalid comparability_status")
    if manifest.get("physical_readiness_status") not in READINESS:
        errors.append("manifest: invalid physical_readiness_status")

    # Numeros
    for field in ("distance_accuracy_m", "angle_accuracy_rad", "sync_expected_accuracy_s"):
        if not finite_nonnegative(manifest.get(field)):
            errors.append(f"manifest: {field} invalid")

    # Partial State / Residues (Section 16)
    hw_file = session / "calibration" / "hardware_inventory.json"
    rev_file = session / "calibration" / "human_review.json"

    if hw_file.is_file() and not manifest_hw:
        warnings.append("partial_state: hardware inventory file present but not referenced in manifest")
        blockers.append("UNREFERENCED_HARDWARE_INVENTORY_PRESENT")

    if rev_file.is_file() and not manifest_rev:
        warnings.append("partial_state: human review file present but not referenced in manifest")
        blockers.append("UNREFERENCED_HUMAN_REVIEW_PRESENT")

    # Hash empty but file present
    if manifest_hw and not manifest.get("hardware_inventory_sha256"):
        errors.append("manifest: hardware_inventory is referenced but hardware_inventory_sha256 is empty")
    if manifest_rev and not manifest.get("human_review_sha256"):
        errors.append("manifest: human_review is referenced but human_review_sha256 is empty")
    if manifest.get("route_spec") and not manifest.get("route_spec_sha256"):
        errors.append("manifest: route_spec is referenced but route_spec_sha256 is empty")

    # Scan for temporary or backup files
    tmp_files = []
    bak_files = []
    # Using glob pattern to look for files starting with '.' and containing tooling identifiers
    if session.is_dir():
        for p in session.rglob("*"):
            if p.is_file():
                if p.name.startswith(".") and (p.name.endswith(".tmp") or p.name.endswith(".bak") or p.name.endswith(".backup")):
                    if (".hardware_inventory.json." in p.name or
                        ".human_review.json." in p.name or
                        ".session_manifest.json." in p.name or
                        ".route_spec.json." in p.name):
                        if p.name.endswith(".tmp"):
                            tmp_files.append(p)
                        else:
                            bak_files.append(p)

    if tmp_files:
        warnings.append(f"partial_state: tooling temporary files found: {[f.name for f in tmp_files]}")
        blockers.append("TOOLING_TEMPORARY_FILES_PRESENT")
    if bak_files:
        warnings.append(f"partial_state: tooling backup files found: {[f.name for f in bak_files]}")
        blockers.append("TOOLING_BACKUP_FILES_PRESENT")

    # Load and validate route spec
    route_path = resolve_ref(session, manifest.get("route_spec"), "route_spec", errors)
    verify_hash(route_path, manifest.get("route_spec_sha256"), "route_spec", errors, evidence)
    route = load_json(route_path, "route_spec", errors) if route_path else None
    route_segments = validate_route(route, errors)

    if route:
        for mf, rf in (("route_id", "route_id"), ("route_revision", "route_revision")):
            if manifest.get(mf) != route.get(rf):
                errors.append(f"manifest: {mf} differs from route spec")
        # Check expected segments matches route segments
        expected = manifest.get("expected_segments", [])
        if isinstance(expected, list) and set(expected) != set(route_segments):
            errors.append("manifest: expected_segments differ from route spec")

    # Validate events
    events_path = resolve_ref(session, manifest.get("events_csv"), "events_csv", errors)
    if events_path and isinstance(expected, list):
        stats, sync_summary = validate_events(events_path, expected, route_segments, errors)

    # Validate inventory
    inventory_path = resolve_ref(session, manifest.get("hardware_inventory"), "hardware_inventory", errors)
    inventory_hash = verify_hash(inventory_path, manifest.get("hardware_inventory_sha256"), "hardware_inventory", errors, evidence)
    inventory = load_json(inventory_path, "hardware_inventory", errors) if inventory_path else None
    validate_inventory(inventory, errors)

    # Validate review
    review_path = resolve_ref(session, manifest.get("human_review"), "human_review", errors)
    review_hash = verify_hash(review_path, manifest.get("human_review_sha256"), "human_review", errors, evidence)
    review = load_json(review_path, "human_review", errors) if review_path else None
    validate_review(review, errors)

    if errors:
        return {
            "ok": False,
            "physical_ready": False,
            "decision": "INVALID",
            "errors": sorted(errors),
            "warnings": ["physical readiness not evaluated because structure is invalid"],
            "blocking_reasons": ["STRUCTURAL_CONTRACT_INVALID"],
            "evidence_hashes": evidence,
            "sync_summary": sync_summary,
            "origin_summary": {},
            "review_summary": {},
            "stats": stats
        }

    # Blockers (Readiness L2/L3)
    if manifest.get("physical_readiness_status") != "GO":
        blockers.append("MANIFEST_PHYSICAL_STATUS_NOT_GO")
    if manifest.get("comparability_status") != "COMPARABLE":
        blockers.append("SESSION_NOT_COMPARABLE")
    if inventory is None:
        blockers.append("SEALED_HARDWARE_INVENTORY_MISSING")
    if review is None:
        blockers.append("SEALED_HUMAN_REVIEW_MISSING")

    if route:
        comparisons = (
            ("coordinate_frame", "coordinate_frame"), ("motion_domain", "motion_domain"),
            ("origin_marker_id", "origin_marker_id"), ("origin_reference", "origin_reference"),
            ("distance_instrument", "distance_instrument"), ("distance_accuracy_m", "distance_accuracy_m"),
            ("angle_instrument", "angle_instrument"), ("angle_accuracy_rad", "angle_accuracy_rad")
        )
        for mf, rf in comparisons:
            if not same(manifest.get(mf), route.get(rf)):
                blockers.append(f"MANIFEST_ROUTE_{mf.upper()}_MISMATCH")
        if manifest.get("experiment_phase") not in route.get("approved_for_phase", []) or not route.get("approval_date"):
            blockers.append("ROUTE_NOT_APPROVED_FOR_PHASE")

    if inventory:
        for mf, inf in (
            ("hardware_inventory_id", "inventory_id"), ("hardware_inventory_revision", "inventory_revision"),
            ("distance_instrument", "distance_instrument"), ("distance_accuracy_m", "distance_accuracy_m"),
            ("angle_instrument", "angle_instrument"), ("angle_accuracy_rad", "angle_accuracy_rad"),
            ("sync_method", "sync_method"), ("sync_expected_accuracy_s", "sync_expected_accuracy_s")
        ):
            if not same(manifest.get(mf), inventory.get(inf)):
                blockers.append(f"MANIFEST_INVENTORY_{mf.upper()}_MISMATCH")
        if manifest.get("hardware_inventory_sha256") != inventory_hash:
            blockers.append("INVENTORY_HASH_REFERENCE_MISMATCH")
        if inventory.get("inventory_status") != "REVIEWED_READY":
            blockers.append("INVENTORY_NOT_READY")
        valid_until = parse_iso(inventory.get("valid_until"), "hardware_inventory: valid_until", [], required=False)
        if inventory.get("inventory_status") == "REVIEWED_READY" and (valid_until is None or valid_until <= datetime.now(timezone.utc)):
            blockers.append("INVENTORY_EXPIRED")
        if manifest.get("route_id") not in inventory.get("valid_for_route_ids", []):
            blockers.append("INVENTORY_NOT_VALID_FOR_ROUTE")
        for field, label in (
            ("distance_instrument_available", "DISTANCE_INSTRUMENT_UNAVAILABLE"),
            ("angle_instrument_available", "ANGLE_INSTRUMENT_UNAVAILABLE"),
            ("floor_markers_available", "FLOOR_MARKERS_UNAVAILABLE"),
            ("orientation_marker_available", "ORIENTATION_MARKER_UNAVAILABLE"),
            ("sync_marker_available", "SYNC_MARKER_UNAVAILABLE"),
            ("storage_confirmed", "STORAGE_NOT_CONFIRMED"),
            ("supervised_area_confirmed", "SUPERVISED_AREA_NOT_CONFIRMED"),
            ("safety_observer_confirmed", "SAFETY_OBSERVER_NOT_CONFIRMED")
        ):
            if not inventory.get(field):
                blockers.append(label)

    if review:
        links = (
            ("session_id", manifest.get("session_id")), ("route_id", manifest.get("route_id")),
            ("route_revision", manifest.get("route_revision")), ("route_spec_sha256", manifest.get("route_spec_sha256")),
            ("hardware_inventory_id", manifest.get("hardware_inventory_id")),
            ("hardware_inventory_revision", manifest.get("hardware_inventory_revision")),
            ("hardware_inventory_sha256", manifest.get("hardware_inventory_sha256"))
        )
        for field, value in links:
            if review.get(field) != value:
                blockers.append(f"HUMAN_REVIEW_{field.upper()}_MISMATCH")
        if (manifest.get("human_review_id") != review.get("review_id") or
            manifest.get("human_review_revision") != review.get("review_revision") or
            manifest.get("human_review_sha256") != review_hash):
            blockers.append("HUMAN_REVIEW_MANIFEST_REFERENCE_MISMATCH")
        if review.get("decision") != "GO":
            blockers.append("HUMAN_REVIEW_DECISION_NOT_GO")
        if review.get("origin_placement_status") != "IN_TOLERANCE":
            blockers.append("ORIGIN_NOT_IN_TOLERANCE")
        pos = review.get("origin_position_error_m")
        yaw = review.get("origin_yaw_error_rad")
        if not finite_nonnegative(pos) or not route or pos > route.get("origin_position_tolerance_m", -1):
            blockers.append("ORIGIN_POSITION_OUT_OF_TOLERANCE")
        if not finite_nonnegative(yaw) or not route or yaw > route.get("origin_yaw_tolerance_rad", -1):
            blockers.append("ORIGIN_YAW_OUT_OF_TOLERANCE")
        if not review.get("sync_plan_reviewed"):
            blockers.append("SYNC_PLAN_NOT_REVIEWED")
        if not review.get("safety_protocol_reviewed"):
            blockers.append("SAFETY_PROTOCOL_NOT_REVIEWED")
        parse_iso(review.get("reviewed_at"), "human_review: reviewed_at", blockers)

    if sync_summary["count"] < 2:
        blockers.append("DOUBLE_SYNC_MARKERS_MISSING")
    if not sync_summary["initial_present"]:
        blockers.append("INITIAL_SYNC_MARKER_MISSING")
    if not sync_summary["final_present"]:
        blockers.append("FINAL_SYNC_MARKER_MISSING")

    manifest_sync = manifest.get("sync_expected_accuracy_s")
    inventory_sync = inventory.get("sync_expected_accuracy_s") if inventory else None
    allowed_sync = min(
        manifest_sync if finite_nonnegative(manifest_sync) else math.inf,
        inventory_sync if finite_nonnegative(inventory_sync) else math.inf
    )
    if sync_summary["max_tolerance_s"] is None or sync_summary["max_tolerance_s"] > allowed_sync:
        blockers.append("SYNC_TOLERANCE_EXCEEDS_DECLARED_ACCURACY")
    if any(placeholder(source) for source in sync_summary["sources"]):
        blockers.append("SYNC_SOURCE_PLACEHOLDER")

    critical = []
    critical += [
        manifest.get(x) for x in (
            "session_id", "location", "route_id", "origin_marker_id", "origin_reference",
            "initial_orientation_marker", "distance_instrument", "angle_instrument", "sync_method"
        )
    ]
    if route:
        critical += [
            route.get(x) for x in (
                "route_id", "origin_marker_id", "origin_reference", "distance_instrument",
                "angle_instrument", "approved_by_role"
            )
        ]
    if inventory:
        critical += [
            inventory.get(x) for x in (
                "inventory_id", "reviewed_by_role", "location_scope", "distance_instrument",
                "angle_instrument", "sync_method"
            )
        ]
    if review:
        critical += [
            review.get(x) for x in (
                "review_id", "reviewed_by_role", "movement_authorization_reference"
            )
        ]
    if any(placeholder(value) for value in critical):
        blockers.append("CRITICAL_PLACEHOLDER_PRESENT")

    origin_summary = {
        "comparability_status": manifest.get("comparability_status"),
        "placement_status": review.get("origin_placement_status") if review else None,
        "position_error_m": review.get("origin_position_error_m") if review else None,
        "yaw_error_rad": review.get("origin_yaw_error_rad") if review else None
    }
    review_summary = {
        "present": review is not None,
        "decision": review.get("decision") if review else None,
        "review_id": review.get("review_id") if review else None,
        "reviewed_by_role": review.get("reviewed_by_role") if review else None
    }

    blockers = sorted(set(blockers))
    physical_ready = not blockers
    decision = "GO" if physical_ready else "NO_GO"
    if blockers:
        warnings.append("physical readiness requirements are not satisfied")

    return {
        "ok": True,
        "physical_ready": physical_ready,
        "decision": decision,
        "errors": [],
        "warnings": warnings,
        "blocking_reasons": blockers,
        "evidence_hashes": evidence,
        "sync_summary": sync_summary,
        "origin_summary": origin_summary,
        "review_summary": review_summary,
        "stats": stats
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("session_dir",type=Path);parser.add_argument("--output",type=Path);args=parser.parse_args()
    report=validate(args.session_dir);payload=json.dumps(report,indent=2,sort_keys=True)+"\n"
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(payload,encoding="utf-8")
    print(payload,end="");return 0 if report["ok"] else 3


if __name__=="__main__": raise SystemExit(main())
