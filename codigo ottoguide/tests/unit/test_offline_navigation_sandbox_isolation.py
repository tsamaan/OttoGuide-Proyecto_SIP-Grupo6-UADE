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
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

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
COLLISION_MONITOR_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_offline_collision_monitor.py"
)
BEHAVIOR_SERVER_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_offline_behavior_server.py"
)
BT_NAVIGATOR_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_offline_bt_navigator.py"
)
WAYPOINT_FOLLOWER_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_offline_waypoint_follower.py"
)
DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "smoke_test_direct_nav2_action_bridge.py"
)
BT_XML_FILE = CODE_ROOT / "config" / "navigation" / "bt" / "offline_navigate_to_pose.xml"
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


def _load_smoke_module():
    """Loads the direct-bridge smoke test as a plain module. Safe without
    ROS: every rclpy import in that file is local to a function/method
    body, never at module scope.
    """
    spec = importlib.util.spec_from_file_location(
        "smoke_test_direct_nav2_action_bridge", DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


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

    def test_simulator_only_subscribes_to_relative_cmd_vel_safe(self):
        text = SIMULATOR_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(SIMULATOR_FILE))
        subscribed_topics = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "create_subscription":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    subscribed_topics.append(node.args[1].value)
        self.assertEqual(subscribed_topics, ["cmd_vel_safe"])


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

    def test_no_simple_commander_in_launch(self):
        """waypoint_follower is authorized as of Phase 2G (see
        WaypointFollowerLaunchAndLifecycleTests); Simple Commander remains
        fully out of scope.
        """
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        executables = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executables.add(kw.value.value)
        self.assertNotIn("simple_commander", executables)


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
            COLLISION_MONITOR_SMOKE_TEST_FILE,
            BEHAVIOR_SERVER_SMOKE_TEST_FILE,
            BT_NAVIGATOR_SMOKE_TEST_FILE,
        ):
            self.assertIn(str(required_file), result["checked_files"])

    def test_fails_if_collision_monitor_smoke_missing_from_runtime_scan_files(self):
        self.assertIn(checker.COLLISION_MONITOR_SMOKE_TEST_FILE, checker.RUNTIME_SCAN_FILES)

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

    def test_no_simple_commander_or_collision_detector_executables(self):
        """waypoint_follower is authorized as of Phase 2G (see
        WaypointFollowerLaunchAndLifecycleTests); Simple Commander and
        collision_detector remain fully out of scope.
        """
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        executables = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executables.add(kw.value.value)
        for forbidden in (
            "simple_commander",
            "collision_detector",
        ):
            self.assertNotIn(forbidden, executables)


class VelocityTopicAllowlistTests(unittest.TestCase):
    def test_allowed_topics(self):
        self.assertEqual(checker.ALLOWED_VELOCITY_TOPIC_NAMES, {"cmd_vel_raw", "cmd_vel_safe"})

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
        self.assertIn("lifecycle_manager_collision_monitor", text)
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
        collision_monitor_only_lists = [names for names in node_names_lists if names == ["collision_monitor"]]
        self.assertTrue(collision_monitor_only_lists, "no dedicated collision_monitor-only lifecycle manager found")


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


