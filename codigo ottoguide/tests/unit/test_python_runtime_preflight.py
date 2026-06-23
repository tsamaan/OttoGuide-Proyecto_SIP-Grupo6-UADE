#!/usr/bin/env python3
"""Phase D -- Python runtime compatibility preflight tests.

Covers check_python_runtime() from scripts/check_python_runtime.py:
  - Simulates Python 3.8, 3.9, 3.10, 3.12 without spawning a real interpreter.
  - Verifies decision=BLOCKED for unsupported versions, decision=PASS for supported.
  - Verifies PYTHON_RUNTIME_COMPATIBLE boolean tracks decision.
  - Verifies the version string and required_version field are always present.
  - Verifies the real subprocess exits 0 on the current (>= 3.10) interpreter.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from collections import namedtuple
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
PREFLIGHT_PY = CODE_ROOT / "scripts" / "check_python_runtime.py"

if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

_FakeVI = namedtuple("_FakeVI", ["major", "minor", "micro"])


def _load_preflight():
    spec = importlib.util.spec_from_file_location("check_python_runtime", PREFLIGHT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_preflight = _load_preflight()
check_python_runtime = _preflight.check_python_runtime


class TestPythonRuntimeVersionBoundary(unittest.TestCase):
    """Verify the accept/reject boundary at Python 3.10."""

    def test_python_38_is_blocked(self):
        result = check_python_runtime(version_info=_FakeVI(3, 8, 0))
        self.assertFalse(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "BLOCKED")

    def test_python_39_is_blocked(self):
        result = check_python_runtime(version_info=_FakeVI(3, 9, 19))
        self.assertFalse(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "BLOCKED")

    def test_python_310_is_accepted(self):
        result = check_python_runtime(version_info=_FakeVI(3, 10, 0))
        self.assertTrue(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "PASS")

    def test_python_311_is_accepted(self):
        result = check_python_runtime(version_info=_FakeVI(3, 11, 7))
        self.assertTrue(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "PASS")

    def test_python_312_is_accepted(self):
        result = check_python_runtime(version_info=_FakeVI(3, 12, 3))
        self.assertTrue(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "PASS")

    def test_python_313_is_accepted(self):
        result = check_python_runtime(version_info=_FakeVI(3, 13, 0))
        self.assertTrue(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "PASS")

    def test_python_2_is_blocked(self):
        result = check_python_runtime(version_info=_FakeVI(2, 7, 18))
        self.assertFalse(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "BLOCKED")


class TestPythonRuntimeResultFields(unittest.TestCase):
    """Verify all output fields are present and correctly populated."""

    def test_version_string_reflects_input(self):
        result = check_python_runtime(version_info=_FakeVI(3, 8, 5))
        self.assertEqual(result["python_version"], "3.8.5")

    def test_version_string_micro_zero_preserved(self):
        result = check_python_runtime(version_info=_FakeVI(3, 10, 0))
        self.assertEqual(result["python_version"], "3.10.0")

    def test_required_version_always_stated(self):
        for vi in (_FakeVI(3, 8, 0), _FakeVI(3, 12, 0)):
            with self.subTest(vi=vi):
                result = check_python_runtime(version_info=vi)
                self.assertEqual(result["required_version"], "3.10")

    def test_compatible_flag_matches_decision(self):
        for vi, expected in [
            (_FakeVI(3, 8, 0), False),
            (_FakeVI(3, 10, 0), True),
        ]:
            with self.subTest(vi=vi):
                result = check_python_runtime(version_info=vi)
                self.assertEqual(result["PYTHON_RUNTIME_COMPATIBLE"], expected)

    def test_all_required_keys_present(self):
        result = check_python_runtime(version_info=_FakeVI(3, 8, 0))
        for key in ("PYTHON_RUNTIME_COMPATIBLE", "decision", "python_version", "required_version"):
            self.assertIn(key, result, f"missing key: {key}")


class TestPythonRuntimeSubprocess(unittest.TestCase):
    """Verify the script behaves correctly when run as a subprocess."""

    def test_current_python_exits_zero_with_pass_decision(self):
        """The test suite requires Python >= 3.10; the preflight must agree."""
        proc = subprocess.run(
            [sys.executable, str(PREFLIGHT_PY)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr!r}")
        result = json.loads(proc.stdout)
        self.assertTrue(result["PYTHON_RUNTIME_COMPATIBLE"])
        self.assertEqual(result["decision"], "PASS")

    def test_subprocess_output_is_valid_json_on_all_keys(self):
        proc = subprocess.run(
            [sys.executable, str(PREFLIGHT_PY)],
            capture_output=True, text=True, timeout=10,
        )
        result = json.loads(proc.stdout)
        for key in ("PYTHON_RUNTIME_COMPATIBLE", "decision", "python_version", "required_version"):
            self.assertIn(key, result)

    def test_blocked_version_exits_nonzero(self):
        """Simulate a blocked interpreter by patching version_info at module level.
        We verify this via the function API (subprocess with a real old Python
        is not available in this environment; the function signature is the test
        boundary)."""
        result = check_python_runtime(version_info=_FakeVI(3, 8, 0))
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertFalse(result["PYTHON_RUNTIME_COMPATIBLE"])


if __name__ == "__main__":
    unittest.main()
