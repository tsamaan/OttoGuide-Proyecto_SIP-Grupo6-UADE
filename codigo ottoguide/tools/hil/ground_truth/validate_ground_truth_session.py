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
    for field in REQUIRED_ROUTE:
        if field not in route: errors.append(f"route_spec: missing required field {field}")
    if route.get("schema_version") != SCHEMA_VERSION: errors.append("route_spec: unsupported schema_version")
    segments = route.get("segments"); indexed = {}; orders = set()
    if not isinstance(segments, list) or not segments:
        errors.append("route_spec: segments must be a non-empty list")
        return indexed
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict): errors.append(f"route_spec: segments[{index}] must be an object"); continue
        for field in ("segment_id", "order", "expected_state", "start_marker", "end_marker", "expected_distance_m", "expected_yaw_change_rad", "position_tolerance_m", "yaw_tolerance_rad", "minimum_duration_s", "notes"):
            if field not in segment: errors.append(f"route_spec: segments[{index}] missing {field}")
        sid = segment.get("segment_id")
        if not isinstance(sid, str) or not sid.strip(): errors.append(f"route_spec: segments[{index}] segment_id required")
        elif sid in indexed: errors.append(f"route_spec: duplicate segment_id {sid}")
        else: indexed[sid] = segment
        order = segment.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 1 or order in orders: errors.append(f"route_spec: invalid/duplicate order for {sid}")
        orders.add(order)
        if segment.get("expected_state") not in EXPECTED_STATES - {"UNKNOWN"}: errors.append(f"route_spec: invalid expected_state for {sid}")
        for field in ("expected_distance_m", "position_tolerance_m", "yaw_tolerance_rad", "minimum_duration_s"):
            if field in segment and not finite_nonnegative(segment[field]): errors.append(f"route_spec: {sid} {field} invalid")
        yaw = segment.get("expected_yaw_change_rad")
        if not isinstance(yaw, (int, float)) or isinstance(yaw, bool) or not math.isfinite(yaw): errors.append(f"route_spec: {sid} expected_yaw_change_rad invalid")
    for field in ("origin_position_tolerance_m", "origin_yaw_tolerance_rad", "distance_accuracy_m", "angle_accuracy_rad"):
        if not finite_nonnegative(route.get(field)): errors.append(f"route_spec: {field} invalid")
    approved = route.get("approved_for_phase")
    if not isinstance(approved, list) or any(item not in PHASES for item in approved): errors.append("route_spec: approved_for_phase invalid")
    return indexed


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
    if data is None: return
    for field in REQUIRED_HARDWARE:
        if field not in data: errors.append(f"hardware_inventory: missing {field}")
    if data.get("schema_version") != SCHEMA_VERSION: errors.append("hardware_inventory: unsupported schema_version")
    if data.get("inventory_status") not in INVENTORY_STATUS: errors.append("hardware_inventory: invalid inventory_status")
    if data.get("inventory_status") != "NOT_REVIEWED":
        parse_iso(data.get("reviewed_at"), "hardware_inventory: reviewed_at", errors)
        if not isinstance(data.get("reviewed_by_role"), str) or not data["reviewed_by_role"].strip(): errors.append("hardware_inventory: reviewed_by_role required")
    if data.get("inventory_status") == "REVIEWED_READY": parse_iso(data.get("valid_until"), "hardware_inventory: valid_until", errors)
    if not isinstance(data.get("valid_for_route_ids"), list) or any(not isinstance(x,str) or not x.strip() for x in data.get("valid_for_route_ids",[])): errors.append("hardware_inventory: valid_for_route_ids invalid")
    for field in ("distance_accuracy_m", "angle_accuracy_rad", "sync_expected_accuracy_s"):
        value=data.get(field)
        if value is not None and not finite_nonnegative(value): errors.append(f"hardware_inventory: {field} invalid")
    for field in ("distance_instrument_available","angle_instrument_available","floor_markers_available","orientation_marker_available","sync_marker_available","external_camera_available","camera_support_available","fiducial_marker_available","storage_confirmed","supervised_area_confirmed","safety_observer_confirmed"):
        if field in data and not isinstance(data[field],bool): errors.append(f"hardware_inventory: {field} must be boolean")


