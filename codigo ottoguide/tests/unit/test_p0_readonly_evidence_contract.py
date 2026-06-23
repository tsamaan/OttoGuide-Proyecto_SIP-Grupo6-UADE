#!/usr/bin/env python3
"""Fase 2H.2.4 -- offline contract tests for the P0 physical READ-ONLY
pipeline (collector core + schema + validator). Supersedes the Fase
2H.2.3 skeleton-era version of this file: the collector is no longer a
shell script that only prints/discards commands, it is a real Python core
(collect_p0_readonly_evidence.py) wrapped by a minimal shell shim.

Three halves:

* Source contract: neither the shell wrapper nor the Python core contains
  any forbidden movement/control/launch/lifecycle command, no SSH/SCP/
  rsync/IP, no shell=True/eval, and the core's argv-only command tables
  are exactly what the docstring claims.

* Authorization contract: dry-run is the default; --execute-read-only and
  --fixture-dir are mutually exclusive; each requires its own environment
  variable; real execution requires every one of the five extra CLI
  gates.

* Validator behaviour: the three-layer decision (bundle_integrity,
  read_only_invariants, p0_field_decision) and its exit codes, against
  hand-built minimal bundles (the full collector->bundle->validator path
  is covered separately by test_p0_readonly_pipeline_e2e.py).

The shell wrapper is executed only for --help/bash -n in this file (never
--execute-read-only); the Python core is imported directly. Runs on every
platform.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
P0_DIR = CODE_ROOT / "tools" / "hil" / "physical_read_only"
WRAPPER = P0_DIR / "collect_p0_readonly_evidence.sh"
COLLECTOR_PY = P0_DIR / "collect_p0_readonly_evidence.py"
SCHEMA_PY = P0_DIR / "p0_evidence_schema.py"
VALIDATOR_PY = P0_DIR / "validate_p0_readonly_evidence.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = _load(SCHEMA_PY, "p0_evidence_schema")
collector = _load(COLLECTOR_PY, "collect_p0_readonly_evidence")
validator = _load(VALIDATOR_PY, "validate_p0_readonly_evidence")

FORBIDDEN_PATTERNS = (
    r"ros2\s+action\s+send_goal",
    r"ros2\s+topic\s+pub",
    r"ros2\s+service\s+call",
    r"ros2\s+lifecycle\s+set",
    r"ros2\s+launch",
    r"ros2\s+param\s+set",
    r"\bsport_mode\b",
    r"\blowcmd\b",
    r"\bloco\b",
    r"lowstate\s+write",
    r"\bdamp\b",
    r"\bstand\b",
    r"\bsit\b",
    r"\bwalk\b",
    r"unitree",
)
FORBIDDEN_NETWORK_PATTERNS = (r"\bssh\b", r"\bscp\b", r"\bsftp\b", r"\brsync\b", r"192\.168\.", r"\bping\b")


# ---------------------------------------------------------------------------
# Source contract
# ---------------------------------------------------------------------------


class TestShellWrapperSourceContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WRAPPER.is_file(), f"missing {WRAPPER}")
        self.src = WRAPPER.read_text(encoding="utf-8")

    def test_bash_syntax_valid(self):
        """POSIX only: on native Windows, "bash" on PATH commonly resolves
        to the WSL interop launcher (System32\\bash.exe), which cannot
        interpret a Windows-style host path and fails with an unrelated
        "No such file or directory" -- not a real syntax error. Git Bash
        (used elsewhere in this session) is a separate, non-PATH tool."""
        if os.name != "posix":
            self.skipTest("bash -n requires a real POSIX bash, not the Windows/WSL interop launcher")
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash not available on PATH")
        proc = subprocess.run([bash, "-n", str(WRAPPER)], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_no_forbidden_commands(self):
        for pattern in FORBIDDEN_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.src, re.IGNORECASE))

    def test_no_ssh_or_ip_or_remote(self):
        for pattern in FORBIDDEN_NETWORK_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.src, re.IGNORECASE))

    def test_no_eval_or_dynamic_shell(self):
        self.assertNotIn("eval ", self.src)
        self.assertNotIn("eval(", self.src)

    def test_wrapper_is_minimal_exec_only(self):
        """The wrapper must never branch on flag values itself (no
        --dry-run/--execute-read-only case handling) -- it forwards "$@"
        verbatim and lets the Python core hold every gate."""
        self.assertIn('exec "${PYTHON_BIN}" "${CORE_PY}" "$@"', self.src)
        self.assertNotIn("--execute-read-only)", self.src)
        self.assertNotIn("--dry-run)", self.src)


class TestPythonCoreSourceContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(COLLECTOR_PY.is_file(), f"missing {COLLECTOR_PY}")
        self.src = COLLECTOR_PY.read_text(encoding="utf-8")
        self.tree = ast.parse(self.src, filename=str(COLLECTOR_PY))

    def test_no_forbidden_commands(self):
        for pattern in FORBIDDEN_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.src, re.IGNORECASE))

    def test_no_ssh_or_ip_or_remote(self):
        for pattern in FORBIDDEN_NETWORK_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.src, re.IGNORECASE))

    def test_no_shell_true_or_eval_or_os_system(self):
        """Checks actual code constructs (AST), not prose: the module's own
        docstring legitimately discusses "shell=True" as something it does
        NOT do, which a naive substring search on raw source text would
        misfire on."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
                    self.fail(f"os.system(...) call found: {ast.dump(node)}")
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.fail(f"shell=True found: {ast.dump(node)}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "eval")

    def test_every_subprocess_run_call_uses_argv_list_literal(self):
        """Every subprocess.run(...) call's first positional argument must
        be a list/tuple literal (or a name bound to one elsewhere), never a
        formatted/concatenated string -- the structural guarantee that
        backs "argv-only, never a shell string". Deliberately scoped to
        calls on the `subprocess` module itself, not on this file's own
        ctx.run(label, argv) wrapper method (whose first argument is the
        command *label*, a plain string, by design)."""
        run_calls = [
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
        ]
        self.assertTrue(run_calls, "expected at least one subprocess.run call")
        for call in run_calls:
            self.assertTrue(call.args, "subprocess.run call with no positional argv argument")
            first = call.args[0]
            self.assertIsInstance(first, (ast.List, ast.Name), ast.dump(first))

    def test_dry_run_is_default_mode(self):
        mode = collector.resolve_mode(_ns())
        self.assertEqual(mode, "dry_run")

    def test_movement_invariant_fields_are_literal_false_constants(self):
        """AST-level guard: the seven read-only invariant fields must be
        assigned the literal constant False inside build_bundle's
        session_meta dict, never a variable/expression that could be
        influenced by fixture data or CLI input."""
        func = next(
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == "build_bundle"
        )
        dict_literals = [n for n in ast.walk(func) if isinstance(n, ast.Dict)]
        found = {}
        for d in dict_literals:
            for key, value in zip(d.keys, d.values):
                if isinstance(key, ast.Constant) and key.value in schema.MUST_BE_FALSE_FIELDS:
                    found[key.value] = value
        for field in schema.MUST_BE_FALSE_FIELDS:
            self.assertIn(field, found, f"{field} not assigned in build_bundle's session_meta dict")
            value_node = found[field]
            self.assertIsInstance(value_node, ast.Constant, ast.dump(value_node))
            self.assertIs(value_node.value, False, f"{field} must be the literal constant False")


def _ns(**overrides):
    from argparse import Namespace
    base = dict(
        dry_run=False, execute_read_only=False, fixture_dir=None,
        output_dir=Path("./p0_readonly_evidence"), expected_head=None,
        operator_present=None, hardstop_present=None, area_cleared=None,
        movement_not_authorized_acknowledged=None,
    )
    base.update(overrides)
    return Namespace(**base)


# ---------------------------------------------------------------------------
# Authorization contract
# ---------------------------------------------------------------------------


class TestAuthorizationContract(unittest.TestCase):
    def test_mode_conflict_rejected(self):
        args = _ns(execute_read_only=True, fixture_dir=Path("/tmp/x"))
        with self.assertRaises(collector.CollectorAuthorizationError) as ctx:
            collector.resolve_mode(args)
        self.assertEqual(ctx.exception.code, "MODE_CONFLICT")

    def test_fixture_without_env_rejected(self, monkeypatch=None):
        import os
        env_backup = os.environ.pop(collector.FIXTURE_MODE_ENV, None)
        try:
            args = _ns(fixture_dir=Path("/tmp/x"))
            with self.assertRaises(collector.CollectorAuthorizationError) as ctx:
                collector.resolve_mode(args)
            self.assertEqual(ctx.exception.code, "FIXTURE_MODE_NOT_AUTHORIZED")
        finally:
            if env_backup is not None:
                os.environ[collector.FIXTURE_MODE_ENV] = env_backup

    def test_execute_read_only_without_env_rejected(self):
        import os
        env_backup = os.environ.pop(collector.READ_ONLY_AUTHORIZED_ENV, None)
        try:
            args = _ns(
                execute_read_only=True, expected_head="0" * 40,
                operator_present="yes", hardstop_present="yes",
                area_cleared="yes", movement_not_authorized_acknowledged="yes",
            )
            with self.assertRaises(collector.CollectorAuthorizationError) as ctx:
                collector.resolve_mode(args)
            self.assertEqual(ctx.exception.code, "P0_NOT_AUTHORIZED")
        finally:
            if env_backup is not None:
                os.environ[collector.READ_ONLY_AUTHORIZED_ENV] = env_backup

    def test_execute_read_only_missing_gates_rejected_even_with_env(self):
        import os
        os.environ[collector.READ_ONLY_AUTHORIZED_ENV] = "YES"
        try:
            args = _ns(execute_read_only=True)  # every other gate left None/no
            with self.assertRaises(collector.CollectorAuthorizationError) as ctx:
                collector.resolve_mode(args)
            self.assertTrue(ctx.exception.code.startswith("P0_NOT_AUTHORIZED:"))
        finally:
            del os.environ[collector.READ_ONLY_AUTHORIZED_ENV]

    def test_execute_read_only_fully_gated_authorizes_real_mode(self):
        import os
        os.environ[collector.READ_ONLY_AUTHORIZED_ENV] = "YES"
        try:
            args = _ns(
                execute_read_only=True, expected_head="a" * 40,
                operator_present="yes", hardstop_present="yes",
                area_cleared="yes", movement_not_authorized_acknowledged="yes",
                output_dir=Path("/tmp/p0_real_mode_never_actually_run"),
            )
            self.assertEqual(collector.resolve_mode(args), "real")
        finally:
            del os.environ[collector.READ_ONLY_AUTHORIZED_ENV]

    def test_malformed_expected_head_rejected(self):
        import os
        os.environ[collector.READ_ONLY_AUTHORIZED_ENV] = "YES"
        try:
            args = _ns(
                execute_read_only=True, expected_head="not-a-sha",
                operator_present="yes", hardstop_present="yes",
                area_cleared="yes", movement_not_authorized_acknowledged="yes",
            )
            with self.assertRaises(collector.CollectorAuthorizationError):
                collector.resolve_mode(args)
        finally:
            del os.environ[collector.READ_ONLY_AUTHORIZED_ENV]


# ---------------------------------------------------------------------------
# Validator behaviour (hand-built minimal bundles)
# ---------------------------------------------------------------------------


def _envelope(session_id="s1"):
    return {"schema_version": schema.SCHEMA_VERSION, "session_id": session_id,
            "collected_at_utc": "2026-01-01T00:00:00Z", "collector_version": schema.COLLECTOR_VERSION}


def _write_good_bundle(d: Path, session_id="s1", fixture_mode=False) -> None:
    meta = {
        **_envelope(session_id),
        "actual_branch": "robot", "expected_branch": "robot",
        "actual_head": "a" * 40, "expected_head": "a" * 40, "head_matches_expected": True,
        "tracked_worktree_clean": True, "tracked_changes": [],
        "untracked_paths": ["codigo ottoguide/logs/mission_x.json"], "untracked_symlinks": [],
        "untracked_allowlist_only": True,
        "ros_distro": "foxy", "rmw_implementation": "rmw_cyclonedds_cpp",
        "fixture_mode": fixture_mode, "physical_execution_performed": not fixture_mode,
        "operator_present": True, "hardstop_present": True,
        "movement_command_sent": False, "goal_sent": False, "cmd_vel_published": False,
        "damp_invoked": False, "control_service_called": False,
        "lifecycle_changed": False, "parameter_changed": False,
    }
    graph = {**_envelope(session_id), "nodes": [], "topics": [
        {"name": "/odom"}, {"name": "/scan"}, {"name": "/tf"}, {"name": "/tf_static"},
    ], "services": [], "actions": [], "critical_actions": [], "critical_topics": []}
    tf_loc = {**_envelope(session_id), "l2_odometry": "CANDIDATE_OBSERVED_PENDING_ANALYSIS",
              "l3_localization_map": "CANDIDATE_OBSERVED_PENDING_ANALYSIS"}
    sensors = {**_envelope(session_id), "sensors": {}}
    cmd_vel = {**_envelope(session_id), "topics": {}}
    safety = {
        **_envelope(session_id),
        "operator_present": True, "operator_identity_or_role": "op",
        "hardstop_present": True, "hardstop_type": "estop",
        "hardstop_tested_before_session": True, "area_cleared": True,
        "robot_physically_supervised": True, "dual_control_prohibited_acknowledged": True,
        "movement_not_authorized_acknowledged": True, "notes": None,
    }
    cmdlog = {**_envelope(session_id), "commands": []}
    docs = {
        schema.SESSION_META: meta, schema.ROS_GRAPH: graph, schema.TF_AND_LOCALIZATION: tf_loc,
        schema.SENSORS: sensors, schema.CMD_VEL_CHAIN: cmd_vel, schema.SAFETY_HUMAN_CHECKLIST: safety,
        schema.COMMAND_LOG: cmdlog,
    }
    manifest_files = []
    for name, data in docs.items():
        path = d / name
        path.write_text(json.dumps(data), encoding="utf-8")
        manifest_files.append({"filename": name, "sha256": schema.sha256_file(path), "size_bytes": path.stat().st_size})
    manifest = {**_envelope(session_id), "files": manifest_files}
    (d / schema.HASH_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def _rehash(d: Path, filename: str) -> None:
    manifest = json.loads((d / schema.HASH_MANIFEST).read_text())
    for entry in manifest["files"]:
        if entry["filename"] == filename:
            entry["sha256"] = schema.sha256_file(d / filename)
            entry["size_bytes"] = (d / filename).stat().st_size
    (d / schema.HASH_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


class TestValidatorThreeLayerDecision(unittest.TestCase):
    def test_clean_real_bundle_is_go_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d, fixture_mode=False)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["read_only_invariants"], "PASS")
            self.assertEqual(result["p0_field_decision"], "GO_CANDIDATE")
            self.assertEqual(validator._exit_code(result), 0)

    def test_clean_fixture_bundle_is_fixture_only_never_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d, fixture_mode=True)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "FIXTURE_ONLY")
            self.assertEqual(validator._exit_code(result), 3)

    def test_missing_file_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            (d / schema.HASH_MANIFEST).unlink()
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertEqual(result["p0_field_decision"], "NOT_EVALUATED")
            self.assertEqual(validator._exit_code(result), 1)

    def test_hash_mismatch_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            data = json.loads((d / schema.ROS_GRAPH).read_text())
            data["nodes"] = ["tampered"]
            (d / schema.ROS_GRAPH).write_text(json.dumps(data), encoding="utf-8")
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("HASH_MISMATCH" in e for e in result["integrity_errors"]))
            self.assertEqual(validator._exit_code(result), 1)

    def test_movement_flag_true_fails_read_only_invariants(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["cmd_vel_published"] = True
            (d / schema.SESSION_META).write_text(json.dumps(meta), encoding="utf-8")
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["read_only_invariants"], "FAIL")
            self.assertEqual(result["p0_field_decision"], "NOT_EVALUATED")
            self.assertEqual(validator._exit_code(result), 1)

    def test_wrong_branch_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["actual_branch"] = "main"
            (d / schema.SESSION_META).write_text(json.dumps(meta), encoding="utf-8")
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["read_only_invariants"], "PASS")
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("BRANCH_NOT_OPERATIONAL" in e for e in result["no_go_findings"]))
            self.assertEqual(validator._exit_code(result), 2)

    def test_operator_absent_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            safety = json.loads((d / schema.SAFETY_HUMAN_CHECKLIST).read_text())
            safety["operator_present"] = False
            (d / schema.SAFETY_HUMAN_CHECKLIST).write_text(json.dumps(safety), encoding="utf-8")
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["operator_present"] = False
            (d / schema.SESSION_META).write_text(json.dumps(meta), encoding="utf-8")
            _rehash(d, schema.SAFETY_HUMAN_CHECKLIST)
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("operator_present" in e for e in result["no_go_findings"]))
            self.assertEqual(validator._exit_code(result), 2)

    def test_untracked_outside_allowlist_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["untracked_paths"] = ["some/other/path.txt"]
            (d / schema.SESSION_META).write_text(json.dumps(meta), encoding="utf-8")
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertIn("UNTRACKED_OUTSIDE_ALLOWLIST", result["no_go_findings"])

    def test_wrong_ros_distro_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["ros_distro"] = "jazzy"
            (d / schema.SESSION_META).write_text(json.dumps(meta), encoding="utf-8")
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("ROS_DISTRO_MISMATCH" in e for e in result["no_go_findings"]))

    def test_missing_critical_topic_is_no_go_not_integrity_failure(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            graph = json.loads((d / schema.ROS_GRAPH).read_text())
            graph["topics"] = [t for t in graph["topics"] if t["name"] != "/odom"]
            (d / schema.ROS_GRAPH).write_text(json.dumps(graph), encoding="utf-8")
            _rehash(d, schema.ROS_GRAPH)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("CRITICAL_TOPIC_MISSING:/odom" in e for e in result["no_go_findings"]))

    def test_malformed_graph_field_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            graph = json.loads((d / schema.ROS_GRAPH).read_text())
            graph["nodes"] = "not-a-list"
            (d / schema.ROS_GRAPH).write_text(json.dumps(graph), encoding="utf-8")
            _rehash(d, schema.ROS_GRAPH)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("GRAPH_FIELD_NOT_LIST:nodes" in e for e in result["integrity_errors"]))


if __name__ == "__main__":
    unittest.main()
