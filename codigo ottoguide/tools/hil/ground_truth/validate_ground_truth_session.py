#!/usr/bin/env python3
"""Validate schema-1.0 ground-truth structure and report physical readiness separately."""
from __future__ import annotations

import argparse, csv, hashlib, json, math
from datetime import datetime
from pathlib import Path, PurePosixPath

SCHEMA_VERSION="1.0"; PHASES={"CALIBRATION","DEVELOPMENT","VALIDATION-SAME-ROUTE","VALIDATION-DOMAIN-SHIFT"}; GT_LEVELS={"GT-MIN","GT-CONT"}; COMPARABILITY={"COMPARABLE","NOT_COMPARABLE","PENDING_REVIEW"}; READINESS={"NOT_REVIEWED","NO_GO","GO"}
EVENT_TYPES={"SESSION_START","SESSION_END","STATIONARY_START","STATIONARY_END","SEGMENT_START","SEGMENT_END","SYNC_MARKER","GROUND_TRUTH_GAP_START","GROUND_TRUTH_GAP_END"}; EXPECTED_STATES={"STATIONARY","TRANSLATING","ROTATING","COMBINED","UNKNOWN"}
EVENT_COLUMNS=["timestamp_ns","relative_time_s","event_id","event_type","segment_id","expected_state","expected_x_m","expected_y_m","expected_yaw_rad","position_tolerance_m","yaw_tolerance_rad","time_tolerance_s","source","notes"]
REQUIRED_MANIFEST=["schema_version","tooling_version","session_id","created_at","operator","location","robot_model","lidar","capture_mode","ground_truth_level","time_base","rosbag_path","events_csv","external_video","external_pose_file","hardware_inventory","coordinate_frame","measurement_units","expected_segments","calibration_files","notes","experiment_phase","route_id","route_spec","route_spec_sha256","route_revision","motion_domain","origin_marker_id","origin_reference","initial_orientation_marker","comparability_status","reference_accuracy","clock_sync_method","distance_instrument","distance_accuracy_m","angle_instrument","angle_accuracy_rad","sync_method","sync_expected_accuracy_s","physical_readiness_status"]
REQUIRED_ROUTE=["schema_version","route_id","route_revision","title","motion_domain","coordinate_frame","origin_marker_id","origin_reference","initial_yaw_rad","origin_position_tolerance_m","origin_yaw_tolerance_rad","segments","stationary_intervals","measurement_method","distance_instrument","distance_accuracy_m","angle_instrument","angle_accuracy_rad","approved_for_phase","approved_by_role","approval_date","notes"]
REQUIRED_HARDWARE=["schema_version","inventory_id","review_date","distance_instrument_available","distance_instrument","distance_accuracy_m","angle_instrument_available","angle_instrument","angle_accuracy_rad","floor_markers_available","orientation_marker_available","sync_marker_available","sync_method","sync_expected_accuracy_s","external_camera_available","camera_support_available","fiducial_marker_available","storage_confirmed","supervised_area_confirmed","safety_observer_confirmed","notes"]
REQUIRED_DIRS=["ground_truth","raw","external","calibration","reports","notes"]; PAIRS={"STATIONARY_START":"STATIONARY_END","SEGMENT_START":"SEGMENT_END","GROUND_TRUTH_GAP_START":"GROUND_TRUTH_GAP_END"}

def finite_nonnegative(value): return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0
def add_ref(session,value,field,errors):
    if not isinstance(value,str): errors.append(f"manifest: {field} must be a string"); return None
    if not value: return None
    p=PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts: errors.append(f"{field}: reference must be session-relative: {value}"); return None
    resolved=session/Path(*p.parts)
    if not resolved.exists(): errors.append(f"{field}: referenced path does not exist: {value}"); return None
    return resolved
def load_json(path,label,errors):
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc: errors.append(f"{label}: cannot read valid JSON: {exc}"); return None
    if not isinstance(data,dict): errors.append(f"{label}: root must be an object"); return None
    return data
def check_iso(value,field,errors,date_only=False):
    if not isinstance(value,str) or not value.strip(): errors.append(f"{field}: non-empty ISO date/time required"); return False
    try: parsed=datetime.fromisoformat(value)
    except ValueError: errors.append(f"{field}: invalid ISO-8601 value"); return False
    if not date_only and parsed.tzinfo is None: errors.append(f"{field}: timezone-aware timestamp required"); return False
    return True
