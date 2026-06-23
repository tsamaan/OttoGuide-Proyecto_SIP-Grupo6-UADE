#!/usr/bin/env python3
"""Fase 2H.2.5 -- offline contract tests for the P0 physical READ-ONLY
pipeline (collector core + schema + validator, schema v2).

Three sections:

* Source contract: neither the shell wrapper nor the Python core contains
  any forbidden movement/control/launch/lifecycle command, no SSH/SCP/
  rsync/IP, no shell=True/eval, and the core's argv-only command tables
  are exactly what the docstring claims.

* Authorization contract: dry-run is the default; --execute-read-only and
  --fixture-dir are mutually exclusive; each requires its own environment
  variable; real execution requires every one of the ten extra CLI gates
  introduced in 2H.2.5.

* Validator behaviour: the four-layer decision (bundle_integrity,
  read_only_invariants, collection_completeness, p0_field_decision) and
  its exit codes, against hand-built minimal bundles (full
  collector->bundle->validator path covered by test_p0_readonly_pipeline_e2e.py).

The shell wrapper is executed only for bash -n in this file (never
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
import time
import unittest
import unittest.mock
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
        # v2 gates
        operator_role=None, hardstop_type=None,
        hardstop_tested_before_session=None, robot_physically_supervised=None,
        dual_control_prohibited_acknowledged=None,
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
                # v2 gates
                operator_role="test-operator", hardstop_type="physical-estop",
                hardstop_tested_before_session="yes",
                robot_physically_supervised="yes",
                dual_control_prohibited_acknowledged="yes",
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
                operator_role="op", hardstop_type="estop",
                hardstop_tested_before_session="yes",
                robot_physically_supervised="yes",
                dual_control_prohibited_acknowledged="yes",
            )
            with self.assertRaises(collector.CollectorAuthorizationError):
                collector.resolve_mode(args)
        finally:
            del os.environ[collector.READ_ONLY_AUTHORIZED_ENV]

    def test_v2_gates_each_required_for_real_mode(self):
        import os
        os.environ[collector.READ_ONLY_AUTHORIZED_ENV] = "YES"
        v2_defaults = dict(
            execute_read_only=True, expected_head="a" * 40,
            operator_present="yes", hardstop_present="yes",
            area_cleared="yes", movement_not_authorized_acknowledged="yes",
            output_dir=Path("/tmp/p0_test"),
            operator_role="op", hardstop_type="estop",
            hardstop_tested_before_session="yes",
            robot_physically_supervised="yes",
            dual_control_prohibited_acknowledged="yes",
        )
        try:
            for missing_key in ("operator_role", "hardstop_type", "hardstop_tested_before_session",
                                "robot_physically_supervised", "dual_control_prohibited_acknowledged"):
                overrides = {**v2_defaults, missing_key: None}
                with self.subTest(missing_key=missing_key):
                    with self.assertRaises(collector.CollectorAuthorizationError) as ctx:
                        collector.resolve_mode(_ns(**overrides))
                    self.assertTrue(ctx.exception.code.startswith("P0_NOT_AUTHORIZED:"))
        finally:
            del os.environ[collector.READ_ONLY_AUTHORIZED_ENV]


# ---------------------------------------------------------------------------
# Validator behaviour (hand-built minimal bundles)
# ---------------------------------------------------------------------------


def _envelope(session_id="s1"):
    return {"schema_version": schema.SCHEMA_VERSION, "session_id": session_id,
            "collected_at_utc": "2026-01-01T00:00:00Z", "collector_version": schema.COLLECTOR_VERSION}


def _write_json_0600(path: Path, data) -> None:
    """Writes JSON and sets mode 0600, mirroring the production collector's
    SAFE_FILE_MODE so synthetic test bundles satisfy the same POSIX
    permission check the validator enforces on real bundles."""
    path.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(path, 0o600)


def _cmd_entry(label, argv, stdout="", exit_code=0, timed_out=False):
    return {
        "label": label, "argv": argv,
        "started_utc": "2026-01-01T00:00:00Z", "ended_utc": "2026-01-01T00:00:01Z",
        "duration_ms": 10, "exit_code": exit_code, "timed_out": timed_out,
        "stdout": stdout, "stderr": "", "stdout_truncated": False, "stderr_truncated": False,
        "read_only_classification": "read_only",
    }


def _write_good_bundle(d: Path, session_id="s1", fixture_mode=False) -> None:
    env = _envelope(session_id)
    collection_mode = schema.COLLECTION_MODE_FIXTURE if fixture_mode else schema.COLLECTION_MODE_REAL

    meta = {
        **env,
        "actual_branch": "robot", "expected_branch": "robot",
        "actual_head": "a" * 40, "expected_head": "a" * 40, "head_matches_expected": True,
        "tracked_worktree_clean": True, "tracked_changes": [],
        "untracked_paths": ["codigo ottoguide/logs/mission_x.json"], "untracked_symlinks": [],
        "untracked_allowlist_only": True,
        "git_remote_metadata": {"origin_url": "https://github.com/example/repo.git"},
        "ros_distro": "foxy", "rmw_implementation": "rmw_cyclonedds_cpp",
        "collection_mode": collection_mode,
        "fixture_mode": fixture_mode,
        "field_collection_executed": not fixture_mode,
        # MUST_BE_FALSE_FIELDS (v2)
        "movement_command_sent": False, "goal_sent": False, "cmd_vel_published": False,
        "damp_invoked": False, "control_service_called": False,
        "lifecycle_changed": False, "parameter_changed": False,
        "physical_control_execution_performed": False,
        # human safety summary
        "operator_present": True, "hardstop_present": True, "area_cleared": True,
        "robot_physically_supervised": True, "movement_not_authorized_acknowledged": True,
    }

    # All required topics with correct types
    graph = {
        **env,
        "nodes": ["/controller_server", "/collision_monitor"],
        "topics": [
            {"name": "/odom", "type": "nav_msgs/msg/Odometry"},
            {"name": "/scan", "type": "sensor_msgs/msg/LaserScan"},
            {"name": "/tf", "type": "tf2_msgs/msg/TFMessage"},
            {"name": "/tf_static", "type": "tf2_msgs/msg/TFMessage"},
            {"name": "/map", "type": "nav_msgs/msg/OccupancyGrid"},
            {"name": "/map_metadata", "type": "nav_msgs/msg/MapMetaData"},
            {"name": "/cmd_vel_raw", "type": "geometry_msgs/msg/Twist"},
            {"name": "/cmd_vel_safe", "type": "geometry_msgs/msg/Twist"},
        ],
        "services": [], "actions": [], "critical_actions": [], "critical_topics": [],
    }

    # TF and localization with all required edges
    tf_loc = {
        **env,
        "tf_topic_present": True, "tf_static_topic_present": True,
        "odom_topic_present": True, "map_topic_present": True,
        "single_sample_odom": "header:\n  frame_id: odom\nchild_frame_id: base_link\n",
        "single_sample_tf_static": "transforms:\n- header:\n    frame_id: map\n  child_frame_id: odom\n",
        "candidate_odom_frame_id": "odom",
        "candidate_child_frame_id": "base_link",
        "tf_edges_observed": list(schema.REQUIRED_TF_EDGES),
        "required_tf_edges": list(schema.REQUIRED_TF_EDGES),
        "l2_odometry": "CANDIDATE_OBSERVED_PENDING_ANALYSIS",
        "l3_localization_map": "CANDIDATE_OBSERVED_PENDING_ANALYSIS",
    }

    sensors = {
        **env,
        "sensors": {
            "/scan": {
                "present": True, "type": "sensor_msgs/msg/LaserScan",
                "publisher_count": 1, "frequency_attempted": True, "frequency_result": 10.0,
                "frame_id": None, "sample_collected": False, "errors": [],
            }
        },
    }

    cmd_vel = {
        **env,
        "topics": {
            "/cmd_vel_raw": {"present": True, "publisher_count": 1, "subscription_count": 1, "qos": None},
            "/cmd_vel_safe": {"present": True, "publisher_count": 1, "subscription_count": 1, "qos": None},
        },
        "unexpected_global_cmd_vel": False,
        "collision_monitor_observed": True,
        "controller_server_observed": True,
        "consumer_observed": None,
        "status": "OBSERVED_PENDING_PHYSICAL_ANALYSIS",
    }

    safety = {
        **env,
        "operator_present": True, "operator_identity_or_role": "test-op",
        "hardstop_present": True, "hardstop_type": "physical-estop",
        "hardstop_tested_before_session": True, "area_cleared": True,
        "robot_physically_supervised": True, "dual_control_prohibited_acknowledged": True,
        "movement_not_authorized_acknowledged": True, "notes": None,
    }

    # Command log with all strict + bounded commands (exit_code=0, timed_out=False)
    cmdlog = {
        **env,
        "commands": [
            _cmd_entry("git_branch", ["git", "-C", "/repo", "branch", "--show-current"], stdout="robot\n"),
            _cmd_entry("git_head", ["git", "-C", "/repo", "rev-parse", "HEAD"], stdout="a" * 40 + "\n"),
            _cmd_entry("git_status", ["git", "-C", "/repo", "status", "--short", "--branch", "--untracked-files=all"],
                       stdout="## robot\n?? \"codigo ottoguide/logs/mission_x.json\"\n"),
            _cmd_entry("git_remote_origin", ["git", "-C", "/repo", "remote", "get-url", "origin"],
                       stdout="https://github.com/example/repo.git\n"),
            _cmd_entry("ros2_node_list", ["ros2", "node", "list"],
                       stdout="/controller_server\n/collision_monitor\n"),
            _cmd_entry("ros2_topic_list", ["ros2", "topic", "list", "-t"],
                       stdout="/odom [nav_msgs/msg/Odometry]\n/scan [sensor_msgs/msg/LaserScan]\n"),
            _cmd_entry("ros2_service_list", ["ros2", "service", "list", "-t"], stdout=""),
            _cmd_entry("ros2_action_list", ["ros2", "action", "list", "-t"], stdout=""),
            _cmd_entry("tf_static_echo_once", ["ros2", "topic", "echo", "--once", "/tf_static"],
                       stdout="transforms:\n- header:\n    frame_id: map\n  child_frame_id: odom\n"),
            _cmd_entry("odom_echo_once", ["ros2", "topic", "echo", "--once", "/odom"],
                       stdout="header:\n  frame_id: odom\nchild_frame_id: base_link\n"),
        ],
    }

    docs = {
        schema.SESSION_META: meta, schema.ROS_GRAPH: graph, schema.TF_AND_LOCALIZATION: tf_loc,
        schema.SENSORS: sensors, schema.CMD_VEL_CHAIN: cmd_vel, schema.SAFETY_HUMAN_CHECKLIST: safety,
        schema.COMMAND_LOG: cmdlog,
    }
    os.chmod(d, 0o700)
    manifest_files = []
    for name, data in docs.items():
        path = d / name
        path.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(path, 0o600)
        manifest_files.append({
            "filename": name, "sha256": schema.sha256_file(path),
            "size_bytes": path.stat().st_size,
            "mode": None, "uid": None, "nlink": None, "file_type": "regular",
        })
    manifest = {**env, "files": manifest_files}
    manifest_path = d / schema.HASH_MANIFEST
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    # Sidecar: 64-hex SHA-256 of the manifest file
    sidecar_path = d / schema.HASH_MANIFEST_SIDECAR
    sidecar_path.write_bytes(
        (schema.sha256_file(manifest_path) + "\n").encode("ascii")
    )
    os.chmod(sidecar_path, 0o600)


def _rehash(d: Path, filename: str) -> None:
    """Update the manifest entry for filename, then re-write the sidecar."""
    os.chmod(d / filename, 0o600)
    manifest = json.loads((d / schema.HASH_MANIFEST).read_text())
    for entry in manifest["files"]:
        if entry["filename"] == filename:
            entry["sha256"] = schema.sha256_file(d / filename)
            entry["size_bytes"] = (d / filename).stat().st_size
    manifest_path = d / schema.HASH_MANIFEST
    _write_json_0600(manifest_path, manifest)
    sidecar_path = d / schema.HASH_MANIFEST_SIDECAR
    sidecar_path.write_bytes(
        (schema.sha256_file(manifest_path) + "\n").encode("ascii")
    )
    os.chmod(sidecar_path, 0o600)


class TestValidatorThreeLayerDecision(unittest.TestCase):
    def test_clean_real_bundle_is_go_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d, fixture_mode=False)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "PASS", result)
            self.assertEqual(result["read_only_invariants"], "PASS", result)
            self.assertEqual(result.get("collection_completeness"), "PASS", result)
            self.assertEqual(result["p0_field_decision"], "GO_CANDIDATE", result)
            self.assertEqual(validator._exit_code(result), 0)

    def test_clean_fixture_bundle_is_fixture_only_never_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d, fixture_mode=True)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "PASS", result)
            self.assertEqual(result.get("collection_completeness"), "PASS", result)
            self.assertEqual(result["p0_field_decision"], "FIXTURE_ONLY", result)
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
            _write_json_0600(d / schema.ROS_GRAPH, data)
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
            _write_json_0600(d / schema.SESSION_META, meta)
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
            _write_json_0600(d / schema.SESSION_META, meta)
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
            _write_json_0600(d / schema.SAFETY_HUMAN_CHECKLIST, safety)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["operator_present"] = False
            _write_json_0600(d / schema.SESSION_META, meta)
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
            _write_json_0600(d / schema.SESSION_META, meta)
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
            _write_json_0600(d / schema.SESSION_META, meta)
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
            _write_json_0600(d / schema.ROS_GRAPH, graph)
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
            _write_json_0600(d / schema.ROS_GRAPH, graph)
            _rehash(d, schema.ROS_GRAPH)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("GRAPH_FIELD_NOT_LIST:nodes" in e for e in result["integrity_errors"]))


# ---------------------------------------------------------------------------
# v2 contract tests (spec section 11, Fase 2H.2.5)
# ---------------------------------------------------------------------------


class TestV2BundleIntegrityContract(unittest.TestCase):
    """Integrity-layer contracts for schema v2: sidecar, manifest, schema version."""

    def test_schema_v1_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            # Downgrade schema_version to 1 in session_meta
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["schema_version"] = 1
            _write_json_0600(d / schema.SESSION_META, meta)
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("SCHEMA_VERSION_MISMATCH" in e for e in result["integrity_errors"]))

    def test_sidecar_absent_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            (d / schema.HASH_MANIFEST_SIDECAR).unlink()
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertIn("SIDECAR_MISSING", result["integrity_errors"])

    def test_sidecar_invalid_format_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            (d / schema.HASH_MANIFEST_SIDECAR).write_bytes(b"not-a-hex-hash\n")
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("SIDECAR_INVALID_FORMAT" in e for e in result["integrity_errors"]))

    def test_sidecar_hash_mismatch_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            # Write a valid hex hash that doesn't match the manifest
            (d / schema.HASH_MANIFEST_SIDECAR).write_bytes(("0" * 64 + "\n").encode("ascii"))
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("SIDECAR_HASH_MISMATCH" in e for e in result["integrity_errors"]))

    def test_manifest_duplicate_filename_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            manifest = json.loads((d / schema.HASH_MANIFEST).read_text())
            # Duplicate the first entry
            manifest["files"].append(manifest["files"][0])
            manifest_path = d / schema.HASH_MANIFEST
            _write_json_0600(manifest_path, manifest)
            # Update sidecar to match the (now broken) manifest
            sidecar_path = d / schema.HASH_MANIFEST_SIDECAR
            sidecar_path.write_bytes(
                (schema.sha256_file(manifest_path) + "\n").encode("ascii")
            )
            os.chmod(sidecar_path, 0o600)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("MANIFEST_DUPLICATE_FILENAME" in e for e in result["integrity_errors"]))

    def test_manifest_path_traversal_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            manifest = json.loads((d / schema.HASH_MANIFEST).read_text())
            manifest["files"][0]["filename"] = "../outside.json"
            manifest_path = d / schema.HASH_MANIFEST
            _write_json_0600(manifest_path, manifest)
            sidecar_path = d / schema.HASH_MANIFEST_SIDECAR
            sidecar_path.write_bytes(
                (schema.sha256_file(manifest_path) + "\n").encode("ascii")
            )
            os.chmod(sidecar_path, 0o600)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("MANIFEST_FILENAME_PATH_TRAVERSAL" in e or
                                "MANIFEST_FILENAME_CONTAINS_SEPARATOR" in e
                                for e in result["integrity_errors"]))

    def test_physical_control_execution_performed_in_must_be_false_fields(self):
        self.assertIn("physical_control_execution_performed", schema.MUST_BE_FALSE_FIELDS)

    def test_physical_control_execution_performed_true_fails_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["physical_control_execution_performed"] = True
            _write_json_0600(d / schema.SESSION_META, meta)
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["read_only_invariants"], "FAIL")
            self.assertTrue(any("physical_control_execution_performed" in e
                                for e in result["read_only_errors"]))


class TestV2FieldDecisionContract(unittest.TestCase):
    """Field-decision and completeness layer contracts for schema v2."""

    def test_untracked_exact_policy_rejects_non_log_path(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["untracked_paths"] = ["codigo ottoguide/logs/mission_x.py"]  # .py not allowed
            _write_json_0600(d / schema.SESSION_META, meta)
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertIn("UNTRACKED_OUTSIDE_ALLOWLIST", result["no_go_findings"])

    def test_untracked_exact_policy_accepts_mission_log(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["untracked_paths"] = [
                "codigo ottoguide/logs/mission_20260622T091904695910Z.json"
            ]
            _write_json_0600(d / schema.SESSION_META, meta)
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertNotIn("UNTRACKED_OUTSIDE_ALLOWLIST", result.get("no_go_findings", []))

    def test_operator_role_missing_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            safety = json.loads((d / schema.SAFETY_HUMAN_CHECKLIST).read_text())
            safety["operator_identity_or_role"] = ""
            _write_json_0600(d / schema.SAFETY_HUMAN_CHECKLIST, safety)
            _rehash(d, schema.SAFETY_HUMAN_CHECKLIST)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("OPERATOR_ROLE_MISSING_OR_EMPTY" in e for e in result["no_go_findings"]))

    def test_hardstop_type_missing_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            safety = json.loads((d / schema.SAFETY_HUMAN_CHECKLIST).read_text())
            safety["hardstop_type"] = ""
            _write_json_0600(d / schema.SAFETY_HUMAN_CHECKLIST, safety)
            _rehash(d, schema.SAFETY_HUMAN_CHECKLIST)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("HARDSTOP_TYPE_MISSING_OR_EMPTY" in e for e in result["no_go_findings"]))

    def test_collection_mode_unknown_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            meta = json.loads((d / schema.SESSION_META).read_text())
            meta["collection_mode"] = "unknown_mode"
            _write_json_0600(d / schema.SESSION_META, meta)
            _rehash(d, schema.SESSION_META)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("COLLECTION_MODE_UNKNOWN" in e for e in result["no_go_findings"]))

    def test_fixture_bundle_never_go_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d, fixture_mode=True)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertNotEqual(result["p0_field_decision"], "GO_CANDIDATE")
            self.assertEqual(result["p0_field_decision"], "FIXTURE_ONLY")

    def test_collection_completeness_fail_forces_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            # Remove strict commands from command log — forces STRICT_COMMAND_MISSING
            cmdlog = json.loads((d / schema.COMMAND_LOG).read_text())
            cmdlog["commands"] = []
            _write_json_0600(d / schema.COMMAND_LOG, cmdlog)
            _rehash(d, schema.COMMAND_LOG)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result.get("collection_completeness"), "FAIL")
            self.assertEqual(result["p0_field_decision"], "NO_GO")

    def test_command_log_forbidden_label_fails_read_only_invariants(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            cmdlog = json.loads((d / schema.COMMAND_LOG).read_text())
            cmdlog["commands"].append(_cmd_entry(
                "not_an_allowed_label_xyz",
                ["some", "cmd"],
                stdout="",
            ))
            _write_json_0600(d / schema.COMMAND_LOG, cmdlog)
            _rehash(d, schema.COMMAND_LOG)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["read_only_invariants"], "FAIL")
            self.assertTrue(any("COMMAND_LOG_LABEL_NOT_ALLOWED" in e
                                for e in result["read_only_errors"]))

    def test_tf_edge_missing_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            tf_loc = json.loads((d / schema.TF_AND_LOCALIZATION).read_text())
            tf_loc["tf_edges_observed"] = ["map->odom"]  # only 1 of 4 required edges
            _write_json_0600(d / schema.TF_AND_LOCALIZATION, tf_loc)
            _rehash(d, schema.TF_AND_LOCALIZATION)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("TF_EDGE_NOT_OBSERVED" in e for e in result["no_go_findings"]))

    def test_remote_url_credential_redaction(self):
        url_with_cred = "https://user:token@github.com/owner/repo.git"
        redacted = schema.redact_git_url(url_with_cred)
        self.assertNotIn("token", redacted)
        self.assertNotIn("user:token", redacted)
        self.assertIn("github.com", redacted)

    def test_dual_control_prohibited_acknowledged_required_for_go(self):
        self.assertIn("dual_control_prohibited_acknowledged", schema.SAFETY_REQUIRED_TRUE_FOR_GO)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write_good_bundle(d)
            safety = json.loads((d / schema.SAFETY_HUMAN_CHECKLIST).read_text())
            safety["dual_control_prohibited_acknowledged"] = False
            _write_json_0600(d / schema.SAFETY_HUMAN_CHECKLIST, safety)
            _rehash(d, schema.SAFETY_HUMAN_CHECKLIST)
            result = validator.validate_evidence_dir(d, expected_head="a" * 40)
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("dual_control_prohibited_acknowledged" in e
                                for e in result["no_go_findings"]))


# ---------------------------------------------------------------------------
# v3 clock trust contract tests (Fase 2H.2.6)
# ---------------------------------------------------------------------------


class TestClockTrustSchema(unittest.TestCase):
    """wall_clock_trust() and base_envelope() behave correctly for invalid clocks."""

    def test_trusted_clock_returns_trusted(self):
        """A year >= 2020 must yield CLOCK_TRUSTED."""
        with unittest.mock.patch("time.gmtime") as mock_gmtime:
            mock_gmtime.return_value = time.struct_time((2026, 6, 23, 0, 0, 0, 0, 0, 0))
            trust, iso = schema.wall_clock_trust()
        self.assertEqual(trust, schema.CLOCK_TRUSTED)
        self.assertIn("2026", iso)

    def test_epoch_1970_returns_untrusted(self):
        """Year 1970 (robot RTC epoch) must yield CLOCK_UNTRUSTED."""
        with unittest.mock.patch("time.gmtime") as mock_gmtime:
            mock_gmtime.return_value = time.struct_time((1970, 5, 26, 8, 20, 14, 0, 0, 0))
            trust, iso = schema.wall_clock_trust()
        self.assertEqual(trust, schema.CLOCK_UNTRUSTED)
        self.assertIn("1970", iso)

    def test_year_2019_returns_untrusted(self):
        """Year 2019 is below the minimum threshold and must be CLOCK_UNTRUSTED."""
        with unittest.mock.patch("time.gmtime") as mock_gmtime:
            mock_gmtime.return_value = time.struct_time((2019, 1, 1, 0, 0, 0, 0, 0, 0))
            trust, iso = schema.wall_clock_trust()
        self.assertEqual(trust, schema.CLOCK_UNTRUSTED)

    def test_base_envelope_includes_clock_fields(self):
        """base_envelope() must include all v3 clock fields."""
        session_id = "test-session-clock"
        env = schema.base_envelope(session_id)
        for field in ("wall_clock_value", "wall_clock_trusted", "wall_clock_source",
                      "monotonic_started_ns", "monotonic_ended_ns"):
            self.assertIn(field, env, f"Missing field: {field}")
        self.assertEqual(env["wall_clock_source"], "time.gmtime()")

    def test_base_envelope_with_untrusted_clock(self):
        """base_envelope() with 1970 clock must set wall_clock_trusted=False."""
        with unittest.mock.patch("time.gmtime") as mock_gmtime:
            mock_gmtime.return_value = time.struct_time((1970, 5, 26, 8, 20, 14, 0, 0, 0))
            env = schema.base_envelope("sid-1970")
        self.assertFalse(env["wall_clock_trusted"])
        self.assertIn("1970", env["wall_clock_value"])

    def test_base_envelope_duration_ms_computed(self):
        """When monotonic_started_ns is provided, duration_ms must be present."""
        started = schema.monotonic_now_ns()
        env = schema.base_envelope("sid-dur", monotonic_started_ns=started)
        self.assertIn("duration_ms", env)
        self.assertGreaterEqual(env["duration_ms"], 0)

    def test_clock_untrusted_constant_value(self):
        """CLOCK_UNTRUSTED and CLOCK_TRUSTED must be distinct non-empty strings."""
        self.assertIsInstance(schema.CLOCK_UNTRUSTED, str)
        self.assertIsInstance(schema.CLOCK_TRUSTED, str)
        self.assertNotEqual(schema.CLOCK_UNTRUSTED, schema.CLOCK_TRUSTED)
        self.assertTrue(schema.CLOCK_UNTRUSTED)
        self.assertTrue(schema.CLOCK_TRUSTED)


if __name__ == "__main__":
    unittest.main()
