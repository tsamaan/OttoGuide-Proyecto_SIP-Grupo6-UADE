#!/usr/bin/env python3
"""
analyze_capture_sqlite.py
=========================
Offline analyzer for ROS 2 bag captures (SQLite3 backend).
Opens .db3 in read-only mode.  Never modifies the bag.

Usage:
  python analyze_capture_sqlite.py --bag-dir <path/to/bag> --out <analysis_dir>

Outputs (in <analysis_dir>/):
  sqlite_analysis.json
  capture_topic_matrix.csv
  capture_analysis.md
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import textwrap
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Topic classification for OttoGuide G1 EDU 8 progressive replay plan
# ---------------------------------------------------------------------------

SENSOR_BASE = {
    "/utlidar/cloud",
    "/livox/imu",
    "/scan",
}

ROBOT_STATE_SDK = {
    "/unitree/remote_joy",
    "/unitree/lowstate_imu",
    "/unitree/secondary_imu",
    "/unitree/fsm_state",
    "/unitree/lowstate_summary",
    "/unitree/sdk_health",
}

NAVIGATION_MAP = {
    "/tf",
    "/tf_static",
    "/odom",
    "/map",
    "/map_metadata",
}

SAFETY_CONTROL = {
    "/cmd_vel",
    "/api/sport/request",
    "/api/sport/response",
}

NAV_PATTERNS = [
    "slam", "localization", "relocalization", "navigation",
    "nav", "trajectory", "waypoint", "motion",
]

SDK_PATTERNS = [
    "sport", "lowstate", "wireless", "odom",
]


def classify_topic(name: str) -> str:
    if name in SENSOR_BASE:
        return "sensor_base"
    if name in ROBOT_STATE_SDK:
        return "robot_state_sdk"
    if name in NAVIGATION_MAP:
        return "navigation_map"
    if name in SAFETY_CONTROL:
        return "safety_control"
    nl = name.lower()
    for p in NAV_PATTERNS:
        if p in nl:
            return "navigation_map"
    for p in SDK_PATTERNS:
        if p in nl:
            return "robot_state_sdk"
    return "other"


def replay_level(name: str, group: str) -> List[str]:
    """Return which replay levels this topic contributes to."""
    levels = []
    if name in SENSOR_BASE:
        levels.append("L0_sensor_base")
    if name == "/unitree/remote_joy":
        levels.append("L1_temporal_intent")
    if name == "/odom":
        levels.append("L2_validated_odometry")
    if name in {"/tf", "/tf_static", "/map", "/map_metadata"}:
        levels.append("L3_localization")
    return levels if levels else ["capture_context"]


def max_timestamp_gap(cur: sqlite3.Cursor, topic_id: int):
    previous = None
    maximum = None
    for (timestamp,) in cur.execute(
        "SELECT timestamp FROM messages WHERE topic_id = ? ORDER BY timestamp",
        (topic_id,),
    ):
        if previous is not None:
            gap = (timestamp - previous) / 1e9
            maximum = gap if maximum is None else max(maximum, gap)
        previous = timestamp
    return maximum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_metadata(bag_dir: Path) -> Path:
    m = bag_dir / "metadata.yaml"
    if not m.exists():
        raise FileNotFoundError(f"metadata.yaml not found in {bag_dir}")
    return m


def find_db3(bag_dir: Path) -> Path:
    dbs = list(bag_dir.glob("*.db3"))
    if not dbs:
        raise FileNotFoundError(f"No .db3 file found in {bag_dir}")
    return dbs[0]


def open_db3_readonly(db3_path: Path) -> sqlite3.Connection:
    uri = db3_path.as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def load_metadata(meta_path: Path) -> dict:
    with open(meta_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_bag(bag_dir: Path, out_dir: Path) -> dict:
    bag_dir = bag_dir.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    meta_path = find_metadata(bag_dir)
    db3_path = find_db3(bag_dir)

    print(f"[INFO] bag_dir  : {bag_dir}")
    print(f"[INFO] metadata : {meta_path}")
    print(f"[INFO] db3      : {db3_path}")
    print(f"[INFO] out_dir  : {out_dir}")

    # ---- metadata.yaml -------------------------------------------------------
    meta = load_metadata(meta_path)
    bag_info = meta.get("rosbag2_bagfile_information", meta)
    duration_ns = bag_info.get("duration", {})
    if isinstance(duration_ns, dict):
        duration_ns = duration_ns.get("nanoseconds", 0)
    start_ns = bag_info.get("starting_time", {})
    if isinstance(start_ns, dict):
        start_ns = start_ns.get("nanoseconds_since_epoch", 0)
    message_count_meta = bag_info.get("message_count", 0)
    storage_id = bag_info.get("storage_identifier", "unknown")

    duration_s = duration_ns / 1e9 if duration_ns else 0.0
    start_dt = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc).isoformat() if start_ns else "unknown"

    # Topics from metadata
    meta_topics = {}
    for tc in bag_info.get("topics_with_message_count", []):
        ti = tc.get("topic_metadata", {})
        tn = ti.get("name", "")
        meta_topics[tn] = {
            "type": ti.get("type", ""),
            "serialization_format": ti.get("serialization_format", ""),
            "offered_qos_profiles": ti.get("offered_qos_profiles", ""),
            "message_count_meta": tc.get("message_count", 0),
        }

    # ---- SQLite --------------------------------------------------------------
    con = open_db3_readonly(db3_path)
    cur = con.cursor()

    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]

    # topics table
    sql_topics = {}
    if "topics" in tables:
        for row in cur.execute("SELECT id, name, type, serialization_format FROM topics"):
            tid, tname, ttype, tser = row
            sql_topics[tid] = {"name": tname, "type": ttype, "serialization_format": tser}

    # messages table - count per topic_id and min/max timestamps
    topic_stats = {}
    if "messages" in tables:
        for row in cur.execute(
            "SELECT topic_id, COUNT(*) as cnt, MIN(timestamp) as ts_min, MAX(timestamp) as ts_max FROM messages GROUP BY topic_id"
        ):
            tid, cnt, ts_min, ts_max = row
            topic_stats[tid] = {"count": cnt, "ts_min": ts_min, "ts_max": ts_max}

    # ---- Build per-topic records --------------------------------------------
    topic_records = []
    all_topic_names = set()

    for tid, tinfo in sql_topics.items():
        tn = tinfo["name"]
        all_topic_names.add(tn)
        stats = topic_stats.get(tid, {"count": 0, "ts_min": None, "ts_max": None})
        cnt = stats["count"]
        ts_min = stats["ts_min"]
        ts_max = stats["ts_max"]

        span_s = (ts_max - ts_min) / 1e9 if (ts_min and ts_max and ts_max > ts_min) else None
        hz = cnt / span_s if (span_s and span_s > 0) else None
        max_gap_s = max_timestamp_gap(cur, tid) if cnt > 1 else None

        group = classify_topic(tn)
        levels = replay_level(tn, group)
        meta_info = meta_topics.get(tn, {})

        topic_records.append({
            "name": tn,
            "type": tinfo.get("type", meta_info.get("type", "")),
            "count": cnt,
            "span_s": round(span_s, 3) if span_s else None,
            "hz_avg": round(hz, 3) if hz else None,
            "max_gap_s": round(max_gap_s, 6) if max_gap_s is not None else None,
            "group": group,
            "replay_levels": levels,
            "topic_id_db": tid,
            "count_meta": meta_info.get("message_count_meta", None),
        })

    # Also add topics in metadata but not found in sqlite (edge case)
    for tn, minfo in meta_topics.items():
        if tn not in all_topic_names:
            group = classify_topic(tn)
            levels = replay_level(tn, group)
            topic_records.append({
                "name": tn,
                "type": minfo.get("type", ""),
                "count": minfo.get("message_count_meta", 0),
                "span_s": None,
                "hz_avg": None,
                "max_gap_s": None,
                "group": group,
                "replay_levels": levels,
                "topic_id_db": None,
                "count_meta": minfo.get("message_count_meta", 0),
            })

    con.close()
    topic_records.sort(key=lambda r: r["name"])

    # ---- Presence checks ----------------------------------------------------
    present = all_topic_names

    # Sensor base
    sensor_present = SENSOR_BASE & present
    sensor_missing = SENSOR_BASE - present

    # SDK state
    sdk_present = ROBOT_STATE_SDK & present
    sdk_missing = ROBOT_STATE_SDK - present

    # Nav/map
    nav_present = NAVIGATION_MAP & present
    nav_missing = NAVIGATION_MAP - present

    # Safety
    cmd_vel_present = "/cmd_vel" in present
    api_sport_present = bool({"/api/sport/request", "/api/sport/response"} & present)

    # Unitree candidates (any)
    unitree_candidates_present = [
        t for t in present
        if any(p in t.lower() for p in ["sport", "lowstate", "wireless", "secondary_imu", "odommodestate"])
    ]

    # Level readiness. Presence of IMU, joints, FSM, or LowState never satisfies L2.
    records_by_name = {record["name"]: record for record in topic_records}
    l0_ready = len(sensor_missing) == 0
    continuity_topics = SENSOR_BASE | {"/unitree/remote_joy"}
    continuity = {
        topic: records_by_name.get(topic, {}).get("max_gap_s")
        for topic in sorted(continuity_topics)
    }
    continuity_ready = all(
        gap is not None and gap <= 1.0 for gap in continuity.values()
    )
    l1_ready = l0_ready and "/unitree/remote_joy" in present and continuity_ready
    odom_record = records_by_name.get("/odom")
    l2_ready = bool(
        l1_ready and odom_record and
        odom_record.get("type") == "nav_msgs/msg/Odometry"
    )
    l3_ready = l2_ready and ("/tf" in present) and ("/tf_static" in present) and ("/map" in present)

    # ---- Build result dict --------------------------------------------------
    result = {
        "bag_dir": str(bag_dir),
        "db3_path": str(db3_path),
        "metadata_path": str(meta_path),
        "storage_id": storage_id,
        "duration_s": round(duration_s, 3),
        "start_utc": start_dt,
        "message_count_meta": message_count_meta,
        "message_count_sqlite": sum(r["count"] for r in topic_records),
        "tables_in_db3": tables,
        "topics": topic_records,
        "presence": {
            "sensor_base_present": sorted(sensor_present),
            "sensor_base_missing": sorted(sensor_missing),
            "robot_state_sdk_present": sorted(sdk_present),
            "robot_state_sdk_missing": sorted(sdk_missing),
            "navigation_map_present": sorted(nav_present),
            "navigation_map_missing": sorted(nav_missing),
            "cmd_vel_present": cmd_vel_present,
            "api_sport_present": api_sport_present,
            "unitree_candidates_found": sorted(unitree_candidates_present),
            "continuity_max_gap_s": continuity,
            "continuity_threshold_s": 1.0,
        },
        "replay_readiness": {
            "L0_sensor_base": l0_ready,
            "L1_temporal": l1_ready,
            "L2_odom_sdk": l2_ready,
            "L3_slam_nav": l3_ready,
            "L0_note": "Needs /utlidar/cloud, /livox/imu, and /scan",
            "L1_note": "Needs L0 + /unitree/remote_joy with maximum gaps <= 1 second",
            "L2_note": "Needs L1 + nav_msgs/msg/Odometry on /odom; IMU, joints, LowState, and FSM do not satisfy L2",
            "L3_note": "Needs validated L2 plus /tf, /tf_static, and /map",
        },
    }

    return result, topic_records


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_json(result: dict, out_dir: Path):
    p = out_dir / "sqlite_analysis.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[OUT] {p}")


def write_csv(topic_records: list, out_dir: Path):
    p = out_dir / "capture_topic_matrix.csv"
    fields = ["name", "type", "count", "hz_avg", "span_s", "max_gap_s", "group", "replay_levels"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in topic_records:
            row = dict(r)
            row["replay_levels"] = "|".join(row.get("replay_levels", []))
            w.writerow(row)
    print(f"[OUT] {p}")


def write_markdown(result: dict, topic_records: list, out_dir: Path):
    p = out_dir / "capture_analysis.md"
    rd = result["replay_readiness"]
    pr = result["presence"]

    def bool_icon(b: bool) -> str:
        return "✅" if b else "❌"

    lines = [
        "# Capture Analysis — OttoGuide G1 EDU 8",
        "",
        f"**Bag dir:** `{result['bag_dir']}`",
        f"**DB3:** `{result['db3_path']}`",
        f"**Storage:** `{result['storage_id']}`",
        f"**Duration:** {result['duration_s']:.2f} s",
        f"**Start UTC:** {result['start_utc']}",
        f"**Messages (metadata):** {result['message_count_meta']:,}",
        f"**Messages (SQLite count):** {result['message_count_sqlite']:,}",
        f"**Tables in DB3:** {', '.join(result['tables_in_db3'])}",
        "",
        "---",
        "",
        "## Replay Readiness",
        "",
        f"| Level | Ready | Note |",
        f"|-------|-------|------|",
        f"| L0 – Sensor base           | {bool_icon(rd['L0_sensor_base'])} | {rd['L0_note']} |",
        f"| L1 – Teach & Replay        | {bool_icon(rd['L1_temporal'])} | {rd['L1_note']} |",
        f"| L2 – State-corrected odom  | {bool_icon(rd['L2_odom_sdk'])} | {rd['L2_note']} |",
        f"| L3 – Localized Nav / SLAM  | {bool_icon(rd['L3_slam_nav'])} | {rd['L3_note']} |",
        "",
        "---",
        "",
        "## Presence Summary",
        "",
        "### OttoGuide sensor base",
        f"- Present: {', '.join(pr['sensor_base_present']) or '(none)'}",
        f"- Missing: {', '.join(pr['sensor_base_missing']) or '(none)'}",
        "",
        "### Robot state / SDK",
        f"- Present: {', '.join(pr['robot_state_sdk_present']) or '(none)'}",
        f"- Missing: {', '.join(pr['robot_state_sdk_missing']) or '(none)'}",
        f"- Unitree candidates found: {', '.join(pr['unitree_candidates_found']) or '(none)'}",
        "",
        "### Navigation / map",
        f"- Present: {', '.join(pr['navigation_map_present']) or '(none)'}",
        f"- Missing: {', '.join(pr['navigation_map_missing']) or '(none)'}",
        "",
        "### Safety / control audit",
        f"- `/cmd_vel` present: {bool_icon(pr['cmd_vel_present'])} {'← AUDIT: check publisher count in next live capture' if pr['cmd_vel_present'] else ''}",
        f"- API sport topics present: {bool_icon(pr['api_sport_present'])}",
        f"- Continuity threshold: {pr['continuity_threshold_s']:.1f} s maximum gap",
        "",
        "---",
        "",
        "## Topic Matrix",
        "",
        "| Topic | Type | Count | Hz avg | Max gap s | Group | Replay levels |",
        "|-------|------|------:|-------:|----------:|-------|---------------|",
    ]

    for r in topic_records:
        hz = f"{r['hz_avg']:.2f}" if r["hz_avg"] else "—"
        gap = f"{r['max_gap_s']:.6f}" if r["max_gap_s"] is not None else "—"
        lvls = " ".join(r["replay_levels"])
        lines.append(f"| `{r['name']}` | `{r['type']}` | {r['count']:,} | {hz} | {gap} | {r['group']} | {lvls} |")

    lines += [
        "",
        "---",
        "",
        "## Conclusions",
        "",
    ]

    rd_l0 = rd["L0_sensor_base"]
    rd_l1 = rd["L1_temporal"]
    rd_l2 = rd["L2_odom_sdk"]
    rd_l3 = rd["L3_slam_nav"]

    if rd_l0 and not rd_l1:
        lines.append(
            "This capture contains **L0 sensor-base data only** (LiDAR + IMU + scan). "
            "It lacks a wireless remote control input topic (`/unitree/remote_joy` or `/wirelesscontroller`) "
            "which is required for **L1 Teach & Replay** intention tracking."
        )
    elif rd_l1 and not rd_l2:
        lines.append(
            "This capture supports **L1 Teach & Replay**. "
            "Odometry topic (`/odom`) is missing — **L2 State-corrected replay** is not yet ready. "
            "Note: raw IMU, joint states, LowState or FSM topics do not satisfy L2 odom requirements."
        )
    elif rd_l2 and not rd_l3:
        lines.append(
            "This capture supports **L1 Teach & Replay** and **L2 State-corrected replay**. "
            "Map or transformation topics (`/tf`, `/tf_static`, `/map`) are missing — **L3 localized navigation** is not possible."
        )
    elif rd_l3:
        lines.append(
            "This capture contains the required topic set for **L0/L1/L2/L3 analysis**. "
            "Physical navigation still requires a separate authorized validation."
        )
    else:
        lines.append(
            "Capture has incomplete sensor data. Review topic matrix above."
        )

    lines += [
        "",
        "### What is still missing for full progressive replay",
        "| Missing | Needed for |",
        "|---------|-----------|",
    ]
    if not rd_l0:
        lines.append("| Sensor base topics (/utlidar/cloud, /livox/imu, /scan) | L0 Sensor base |")
    if not rd_l1:
        lines.append("| Joystick input (/unitree/remote_joy) | L1 Teach & Replay |")
    if not rd_l2:
        lines.append("| Validated odometry (/odom) | L2 State-corrected odom |")
    if "/tf" not in pr["navigation_map_present"] or "/tf_static" not in pr["navigation_map_present"]:
        lines.append("| `/tf`, `/tf_static` | L3 Localized Nav / SLAM |")
    if "/map" not in pr["navigation_map_present"]:
        lines.append("| `/map` | L3 Localized Nav / SLAM |")

    lines += [
        "",
        f"*Generated by analyze_capture_sqlite.py at {datetime.now(tz=timezone.utc).isoformat()}*",
    ]

    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[OUT] {p}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Offline analyzer for ROS 2 bag SQLite captures (read-only)."
    )
    parser.add_argument("--bag-dir", required=True, help="Path to the bag directory (contains metadata.yaml + .db3)")
    parser.add_argument("--out", required=True, help="Output directory for analysis files")
    args = parser.parse_args()

    bag_dir = Path(args.bag_dir)
    out_dir = Path(args.out)

    if not bag_dir.exists():
        print(f"[ERROR] bag-dir does not exist: {bag_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        result, topic_records = analyze_bag(bag_dir, out_dir)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    except sqlite3.Error as e:
        print(f"[ERROR] SQLite error: {e}", file=sys.stderr)
        sys.exit(1)

    write_json(result, out_dir)
    write_csv(topic_records, out_dir)
    write_markdown(result, topic_records, out_dir)

    print()
    print("=== Summary ===")
    rd = result["replay_readiness"]
    print(f"  Duration     : {result['duration_s']:.2f} s")
    print(f"  Topics found : {len(topic_records)}")
    print(f"  L0 sensors   : {'READY' if rd['L0_sensor_base'] else 'NOT READY'}")
    print(f"  L1 intention : {'READY' if rd['L1_temporal'] else 'NOT READY'}")
    print(f"  L2 odometry  : {'READY' if rd['L2_odom_sdk'] else 'NOT READY'}")
    print(f"  L3 localized : {'READY' if rd['L3_slam_nav'] else 'NOT READY'}")
    print()


if __name__ == "__main__":
    main()
