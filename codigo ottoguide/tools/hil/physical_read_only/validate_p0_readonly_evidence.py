#!/usr/bin/env python3
"""Fase 2H.2.5 -- offline contract validator for a P0 *physical read-only*
evidence bundle (schema version 2).

P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED. This validator NEVER
touches a robot, a network, or ROS; it only inspects a directory of JSON
files a collector run (real or fixture) produced, and computes four
*independent* decision layers -- never mixed into one boolean:

* bundle_integrity     -- are all required files present, schema-versioned,
                          well-formed, sidecar present and matching,
                          filesystem metadata correct, and does every
                          file's hash match the manifest?
* read_only_invariants -- does the bundle assert (truthfully, by the
                          collector's own construction) that no
                          movement/goal/cmd_vel/control/lifecycle/parameter
                          action was ever performed, and does the command
                          log contain only allowed read-only commands?
* collection_completeness -- were all required observations attempted and
                          did strict commands succeed?
* p0_field_decision   -- given integrity + read-only + completeness all
                          hold, is this specific bundle (git state, human
                          safety, ROS/DDS environment, sensor/topic
                          presence) actually safe to treat as a field-
                          session candidate?
                          GO_CANDIDATE | NO_GO | FIXTURE_ONLY.

Decision order:
  integrity FAIL          → NOT_EVALUATED (skips all later layers)
  read_only FAIL          → NOT_EVALUATED
  completeness FAIL       → NO_GO
  field gates incomplete  → NO_GO
  fixture clean           → FIXTURE_ONLY
  real complete           → GO_CANDIDATE

A fixture-mode bundle can never reach GO_CANDIDATE: the best it can reach
is FIXTURE_ONLY (clean fixture data), and a fixture with genuine NO_GO
findings (e.g. operator absent) still honestly reports NO_GO -- fixture
mode only ever *caps* the ceiling, it never hides a real finding.

Exit codes:
  0 = real bundle, all layers PASS, GO_CANDIDATE
  1 = bundle_integrity FAIL or read_only_invariants FAIL
  2 = integrity + read-only PASS, completeness or field gates fail (NO_GO)
  3 = fixture bundle, all layers PASS, FIXTURE_ONLY
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
P0_DIR = THIS_FILE.parent
sys.path.insert(0, str(P0_DIR))
import p0_evidence_schema as schema  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"

# ---------------------------------------------------------------------------
# Command-log allowlist (Fase 2H.2.5)
# ---------------------------------------------------------------------------
# Each entry: label_pattern -> (executable, required_subcommand_prefix)
# label_pattern is a regex matched against the log entry's "label" field.
# Entries with label_pattern None match any label and apply to generic checks.

_FORBIDDEN_COMMAND_SUBSTRINGS = (
    "send_goal", "topic pub", "service call", "lifecycle set",
    "param set", "launch", "unitree", "lowcmd", "lowstate",
    "sport_mode", "loco", "damp", "stand", "sit", "walk",
    "cmd_vel_published", "nav_vel",
)

_ALLOWED_GIT_SUBCOMMANDS = frozenset({
    "branch --show-current",
    "rev-parse HEAD",
    "status --short --branch --untracked-files=all",
    "remote get-url origin",
})

_ALLOWED_ROS2_SUBCOMMANDS = frozenset({
    "node list",
    "topic list -t",
    "service list -t",
    "action list -t",
})

# Topics allowed for echo --once (no arbitrary topic)
_ALLOWED_ECHO_TOPICS = frozenset({"/tf_static", "/odom"})

# v2: explicit label-based allowlist
_ALLOWED_LABEL_PATTERNS = (
    re.compile(r"^git_(branch|head|status|remote_origin)$"),
    re.compile(r"^ros2_(node|topic|service|action)_list$"),
    re.compile(r"^(tf_static|odom)_echo_once$"),
    re.compile(r"^topic_info_[a-z0-9_]+$"),
    re.compile(r"^topic_hz_[a-z0-9_]+$"),
    re.compile(r"^cmd_vel_info_[a-z0-9_]+$"),
)


def _label_allowed(label: str) -> bool:
    return any(p.match(label) for p in _ALLOWED_LABEL_PATTERNS)


def _argv_safe(argv: "list") -> "str | None":
    """Returns None if argv is safe, or an error code string if not."""
    if not isinstance(argv, list):
        return "ARGV_NOT_A_LIST"
    if not argv:
        return "ARGV_EMPTY"
    for item in argv:
        if not isinstance(item, str):
            return "ARGV_NON_STRING_ELEMENT"
    joined = " ".join(str(a) for a in argv)
    for forbidden in _FORBIDDEN_COMMAND_SUBSTRINGS:
        if forbidden in joined.lower():
            return f"FORBIDDEN_COMMAND_SUBSTRING:{forbidden}"
    return None


def check_command_log(command_log_doc: "dict | None") -> "list[str]":
    """Audits every entry in the command log for structure and allowlist
    compliance. Returns a list of violation codes."""
    violations: "list[str]" = []
    if not isinstance(command_log_doc, dict):
        return violations
    commands = command_log_doc.get("commands")
    if not isinstance(commands, list):
        violations.append("COMMAND_LOG_NOT_A_LIST")
        return violations
    for i, entry in enumerate(commands):
        if not isinstance(entry, dict):
            violations.append(f"COMMAND_LOG_ENTRY_NOT_DICT:index={i}")
            continue
        label = entry.get("label")
        argv = entry.get("argv")
        exit_code = entry.get("exit_code")
        timed_out = entry.get("timed_out")
        ro_class = entry.get("read_only_classification")
        if not isinstance(label, str) or not label:
            violations.append(f"COMMAND_LOG_LABEL_MISSING:index={i}")
            continue
        if not isinstance(exit_code, int):
            violations.append(f"COMMAND_LOG_EXIT_CODE_NOT_INT:label={label}")
        if not isinstance(timed_out, bool):
            violations.append(f"COMMAND_LOG_TIMED_OUT_NOT_BOOL:label={label}")
        if ro_class != "read_only":
            violations.append(f"COMMAND_LOG_NOT_READ_ONLY:label={label}")
        if not _label_allowed(label):
            violations.append(f"COMMAND_LOG_LABEL_NOT_ALLOWED:{label}")
        argv_error = _argv_safe(argv)
        if argv_error is not None:
            violations.append(f"COMMAND_LOG_ARGV_UNSAFE:{label}:{argv_error}")
    return violations


def check_collection_completeness(command_log_doc: "dict | None", docs: "dict") -> "list[str]":
    """Checks that all strict (required for GO) commands were attempted,
    exited with code 0, and did not time out. Returns failure codes."""
    failures: "list[str]" = []
    if not isinstance(command_log_doc, dict):
        return failures
    commands = command_log_doc.get("commands", [])
    if not isinstance(commands, list):
        return failures
    by_label = {e.get("label"): e for e in commands if isinstance(e, dict)}

    # Strict commands: must be present, exit_code=0, timed_out=False
    strict_labels = (
        "git_branch", "git_head", "git_status", "git_remote_origin",
        "ros2_node_list", "ros2_topic_list", "ros2_service_list", "ros2_action_list",
    )
    for label in strict_labels:
        entry = by_label.get(label)
        if entry is None:
            failures.append(f"STRICT_COMMAND_MISSING:{label}")
            continue
        if entry.get("exit_code") != 0:
            failures.append(f"STRICT_COMMAND_FAILED:{label}:exit={entry.get('exit_code')}")
        if entry.get("timed_out") is True:
            failures.append(f"STRICT_COMMAND_TIMED_OUT:{label}")

    # Bounded observation commands: a timeout is acceptable only if
    # parseable evidence was produced; without evidence it's a failure.
    bounded_labels = ("tf_static_echo_once", "odom_echo_once")
    for label in bounded_labels:
        entry = by_label.get(label)
        if entry is None:
            failures.append(f"BOUNDED_COMMAND_MISSING:{label}")
            continue
        stdout = entry.get("stdout", "")
        if entry.get("timed_out") is True and not stdout.strip():
            failures.append(f"BOUNDED_COMMAND_TIMEOUT_NO_EVIDENCE:{label}")

    return failures


# ---------------------------------------------------------------------------
# Bundle loading helpers
# ---------------------------------------------------------------------------


def _load(evidence_dir: Path, filename: str, errors: list) -> "dict | None":
    path = evidence_dir / filename
    data, error_code = schema.load_json_file(path)
    if error_code is not None:
        errors.append(error_code)
        return None
    if not isinstance(data, dict):
        errors.append(f"NOT_AN_OBJECT:{filename}")
        return None
    return data


def _check_schema_envelope(name: str, data: dict, errors: list) -> None:
    if data.get("schema_version") != schema.SCHEMA_VERSION:
        errors.append(f"SCHEMA_VERSION_MISMATCH:{name}:got={data.get('schema_version')!r}")
    if not data.get("session_id"):
        errors.append(f"SESSION_ID_MISSING:{name}")


def _check_session_id_consistency(docs: "dict[str, dict]", errors: list) -> None:
    session_ids = {name: doc.get("session_id") for name, doc in docs.items() if doc is not None}
    distinct = set(session_ids.values())
    if len(distinct) > 1:
        errors.append(f"SESSION_ID_INCONSISTENT:{session_ids}")


def _check_sidecar(evidence_dir: Path, errors: list) -> "str | None":
    """Validates the manifest sidecar and returns the expected manifest hash
    (or None on failure)."""
    sidecar_path = evidence_dir / schema.HASH_MANIFEST_SIDECAR
    if sidecar_path.is_symlink():
        errors.append("SIDECAR_IS_SYMLINK")
        return None
    if not sidecar_path.is_file():
        errors.append("SIDECAR_MISSING")
        return None
    try:
        raw = sidecar_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        errors.append(f"SIDECAR_READ_FAILED:{exc}")
        return None
    if not re.match(r"^[0-9a-f]{64}$", raw):
        errors.append(f"SIDECAR_INVALID_FORMAT:got={raw!r}")
        return None
    manifest_path = evidence_dir / schema.HASH_MANIFEST
    if manifest_path.is_file():
        actual_hash = schema.sha256_file(manifest_path)
        if actual_hash != raw:
            errors.append(f"SIDECAR_HASH_MISMATCH:expected={raw}:got={actual_hash}")
            return None
    return raw


def _check_file_safety(evidence_dir: Path, filenames: "tuple[str, ...]", errors: list) -> None:
    for filename in filenames:
        path = evidence_dir / filename
        try:
            lst = path.lstat()
        except OSError:
            continue  # Already reported as MISSING_FILE by _load.
        if stat.S_ISLNK(lst.st_mode):
            errors.append(f"FILE_IS_SYMLINK:{filename}")
        elif not stat.S_ISREG(lst.st_mode):
            errors.append(f"FILE_NOT_REGULAR:{filename}")
        if hasattr(lst, "st_nlink") and lst.st_nlink != 1:
            errors.append(f"FILE_UNEXPECTED_NLINK:{filename}")
        if hasattr(os, "getuid") and hasattr(lst, "st_uid") and lst.st_uid != os.getuid():
            errors.append(f"FILE_WRONG_OWNER:{filename}")
        # Windows does not enforce Unix permission bits; skip on win32.
        if sys.platform != "win32" and hasattr(lst, "st_mode"):
            mode = stat.S_IMODE(lst.st_mode)
            if mode & 0o077:
                errors.append(f"FILE_PERMISSIONS_TOO_OPEN:{filename}:mode={oct(mode)}")


def _check_dir_safety(evidence_dir: Path, errors: list) -> None:
    try:
        lst = evidence_dir.lstat()
    except OSError as exc:
        errors.append(f"EVIDENCE_DIR_STAT_FAILED:{exc}")
        return
    if stat.S_ISLNK(lst.st_mode):
        errors.append("EVIDENCE_DIR_IS_SYMLINK")
        return
    if not stat.S_ISDIR(lst.st_mode):
        errors.append("EVIDENCE_DIR_NOT_A_DIRECTORY")
        return
    if hasattr(os, "getuid") and hasattr(lst, "st_uid") and lst.st_uid != os.getuid():
        errors.append("EVIDENCE_DIR_WRONG_OWNER")
    # Windows does not enforce Unix permission bits; skip on win32.
    if sys.platform != "win32" and hasattr(lst, "st_mode"):
        mode = stat.S_IMODE(lst.st_mode)
        if mode & 0o077:
            errors.append(f"EVIDENCE_DIR_PERMISSIONS_TOO_OPEN:mode={oct(mode)}")


def _check_manifest(evidence_dir: Path, manifest: "dict | None", errors: list) -> None:
    if manifest is None:
        return
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        errors.append("HASH_MANIFEST_EMPTY_OR_MALFORMED")
        return
    covered = set()
    filenames_seen: "list[str]" = []
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("HASH_MANIFEST_ENTRY_MALFORMED")
            continue
        fname = entry.get("filename")
        expected_sha = entry.get("sha256")
        if not isinstance(fname, str) or not isinstance(expected_sha, str) or len(expected_sha) != 64:
            errors.append(f"HASH_MANIFEST_ENTRY_MALFORMED:{fname}")
            continue
        # Path safety checks on filename
        if "/" in fname or "\\" in fname:
            errors.append(f"MANIFEST_FILENAME_CONTAINS_SEPARATOR:{fname}")
            continue
        if ".." in fname:
            errors.append(f"MANIFEST_FILENAME_PATH_TRAVERSAL:{fname}")
            continue
        if not fname:
            errors.append("MANIFEST_FILENAME_EMPTY")
            continue
        if fname in covered:
            errors.append(f"MANIFEST_DUPLICATE_FILENAME:{fname}")
            continue
        covered.add(fname)
        filenames_seen.append(fname)
        target = evidence_dir / fname
        if not target.is_file():
            errors.append(f"HASH_TARGET_MISSING:{fname}")
            continue
        actual = schema.sha256_file(target)
        if actual != expected_sha:
            errors.append(f"HASH_MISMATCH:{fname}")
        size_bytes = entry.get("size_bytes")
        if isinstance(size_bytes, int) and size_bytes != target.stat().st_size:
            errors.append(f"SIZE_MISMATCH:{fname}")
    missing_from_manifest = set(schema.BUNDLE_DATA_FILES) - covered
    for fname in sorted(missing_from_manifest):
        errors.append(f"MANIFEST_DOES_NOT_COVER:{fname}")
    extra_in_manifest = covered - set(schema.BUNDLE_DATA_FILES)
    for fname in sorted(extra_in_manifest):
        errors.append(f"MANIFEST_EXTRA_FILENAME:{fname}")


def check_bundle_integrity(
    evidence_dir: Path, docs: "dict[str, dict]", manifest: "dict | None"
) -> "list[str]":
    errors: "list[str]" = []
    _check_dir_safety(evidence_dir, errors)
    _check_sidecar(evidence_dir, errors)
    for name, doc in docs.items():
        if doc is not None:
            _check_schema_envelope(name, doc, errors)
    _check_session_id_consistency(docs, errors)
    _check_file_safety(evidence_dir, schema.ALL_BUNDLE_FILES, errors)
    _check_manifest(evidence_dir, manifest, errors)

    meta = docs.get(schema.SESSION_META)
    if isinstance(meta, dict):
        for field in schema.MUST_BE_FALSE_FIELDS:
            if field not in meta:
                errors.append(f"READONLY_FIELD_MISSING:{field}")

    graph = docs.get(schema.ROS_GRAPH)
    if isinstance(graph, dict):
        for field in schema.GRAPH_LIST_FIELDS:
            if field not in graph:
                errors.append(f"GRAPH_FIELD_MISSING:{field}")
            elif not isinstance(graph[field], list):
                errors.append(f"GRAPH_FIELD_NOT_LIST:{field}")

    safety = docs.get(schema.SAFETY_HUMAN_CHECKLIST)
    if isinstance(safety, dict):
        for field in schema.SAFETY_REQUIRED_DEFINED_FIELDS:
            if field not in safety:
                errors.append(f"SAFETY_FIELD_UNDEFINED:{field}")
    return errors


def check_read_only_invariants(
    docs: "dict[str, dict]", command_log_doc: "dict | None"
) -> "list[str]":
    errors: "list[str]" = []
    meta = docs.get(schema.SESSION_META)
    if not isinstance(meta, dict):
        return errors  # Already an integrity failure; do not double-report.
    for field in schema.MUST_BE_FALSE_FIELDS:
        if field in meta and meta[field] is not False:
            errors.append(f"READONLY_FIELD_NOT_FALSE:{field}={meta[field]!r}")
    # Command log audit
    command_violations = check_command_log(command_log_doc)
    errors.extend(command_violations)
    return errors


def check_field_decision(
    docs: "dict[str, dict]",
    expected_head: str,
    expected_branch: str,
) -> "tuple[list[str], list[str]]":
    """Returns (no_go_findings, warnings). Never mixes the two: a warning
    alone never blocks GO_CANDIDATE, a NO_GO finding always does."""
    no_go: "list[str]" = []
    warnings: "list[str]" = []
    meta = docs.get(schema.SESSION_META) or {}
    safety = docs.get(schema.SAFETY_HUMAN_CHECKLIST) or {}
    graph = docs.get(schema.ROS_GRAPH) or {}
    tf_loc = docs.get(schema.TF_AND_LOCALIZATION) or {}
    sensors_doc = docs.get(schema.SENSORS) or {}

    # --- Git gates ---
    actual_branch = meta.get("actual_branch")
    if actual_branch != expected_branch:
        no_go.append(f"BRANCH_NOT_OPERATIONAL:expected={expected_branch}:got={actual_branch!r}")
    actual_head = meta.get("actual_head")
    # v2: expected_head is always provided (required CLI arg)
    if actual_head is None or actual_head.lower() != expected_head.lower():
        no_go.append(f"HEAD_MISMATCH:expected={expected_head}:got={actual_head!r}")
    # Check coherence between session_meta.expected_head and the argument
    meta_expected_head = meta.get("expected_head")
    if meta_expected_head is not None and meta_expected_head.lower() != expected_head.lower():
        no_go.append(f"SESSION_META_EXPECTED_HEAD_MISMATCH:arg={expected_head}:meta={meta_expected_head!r}")
    if meta.get("head_matches_expected") is not True:
        no_go.append("HEAD_MATCHES_EXPECTED_NOT_TRUE")
    if meta.get("tracked_worktree_clean") is not True:
        no_go.append("TRACKED_WORKTREE_NOT_CLEAN")
    untracked_paths = meta.get("untracked_paths")
    if isinstance(untracked_paths, list):
        if not schema.untracked_allowlist_only(untracked_paths):
            no_go.append("UNTRACKED_OUTSIDE_ALLOWLIST")
    else:
        no_go.append("UNTRACKED_PATHS_MISSING")
    untracked_symlinks = meta.get("untracked_symlinks")
    if untracked_symlinks:
        no_go.append("UNTRACKED_SYMLINKS_PRESENT")

    # --- Human safety gates (v2: explicit, not inferred) ---
    for field in schema.SAFETY_REQUIRED_TRUE_FOR_GO:
        if safety.get(field) is not True:
            no_go.append(f"SAFETY_GATE_NOT_TRUE:{field}")
    # hardstop_tested_before_session: must be literally True; "unknown" → NO_GO in v2
    hardstop_tested = safety.get("hardstop_tested_before_session")
    if hardstop_tested is not True:
        no_go.append(f"HARDSTOP_NOT_TESTED_BEFORE_SESSION:got={hardstop_tested!r}")
    # operator_identity_or_role must be non-empty for real mode
    op_role = safety.get("operator_identity_or_role")
    if not op_role or not str(op_role).strip():
        no_go.append("OPERATOR_ROLE_MISSING_OR_EMPTY")
    # hardstop_type must be non-empty
    hs_type = safety.get("hardstop_type")
    if not hs_type or not str(hs_type).strip():
        no_go.append("HARDSTOP_TYPE_MISSING_OR_EMPTY")

    # --- ROS / DDS environment gates ---
    if meta.get("ros_distro") != schema.EXPECTED_ROS_DISTRO:
        no_go.append(f"ROS_DISTRO_MISMATCH:got={meta.get('ros_distro')!r}")
    if meta.get("rmw_implementation") != schema.EXPECTED_RMW_IMPLEMENTATION:
        no_go.append(f"RMW_IMPLEMENTATION_MISMATCH:got={meta.get('rmw_implementation')!r}")

    # --- v2: collection mode check ---
    collection_mode = meta.get("collection_mode")
    if collection_mode not in (schema.COLLECTION_MODE_FIXTURE, schema.COLLECTION_MODE_REAL):
        no_go.append(f"COLLECTION_MODE_UNKNOWN:{collection_mode!r}")

    # --- Critical topic presence with type and publisher validation ---
    topics = graph.get("topics")
    topic_map: "dict[str, dict]" = {}
    if isinstance(topics, list):
        for t in topics:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                topic_map[t["name"]] = t
    # Required topics with types (from spec section 10.11)
    required_topic_types = {
        "/odom": "nav_msgs/msg/Odometry",
        "/scan": "sensor_msgs/msg/LaserScan",
        "/tf": "tf2_msgs/msg/TFMessage",
        "/tf_static": "tf2_msgs/msg/TFMessage",
        "/map": "nav_msgs/msg/OccupancyGrid",
        "/map_metadata": "nav_msgs/msg/MapMetaData",
    }
    for topic_name, expected_type in required_topic_types.items():
        if topic_name not in topic_map:
            no_go.append(f"CRITICAL_TOPIC_MISSING:{topic_name}")
        else:
            t_entry = topic_map[topic_name]
            if t_entry.get("type") and t_entry["type"] != expected_type:
                no_go.append(f"CRITICAL_TOPIC_WRONG_TYPE:{topic_name}:got={t_entry['type']!r}")

    # --- TF / odom gates ---
    odom_present = "/odom" in topic_map
    if not odom_present:
        no_go.append("ODOM_TOPIC_MISSING")
    else:
        tf_doc = tf_loc
        if not tf_doc.get("single_sample_odom"):
            no_go.append("ODOM_SAMPLE_MISSING")
        if not tf_doc.get("candidate_odom_frame_id"):
            no_go.append("ODOM_FRAME_ID_MISSING")
        if not tf_doc.get("candidate_child_frame_id"):
            no_go.append("ODOM_CHILD_FRAME_ID_MISSING")

    # TF edges: any required edge not in tf_edges_observed → NO_GO
    tf_edges_observed = tf_loc.get("tf_edges_observed", [])
    required_edges = tf_loc.get("required_tf_edges", list(schema.REQUIRED_TF_EDGES))
    for edge in required_edges:
        if edge not in tf_edges_observed:
            no_go.append(f"TF_EDGE_NOT_OBSERVED:{edge}")

    # --- Scan gates ---
    sensors = sensors_doc.get("sensors") or {}
    scan_info = sensors.get("/scan") or {}
    if not scan_info.get("present"):
        no_go.append("SCAN_NOT_PRESENT")
    else:
        pub_count = scan_info.get("publisher_count")
        if pub_count is not None and pub_count < 1:
            no_go.append("SCAN_NO_PUBLISHER")
        hz = scan_info.get("frequency_result")
        if hz is not None and hz <= 0:
            no_go.append("SCAN_FREQUENCY_ZERO_OR_NEGATIVE")
        # If hz was attempted but is None (no parseable result) → NO_GO
        if scan_info.get("frequency_attempted") and hz is None:
            no_go.append("SCAN_FREQUENCY_NOT_PARSEABLE")

    # Optional sensors: absence is warning only
    for topic in schema.SENSOR_TOPICS:
        if topic == "/scan":
            continue
        info = sensors.get(topic) or {}
        if not info.get("present"):
            warnings.append(f"SENSOR_NOT_DISCOVERED:{topic}")

    # --- cmd_vel chain ---
    cmd_doc = docs.get(schema.CMD_VEL_CHAIN) or {}
    topics_cv = cmd_doc.get("topics") or {}
    # Unexpected global /cmd_vel → NO_GO
    if cmd_doc.get("unexpected_global_cmd_vel"):
        no_go.append("UNEXPECTED_GLOBAL_CMD_VEL")
    # /cmd_vel_raw and /cmd_vel_safe must be present with publishers and subscribers
    for cv_topic in ("/cmd_vel_raw", "/cmd_vel_safe"):
        info = topics_cv.get(cv_topic) or {}
        if not info.get("present"):
            no_go.append(f"CMD_VEL_TOPIC_MISSING:{cv_topic}")
        else:
            pub_c = info.get("publisher_count")
            sub_c = info.get("subscription_count")
            if pub_c is not None and pub_c < 1:
                no_go.append(f"CMD_VEL_NO_PUBLISHER:{cv_topic}")
            if sub_c is not None and sub_c < 1:
                no_go.append(f"CMD_VEL_NO_SUBSCRIBER:{cv_topic}")
    if not cmd_doc.get("controller_server_observed"):
        no_go.append("CONTROLLER_SERVER_NOT_OBSERVED")
    if not cmd_doc.get("collision_monitor_observed"):
        no_go.append("COLLISION_MONITOR_NOT_OBSERVED")

    if tf_loc.get("l2_odometry") == schema.READINESS_NOT_READY:
        warnings.append("L2_ODOMETRY_NOT_READY")
    if tf_loc.get("l3_localization_map") == schema.READINESS_NOT_READY:
        warnings.append("L3_LOCALIZATION_MAP_NOT_READY")

    return no_go, warnings


def validate_evidence_dir(
    evidence_dir: Path,
    expected_head: str,
    expected_branch: str = schema.EXPECTED_BRANCH,
) -> dict:
    integrity_errors: "list[str]" = []
    docs: "dict[str, dict]" = {}
    for filename in schema.BUNDLE_DATA_FILES:
        docs[filename] = _load(evidence_dir, filename, integrity_errors)
    manifest = _load(evidence_dir, schema.HASH_MANIFEST, integrity_errors)
    command_log_doc = docs.get(schema.COMMAND_LOG)

    integrity_errors += check_bundle_integrity(evidence_dir, docs, manifest)
    bundle_integrity = FAIL if integrity_errors else PASS

    read_only_errors: "list[str]" = []
    completeness_errors: "list[str]" = []
    no_go_findings: "list[str]" = []
    warnings: "list[str]" = []
    fixture_mode = bool((docs.get(schema.SESSION_META) or {}).get("fixture_mode"))

    if bundle_integrity == PASS:
        read_only_errors = check_read_only_invariants(docs, command_log_doc)
    read_only_invariants = FAIL if read_only_errors else PASS

    if bundle_integrity == PASS and read_only_invariants == PASS:
        completeness_errors = check_collection_completeness(command_log_doc, docs)
    collection_completeness = FAIL if completeness_errors else PASS

    if bundle_integrity == PASS and read_only_invariants == PASS:
        no_go_findings, warnings = check_field_decision(docs, expected_head, expected_branch)
        if completeness_errors:
            no_go_findings = [f"COLLECTION_COMPLETENESS_FAIL:see_completeness_errors"] + no_go_findings

    if bundle_integrity != PASS or read_only_invariants != PASS:
        p0_field_decision = "NOT_EVALUATED"
    elif no_go_findings or completeness_errors:
        p0_field_decision = schema.DECISION_NO_GO
    elif fixture_mode:
        p0_field_decision = schema.DECISION_FIXTURE_ONLY
    else:
        p0_field_decision = schema.DECISION_GO_CANDIDATE

    return {
        "evidence_dir": str(evidence_dir),
        "bundle_integrity": bundle_integrity,
        "read_only_invariants": read_only_invariants,
        "collection_completeness": collection_completeness,
        "p0_field_decision": p0_field_decision,
        "fixture_mode": fixture_mode,
        "errors": integrity_errors + read_only_errors + completeness_errors + no_go_findings,
        "integrity_errors": integrity_errors,
        "read_only_errors": read_only_errors,
        "completeness_errors": completeness_errors,
        "no_go_findings": no_go_findings,
        "warnings": warnings,
    }


def _exit_code(result: dict) -> int:
    if result["bundle_integrity"] != PASS or result["read_only_invariants"] != PASS:
        return 1
    if result["p0_field_decision"] == schema.DECISION_NO_GO:
        return 2
    if result["p0_field_decision"] == schema.DECISION_FIXTURE_ONLY:
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir", type=Path)
    # v2: --expected-head is required
    parser.add_argument(
        "--expected-head", dest="expected_head", required=True,
        help="Expected 40-hex git HEAD SHA (required).",
    )
    parser.add_argument(
        "--expected-branch", dest="expected_branch", default=schema.EXPECTED_BRANCH,
        help=f"Expected branch name (default: {schema.EXPECTED_BRANCH}).",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    # Validate expected_head format
    head = args.expected_head.lower()
    if not re.match(r"^[0-9a-f]{40}$", head):
        print(
            json.dumps({"ok": False, "status": f"INVALID_EXPECTED_HEAD:{args.expected_head!r}"}),
            file=sys.stderr,
        )
        return 1

    result = validate_evidence_dir(args.evidence_dir, head, args.expected_branch)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return _exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
