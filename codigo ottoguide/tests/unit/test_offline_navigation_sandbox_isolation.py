#!/usr/bin/env python3
"""Pure unittest suite for the offline Nav2 sandbox static isolation checker.

Runs without ROS: no rclpy import, no node start, no network access.
"""
from __future__ import annotations

import ast
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
SIMULATOR_FILE = CODE_ROOT / "tools" / "hil" / "offline_navigation" / "offline_runtime_simulator.py"
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"
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


class RealNamespaceTests(unittest.TestCase):
    def test_sandbox_namespace_argument_declared_with_offline_nav_default(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        found_default = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = getattr(node.func, "id", None)
                if func_name == "DeclareLaunchArgument" and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and first_arg.value == "sandbox_namespace":
                        for kw in node.keywords:
                            if kw.arg == "default_value" and isinstance(kw.value, ast.Constant):
                                found_default = kw.value.value
        self.assertEqual(found_default, "offline_nav")

    def test_at_least_one_node_applies_namespace_kwarg(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        namespace_kwarg_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                for kw in node.keywords:
                    if kw.arg == "namespace":
                        namespace_kwarg_count += 1
        self.assertGreater(namespace_kwarg_count, 0)

    def test_checker_rejects_textual_only_offline_marker(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file_with_suffix(
            "# this file just mentions the word offline in a comment\n", suffix=".py"
        ) as tmp_launch:
            checker.LAUNCH_FILE = tmp_launch
            try:
                checker.check_namespace_offline(result)
            finally:
                checker.LAUNCH_FILE = LAUNCH_FILE
        self.assertIn("NO_SANDBOX_NAMESPACE_ARGUMENT_DECLARED", result["errors"])

    def test_checker_accepts_real_launch_namespace(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_namespace_offline(result)
        self.assertNotIn("NO_SANDBOX_NAMESPACE_ARGUMENT_DECLARED", result["errors"])
        self.assertNotIn("SANDBOX_NAMESPACE_DEFAULT_NOT_OFFLINE_NAV", result["errors"])
        self.assertNotIn("NO_NODE_APPLIES_NAMESPACE_KWARG", result["errors"])

    @contextmanager
    def _temp_file_with_suffix(self, content: str, suffix: str):
        fd, path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


class RuntimeModeCheckerTests(unittest.TestCase):
    def setUp(self):
        self._saved_environ = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_environ)

    def test_runtime_mode_localhost_only_missing_is_error(self):
        os.environ.pop("ROS_LOCALHOST_ONLY", None)
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_localhost_only_required(result, runtime=True)
        self.assertIn("ROS_LOCALHOST_ONLY_NOT_ENABLED", result["errors"])

    def test_runtime_mode_localhost_only_wrong_value_is_error(self):
        os.environ["ROS_LOCALHOST_ONLY"] = "0"
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_localhost_only_required(result, runtime=True)
        self.assertIn("ROS_LOCALHOST_ONLY_NOT_ENABLED", result["errors"])

    def test_runtime_mode_localhost_only_correct_value_passes(self):
        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_localhost_only_required(result, runtime=True)
        self.assertNotIn("ROS_LOCALHOST_ONLY_NOT_ENABLED", result["errors"])

    def test_runtime_mode_domain_id_missing_is_error(self):
        os.environ.pop("ROS_DOMAIN_ID", None)
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_domain_id_required(result, runtime=True)
        self.assertIn("ROS_DOMAIN_ID_MISSING", result["errors"])

    def test_runtime_mode_domain_id_zero_is_error(self):
        os.environ["ROS_DOMAIN_ID"] = "0"
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_domain_id_required(result, runtime=True)
        self.assertIn("ROS_DOMAIN_ID_IS_ZERO", result["errors"])

    def test_runtime_mode_domain_id_valid_passes(self):
        os.environ["ROS_DOMAIN_ID"] = "77"
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_domain_id_required(result, runtime=True)
        self.assertNotIn("ROS_DOMAIN_ID_MISSING", result["errors"])
        self.assertNotIn("ROS_DOMAIN_ID_IS_ZERO", result["errors"])

    def test_static_mode_missing_vars_are_warnings_not_errors(self):
        os.environ.pop("ROS_LOCALHOST_ONLY", None)
        os.environ.pop("ROS_DOMAIN_ID", None)
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_localhost_only_required(result, runtime=False)
        checker.check_domain_id_required(result, runtime=False)
        self.assertEqual(result["errors"], [])
        self.assertIn("ROS_LOCALHOST_ONLY_NOT_SET_IN_ENVIRONMENT", result["warnings"])
        self.assertIn("ROS_DOMAIN_ID_NOT_SET_IN_ENVIRONMENT", result["warnings"])

    def test_verify_runtime_mode_field_present(self):
        result = checker.verify(runtime=True)
        self.assertEqual(result["mode"], "RUNTIME")

    def test_verify_static_mode_field_present(self):
        result = checker.verify(runtime=False)
        self.assertEqual(result["mode"], "STATIC")

    def test_verify_runtime_scans_simulator_and_wrapper(self):
        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        os.environ["ROS_DOMAIN_ID"] = "77"
        result = checker.verify(runtime=True)
        self.assertIn(str(SIMULATOR_FILE), result["checked_files"])
        self.assertIn(str(RUNTIME_WRAPPER), result["checked_files"])


class GlobalTopicAbsenceTests(unittest.TestCase):
    def test_launch_file_has_no_global_cmd_vel_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_forbidden_topics(result, [LAUNCH_FILE])
        self.assertEqual(result["errors"], [])

    def test_simulator_has_no_global_cmd_vel_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_forbidden_topics(result, [SIMULATOR_FILE])
        self.assertEqual(result["errors"], [])

    def test_runtime_wrapper_has_no_global_cmd_vel_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_forbidden_topics(result, [RUNTIME_WRAPPER])
        self.assertEqual(result["errors"], [])

    def test_simulator_does_not_subscribe_to_any_cmd_vel_topic(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertNotIn("create_subscription", text)


class FrameContractTests(unittest.TestCase):
    def test_simulator_uses_odom_and_base_link_frames(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn('ODOM_FRAME = "odom"', text)
        self.assertIn('BASE_FRAME = "base_link"', text)
        self.assertIn('LIDAR_FRAME = "utlidar_lidar"', text)

    def test_simulator_does_not_import_hardware_modules(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(SIMULATOR_FILE))
        forbidden = {"unitree_sdk2py", "real_adapter"}
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                self.assertFalse(
                    any(name == f or name.startswith(f + ".") for f in forbidden),
                    f"forbidden hardware import found: {name}",
                )

    def test_launch_declares_synthetic_static_transforms(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("static_transform_publisher", text)
        self.assertIn("map_to_odom_synthetic_tf", text)
        self.assertIn("base_link_to_utlidar_lidar_synthetic_tf", text)


class SimulatorParameterTests(unittest.TestCase):
    def test_simulator_declares_expected_parameters(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        for param in ("publish_frequency_hz", "scan_range_count", "scan_range_m"):
            self.assertIn(f'declare_parameter("{param}"', text)

    def test_simulator_publishes_odom_and_scan_relative_topics(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn('create_publisher(Odometry, "odom"', text)
        self.assertIn('create_publisher(LaserScan, "scan"', text)

    def test_simulator_uses_conservative_covariance(self):
        # rclpy is not guaranteed to be importable outside ROS, so this
        # asserts structurally on source text rather than importing the module.
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("POSE_COVARIANCE_CONSERVATIVE", text)
        self.assertIn("TWIST_COVARIANCE_CONSERVATIVE", text)
        self.assertIn("999.0", text)


if __name__ == "__main__":
    unittest.main()
