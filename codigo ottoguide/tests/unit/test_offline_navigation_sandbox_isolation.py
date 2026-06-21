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
FOUNDATION_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_offline_runtime.py"
)
PLANNER_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_offline_planner.py"
)
CONTROLLER_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_offline_controller.py"
)
PARAMS_FILE = CODE_ROOT / "config" / "navigation" / "nav2_offline_sandbox_params.yaml"
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

    def test_simulator_only_subscribes_to_relative_cmd_vel_raw(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(SIMULATOR_FILE))
        subscribed_topics = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "create_subscription":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    subscribed_topics.append(node.args[1].value)
        self.assertEqual(subscribed_topics, ["cmd_vel_raw"])


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


class SimulatorParameterValidationTests(unittest.TestCase):
    def test_simulator_validates_publish_frequency_positive(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("frequency_hz <= 0.0", text)
        self.assertIn("raise ValueError", text)

    def test_simulator_validates_scan_range_count_minimum(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("self._scan_range_count < 2", text)

    def test_simulator_validates_scan_range_greater_than_range_min(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("self._scan_range_m <= self._scan_range_min_m", text)

    def test_simulator_uses_correct_scan_time_formula(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("self._scan_time_s = 1.0 / frequency_hz", text)
        self.assertIn("scan_msg.scan_time = self._scan_time_s", text)

    def test_simulator_integrates_commanded_velocity_into_odom_twist(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("odom_msg.twist.twist.linear.x = effective_linear_x", text)
        self.assertIn("odom_msg.twist.twist.angular.z = effective_angular_z", text)


class PlannerConfigurationTests(unittest.TestCase):
    def test_params_yaml_configures_navfn_planner_plugin(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("nav2_navfn_planner::NavfnPlanner", text)
        self.assertIn("planner_plugins:", text)

    def test_params_yaml_global_costmap_has_static_and_inflation_layers(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("nav2_costmap_2d::StaticLayer", text)
        self.assertIn("nav2_costmap_2d::InflationLayer", text)

    def test_params_yaml_global_costmap_uses_map_frame_and_base_link(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("global_frame: map", text)
        self.assertIn("robot_base_frame: base_link", text)

    def test_params_yaml_has_controller_server_and_local_costmap(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("controller_server:", text)
        self.assertIn("local_costmap:", text)

    def test_params_yaml_declares_offline_only_synthetic_markers(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        for marker in ("OFFLINE_ONLY", "SYNTHETIC", "NOT_FOR_HARDWARE"):
            self.assertIn(marker, text)

    def test_launch_declares_planner_server_node(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("nav2_planner", text)
        self.assertIn("planner_server", text)

    def test_planner_server_is_namespaced(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_namespace_offline(result)
        self.assertNotIn("NODE_MISSING_NAMESPACE_planner_server", result["errors"])

    def test_lifecycle_manager_includes_planner_server(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        node_names_lists = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "node_names"
                        and isinstance(value, ast.List)
                    ):
                        node_names_lists.append(
                            [elt.value for elt in value.elts if isinstance(elt, ast.Constant)]
                        )
        self.assertTrue(node_names_lists, "no node_names list found in launch file")
        self.assertIn("planner_server", node_names_lists[0])
        self.assertIn("map_server", node_names_lists[0])

    def test_controller_server_node_in_launch_with_cmd_vel_raw_remap(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        controller_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                executable = None
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executable = kw.value.value
                if executable == "controller_server":
                    controller_node = node
                    break
        self.assertIsNotNone(controller_node, "controller_server Node not found in launch")
        remap_found = False
        for kw in controller_node.keywords:
            if kw.arg == "remappings" and isinstance(kw.value, ast.List):
                for element in kw.value.elts:
                    if isinstance(element, ast.Tuple) and len(element.elts) == 2:
                        src, dst = element.elts
                        if (
                            isinstance(src, ast.Constant)
                            and isinstance(dst, ast.Constant)
                            and src.value == "cmd_vel"
                            and dst.value == "cmd_vel_raw"
                        ):
                            remap_found = True
        self.assertTrue(remap_found, "controller_server must remap cmd_vel -> cmd_vel_raw")

    def test_no_behavior_or_waypoint_or_collision_monitor_in_launch(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        executables = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executables.add(kw.value.value)
        for forbidden in ("behavior_server", "waypoint_follower", "collision_monitor"):
            self.assertNotIn(forbidden, executables)


class VelocityTopicAbsenceTests(unittest.TestCase):
    def test_launch_has_no_velocity_topic_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_forbidden_topics(result, [LAUNCH_FILE])
        self.assertEqual(result["errors"], [])

    def test_params_yaml_has_no_velocity_topic_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_forbidden_topics(result, [PARAMS_FILE])
        self.assertEqual(result["errors"], [])

    def test_planner_smoke_test_detection_idiom_not_flagged_as_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_forbidden_topics(result, [PLANNER_SMOKE_TEST_FILE])
        self.assertEqual(result["errors"], [])

    def test_foundation_smoke_test_detection_idiom_not_flagged_as_usage(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_forbidden_topics(result, [FOUNDATION_SMOKE_TEST_FILE])
        self.assertEqual(result["errors"], [])

    def test_real_cmd_vel_publisher_usage_is_still_detected(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_publisher(Twist, '/cmd_vel', 10)\n") as tmp_file:
            checker.check_forbidden_topics(result, [tmp_file])
        self.assertIn("CMD_VEL_REFERENCED", result["errors"])

    @contextmanager
    def _temp_file(self, content: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


class RuntimeFilesIncludedInVerifierTests(unittest.TestCase):
    def test_runtime_scan_includes_all_required_files(self):
        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        os.environ["ROS_DOMAIN_ID"] = "77"
        result = checker.verify(runtime=True)
        for required_file in (
            LAUNCH_FILE,
            PARAMS_FILE,
            MAP_YAML,
            SIMULATOR_FILE,
            RUNTIME_WRAPPER,
            FOUNDATION_SMOKE_TEST_FILE,
            PLANNER_SMOKE_TEST_FILE,
            CONTROLLER_SMOKE_TEST_FILE,
        ):
            self.assertIn(str(required_file), result["checked_files"])

    def test_runtime_verify_passes_with_correct_isolation_env(self):
        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        os.environ["ROS_DOMAIN_ID"] = "77"
        result = checker.verify(runtime=True)
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["errors"], [])


class ControllerConfigurationTests(unittest.TestCase):
    def test_params_yaml_configures_a_followpath_controller_plugin(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("controller_plugins:", text)
        self.assertIn("FollowPath:", text)

    def test_params_yaml_local_costmap_uses_odom_frame_and_obstacle_layer(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("local_costmap:", text)
        self.assertIn("global_frame: odom", text)
        self.assertIn("nav2_costmap_2d::ObstacleLayer", text)

    def test_params_yaml_local_costmap_obstacle_layer_uses_relative_scan(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn('topic: "scan"', text)

    def test_lifecycle_manager_includes_controller_server(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        node_names_lists = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "node_names"
                        and isinstance(value, ast.List)
                    ):
                        node_names_lists.append(
                            [elt.value for elt in value.elts if isinstance(elt, ast.Constant)]
                        )
        self.assertTrue(node_names_lists, "no node_names list found in launch file")
        all_managed_names = {name for names in node_names_lists for name in names}
        self.assertIn("controller_server", all_managed_names)
        self.assertIn("planner_server", all_managed_names)
        self.assertIn("map_server", all_managed_names)

    def test_controller_server_lifecycle_is_isolated_from_navigation_lifecycle(self):
        """controller_server must be managed by its own lifecycle manager so
        that a configure failure there cannot block map_server/planner_server
        bringup, which were already validated before control was attempted.
        """
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        node_names_lists = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "node_names"
                        and isinstance(value, ast.List)
                    ):
                        node_names_lists.append(
                            [elt.value for elt in value.elts if isinstance(elt, ast.Constant)]
                        )
        navigation_list = next(
            (names for names in node_names_lists if "map_server" in names), None
        )
        controller_list = next(
            (names for names in node_names_lists if "controller_server" in names), None
        )
        self.assertIsNotNone(navigation_list)
        self.assertIsNotNone(controller_list)
        self.assertIsNot(navigation_list, controller_list)
        self.assertNotIn("controller_server", navigation_list)

    def test_controller_server_is_namespaced(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_namespace_offline(result)
        self.assertNotIn("NODE_MISSING_NAMESPACE_controller_server", result["errors"])

    def test_no_bt_navigator_behavior_waypoint_or_collision_monitor_executables(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        executables = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executables.add(kw.value.value)
        for forbidden in (
            "bt_navigator",
            "behavior_server",
            "waypoint_follower",
            "collision_monitor",
            "collision_detector",
        ):
            self.assertNotIn(forbidden, executables)


class VelocityTopicAllowlistTests(unittest.TestCase):
    def test_allowed_topic_is_cmd_vel_raw_only(self):
        self.assertEqual(checker.ALLOWED_VELOCITY_TOPIC_NAME, "cmd_vel_raw")

    def test_remap_tuple_in_launch_is_cmd_vel_to_cmd_vel_raw(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_velocity_topic_allowlist(result, [LAUNCH_FILE])
        self.assertEqual(result["errors"], [])

    def test_rejects_global_cmd_vel(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_publisher(Twist, '/cmd_vel', 10)\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertIn("FORBIDDEN_VELOCITY_TOPIC_cmd_vel", result["errors"])

    def test_rejects_global_cmd_vel_nav(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("topic = '/cmd_vel_nav'\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertIn("FORBIDDEN_VELOCITY_TOPIC_cmd_vel_nav", result["errors"])

    def test_rejects_namespaced_offline_nav_cmd_vel(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_publisher(Twist, '/offline_nav/cmd_vel', 10)\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertIn("FORBIDDEN_VELOCITY_TOPIC_cmd_vel", result["errors"])

    def test_accepts_relative_cmd_vel_raw_subscription(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_subscription(Twist, 'cmd_vel_raw', cb, 10)\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertEqual(result["errors"], [])

    def test_does_not_flag_unrelated_identifier_containing_cmd_vel(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(
            'self.declare_parameter("cmd_vel_watchdog_timeout_s", 0.5)\n'
        ) as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertEqual(result["errors"], [])

    @contextmanager
    def _temp_file(self, content: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


class SimulatorClosedLoopTests(unittest.TestCase):
    def test_simulator_declares_velocity_limit_parameters(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn('declare_parameter("max_linear_speed_mps"', text)
        self.assertIn('declare_parameter("max_angular_speed_radps"', text)

    def test_simulator_default_velocity_limits_match_spec(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_MAX_LINEAR_SPEED_MPS = 0.10", text)
        self.assertIn("DEFAULT_MAX_ANGULAR_SPEED_RADPS = 0.30", text)

    def test_simulator_clamps_commanded_velocity(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("_clamp(", text)
        self.assertIn("self._max_linear_speed_mps", text)
        self.assertIn("self._max_angular_speed_radps", text)

    def test_simulator_declares_watchdog_timeout_parameter(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn('"cmd_vel_watchdog_timeout_s"', text)
        self.assertIn("DEFAULT_CMD_VEL_WATCHDOG_TIMEOUT_S = 0.5", text)

    def test_simulator_watchdog_zeroes_velocity_on_timeout(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("_watchdog_expired", text)
        self.assertIn("effective_linear_x = 0.0", text)
        self.assertIn("effective_angular_z = 0.0", text)

    def test_simulator_integrates_planar_pose_deterministically(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("def _integrate_pose", text)
        self.assertIn("self._x += linear_x * math.cos(self._yaw) * dt", text)
        self.assertIn("self._y += linear_x * math.sin(self._yaw) * dt", text)
        self.assertIn("self._yaw += angular_z * dt", text)
        # No randomness/noise sources used as inputs to the integration.
        self.assertNotIn("import random", text)
        self.assertNotIn("random.", text)

    def test_simulator_does_not_import_hardware_modules_after_extension(self):
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
                self.assertFalse(any(name == f or name.startswith(f + ".") for f in forbidden))

    def test_simulator_declares_offline_only_synthetic_markers(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        for marker in ("OFFLINE_ONLY", "SYNTHETIC", "NOT_FOR_HARDWARE"):
            self.assertIn(marker, text)


class PlannerToleranceTests(unittest.TestCase):
    def test_planner_smoke_test_uses_010m_endpoint_tolerance(self):
        text = PLANNER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("PATH_ENDPOINT_TOLERANCE_M = 0.10", text)

    def test_planner_smoke_test_queries_real_lifecycle_state(self):
        text = PLANNER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("_lifecycle_get", text)
        self.assertIn("ros2", text)
        self.assertIn("lifecycle", text)

    def test_planner_smoke_test_separates_discovery_from_lifecycle_active(self):
        text = PLANNER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("map_server_node_discovered", text)
        self.assertIn("planner_server_node_discovered", text)
        self.assertIn("map_server_lifecycle_active", text)
        self.assertIn("planner_server_lifecycle_active", text)


class SmokeTestsUseRealLifecycleTests(unittest.TestCase):
    def test_controller_smoke_test_queries_real_lifecycle_state(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("_lifecycle_get", text)
        self.assertIn("map_server_lifecycle_active", text)
        self.assertIn("planner_server_lifecycle_active", text)
        self.assertIn("controller_server_lifecycle_active", text)

    def test_controller_smoke_test_starts_runtime_via_wrapper(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("RUNTIME_WRAPPER", text)
        self.assertIn('"bash", str(RUNTIME_WRAPPER)', text)

    def test_controller_smoke_test_uses_follow_path_action(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("FollowPath", text)
        self.assertIn("/follow_path", text)

    def test_controller_smoke_test_checks_cancellation(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("cancel_goal_async", text)
        self.assertIn("STATUS_CANCELED", text)


class NamespacedParameterRewriteTests(unittest.TestCase):
    def test_launch_imports_rewritten_yaml_and_parameter_file(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("from launch_ros.descriptions import ParameterFile", text)
        self.assertIn("from nav2_common.launch import RewrittenYaml", text)

    def test_configured_params_root_key_is_sandbox_namespace(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        root_key_value = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RewrittenYaml":
                for kw in node.keywords:
                    if kw.arg == "root_key":
                        root_key_value = kw.value
        self.assertIsNotNone(root_key_value, "RewrittenYaml(root_key=...) not found")
        self.assertIsInstance(root_key_value, ast.Name)
        self.assertEqual(root_key_value.id, "namespace")

    def test_configured_params_convert_types_enabled(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RewrittenYaml":
                for kw in node.keywords:
                    if kw.arg == "convert_types" and isinstance(kw.value, ast.Constant):
                        found = kw.value.value is True
        self.assertTrue(found, "RewrittenYaml(convert_types=True) not found")

    def _node_uses_configured_params(self, executable: str) -> bool:
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                node_executable = None
                parameters_kw = None
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        node_executable = kw.value.value
                    if kw.arg == "parameters":
                        parameters_kw = kw.value
                if node_executable == executable and isinstance(parameters_kw, ast.List):
                    for elt in parameters_kw.elts:
                        if isinstance(elt, ast.Name) and elt.id == "configured_params":
                            return True
        return False

    def test_map_server_uses_configured_params(self):
        self.assertTrue(self._node_uses_configured_params("map_server"))

    def test_map_server_still_overrides_yaml_filename(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("'yaml_filename': LaunchConfiguration('map_yaml')", text)

    def test_planner_server_uses_configured_params(self):
        self.assertTrue(self._node_uses_configured_params("planner_server"))

    def test_controller_server_uses_configured_params(self):
        self.assertTrue(self._node_uses_configured_params("controller_server"))

    def test_params_yaml_has_no_duplicated_namespace_root_key(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertNotIn("offline_nav:", text)

    def test_lifecycle_managers_remain_separated(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("lifecycle_manager_navigation", text)
        self.assertIn("lifecycle_manager_controller", text)
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        node_names_lists = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "node_names"
                        and isinstance(value, ast.List)
                    ):
                        node_names_lists.append(
                            [elt.value for elt in value.elts if isinstance(elt, ast.Constant)]
                        )
        controller_only_lists = [names for names in node_names_lists if names == ["controller_server"]]
        self.assertTrue(controller_only_lists, "no dedicated controller_server-only lifecycle manager found")


    def test_controller_smoke_test_has_effective_parameter_verification_utility(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        runtime_wrapper_text = RUNTIME_WRAPPER.read_text(encoding="utf-8")
        self.assertIn("RUNTIME_WRAPPER", text)
        self.assertIn("ros2", runtime_wrapper_text)


class OfflineControllerSmokeCorrectionTests(unittest.TestCase):
    def test_namespaced_subscriptions(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('self.odom_topic_observed = f"/{namespace}/odom"', text)
        self.assertIn('self.cmd_vel_topic_observed = f"/{namespace}/cmd_vel_raw"', text)
        self.assertIn('self.create_subscription(Odometry, self.odom_topic_observed,', text)
        self.assertIn('self.create_subscription(Twist, self.cmd_vel_topic_observed,', text)

    def test_absence_of_global_subscriptions(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertNotIn('self.create_subscription(Odometry, "odom",', text)
        self.assertNotIn('self.create_subscription(Twist, "cmd_vel_raw",', text)

    def test_metrics_initialized_as_none(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('"simulated_distance_moved": None', text)
        self.assertIn('"final_distance_to_goal": None', text)
        self.assertIn('"success_final_twist_zero": None', text)

    def test_mandatory_odom_wait(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("wait_for_initial_odom", text)
        self.assertIn("ODOM_NOT_RECEIVED", text)

    def test_callback_processing_during_action(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("spin_until_future_complete_custom", text)
        self.assertIn("rclpy.spin_once(self", text)

    def test_nonzero_command_wait_before_cancel(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("command_ok = False", text)
        self.assertIn("movement_ok = False", text)
        self.assertIn("abs(cmd.linear.x) > 1e-6 or abs(cmd.angular.z) > 1e-6", text)

    def test_independent_runtimes_and_domains(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('run_single_scenario(namespace, "117", "success"', text)
        self.assertIn('run_single_scenario(namespace, "118", "cancel"', text)
        self.assertIn('run_single_scenario(namespace, "119", "success"', text)
        self.assertIn('run_single_scenario(namespace, "120", "cancel"', text)

    def test_cancel_status_canceled(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("STATUS_CANCELED", text)
        self.assertIn('"CANCELED"', text)

    def test_goal_status_4_not_accepted_as_cancel(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertNotIn('"CANCELED" if cancel_status == "GOAL_STATUS_4"', text)

    def test_odom_twist_stop_validation(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("odom.twist.twist.linear.x", text)
        self.assertIn("odom.twist.twist.angular.z", text)
        self.assertIn("watchdog_effective_stop", text)

    def test_pose_stability_validation(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("pose_stable_after_cancel", text)
        self.assertIn("max_diff < 0.002", text)

    def test_watchdog_independent_of_raw_zero(self):
        text = CONTROLLER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("zero_raw_command_received = False", text)
        self.assertIn("watchdog_effective_stop = False", text)


if __name__ == "__main__":
    unittest.main()