def validate_route(route,errors):
    if route is None:return {}
    for f in REQUIRED_ROUTE:
        if f not in route: errors.append(f"route_spec: missing required field {f}")
    if route.get("schema_version")!=SCHEMA_VERSION: errors.append(f"route_spec: unsupported schema_version {route.get('schema_version')!r}")
    for f in ("initial_yaw_rad","origin_position_tolerance_m","origin_yaw_tolerance_rad","distance_accuracy_m","angle_accuracy_rad"):
        if f in route and not finite_nonnegative(abs(route[f]) if f=="initial_yaw_rad" and isinstance(route[f],(int,float)) else route[f]): errors.append(f"route_spec: {f} must be finite and non-negative" if f!="initial_yaw_rad" else "route_spec: initial_yaw_rad must be finite")
    segments=route.get("segments"); result={}
    if not isinstance(segments,list) or not segments: errors.append("route_spec: segments must be a non-empty list")
    else:
        orders=set()
        for i,s in enumerate(segments):
            if not isinstance(s,dict): errors.append(f"route_spec: segments[{i}] must be an object"); continue
            required=["segment_id","order","expected_state","start_marker","end_marker","expected_distance_m","expected_yaw_change_rad","position_tolerance_m","yaw_tolerance_rad","minimum_duration_s","notes"]
            for f in required:
                if f not in s: errors.append(f"route_spec: segments[{i}] missing {f}")
            sid=s.get("segment_id")
            if not isinstance(sid,str) or not sid.strip(): errors.append(f"route_spec: segments[{i}] segment_id required")
            elif sid in result: errors.append(f"route_spec: duplicate segment_id {sid}")
            else: result[sid]=s
            order=s.get("order")
            if not isinstance(order,int) or isinstance(order,bool) or order<1: errors.append(f"route_spec: segment {sid} invalid order")
            elif order in orders: errors.append(f"route_spec: duplicate segment order {order}")
            orders.add(order)
            if s.get("expected_state") not in EXPECTED_STATES-{"UNKNOWN"}: errors.append(f"route_spec: segment {sid} invalid expected_state")
            for f in ("expected_distance_m","position_tolerance_m","yaw_tolerance_rad","minimum_duration_s"):
                if f in s and not finite_nonnegative(s[f]): errors.append(f"route_spec: segment {sid} {f} must be finite and non-negative")
            if "expected_yaw_change_rad" in s and (not isinstance(s["expected_yaw_change_rad"],(int,float)) or isinstance(s["expected_yaw_change_rad"],bool) or not math.isfinite(s["expected_yaw_change_rad"])): errors.append(f"route_spec: segment {sid} expected_yaw_change_rad must be finite")
    approved=route.get("approved_for_phase")
    if not isinstance(approved,list) or any(x not in PHASES for x in approved): errors.append("route_spec: approved_for_phase must contain known phases")
    if route.get("approval_date"): check_iso(route["approval_date"],"route_spec: approval_date",errors,date_only=True)
    return result
def parse_event_number(row,field,line,errors,integer=False,optional=False):
    raw=row.get(field,"").strip()
    if optional and raw=="": return None
    try: value=int(raw) if integer else float(raw)
    except ValueError: errors.append(f"events line {line}: {field} invalid numeric value {raw!r}"); return None
    if (not integer and not math.isfinite(value)): errors.append(f"events line {line}: {field} must be finite"); return None
    return value
