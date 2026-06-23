#!/usr/bin/env python3
"""Fase 2H.2.4 -- deterministic tests for the *real parent CLI* timeout
driver (tools/hil/offline_navigation/run_2h24_parent_cli_timeout.py) and
the hidden fault-injection hooks it depends on in
smoke_test_main_runtime_navigation_selection.py.

Two layers:

* Pure / guard tests run on every platform (Windows included): the hidden
  --fault-inject-hang-sandbox flag never appears in --help, and both the
  smoke test itself and the driver refuse fault injection without the
  exact OTTOGUIDE_2H24_FAULT_INJECTION=1 environment variable.

* POSIX behavioural tests (skipped on Windows) drive the genuine CLI
  entrypoint (main() -> _parent_main() -> communicate(timeout=...) ->
  TimeoutExpired -> _parent_timeout_cleanup -> JSON -> exit code) as a real
  subprocess and assert the acceptance set: cleanup_decision == PASS,
  scenario_decision == EXPECTED_TIMEOUT, zero zombies, and an unrelated
  sentinel left completely untouched.

No ROS, no network, no hardware. Every spawned process is reaped in finally.
"""
from __future__ import annotations

import importlib.util
import json
import os
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
DRIVER_PATH = OFFLINE_DIR / "run_2h24_parent_cli_timeout.py"

_IS_POSIX = os.name == "posix" and Path("/proc").is_dir()
_POSIX_SKIP = "requires POSIX /proc + setsid/killpg semantics"

FAULT_ENV = "OTTOGUIDE_2H24_FAULT_INJECTION"
MARGIN_ENV = "OTTOGUIDE_2H24_FAULT_TIMEOUT_MARGIN_S"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load(SMOKE_TEST_PATH, "smoke_test_main_runtime_navigation_selection")


# ---------------------------------------------------------------------------
# Guard tests (all platforms)
# ---------------------------------------------------------------------------


class TestFaultInjectionHidden(unittest.TestCase):
    def test_flag_not_in_help_output(self):
        """The smoke test defines the hidden flag itself (argparse.SUPPRESS);
        its --help must never list it. The driver, by contrast, defines no
        such flag at all -- it only sets env vars and passes the smoke
        test's own flag through -- so it is not checked here."""
        proc = subprocess.run(
            [sys.executable, str(SMOKE_TEST_PATH), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("fault-inject", proc.stdout.lower())


class TestSmokeTestFaultInjectionGuard(unittest.TestCase):
    def _run(self, env_extra: dict, extra_args: "list[str]" = ()) -> "subprocess.CompletedProcess[str]":
        env = os.environ.copy()
        env.pop(FAULT_ENV, None)
        env.update(env_extra)
        cmd = [
            sys.executable, str(SMOKE_TEST_PATH),
            "--base-domain-id", "220", "--timeout", "1",
            "--fault-inject-hang-sandbox", *extra_args,
        ]
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)

    def test_parent_refuses_fault_injection_without_env(self):
        start = time.monotonic()
        proc = self._run({})
        elapsed = time.monotonic() - start
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("FAULT_INJECTION_NOT_AUTHORIZED", proc.stdout)
        self.assertLess(elapsed, 10.0, "must fail closed immediately, never stall")

    def test_parent_refuses_fault_injection_with_wrong_value(self):
        proc = self._run({FAULT_ENV: "true"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("FAULT_INJECTION_NOT_AUTHORIZED", proc.stdout)

    def test_normal_invocation_without_flag_does_not_require_env(self):
        """Sanity: the hidden flag is opt-in only -- a normal --help/parse
        path is never gated by the fault-injection env var."""
        env = os.environ.copy()
        env.pop(FAULT_ENV, None)
        proc = subprocess.run(
            [sys.executable, str(SMOKE_TEST_PATH), "--help"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0)


class TestDriverGuard(unittest.TestCase):
    def test_driver_refuses_without_env(self):
        env = os.environ.copy()
        env.pop(FAULT_ENV, None)
        out = Path(tempfile.gettempdir()) / "ottoguide_2h24_driver_refuse.json"
        proc = subprocess.run(
            [sys.executable, str(DRIVER_PATH), "--output", str(out)],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(proc.returncode, 0)
        data = json.loads(out.read_text())
        self.assertNotEqual(data["cleanup_decision"], "PASS")
        self.assertIn(data["cleanup_decision"], ("UNSUPPORTED_PLATFORM", "FAIL"))
        self.assertTrue(
            any(e in ("FAULT_INJECTION_NOT_AUTHORIZED", "REQUIRES_POSIX_PROC_KILLPG")
                for e in data["errors"]),
            data["errors"],
        )
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# POSIX behavioural tests
# ---------------------------------------------------------------------------


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP)
class TestParentCLITimeoutE2E(unittest.TestCase):
    """End-to-end: drive the *real* CLI entrypoint (main() -> _parent_main())
    through a genuine subprocess.TimeoutExpired and assert the full
    acceptance set, keeping cleanup_decision strictly separate from
    scenario_decision (an intentional, controlled timeout is the expected
    outcome here, never a navigation PASS)."""

    def test_parent_cli_timeout_exercised_end_to_end(self):
        env = os.environ.copy()
        env[FAULT_ENV] = "1"
        out = Path(tempfile.gettempdir()) / "ottoguide_2h24_cli_e2e_test.json"
        proc = subprocess.run(
            [sys.executable, str(DRIVER_PATH), "--domain-id", "220", "--output", str(out)],
            env=env, capture_output=True, text=True, timeout=180,
        )
        data = json.loads(out.read_text())
        self.assertEqual(
            proc.returncode, 0,
            f"driver stdout={proc.stdout}\nstderr={proc.stderr}\ndata={json.dumps(data, indent=2)}",
        )
        self.assertEqual(data["cleanup_decision"], "PASS")
        self.assertEqual(data["scenario_decision"], "EXPECTED_TIMEOUT")
        self.assertNotEqual(data["parent_cli_exit_code"], 0)
        self.assertTrue(data["scenarios"], "expected at least one scenario reported")
        for sc in data["scenarios"]:
            self.assertTrue(sc.get("parent_timeout_cleanup_executed"))
            self.assertIn("CHILD_PROCESS_TIMEOUT", sc.get("errors", []))
            ev = sc["parent_timeout_cleanup_evidence"]
            self.assertTrue(ev["lease_validation"]["ok"])
            self.assertTrue(ev["child_identity_validation"]["ok"])
            self.assertTrue(ev["child_reaped"])
            self.assertFalse(ev["child_group_alive_after"])
            self.assertFalse(ev["sandbox_group_alive_after"])
            self.assertEqual(ev["owned_members_remaining"], [])
        self.assertEqual(data["zombies_remaining"], 0)
        self.assertTrue(data["sentinel"]["alive_after"])
        self.assertFalse(data["sentinel"]["signalled"])
        self.assertTrue(data["sentinel"]["reaped"])
        out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
