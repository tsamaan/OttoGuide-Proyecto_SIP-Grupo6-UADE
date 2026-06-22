#!/usr/bin/env python3
"""Fase 2H.2.3 -- offline contract validator for a P0 *physical read-only*
evidence bundle.

P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED. This validator NEVER touches a
robot, a network, or ROS. It only inspects a directory of JSON files that a
future, explicitly-authorized P0 session would produce, and proves -- purely
from their contents -- that the session was read-only: no movement command, no
goal, no cmd_vel publication, no damp/control invocation, the working branch
was the validated operational branch (`robot`), the human-safety fields were
recorded, the ROS graph fields are well-formed lists, and every file named in
the hash manifest is present with a matching SHA-256.

Fields that a real session genuinely could not know stay null / "unknown" /
"not_collected"; this validator never invents physical data, it only checks
the read-only *invariants*.

Exit code 0 = valid read-only bundle; non-zero = at least one violation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

OPERATIONAL_BRANCH = "robot"

SESSION_META = "p0_session_meta.json"
ROS_GRAPH = "p0_ros_graph.json"
HASH_MANIFEST = "p0_hash_manifest.json"

# Read-only invariants that must be explicitly false in the session meta.
MUST_BE_FALSE = (
    "movement_command_sent",
    "goal_sent",
    "cmd_vel_published",
    "damp_invoked",
)
# Human-safety fields that must be *defined* (not missing), though their value
# may legitimately be a recorded boolean.
MUST_BE_DEFINED = (
    "operator_present",
    "hardstop_present",
)
GRAPH_LIST_FIELDS = ("nodes", "actions", "topics", "services")

# Sentinel values that are acceptable for unknown/uncollected physical data.
_ALLOWED_UNKNOWN = (None, "unknown", "not_collected", "null")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_evidence_dir(evidence_dir: Path) -> "tuple[bool, list[str]]":
    errors: list[str] = []

    def _load(name: str) -> "dict | None":
        p = evidence_dir / name
        if not p.is_file():
            errors.append(f"MISSING_FILE:{name}")
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"INVALID_JSON:{name}:{exc}")
            return None

    meta = _load(SESSION_META)
    graph = _load(ROS_GRAPH)
    manifest = _load(HASH_MANIFEST)

    # --- session meta invariants ---
    if isinstance(meta, dict):
        branch = meta.get("branch")
        if branch != OPERATIONAL_BRANCH:
            errors.append(f"BRANCH_NOT_OPERATIONAL:expected={OPERATIONAL_BRANCH}:got={branch!r}")
        for field in MUST_BE_FALSE:
            if field not in meta:
                errors.append(f"READONLY_FIELD_MISSING:{field}")
            elif meta[field] is not False:
                errors.append(f"READONLY_FIELD_NOT_FALSE:{field}={meta[field]!r}")
        for field in MUST_BE_DEFINED:
            if field not in meta:
                errors.append(f"SAFETY_FIELD_UNDEFINED:{field}")
    # _load already recorded MISSING_FILE if meta is None.

    # --- ROS graph well-formedness ---
    if isinstance(graph, dict):
        for field in GRAPH_LIST_FIELDS:
            if field not in graph:
                errors.append(f"GRAPH_FIELD_MISSING:{field}")
            elif not isinstance(graph[field], list):
                errors.append(f"GRAPH_FIELD_NOT_LIST:{field}")

    # --- hash manifest: present + every referenced file matches ---
    if isinstance(manifest, dict):
        if not manifest:
            errors.append("HASH_MANIFEST_EMPTY")
        for fname, expected_sha in manifest.items():
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                errors.append(f"HASH_MALFORMED:{fname}")
                continue
            target = evidence_dir / fname
            if not target.is_file():
                errors.append(f"HASH_TARGET_MISSING:{fname}")
                continue
            actual = _sha256(target)
            if actual != expected_sha:
                errors.append(f"HASH_MISMATCH:{fname}")

    return (len(errors) == 0), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    ok, errors = validate_evidence_dir(args.evidence_dir)
    result = {
        "evidence_dir": str(args.evidence_dir),
        "ok": ok,
        "decision": "PASS" if ok else "FAIL",
        "errors": errors,
        "p0_status": "PREPARED_NOT_AUTHORIZED",
        "physical_execution_performed": False,
    }
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
