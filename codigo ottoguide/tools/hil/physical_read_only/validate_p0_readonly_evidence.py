#!/usr/bin/env python3
"""Fase 2H.2.4 -- offline contract validator for a P0 *physical read-only*
evidence bundle.

P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED. This validator NEVER
touches a robot, a network, or ROS; it only inspects a directory of JSON
files a collector run (real or fixture) produced, and computes three
*independent* decision layers -- never mixed into one boolean:

* bundle_integrity   -- are all required files present, schema-versioned,
                         well-formed, and does every file's hash match the
                         manifest?
* read_only_invariants -- does the bundle itself assert (truthfully, by
                         the collector's own construction) that no
                         movement/goal/cmd_vel/control/lifecycle/parameter
                         action was ever performed?
* p0_field_decision  -- given integrity and read-only both hold, is this
                         specific bundle (git state, human safety, ROS/DDS
                         environment, sensor/topic presence) actually safe
                         to treat as a field-session candidate?
                         GO_CANDIDATE | NO_GO | FIXTURE_ONLY.

A fixture-mode bundle can never reach GO_CANDIDATE: the best it can reach
is FIXTURE_ONLY (clean fixture data), and a fixture with genuine NO_GO
findings (e.g. operator absent) still honestly reports NO_GO -- fixture
mode only ever *caps* the ceiling, it never hides a real finding.

Exit codes:
  0 = real bundle, integrity PASS, read-only PASS, GO_CANDIDATE
  1 = bundle_integrity FAIL or read_only_invariants FAIL
  2 = integrity + read-only PASS, but NO_GO
  3 = fixture bundle, integrity + read-only PASS, FIXTURE_ONLY
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
P0_DIR = THIS_FILE.parent
sys.path.insert(0, str(P0_DIR))
import p0_evidence_schema as schema  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"


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
        errors.append(f"SCHEMA_VERSION_MISMATCH:{name}")
    if not data.get("session_id"):
        errors.append(f"SESSION_ID_MISSING:{name}")


def _check_session_id_consistency(docs: "dict[str, dict]", errors: list) -> None:
    session_ids = {name: doc.get("session_id") for name, doc in docs.items() if doc is not None}
    distinct = set(session_ids.values())
    if len(distinct) > 1:
        errors.append(f"SESSION_ID_INCONSISTENT:{session_ids}")


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


def _check_manifest(evidence_dir: Path, manifest: "dict | None", errors: list) -> None:
    if manifest is None:
        return
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        errors.append("HASH_MANIFEST_EMPTY_OR_MALFORMED")
        return
    covered = set()
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("HASH_MANIFEST_ENTRY_MALFORMED")
            continue
        fname = entry.get("filename")
        expected_sha = entry.get("sha256")
        if not isinstance(fname, str) or not isinstance(expected_sha, str) or len(expected_sha) != 64:
            errors.append(f"HASH_MANIFEST_ENTRY_MALFORMED:{fname}")
            continue
        covered.add(fname)
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


def check_bundle_integrity(evidence_dir: Path, docs: "dict[str, dict]", manifest: "dict | None") -> "list[str]":
    errors: "list[str]" = []
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


def check_read_only_invariants(docs: "dict[str, dict]") -> "list[str]":
    errors: "list[str]" = []
    meta = docs.get(schema.SESSION_META)
    if not isinstance(meta, dict):
        return errors  # Already an integrity failure; do not double-report.
    for field in schema.MUST_BE_FALSE_FIELDS:
        if field in meta and meta[field] is not False:
            errors.append(f"READONLY_FIELD_NOT_FALSE:{field}={meta[field]!r}")
    return errors


def check_field_decision(
    docs: "dict[str, dict]", expected_head: "str | None", expected_branch: str,
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
    if expected_head is not None and actual_head != expected_head:
        no_go.append(f"HEAD_MISMATCH:expected={expected_head}:got={actual_head!r}")
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

    # --- Human safety gates ---
    for field in schema.SAFETY_REQUIRED_TRUE_FOR_GO:
        if safety.get(field) is not True:
            no_go.append(f"SAFETY_GATE_NOT_TRUE:{field}")
    hardstop_tested = safety.get("hardstop_tested_before_session")
    if hardstop_tested is False:
        no_go.append("HARDSTOP_NOT_TESTED_BEFORE_SESSION")
    elif hardstop_tested in (None, "unknown"):
        warnings.append("HARDSTOP_TESTED_BEFORE_SESSION_UNKNOWN")

    # --- ROS / DDS environment gates ---
    if meta.get("ros_distro") != schema.EXPECTED_ROS_DISTRO:
        no_go.append(f"ROS_DISTRO_MISMATCH:got={meta.get('ros_distro')!r}")
    if meta.get("rmw_implementation") != schema.EXPECTED_RMW_IMPLEMENTATION:
        no_go.append(f"RMW_IMPLEMENTATION_MISMATCH:got={meta.get('rmw_implementation')!r}")

    # --- Critical topic presence (NO_GO only -- never an integrity issue,
    #     and never auto-promotes L2/L3 readiness). ---
    topics = graph.get("topics")
    topic_names = {t.get("name") for t in topics} if isinstance(topics, list) else set()
    for critical in ("/odom", "/scan", "/tf", "/tf_static"):
        if critical not in topic_names:
            no_go.append(f"CRITICAL_TOPIC_MISSING:{critical}")
    if tf_loc.get("l2_odometry") == schema.READINESS_NOT_READY:
        warnings.append("L2_ODOMETRY_NOT_READY")
    if tf_loc.get("l3_localization_map") == schema.READINESS_NOT_READY:
        warnings.append("L3_LOCALIZATION_MAP_NOT_READY")

    sensors = sensors_doc.get("sensors")
    if isinstance(sensors, dict):
        for topic, detail in sensors.items():
            if isinstance(detail, dict) and detail.get("present") is False:
                warnings.append(f"SENSOR_NOT_DISCOVERED:{topic}")

    return no_go, warnings


def validate_evidence_dir(
    evidence_dir: Path, expected_head: "str | None" = None, expected_branch: str = schema.EXPECTED_BRANCH,
) -> dict:
    integrity_errors: "list[str]" = []
    docs: "dict[str, dict]" = {}
    for filename in schema.BUNDLE_DATA_FILES:
        docs[filename] = _load(evidence_dir, filename, integrity_errors)
    manifest = _load(evidence_dir, schema.HASH_MANIFEST, integrity_errors)

    integrity_errors += check_bundle_integrity(evidence_dir, docs, manifest)
    bundle_integrity = FAIL if integrity_errors else PASS

    read_only_errors = check_read_only_invariants(docs)
    read_only_invariants = FAIL if read_only_errors else PASS

    no_go_findings: "list[str]" = []
    warnings: "list[str]" = []
    fixture_mode = bool((docs.get(schema.SESSION_META) or {}).get("fixture_mode"))

    if bundle_integrity == PASS and read_only_invariants == PASS:
        no_go_findings, warnings = check_field_decision(docs, expected_head, expected_branch)

    if bundle_integrity != PASS or read_only_invariants != PASS:
        p0_field_decision = "NOT_EVALUATED"
    elif no_go_findings:
        p0_field_decision = schema.DECISION_NO_GO
    elif fixture_mode:
        p0_field_decision = schema.DECISION_FIXTURE_ONLY
    else:
        p0_field_decision = schema.DECISION_GO_CANDIDATE

    return {
        "evidence_dir": str(evidence_dir),
        "bundle_integrity": bundle_integrity,
        "read_only_invariants": read_only_invariants,
        "p0_field_decision": p0_field_decision,
        "fixture_mode": fixture_mode,
        "errors": integrity_errors + read_only_errors + no_go_findings,
        "integrity_errors": integrity_errors,
        "read_only_errors": read_only_errors,
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
    parser.add_argument("--expected-head", dest="expected_head")
    parser.add_argument("--expected-branch", dest="expected_branch", default=schema.EXPECTED_BRANCH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = validate_evidence_dir(args.evidence_dir, args.expected_head, args.expected_branch)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return _exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