def validate_events(path,expected,route_segments,errors):
    stats={"event_count":0,"segment_count":0};
    try:
        with path.open(newline="",encoding="utf-8") as h: reader=csv.DictReader(h); fields=reader.fieldnames; rows=list(reader)
    except (OSError,UnicodeError) as exc: errors.append(f"events_csv: cannot read: {exc}"); return stats
    if fields!=EVENT_COLUMNS: errors.append("events_csv: columns do not match schema 1.0 contract"); return stats
    stats["event_count"]=len(rows); ids=set(); prev_ns=prev_rel=None; opens={}; completed={}; intervals=[]; reverse={v:k for k,v in PAIRS.items()}; starts=ends=0
    for line,row in enumerate(rows,2):
        eid=row["event_id"].strip(); typ=row["event_type"].strip(); sid=row["segment_id"].strip(); state=row["expected_state"].strip()
        if not eid: errors.append(f"events line {line}: event_id required")
        elif eid in ids: errors.append(f"events line {line}: duplicate event_id {eid}")
        ids.add(eid)
        if typ not in EVENT_TYPES: errors.append(f"events line {line}: unknown event_type {typ}")
        if state not in EXPECTED_STATES: errors.append(f"events line {line}: unknown expected_state {state}")
        if not row["source"].strip(): errors.append(f"events line {line}: source required")
        if typ not in {"SESSION_START","SESSION_END","SYNC_MARKER"} and not sid: errors.append(f"events line {line}: segment_id required for {typ}")
        ns=parse_event_number(row,"timestamp_ns",line,errors,integer=True); rel=parse_event_number(row,"relative_time_s",line,errors)
        pose={f:parse_event_number(row,f,line,errors,optional=True) for f in ("expected_x_m","expected_y_m","expected_yaw_rad")}
        tol={f:parse_event_number(row,f,line,errors,optional=True) for f in ("position_tolerance_m","yaw_tolerance_rad","time_tolerance_s")}
        for f,v in tol.items():
            if v is not None and v<0: errors.append(f"events line {line}: {f} must be non-negative")
        if (pose["expected_x_m"] is not None or pose["expected_y_m"] is not None) and tol["position_tolerance_m"] is None: errors.append(f"events line {line}: expected position requires position_tolerance_m")
        if pose["expected_yaw_rad"] is not None and tol["yaw_tolerance_rad"] is None: errors.append(f"events line {line}: expected yaw requires yaw_tolerance_rad")
        if typ=="SYNC_MARKER" and tol["time_tolerance_s"] is None: errors.append(f"events line {line}: SYNC_MARKER requires time_tolerance_s")
        if typ=="SEGMENT_END":
            if pose["expected_x_m"] is None and pose["expected_y_m"] is None and pose["expected_yaw_rad"] is None: errors.append(f"events line {line}: SEGMENT_END requires an expected magnitude")
        if ns is not None and prev_ns is not None and ns<=prev_ns: errors.append(f"events line {line}: timestamp_ns is not strictly monotonic")
        if rel is not None and prev_rel is not None and rel<prev_rel: errors.append(f"events line {line}: relative_time_s is not monotonic")
        if ns is not None: prev_ns=ns
        if rel is not None: prev_rel=rel
        if typ=="SESSION_START": starts+=1
        if typ=="SESSION_END": ends+=1
        if typ in PAIRS:
            key=(typ,sid)
            if key in opens: errors.append(f"events line {line}: overlapping {typ} for {sid}")
            elif rel is not None: opens[key]=(line,rel)
        elif typ in reverse:
            key=(reverse[typ],sid)
            if key not in opens: errors.append(f"events line {line}: {typ} without {reverse[typ]} for {sid}")
            else:
                _,begin=opens.pop(key)
                if typ=="SEGMENT_END" and rel is not None:
                    completed[sid]=completed.get(sid,0)+1; intervals.append((begin,rel,sid))
                    spec=route_segments.get(sid)
                    if spec and rel-begin<spec["minimum_duration_s"]: errors.append(f"events line {line}: segment {sid} shorter than route minimum_duration_s")
        if typ=="SEGMENT_START" and sid in route_segments and state!=route_segments[sid]["expected_state"]: errors.append(f"events line {line}: segment {sid} expected_state differs from route spec")
    if starts!=1: errors.append(f"events_csv: expected one SESSION_START, found {starts}")
    if ends!=1: errors.append(f"events_csv: expected one SESSION_END, found {ends}")
    if rows and rows[0]["event_type"]!="SESSION_START": errors.append("events_csv: first event must be SESSION_START")
    if rows and rows[-1]["event_type"]!="SESSION_END": errors.append("events_csv: last event must be SESSION_END")
    for (typ,sid),(line,_) in sorted(opens.items()): errors.append(f"events line {line}: {typ} without {PAIRS[typ]} for {sid}")
    for a,b in zip(sorted(intervals),sorted(intervals)[1:]):
        if b[0]<a[1]: errors.append(f"events_csv: segments overlap: {a[2]} and {b[2]}")
    declared=set(expected)
    for sid in sorted(declared):
        if completed.get(sid,0)!=1: errors.append(f"events_csv: segment {sid} must complete exactly once, found {completed.get(sid,0)}")
    for sid in sorted(set(completed)-declared): errors.append(f"events_csv: completed undeclared segment {sid}")
    stats["segment_count"]=sum(1 for n in completed.values() if n==1); return stats
