#!/usr/bin/env python3
"""Fase 2H.2.2 -- component probing error differentiation and anti-starvation.

Tests _node_list(), _lifecycle_get(), and wait_for_components_deterministic()
from the smoke-test runtime to verify:
  1. Each failure path (timeout, command_not_found, nonzero_exit, parse_error,
     lifecycle_unavailable) is distinguished rather than collapsed to a generic
     empty/None return.
  2. wait_for_components_deterministic() never starves late components when an
     early component is absent or slow to respond.
  3. Telemetry counters (node_list_attempts, lifecycle_query_count) equal the
     actual number of subprocess calls issued, not an approximate loop count.

Pure Python -- no ROS, no network, no hardware.  subprocess.run is patched for
every test case so no real ros2 binary is needed.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
SMOKE_PY = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation"
    / "smoke_test_main_runtime_navigation_selection.py"
)

if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))


def _load_smoke():
    spec = importlib.util.spec_from_file_location(
        "_smoke_runtime_probing", SMOKE_PY
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_smoke = _load_smoke()
_run = _smoke._run
_node_list = _smoke._node_list
_lifecycle_get = _smoke._lifecycle_get
wait_for_components = _smoke.wait_for_components_deterministic


def _cp(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestRunCommandResult(unittest.TestCase):
    """_run() must return _CommandResult with correct structured fields for every outcome."""

    def test_success_sets_error_class_none_and_is_not_timed_out(self):
        with patch("subprocess.run", return_value=_cp(stdout="hello\n", returncode=0)):
            result = _run(["ros2", "node", "list"], {}, timeout=1.0)
        self.assertEqual(result.error_class, "NONE")
        self.assertFalse(result.timed_out)
        self.assertEqual(result.stdout, "hello\n")
        self.assertEqual(result.returncode, 0)

    def test_timeout_sets_timed_out_true_and_preserves_partial_bytes_output(self):
        exc = subprocess.TimeoutExpired(
            ["ros2", "node", "list"], 1.0, output=b"partial\noutput", stderr=None
        )
        with patch("subprocess.run", side_effect=exc):
            result = _run(["ros2", "node", "list"], {}, timeout=1.0)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.error_class, "TIMEOUT")
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial\noutput")
        self.assertEqual(result.stderr, "")

    def test_file_not_found_sets_command_not_found_class_not_timed_out(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("no ros2")):
            result = _run(["ros2", "node", "list"], {}, timeout=1.0)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.error_class, "COMMAND_NOT_FOUND")
        self.assertEqual(result.returncode, 127)

    def test_nonzero_exit_sets_nonzero_exit_class(self):
        with patch("subprocess.run", return_value=_cp(returncode=2, stderr="err")):
            result = _run(["ros2", "node", "list"], {}, timeout=1.0)
        self.assertEqual(result.error_class, "NONZERO_EXIT")
        self.assertFalse(result.timed_out)


class TestNodeListErrorDifferentiation(unittest.TestCase):
    """_node_list() must distinguish each failure kind from success."""

    def test_success_with_nodes_returns_nonempty_list_no_error(self):
        with patch("subprocess.run", return_value=_cp(stdout="/node_a\n/node_b\n")):
            nodes, err = _node_list({}, timeout=1.0)
        self.assertEqual(nodes, ["/node_a", "/node_b"])
        self.assertIsNone(err)

    def test_success_with_empty_graph_returns_empty_list_no_error(self):
        with patch("subprocess.run", return_value=_cp(stdout="")):
            nodes, err = _node_list({}, timeout=1.0)
        self.assertEqual(nodes, [])
        self.assertIsNone(err)

    def test_timeout_is_differentiated_from_empty_success(self):
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["ros2", "node", "list"], 1.0)):
            nodes, err = _node_list({}, timeout=1.0)
        self.assertEqual(nodes, [])
        self.assertEqual(err, "TIMEOUT")

    def test_command_not_found_is_differentiated(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("ros2 not found")):
            nodes, err = _node_list({}, timeout=1.0)
        self.assertEqual(nodes, [])
        self.assertEqual(err, "COMMAND_NOT_FOUND")

    def test_nonzero_exit_is_differentiated_from_timeout(self):
        with patch("subprocess.run", return_value=_cp(returncode=1, stderr="some ros error")):
            nodes, err = _node_list({}, timeout=1.0)
        self.assertEqual(nodes, [])
        self.assertEqual(err, "NONZERO_EXIT")

    def test_file_not_found_raises_caught_as_command_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("ros2 not found")):
            nodes, err = _node_list({}, timeout=1.0)
        self.assertEqual(nodes, [])
        self.assertEqual(err, "COMMAND_NOT_FOUND")


class TestLifecycleGetErrorDifferentiation(unittest.TestCase):
    """_lifecycle_get() must distinguish each failure kind from success."""

    def test_valid_state_returned_on_success(self):
        with patch("subprocess.run", return_value=_cp(stdout="active [3]\n")):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertEqual(state, "active")
        self.assertIsNone(err)

    def test_non_active_state_parsed_correctly(self):
        with patch("subprocess.run", return_value=_cp(stdout="unconfigured [1]\n")):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertEqual(state, "unconfigured")
        self.assertIsNone(err)

    def test_timeout_is_differentiated(self):
        exc = subprocess.TimeoutExpired(
            ["ros2", "lifecycle", "get", "/nav/node"], 1.0
        )
        with patch("subprocess.run", side_effect=exc):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertIsNone(state)
        self.assertEqual(err, "TIMEOUT")

    def test_command_not_found_is_differentiated(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("ros2 not found")):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertIsNone(state)
        self.assertEqual(err, "COMMAND_NOT_FOUND")

    def test_nonzero_exit_without_lifecycle_hint_is_differentiated(self):
        with patch("subprocess.run",
                   return_value=_cp(returncode=1, stderr="generic ros error")):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertIsNone(state)
        self.assertEqual(err, "NONZERO_EXIT")

    def test_parse_error_on_empty_stdout_is_differentiated(self):
        with patch("subprocess.run", return_value=_cp(stdout="", returncode=0)):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertIsNone(state)
        self.assertEqual(err, "PARSE_ERROR")

    def test_lifecycle_unavailable_hint_in_stderr_is_differentiated(self):
        with patch("subprocess.run",
                   return_value=_cp(returncode=1,
                                    stderr="/nav/node is not a lifecycle node")):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertIsNone(state)
        self.assertEqual(err, "LIFECYCLE_UNAVAILABLE")

    def test_file_not_found_raises_caught_as_command_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("ros2 not found")):
            state, err = _lifecycle_get("/nav/node", {}, timeout=1.0)
        self.assertIsNone(state)
        self.assertEqual(err, "COMMAND_NOT_FOUND")


class TestWaitForComponentsAntiStarvation(unittest.TestCase):
    """wait_for_components_deterministic() must not starve later components."""

    def test_late_component_probed_when_early_is_absent_in_first_iteration(self):
        """When /early is not yet in node_list on iter 1, /late (which IS
        present) must still have its lifecycle queried in that same iteration.
        The single-shared-node-list design prevents per-component deadline
        starvation; this test verifies it end-to-end."""
        fqns = ["/early", "/late"]
        lifecycle_calls: list = []
        call_n = {"node_list": 0}

        def fake_run(cmd, **kwargs):
            if len(cmd) >= 3 and cmd[1] == "node" and cmd[2] == "list":
                call_n["node_list"] += 1
                stdout = "/late\n" if call_n["node_list"] == 1 else "/early\n/late\n"
                return _cp(stdout=stdout)
            if len(cmd) >= 3 and cmd[1] == "lifecycle" and cmd[2] == "get":
                fqn = cmd[-1]
                lifecycle_calls.append((call_n["node_list"], fqn))
                return _cp(stdout="active\n")
            return _cp(returncode=1)

        with patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"):
            ok, status = wait_for_components(fqns, {}, time.monotonic() + 30.0)

        self.assertTrue(ok)
        late_in_iter1 = any(it == 1 and fqn == "/late" for (it, fqn) in lifecycle_calls)
        self.assertTrue(
            late_in_iter1,
            f"/late was not queried in iter 1; lifecycle_calls={lifecycle_calls}"
        )

    def test_component_with_transient_lifecycle_error_recovers_and_reaches_active(self):
        """/comp gets a lifecycle error on iter 1 but must still be queried on
        iter 2 and can then transition to active — the function must not give
        up after a single failure."""
        fqns = ["/comp"]
        call_n = {"lc": 0}

        def fake_run(cmd, **kwargs):
            if len(cmd) >= 3 and cmd[1] == "node" and cmd[2] == "list":
                return _cp(stdout="/comp\n")
            if len(cmd) >= 3 and cmd[1] == "lifecycle" and cmd[2] == "get":
                call_n["lc"] += 1
                if call_n["lc"] == 1:
                    raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1.0))
                return _cp(stdout="active\n")
            return _cp(returncode=1)

        with patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"):
            ok, status = wait_for_components(fqns, {}, time.monotonic() + 30.0)

        self.assertTrue(ok)
        self.assertEqual(status["/comp"], "active")

    def test_lifecycle_error_kind_preserved_in_final_status(self):
        """When a component's lifecycle_get fails and the deadline expires before
        it recovers, the status string must include the specific error kind so
        the caller can distinguish timeout from parse_error from unavailable."""
        fqns = ["/comp"]

        def fake_run(cmd, **kwargs):
            if len(cmd) >= 3 and cmd[1] == "node" and cmd[2] == "list":
                return _cp(stdout="/comp\n")
            if len(cmd) >= 3 and cmd[1] == "lifecycle" and cmd[2] == "get":
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1.0))
            return _cp(returncode=1)

        # _run() now records duration via two time.monotonic() calls (t0 + end).
        # Sequence covers exactly the 7 calls made before the deadline expires:
        #   1. outer remaining check     (< 15.0 → keep looping)
        #   2. _run() t0 for node_list
        #   3. _run() duration for node_list
        #   4. remaining2 check          (< 15.0 → proceed to lifecycle_get)
        #   5. _run() t0 for lifecycle_get
        #   6. _run() duration for lifecycle_get (TimeoutExpired also measures)
        #   7. end-of-loop deadline check (>= 15.0 → break)
        mono_seq = [10.0, 10.0, 10.001, 10.002, 10.003, 10.004, 100.0]
        mono_idx = {"i": 0}

        def fake_mono():
            v = mono_seq[min(mono_idx["i"], len(mono_seq) - 1)]
            mono_idx["i"] += 1
            return v

        with patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"), \
             patch("time.monotonic", side_effect=fake_mono), \
             patch("time.monotonic_ns", return_value=int(10e9)):
            ok, status = wait_for_components(fqns, {}, deadline=15.0)

        self.assertFalse(ok)
        self.assertIn("TIMEOUT", status["/comp"],
                      f"error kind not preserved; got: {status['/comp']!r}")


class TestWaitForComponentsCounterAccuracy(unittest.TestCase):
    """Telemetry counters must equal actual subprocess call counts."""

    def test_node_list_attempts_equals_actual_ros2_node_list_calls(self):
        fqns = ["/comp"]
        actual_node_list = {"n": 0}
        call_n = {"n": 0}

        def fake_run(cmd, **kwargs):
            if len(cmd) >= 3 and cmd[1] == "node" and cmd[2] == "list":
                actual_node_list["n"] += 1
                call_n["n"] += 1
                return _cp(stdout="/comp\n" if call_n["n"] >= 2 else "")
            if len(cmd) >= 3 and cmd[1] == "lifecycle" and cmd[2] == "get":
                return _cp(stdout="active\n")
            return _cp(returncode=1)

        tel = {}
        with patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"):
            ok, _ = wait_for_components(fqns, {}, time.monotonic() + 30.0, _telemetry=tel)

        self.assertTrue(ok)
        self.assertEqual(tel["node_list_attempts"], actual_node_list["n"])

    def test_lifecycle_query_count_equals_actual_lifecycle_get_calls(self):
        fqns = ["/comp_a", "/comp_b"]
        actual_lc = {"n": 0}
        call_n = {"node_list": 0}

        def fake_run(cmd, **kwargs):
            if len(cmd) >= 3 and cmd[1] == "node" and cmd[2] == "list":
                call_n["node_list"] += 1
                if call_n["node_list"] <= 2:
                    return _cp(stdout="/comp_a\n")
                return _cp(stdout="/comp_a\n/comp_b\n")
            if len(cmd) >= 3 and cmd[1] == "lifecycle" and cmd[2] == "get":
                actual_lc["n"] += 1
                return _cp(stdout="active\n")
            return _cp(returncode=1)

        tel = {}
        with patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"):
            ok, _ = wait_for_components(fqns, {}, time.monotonic() + 30.0, _telemetry=tel)

        self.assertTrue(ok)
        self.assertEqual(tel["lifecycle_query_count"], actual_lc["n"])

    def test_lifecycle_query_errors_counts_only_failed_lifecycle_gets(self):
        fqns = ["/comp"]
        call_n = {"lc": 0}

        def fake_run(cmd, **kwargs):
            if len(cmd) >= 3 and cmd[1] == "node" and cmd[2] == "list":
                return _cp(stdout="/comp\n")
            if len(cmd) >= 3 and cmd[1] == "lifecycle" and cmd[2] == "get":
                call_n["lc"] += 1
                if call_n["lc"] <= 2:
                    return _cp(returncode=1, stderr="some error")
                return _cp(stdout="active\n")
            return _cp(returncode=1)

        tel = {}
        with patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"):
            ok, _ = wait_for_components(fqns, {}, time.monotonic() + 30.0, _telemetry=tel)

        self.assertTrue(ok)
        self.assertEqual(tel["lifecycle_query_errors"], 2)
        self.assertEqual(tel["lifecycle_query_count"], 3)


if __name__ == "__main__":
    unittest.main()
