#!/usr/bin/env python3
"""FASE A5 (R0B hotfix) - pruebas puras del gate post-launch (sin red real, sin DDS, sin
robot). Se inyectan _pid_alive y _get_health para no depender de /proc ni HTTP real.
Ejecutar: python tests/test_postlaunch_gate.py
"""
import json, os, sys, tempfile, time, shutil, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "companion"))
import postlaunch_gate as gate


class TestPostlaunchGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="postlaunch_gate_test_")
        os.makedirs(os.path.join(self.tmp, "recorder_data"), exist_ok=True)
        with open(os.path.join(self.tmp, "pids.json"), "w", encoding="utf-8") as f:
            json.dump({"supervisor": 111, "recorder": 222, "bridge": 333}, f)
        self._touch_recorder_state()
        self._orig_pid_alive = gate._pid_alive
        self._orig_get_health = gate._get_health
        gate._pid_alive = lambda pid: pid in (111, 222, 333)

    def tearDown(self):
        gate._pid_alive = self._orig_pid_alive
        gate._get_health = self._orig_get_health
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch_recorder_state(self):
        with open(os.path.join(self.tmp, "recorder_data", "recorder_state.json"), "w", encoding="utf-8") as f:
            json.dump({"final": False}, f)

    def _good_health(self):
        return {"session_id": "sess-1", "read_only_demo": True, "dds_writers_created": 0}, None

    def test_all_conditions_pass(self):
        gate._get_health = lambda host, port, timeout_s=2.0: self._good_health()
        passed, detail = gate.check_once(self.tmp, "sess-1", "127.0.0.1", 8000)
        self.assertTrue(passed, detail)

    def test_fails_when_session_id_mismatch(self):
        gate._get_health = lambda host, port, timeout_s=2.0: (
            {"session_id": "OTHER", "read_only_demo": True, "dds_writers_created": 0}, None)
        passed, detail = gate.check_once(self.tmp, "sess-1", "127.0.0.1", 8000)
        self.assertFalse(passed)
        self.assertFalse(detail["health_session_id_match"])

    def test_fails_when_dds_writers_created_nonzero(self):
        gate._get_health = lambda host, port, timeout_s=2.0: (
            {"session_id": "sess-1", "read_only_demo": True, "dds_writers_created": 1}, None)
        passed, detail = gate.check_once(self.tmp, "sess-1", "127.0.0.1", 8000)
        self.assertFalse(passed)
        self.assertFalse(detail["health_dds_writers_created_zero"])

    def test_fails_when_recorder_state_stale(self):
        gate._get_health = lambda host, port, timeout_s=2.0: self._good_health()
        old = time.time() - 30
        rs_path = os.path.join(self.tmp, "recorder_data", "recorder_state.json")
        os.utime(rs_path, (old, old))
        passed, detail = gate.check_once(self.tmp, "sess-1", "127.0.0.1", 8000)
        self.assertFalse(passed)
        self.assertFalse(detail["recorder_state_fresh"])

    def test_fails_when_pids_json_missing(self):
        os.remove(os.path.join(self.tmp, "pids.json"))
        gate._get_health = lambda host, port, timeout_s=2.0: self._good_health()
        passed, detail = gate.check_once(self.tmp, "sess-1", "127.0.0.1", 8000)
        self.assertFalse(passed)
        self.assertFalse(detail["pids_json_valid"])

    def test_fails_when_a_pid_is_dead(self):
        gate._pid_alive = lambda pid: pid in (111, 333)  # recorder (222) muerto
        gate._get_health = lambda host, port, timeout_s=2.0: self._good_health()
        passed, detail = gate.check_once(self.tmp, "sess-1", "127.0.0.1", 8000)
        self.assertFalse(passed)
        self.assertFalse(detail["recorder_pid_alive"])

    def test_fails_when_health_unreachable(self):
        gate._get_health = lambda host, port, timeout_s=2.0: (None, "connection refused")
        passed, detail = gate.check_once(self.tmp, "sess-1", "127.0.0.1", 8000)
        self.assertFalse(passed)
        self.assertFalse(detail["health_reachable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
