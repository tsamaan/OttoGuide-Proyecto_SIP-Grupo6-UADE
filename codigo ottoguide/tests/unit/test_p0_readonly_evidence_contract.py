#!/usr/bin/env python3
"""Fase 2H.2.3 -- offline contract tests for the P0 physical READ-ONLY package.

Two halves:

* Collector source contract: the shell collector must contain NONE of the
  forbidden movement/control/launch/lifecycle commands (§21.3 denylist), and
  MUST carry the read-only guards (dry-run default, the --execute-read-only
  flag, the OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES gate, and a per-command
  timeout).

* Validator behaviour: a clean read-only bundle validates; any violation
  (movement/goal/cmd_vel/damp not false, wrong branch, missing safety field,
  malformed graph, missing/mismatched hash) is rejected.

The shell collector is NEVER executed here and NEVER touches a robot; it is
only read as text. Runs on every platform.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
P0_DIR = CODE_ROOT / "tools" / "hil" / "physical_read_only"
COLLECTOR = P0_DIR / "collect_p0_readonly_evidence.sh"
VALIDATOR = P0_DIR / "validate_p0_readonly_evidence.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_p0_readonly_evidence", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()

# §21.3 denylist -- none of these may appear in the collector source.
FORBIDDEN_PATTERNS = (
    r"ros2\s+action\s+send_goal",
    r"ros2\s+topic\s+pub",
    r"ros2\s+service\s+call",
    r"ros2\s+lifecycle\s+set",
    r"ros2\s+launch",
    r"ros2\s+run",
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


class TestCollectorSourceContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(COLLECTOR.is_file(), f"missing {COLLECTOR}")
        self.src = COLLECTOR.read_text(encoding="utf-8")

    def test_no_forbidden_commands(self):
        for pattern in FORBIDDEN_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIsNone(
                    re.search(pattern, self.src, re.IGNORECASE),
                    f"collector must not contain forbidden pattern: {pattern}",
                )

    def test_no_ssh_or_ip_or_remote(self):
        for pattern in (r"\bssh\b", r"\bscp\b", r"\bsftp\b", r"\brsync\b",
                        r"192\.168\.", r"\bping\b"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.src, re.IGNORECASE), pattern)

    def test_dry_run_is_default(self):
        self.assertRegex(self.src, r"DRY_RUN=1")
        # The first assignment of DRY_RUN must be 1 (default before arg parse).
        first = re.search(r"DRY_RUN=(\d)", self.src)
        self.assertIsNotNone(first)
        self.assertEqual(first.group(1), "1")

    def test_execute_flag_and_env_double_gate(self):
        self.assertIn("--execute-read-only", self.src)
        self.assertIn("OTTOGUIDE_P0_READ_ONLY_AUTHORIZED", self.src)
        self.assertRegex(self.src, r'OTTOGUIDE_P0_READ_ONLY_AUTHORIZED[^\n]*!=\s*"YES"|"YES"')

    def test_uses_timeout_for_blocking_commands(self):
        self.assertRegex(self.src, r'\btimeout\b\s+"\$CMD_TIMEOUT"')

    def test_only_readonly_ros2_subcommands(self):
        # Every `ros2 <subcommand>` must be one of the allowed read-only ones.
        allowed = {"node", "action", "topic", "service", "interface", "param"}
        for m in re.finditer(r"ros2\s+(\w+)", self.src):
            sub = m.group(1)
            self.assertIn(sub, allowed, f"unexpected ros2 subcommand: {sub}")
        # And topic usage is only list/info/echo --once/hz, never pub.
        for m in re.finditer(r"ros2\s+topic\s+(\w+)", self.src):
            self.assertIn(m.group(1), {"list", "info", "echo", "hz"})
        for m in re.finditer(r"ros2\s+param\s+(\w+)", self.src):
            self.assertIn(m.group(1), {"list", "get"})


def _good_bundle(d: Path) -> None:
    meta = {
        "branch": "robot",
        "head": "0" * 40,
        "ros_distro": "foxy",
        "rmw": "rmw_cyclonedds_cpp",
        "operator_present": True,
        "hardstop_present": True,
        "movement_command_sent": False,
        "goal_sent": False,
        "cmd_vel_published": False,
        "damp_invoked": False,
        # Unknown physical data legitimately left uncollected.
        "battery_voltage": None,
        "imu_temp": "not_collected",
    }
    graph = {"nodes": [], "actions": [], "topics": [], "services": []}
    (d / "p0_session_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "p0_ros_graph.json").write_text(json.dumps(graph), encoding="utf-8")
    manifest = {}
    for name in ("p0_session_meta.json", "p0_ros_graph.json"):
        manifest[name] = hashlib.sha256((d / name).read_bytes()).hexdigest()
    (d / "p0_hash_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestValidatorBehaviour(unittest.TestCase):
    def test_clean_bundle_validates(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _good_bundle(d)
            ok, errors = validator.validate_evidence_dir(d)
            self.assertTrue(ok, errors)
            self.assertEqual(errors, [])

    def _mutate_meta(self, d: Path, **changes) -> None:
        meta = json.loads((d / "p0_session_meta.json").read_text())
        meta.update(changes)
        (d / "p0_session_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        # Refresh manifest hash for the mutated meta so we isolate the *field*
        # violation from a hash violation.
        manifest = json.loads((d / "p0_hash_manifest.json").read_text())
        manifest["p0_session_meta.json"] = hashlib.sha256(
            (d / "p0_session_meta.json").read_bytes()
        ).hexdigest()
        (d / "p0_hash_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_movement_command_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); _good_bundle(d)
            self._mutate_meta(d, movement_command_sent=True)
            ok, errors = validator.validate_evidence_dir(d)
            self.assertFalse(ok)
            self.assertTrue(any("movement_command_sent" in e for e in errors), errors)

    def test_goal_and_cmd_vel_and_damp_rejected(self):
        for field in ("goal_sent", "cmd_vel_published", "damp_invoked"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                d = Path(td); _good_bundle(d)
                self._mutate_meta(d, **{field: True})
                ok, errors = validator.validate_evidence_dir(d)
                self.assertFalse(ok)
                self.assertTrue(any(field in e for e in errors), errors)

    def test_wrong_branch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); _good_bundle(d)
            self._mutate_meta(d, branch="main")
            ok, errors = validator.validate_evidence_dir(d)
            self.assertFalse(ok)
            self.assertTrue(any("BRANCH_NOT_OPERATIONAL" in e for e in errors), errors)

    def test_missing_safety_field_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); _good_bundle(d)
            meta = json.loads((d / "p0_session_meta.json").read_text())
            del meta["operator_present"]
            (d / "p0_session_meta.json").write_text(json.dumps(meta), encoding="utf-8")
            manifest = json.loads((d / "p0_hash_manifest.json").read_text())
            manifest["p0_session_meta.json"] = hashlib.sha256(
                (d / "p0_session_meta.json").read_bytes()).hexdigest()
            (d / "p0_hash_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            ok, errors = validator.validate_evidence_dir(d)
            self.assertFalse(ok)
            self.assertTrue(any("SAFETY_FIELD_UNDEFINED:operator_present" in e for e in errors), errors)

    def test_missing_hash_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); _good_bundle(d)
            (d / "p0_hash_manifest.json").unlink()
            ok, errors = validator.validate_evidence_dir(d)
            self.assertFalse(ok)
            self.assertTrue(any("MISSING_FILE:p0_hash_manifest.json" in e for e in errors), errors)

    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); _good_bundle(d)
            # Tamper a file AFTER the manifest was written.
            (d / "p0_ros_graph.json").write_text(
                json.dumps({"nodes": ["x"], "actions": [], "topics": [], "services": []}),
                encoding="utf-8",
            )
            ok, errors = validator.validate_evidence_dir(d)
            self.assertFalse(ok)
            self.assertTrue(any("HASH_MISMATCH:p0_ros_graph.json" in e for e in errors), errors)

    def test_malformed_graph_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); _good_bundle(d)
            (d / "p0_ros_graph.json").write_text(
                json.dumps({"nodes": "notalist", "actions": [], "topics": [], "services": []}),
                encoding="utf-8",
            )
            manifest = json.loads((d / "p0_hash_manifest.json").read_text())
            manifest["p0_ros_graph.json"] = hashlib.sha256(
                (d / "p0_ros_graph.json").read_bytes()).hexdigest()
            (d / "p0_hash_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            ok, errors = validator.validate_evidence_dir(d)
            self.assertFalse(ok)
            self.assertTrue(any("GRAPH_FIELD_NOT_LIST:nodes" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