def validate_inventory(data,errors):
    if data is None:return False
    for f in REQUIRED_HARDWARE:
        if f not in data: errors.append(f"hardware_inventory: missing required field {f}")
    if data.get("schema_version")!=SCHEMA_VERSION: errors.append(f"hardware_inventory: unsupported schema_version {data.get('schema_version')!r}")
    bools=["distance_instrument_available","angle_instrument_available","floor_markers_available","orientation_marker_available","sync_marker_available","external_camera_available","camera_support_available","fiducial_marker_available","storage_confirmed","supervised_area_confirmed","safety_observer_confirmed"]
    for f in bools:
        if f in data and not isinstance(data[f],bool): errors.append(f"hardware_inventory: {f} must be boolean")
    for f in ("distance_accuracy_m","angle_accuracy_rad","sync_expected_accuracy_s"):
        v=data.get(f)
        if v is not None and not finite_nonnegative(v): errors.append(f"hardware_inventory: {f} must be null or finite non-negative")
    for available,instrument,accuracy in (("distance_instrument_available","distance_instrument","distance_accuracy_m"),("angle_instrument_available","angle_instrument","angle_accuracy_rad")):
        if data.get(available) and (not isinstance(data.get(instrument),str) or not data[instrument].strip() or not finite_nonnegative(data.get(accuracy))): errors.append(f"hardware_inventory: available {instrument} requires name and accuracy")
    if data.get("sync_marker_available") and (not isinstance(data.get("sync_method"),str) or not data["sync_method"].strip() or not finite_nonnegative(data.get("sync_expected_accuracy_s"))): errors.append("hardware_inventory: available sync marker requires method and accuracy")
    return True
def readiness(manifest,route,hardware,structural_ok):
    blockers=[]
    if not structural_ok:return False,["STRUCTURAL_CONTRACT_INVALID"]
    if manifest.get("physical_readiness_status")!="GO": blockers.append("MANIFEST_PHYSICAL_STATUS_NOT_GO")
    if not route or manifest.get("experiment_phase") not in route.get("approved_for_phase",[]) or not route.get("approved_by_role") or not route.get("approval_date"): blockers.append("ROUTE_NOT_APPROVED_FOR_PHASE")
    if hardware is None: blockers.append("HARDWARE_INVENTORY_MISSING"); return False,blockers
    for f,label in (("distance_instrument_available","DISTANCE_INSTRUMENT_UNAVAILABLE"),("angle_instrument_available","ANGLE_INSTRUMENT_UNAVAILABLE"),("floor_markers_available","FLOOR_MARKERS_UNAVAILABLE"),("orientation_marker_available","ORIENTATION_MARKER_UNAVAILABLE"),("sync_marker_available","SYNC_MARKER_UNAVAILABLE"),("storage_confirmed","STORAGE_NOT_CONFIRMED"),("supervised_area_confirmed","SUPERVISED_AREA_NOT_CONFIRMED"),("safety_observer_confirmed","SAFETY_OBSERVER_NOT_CONFIRMED")):
        if not hardware.get(f): blockers.append(label)
    return not blockers,blockers