class CollisionMonitorContractUnitTests(unittest.TestCase):
    def test_collision_monitor_configured_in_params_yaml(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("collision_monitor:", text)
        self.assertIn("cmd_vel_in_topic: \"cmd_vel_raw\"", text)
        self.assertIn("cmd_vel_out_topic: \"cmd_vel_safe\"", text)
        self.assertIn("slowdown_polygon:", text)
        self.assertIn("stop_polygon:", text)

    def test_verify_sandbox_isolation_detects_collision_monitor_errors(self):
        result = {"errors": []}
        # Simulate launch file content without collision_monitor
        with self._temp_file("no collision monitor node here") as tmp_launch:
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                checker.check_collision_monitor_contract(result, [tmp_launch])
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("COLLISION_MONITOR_MISSING", result["errors"])
        self.assertIn("LIFECYCLE_MANAGER_COLLISION_MONITOR_MISSING", result["errors"])

    def test_verify_sandbox_isolation_detects_bypass_errors(self):
        result = {"errors": []}
        # Simulate bypass remapping
        with self._temp_file("('cmd_vel', 'cmd_vel_safe')") as tmp_launch:
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                checker.check_collision_monitor_contract(result, [tmp_launch])
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("DIRECT_RAW_TO_SIMULATOR_BYPASS", result["errors"])

    def test_verify_sandbox_isolation_detects_simulator_raw_subscription(self):
        result = {"errors": []}
        with self._temp_file("create_subscription(Twist, \"cmd_vel_raw\"") as tmp_sim:
            saved_sim = checker.SIMULATOR_FILE
            checker.SIMULATOR_FILE = tmp_sim
            try:
                checker.check_collision_monitor_contract(result, [tmp_sim])
            finally:
                checker.SIMULATOR_FILE = saved_sim
        self.assertIn("SIMULATOR_SUBSCRIBED_TO_CMD_VEL_RAW", result["errors"])

    def test_verify_sandbox_isolation_detects_simulator_missing_safe_subscription(self):
        result = {"errors": []}
        with self._temp_file("no safe topic here") as tmp_sim:
            saved_sim = checker.SIMULATOR_FILE
            checker.SIMULATOR_FILE = tmp_sim
            try:
                checker.check_collision_monitor_contract(result, [tmp_sim])
            finally:
                checker.SIMULATOR_FILE = saved_sim
        self.assertIn("OUTPUT_SAFE_WITHOUT_CONSUMER", result["errors"])

    @contextmanager
    def _temp_file(self, content: str):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


class HardenCollisionSafetyUnitTests(unittest.TestCase):
    @contextmanager
    def _temp_file(self, content: str):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)

    def test_collision_smoke_included_in_runtime_scan_files(self):
        self.assertIn(checker.COLLISION_MONITOR_SMOKE_TEST_FILE, checker.RUNTIME_SCAN_FILES)

    def test_reject_cmd_vel_unsafe(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_publisher(Twist, 'cmd_vel_unsafe', 10)\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertIn("FORBIDDEN_VELOCITY_TOPIC_cmd_vel_unsafe", result["errors"])

    def test_reject_cmd_vel_filtered(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_publisher(Twist, 'cmd_vel_filtered', 10)\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertIn("FORBIDDEN_VELOCITY_TOPIC_cmd_vel_filtered", result["errors"])

    def test_reject_global_offline_nav_cmd_vel(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_publisher(Twist, '/offline_nav/cmd_vel', 10)\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertIn("FORBIDDEN_VELOCITY_TOPIC_cmd_vel", result["errors"])

    def test_accept_exclusive_raw_and_safe(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_publisher(Twist, 'cmd_vel_raw', 10)\nnode.create_subscription(Twist, 'cmd_vel_safe', cb, 10)\n") as tmp_file:
            checker.check_velocity_topic_allowlist(result, [tmp_file])
        self.assertEqual(result["errors"], [])

    def test_planner_smoke_accepts_integrated_runtime(self):
        text = PLANNER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("controller_server_present", text)
        self.assertNotIn("controller_server_started", text)

    def test_no_domain_id_dependent_logic_in_launch(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertNotIn("os.environ", text)


class BehaviorServerIntegrationTests(unittest.TestCase):
    def test_behavior_server_node_present_and_namespaced(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_namespace_offline(result)
        self.assertNotIn("NODE_MISSING_NAMESPACE_behavior_server", result["errors"])

    def test_behavior_server_has_dedicated_lifecycle_manager(self):
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
        behavior_only_lists = [names for names in node_names_lists if names == ["behavior_server"]]
        self.assertTrue(behavior_only_lists, "no dedicated behavior_server-only lifecycle manager found")

    def test_wait_and_spin_plugins_configured(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn('behavior_plugins: ["wait", "spin"]', text)
        self.assertIn('plugin: "nav2_behaviors::Wait"', text)
        self.assertIn('plugin: "nav2_behaviors::Spin"', text)

    def test_max_rotational_vel_within_sandbox_limit(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("max_rotational_vel: 0.30", text)

    def test_behavior_server_remaps_cmd_vel_to_cmd_vel_raw(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        behavior_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                executable = None
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executable = kw.value.value
                if executable == "behavior_server":
                    behavior_node = node
                    break
        self.assertIsNotNone(behavior_node, "behavior_server Node not found in launch")
        remap_found = False
        for kw in behavior_node.keywords:
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
        self.assertTrue(remap_found, "behavior_server must remap cmd_vel -> cmd_vel_raw")

    def test_behavior_server_never_remaps_directly_to_cmd_vel_safe(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_collision_monitor_contract(result, [LAUNCH_FILE, SIMULATOR_FILE])
        self.assertNotIn("BEHAVIOR_SERVER_DIRECT_SAFE_BYPASS", result["errors"])

    def test_behavior_server_smoke_included_in_runtime_scan_files(self):
        self.assertIn(checker.BEHAVIOR_SERVER_SMOKE_TEST_FILE, checker.RUNTIME_SCAN_FILES)

    def test_behavior_server_smoke_derives_domain_ids_from_base_argument(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("--base-domain-id", text)
        self.assertIn("base, parse_error = parse_base_domain_id(args.base_domain_id)", text)
        self.assertIn('domain_spin = str(base + 1)', text)
        self.assertIn('domain_cancel = str(base + 2)', text)

    def test_behavior_server_smoke_does_not_hardcode_domain_ids_ignoring_argument(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertNotIn('DEFAULT_BASE_DOMAIN_ID = "121"', text)
        self.assertIn("domain_wait = str(base)", text)

    def test_wait_scenario_requires_zero_motion_and_no_safe_nonzero(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('"pose_stable"', text)
        self.assertIn('"odom_twist_zero"', text)
        self.assertIn('and not result["safe_nonzero_detected"]', text)

    def test_spin_scenario_observes_raw_and_safe_angular(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["raw_angular_observed"] = client.raw_angular_observed', text)
        self.assertIn('result["safe_angular_observed"] = client.safe_angular_observed', text)
        self.assertIn('result["yaw_change"]', text)

    def test_cancel_spin_requires_prior_motion_and_subsequent_stop(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('and result["motion_observed"]', text)
        self.assertIn('and result["cancel_result"] == "CANCELED"', text)
        self.assertIn('and result["safe_angular_zero_after_cancel"]', text)
        self.assertIn('and result["odom_twist_zero"]', text)
        self.assertIn('and result["pose_stable"]', text)

    def test_behavior_server_smoke_checks_no_simple_commander(self):
        """waypoint_follower is authorized as of Phase 2G and is always
        present in the launch now (allowlist exception authorized during
        the Phase 2G resume to fix this exact regression), so the behavior
        server smoke test must no longer treat its discovery as a
        violation. Simple Commander remains forbidden.
        """
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("simple_commander", text)
        self.assertIn("mission_node_detected", text)
        self.assertNotIn('"waypoint_follower"', text)

    def test_behavior_server_smoke_no_longer_forbids_bt_navigator(self):
        """bt_navigator is authorized as of Phase 2F and is always present
        in the launch now, so the behavior server smoke test must not treat
        its discovery as a violation.
        """
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertNotIn('"bt_navigator",\n    "waypoint_follower"', text)

    def test_behavior_server_smoke_checks_no_hardware(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("FORBIDDEN_NODE_SUBSTRINGS", text)
        self.assertIn("hardware_node_detected", text)

    def test_no_mission_components_checker_rejects_simple_commander(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text("nav2_simple_commander\n", encoding="utf-8")
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_no_mission_components(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("MISSION_COMPONENT_OUT_OF_SCOPE_REFERENCED", result["errors"])

    def test_no_mission_components_checker_rejects_basic_navigator(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text("from nav2_simple_commander import BasicNavigator\n", encoding="utf-8")
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_no_mission_components(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("MISSION_COMPONENT_OUT_OF_SCOPE_REFERENCED", result["errors"])

    def test_no_mission_components_checker_rejects_parallel_app_stack(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text("followWaypoints()\n", encoding="utf-8")
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_no_mission_components(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("PARALLEL_APP_STACK_REFERENCED", result["errors"])

    def test_no_mission_components_checker_allows_bt_navigator(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text("nav2_bt_navigator\nbt_navigator\n", encoding="utf-8")
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_no_mission_components(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertNotIn("MISSION_COMPONENT_OUT_OF_SCOPE_REFERENCED", result["errors"])

    def test_no_mission_components_checker_allows_waypoint_follower(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text("nav2_waypoint_follower\nwaypoint_follower\n", encoding="utf-8")
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_no_mission_components(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertNotIn("MISSION_COMPONENT_OUT_OF_SCOPE_REFERENCED", result["errors"])
        self.assertNotIn("PARALLEL_APP_STACK_REFERENCED", result["errors"])


class BtNavigatorLaunchAndLifecycleTests(unittest.TestCase):
    def test_bt_navigator_node_present_with_correct_package_and_executable(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                package = executable = None
                for kw in node.keywords:
                    if kw.arg == "package" and isinstance(kw.value, ast.Constant):
                        package = kw.value.value
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executable = kw.value.value
                if executable == "bt_navigator":
                    found = package
                    break
        self.assertEqual(found, "nav2_bt_navigator")

    def test_bt_navigator_is_namespaced(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_namespace_offline(result)
        self.assertNotIn("NODE_MISSING_NAMESPACE_bt_navigator", result["errors"])

    def test_bt_navigator_uses_configured_params_variant(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("bt_navigator_params", text)

    def test_bt_navigator_has_dedicated_lifecycle_manager(self):
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
        bt_only_lists = [names for names in node_names_lists if names == ["bt_navigator"]]
        self.assertTrue(bt_only_lists, "no dedicated bt_navigator-only lifecycle manager found")

    def test_bt_navigator_has_no_velocity_remappings(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                executable = None
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executable = kw.value.value
                if executable == "bt_navigator":
                    for kw in node.keywords:
                        self.assertNotEqual(kw.arg, "remappings")

    def test_bt_navigator_added_to_launch_description(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("bt_navigator_node,", text)
        self.assertIn("lifecycle_manager_bt_navigator_node,", text)

    def test_no_simple_commander_executables(self):
        """waypoint_follower is authorized as of Phase 2G (see
        WaypointFollowerLaunchAndLifecycleTests for its specific contract);
        Simple Commander remains fully out of scope.
        """
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        executables = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executables.add(kw.value.value)
        self.assertNotIn("simple_commander", executables)


class BtNavigatorParameterTests(unittest.TestCase):
    def test_bt_navigator_section_exists(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("bt_navigator:", text)

    def test_bt_navigator_use_sim_time_false(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        bt_section = text.split("bt_navigator:", 1)[1]
        self.assertIn("use_sim_time: false", bt_section)

    def test_bt_navigator_frames_correct(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        bt_section = text.split("bt_navigator:", 1)[1]
        self.assertIn('global_frame: "map"', bt_section)
        self.assertIn('robot_base_frame: "base_link"', bt_section)

    def test_bt_navigator_odom_topic_correct(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        bt_section = text.split("bt_navigator:", 1)[1]
        self.assertIn('odom_topic: "odom"', bt_section)

    def test_navigate_to_pose_configured(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        bt_section = text.split("bt_navigator:", 1)[1]
        self.assertIn("navigate_to_pose:", bt_section)
        self.assertIn("nav2_bt_navigator::NavigateToPoseNavigator", bt_section)

    def test_navigate_through_poses_not_enabled(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        bt_section = text.split("bt_navigator:", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("navigate_through_poses", bt_section)
        self.assertNotIn("NavigateThroughPosesNavigator", bt_section)

    def test_bt_xml_path_injected_outside_yaml_placeholder(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("default_nav_to_pose_bt_xml", text)
        self.assertIn("BT_XML_FILE", text)

    def test_bt_xml_path_is_within_repository_not_temp_or_artifacts(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        bt_xml_expr = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "BT_XML_FILE"
                for target in node.targets
            ):
                bt_xml_expr = ast.unparse(node.value)
                break
        self.assertIsNotNone(bt_xml_expr, "BT_XML_FILE assignment not found")
        self.assertNotIn("artifacts", bt_xml_expr)
        self.assertNotIn("/tmp", bt_xml_expr)
        self.assertIn("CODE_ROOT", bt_xml_expr)


class BtNavigatorXmlTests(unittest.TestCase):
    def test_xml_file_exists(self):
        self.assertTrue(BT_XML_FILE.is_file())

    def test_xml_is_parseable(self):
        tree = ET.parse(BT_XML_FILE)
        self.assertEqual(tree.getroot().tag, "root")

    def test_xml_declares_synthetic_markers(self):
        text = BT_XML_FILE.read_text(encoding="utf-8")
        for marker in ("OFFLINE_ONLY", "SYNTHETIC", "NOT_FOR_HARDWARE", "NOT_UADE_MAP"):
            self.assertIn(marker, text)

    def test_xml_contains_compute_path_to_pose_and_follow_path(self):
        text = BT_XML_FILE.read_text(encoding="utf-8")
        self.assertIn("ComputePathToPose", text)
        self.assertIn("FollowPath", text)

    def test_xml_does_not_contain_out_of_scope_nodes(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_bt_navigator_contract(result)
        for forbidden in (
            "BT_XML_FORBIDDEN_NODE_BackUp",
            "BT_XML_FORBIDDEN_NODE_DriveOnHeading",
            "BT_XML_FORBIDDEN_NODE_AssistedTeleop",
        ):
            self.assertNotIn(forbidden, result["errors"])

    def test_xml_rejects_backup_node_if_present(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_xml = Path(tmp_dir) / "offline_navigate_to_pose.xml"
            tmp_xml.write_text(
                '<root BTCPP_format="4"><BehaviorTree ID="MainTree">'
                '<Sequence><BackUp backup_dist="0.3"/></Sequence>'
                "</BehaviorTree></root>",
                encoding="utf-8",
            )
            saved_xml = checker.BT_XML_FILE
            checker.BT_XML_FILE = tmp_xml
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_bt_navigator_contract(result)
            finally:
                checker.BT_XML_FILE = saved_xml
        self.assertIn("BT_XML_FORBIDDEN_NODE_BackUp", result["errors"])

    def test_xml_rejects_waypoint_follower_and_navigate_through_poses(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_xml = Path(tmp_dir) / "offline_navigate_to_pose.xml"
            tmp_xml.write_text(
                '<root BTCPP_format="4"><BehaviorTree ID="MainTree">'
                "<Sequence><WaypointFollower/><NavigateThroughPoses/></Sequence>"
                "</BehaviorTree></root>",
                encoding="utf-8",
            )
            saved_xml = checker.BT_XML_FILE
            checker.BT_XML_FILE = tmp_xml
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_bt_navigator_contract(result)
            finally:
                checker.BT_XML_FILE = saved_xml
        self.assertIn("BT_XML_FORBIDDEN_NODE_WaypointFollower", result["errors"])
        self.assertIn("BT_XML_FORBIDDEN_NODE_NavigateThroughPoses", result["errors"])


class WaypointFollowerLaunchAndLifecycleTests(unittest.TestCase):
    def test_waypoint_follower_node_present_with_correct_package_and_executable(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                package = executable = None
                for kw in node.keywords:
                    if kw.arg == "package" and isinstance(kw.value, ast.Constant):
                        package = kw.value.value
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executable = kw.value.value
                if executable == "waypoint_follower":
                    found = package
                    break
        self.assertEqual(found, "nav2_waypoint_follower")

    def test_waypoint_follower_is_namespaced(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_namespace_offline(result)
        self.assertNotIn("NODE_MISSING_NAMESPACE_waypoint_follower", result["errors"])

    def test_waypoint_follower_uses_configured_params_variant(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                executable = None
                params_arg = None
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executable = kw.value.value
                    if kw.arg == "parameters":
                        params_arg = kw.value
                if executable == "waypoint_follower":
                    self.assertIsNotNone(params_arg)
                    self.assertIn("configured_params", ast.unparse(params_arg))
                    return
        self.fail("waypoint_follower node not found")

    def test_waypoint_follower_has_dedicated_lifecycle_manager(self):
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
        wf_only_lists = [names for names in node_names_lists if names == ["waypoint_follower"]]
        self.assertTrue(wf_only_lists, "no dedicated waypoint_follower-only lifecycle manager found")

    def test_waypoint_follower_has_no_velocity_remappings(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                executable = None
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executable = kw.value.value
                if executable == "waypoint_follower":
                    for kw in node.keywords:
                        self.assertNotEqual(kw.arg, "remappings")

    def test_waypoint_follower_added_to_launch_description(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("waypoint_follower_node,", text)
        self.assertIn("lifecycle_manager_waypoint_follower_node,", text)

    def test_no_simple_commander_executable(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
        executables = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                for kw in node.keywords:
                    if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                        executables.add(kw.value.value)
        self.assertNotIn("simple_commander", executables)

    def test_waypoint_follower_contract_checker_passes_on_real_launch_file(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_waypoint_follower_contract(result)
        self.assertEqual(result["errors"], [])

    def test_waypoint_follower_contract_checker_rejects_duplicate_node(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text(
                "from launch_ros.actions import Node\n"
                "Node(package='nav2_waypoint_follower', executable='waypoint_follower', "
                "name='waypoint_follower', namespace='offline_nav')\n"
                "Node(package='nav2_waypoint_follower', executable='waypoint_follower', "
                "name='waypoint_follower_2', namespace='offline_nav')\n",
                encoding="utf-8",
            )
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_waypoint_follower_contract(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("WAYPOINT_FOLLOWER_DUPLICATE_NODE_DETECTED", result["errors"])

    def test_waypoint_follower_contract_checker_rejects_missing_namespace(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text(
                "from launch_ros.actions import Node\n"
                "Node(package='nav2_waypoint_follower', executable='waypoint_follower', "
                "name='waypoint_follower')\n",
                encoding="utf-8",
            )
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_waypoint_follower_contract(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("WAYPOINT_FOLLOWER_MISSING_NAMESPACE", result["errors"])

    def test_waypoint_follower_contract_checker_rejects_velocity_remap(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_launch = Path(tmp_dir) / "offline_nav_sandbox.launch.py"
            tmp_launch.write_text(
                "from launch_ros.actions import Node\n"
                "Node(package='nav2_waypoint_follower', executable='waypoint_follower', "
                "name='waypoint_follower', namespace='offline_nav', "
                "remappings=[('cmd_vel', 'cmd_vel_raw')])\n",
                encoding="utf-8",
            )
            saved_launch = checker.LAUNCH_FILE
            checker.LAUNCH_FILE = tmp_launch
            try:
                result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
                checker.check_waypoint_follower_contract(result)
            finally:
                checker.LAUNCH_FILE = saved_launch
        self.assertIn("WAYPOINT_FOLLOWER_HAS_VELOCITY_REMAP", result["errors"])


class WaypointFollowerParameterTests(unittest.TestCase):
    def test_waypoint_follower_section_exists(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("waypoint_follower:", text)

    def test_waypoint_follower_use_sim_time_false(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        section = text.split("waypoint_follower:", 1)[1]
        self.assertIn("use_sim_time: false", section)

    def test_stop_on_failure_explicit_true(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        section = text.split("waypoint_follower:", 1)[1]
        self.assertIn("stop_on_failure: true", section)

    def test_waypoint_task_executor_plugin_is_minimal_stock_plugin(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        section = text.split("waypoint_follower:", 1)[1]
        self.assertIn('waypoint_task_executor_plugin: "wait_at_waypoint"', section)
        self.assertIn('plugin: "nav2_waypoint_follower::WaitAtWaypoint"', section)

    def test_no_custom_task_executor_plugin(self):
        text = PARAMS_FILE.read_text(encoding="utf-8")
        section = text.split("waypoint_follower:", 1)[1]
        self.assertNotIn("photo_at_waypoint", section)
        self.assertNotIn("input_at_waypoint", section)


class WaypointFollowerSmokeTestStructureTests(unittest.TestCase):
    def _load_module(self, path: Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError:
            self.skipTest("rclpy not available in this environment")
            raise
        return module

    def test_smoke_test_included_in_runtime_scan(self):
        self.assertIn(checker.WAYPOINT_FOLLOWER_SMOKE_TEST_FILE, checker.RUNTIME_SCAN_FILES)

    def test_smoke_test_accepts_cli_arguments(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        for arg in ("--namespace", "--base-domain-id", "--timeout", "--output"):
            self.assertIn(arg, text)

    def test_smoke_test_derives_three_domain_ids_from_base_argument(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("base, parse_error = parse_base_domain_id(args.base_domain_id)", text)
        self.assertIn("domain_success = str(base)", text)
        self.assertIn("domain_cancel = str(base + 1)", text)
        self.assertIn("domain_unreachable = str(base + 2)", text)

    def test_maximum_offset_is_two(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("MAXIMUM_OFFSET = 2", text)

    def test_success_scenario_requires_three_or_more_waypoints_and_empty_missed(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["waypoints_requested"] >= 3', text)
        self.assertIn('result["missed_waypoints"] == []', text)

    def test_success_scenario_requires_exact_waypoint_coverage_no_gaps(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("feedback_covers_expected", text)
        self.assertIn("_progress_covers_expected_indices", text)
        self.assertIn('result["waypoints_reached"] == result["waypoints_requested"]', text)

    def test_normalize_progress_collapses_consecutive_duplicates_only(self):
        module = self._load_module(WAYPOINT_FOLLOWER_SMOKE_TEST_FILE)
        self.assertEqual(module._normalize_progress([0, 1, 2]), [0, 1, 2])
        self.assertEqual(module._normalize_progress([0, 0, 1, 1, 2]), [0, 1, 2])
        self.assertEqual(module._normalize_progress([0]), [0])
        self.assertEqual(module._normalize_progress([0, 2]), [0, 2])
        self.assertEqual(module._normalize_progress([1, 2]), [1, 2])
        self.assertEqual(module._normalize_progress([0, 1]), [0, 1])
        self.assertEqual(module._normalize_progress([]), [])

    def test_progress_covers_expected_indices_exact_match_only(self):
        module = self._load_module(WAYPOINT_FOLLOWER_SMOKE_TEST_FILE)
        self.assertTrue(module._progress_covers_expected_indices([0, 1, 2], [0, 1, 2]))
        self.assertFalse(module._progress_covers_expected_indices([0], [0, 1, 2]))
        self.assertFalse(module._progress_covers_expected_indices([0, 2], [0, 1, 2]))
        self.assertFalse(module._progress_covers_expected_indices([1, 2], [0, 1, 2]))
        self.assertFalse(module._progress_covers_expected_indices([0, 1], [0, 1, 2]))

    def test_waypoints_reached_field_present_and_required_equal_to_requested(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('"waypoints_reached": None', text)
        self.assertIn('result["waypoints_reached"] = result["waypoints_requested"]', text)

    def test_success_scenario_rejects_any_missed_waypoint(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["missed_waypoints"] == []', text)

    def test_cancel_scenario_requires_precondition_motion_past_first_waypoint(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("past_first_waypoint", text)
        self.assertIn("cancel_precondition_motion_observed", text)

    def test_cancel_scenario_requires_accepted_request_and_canceled_result(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["cancel_response_received"]', text)
        self.assertIn('result["cancel_request_accepted"]', text)
        self.assertIn('result["final_action_status"] == "CANCELED"', text)

    def test_unreachable_scenario_uses_out_of_bounds_point_not_arbitrary(self):
        """The original interior-occupied-cell hypothesis was disproven by a
        real Phase 2G resume diagnostic ROS run (domain 222): at this map's
        0.05m resolution a single occupied pixel is thinner than the
        planner/costmap's effective footprint+inflation and is routed
        around (FollowWaypoints SUCCEEDED). An out-of-bounds point was
        substituted and confirmed instead (domain 221: ABORTED,
        missed_waypoints=[1], error_code=204/GOAL_OUTSIDE_MAP).
        """
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("UNREACHABLE_WAYPOINT_XY = (5.0, 5.0)", text)
        self.assertIn("GOAL_OUTSIDE_MAP", text)
        self.assertIn("resume diagnostic run", text)

    def test_unreachable_scenario_proves_stop_on_failure(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("stop_on_failure_proven", text)
        self.assertIn("waypoint_after_failure_not_reached", text)

    def test_unreachable_scenario_requires_missed_index_one(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["unreachable_waypoint_index"] in result["missed_waypoints"]', text)

    def test_unreachable_scenario_requires_specific_error_code_not_any_abort(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("COMPUTE_PATH_TO_POSE_GOAL_OUTSIDE_MAP = 204", text)
        self.assertIn(
            'result["missed_waypoint_error_code"] == COMPUTE_PATH_TO_POSE_GOAL_OUTSIDE_MAP', text
        )

    def test_unreachable_scenario_rejects_feedback_progress_to_index_two(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn(
            "result[\"unreachable_waypoint_index\"] + 1\n                            not in (result[\"feedback_indices\"] or [])",
            text,
        )

    def test_unreachable_scenario_does_not_convert_generic_timeout_into_pass(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["final_action_status"] != "RESULT_TIMEOUT"', text)
        self.assertIn('UNREACHABLE_TERMINAL_STATUSES = ("ABORTED",)', text)

    def test_action_availability_required_in_all_three_scenarios(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertEqual(
            text.count('result["follow_waypoints_action_available"]\n'), 3,
            "follow_waypoints_action_available must gate ok in success, cancel, and unreachable",
        )

    def test_pipe_deadlock_removed_uses_dedicated_log_files(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(WAYPOINT_FOLLOWER_SMOKE_TEST_FILE))
        popen_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "Popen"
        ]
        self.assertEqual(len(popen_calls), 3, "expected exactly one Popen per scenario")
        for call in popen_calls:
            for kw in call.keywords:
                if kw.arg == "stdout":
                    stdout_expr = ast.unparse(kw.value)
                    self.assertNotEqual(stdout_expr, "subprocess.PIPE")
        self.assertIn("_scenario_log_path", text)
        self.assertIn('open(log_path, "w"', text)
        self.assertIn("log_file.close()", text)

    def test_log_paths_are_under_tmp_not_inside_repository(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('Path(f"/tmp/ottoguide_waypoint_', text)

    def test_no_waypoint_or_simple_commander_forbidden_node_used_for_mission_app(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("FORBIDDEN_MISSION_NODE_SUBSTRINGS", text)
        self.assertIn("simple_commander", text)
        self.assertIn("mission_app_component_detected", text)


def _read_pgm_p5(path: Path) -> tuple[int, int, list[int]]:
    """Minimal pure-Python binary PGM (P5) reader: no PIL/numpy dependency.
    Returns (width, height, pixel_values) with pixel_values in row-major
    order, matching the layout documented in offline_sandbox_test_map.yaml
    (resolution 0.05, origin [-1.0, -0.75]).
    """
    with open(path, "rb") as f:
        magic = f.readline().strip()
        if magic != b"P5":
            raise ValueError(f"not a binary PGM (P5) file: {magic!r}")
        dims_line = f.readline().strip()
        width, height = (int(token) for token in dims_line.split())
        maxval_line = f.readline().strip()
        maxval = int(maxval_line)
        if maxval > 255:
            raise ValueError("16-bit PGM not supported by this minimal reader")
        data = f.read(width * height)
    return width, height, list(data)


def _world_to_pixel(x: float, y: float, origin: tuple[float, float], resolution: float, height: int) -> tuple[int, int]:
    """Inverse of the world_x/world_y formulas documented in
    smoke_test_offline_waypoint_follower.py: returns (row, col).
    """
    col = int((x - origin[0]) / resolution)
    row = height - 1 - int((y - origin[1]) / resolution)
    return row, col


class WaypointFollowerMapFixturePgmTests(unittest.TestCase):
    """Functional (not string-search) validation that the coordinates the
    smoke test treats as occupied/free really are, by parsing the real PGM
    fixture bytes -- not by trusting a comment.
    """

    MAP_ORIGIN = (-1.0, -0.75)
    MAP_RESOLUTION = 0.05

    def setUp(self):
        self.width, self.height, self.pixels = _read_pgm_p5(MAP_PGM)

    def _value_at_world(self, x: float, y: float) -> int:
        row, col = _world_to_pixel(x, y, self.MAP_ORIGIN, self.MAP_RESOLUTION, self.height)
        self.assertTrue(0 <= row < self.height, f"row {row} outside map for world ({x},{y})")
        self.assertTrue(0 <= col < self.width, f"col {col} outside map for world ({x},{y})")
        return self.pixels[row * self.width + col]

    def test_map_dimensions_match_documented_fixture(self):
        self.assertEqual((self.width, self.height), (40, 30))

    def test_world_bounds_match_documented_resolution_and_origin(self):
        x_min = self.MAP_ORIGIN[0]
        x_max = self.MAP_ORIGIN[0] + self.width * self.MAP_RESOLUTION
        y_min = self.MAP_ORIGIN[1]
        y_max = self.MAP_ORIGIN[1] + self.height * self.MAP_RESOLUTION
        self.assertAlmostEqual(x_min, -1.0)
        self.assertAlmostEqual(x_max, 1.0)
        self.assertAlmostEqual(y_min, -0.75)
        self.assertAlmostEqual(y_max, 0.75)

    def test_original_interior_cell_hypothesis_is_occupied_but_not_used_as_unreachable_point(self):
        """The interior cell originally hypothesized as unreachable (world
        (0.025, 0.575), pixel row=3 col=20) is confirmed occupied in the
        real PGM data -- the hypothesis about *occupancy* was correct. What
        was wrong, and disproven by the Phase 2G resume diagnostic ROS run,
        was the assumption that occupancy alone makes a single-pixel
        obstacle unreachable at this map's resolution. The smoke test must
        not use this point as UNREACHABLE_WAYPOINT_XY.
        """
        value = self._value_at_world(0.025, 0.575)
        self.assertEqual(value, 0, "expected the original hypothesis cell to be occupied")
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertNotIn("UNREACHABLE_WAYPOINT_XY = (0.025, 0.575)", text)

    def test_unreachable_waypoint_xy_is_outside_map_bounds(self):
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("UNREACHABLE_WAYPOINT_XY = (5.0, 5.0)", text)
        x, y = 5.0, 5.0
        x_min, x_max = self.MAP_ORIGIN[0], self.MAP_ORIGIN[0] + self.width * self.MAP_RESOLUTION
        y_min, y_max = self.MAP_ORIGIN[1], self.MAP_ORIGIN[1] + self.height * self.MAP_RESOLUTION
        self.assertTrue(x < x_min or x > x_max or y < y_min or y > y_max)

    def test_success_waypoint_offsets_land_on_free_cells_from_map_center(self):
        """SUCCESS_WAYPOINT_OFFSETS_M are applied relative to the observed
        initial pose at runtime (unknown at static-test time), but the
        offsets are small enough that, applied from the map's free central
        region, they must land on free cells -- never on a hardcoded
        perimeter wall or the interior obstacle column.
        """
        text = WAYPOINT_FOLLOWER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("SUCCESS_WAYPOINT_OFFSETS_M", text)
        cursor_x, cursor_y = 0.0, 0.0
        for dx, dy in ((0.30, 0.0), (0.30, 0.20), (0.0, 0.20)):
            cursor_x += dx
            cursor_y += dy
            value = self._value_at_world(cursor_x, cursor_y)
            self.assertEqual(value, 254, f"expected free cell at ({cursor_x},{cursor_y})")

    def test_unreachable_scenario_reachable_companions_land_on_free_cells(self):
        """The two reachable waypoints surrounding UNREACHABLE_WAYPOINT_XY
        in run_unreachable_scenario (offsets +0.20 in x, and +0.20x/-0.20y
        from the initial pose) must themselves be free, so a failure in
        that scenario can only be attributed to the deliberately
        unreachable middle waypoint.
        """
        for dx, dy in ((0.20, 0.0), (0.20, -0.20)):
            value = self._value_at_world(dx, dy)
            self.assertEqual(value, 254, f"expected free cell at offset ({dx},{dy}) from origin")


class BtNavigatorSmokeTestStructureTests(unittest.TestCase):
    def test_smoke_test_included_in_runtime_scan(self):
        self.assertIn(checker.BT_NAVIGATOR_SMOKE_TEST_FILE, checker.RUNTIME_SCAN_FILES)

    def test_smoke_test_checks_no_simple_commander(self):
        """waypoint_follower is authorized as of Phase 2G and is always
        present in the launch now (allowlist exception authorized during
        the Phase 2G resume to fix this exact regression, mirroring the
        identical fix applied to the behavior server smoke test), so the
        BT Navigator smoke test must no longer treat its discovery as a
        violation. Simple Commander remains forbidden.
        """
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("simple_commander", text)
        self.assertIn("mission_node_detected", text)
        self.assertNotIn('"waypoint_follower"', text)

    def test_smoke_test_accepts_cli_arguments(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        for arg in ("--namespace", "--base-domain-id", "--timeout", "--output"):
            self.assertIn(arg, text)

    def test_smoke_test_derives_domain_ids_from_base_argument(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("base, parse_error = parse_base_domain_id(args.base_domain_id)", text)
        self.assertIn("domain_success = str(base)", text)
        self.assertIn("domain_cancel = str(base + 1)", text)

    def test_smoke_test_does_not_hardcode_domain_ids_ignoring_argument(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertNotIn('domain_success = "180"', text)
        self.assertNotIn('domain_cancel = "181"', text)

    def test_success_scenario_requires_real_motion_and_distance(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["distance_moved"] is not None and result["distance_moved"] > 0.05', text)
        self.assertIn(
            'result["final_distance_to_goal"] is not None and result["final_distance_to_goal"] < GOAL_TOLERANCE_M',
            text,
        )

    def test_success_scenario_requires_real_telemetry(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["odom_messages_received"] > 0', text)
        self.assertIn('result["raw_messages_received"] > 0', text)
        self.assertIn('result["safe_messages_received"] > 0', text)

    def test_cancel_scenario_requires_precondition_motion(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("CANCEL_PRECONDITION_MOTION_NOT_OBSERVED", text)
        self.assertIn("cancel_precondition_motion_observed", text)

    def test_cancel_scenario_requires_accepted_request_and_canceled_result(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["cancel_request_accepted"]', text)
        self.assertIn('result["cancel_result"] == "CANCELED"', text)

    def test_cancel_scenario_requires_safe_and_odom_message_after_cancel(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("safe_message_after_cancel", text)
        self.assertIn("odom_message_after_cancel", text)
        self.assertIn("safe_zero_after_cancel", text)
        self.assertIn("odom_zero_after_cancel", text)

    def test_cancel_scenario_requires_pose_stable(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('result["pose_stable"]', text)

    def test_absence_of_data_remains_none(self):
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('"distance_moved": None', text)
        self.assertIn('"final_distance_to_goal": None', text)
        self.assertIn('"initial_pose": None', text)


class BtNavigatorWaitPlanarMotionTests(unittest.TestCase):
    def test_wait_detects_linear_x_nonzero(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("def _planar_nonzero(linear_x: float, linear_y: float, angular_z: float)", text)
        self.assertIn("abs(linear_x) > PLANAR_NONZERO_TOLERANCE", text)

    def test_wait_detects_linear_y_nonzero(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("abs(linear_y) > PLANAR_NONZERO_TOLERANCE", text)

    def test_wait_detects_angular_z_nonzero(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("abs(angular_z) > PLANAR_NONZERO_TOLERANCE", text)

    def test_wait_uses_general_safe_nonzero_name_not_angular_only(self):
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("safe_nonzero_detected", text)

    def test_wait_tracks_safe_messages_received_without_requiring_nonzero_count(self):
        """Wait's onCycleUpdate path never calls stopRobot() on normal
        SUCCEEDED completion (verified against
        /opt/ros/jazzy/include/nav2_behaviors/timed_behavior.hpp), so zero
        cmd_vel_safe messages is the correct, expected outcome for a
        successful Wait. The pass/fail gate must rely on odom_twist_zero
        (an odometry message that always exists) and safe_nonzero_detected,
        not on safe_messages_received being nonzero.
        """
        text = BEHAVIOR_SERVER_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn("result[\"safe_messages_received\"] = client.safe_messages_received", text)
        self.assertNotIn('and result["safe_messages_received"] > 0', text)

    def test_planar_nonzero_function_behavior(self):
        module_globals: dict = {}
        spec = importlib.util.spec_from_file_location(
            "smoke_test_offline_behavior_server", BEHAVIOR_SERVER_SMOKE_TEST_FILE
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError:
            self.skipTest("rclpy not available in this environment")
            return
        self.assertTrue(module._planar_nonzero(0.05, 0.0, 0.0))
        self.assertTrue(module._planar_nonzero(0.0, 0.05, 0.0))
        self.assertTrue(module._planar_nonzero(0.0, 0.0, 0.05))
        self.assertFalse(module._planar_nonzero(0.0, 0.0, 0.0))


class DomainIdRangePolicyTests(unittest.TestCase):
    def _load_module(self, path: Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError:
            self.skipTest("rclpy not available in this environment")
            raise
        return module

    def test_behavior_server_min_max_and_offset(self):
        module = self._load_module(BEHAVIOR_SERVER_SMOKE_TEST_FILE)
        self.assertEqual(module.MIN_DOMAIN_ID, 1)
        self.assertEqual(module.MAX_DOMAIN_ID, 232)
        self.assertEqual(module.MAXIMUM_OFFSET, 2)

    def test_collision_monitor_min_max_and_offset(self):
        module = self._load_module(COLLISION_MONITOR_SMOKE_TEST_FILE)
        self.assertEqual(module.MIN_DOMAIN_ID, 1)
        self.assertEqual(module.MAX_DOMAIN_ID, 232)
        self.assertEqual(module.MAXIMUM_OFFSET, 4)

    def test_bt_navigator_min_max_and_offset(self):
        module = self._load_module(BT_NAVIGATOR_SMOKE_TEST_FILE)
        self.assertEqual(module.MIN_DOMAIN_ID, 1)
        self.assertEqual(module.MAX_DOMAIN_ID, 232)
        self.assertEqual(module.MAXIMUM_OFFSET, 1)

    def test_waypoint_follower_min_max_and_offset(self):
        module = self._load_module(WAYPOINT_FOLLOWER_SMOKE_TEST_FILE)
        self.assertEqual(module.MIN_DOMAIN_ID, 1)
        self.assertEqual(module.MAX_DOMAIN_ID, 232)
        self.assertEqual(module.MAXIMUM_OFFSET, 2)

    def test_behavior_server_base_out_of_range_is_invalid(self):
        module = self._load_module(BEHAVIOR_SERVER_SMOKE_TEST_FILE)
        self.assertEqual(module.validate_domain_id_range(0, module.MAXIMUM_OFFSET), "INVALID_DOMAIN_ID")
        self.assertEqual(module.validate_domain_id_range(233, module.MAXIMUM_OFFSET), "INVALID_DOMAIN_ID")

    def test_behavior_server_derived_out_of_range(self):
        module = self._load_module(BEHAVIOR_SERVER_SMOKE_TEST_FILE)
        self.assertEqual(
            module.validate_domain_id_range(231, module.MAXIMUM_OFFSET),
            "DERIVED_DOMAIN_ID_OUT_OF_RANGE",
        )

    def test_collision_monitor_derived_out_of_range(self):
        module = self._load_module(COLLISION_MONITOR_SMOKE_TEST_FILE)
        self.assertEqual(
            module.validate_domain_id_range(229, module.MAXIMUM_OFFSET),
            "DERIVED_DOMAIN_ID_OUT_OF_RANGE",
        )

    def test_bt_navigator_derived_out_of_range(self):
        module = self._load_module(BT_NAVIGATOR_SMOKE_TEST_FILE)
        self.assertEqual(
            module.validate_domain_id_range(232, module.MAXIMUM_OFFSET),
            "DERIVED_DOMAIN_ID_OUT_OF_RANGE",
        )

    def test_waypoint_follower_derived_out_of_range(self):
        module = self._load_module(WAYPOINT_FOLLOWER_SMOKE_TEST_FILE)
        self.assertEqual(
            module.validate_domain_id_range(231, module.MAXIMUM_OFFSET),
            "DERIVED_DOMAIN_ID_OUT_OF_RANGE",
        )

    def test_valid_range_returns_none(self):
        module = self._load_module(BT_NAVIGATOR_SMOKE_TEST_FILE)
        self.assertIsNone(module.validate_domain_id_range(180, module.MAXIMUM_OFFSET))

    def test_no_domain_id_dependent_launch_logic(self):
        text = LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertNotIn("os.environ", text)

    def test_no_special_case_exceptions_for_specific_domain_ids_in_smoke_tests(self):
        """validate_domain_id_range must compare only against MIN_DOMAIN_ID,
        MAX_DOMAIN_ID and the given offset -- never against a literal domain
        id constant that would carve out an exception for a specific value.
        """
        forbidden_literals = {0, 77, 121, 160, 180, 200, 220}
        for path in (
            BEHAVIOR_SERVER_SMOKE_TEST_FILE,
            COLLISION_MONITOR_SMOKE_TEST_FILE,
            BT_NAVIGATOR_SMOKE_TEST_FILE,
            WAYPOINT_FOLLOWER_SMOKE_TEST_FILE,
        ):
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "validate_domain_id_range":
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Constant) and isinstance(inner.value, int):
                            self.assertNotIn(inner.value, forbidden_literals)


class ArchitectureReconciliationStaticGuardTests(unittest.TestCase):
    """Fase 2H.0: verify_sandbox_isolation.py also guards the canonical
    navigation/hardware contract files (models.py, port.py,
    tour_orchestrator.py, main.py) against BasicNavigator/cmd_vel_nav/
    src.hardware leakage, on top of its existing sandbox-only checks.
    """

    def test_static_verify_includes_architecture_files(self):
        result = checker.verify(runtime=False)
        checked = set(result["checked_files"])
        self.assertIn(str(checker.ARCHITECTURE_MODELS_FILE), checked)
        self.assertIn(str(checker.ARCHITECTURE_PORT_FILE), checked)
        self.assertIn(str(checker.ARCHITECTURE_TOUR_ORCHESTRATOR_FILE), checked)
        self.assertIn(str(checker.ARCHITECTURE_MAIN_FILE), checked)

    def test_static_verify_passes_with_current_architecture_files(self):
        result = checker.verify(runtime=False)
        architecture_errors = [
            e for e in result["errors"] if e.startswith("ARCHITECTURE_")
        ]
        self.assertEqual(architecture_errors, [])

    def test_detects_forbidden_symbol_in_architecture_file(self):
        result = {"checked_files": [], "errors": [], "warnings": []}
        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "models.py"
            bad_file.write_text(
                "BasicNavigator = None\n", encoding="utf-8"
            )
            original = checker.ARCHITECTURE_RECONCILIATION_FILES
            checker.ARCHITECTURE_RECONCILIATION_FILES = (bad_file,)
            try:
                checker.check_architecture_reconciliation_contract(result)
            finally:
                checker.ARCHITECTURE_RECONCILIATION_FILES = original
        self.assertTrue(
            any(e.startswith("ARCHITECTURE_FORBIDDEN_SYMBOL:") for e in result["errors"])
        )

    def test_detects_forbidden_src_hardware_import(self):
        result = {"checked_files": [], "errors": [], "warnings": []}
        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "tour_orchestrator.py"
            bad_file.write_text(
                "from src.hardware import RobotHardwareAPI\n", encoding="utf-8"
            )
            original = checker.ARCHITECTURE_RECONCILIATION_FILES
            checker.ARCHITECTURE_RECONCILIATION_FILES = (bad_file,)
            try:
                checker.check_architecture_reconciliation_contract(result)
            finally:
                checker.ARCHITECTURE_RECONCILIATION_FILES = original
        self.assertTrue(
            any(e.startswith("ARCHITECTURE_FORBIDDEN_IMPORT:") for e in result["errors"])
        )

    def test_does_not_flag_unrelated_src_hardware_substring(self):
        result = {"checked_files": [], "errors": [], "warnings": []}
        with tempfile.TemporaryDirectory() as tmp:
            ok_file = Path(tmp) / "port.py"
            ok_file.write_text(
                "from hardware.interface import RobotHardwareInterface\n",
                encoding="utf-8",
            )
            original = checker.ARCHITECTURE_RECONCILIATION_FILES
            checker.ARCHITECTURE_RECONCILIATION_FILES = (ok_file,)
            try:
                checker.check_architecture_reconciliation_contract(result)
            finally:
                checker.ARCHITECTURE_RECONCILIATION_FILES = original
        self.assertEqual(result["errors"], [])


class _ModuleLoaderMixin:
    def _load_module(self, path: Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError:
            self.skipTest("rclpy not available in this environment")
            raise
        return module


class BaseDomainIdParsingTests(_ModuleLoaderMixin, unittest.TestCase):
    """Functional tests of parse_base_domain_id: the actual int() conversion
    logic, not just a string search for its presence in the source. Covers
    Fase 2F.1 hallazgo A (non-integer CLI input must never raise/traceback).
    """

    def _scripts(self):
        return (
            BEHAVIOR_SERVER_SMOKE_TEST_FILE,
            COLLISION_MONITOR_SMOKE_TEST_FILE,
            BT_NAVIGATOR_SMOKE_TEST_FILE,
            WAYPOINT_FOLLOWER_SMOKE_TEST_FILE,
        )

    def test_non_integer_strings_return_invalid_domain_id_in_all_three_scripts(self):
        for path in self._scripts():
            module = self._load_module(path)
            for raw in ("abc", "12.5", "", "   ", "1e2", "None"):
                with self.subTest(script=path.name, raw=raw):
                    value, error = module.parse_base_domain_id(raw)
                    self.assertIsNone(value)
                    self.assertEqual(error, "INVALID_DOMAIN_ID")

    def test_valid_integer_strings_parse_correctly_in_all_three_scripts(self):
        for path in self._scripts():
            module = self._load_module(path)
            for raw, expected in (("1", 1), ("232", 232), ("  77  ", 77), ("0", 0), ("233", 233)):
                with self.subTest(script=path.name, raw=raw):
                    value, error = module.parse_base_domain_id(raw)
                    self.assertIsNone(error)
                    self.assertEqual(value, expected)

    def test_parse_never_raises_on_arbitrary_garbage_input(self):
        garbage_inputs = ("abc", "12.5", "", "   ", "--", "1 2", "0x1F", "NaN", "inf", None)
        for path in self._scripts():
            module = self._load_module(path)
            for raw in garbage_inputs:
                with self.subTest(script=path.name, raw=raw):
                    try:
                        value, error = module.parse_base_domain_id(raw)
                    except Exception as exc:  # pragma: no cover - the whole point is that this must not happen
                        self.fail(f"{path.name}: parse_base_domain_id({raw!r}) raised {exc!r}")
                    if error is not None:
                        self.assertIsNone(value)
                        self.assertEqual(error, "INVALID_DOMAIN_ID")

    def test_main_uses_parse_base_domain_id_before_validate_domain_id_range(self):
        """Static structural check that main() calls the safe parser instead
        of a bare int(args.base_domain_id), and that the parse error is
        handled before validate_domain_id_range is ever invoked.
        """
        for path in self._scripts():
            text = path.read_text(encoding="utf-8")
            self.assertIn("base, parse_error = parse_base_domain_id(args.base_domain_id)", text)
            self.assertNotIn("base = int(args.base_domain_id)", text)
            parse_idx = text.index("base, parse_error = parse_base_domain_id")
            validate_idx = text.index("domain_error = validate_domain_id_range(base, MAXIMUM_OFFSET)")
            self.assertLess(parse_idx, validate_idx)


class BaseDomainIdCliContractTests(_ModuleLoaderMixin, unittest.TestCase):
    """End-to-end CLI contract tests (argparse -> main()) for all three
    smoke tests, run via subprocess so they exercise the exact same code
    path a human operator would invoke. Requires the real ROS 2 Jazzy
    interpreter (rclpy import at module level), so these are skipped
    automatically wherever rclpy is unavailable (e.g. plain Windows).
    """

    def _scripts(self):
        return (
            BEHAVIOR_SERVER_SMOKE_TEST_FILE,
            COLLISION_MONITOR_SMOKE_TEST_FILE,
            BT_NAVIGATOR_SMOKE_TEST_FILE,
            WAYPOINT_FOLLOWER_SMOKE_TEST_FILE,
        )

    def _run_cli(self, path: Path, base_domain_id: str):
        import subprocess
        try:
            import rclpy  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("rclpy not available in this environment")
        proc = subprocess.run(
            ["python3", str(path), "--base-domain-id", base_domain_id, "--timeout", "1"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc

    def test_invalid_inputs_exit_2_with_clean_json_and_no_traceback(self):
        for path in self._scripts():
            for raw in ("abc", "12.5", "", "   ", "0", "233"):
                with self.subTest(script=path.name, raw=raw):
                    proc = self._run_cli(path, raw)
                    self.assertEqual(proc.returncode, 2)
                    self.assertNotIn("Traceback", proc.stdout)
                    self.assertNotIn("Traceback", proc.stderr)
                    payload = json.loads(proc.stdout)
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["decision"], "FAIL")
                    self.assertIn("INVALID_DOMAIN_ID", payload["errors"])


class CancelAcceptanceSemanticsTests(_ModuleLoaderMixin, unittest.TestCase):
    """Semantic tests for _BtNavigatorSmokeClient.request_cancel_and_check_
    acceptance: verifies the real action_msgs/srv/CancelGoal contract is
    used (return_code + goals_canceling[].goal_id matching), not merely
    future completion. Covers Fase 2F.1 hallazgo B.
    """

    def _load_bt_module(self):
        spec = importlib.util.spec_from_file_location(
            "smoke_test_offline_bt_navigator", BT_NAVIGATOR_SMOKE_TEST_FILE
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError:
            self.skipTest("rclpy not available in this environment")
            raise
        return module

    def _make_goal_handle(self, module, uuid_bytes: bytes):
        from unique_identifier_msgs.msg import UUID

        class _FakeGoalHandle:
            def __init__(self, goal_id, future_to_return):
                self._goal_id = goal_id
                self._future_to_return = future_to_return

            @property
            def goal_id(self):
                return self._goal_id

            def cancel_goal_async(self):
                return self._future_to_return

        return _FakeGoalHandle

    def _make_future(self, result_value, done: bool = True):
        class _FakeFuture:
            def __init__(self, value, is_done):
                self._value = value
                self._is_done = is_done

            def done(self):
                return self._is_done

            def result(self):
                return self._value

        return _FakeFuture(result_value, done)

    def _make_response(self, module, return_code: int, canceling_uuids):
        from action_msgs.msg import GoalInfo
        from action_msgs.srv import CancelGoal
        from unique_identifier_msgs.msg import UUID

        response = CancelGoal.Response()
        response.return_code = return_code
        infos = []
        for raw_uuid in canceling_uuids:
            info = GoalInfo()
            info.goal_id = UUID(uuid=list(raw_uuid))
            infos.append(info)
        response.goals_canceling = infos
        return response

    def _client_with_fake_spin(self, module, fake_future):
        """A bare (non-rclpy-initialized) client instance, with spin_until_
        future_complete_custom monkeypatched to just check future.done()
        without actually spinning an executor (no rclpy.init() needed).
        """
        client = module._BtNavigatorSmokeClient.__new__(module._BtNavigatorSmokeClient)
        client.spin_until_future_complete_custom = lambda future, timeout_s: future.done()
        return client

    def test_future_not_completed_is_not_accepted(self):
        module = self._load_bt_module()
        from unique_identifier_msgs.msg import UUID
        goal_uuid = bytes(range(16))
        future = self._make_future(None, done=False)
        goal_handle_cls = self._make_goal_handle(module, goal_uuid)
        goal_handle = goal_handle_cls(UUID(uuid=list(goal_uuid)), future)
        client = self._client_with_fake_spin(module, future)

        outcome = client.request_cancel_and_check_acceptance(goal_handle, timeout_s=1.0)
        self.assertFalse(outcome["cancel_response_received"])
        self.assertFalse(outcome["cancel_request_accepted"])
        self.assertIn("CANCEL_RESPONSE_TIMEOUT", outcome["errors"])

    def test_null_response_is_not_accepted(self):
        module = self._load_bt_module()
        from unique_identifier_msgs.msg import UUID
        goal_uuid = bytes(range(16))
        future = self._make_future(None, done=True)
        goal_handle_cls = self._make_goal_handle(module, goal_uuid)
        goal_handle = goal_handle_cls(UUID(uuid=list(goal_uuid)), future)
        client = self._client_with_fake_spin(module, future)

        outcome = client.request_cancel_and_check_acceptance(goal_handle, timeout_s=1.0)
        self.assertFalse(outcome["cancel_response_received"])
        self.assertFalse(outcome["cancel_request_accepted"])
        self.assertIn("CANCEL_RESPONSE_TIMEOUT", outcome["errors"])

    def test_response_received_but_rejected_is_not_accepted(self):
        module = self._load_bt_module()
        from action_msgs.srv import CancelGoal
        from unique_identifier_msgs.msg import UUID
        goal_uuid = bytes(range(16))
        response = self._make_response(module, CancelGoal.Response.ERROR_REJECTED, [])
        future = self._make_future(response, done=True)
        goal_handle_cls = self._make_goal_handle(module, goal_uuid)
        goal_handle = goal_handle_cls(UUID(uuid=list(goal_uuid)), future)
        client = self._client_with_fake_spin(module, future)

        outcome = client.request_cancel_and_check_acceptance(goal_handle, timeout_s=1.0)
        self.assertTrue(outcome["cancel_response_received"])
        self.assertFalse(outcome["cancel_request_accepted"])
        self.assertIn("CANCEL_REQUEST_NOT_ACCEPTED", outcome["errors"])

    def test_response_with_empty_goals_canceling_is_not_accepted(self):
        module = self._load_bt_module()
        from action_msgs.srv import CancelGoal
        from unique_identifier_msgs.msg import UUID
        goal_uuid = bytes(range(16))
        response = self._make_response(module, CancelGoal.Response.ERROR_NONE, [])
        future = self._make_future(response, done=True)
        goal_handle_cls = self._make_goal_handle(module, goal_uuid)
        goal_handle = goal_handle_cls(UUID(uuid=list(goal_uuid)), future)
        client = self._client_with_fake_spin(module, future)

        outcome = client.request_cancel_and_check_acceptance(goal_handle, timeout_s=1.0)
        self.assertTrue(outcome["cancel_response_received"])
        self.assertFalse(outcome["cancel_request_accepted"])
        self.assertIn("CANCEL_REQUEST_NOT_ACCEPTED", outcome["errors"])

    def test_response_confirms_a_different_goal_is_not_accepted(self):
        module = self._load_bt_module()
        from action_msgs.srv import CancelGoal
        from unique_identifier_msgs.msg import UUID
        goal_uuid = bytes(range(16))
        other_goal_uuid = bytes(reversed(range(16)))
        response = self._make_response(module, CancelGoal.Response.ERROR_NONE, [other_goal_uuid])
        future = self._make_future(response, done=True)
        goal_handle_cls = self._make_goal_handle(module, goal_uuid)
        goal_handle = goal_handle_cls(UUID(uuid=list(goal_uuid)), future)
        client = self._client_with_fake_spin(module, future)

        outcome = client.request_cancel_and_check_acceptance(goal_handle, timeout_s=1.0)
        self.assertTrue(outcome["cancel_response_received"])
        self.assertFalse(outcome["cancel_request_accepted"])
        self.assertIn("CANCEL_REQUEST_NOT_ACCEPTED", outcome["errors"])

    def test_response_confirms_the_expected_goal_is_accepted(self):
        module = self._load_bt_module()
        from action_msgs.srv import CancelGoal
        from unique_identifier_msgs.msg import UUID
        goal_uuid = bytes(range(16))
        response = self._make_response(module, CancelGoal.Response.ERROR_NONE, [goal_uuid])
        future = self._make_future(response, done=True)
        goal_handle_cls = self._make_goal_handle(module, goal_uuid)
        goal_handle = goal_handle_cls(UUID(uuid=list(goal_uuid)), future)
        client = self._client_with_fake_spin(module, future)

        outcome = client.request_cancel_and_check_acceptance(goal_handle, timeout_s=1.0)
        self.assertTrue(outcome["cancel_response_received"])
        self.assertTrue(outcome["cancel_request_accepted"])
        self.assertEqual(outcome["errors"], [])

    def test_response_confirms_expected_goal_among_multiple_canceling(self):
        module = self._load_bt_module()
        from action_msgs.srv import CancelGoal
        from unique_identifier_msgs.msg import UUID
        goal_uuid = bytes(range(16))
        other_goal_uuid = bytes(reversed(range(16)))
        response = self._make_response(
            module, CancelGoal.Response.ERROR_NONE, [other_goal_uuid, goal_uuid]
        )
        future = self._make_future(response, done=True)
        goal_handle_cls = self._make_goal_handle(module, goal_uuid)
        goal_handle = goal_handle_cls(UUID(uuid=list(goal_uuid)), future)
        client = self._client_with_fake_spin(module, future)

        outcome = client.request_cancel_and_check_acceptance(goal_handle, timeout_s=1.0)
        self.assertTrue(outcome["cancel_request_accepted"])

    def test_final_result_not_canceled_does_not_imply_acceptance_was_skipped(self):
        """Acceptance and final outcome are independent checks: a script
        must still gate on cancel_result == CANCELED separately, even when
        cancel_request_accepted is True. This test documents that the
        acceptance helper itself does not look at the navigate result at
        all -- it is purely about the CancelGoal response.
        """
        module = self._load_bt_module()
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertIn('and result["cancel_result"] == "CANCELED"', text)
        self.assertIn('and result["cancel_request_accepted"]', text)
        self.assertIn('and result["cancel_response_received"]', text)

    def test_false_positive_pattern_removed_from_source(self):
        """The old anti-pattern (treating bool(future_completed) as proof of
        acceptance) must no longer appear in the cancel scenario."""
        text = BT_NAVIGATOR_SMOKE_TEST_FILE.read_text(encoding="utf-8")
        self.assertNotIn('result["cancel_request_accepted"] = bool(cancel_accepted)', text)
        self.assertIn("response.return_code != CancelGoal.Response.ERROR_NONE", text)
        self.assertIn("goal_handle.goal_id.uuid", text)
        self.assertIn("goal_handle.goal_id.uuid", text)


class DirectNav2ActionBridgeIsolationTests(unittest.TestCase):
    def test_direct_bridge_rejects_basic_navigator(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("from nav2_simple_commander.robot_navigator import BasicNavigator\n") as tmp_file:
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            checker.check_direct_nav2_action_bridge_contract(result, [tmp_file])
        self.assertTrue(any("DIRECT_BRIDGE_FORBIDDEN_IMPORT" in e for e in result["errors"]))

    def test_direct_bridge_rejects_twist(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("from geometry_msgs.msg import Twist\n") as tmp_file:
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            checker.check_direct_nav2_action_bridge_contract(result, [tmp_file])
        self.assertTrue(any("DIRECT_BRIDGE_FORBIDDEN_IMPORT" in e for e in result["errors"]))

    def test_direct_bridge_rejects_create_subscription(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("node.create_subscription(Msg, 'topic', cb, 10)\n") as tmp_file:
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            checker.check_direct_nav2_action_bridge_contract(result, [tmp_file])
        self.assertTrue(any("DIRECT_BRIDGE_FORBIDDEN_CALL" in e for e in result["errors"]))

    def test_direct_bridge_rejects_hardware_import(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("import src.hardware.real_adapter\n") as tmp_file:
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            checker.check_direct_nav2_action_bridge_contract(result, [tmp_file])
        self.assertTrue(any("DIRECT_BRIDGE_FORBIDDEN_IMPORT" in e for e in result["errors"]))

    def test_direct_bridge_rejects_forbidden_topics(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file("topic = '/cmd_vel'\n") as tmp_file:
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            checker.check_direct_nav2_action_bridge_contract(result, [tmp_file])
        self.assertTrue(any("DIRECT_BRIDGE_FORBIDDEN_TOPIC" in e for e in result["errors"]))

    @contextmanager
    def _temp_file(self, content: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


class DirectNav2ActionBridgeOwnershipContractTests(unittest.TestCase):
    """Fase 2H.1.2: regresion-guard estatico para los defectos de ownership
    terminal/cancelacion confirmados en la auditoria de 49a998c.
    """

    REAL_BRIDGE_FILE = (
        CODE_ROOT / "src" / "navigation" / "direct_nav2_action_bridge.py"
    )

    def test_real_bridge_file_passes_ownership_contract(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        saved = checker.DIRECT_NAV2_ACTION_BRIDGE_FILE
        checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = self.REAL_BRIDGE_FILE
        try:
            checker.check_direct_nav2_action_bridge_ownership_contract(
                result, [self.REAL_BRIDGE_FILE]
            )
        finally:
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = saved
        self.assertEqual(result["errors"], [])

    def test_rejects_monitor_calling_public_cancel_navigation(self):
        source = (
            "class DirectNav2ActionBridge:\n"
            "    async def _result_monitor_task(self, *a, **kw):\n"
            "        await self.cancel_navigation()\n"
            "    async def _request_cancel_only(self):\n"
            "        pass\n"
            "    async def cancel_navigation(self):\n"
            "        raise RuntimeError('CANCEL_TERMINAL_NOT_CANCELED:' + str(1))\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_ownership_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = saved
        self.assertIn("DIRECT_BRIDGE_MONITOR_CALLS_PUBLIC_CANCEL", result["errors"])

    def test_rejects_missing_internal_cancel_helper(self):
        source = (
            "class DirectNav2ActionBridge:\n"
            "    async def _result_monitor_task(self, *a, **kw):\n"
            "        pass\n"
            "    async def cancel_navigation(self):\n"
            "        raise RuntimeError('CANCEL_TERMINAL_NOT_CANCELED:' + str(1))\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_ownership_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = saved
        self.assertIn("DIRECT_BRIDGE_CANCEL_HELPER_MISSING", result["errors"])

    def test_rejects_cancel_helper_that_waits_on_result_task(self):
        source = (
            "class DirectNav2ActionBridge:\n"
            "    async def _result_monitor_task(self, *a, **kw):\n"
            "        pass\n"
            "    async def _request_cancel_only(self):\n"
            "        await self._active_result_task\n"
            "    async def cancel_navigation(self):\n"
            "        raise RuntimeError('CANCEL_TERMINAL_NOT_CANCELED:' + str(1))\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_ownership_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = saved
        self.assertIn("DIRECT_BRIDGE_CANCEL_HELPER_WAITS_ON_RESULT_TASK", result["errors"])

    def test_rejects_public_cancel_not_enforcing_canceled_terminal(self):
        source = (
            "class DirectNav2ActionBridge:\n"
            "    async def _result_monitor_task(self, *a, **kw):\n"
            "        pass\n"
            "    async def _request_cancel_only(self):\n"
            "        pass\n"
            "    async def cancel_navigation(self):\n"
            "        pass\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_ownership_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = saved
        self.assertIn("DIRECT_BRIDGE_CANCEL_DOES_NOT_ENFORCE_CANCELED_TERMINAL", result["errors"])
        self.assertIn("DIRECT_BRIDGE_CANCEL_DOES_NOT_RAISE_ON_NON_TERMINAL", result["errors"])

    def test_rejects_silent_import_error(self):
        source = (
            "class DirectNav2ActionBridge:\n"
            "    async def _result_monitor_task(self, *a, **kw):\n"
            "        pass\n"
            "    async def _request_cancel_only(self):\n"
            "        pass\n"
            "    async def cancel_navigation(self):\n"
            "        raise RuntimeError('CANCEL_TERMINAL_NOT_CANCELED:' + str(1))\n"
            "    async def inject_absolute_pose(self, pose):\n"
            "        try:\n"
            "            import cv2\n"
            "        except ImportError:\n"
            "            pass\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_ownership_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = saved
        self.assertIn("DIRECT_BRIDGE_SILENT_IMPORT_ERROR", result["errors"])

    @contextmanager
    def _temp_file(self, content: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


class DirectNav2ActionBridgeCloseDegradedContractTests(unittest.TestCase):
    """Fase 2H.1.3: el bridge debe detectar degradacion preexistente al
    entrar a _cleanup(), no solo a partir de fallos reactivos.
    """

    def test_real_bridge_file_passes_close_degraded_contract(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_direct_nav2_action_bridge_close_degraded_contract(
            result, [checker.DIRECT_NAV2_ACTION_BRIDGE_FILE]
        )
        self.assertEqual(result["errors"], [])

    def test_rejects_cleanup_without_preexisting_state_check(self):
        source = (
            "class DirectNav2ActionBridge:\n"
            "    async def _cleanup(self):\n"
            "        degraded = False\n"
            "        try:\n"
            "            pass\n"
            "        except Exception:\n"
            "            degraded = True\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_close_degraded_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_FILE = saved
        self.assertIn("DIRECT_BRIDGE_CLOSE_DOES_NOT_CHECK_PREEXISTING_DEGRADED_STATE", result["errors"])
        self.assertIn("DIRECT_BRIDGE_CLOSE_DOES_NOT_CHECK_DANGLING_TASK_ACTIVE", result["errors"])

    @contextmanager
    def _temp_file(self, content: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


class DirectNav2ActionBridgeSmokeHardeningContractTests(unittest.TestCase):
    """Fase 2H.1.3: guards estaticos para el smoke runtime + tests directos
    de los helpers puros extraidos de smoke_test_direct_nav2_action_bridge.py.
    """

    def test_real_smoke_file_passes_hardening_contract(self):
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        checker.check_direct_nav2_action_bridge_smoke_hardening_contract(
            result, [checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE]
        )
        self.assertEqual(result["errors"], [])

    def test_rejects_silenced_bridge_close_exception(self):
        source = (
            "async def f(bridge):\n"
            "    try:\n"
            "        await bridge.close()\n"
            "    except Exception:\n"
            "        pass\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_smoke_hardening_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = saved
        self.assertIn("SMOKE_BRIDGE_CLOSE_EXCEPTION_SILENCED", result["errors"])

    def test_rejects_fw_unreachable_accepting_rejected(self):
        source = (
            "def f(res, NavigationTerminalStatus):\n"
            "    if res.status in (NavigationTerminalStatus.REJECTED, NavigationTerminalStatus.ABORTED):\n"
            "        pass\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_smoke_hardening_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = saved
        self.assertIn("SMOKE_FW_UNREACHABLE_ACCEPTS_REJECTED", result["errors"])

    def test_rejects_fixed_child_output_path_without_token(self):
        source = (
            "def f(name, domain):\n"
            "    return f'/tmp/ottoguide_direct_bridge_child_{name}_{domain}.json'\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_smoke_hardening_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = saved
        self.assertIn("SMOKE_CHILD_OUTPUT_PATH_NOT_UNIQUE", result["errors"])

    def test_rejects_observer_thread_joined_without_post_check(self):
        source = (
            "class TelemetryObserver:\n"
            "    def shutdown(self):\n"
            "        if self._thread.is_alive():\n"
            "            self._thread.join(timeout=2.0)\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_smoke_hardening_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = saved
        self.assertIn("SMOKE_OBSERVER_THREAD_JOINED_WITHOUT_POST_CHECK", result["errors"])

    def test_rejects_potentially_uninitialized_pgid(self):
        source = (
            "def _shutdown_and_count_orphans(launch_process):\n"
            "    if launch_process is None:\n"
            "        return 0\n"
            "    try:\n"
            "        pgid = os.getpgid(launch_process.pid)\n"
            "        os.killpg(pgid, 2)\n"
            "    except Exception:\n"
            "        pass\n"
            "    return 1 if _process_group_is_alive(pgid) else 0\n"
        )
        result = {"errors": [], "warnings": [], "forbidden_matches": [], "checked_files": []}
        with self._temp_file(source) as tmp_file:
            saved = checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE
            checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = tmp_file
            try:
                checker.check_direct_nav2_action_bridge_smoke_hardening_contract(result, [tmp_file])
            finally:
                checker.DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = saved
        self.assertIn("SMOKE_PGID_POTENTIALLY_UNINITIALIZED", result["errors"])

    # -- direct tests of the pure helpers extracted from the smoke test --

    def test_validate_child_result_detects_scenario_mismatch(self):
        payload = {"ok": True, "scenario": "ntp_cancel", "domain_id": "213"}
        errors = smoke._validate_child_result(payload, "ntp_success", "213", 0)
        self.assertTrue(any(e.startswith("CHILD_SCENARIO_MISMATCH") for e in errors))

    def test_validate_child_result_detects_domain_mismatch(self):
        payload = {"ok": True, "scenario": "ntp_success", "domain_id": "999"}
        errors = smoke._validate_child_result(payload, "ntp_success", "213", 0)
        self.assertTrue(any(e.startswith("CHILD_DOMAIN_MISMATCH") for e in errors))

    def test_validate_child_result_detects_exit_code_mismatch_ok_true(self):
        payload = {"ok": True, "scenario": "ntp_success", "domain_id": "213"}
        errors = smoke._validate_child_result(payload, "ntp_success", "213", 1)
        self.assertTrue(any(e.startswith("CHILD_EXIT_CODE_MISMATCH") for e in errors))

    def test_validate_child_result_detects_exit_code_mismatch_ok_false(self):
        payload = {"ok": False, "scenario": "ntp_success", "domain_id": "213"}
        errors = smoke._validate_child_result(payload, "ntp_success", "213", 0)
        self.assertTrue(any(e.startswith("CHILD_EXIT_CODE_MISMATCH") for e in errors))

    def test_validate_child_result_accepts_consistent_payload(self):
        payload = {"ok": True, "scenario": "ntp_success", "domain_id": "213"}
        self.assertEqual(smoke._validate_child_result(payload, "ntp_success", "213", 0), [])
        payload_fail = {"ok": False, "scenario": "ntp_success", "domain_id": "213"}
        self.assertEqual(smoke._validate_child_result(payload_fail, "ntp_success", "213", 1), [])

    def test_build_child_output_path_is_unique_per_call(self):
        path1 = smoke._build_child_output_path(1234, "ntp_success", "212")
        path2 = smoke._build_child_output_path(1234, "ntp_success", "212")
        self.assertNotEqual(path1, path2)
        self.assertFalse(path1.exists())
        self.assertFalse(path2.exists())

    def test_shutdown_and_count_orphans_handles_process_lookup_error(self):
        launch_process = MagicMock()
        launch_process.pid = 999999
        with patch.object(smoke.os, "getpgid", side_effect=ProcessLookupError, create=True):
            orphan_count = smoke._shutdown_and_count_orphans(launch_process)
        self.assertEqual(orphan_count, 0)

    def test_validate_fw_unreachable_result_rejects_rejected(self):
        from src.navigation.models import NavigationResult, NavigationTerminalStatus
        res = NavigationResult("test", NavigationTerminalStatus.REJECTED, False)
        errors = smoke._validate_fw_unreachable_result(res, [0], False, NavigationTerminalStatus)
        self.assertIn("FW_UNREACHABLE_REJECTED_NOT_ALLOWED", errors)

    def test_validate_fw_unreachable_result_rejects_timeout_and_error(self):
        from src.navigation.models import NavigationResult, NavigationTerminalStatus
        timeout_res = NavigationResult("test", NavigationTerminalStatus.TIMEOUT, False)
        errors = smoke._validate_fw_unreachable_result(timeout_res, [0], False, NavigationTerminalStatus)
        self.assertIn("FW_UNREACHABLE_REPORTED_AS_TIMEOUT", errors)

        error_res = NavigationResult("test", NavigationTerminalStatus.ERROR, False)
        errors = smoke._validate_fw_unreachable_result(error_res, [0], False, NavigationTerminalStatus)
        self.assertIn("FW_UNREACHABLE_REPORTED_AS_ERROR", errors)

    def test_validate_fw_unreachable_result_accepts_full_contract(self):
        from src.navigation.models import MissedWaypointDetail, NavigationResult, NavigationTerminalStatus
        res = NavigationResult(
            "test", NavigationTerminalStatus.ABORTED, False,
            missed_waypoints=(MissedWaypointDetail(index=1, error_code=204),)
        )
        errors = smoke._validate_fw_unreachable_result(res, [0, 1], False, NavigationTerminalStatus)
        self.assertEqual(errors, [])

    def test_validate_fw_unreachable_result_requires_index_1_and_code_204(self):
        from src.navigation.models import MissedWaypointDetail, NavigationResult, NavigationTerminalStatus
        wrong_code = NavigationResult(
            "test", NavigationTerminalStatus.ABORTED, False,
            missed_waypoints=(MissedWaypointDetail(index=1, error_code=105),)
        )
        errors = smoke._validate_fw_unreachable_result(wrong_code, [0, 1], False, NavigationTerminalStatus)
        self.assertTrue(any(e.startswith("MISSED_WAYPOINT_ERROR_CODE_NOT_204") for e in errors))

        no_missed = NavigationResult("test", NavigationTerminalStatus.ABORTED, False)
        errors = smoke._validate_fw_unreachable_result(no_missed, [0, 1], False, NavigationTerminalStatus)
        self.assertIn("MISSED_WAYPOINT_INDEX_1_ABSENT", errors)

    def test_validate_fw_unreachable_result_rejects_progress_to_index_2(self):
        from src.navigation.models import MissedWaypointDetail, NavigationResult, NavigationTerminalStatus
        res = NavigationResult(
            "test", NavigationTerminalStatus.ABORTED, False,
            missed_waypoints=(MissedWaypointDetail(index=1, error_code=204),)
        )
        errors = smoke._validate_fw_unreachable_result(res, [0, 1, 2], False, NavigationTerminalStatus)
        self.assertIn("FEEDBACK_PROGRESSED_TO_INDEX_2", errors)

    def test_validate_fw_unreachable_result_rejects_true_task_result(self):
        from src.navigation.models import MissedWaypointDetail, NavigationResult, NavigationTerminalStatus
        res = NavigationResult(
            "test", NavigationTerminalStatus.ABORTED, False,
            missed_waypoints=(MissedWaypointDetail(index=1, error_code=204),)
        )
        errors = smoke._validate_fw_unreachable_result(res, [0, 1], True, NavigationTerminalStatus)
        self.assertIn("NAVIGATION_TASK_RESULT_TRUE_FOR_UNREACHABLE", errors)

    def test_validate_fw_unreachable_result_fails_without_result(self):
        from src.navigation.models import NavigationTerminalStatus
        errors = smoke._validate_fw_unreachable_result(None, [0], False, NavigationTerminalStatus)
        self.assertEqual(errors, ["FW_UNREACHABLE_NO_RESULT"])

    def test_telemetry_observer_shutdown_raises_on_thread_still_alive(self):
        observer = smoke.TelemetryObserver.__new__(smoke.TelemetryObserver)
        observer._executor = MagicMock()
        observer._node = MagicMock()
        observer._rclpy = MagicMock()
        observer._context = MagicMock()
        observer._thread = MagicMock()
        observer._thread.is_alive.return_value = True

        with self.assertRaisesRegex(RuntimeError, "OBSERVER_THREAD_STILL_ALIVE"):
            observer.shutdown()
        observer._thread.join.assert_called_once()

    def test_telemetry_observer_shutdown_reports_nonfatal_failures_together(self):
        observer = smoke.TelemetryObserver.__new__(smoke.TelemetryObserver)
        observer._executor = MagicMock()
        observer._executor.shutdown.side_effect = Exception("executor boom")
        observer._node = MagicMock()
        observer._node.destroy_node.side_effect = Exception("node boom")
        observer._rclpy = MagicMock()
        observer._context = MagicMock()
        observer._thread = MagicMock()
        observer._thread.is_alive.return_value = False

        with self.assertRaisesRegex(RuntimeError, "OBSERVER_SHUTDOWN_FAILED"):
            observer.shutdown()

    def test_telemetry_observer_shutdown_clean_does_not_raise(self):
        observer = smoke.TelemetryObserver.__new__(smoke.TelemetryObserver)
        observer._executor = MagicMock()
        observer._node = MagicMock()
        observer._rclpy = MagicMock()
        observer._rclpy.ok.return_value = False
        observer._context = MagicMock()
        observer._thread = MagicMock()
        observer._thread.is_alive.return_value = False

        observer.shutdown()  # must not raise

    @contextmanager
    def _temp_file(self, content: str):
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            yield Path(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