def validate_review(data, errors):
    if data is None: return
    for field in REQUIRED_REVIEW:
        if field not in data: errors.append(f"human_review: missing {field}")
    if data.get("schema_version") != SCHEMA_VERSION: errors.append("human_review: unsupported schema_version")
    if data.get("decision") not in REVIEW_DECISIONS: errors.append("human_review: invalid decision")
    if data.get("origin_placement_status") not in ORIGIN_STATUS: errors.append("human_review: invalid origin_placement_status")
    for field in ("origin_position_error_m","origin_yaw_error_rad"):
        value=data.get(field)
        if value is not None and not finite_nonnegative(value): errors.append(f"human_review: {field} invalid")
    for field in ("sync_plan_reviewed","safety_protocol_reviewed"):
        if field in data and not isinstance(data[field],bool): errors.append(f"human_review: {field} must be boolean")
    if data.get("reviewed_at"): parse_iso(data["reviewed_at"], "human_review: reviewed_at", errors)


def same(a,b):
    if isinstance(a,(int,float)) and isinstance(b,(int,float)): return math.isclose(a,b,rel_tol=0,abs_tol=1e-12)
    return a == b


def validate(session):
    errors=[]; warnings=[]; blockers=[]; evidence={}; stats={}; sync_summary={"count":0,"initial_present":False,"final_present":False,"max_tolerance_s":None,"sources":[]}; origin_summary={}; review_summary={}
    for directory in REQUIRED_DIRS:
        if not (session/directory).is_dir(): errors.append(f"structure: missing directory {directory}")
    manifest=load_json(session/"session_manifest.json","manifest",errors)
    if manifest is None:
        return {"ok":False,"physical_ready":False,"decision":"INVALID","errors":sorted(errors),"warnings":[],"blocking_reasons":["STRUCTURAL_CONTRACT_INVALID"],"evidence_hashes":{},"sync_summary":sync_summary,"origin_summary":{},"review_summary":{},"stats":{}}
    for field in REQUIRED_MANIFEST:
        if field not in manifest: errors.append(f"manifest: missing {field}")
    if manifest.get("schema_version") != SCHEMA_VERSION: errors.append("manifest: unsupported schema_version")
    if manifest.get("session_id") != session.name: errors.append("manifest: session_id must equal directory name")
    parse_iso(manifest.get("created_at"),"manifest: created_at",errors)
    if manifest.get("experiment_phase") not in PHASES: errors.append("manifest: invalid experiment_phase")
    if manifest.get("ground_truth_level") not in GT_LEVELS: errors.append("manifest: invalid ground_truth_level")
    if manifest.get("comparability_status") not in COMPARABILITY: errors.append("manifest: invalid comparability_status")
    if manifest.get("physical_readiness_status") not in READINESS: errors.append("manifest: invalid physical_readiness_status")
    expected=manifest.get("expected_segments")
    if not isinstance(expected,list) or any(not isinstance(x,str) or not x.strip() for x in expected): errors.append("manifest: expected_segments invalid"); expected=[]
    elif len(expected)!=len(set(expected)): errors.append("manifest: expected_segments duplicated")
    for field in ("distance_accuracy_m","angle_accuracy_rad","sync_expected_accuracy_s"):
        if not finite_nonnegative(manifest.get(field)): errors.append(f"manifest: {field} invalid")
    route_path=resolve_ref(session,manifest.get("route_spec"),"route_spec",errors); verify_hash(route_path,manifest.get("route_spec_sha256"),"route_spec",errors,evidence)
    route=load_json(route_path,"route_spec",errors) if route_path else None; route_segments=validate_route(route,errors)
    if route:
        for mf,rf in (("route_id","route_id"),("route_revision","route_revision")):
            if manifest.get(mf)!=route.get(rf): errors.append(f"manifest: {mf} differs from route spec")
        if set(expected)!=set(route_segments): errors.append("manifest: expected_segments differ from route spec")
    events_path=resolve_ref(session,manifest.get("events_csv"),"events_csv",errors)
    if events_path: stats,sync_summary=validate_events(events_path,expected,route_segments,errors)
    inventory_path=resolve_ref(session,manifest.get("hardware_inventory"),"hardware_inventory",errors); inventory_hash=verify_hash(inventory_path,manifest.get("hardware_inventory_sha256"),"hardware_inventory",errors,evidence)
    inventory=load_json(inventory_path,"hardware_inventory",errors) if inventory_path else None; validate_inventory(inventory,errors)
    review_path=resolve_ref(session,manifest.get("human_review"),"human_review",errors); review_hash=verify_hash(review_path,manifest.get("human_review_sha256"),"human_review",errors,evidence)
    review=load_json(review_path,"human_review",errors) if review_path else None; validate_review(review,errors)
    if errors:
        return {"ok":False,"physical_ready":False,"decision":"INVALID","errors":sorted(errors),"warnings":["physical readiness not evaluated because structure is invalid"],"blocking_reasons":["STRUCTURAL_CONTRACT_INVALID"],"evidence_hashes":evidence,"sync_summary":sync_summary,"origin_summary":{},"review_summary":{},"stats":stats}
    if manifest.get("physical_readiness_status")!="GO": blockers.append("MANIFEST_PHYSICAL_STATUS_NOT_GO")
    if manifest.get("comparability_status")!="COMPARABLE": blockers.append("SESSION_NOT_COMPARABLE")
    if inventory is None: blockers.append("SEALED_HARDWARE_INVENTORY_MISSING")
    if review is None: blockers.append("SEALED_HUMAN_REVIEW_MISSING")
    if route:
        comparisons=(("coordinate_frame","coordinate_frame"),("motion_domain","motion_domain"),("origin_marker_id","origin_marker_id"),("origin_reference","origin_reference"),("distance_instrument","distance_instrument"),("distance_accuracy_m","distance_accuracy_m"),("angle_instrument","angle_instrument"),("angle_accuracy_rad","angle_accuracy_rad"))
        for mf,rf in comparisons:
            if not same(manifest.get(mf),route.get(rf)): blockers.append(f"MANIFEST_ROUTE_{mf.upper()}_MISMATCH")
        if manifest.get("experiment_phase") not in route.get("approved_for_phase",[]) or not route.get("approval_date"): blockers.append("ROUTE_NOT_APPROVED_FOR_PHASE")
    if inventory:
        for mf,inf in (("hardware_inventory_id","inventory_id"),("hardware_inventory_revision","inventory_revision"),("distance_instrument","distance_instrument"),("distance_accuracy_m","distance_accuracy_m"),("angle_instrument","angle_instrument"),("angle_accuracy_rad","angle_accuracy_rad"),("sync_method","sync_method"),("sync_expected_accuracy_s","sync_expected_accuracy_s")):
            if not same(manifest.get(mf),inventory.get(inf)): blockers.append(f"MANIFEST_INVENTORY_{mf.upper()}_MISMATCH")
        if manifest.get("hardware_inventory_sha256")!=inventory_hash: blockers.append("INVENTORY_HASH_REFERENCE_MISMATCH")
        if inventory.get("inventory_status")!="REVIEWED_READY": blockers.append("INVENTORY_NOT_READY")
        valid_until=parse_iso(inventory.get("valid_until"),"hardware_inventory: valid_until",[],required=False)
        if inventory.get("inventory_status")=="REVIEWED_READY" and (valid_until is None or valid_until<=datetime.now(timezone.utc)): blockers.append("INVENTORY_EXPIRED")
        if manifest.get("route_id") not in inventory.get("valid_for_route_ids",[]): blockers.append("INVENTORY_NOT_VALID_FOR_ROUTE")
        for field,label in (("distance_instrument_available","DISTANCE_INSTRUMENT_UNAVAILABLE"),("angle_instrument_available","ANGLE_INSTRUMENT_UNAVAILABLE"),("floor_markers_available","FLOOR_MARKERS_UNAVAILABLE"),("orientation_marker_available","ORIENTATION_MARKER_UNAVAILABLE"),("sync_marker_available","SYNC_MARKER_UNAVAILABLE"),("storage_confirmed","STORAGE_NOT_CONFIRMED"),("supervised_area_confirmed","SUPERVISED_AREA_NOT_CONFIRMED"),("safety_observer_confirmed","SAFETY_OBSERVER_NOT_CONFIRMED")):
            if not inventory.get(field): blockers.append(label)
    if review:
        links=(("session_id",manifest.get("session_id")),("route_id",manifest.get("route_id")),("route_revision",manifest.get("route_revision")),("route_spec_sha256",manifest.get("route_spec_sha256")),("hardware_inventory_id",manifest.get("hardware_inventory_id")),("hardware_inventory_revision",manifest.get("hardware_inventory_revision")),("hardware_inventory_sha256",manifest.get("hardware_inventory_sha256")))
        for field,value in links:
            if review.get(field)!=value: blockers.append(f"HUMAN_REVIEW_{field.upper()}_MISMATCH")
        if manifest.get("human_review_id")!=review.get("review_id") or manifest.get("human_review_revision")!=review.get("review_revision") or manifest.get("human_review_sha256")!=review_hash: blockers.append("HUMAN_REVIEW_MANIFEST_REFERENCE_MISMATCH")
        if review.get("decision")!="GO": blockers.append("HUMAN_REVIEW_DECISION_NOT_GO")
        if review.get("origin_placement_status")!="IN_TOLERANCE": blockers.append("ORIGIN_NOT_IN_TOLERANCE")
        pos=review.get("origin_position_error_m"); yaw=review.get("origin_yaw_error_rad")
        if not finite_nonnegative(pos) or not route or pos>route.get("origin_position_tolerance_m",-1): blockers.append("ORIGIN_POSITION_OUT_OF_TOLERANCE")
        if not finite_nonnegative(yaw) or not route or yaw>route.get("origin_yaw_tolerance_rad",-1): blockers.append("ORIGIN_YAW_OUT_OF_TOLERANCE")
        if not review.get("sync_plan_reviewed"): blockers.append("SYNC_PLAN_NOT_REVIEWED")
        if not review.get("safety_protocol_reviewed"): blockers.append("SAFETY_PROTOCOL_NOT_REVIEWED")
        parse_iso(review.get("reviewed_at"),"human_review: reviewed_at",blockers)
    if sync_summary["count"]<2: blockers.append("DOUBLE_SYNC_MARKERS_MISSING")
    if not sync_summary["initial_present"]: blockers.append("INITIAL_SYNC_MARKER_MISSING")
    if not sync_summary["final_present"]: blockers.append("FINAL_SYNC_MARKER_MISSING")
    manifest_sync=manifest.get("sync_expected_accuracy_s"); inventory_sync=inventory.get("sync_expected_accuracy_s") if inventory else None
    allowed_sync=min(manifest_sync if finite_nonnegative(manifest_sync) else math.inf,inventory_sync if finite_nonnegative(inventory_sync) else math.inf)
    if sync_summary["max_tolerance_s"] is None or sync_summary["max_tolerance_s"]>allowed_sync: blockers.append("SYNC_TOLERANCE_EXCEEDS_DECLARED_ACCURACY")
    if any(placeholder(source) for source in sync_summary["sources"]): blockers.append("SYNC_SOURCE_PLACEHOLDER")
    critical=[]
    critical += [manifest.get(x) for x in ("session_id","location","route_id","origin_marker_id","origin_reference","initial_orientation_marker","distance_instrument","angle_instrument","sync_method")]
    if route: critical += [route.get(x) for x in ("route_id","origin_marker_id","origin_reference","distance_instrument","angle_instrument","approved_by_role")]
    if inventory: critical += [inventory.get(x) for x in ("inventory_id","reviewed_by_role","location_scope","distance_instrument","angle_instrument","sync_method")]
    if review: critical += [review.get(x) for x in ("review_id","reviewed_by_role","movement_authorization_reference")]
    if any(placeholder(value) for value in critical): blockers.append("CRITICAL_PLACEHOLDER_PRESENT")
    origin_summary={"comparability_status":manifest.get("comparability_status"),"placement_status":review.get("origin_placement_status") if review else None,"position_error_m":review.get("origin_position_error_m") if review else None,"yaw_error_rad":review.get("origin_yaw_error_rad") if review else None}
    review_summary={"present":review is not None,"decision":review.get("decision") if review else None,"review_id":review.get("review_id") if review else None,"reviewed_by_role":review.get("reviewed_by_role") if review else None}
    blockers=sorted(set(blockers)); physical_ready=not blockers; decision="GO" if physical_ready else "NO_GO"
    if blockers: warnings.append("physical readiness requirements are not satisfied")
    return {"ok":True,"physical_ready":physical_ready,"decision":decision,"errors":[],"warnings":warnings,"blocking_reasons":blockers,"evidence_hashes":evidence,"sync_summary":sync_summary,"origin_summary":origin_summary,"review_summary":review_summary,"stats":stats}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("session_dir",type=Path);parser.add_argument("--output",type=Path);args=parser.parse_args()
    report=validate(args.session_dir);payload=json.dumps(report,indent=2,sort_keys=True)+"\n"
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(payload,encoding="utf-8")
    print(payload,end="");return 0 if report["ok"] else 3


if __name__=="__main__": raise SystemExit(main())
