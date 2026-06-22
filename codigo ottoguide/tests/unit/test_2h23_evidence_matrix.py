#!/usr/bin/env python3
"""Fase 2H.2.3 -- deterministic tests for the parent-timeout-cleanup evidence
driver (tools/hil/offline_navigation/run_2h23_evidence_matrix.py).

Two layers:

* Pure / guard tests run on every platform (Windows included): they prove the
  fault-injection guard refuses to stall without the explicit environment
  variable, that an invalid lease is never authorized for sandbox cleanup,
  and that a valid lease is.

* POSIX behavioural tests (skipped on Windows) drive the real
  ``_parent_timeout_cleanup`` against a real, isolated process tree and the
  end-to-end driver subprocess, asserting the §16.3 acceptance set:
  parent_timeout_cleanup_executed, child reaped, child + sandbox groups gone,
  zero zombies, and an unrelated sentinel left completely untouched.

No ROS, no network, no hardware. Every spawned process is reaped in finally.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
OFFLINE_DIR = CODE_ROOT / "tools" / "hil" / "offline_navigation"
SMOKE_TEST_PATH = OFFLINE_DIR / "smoke_test_main_runtime_navigation_selection.py"
DRIVER_PATH = OFFLINE_DIR / "run_2h23_evidence_matrix.py"

_IS_POSIX = os.name == "posix" and Path("/proc").is_dir()
_POSIX_SKIP = "requires POSIX /proc + setsid/killpg semantics"

FAULT_ENV = "OTTOGUIDE_2H23_FAULT_INJECTION"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load(SMOKE_TEST_PATH, "smoke_test_main_runtime_navigation_selection")
driver = _load(DRIVER_PATH, "run_2h23_evidence_matrix")


# ---------------------------------------------------------------------------
# Guard tests (all platforms)
# ---------------------------------------------------------------------------


class TestFaultInjectionGuard(unittest.TestCase):
    def _run_fault_child(self, env_extra: dict) -> "subprocess.CompletedProcess[str]":
        env = os.environ.copy()
        env.pop(FAULT_ENV, None)
        env.update(env_extra)
        cmd = [
            sys.executable, str(DRIVER_PATH), "--fault-child",
            "--run-id", "deadbeef", "--domain-id", "104",
            "--lease-dir", str(Path(tempfile.gettempdir()) / "nonexistent_2h23"),
            "--lease-token", "x" * 64,
            "--expected-parent-pid", "2", "--expected-parent-ppid", "2",
            "--expected-parent-pgid", "2", "--expected-parent-sid", "2",
            "--expected-parent-start-ticks", "2", "--expected-parent-uid", "1000",
        ]
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)

    def test_fault_child_disabled_by_default(self):
        """Without the explicit env var the injected child refuses to stall
        and exits non-zero immediately (never reaches the sleep)."""
        start = time.monotonic()
        proc = self._run_fault_child({})
        elapsed = time.monotonic() - start
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("FAULT_INJECTION_NOT_AUTHORIZED", proc.stderr)
        # Must not have stalled: a real stall would be CHILD_STALL_S seconds.
        self.assertLess(elapsed, 20.0)

    def test_fault_child_requires_explicit_variable_value(self):
        """A truthy-but-wrong value is still refused; only the exact '1'
        authorizes the stall path."""
        proc = self._run_fault_child({FAULT_ENV: "0"})
        self.assertEqual(proc.returncode, 3)
        self.assertIn("FAULT_INJECTION_NOT_AUTHORIZED", proc.stderr)

    def test_driver_refuses_without_env(self):
        """The driver (parent) refuses to run the timeout E2E without the
        explicit fault-injection authorization, on every platform."""
        env = os.environ.copy()
        env.pop(FAULT_ENV, None)
        out = Path(tempfile.gettempdir()) / "ottoguide_2h23_driver_refuse.json"
        proc = subprocess.run(
            [sys.executable, str(DRIVER_PATH), "--domain-id", "104", "--output", str(out)],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(proc.returncode, 0)
        data = json.loads(out.read_text())
        # Either platform-gated or authorization-gated, never a green run.
        self.assertNotEqual(data["decision"], "PASS")
        self.assertIn(
            data["decision"], ("UNSUPPORTED_PLATFORM", "FAIL"),
        )
        flat_errors = data["errors"]
        self.assertTrue(
            any(e in ("FAULT_INJECTION_NOT_AUTHORIZED", "REQUIRES_POSIX_PROC_KILLPG")
                for e in flat_errors),
            flat_errors,
        )
        out.unlink(missing_ok=True)


class TestLeaseAuthorization(unittest.TestCase):
    """Pure validation: an invalid lease is never authorized; a valid one is.
    Uses the smoke test's own validators, which the driver and
    _parent_timeout_cleanup share."""

    def _parent_identity(self):
        return smoke.ProcessIdentity(pid=1234, ppid=1, pgid=1234, sid=1234, start_ticks=10, uid=1000)

    def _valid_lease_data(self, token: str):
        pid_dict = self._parent_identity().to_dict()
        now = time.time_ns()
        return {
            "schema_version": smoke.LEASE_SCHEMA_VERSION,
            "run_id": "run1", "lease_token": token, "scenario": "fault_injection_timeout",
            "domain_id": "104", "max_age_s": 600.0, "created_at_ns": now, "updated_at_ns": now,
            "parent": pid_dict, "child": smoke._EMPTY_IDENTITY_DICT, "sandbox": smoke._EMPTY_IDENTITY_DICT,
        }

    def test_invalid_lease_token_not_authorized(self):
        token = "a" * 64
        data = self._valid_lease_data(token)
        errors = smoke.validate_lease_immutable_fields(
            data, "run1", "fault_injection_timeout", "104",
            expected_parent=self._parent_identity(), expected_token="b" * 64,
        )
        self.assertIn("LEASE_TOKEN_MISMATCH", errors)

    def test_valid_lease_authorized(self):
        token = "c" * 64
        data = self._valid_lease_data(token)
        errors = smoke.validate_lease_immutable_fields(
            data, "run1", "fault_injection_timeout", "104",
            expected_parent=self._parent_identity(), expected_token=token,
        )
        self.assertEqual(errors, [])

    def test_invalid_lease_scenario_mismatch_not_authorized(self):
        token = "d" * 64
        data = self._valid_lease_data(token)
        errors = smoke.validate_lease_immutable_fields(
            data, "run1", "WRONG_SCENARIO", "104",
            expected_parent=self._parent_identity(), expected_token=token,
        )
        self.assertIn("LEASE_SCENARIO_MISMATCH", errors)


# ---------------------------------------------------------------------------
# POSIX behavioural tests
# ---------------------------------------------------------------------------


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP)
class TestSentinelAndDirectChildCleanup(unittest.TestCase):
    def test_unrelated_sentinel_survives_group_cleanup(self):
        """A cleanup that escalates one isolated group never touches an
        unrelated sentinel in its own group."""
        sentinel_proc, sentinel_id = smoke.spawn_isolated(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        victim_proc, victim_id = smoke.spawn_isolated(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        time.sleep(0.3)
        try:
            attempts: list = []
            self.assertTrue(smoke.identity_still_valid(sentinel_id))
            smoke.escalate_signal_to_group(
                victim_id.pgid, victim_id, smoke.CleanupTimeouts(), attempts, "victim",
                reap_callback=victim_proc.poll,
            )
            # Settle for init/parent reap of the victim.
            deadline = time.monotonic() + 5.0
            while smoke._pgid_alive(victim_id.pgid) and time.monotonic() < deadline:
                victim_proc.poll()
                time.sleep(0.1)
            self.assertFalse(smoke._pgid_alive(victim_id.pgid), "victim group should be gone")
            # Sentinel untouched.
            self.assertTrue(smoke.identity_still_valid(sentinel_id), "sentinel must survive")
            self.assertNotIn(sentinel_id.pgid, {a.get("pgid") for a in attempts})
        finally:
            for p, ident in ((victim_proc, victim_id), (sentinel_proc, sentinel_id)):
                try:
                    if not smoke.is_protected_id(ident.pgid):
                        os.killpg(ident.pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    p.wait(timeout=5)
                except Exception:
                    pass

    def test_direct_child_cleaned_by_captured_identity(self):
        """A directly-spawned isolated child is torn down via its captured
        identity and reaped, leaving no zombie under this process."""
        proc, ident = smoke.spawn_isolated(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        time.sleep(0.3)
        try:
            attempts: list = []
            smoke.escalate_signal_to_group(
                ident.pgid, ident, smoke.CleanupTimeouts(), attempts, "child",
                reap_callback=proc.poll,
            )
            deadline = time.monotonic() + 5.0
            while smoke._pgid_alive(ident.pgid) and time.monotonic() < deadline:
                proc.poll()
                time.sleep(0.1)
            self.assertFalse(smoke._pgid_alive(ident.pgid))
            proc.wait(timeout=5)
            self.assertNotIn(proc.pid, smoke._collect_zombie_children(os.getpid()))
        finally:
            try:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP)
class TestTimeoutE2EDriver(unittest.TestCase):
    """End-to-end: drive the real production timeout transition and assert the
    full §16.3 acceptance set. Uses domain 105 (timeout E2E band, never 0)."""

    def test_parent_timeout_cleanup_exercised_end_to_end(self):
        env = os.environ.copy()
        env[FAULT_ENV] = "1"
        env["ROS_LOCALHOST_ONLY"] = "1"
        env["ROS_DOMAIN_ID"] = "105"
        out = Path(tempfile.gettempdir()) / "ottoguide_2h23_e2e_test.json"
        proc = subprocess.run(
            [sys.executable, str(DRIVER_PATH), "--domain-id", "105", "--output", str(out)],
            env=env, capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")
        data = json.loads(out.read_text())
        c = data["cleanup_evidence"]
        self.assertEqual(data["decision"], "PASS")
        self.assertTrue(data["parent_timeout_cleanup_executed"])
        self.assertTrue(data["lease_populated_before_timeout"])
        self.assertTrue(c["lease_validation"]["ok"])
        self.assertTrue(c["child_identity_validation"]["ok"])
        self.assertTrue(c["child_reaped"])
        self.assertFalse(c["child_group_alive_after"])
        self.assertFalse(c["sandbox_group_alive_after"])
        self.assertEqual(c["owned_members_remaining"], [])
        self.assertEqual(data["zombies_remaining"], 0)
        self.assertTrue(data["sentinel"]["alive_after_timeout"])
        self.assertFalse(data["sentinel"]["received_signal"])
        self.assertTrue(data["sentinel"]["reaped"])
        out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