def validate(session,hardware_inventory_path=None):
    errors=[]; warnings=[]
    for d in REQUIRED_DIRS:
        if not (session/d).is_dir():errors.append(f"structure: missing directory {d}")
    manifest=load_json(session/"session_manifest.json","manifest",errors)
    if manifest is None:return {"ok":False,"physical_ready":False,"errors":sorted(errors),"warnings":[],"blocking_reasons":["STRUCTURAL_CONTRACT_INVALID"],"stats":{}}
    for f in REQUIRED_MANIFEST:
        if f not in manifest:errors.append(f"manifest: missing required field {f}")
    if manifest.get("schema_version")!=SCHEMA_VERSION:errors.append(f"manifest: unsupported schema_version {manifest.get('schema_version')!r}; expected {SCHEMA_VERSION}")
    if not isinstance(manifest.get("tooling_version"),str) or not manifest.get("tooling_version","").strip():errors.append("manifest: tooling_version must be recorded")
    if manifest.get("session_id")!=session.name:errors.append("manifest: session_id must equal session directory name")
    check_iso(manifest.get("created_at"),"manifest: created_at",errors)
    if manifest.get("experiment_phase") not in PHASES:errors.append("manifest: invalid experiment_phase")
    if manifest.get("ground_truth_level") not in GT_LEVELS:errors.append("manifest: invalid ground_truth_level")
    if manifest.get("comparability_status") not in COMPARABILITY:errors.append("manifest: invalid comparability_status")
    if manifest.get("physical_readiness_status") not in READINESS:errors.append("manifest: invalid physical_readiness_status")
    if manifest.get("measurement_units")!={"distance":"m","angle":"rad","time":"s","timestamp":"ns"}:errors.append("manifest: measurement_units must be m/rad/s/ns")
    required_strings=("schema_version","tooling_version","session_id","created_at","operator","location","robot_model","lidar","capture_mode","ground_truth_level","time_base","events_csv","coordinate_frame","notes","experiment_phase","route_id","route_spec","route_spec_sha256","route_revision","motion_domain","origin_marker_id","origin_reference","initial_orientation_marker","comparability_status","reference_accuracy","clock_sync_method","distance_instrument","angle_instrument","sync_method","physical_readiness_status")
    for f in required_strings:
        if f in manifest and (not isinstance(manifest[f],str) or not manifest[f].strip()):errors.append(f"manifest: {f} must be a non-empty string")
    for f in ("rosbag_path","external_video","external_pose_file","hardware_inventory"):
        if f in manifest and not isinstance(manifest[f],str):errors.append(f"manifest: {f} must be a string")
    if "route_spec_sha256" in manifest and isinstance(manifest["route_spec_sha256"],str) and (len(manifest["route_spec_sha256"])!=64 or any(c not in "0123456789abcdef" for c in manifest["route_spec_sha256"])):errors.append("manifest: route_spec_sha256 must be 64 lowercase hexadecimal characters")
    calibrations=manifest.get("calibration_files")
    if not isinstance(calibrations,list) or any(not isinstance(x,str) or not x.strip() for x in calibrations):errors.append("manifest: calibration_files must contain non-empty strings")
    for f in ("distance_accuracy_m","angle_accuracy_rad","sync_expected_accuracy_s"):
        if f in manifest and not finite_nonnegative(manifest[f]):errors.append(f"manifest: {f} must be finite and non-negative")
    expected=manifest.get("expected_segments")
    if not isinstance(expected,list) or any(not isinstance(x,str) or not x.strip() for x in expected):errors.append("manifest: expected_segments must contain non-empty strings"); expected=[]
    elif len(expected)!=len(set(expected)):errors.append("manifest: expected_segments must be unique")
    route_path=add_ref(session,manifest.get("route_spec"),"route_spec",errors); route=load_json(route_path,"route_spec",errors) if route_path else None; route_segments=validate_route(route,errors)
    if route_path and isinstance(manifest.get("route_spec_sha256"),str) and hashlib.sha256(route_path.read_bytes()).hexdigest()!=manifest["route_spec_sha256"]:errors.append("manifest: route_spec_sha256 mismatch")
    if route:
        if manifest.get("route_id")!=route.get("route_id"):errors.append("manifest: route_id differs from route spec")
        if manifest.get("route_revision")!=route.get("route_revision"):errors.append("manifest: route_revision differs from route spec")
        if set(expected)!=set(route_segments):errors.append("manifest: expected_segments differ from route spec")
    events=add_ref(session,manifest.get("events_csv"),"events_csv",errors); stats=validate_events(events,expected,route_segments,errors) if events else {}
    for f in ("rosbag_path","external_video","external_pose_file"):
        add_ref(session,manifest.get(f),f,errors)
    if isinstance(calibrations,list):
        for i,value in enumerate(calibrations):add_ref(session,value,f"calibration_files[{i}]",errors)
    inventory_path=hardware_inventory_path
    if inventory_path is None and manifest.get("hardware_inventory"):inventory_path=add_ref(session,manifest["hardware_inventory"],"hardware_inventory",errors)
    hardware=load_json(inventory_path,"hardware_inventory",errors) if inventory_path else None
    if hardware is not None:validate_inventory(hardware,errors)
    structural_ok=not errors; physical,blockers=readiness(manifest,route,hardware,structural_ok)
    if not physical:warnings.append("physical readiness requirements are not satisfied")
    return {"ok":structural_ok,"physical_ready":physical,"errors":sorted(errors),"warnings":sorted(warnings),"blocking_reasons":sorted(blockers),"stats":stats}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("session_dir",type=Path);p.add_argument("--hardware-inventory",type=Path);p.add_argument("--output",type=Path);a=p.parse_args();report=validate(a.session_dir,a.hardware_inventory);payload=json.dumps(report,indent=2,sort_keys=True)+"\n"
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(payload,encoding="utf-8")
    print(payload,end="");return 0 if report["ok"] else 1
if __name__=="__main__":raise SystemExit(main())
