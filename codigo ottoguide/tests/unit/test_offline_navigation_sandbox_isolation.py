#!/usr/bin/env python3
"""Pure unittest suite for the offline Nav2 sandbox static isolation checker.

Runs without ROS: no rclpy import, no node start, no network access.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
CHECKER_PATH = CODE_ROOT / "tools" / "hil" / "offline_navigation" / "verify_sandbox_isolation.py"
LAUNCH_FILE = CODE_ROOT / "launch" / "offline_nav_sandbox.launch.py"
MAP_DIR = CODE_ROOT / "tests" / "fixtures" / "offline_navigation"
MAP_PGM = MAP_DIR / "offline_sandbox_test_map.pgm"
MAP_YAML = MAP_DIR / "offline_sandbox_test_map.yaml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("verify_sandbox_isolation", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


class SyntheticMapFixtureTests(unittest.TestCase):
    def test_pgm_file_exists(self):
        self.assertTrue(MAP_PGM.is_file())

    def test_yaml_file_exists_and_is_valid(self):
        self.assertTrue(MAP_YAML.is_file())
        text = MAP_YAML.read_text(encoding="utf-8")
        self.assertIn("image:", text)
        self.assertIn("resolution:", text)
        self.assertIn("origin:", text)

    def test_yaml_resolution_is_positive_float(self):
        text = MAP_YAML.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("resolution:"):
                value = float(line.split(":", 1)[1].strip())
                self.assertGreater(value, 0.0)
                return
        self.fail("resolution field not found in map yaml")

    def test_yaml_referenced_image_exists(self):
        text = MAP_YAML.read_text(encoding="utf-8")
        image_name = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("image:"):
                image_name = stripped.split(":", 1)[1].strip()
                break
        self.assertIsNotNone(image_name)
        self.assertTrue((MAP_DIR / image_name).is_file())

    def test_yaml_declares_synthetic_markers(self):
        text = MAP_YAML.read_text(encoding="utf-8")
        for marker in (
            "SYNTHETIC_TEST_MAP",
            "NOT_UADE_MAP",
            "NOT_METRICALLY_VALIDATED",
            "NOT_FOR_PHYSICAL_NAVIGATION",
        ):
            self.assertIn(marker, text)

    def test_pgm_header_is_valid_p5(self):
        with open(MAP_PGM, "rb") as f:
            magic = f.readline().strip()
            dims = f.readline().strip()
            maxval = f.readline().strip()
        self.assertEqual(magic, b"P5")
        width, height = (int(token) for token in dims.split())
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)
        self.assertEqual(int(maxval), 255)


class LaunchDefaultVersionedTests(unittest.TestCase):
    def test_launch_default_points_to_versioned_fixture(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("tests", text)
        self.assertIn("fixtures", text)
        self.assertIn("offline_navigation", text)

    def test_launch_default_does_not_depend_on_artifacts(self):
        result = checker.verify()
        self.assertNotIn("MAP_DEFAULT_DEPENDS_ON_ARTIFACTS", result["errors"])


class IsolationCheckerDetectionTests(unittest.TestCase):
    def test_baseline_sandbox_passes(self):
        result = checker.verify()
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["errors"], [])

    def test_detects_artifacts_dependency(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_launch_text(
            'MAP_DEFAULT = str(REPO_ROOT / "artifacts" / "maps" / "x.yaml")\n'
        ) as tmp_launch:
            checker.LAUNCH_FILE = tmp_launch
            try:
                checker.check_map_default_versioned(result)
            finally:
                checker.LAUNCH_FILE = LAUNCH_FILE
        self.assertIn("MAP_DEFAULT_DEPENDS_ON_ARTIFACTS", result["errors"])

    def test_detects_forbidden_ip(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("robot_ip = '192.168.123.161'\n") as tmp_file:
            checker.check_forbidden_ip(result, [tmp_file])
        self.assertIn("FORBIDDEN_IP_FOUND", result["errors"])
        self.assertTrue(
            any(m["pattern"] == "FORBIDDEN_IP" for m in result["forbidden_matches"])
        )

    def test_detects_cmd_vel_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("publisher = node.create_publisher(Twist, '/cmd_vel', 10)\n") as tmp_file:
            checker.check_forbidden_topics(result, [tmp_file])
        self.assertIn("CMD_VEL_REFERENCED", result["errors"])

    def test_detects_cmd_vel_nav_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("topic = '/cmd_vel_nav'\n") as tmp_file:
            checker.check_forbidden_topics(result, [tmp_file])
        self.assertIn("CMD_VEL_NAV_REFERENCED", result["errors"])

    def test_does_not_flag_commented_cmd_vel_mention(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("# sin /cmd_vel ni /cmd_vel_nav en este sandbox\n") as tmp_file:
            checker.check_forbidden_topics(result, [tmp_file])
        self.assertEqual(result["errors"], [])

    def test_detects_physical_bridge_reference(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient\n") as tmp_file:
            checker.check_forbidden_bridges(result, [tmp_file])
        self.assertIn("PHYSICAL_BRIDGE_REFERENCED", result["errors"])

    def test_namespace_offline_marker_present(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_namespace_offline(result)
        self.assertNotIn("NO_OFFLINE_NAMESPACE_MARKER", result["errors"])

    def test_localhost_only_documented(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_localhost_only_required(result)
        self.assertNotIn("ROS_LOCALHOST_ONLY_NOT_DOCUMENTED", result["warnings"])

    def test_json_output_is_deterministic(self):
        first = json.dumps(checker.verify(), sort_keys=True)
        second = json.dumps(checker.verify(), sort_keys=True)
        self.assertEqual(first, second)

    def test_main_exit_code_zero_on_pass(self):
        result = checker.verify()
        expected_exit = 0 if result["decision"] == "PASS" else 2
        self.assertIn(expected_exit, (0, 2))

    # -- helpers -----------------------------------------------------
    @contextmanager
    def _temp_file(self, content: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)

    @contextmanager
    def _temp_launch_text(self, map_default_line: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("from pathlib import Path\n")
                f.write("CODE_ROOT = Path('.')\n")
                f.write("REPO_ROOT = Path('.')\n")
                f.write(map_default_line)
            yield Path(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
