#!/usr/bin/env python3
"""Fase 2H.2.5 -- end-to-end tests for the P0 PHYSICAL READ-ONLY pipeline (schema v2):
collector (fixture mode) -> bundle (7 JSON + command log) -> hash manifest
-> validator. Runs the real CLI entrypoints as subprocesses (never
imports internals directly) so the test proves the actual wiring, not
just the underlying functions.

Every case here uses --fixture-dir + OTTOGUIDE_P0_FIXTURE_MODE=YES.
--execute-read-only is never invoked anywhere in this file.

Runs on every platform: fixture mode performs no subprocess calls of its
own (no git, no ros2), so it is fully portable.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
P0_DIR = CODE_ROOT / "tools" / "hil" / "physical_read_only"
COLLECTOR_PY = P0_DIR / "collect_p0_readonly_evidence.py"
VALIDATOR_PY = P0_DIR / "validate_p0_readonly_evidence.py"
WRAPPER_SH = P0_DIR / "collect_p0_readonly_evidence.sh"
SCHEMA_PY = P0_DIR / "p0_evidence_schema.py"
FIXTURES_DIR = CODE_ROOT / "tests" / "fixtures" / "p0_readonly"

# Synthetic constant SHA used in all fixtures so tests don't need updating each phase.
GOOD_HEAD = "0000000000000000000000000000000000000042"
FIXTURE_ENV = "OTTOGUIDE_P0_FIXTURE_MODE"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = _load(SCHEMA_PY, "p0_evidence_schema")


def _run_collector(fixture_case: str, output_dir: Path, expected_head: str = GOOD_HEAD, extra_env: dict = None):
    env = os.environ.copy()
    env[FIXTURE_ENV] = "YES"
    env.pop("OTTOGUIDE_P0_READ_ONLY_AUTHORIZED", None)
    if extra_env:
        env.update(extra_env)
    cmd = [
        sys.executable, str(COLLECTOR_PY),
        "--fixture-dir", str(FIXTURES_DIR / fixture_case),
        "--output-dir", str(output_dir),
        "--expected-head", expected_head,
        "--operator-present", "yes",
        "--hardstop-present", "yes",
        "--area-cleared", "yes",
        "--movement-not-authorized-acknowledged", "yes",
    ]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)


def _run_validator(evidence_dir: Path, expected_head: str = GOOD_HEAD):
    cmd = [sys.executable, str(VALIDATOR_PY), str(evidence_dir), "--expected-head", expected_head]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = None
    return proc, result


class TestNominalFixtureEndToEnd(unittest.TestCase):
    """Case 1: nominal fixture -- full pipeline produces a clean,
    integrity-valid, read-only-valid, FIXTURE_ONLY bundle."""

    def test_collector_writes_all_seven_files_plus_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            proc = _run_collector("nominal", out)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")
            for filename in schema.ALL_BUNDLE_FILES:
                self.assertTrue((out / filename).is_file(), f"missing {filename}")
            self.assertTrue((out / schema.HASH_MANIFEST_SIDECAR).is_file())

    def test_validator_reports_fixture_only_exit_3(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            collector_proc = _run_collector("nominal", out)
            self.assertEqual(collector_proc.returncode, 0)
            proc, result = _run_validator(out)
            self.assertIsNotNone(result, proc.stdout)
            self.assertEqual(result["bundle_integrity"], "PASS", result)
            self.assertEqual(result["read_only_invariants"], "PASS", result)
            self.assertEqual(result.get("collection_completeness"), "PASS", result)
            self.assertEqual(result["p0_field_decision"], "FIXTURE_ONLY", result)
            self.assertEqual(proc.returncode, 3)

    def test_movement_invariants_hardcoded_false_in_output(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            _run_collector("nominal", out)
            meta = json.loads((out / schema.SESSION_META).read_text())
            for field in schema.MUST_BE_FALSE_FIELDS:
                self.assertIs(meta[field], False, field)
            self.assertTrue(meta["fixture_mode"])
            self.assertFalse(meta["physical_control_execution_performed"])
            self.assertFalse(meta["field_collection_executed"])
            self.assertEqual(meta["collection_mode"], "fixture")

    def test_command_log_populated_and_well_formed(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            _run_collector("nominal", out)
            cmdlog = json.loads((out / schema.COMMAND_LOG).read_text())
            commands = cmdlog["commands"]
            self.assertTrue(commands)
            for entry in commands:
                for key in ("label", "argv", "started_utc", "ended_utc", "exit_code", "timed_out",
                            "stdout_truncated", "stderr_truncated", "read_only_classification"):
                    self.assertIn(key, entry)


class TestMissingTopicFixture(unittest.TestCase):
    """Case 2: a sensor topic absent from discovery must never have `hz`
    (or even `topic info`) attempted against it, and must be reported as
    NOT_DISCOVERED -- never silently READY."""

    def test_scan_not_discovered_and_hz_never_attempted(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            proc = _run_collector("missing_topic", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            sensors = json.loads((out / schema.SENSORS).read_text())["sensors"]
            self.assertFalse(sensors["/scan"]["present"])
            self.assertIn("NOT_DISCOVERED", sensors["/scan"]["errors"])
            self.assertFalse(sensors["/scan"]["frequency_attempted"])
            cmdlog = json.loads((out / schema.COMMAND_LOG).read_text())
            labels = {c["label"] for c in cmdlog["commands"]}
            self.assertNotIn("topic_hz_scan", labels)
            self.assertNotIn("topic_info_scan", labels)

    def test_validator_flags_missing_critical_topic_as_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            _run_collector("missing_topic", out)
            proc, result = _run_validator(out)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("CRITICAL_TOPIC_MISSING:/scan" in e for e in result["no_go_findings"]))
            self.assertEqual(proc.returncode, 2)


class TestWrongHeadFixture(unittest.TestCase):
    """Case 3: the operator-supplied --expected-head does not match the
    fixture's own canned git HEAD -- a Git gate finding, not an integrity
    failure."""

    def test_head_mismatch_is_no_go(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            wrong_head = "0" * 40
            collector_proc = _run_collector("nominal", out, expected_head=wrong_head)
            self.assertEqual(collector_proc.returncode, 0)
            meta = json.loads((out / schema.SESSION_META).read_text())
            self.assertFalse(meta["head_matches_expected"])
            proc, result = _run_validator(out, expected_head=wrong_head)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["read_only_invariants"], "PASS")
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertTrue(any("HEAD" in e for e in result["no_go_findings"]))
            self.assertEqual(proc.returncode, 2)


class TestHumanSafetyNoGoFixture(unittest.TestCase):
    """Case 4: human safety checklist reports operator absent -- NO_GO,
    and critically still distinguishable from FIXTURE_ONLY (a fixture
    with bad data must report the bad data, not hide behind its fixture
    status)."""

    def test_operator_absent_forces_no_go_not_fixture_only(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            collector_proc = _run_collector("human_no_go", out)
            self.assertEqual(collector_proc.returncode, 0)
            meta = json.loads((out / schema.SESSION_META).read_text())
            self.assertFalse(meta["operator_present"])
            proc, result = _run_validator(out)
            self.assertEqual(result["bundle_integrity"], "PASS")
            self.assertEqual(result["read_only_invariants"], "PASS")
            self.assertEqual(result["p0_field_decision"], "NO_GO")
            self.assertNotEqual(result["p0_field_decision"], "FIXTURE_ONLY")
            self.assertTrue(any("operator_present" in e for e in result["no_go_findings"]))
            self.assertTrue(any("robot_physically_supervised" in e for e in result["no_go_findings"]))
            self.assertEqual(proc.returncode, 2)


class TestTamperedHashFixture(unittest.TestCase):
    """Case 5: a bundle file is modified after collection -- the manifest
    hash no longer matches, forcing an integrity failure (exit 1), never
    silently accepted."""

    def test_tampered_file_fails_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            collector_proc = _run_collector("nominal", out)
            self.assertEqual(collector_proc.returncode, 0)
            graph_path = out / schema.ROS_GRAPH
            data = json.loads(graph_path.read_text())
            data["nodes"] = data["nodes"] + ["/tampered_node"]
            graph_path.write_text(json.dumps(data), encoding="utf-8")
            proc, result = _run_validator(out)
            self.assertEqual(result["bundle_integrity"], "FAIL")
            self.assertTrue(any("HASH_MISMATCH" in e for e in result["integrity_errors"]))
            self.assertEqual(result["p0_field_decision"], "NOT_EVALUATED")
            self.assertEqual(proc.returncode, 1)


class TestCommandTimeoutFixture(unittest.TestCase):
    """Case 6: a simulated command timeout is faithfully recorded in the
    command log (timed_out=true, non-zero exit_code) without crashing the
    collector or corrupting the rest of the bundle."""

    def test_timeout_recorded_collector_still_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            proc = _run_collector("command_timeout", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cmdlog = json.loads((out / schema.COMMAND_LOG).read_text())
            odom_entries = [c for c in cmdlog["commands"] if c["label"] == "odom_echo_once"]
            self.assertEqual(len(odom_entries), 1)
            self.assertTrue(odom_entries[0]["timed_out"])
            self.assertNotEqual(odom_entries[0]["exit_code"], 0)
            validator_proc, result = _run_validator(out)
            self.assertEqual(result["bundle_integrity"], "PASS", result)
            # odom_echo_once is a bounded command: timed_out=True with empty stdout
            # → BOUNDED_COMMAND_TIMEOUT_NO_EVIDENCE → collection_completeness FAIL
            self.assertEqual(result.get("collection_completeness"), "FAIL", result)
            self.assertEqual(result["p0_field_decision"], "NO_GO", result)
            self.assertEqual(validator_proc.returncode, 2)


class TestLargeOutputFixture(unittest.TestCase):
    """Case 7: a command with pathologically large stdout is truncated to
    the documented limit, with stdout_truncated=true recorded -- never an
    unbounded blob persisted into a versioned bundle."""

    def test_oversized_stdout_truncated(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            proc = _run_collector("large_output", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cmdlog = json.loads((out / schema.COMMAND_LOG).read_text())
            entries = [c for c in cmdlog["commands"] if c["label"] == "tf_static_echo_once"]
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertTrue(entry["stdout_truncated"])
            self.assertLessEqual(len(entry["stdout"]), schema.COMMAND_OUTPUT_TRUNCATE_CHARS)
            validator_proc, result = _run_validator(out)
            self.assertEqual(result["bundle_integrity"], "PASS")


class TestMovementAttemptFixture(unittest.TestCase):
    """Case 8: a fixture (or a compromised fixture author) tries to
    declare that movement actually happened. The collector must ignore
    any such claim entirely -- the seven invariants are hardcoded, never
    sourced from fixture data -- and the resulting bundle must still pass
    read_only_invariants."""

    def test_adversarial_movement_claim_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            proc = _run_collector("movement_attempt", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            meta = json.loads((out / schema.SESSION_META).read_text())
            for field in schema.MUST_BE_FALSE_FIELDS:
                self.assertIs(meta[field], False, f"{field} must remain False despite fixture override attempt")
            validator_proc, result = _run_validator(out)
            self.assertEqual(result["read_only_invariants"], "PASS")


class TestDryRunNeverWritesBundle(unittest.TestCase):
    def test_dry_run_default_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "bundle"
            proc = subprocess.run(
                [sys.executable, str(COLLECTOR_PY), "--output-dir", str(out)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(out.exists())
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "NOT_EXECUTED")


if __name__ == "__main__":
    unittest.main()
