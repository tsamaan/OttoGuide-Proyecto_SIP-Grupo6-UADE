#!/usr/bin/env python3
"""Static, offline-only isolation checker for the Nav2 offline sandbox.

Inspects local files and configuration exclusively. Does not access the
network, does not query the ROS graph, and does not start any node.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
REPO_ROOT = CODE_ROOT.parent

LAUNCH_FILE = CODE_ROOT / "launch" / "offline_nav_sandbox.launch.py"
PARAMS_FILE = CODE_ROOT / "config" / "navigation" / "nav2_offline_sandbox_params.yaml"
MAP_YAML = CODE_ROOT / "tests" / "fixtures" / "offline_navigation" / "offline_sandbox_test_map.yaml"

FORBIDDEN_IP_PATTERN = re.compile(r"192\.168\.123\.\d{1,3}")
FORBIDDEN_CMD_VEL_PATTERN = re.compile(r"/cmd_vel(?!_)")
FORBIDDEN_CMD_VEL_NAV_PATTERN = re.compile(r"/cmd_vel_nav")
FORBIDDEN_BRIDGE_PATTERN = re.compile(
    r"unitree_sdk2py|LocoClient|unitree_capture_bridge|ottoguide_livox_sdk_bridge|livox_ros_driver2"
)
# Out of scope for the current phases of the offline sandbox. These
# executables/packages must never appear in the launch file. bt_navigator /
# nav2_bt_navigator are authorized as of Phase 2F (NavigateToPose only) and
# waypoint_follower / nav2_waypoint_follower are authorized as of Phase 2G
# (FollowWaypoints only, namespaced under /offline_nav); both are
# intentionally excluded from this pattern and enforced by their own
# dedicated contract checkers (check_bt_navigator_contract,
# check_waypoint_follower_contract) instead. Simple Commander / BasicNavigator
# remain fully out of scope and are never exempted.
FORBIDDEN_MISSION_COMPONENT_PATTERN = re.compile(
    r"nav2_simple_commander|simple_commander|BasicNavigator"
)
# Forbidden regardless of namespace: a second/duplicate waypoint follower
# package reference, or any reference to the application's parallel
# BasicNavigator.followWaypoints() client stack.
FORBIDDEN_WAYPOINT_FOLLOWER_DUPLICATE_PATTERN = re.compile(
    r"followWaypoints|nav2_bridge"
)
FORBIDDEN_HAL_IMPORT_MODULES = {
    "unitree_sdk2py",
    "real_adapter",
    "src.hardware.real_adapter",
}

SIMULATOR_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "offline_runtime_simulator.py"
)
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
    CODE_ROOT
    / "tools"
    / "hil"
    / "offline_navigation"
    / "smoke_test_offline_collision_monitor.py"
)
BEHAVIOR_SERVER_SMOKE_TEST_FILE = (
    CODE_ROOT
    / "tools"
    / "hil"
    / "offline_navigation"
    / "smoke_test_offline_behavior_server.py"
)
BT_NAVIGATOR_SMOKE_TEST_FILE = (
    CODE_ROOT
    / "tools"
    / "hil"
    / "offline_navigation"
    / "smoke_test_offline_bt_navigator.py"
)
WAYPOINT_FOLLOWER_SMOKE_TEST_FILE = (
    CODE_ROOT
    / "tools"
    / "hil"
    / "offline_navigation"
    / "smoke_test_offline_waypoint_follower.py"
)
DIRECT_NAV2_ACTION_BRIDGE_FILE = (
    CODE_ROOT / "src" / "navigation" / "direct_nav2_action_bridge.py"
)
DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE = (
    CODE_ROOT
    / "tools"
    / "hil"
    / "offline_navigation"
    / "smoke_test_direct_nav2_action_bridge.py"
)
MAIN_RUNTIME_NAVIGATION_SELECTION_SMOKE_TEST_FILE = (
    CODE_ROOT
    / "tools"
    / "hil"
    / "offline_navigation"
    / "smoke_test_main_runtime_navigation_selection.py"
)
BT_XML_FILE = CODE_ROOT / "config" / "navigation" / "bt" / "offline_navigate_to_pose.xml"

# Fase 2H.0 — Reconciliacion de arquitecturas de navegacion y hardware. These
# canonical contract/runtime files must never reference BasicNavigator,
# /cmd_vel_nav, CMD_VEL_FILTERED_TOPIC, or import src.hardware (the legacy,
# quarantined HAL package). This is a static, file-content guard only; it
# does not change the sandbox's own contract checks above.
ARCHITECTURE_MODELS_FILE = CODE_ROOT / "src" / "navigation" / "models.py"
ARCHITECTURE_PORT_FILE = CODE_ROOT / "src" / "navigation" / "port.py"
ARCHITECTURE_TOUR_ORCHESTRATOR_FILE = CODE_ROOT / "src" / "core" / "tour_orchestrator.py"
ARCHITECTURE_MAIN_FILE = CODE_ROOT / "main.py"
ARCHITECTURE_RECONCILIATION_FILES = (
    ARCHITECTURE_MODELS_FILE,
    ARCHITECTURE_PORT_FILE,
    ARCHITECTURE_TOUR_ORCHESTRATOR_FILE,
    ARCHITECTURE_MAIN_FILE,
)
FORBIDDEN_ARCHITECTURE_SYMBOLS = ("BasicNavigator", "/cmd_vel_nav", "CMD_VEL_FILTERED_TOPIC")
FORBIDDEN_ARCHITECTURE_IMPORT_PREFIX = "src.hardware"

RUNTIME_SCAN_FILES = [
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
    WAYPOINT_FOLLOWER_SMOKE_TEST_FILE,
    DIRECT_NAV2_ACTION_BRIDGE_FILE,
    DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE,
    MAIN_RUNTIME_NAVIGATION_SELECTION_SMOKE_TEST_FILE,
]
EXPECTED_REAL_NAMESPACE = "offline_nav"

FORBIDDEN_BT_XML_NODE_PATTERN = re.compile(
    r"\bBackUp\b|\bDriveOnHeading\b|\bAssistedTeleop\b|\bClearEntireCostmap\b|"
    r"\bRecoveryNode\b|\bRoundRobin\b|\bWaypointFollower\b|\bNavigateThroughPoses\b"
)
REQUIRED_BT_XML_NODE_NAMES = ("ComputePathToPose", "FollowPath")
REQUIRED_BT_XML_MARKERS = (
    "OFFLINE_ONLY",
    "SYNTHETIC",
    "NOT_FOR_HARDWARE",
    "NOT_UADE_MAP",
)

# Required ROS entities in the launch file: a Node call must carry a real
# namespace= kwarg, or (for ExecuteProcess-launched rclpy scripts) the cmd
# list must include a '-r' remap of '__ns:=/<namespace>'.
REQUIRED_NODE_NAMES = {
    "map_server",
    "planner_server",
    "controller_server",
    "collision_monitor",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
    "lifecycle_manager_navigation",
    "lifecycle_manager_controller",
    "lifecycle_manager_collision_monitor",
    "lifecycle_manager_behavior_server",
    "lifecycle_manager_bt_navigator",
    "lifecycle_manager_waypoint_follower",
    "map_to_odom_synthetic_tf",
    "base_link_to_utlidar_lidar_synthetic_tf",
}
REQUIRED_EXECUTE_PROCESS_NAMES = {"offline_runtime_simulator"}

# Velocity topic policy: only the relative 'cmd_vel_raw' and 'cmd_vel_safe' names
# (which resolve under the sandbox namespace) are allowed.
ALLOWED_VELOCITY_TOPIC_NAMES = {"cmd_vel_raw", "cmd_vel_safe"}
FORBIDDEN_VELOCITY_TOPIC_PATTERN = re.compile(r"(?<![\w])cmd_vel(?:_nav)?(?![\w])")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_map_default_versioned(result: dict) -> None:
    result["checked_files"].append(str(LAUNCH_FILE))
    if not LAUNCH_FILE.is_file():
        result["errors"].append("LAUNCH_FILE_MISSING")
        return
    text = _read_text(LAUNCH_FILE)
    try:
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
    except SyntaxError:
        result["errors"].append("LAUNCH_FILE_SYNTAX_ERROR")
        return
    map_default_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MAP_DEFAULT" for target in node.targets
        ):
            map_default_node = node.value
            break
    if map_default_node is None:
        result["errors"].append("MAP_DEFAULT_NOT_FOUND")
        return
    map_default_expr = ast.unparse(map_default_node)
    if "artifacts" in map_default_expr:
        result["errors"].append("MAP_DEFAULT_DEPENDS_ON_ARTIFACTS")
    if "tests" not in map_default_expr or "fixtures" not in map_default_expr:
        result["errors"].append("MAP_DEFAULT_NOT_VERSIONED_FIXTURE")

    result["checked_files"].append(str(MAP_YAML))
    if not MAP_YAML.is_file():
        result["errors"].append("SYNTHETIC_MAP_YAML_MISSING")
        return
    map_text = _read_text(MAP_YAML)
    for marker in (
        "SYNTHETIC_TEST_MAP",
        "NOT_UADE_MAP",
        "NOT_METRICALLY_VALIDATED",
        "NOT_FOR_PHYSICAL_NAVIGATION",
    ):
        if marker not in map_text:
            result["errors"].append(f"MISSING_MARKER_{marker}")

    image_match = re.search(r"^\s*image:\s*(\S+)", map_text, re.MULTILINE)
    if not image_match:
        result["errors"].append("MAP_YAML_MISSING_IMAGE_FIELD")
    else:
        image_path = MAP_YAML.parent / image_match.group(1)
        result["checked_files"].append(str(image_path))
        if not image_path.is_file():
            result["errors"].append("MAP_IMAGE_FILE_MISSING")


def check_forbidden_ip(result: dict, files: list[Path]) -> None:
    for path in files:
        if not path.is_file():
            continue
        text = _read_text(path)
        for match in FORBIDDEN_IP_PATTERN.finditer(text):
            result["forbidden_matches"].append(
                {"file": str(path), "pattern": "FORBIDDEN_IP", "match": match.group(0)}
            )
            result["errors"].append("FORBIDDEN_IP_FOUND")


def _strip_comment_lines(text: str) -> str:
    """Drop Python/YAML comment lines so documentation mentions of a
    forbidden topic (stating it is absent) do not trigger a false positive.
    """
    kept_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


# Smoke tests legitimately reference these topic names as string literals to
# *detect their absence* (e.g. `"/cmd_vel" in topics`), not to publish or
# subscribe to them. Lines matching this idiom are excluded from the
# forbidden-topic scan; actual publisher/subscriber wiring (create_publisher,
# create_subscription, ros2 topic pub, etc.) is not matched by it and still
# triggers a violation.
DETECTION_IDIOM_PATTERN = re.compile(r'["\'](/cmd_vel(?:_nav)?)["\']\s*in\s+\w+')

# Only string literals are inspected for the velocity topic allowlist policy
# (identifiers like result["global_cmd_vel_detected"] or parameter names
# like cmd_vel_watchdog_timeout_s are not topic names and must not match).
STRING_LITERAL_PATTERN = re.compile(r'"([^"\\]|\\.)*"|\'([^\'\\]|\\.)*\'')

# Smoke tests declare their own list of forbidden/allowed velocity topic
# suffixes as module-level constants, then check membership with
# str.endswith(...). The constant *declaration* line is detection tooling,
# not a real publish/subscribe usage, so it is exempted from the scan.
VELOCITY_CONSTANT_DECLARATION_PATTERN = re.compile(
    r"^\s*(FORBIDDEN|ALLOWED)_\w*VELOCITY\w*\s*="
)

# The only legitimate place the bare relative name 'cmd_vel' may appear is as
# the *source* of a remap tuple to 'cmd_vel_raw' on controller_server, e.g.
# remappings=[('cmd_vel', 'cmd_vel_raw')]. This is required so the node's
# internal default output (relative 'cmd_vel') is redirected to the only
# topic name this sandbox allows.
CMD_VEL_REMAP_TUPLE_PATTERN = re.compile(
    r'\(\s*["\']cmd_vel["\']\s*,\s*["\']cmd_vel_raw["\']\s*\)'
)


def _strip_detection_idiom_lines(text: str) -> str:
    kept_lines = []
    for line in text.splitlines():
        if DETECTION_IDIOM_PATTERN.search(line):
            continue
        if VELOCITY_CONSTANT_DECLARATION_PATTERN.match(line):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def check_forbidden_topics(result: dict, files: list[Path]) -> None:
    for path in files:
        if not path.is_file():
            continue
        text = _strip_detection_idiom_lines(_strip_comment_lines(_read_text(path)))
        for match in FORBIDDEN_CMD_VEL_NAV_PATTERN.finditer(text):
            result["forbidden_matches"].append(
                {"file": str(path), "pattern": "CMD_VEL_NAV", "match": match.group(0)}
            )
            result["errors"].append("CMD_VEL_NAV_REFERENCED")
        text_without_cmd_vel_nav = FORBIDDEN_CMD_VEL_NAV_PATTERN.sub("", text)
        for match in FORBIDDEN_CMD_VEL_PATTERN.finditer(text_without_cmd_vel_nav):
            result["forbidden_matches"].append(
                {"file": str(path), "pattern": "CMD_VEL", "match": match.group(0)}
            )
            result["errors"].append("CMD_VEL_REFERENCED")


def check_velocity_topic_allowlist(result: dict, files: list[Path]) -> None:
    """Enforce that the only velocity topic names ever referenced are the
    relative 'cmd_vel_raw' and 'cmd_vel_safe'. Standalone 'cmd_vel' is only
    allowed in launch remappings or in smoke tests detection constants. Topics
    with forbidden suffixes like cmd_vel_unsafe, cmd_vel_filtered, cmd_vel_output,
    cmd_vel_nav, or global FQNs like /cmd_vel, /offline_nav/cmd_vel are rejected.
    """
    allowed_topics = {"cmd_vel_raw", "cmd_vel_safe"}

    def is_allowed_variable(w: str) -> bool:
        return any(sub in w for sub in ("_messages", "_observed", "_timeout", "_topic", "watchdog"))

    for path in files:
        if not path.is_file():
            continue

        if path.suffix == ".yaml":
            # Check YAML configuration exactly
            text = _read_text(path)
            lines = _strip_comment_lines(text).splitlines()
            for line in lines:
                if "cmd_vel_in_topic" in line:
                    if not re.search(r"cmd_vel_in_topic:\s*[\"']?cmd_vel_raw[\"']?", line):
                        result["errors"].append("FORBIDDEN_VELOCITY_TOPIC_cmd_vel_in_topic")
                elif "cmd_vel_out_topic" in line:
                    if not re.search(r"cmd_vel_out_topic:\s*[\"']?cmd_vel_safe[\"']?", line):
                        result["errors"].append("FORBIDDEN_VELOCITY_TOPIC_cmd_vel_out_topic")
                elif "cmd_vel" in line:
                    words = re.findall(r"\bcmd_vel\w*\b", line)
                    for w in words:
                        if w not in allowed_topics and not is_allowed_variable(w):
                            result["errors"].append(f"FORBIDDEN_VELOCITY_TOPIC_{w}")

        elif path.suffix == ".py":
            # Semantic Python check using AST
            try:
                content = _read_text(path)
                tree = ast.parse(content, filename=str(path))
            except Exception:
                result["errors"].append(f"PYTHON_PARSE_ERROR_{path.name}")
                continue

            is_smoke = "smoke" in path.name

            for node in ast.walk(tree):
                # 1. Check create_publisher / create_subscription / ActionClient topic arguments
                if isinstance(node, ast.Call):
                    func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if func_name in ("create_publisher", "create_subscription", "ActionClient"):
                        topic_arg = None
                        if func_name in ("create_publisher", "create_subscription"):
                            if len(node.args) >= 2:
                                topic_arg = node.args[1]
                            for kw in node.keywords:
                                if kw.arg == "topic":
                                    topic_arg = kw.value
                        elif func_name == "ActionClient":
                            if len(node.args) >= 3:
                                topic_arg = node.args[2]
                            for kw in node.keywords:
                                if kw.arg == "action_name":
                                    topic_arg = kw.value

                        if topic_arg is not None:
                            topic_str = ast.unparse(topic_arg).strip("\"'")
                            if "cmd_vel" in topic_str:
                                words = re.findall(r"\bcmd_vel\w*\b", topic_str)
                                for w in words:
                                    w_norm = w.strip("\"'/")
                                    if w_norm.startswith("offline_nav/"):
                                        w_norm = w_norm[len("offline_nav/"):]
                                    if w_norm.startswith("{namespace}/"):
                                        w_norm = w_norm[len("{namespace}/"):]
                                    if w_norm not in allowed_topics and not is_allowed_variable(w_norm):
                                        result["errors"].append(f"FORBIDDEN_VELOCITY_TOPIC_{w_norm}")

                    # 2. Check Node remappings
                    elif func_name == "Node":
                        for kw in node.keywords:
                            if kw.arg == "remappings":
                                if isinstance(kw.value, ast.List):
                                    for elt in kw.value.elts:
                                        if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                                            src_str = ast.unparse(elt.elts[0]).strip("\"'")
                                            dst_str = ast.unparse(elt.elts[1]).strip("\"'")
                                            if "cmd_vel" in src_str or "cmd_vel" in dst_str:
                                                if src_str == "cmd_vel" and dst_str == "cmd_vel_raw":
                                                    continue
                                                result["errors"].append(f"FORBIDDEN_VELOCITY_TOPIC_remap_{src_str}_to_{dst_str}")

                # 3. Check all string constants for forbidden terms
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value
                    if "cmd_vel" in val:
                        words = re.findall(r"\bcmd_vel\w*\b", val)
                        for w in words:
                            w_norm = w.strip("\"'/")
                            if w_norm.startswith("offline_nav/"):
                                w_norm = w_norm[len("offline_nav/"):]
                            if w_norm.startswith("{namespace}/"):
                                w_norm = w_norm[len("{namespace}/"):]

                            if is_smoke:
                                if w_norm in ("cmd_vel", "cmd_vel_nav", "cmd_vel_raw", "cmd_vel_safe"):
                                    continue
                                if is_allowed_variable(w_norm):
                                    continue
                                result["errors"].append(f"FORBIDDEN_VELOCITY_TOPIC_{w_norm}")
                            else:
                                if w_norm in allowed_topics:
                                    continue
                                if w_norm == "cmd_vel" and "launch" in path.name:
                                    continue
                                if is_allowed_variable(w_norm):
                                    continue
                                result["errors"].append(f"FORBIDDEN_VELOCITY_TOPIC_{w_norm}")

        elif path.suffix == ".sh":
            text = _strip_comment_lines(_read_text(path))
            words = re.findall(r"\bcmd_vel\w*\b", text)
            for w in words:
                w_norm = w.strip("\"'/")
                if w_norm not in allowed_topics:
                    result["errors"].append(f"FORBIDDEN_VELOCITY_TOPIC_{w_norm}")


def check_forbidden_bridges(result: dict, files: list[Path]) -> None:
    for path in files:
        if not path.is_file():
            continue
        text = _read_text(path)
        for match in FORBIDDEN_BRIDGE_PATTERN.finditer(text):
            result["forbidden_matches"].append(
                {"file": str(path), "pattern": "PHYSICAL_BRIDGE", "match": match.group(0)}
            )
            result["errors"].append("PHYSICAL_BRIDGE_REFERENCED")


def check_no_mission_components(result: dict) -> None:
    """Simple Commander / BasicNavigator are explicitly out of scope for
    every phase implemented so far; the launch file must never reference
    them. BT Navigator (Phase 2F) and Waypoint Follower (Phase 2G) are
    authorized exceptions enforced by their own dedicated contract checkers
    (check_bt_navigator_contract, check_waypoint_follower_contract).
    """
    result["checked_files"].append(str(LAUNCH_FILE))
    if not LAUNCH_FILE.is_file():
        return
    text = _strip_comment_lines(_read_text(LAUNCH_FILE))
    for match in FORBIDDEN_MISSION_COMPONENT_PATTERN.finditer(text):
        result["forbidden_matches"].append(
            {"file": str(LAUNCH_FILE), "pattern": "MISSION_COMPONENT", "match": match.group(0)}
        )
        result["errors"].append("MISSION_COMPONENT_OUT_OF_SCOPE_REFERENCED")
    for match in FORBIDDEN_WAYPOINT_FOLLOWER_DUPLICATE_PATTERN.finditer(text):
        result["forbidden_matches"].append(
            {"file": str(LAUNCH_FILE), "pattern": "PARALLEL_APP_STACK", "match": match.group(0)}
        )
        result["errors"].append("PARALLEL_APP_STACK_REFERENCED")


def _execute_process_cmd_has_ns_remap(node: ast.Call) -> bool:
    """Detect a '-r', ['__ns:=/', namespace] remap pair inside cmd=[...]."""
    for kw in node.keywords:
        if kw.arg != "cmd" or not isinstance(kw.value, ast.List):
            continue
        elements = kw.value.elts
        for i, element in enumerate(elements):
            if isinstance(element, ast.Constant) and element.value == "-r":
                if i + 1 < len(elements) and isinstance(elements[i + 1], ast.List):
                    remap_parts = elements[i + 1].elts
                    if remap_parts and isinstance(remap_parts[0], ast.Constant):
                        if str(remap_parts[0].value).startswith("__ns:="):
                            return True
    return False


def check_namespace_offline(result: dict) -> None:
    """Require a *real* ROS namespace/remapping per required entity.

    A real namespace means: a DeclareLaunchArgument named 'sandbox_namespace'
    whose default value is EXPECTED_REAL_NAMESPACE; every required Node(...)
    call (REQUIRED_NODE_NAMES) passes namespace= using that argument; and
    every required ExecuteProcess(...) call (REQUIRED_EXECUTE_PROCESS_NAMES)
    remaps '__ns:=/<namespace>' in its cmd list. Counting >0 occurrences is
    not enough: each required entity must be individually verified by name.
    """
    result["checked_files"].append(str(LAUNCH_FILE))
    if not LAUNCH_FILE.is_file():
        result["errors"].append("LAUNCH_FILE_MISSING")
        return
    text = _read_text(LAUNCH_FILE)
    try:
        tree = ast.parse(text, filename=str(LAUNCH_FILE))
    except SyntaxError:
        result["errors"].append("LAUNCH_FILE_SYNTAX_ERROR")
        return

    has_namespace_arg_declaration = False
    has_namespace_arg_correct_default = False
    namespaced_node_names: set[str] = set()
    namespaced_execute_process_names: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)

        if func_name == "DeclareLaunchArgument":
            arg_name = None
            default_value = None
            if node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant):
                    arg_name = first_arg.value
            for kw in node.keywords:
                if kw.arg == "default_value" and isinstance(kw.value, ast.Constant):
                    default_value = kw.value.value
            if arg_name == "sandbox_namespace":
                has_namespace_arg_declaration = True
                if default_value == EXPECTED_REAL_NAMESPACE:
                    has_namespace_arg_correct_default = True

        if func_name == "Node":
            node_name = None
            has_namespace_kwarg = False
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    node_name = kw.value.value
                if kw.arg == "namespace":
                    has_namespace_kwarg = True
            if node_name is not None and has_namespace_kwarg:
                namespaced_node_names.add(node_name)

        if func_name == "ExecuteProcess":
            process_name = None
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    process_name = kw.value.value
            if process_name is not None and _execute_process_cmd_has_ns_remap(node):
                namespaced_execute_process_names.add(process_name)

    if not has_namespace_arg_declaration:
        result["errors"].append("NO_SANDBOX_NAMESPACE_ARGUMENT_DECLARED")
    elif not has_namespace_arg_correct_default:
        result["errors"].append("SANDBOX_NAMESPACE_DEFAULT_NOT_OFFLINE_NAV")

    missing_node_namespaces = REQUIRED_NODE_NAMES - namespaced_node_names
    for missing in sorted(missing_node_namespaces):
        result["errors"].append(f"NODE_MISSING_NAMESPACE_{missing}")

    missing_process_namespaces = REQUIRED_EXECUTE_PROCESS_NAMES - namespaced_execute_process_names
    for missing in sorted(missing_process_namespaces):
        result["errors"].append(f"EXECUTE_PROCESS_MISSING_NS_REMAP_{missing}")


def check_localhost_only_required(result: dict, runtime: bool = False) -> None:
    files_to_check = [LAUNCH_FILE, PARAMS_FILE, RUNTIME_WRAPPER]
    found = False
    for path in files_to_check:
        if path.is_file() and "ROS_LOCALHOST_ONLY" in _read_text(path):
            found = True
    if not found:
        result["warnings"].append("ROS_LOCALHOST_ONLY_NOT_DOCUMENTED")

    value = os.environ.get("ROS_LOCALHOST_ONLY")
    if value != "1":
        if runtime:
            result["errors"].append("ROS_LOCALHOST_ONLY_NOT_ENABLED")
        else:
            result["warnings"].append("ROS_LOCALHOST_ONLY_NOT_SET_IN_ENVIRONMENT")


def check_domain_id_required(result: dict, runtime: bool = False) -> None:
    files_to_check = [LAUNCH_FILE, PARAMS_FILE, RUNTIME_WRAPPER]
    found = False
    for path in files_to_check:
        if path.is_file() and "ROS_DOMAIN_ID" in _read_text(path):
            found = True
    if not found:
        result["warnings"].append("ROS_DOMAIN_ID_NOT_DOCUMENTED")

    value = os.environ.get("ROS_DOMAIN_ID")
    if runtime:
        if not value:
            result["errors"].append("ROS_DOMAIN_ID_MISSING")
        elif value == "0":
            result["errors"].append("ROS_DOMAIN_ID_IS_ZERO")
    else:
        if not value:
            result["warnings"].append("ROS_DOMAIN_ID_NOT_SET_IN_ENVIRONMENT")


def check_no_physical_hal_import(result: dict) -> None:
    result["checked_files"].append(str(LAUNCH_FILE))
    if not LAUNCH_FILE.is_file():
        return
    try:
        tree = ast.parse(_read_text(LAUNCH_FILE), filename=str(LAUNCH_FILE))
    except SyntaxError:
        result["errors"].append("LAUNCH_FILE_SYNTAX_ERROR")
        return
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if any(name == forbidden or name.startswith(forbidden + ".") for forbidden in FORBIDDEN_HAL_IMPORT_MODULES):
                result["errors"].append(f"PHYSICAL_HAL_IMPORT_{name}")

def check_collision_monitor_contract(result: dict, files: list[Path]) -> None:
    if LAUNCH_FILE in files and LAUNCH_FILE.is_file():
        launch_text = _read_text(LAUNCH_FILE)
        if "collision_monitor" not in launch_text:
            result["errors"].append("COLLISION_MONITOR_MISSING")
        if "lifecycle_manager_collision_monitor" not in launch_text:
            result["errors"].append("LIFECYCLE_MANAGER_COLLISION_MONITOR_MISSING")
        if "('cmd_vel', 'cmd_vel_safe')" in launch_text or "(\"cmd_vel\", \"cmd_vel_safe\")" in launch_text:
            result["errors"].append("DIRECT_RAW_TO_SIMULATOR_BYPASS")
        if "behavior_server" in launch_text:
            if "lifecycle_manager_behavior_server" not in launch_text:
                result["errors"].append("LIFECYCLE_MANAGER_BEHAVIOR_SERVER_MISSING")
            tree = ast.parse(launch_text, filename=str(LAUNCH_FILE))
            behavior_server_remaps_to_raw = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
                    executable = None
                    remap_to_cmd_vel_raw = False
                    for kw in node.keywords:
                        if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                            executable = kw.value.value
                        if kw.arg == "remappings" and isinstance(kw.value, ast.List):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                                    src = ast.unparse(elt.elts[0]).strip("\"'")
                                    dst = ast.unparse(elt.elts[1]).strip("\"'")
                                    if src == "cmd_vel" and dst == "cmd_vel_raw":
                                        remap_to_cmd_vel_raw = True
                                    elif src == "cmd_vel" and dst == "cmd_vel_safe":
                                        result["errors"].append("BEHAVIOR_SERVER_DIRECT_SAFE_BYPASS")
                    if executable == "behavior_server" and remap_to_cmd_vel_raw:
                        behavior_server_remaps_to_raw = True
            if not behavior_server_remaps_to_raw:
                result["errors"].append("BEHAVIOR_SERVER_MISSING_CMD_VEL_RAW_REMAP")

    if SIMULATOR_FILE in files and SIMULATOR_FILE.is_file():
        sim_text = _read_text(SIMULATOR_FILE)
        if "cmd_vel_raw" in sim_text:
            if "create_subscription(Twist, \"cmd_vel_raw\"" in sim_text or "create_subscription(Twist, 'cmd_vel_raw'" in sim_text:
                result["errors"].append("SIMULATOR_SUBSCRIBED_TO_CMD_VEL_RAW")
        if "cmd_vel_safe" not in sim_text:
            result["errors"].append("OUTPUT_SAFE_WITHOUT_CONSUMER")


def check_bt_navigator_contract(result: dict) -> None:
    """BT Navigator is authorized as of Phase 2F, but only for NavigateToPose
    orchestration: it must be namespaced, managed by its own dedicated
    lifecycle manager, never remap any velocity topic, and reference a
    versioned, minimal BT XML that contains ComputePathToPose/FollowPath and
    none of the out-of-scope nodes (BackUp, DriveOnHeading, AssistedTeleop,
    ClearEntireCostmap, recovery/round-robin trees, Waypoint Follower,
    NavigateThroughPoses).
    """
    result["checked_files"].append(str(LAUNCH_FILE))
    if not LAUNCH_FILE.is_file():
        result["errors"].append("LAUNCH_FILE_MISSING")
        return
    launch_text = _read_text(LAUNCH_FILE)

    if "bt_navigator" not in launch_text:
        result["errors"].append("BT_NAVIGATOR_MISSING")
        return
    if "lifecycle_manager_bt_navigator" not in launch_text:
        result["errors"].append("LIFECYCLE_MANAGER_BT_NAVIGATOR_MISSING")

    try:
        tree = ast.parse(launch_text, filename=str(LAUNCH_FILE))
    except SyntaxError:
        result["errors"].append("LAUNCH_FILE_SYNTAX_ERROR")
        return

    bt_navigator_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
            executable = None
            for kw in node.keywords:
                if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                    executable = kw.value.value
            if executable == "bt_navigator":
                bt_navigator_node = node
                break

    if bt_navigator_node is None:
        result["errors"].append("BT_NAVIGATOR_NODE_NOT_FOUND")
    else:
        has_namespace = any(kw.arg == "namespace" for kw in bt_navigator_node.keywords)
        if not has_namespace:
            result["errors"].append("BT_NAVIGATOR_MISSING_NAMESPACE")
        for kw in bt_navigator_node.keywords:
            if kw.arg == "remappings":
                result["errors"].append("BT_NAVIGATOR_HAS_VELOCITY_REMAP")

    # node_names list for lifecycle_manager_bt_navigator must contain only
    # bt_navigator, isolated from every other lifecycle manager.
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
    bt_navigator_only_lists = [names for names in node_names_lists if names == ["bt_navigator"]]
    if not bt_navigator_only_lists:
        result["errors"].append("BT_NAVIGATOR_LIFECYCLE_MANAGER_NOT_ISOLATED")

    # XML contract.
    result["checked_files"].append(str(BT_XML_FILE))
    if not BT_XML_FILE.is_file():
        result["errors"].append("BT_XML_MISSING")
        return
    try:
        BT_XML_FILE.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        result["errors"].append("BT_XML_OUTSIDE_REPOSITORY")

    xml_text = _read_text(BT_XML_FILE)
    for marker in REQUIRED_BT_XML_MARKERS:
        if marker not in xml_text:
            result["errors"].append(f"BT_XML_MISSING_MARKER_{marker}")
    for required_node in REQUIRED_BT_XML_NODE_NAMES:
        if required_node not in xml_text:
            result["errors"].append(f"BT_XML_MISSING_NODE_{required_node}")
    xml_text_without_comments = re.sub(r"<!--.*?-->", "", xml_text, flags=re.DOTALL)
    for match in FORBIDDEN_BT_XML_NODE_PATTERN.finditer(xml_text_without_comments):
        result["errors"].append(f"BT_XML_FORBIDDEN_NODE_{match.group(0)}")
    try:
        ET.parse(BT_XML_FILE)
    except ET.ParseError:
        result["errors"].append("BT_XML_NOT_PARSEABLE")


def check_waypoint_follower_contract(result: dict) -> None:
    """Waypoint Follower is authorized as of Phase 2G, but only as a single,
    namespaced node under /offline_nav, managed by its own dedicated
    lifecycle manager, and never remapping any velocity topic (its only
    interaction with the rest of the chain is sending NavigateToPose goals
    to bt_navigator; it never reaches cmd_vel_raw/cmd_vel_safe directly).
    """
    result["checked_files"].append(str(LAUNCH_FILE))
    if not LAUNCH_FILE.is_file():
        result["errors"].append("LAUNCH_FILE_MISSING")
        return
    launch_text = _read_text(LAUNCH_FILE)

    if "waypoint_follower" not in launch_text:
        result["errors"].append("WAYPOINT_FOLLOWER_MISSING")
        return
    if "lifecycle_manager_waypoint_follower" not in launch_text:
        result["errors"].append("LIFECYCLE_MANAGER_WAYPOINT_FOLLOWER_MISSING")

    try:
        tree = ast.parse(launch_text, filename=str(LAUNCH_FILE))
    except SyntaxError:
        result["errors"].append("LAUNCH_FILE_SYNTAX_ERROR")
        return

    waypoint_follower_nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Node":
            package = executable = None
            for kw in node.keywords:
                if kw.arg == "package" and isinstance(kw.value, ast.Constant):
                    package = kw.value.value
                if kw.arg == "executable" and isinstance(kw.value, ast.Constant):
                    executable = kw.value.value
            if executable == "waypoint_follower":
                waypoint_follower_nodes.append((node, package))

    if not waypoint_follower_nodes:
        result["errors"].append("WAYPOINT_FOLLOWER_NODE_NOT_FOUND")
    elif len(waypoint_follower_nodes) > 1:
        result["errors"].append("WAYPOINT_FOLLOWER_DUPLICATE_NODE_DETECTED")
    else:
        wf_node, package = waypoint_follower_nodes[0]
        if package != "nav2_waypoint_follower":
            result["errors"].append("WAYPOINT_FOLLOWER_WRONG_PACKAGE")
        has_namespace = any(kw.arg == "namespace" for kw in wf_node.keywords)
        if not has_namespace:
            result["errors"].append("WAYPOINT_FOLLOWER_MISSING_NAMESPACE")
        for kw in wf_node.keywords:
            if kw.arg == "remappings":
                result["errors"].append("WAYPOINT_FOLLOWER_HAS_VELOCITY_REMAP")

    # node_names list for lifecycle_manager_waypoint_follower must contain
    # only waypoint_follower, isolated from every other lifecycle manager.
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
    waypoint_follower_only_lists = [
        names for names in node_names_lists if names == ["waypoint_follower"]
    ]
    if not waypoint_follower_only_lists:
        result["errors"].append("WAYPOINT_FOLLOWER_LIFECYCLE_MANAGER_NOT_ISOLATED")


def check_architecture_reconciliation_contract(result: dict) -> None:
    """Fase 2H.0: canonical navigation/hardware contract files (models.py,
    port.py, tour_orchestrator.py, main.py) must never reference
    BasicNavigator, /cmd_vel_nav, CMD_VEL_FILTERED_TOPIC, or import the
    legacy, quarantined src.hardware package. This is purely a file-content
    guard and does not start any process or touch the ROS graph.
    """
    for path in ARCHITECTURE_RECONCILIATION_FILES:
        result["checked_files"].append(str(path))
        if not path.is_file():
            result["errors"].append(f"ARCHITECTURE_FILE_MISSING:{path.name}")
            continue

        text = _read_text(path)
        for symbol in FORBIDDEN_ARCHITECTURE_SYMBOLS:
            if symbol in text:
                result["errors"].append(
                    f"ARCHITECTURE_FORBIDDEN_SYMBOL:{path.name}:{symbol}"
                )

        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            result["errors"].append(f"ARCHITECTURE_FILE_SYNTAX_ERROR:{path.name}")
            continue

        for node in ast.walk(tree):
            module_name = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == FORBIDDEN_ARCHITECTURE_IMPORT_PREFIX or alias.name.startswith(
                        FORBIDDEN_ARCHITECTURE_IMPORT_PREFIX + "."
                    ):
                        result["errors"].append(
                            f"ARCHITECTURE_FORBIDDEN_IMPORT:{path.name}:{alias.name}"
                        )
                continue
            if module_name is not None and (
                module_name == FORBIDDEN_ARCHITECTURE_IMPORT_PREFIX
                or module_name.startswith(FORBIDDEN_ARCHITECTURE_IMPORT_PREFIX + ".")
            ):
                result["errors"].append(
                    f"ARCHITECTURE_FORBIDDEN_IMPORT:{path.name}:{module_name}"
                )

def check_direct_nav2_action_bridge_contract(result: dict, files: list[Path]) -> None:
    bridge_files = [DIRECT_NAV2_ACTION_BRIDGE_FILE]
    for path in bridge_files:
        if path not in files or not path.is_file():
            continue
        text = _read_text(path)
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            result["errors"].append(f"DIRECT_BRIDGE_SYNTAX_ERROR:{path.name}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "hardware" in alias.name or "nav2_simple_commander" in alias.name:
                        result["errors"].append(f"DIRECT_BRIDGE_FORBIDDEN_IMPORT:{path.name}:{alias.name}")
                    if "Twist" in alias.name:
                        result["errors"].append(f"DIRECT_BRIDGE_FORBIDDEN_IMPORT:{path.name}:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if "hardware" in mod or "nav2_simple_commander" in mod:
                    result["errors"].append(f"DIRECT_BRIDGE_FORBIDDEN_IMPORT:{path.name}:{mod}")
                for alias in node.names:
                    if alias.name in ("BasicNavigator", "Twist", "nav2_simple_commander"):
                        result["errors"].append(f"DIRECT_BRIDGE_FORBIDDEN_IMPORT:{path.name}:{alias.name}")
            elif isinstance(node, ast.Call):
                func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if func_name == "create_subscription":
                    result["errors"].append(f"DIRECT_BRIDGE_FORBIDDEN_CALL:{path.name}:create_subscription")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                for f_topic in ("/cmd_vel", "/cmd_vel_nav", "/offline_nav/cmd_vel_raw", "/offline_nav/cmd_vel_safe"):
                    if val == f_topic:
                        result["errors"].append(f"DIRECT_BRIDGE_FORBIDDEN_TOPIC:{path.name}:{val}")
            elif isinstance(node, ast.Name):
                if node.id in ("BasicNavigator", "Twist"):
                    result["errors"].append(f"DIRECT_BRIDGE_FORBIDDEN_NAME:{path.name}:{node.id}")


def _find_class_method(tree: ast.Module, class_name: str, method_name: str) -> Optional[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.AsyncFunctionDef, ast.FunctionDef)) and item.name == method_name:
                    return item
    return None


def check_direct_nav2_action_bridge_ownership_contract(result: dict, files: list[Path]) -> None:
    """Fase 2H.1.2: guards de ownership terminal/cancelacion/timeout.

    Impide regresar a los defectos confirmados en la auditoria de 49a998c:
    el monitor de resultado nunca debe llamar al metodo publico
    cancel_navigation() (eso lo haria esperarse a si mismo a traves de
    _active_result_task); debe existir un helper interno de solicitud de
    cancelacion separado; cancel_navigation() debe exigir terminal CANCELED
    (no solo registrar un warning); y no debe existir un
    'except ImportError: pass' que oculte una dependencia faltante.
    """
    if DIRECT_NAV2_ACTION_BRIDGE_FILE not in files or not DIRECT_NAV2_ACTION_BRIDGE_FILE.is_file():
        return

    text = _read_text(DIRECT_NAV2_ACTION_BRIDGE_FILE)
    try:
        tree = ast.parse(text, filename=str(DIRECT_NAV2_ACTION_BRIDGE_FILE))
    except SyntaxError:
        result["errors"].append("DIRECT_BRIDGE_OWNERSHIP_SYNTAX_ERROR")
        return

    class_name = "DirectNav2ActionBridge"

    monitor_method = _find_class_method(tree, class_name, "_result_monitor_task")
    if monitor_method is None:
        result["errors"].append("DIRECT_BRIDGE_MONITOR_METHOD_MISSING")
    else:
        for node in ast.walk(monitor_method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "cancel_navigation" and isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                    result["errors"].append("DIRECT_BRIDGE_MONITOR_CALLS_PUBLIC_CANCEL")

    cancel_helper = _find_class_method(tree, class_name, "_request_cancel_only")
    if cancel_helper is None:
        result["errors"].append("DIRECT_BRIDGE_CANCEL_HELPER_MISSING")
    else:
        # AST attribute-access check, not a raw text search: the docstring
        # legitimately documents this invariant by name ("nunca espera
        # _active_result_task"), which a substring search would misfire on.
        for node in ast.walk(cancel_helper):
            if isinstance(node, ast.Attribute) and node.attr == "_active_result_task":
                result["errors"].append("DIRECT_BRIDGE_CANCEL_HELPER_WAITS_ON_RESULT_TASK")
                break

    cancel_public = _find_class_method(tree, class_name, "cancel_navigation")
    if cancel_public is None:
        result["errors"].append("DIRECT_BRIDGE_PUBLIC_CANCEL_METHOD_MISSING")
    else:
        public_source = ast.get_source_segment(text, cancel_public) or ""
        if "CANCEL_TERMINAL_NOT_CANCELED" not in public_source:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_DOES_NOT_ENFORCE_CANCELED_TERMINAL")
        if "raise RuntimeError" not in public_source and "raise TimeoutError" not in public_source:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_DOES_NOT_RAISE_ON_NON_TERMINAL")

        # 2H.1.4: a CancelGoal acceptance is evidence the server *received*
        # the request, never evidence the goal actually reached CANCELED.
        # Without a result task to observe the real GoalStatus, the method
        # must raise CANCEL_TERMINAL_UNOBSERVABLE and preserve
        # remote_state_unknown -- never fall through to an implicit,
        # successful return that asserts an unobserved cancellation.
        if "CANCEL_TERMINAL_UNOBSERVABLE" not in public_source:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_MISSING_UNOBSERVABLE_GUARD")
        if "remote_state_unknown" not in public_source:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_DOES_NOT_PRESERVE_REMOTE_STATE_UNKNOWN")

        has_explicit_none_check = False
        has_bare_truthy_check_without_else = False
        for node in ast.walk(cancel_public):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "res_task"
                and any(isinstance(op, (ast.Is, ast.IsNot)) for op in test.ops)
                and test.comparators
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
            ):
                has_explicit_none_check = True
            elif (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "res_task"
            ):
                has_explicit_none_check = True
            elif isinstance(test, ast.Name) and test.id == "res_task" and not node.orelse:
                has_bare_truthy_check_without_else = True

        if not has_explicit_none_check:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_NO_EXPLICIT_RES_TASK_NONE_CHECK")
        if has_bare_truthy_check_without_else and not has_explicit_none_check:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_IMPLICIT_RETURN_WHEN_RES_TASK_NONE")

        # 2H.1.5: task_active=True with no goal_handle means CancelGoal was
        # never even sendable -- there is nothing to request and nothing to
        # observe. The method must not fall through to a silent return (the
        # exact defect of the combined `if not goal_handle or not
        # task_active: return` guard, which conflates "no navigation active"
        # with "navigation active but unreachable"); it must raise
        # CANCEL_GOAL_HANDLE_UNAVAILABLE and mark remote_state_unknown.
        if "CANCEL_GOAL_HANDLE_UNAVAILABLE" not in public_source:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_MISSING_HANDLE_UNAVAILABLE_GUARD")

        has_task_active_only_silent_return = False
        has_goal_handle_none_check_with_raise = False
        has_combined_or_guard_with_silent_return = False
        for node in ast.walk(cancel_public):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            body_is_silent_return = (
                len(node.body) == 1
                and isinstance(node.body[0], ast.Return)
                and node.body[0].value is None
            )
            body_has_raise = any(isinstance(n, ast.Raise) for n in node.body)

            is_task_active_false_test = (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "task_active"
            )
            if is_task_active_false_test and body_is_silent_return:
                has_task_active_only_silent_return = True

            is_goal_handle_none_test = (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "goal_handle"
                and any(isinstance(op, ast.Is) for op in test.ops)
                and test.comparators
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
            ) or (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "goal_handle"
            )
            if is_goal_handle_none_test and body_has_raise:
                has_goal_handle_none_check_with_raise = True

            if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
                negated_names = set()
                for value in test.values:
                    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
                        operand = value.operand
                        if isinstance(operand, ast.Name):
                            negated_names.add(operand.id)
                        elif isinstance(operand, ast.Attribute):
                            negated_names.add(operand.attr)
                if "goal_handle" in negated_names and body_is_silent_return:
                    has_combined_or_guard_with_silent_return = True

        if not has_task_active_only_silent_return:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_NO_STANDALONE_TASK_ACTIVE_CHECK")
        if not has_goal_handle_none_check_with_raise:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_NO_EXPLICIT_GOAL_HANDLE_NONE_CHECK")
        if has_combined_or_guard_with_silent_return:
            result["errors"].append("DIRECT_BRIDGE_CANCEL_COMBINED_GUARD_RETURNS_SILENTLY")

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            is_import_error = (
                isinstance(node.type, ast.Name) and node.type.id == "ImportError"
            )
            body_is_only_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
            if is_import_error and body_is_only_pass:
                result["errors"].append("DIRECT_BRIDGE_SILENT_IMPORT_ERROR")


NAVIGATION_SETTINGS_FILE = CODE_ROOT / "config" / "settings.py"
ROUTER_FILE = CODE_ROOT / "api" / "router.py"
NAVIGATION_SELECTION_TEST_FILE = (
    CODE_ROOT / "tests" / "unit" / "test_navigation_runtime_selection.py"
)
CENTRAL_TEST_CLASSES_2H21 = frozenset({
    "NavigationBridgeFactoryTests",
    "FailClosedOrderTests",
    "LifespanDirectBackendTests",
    "ReadinessTests",
    "StatusObservabilityTests",
})

MAIN_NAVIGATION_REQUIRED_FUNCTIONS = (
    "_resolve_navigation_backend",
    "_check_direct_real_interlock",
    "_build_navigation_bridge",
)


def check_navigation_backend_selector_contract(result: dict) -> None:
    """Fase 2H.2: Settings debe declarar un selector explicito de backend
    (auto|legacy|direct|stub) y el interlock de hardware real debe estar
    cerrado por defecto. Guard de texto sobre config/settings.py: no
    requiere instanciar Settings ni ROS.
    """
    result["checked_files"].append(str(NAVIGATION_SETTINGS_FILE))
    if not NAVIGATION_SETTINGS_FILE.is_file():
        result["errors"].append("NAVIGATION_SETTINGS_FILE_MISSING")
        return

    text = _read_text(NAVIGATION_SETTINGS_FILE)
    if 'NAVIGATION_BACKEND: Literal["auto", "legacy", "direct", "stub"]' not in text:
        result["errors"].append("NAVIGATION_BACKEND_SELECTOR_NOT_EXPLICIT")
    if "NAVIGATION_DIRECT_REAL_ENABLED: bool = False" not in text:
        result["errors"].append("NAVIGATION_DIRECT_REAL_INTERLOCK_NOT_CLOSED_BY_DEFAULT")
    if "NAVIGATION_ALLOW_STUB_TOURS: bool = False" not in text:
        result["errors"].append("NAVIGATION_ALLOW_STUB_TOURS_NOT_CLOSED_BY_DEFAULT")


def check_main_runtime_navigation_selection_contract(result: dict) -> None:
    """Fase 2H.2: main.py debe resolver el backend de navegacion via
    helpers explicitos, fail-closed, sin fallback silencioso a stub, y sin
    imports ROS/bridge a nivel de modulo (deben permanecer lazy, dentro de
    las funciones que efectivamente necesitan el backend resuelto).
    """
    result["checked_files"].append(str(ARCHITECTURE_MAIN_FILE))
    if not ARCHITECTURE_MAIN_FILE.is_file():
        result["errors"].append("MAIN_NAVIGATION_FILE_MISSING")
        return

    text = _read_text(ARCHITECTURE_MAIN_FILE)
    try:
        tree = ast.parse(text, filename=str(ARCHITECTURE_MAIN_FILE))
    except SyntaxError:
        result["errors"].append("MAIN_NAVIGATION_SYNTAX_ERROR")
        return

    top_level_funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for fn_name in MAIN_NAVIGATION_REQUIRED_FUNCTIONS:
        if fn_name not in top_level_funcs:
            result["errors"].append(f"MAIN_NAVIGATION_FUNCTION_MISSING:{fn_name}")

    resolve_fn = top_level_funcs.get("_resolve_navigation_backend")
    if resolve_fn is not None:
        resolve_source = ast.get_source_segment(text, resolve_fn) or ""
        if '"legacy"' not in resolve_source or '"stub"' not in resolve_source:
            result["errors"].append("MAIN_NAVIGATION_AUTO_MATRIX_INCOMPLETE")
        if "NAVIGATION_STUB_FORBIDDEN_IN_REAL_MODE" not in resolve_source:
            result["errors"].append("MAIN_NAVIGATION_STUB_REAL_NOT_FORBIDDEN")

    interlock_fn = top_level_funcs.get("_check_direct_real_interlock")
    if interlock_fn is not None:
        interlock_source = ast.get_source_segment(text, interlock_fn) or ""
        if "DIRECT_NAVIGATION_REAL_MODE_NOT_AUTHORIZED" not in interlock_source:
            result["errors"].append("MAIN_NAVIGATION_INTERLOCK_MISSING_ERROR")
        if "NAVIGATION_DIRECT_REAL_ENABLED" not in interlock_source:
            result["errors"].append("MAIN_NAVIGATION_INTERLOCK_MISSING_LATCH_CHECK")

    build_fn = top_level_funcs.get("_build_navigation_bridge")
    if build_fn is not None:
        build_source = ast.get_source_segment(text, build_fn) or ""
        if "NAVIGATION_BACKEND_BUILD_FAILED" not in build_source:
            result["errors"].append("MAIN_NAVIGATION_BUILD_NOT_FAIL_CLOSED")

        for required_kw in (
            "node_name=settings.",
            "namespace=settings.",
            "navigate_to_pose_action=settings.",
            "follow_waypoints_action=settings.",
            "initial_pose_topic=settings.",
            "server_timeout_s=settings.",
            "goal_response_timeout_s=settings.",
            "result_timeout_s=settings.",
            "cancel_response_timeout_s=settings.",
            "cancel_terminal_timeout_s=settings.",
        ):
            if required_kw not in build_source:
                result["errors"].append(
                    f"MAIN_NAVIGATION_DIRECT_BRIDGE_NOT_CONFIGURABLE:{required_kw}"
                )

        # The literal pre-2H.2 defect: any broad except clause inside the
        # factory that constructs _MinimalNavStub() as a silent fallback
        # for a DIFFERENT requested backend (legacy/direct), instead of
        # propagating NAVIGATION_BACKEND_BUILD_FAILED.
        for node in ast.walk(build_fn):
            if not isinstance(node, ast.ExceptHandler):
                continue
            is_broad_except = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            )
            if not is_broad_except:
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "_MinimalNavStub"
                ):
                    result["errors"].append("MAIN_NAVIGATION_SILENT_STUB_FALLBACK")

    # Lazy ROS/bridge imports: rclpy and the two concrete bridge classes
    # must never be imported at module scope in main.py.
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "rclpy" or alias.name.startswith("rclpy."):
                    result["errors"].append("MAIN_NAVIGATION_EAGER_ROS_IMPORT:rclpy")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "rclpy" or mod.startswith("rclpy."):
                result["errors"].append("MAIN_NAVIGATION_EAGER_ROS_IMPORT:rclpy")
            if mod in (
                "src.navigation",
                "src.navigation.nav2_bridge",
                "src.navigation.direct_nav2_action_bridge",
            ):
                for alias in node.names:
                    if alias.name in ("AsyncNav2Bridge", "DirectNav2ActionBridge"):
                        result["errors"].append(
                            f"MAIN_NAVIGATION_EAGER_BRIDGE_IMPORT:{alias.name}"
                        )

    if "/cmd_vel" in text:
        result["errors"].append("MAIN_NAVIGATION_FORBIDDEN_CMD_VEL_LITERAL")

    # Phase 2H.2.1: uvicorn and fastapi must also never be imported at
    # module scope in main.py (they belong inside create_app / lifespan only).
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("uvicorn", "fastapi") or alias.name.startswith("fastapi."):
                    result["errors"].append(
                        f"MAIN_NAVIGATION_EAGER_MODULE_IMPORT:{alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "fastapi" or mod.startswith("fastapi."):
                result["errors"].append("MAIN_NAVIGATION_EAGER_MODULE_IMPORT:fastapi")


def check_readiness_fail_closed_missing_status_contract(result: dict) -> None:
    """Fase 2H.2.1: _resolve_readiness_errors() en api/router.py debe bloquear
    tours cuando get_status esta ausente o no es callable, emitiendo el error
    literal 'navigation status unavailable:missing'.
    """
    result["checked_files"].append(str(ROUTER_FILE))
    if not ROUTER_FILE.is_file():
        result["errors"].append("ROUTER_FILE_MISSING")
        return
    text = _read_text(ROUTER_FILE)
    if "navigation status unavailable:missing" not in text:
        result["errors"].append("READINESS_MISSING_GET_STATUS_NOT_BLOCKED")


def check_test_central_classes_no_broad_skip(result: dict) -> None:
    """Fase 2H.2.1: las clases de test centrales (que no ejercitan el modelo
    real de Pydantic Settings) no deben tener @skipUnless ni @skipIf.
    Solo NavigationConfigValidationTests puede conservar un skip condicional.
    """
    result["checked_files"].append(str(NAVIGATION_SELECTION_TEST_FILE))
    if not NAVIGATION_SELECTION_TEST_FILE.is_file():
        result["errors"].append("NAVIGATION_SELECTION_TEST_FILE_MISSING")
        return
    text = _read_text(NAVIGATION_SELECTION_TEST_FILE)
    try:
        tree = ast.parse(text, filename=str(NAVIGATION_SELECTION_TEST_FILE))
    except SyntaxError:
        result["errors"].append("NAVIGATION_SELECTION_TEST_SYNTAX_ERROR")
        return
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name not in CENTRAL_TEST_CLASSES_2H21:
            continue
        for deco in node.decorator_list:
            deco_src = ast.get_source_segment(text, deco) or ""
            if "skipUnless" in deco_src or "skipIf" in deco_src:
                result["errors"].append(
                    f"CENTRAL_TEST_CLASS_HAS_BROAD_SKIP:{node.name}"
                )


def check_direct_nav2_action_bridge_close_degraded_contract(result: dict, files: list[Path]) -> None:
    """Fase 2H.1.3: _cleanup() debe detectar degradacion ya existente al
    entrar (remote_state_unknown en True, o task_active=True sin un goal
    handle -- p.ej. tras un goal-response timeout, que nunca crea un
    result task que pudiera reportar el fallo por su cuenta) ANTES de
    los intentos reactivos de cancelacion/espera de terminal, no solo a
    partir de fallos de esos intentos.
    """
    if DIRECT_NAV2_ACTION_BRIDGE_FILE not in files or not DIRECT_NAV2_ACTION_BRIDGE_FILE.is_file():
        return

    text = _read_text(DIRECT_NAV2_ACTION_BRIDGE_FILE)
    try:
        tree = ast.parse(text, filename=str(DIRECT_NAV2_ACTION_BRIDGE_FILE))
    except SyntaxError:
        result["errors"].append("DIRECT_BRIDGE_CLOSE_DEGRADED_SYNTAX_ERROR")
        return

    cleanup_method = _find_class_method(tree, "DirectNav2ActionBridge", "_cleanup")
    if cleanup_method is None:
        result["errors"].append("DIRECT_BRIDGE_CLEANUP_METHOD_MISSING")
        return

    first_try_index = None
    for idx, stmt in enumerate(cleanup_method.body):
        if isinstance(stmt, ast.Try):
            first_try_index = idx
            break

    pre_try_statements = (
        cleanup_method.body if first_try_index is None else cleanup_method.body[:first_try_index]
    )
    pre_try_source = "\n".join(ast.get_source_segment(text, s) or "" for s in pre_try_statements)

    if "remote_state_unknown" not in pre_try_source:
        result["errors"].append("DIRECT_BRIDGE_CLOSE_DOES_NOT_CHECK_PREEXISTING_DEGRADED_STATE")
    if "task_active" not in pre_try_source:
        result["errors"].append("DIRECT_BRIDGE_CLOSE_DOES_NOT_CHECK_DANGLING_TASK_ACTIVE")


def check_direct_nav2_action_bridge_smoke_hardening_contract(result: dict, files: list[Path]) -> None:
    """Fase 2H.1.3: guards contra regresiones puntuales del smoke runtime:
    cleanup del bridge silenciado, aceptacion de REJECTED en el escenario
    inalcanzable, ruta de salida de hijo sin token unico, thread del
    observer unido sin comprobacion posterior, y pgid potencialmente sin
    inicializar en la limpieza de process group.
    """
    if DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE not in files or not DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE.is_file():
        return

    text = _read_text(DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE)
    try:
        tree = ast.parse(text, filename=str(DIRECT_NAV2_ACTION_BRIDGE_SMOKE_TEST_FILE))
    except SyntaxError:
        result["errors"].append("SMOKE_HARDENING_SYNTAX_ERROR")
        return

    # 1. No bare 'except ...: pass' wrapping a bridge.close() call.
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            body_calls_bridge_close = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "close"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "bridge"
                for stmt in node.body
                for n in ast.walk(stmt)
            )
            if body_calls_bridge_close:
                for handler in node.handlers:
                    if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                        result["errors"].append("SMOKE_BRIDGE_CLOSE_EXCEPTION_SILENCED")

    # 2. fw_unreachable must never treat REJECTED as equivalent to ABORTED.
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, ast.In) and isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                    attr_names = {
                        elt.attr for elt in comparator.elts if isinstance(elt, ast.Attribute)
                    }
                    if "REJECTED" in attr_names and "ABORTED" in attr_names:
                        result["errors"].append("SMOKE_FW_UNREACHABLE_ACCEPTS_REJECTED")

    # 3. Child output paths must carry a uniqueness token (time_ns() or uuid4()).
    def _is_uniqueness_call(node):
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("time_ns", "uuid4"):
            return True
        if isinstance(func, ast.Name) and func.id == "uuid4":
            return True
        return False

    if not any(_is_uniqueness_call(n) for n in ast.walk(tree)):
        result["errors"].append("SMOKE_CHILD_OUTPUT_PATH_NOT_UNIQUE")

    # 4. Observer thread must be checked again after join(), not just before.
    shutdown_method = _find_class_method(tree, "TelemetryObserver", "shutdown")
    if shutdown_method is None:
        result["errors"].append("SMOKE_OBSERVER_SHUTDOWN_METHOD_MISSING")
    else:
        is_alive_count = sum(
            1 for n in ast.walk(shutdown_method)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "is_alive"
        )
        join_count = sum(
            1 for n in ast.walk(shutdown_method)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "join"
        )
        if join_count == 0:
            result["errors"].append("SMOKE_OBSERVER_SHUTDOWN_NEVER_JOINS_THREAD")
        elif is_alive_count < 2:
            result["errors"].append("SMOKE_OBSERVER_THREAD_JOINED_WITHOUT_POST_CHECK")

    # 5. pgid must be initialized before any use in _shutdown_and_count_orphans.
    orphans_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_shutdown_and_count_orphans":
            orphans_fn = node
            break
    if orphans_fn is None:
        result["errors"].append("SMOKE_ORPHAN_CLEANUP_FUNCTION_MISSING")
    else:
        has_none_init = False
        for stmt in orphans_fn.body:
            targets = None
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            if targets is None:
                continue
            if isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
                if any(isinstance(t, ast.Name) and t.id == "pgid" for t in targets):
                    has_none_init = True
                    break
        if not has_none_init:
            result["errors"].append("SMOKE_PGID_POTENTIALLY_UNINITIALIZED")


MAIN_RUNTIME_TIMEOUT_CLEANUP_TEST_FILE = (
    CODE_ROOT / "tests" / "unit" / "test_main_runtime_timeout_cleanup.py"
)
PARENT_CLI_TIMEOUT_TEST_FILE = CODE_ROOT / "tests" / "unit" / "test_2h24_parent_cli_timeout.py"
PARENT_CLI_TIMEOUT_DRIVER_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "run_2h24_parent_cli_timeout.py"
)

P0_DIR = CODE_ROOT / "tools" / "hil" / "physical_read_only"
P0_COLLECTOR_CORE_FILE = P0_DIR / "collect_p0_readonly_evidence.py"
P0_SCHEMA_FILE = P0_DIR / "p0_evidence_schema.py"
P0_VALIDATOR_FILE = P0_DIR / "validate_p0_readonly_evidence.py"
P0_WRAPPER_FILE = P0_DIR / "collect_p0_readonly_evidence.sh"
P0_CONTRACT_TEST_FILE = CODE_ROOT / "tests" / "unit" / "test_p0_readonly_evidence_contract.py"
P0_E2E_TEST_FILE = CODE_ROOT / "tests" / "unit" / "test_p0_readonly_pipeline_e2e.py"


def check_main_runtime_cleanup_lease_contract(result: dict, files: list[Path]) -> None:
    """Fase 2H.2.2: regression guards for the process-group isolation and
    cleanup-lease hardening of smoke_test_main_runtime_navigation_selection.py.

    Detects the literal regressions named by the phase: a child or sandbox
    Popen call without start_new_session=True, any remaining
    preexec_fn=os.setsid usage, absence of lease validation / a random
    token / protected-PGID rejection / start_ticks capture / child wait, and
    absence of explicit thread/zombie/orphan gates. Uses AST rather than
    bare string search wherever a call shape needs to be distinguished from
    incidental text (e.g. a docstring mentioning these terms).
    """
    target = MAIN_RUNTIME_NAVIGATION_SELECTION_SMOKE_TEST_FILE
    if target not in files or not target.is_file():
        return

    text = _read_text(target)
    try:
        tree = ast.parse(text, filename=str(target))
    except SyntaxError:
        result["errors"].append("MAIN_RUNTIME_CLEANUP_SYNTAX_ERROR")
        return

    popen_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "Popen")
            or (isinstance(node.func, ast.Name) and node.func.id == "Popen")
        )
    ]
    if not popen_calls:
        result["errors"].append("MAIN_RUNTIME_CLEANUP_NO_POPEN_CALLS_FOUND")
    for call in popen_calls:
        kwarg_names = {kw.arg for kw in call.keywords if kw.arg is not None}
        if "preexec_fn" in kwarg_names:
            result["errors"].append("MAIN_RUNTIME_CLEANUP_PREEXEC_FN_USED")
        if "start_new_session" not in kwarg_names:
            # spawn_isolated() is the only sanctioned wrapper around Popen;
            # any direct Popen(...) call in this file must pass the kwarg
            # itself (spawn_isolated's own call does).
            result["errors"].append("MAIN_RUNTIME_CLEANUP_POPEN_WITHOUT_OWN_SESSION")

    required_symbols = (
        ("secrets.token_hex", "MAIN_RUNTIME_CLEANUP_NO_RANDOM_TOKEN"),
        ("is_protected_id", "MAIN_RUNTIME_CLEANUP_NO_PROTECTED_ID_REJECTION"),
        ("start_ticks", "MAIN_RUNTIME_CLEANUP_NO_START_TICKS"),
        ("LEASE_VALIDATION_FAILED", "MAIN_RUNTIME_CLEANUP_NO_LEASE_VALIDATION_FAILURE_MARKER"),
        ("validate_lease_immutable_fields", "MAIN_RUNTIME_CLEANUP_NO_LEASE_VALIDATION_FUNCTION"),
        ("OWNED_THREADS_REMAINING", "MAIN_RUNTIME_CLEANUP_NO_THREAD_GATE"),
        ("ZOMBIES_REMAINING", "MAIN_RUNTIME_CLEANUP_NO_ZOMBIE_GATE"),
        ("ORPHAN_PROCESSES", "MAIN_RUNTIME_CLEANUP_NO_ORPHAN_GATE"),
    )
    for symbol, error_code in required_symbols:
        if symbol not in text:
            result["errors"].append(error_code)

    # Child must be wait()ed on (reaped) somewhere in the cleanup path.
    has_child_wait = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "wait"
        for node in ast.walk(tree)
    )
    if not has_child_wait:
        result["errors"].append("MAIN_RUNTIME_CLEANUP_NO_CHILD_WAIT")

    if not MAIN_RUNTIME_TIMEOUT_CLEANUP_TEST_FILE.is_file():
        result["errors"].append("MAIN_RUNTIME_CLEANUP_TEST_FILE_MISSING")


def check_2h24_toctou_fix_contract(result: dict, files: list[Path]) -> None:
    """Fase 2H.2.4: the pre-2H.2.4 member re-validation defect was a
    two-read pattern -- identity_still_valid(member) (one kernel read)
    *and* read_process_identity(pid).pgid (a second, independent read,
    unguarded against None) -- in _authorized_targets()'s member fallback
    path. Detects both that the literal buggy expression never
    reappears, and that the single-snapshot replacement helper exists and
    is what _authorized_targets() actually calls.
    """
    target = MAIN_RUNTIME_NAVIGATION_SELECTION_SMOKE_TEST_FILE
    if target not in files or not target.is_file():
        return
    text = _read_text(target)
    try:
        tree = ast.parse(text, filename=str(target))
    except SyntaxError:
        result["errors"].append("TOCTOU_FIX_SYNTAX_ERROR")
        return

    # AST-level, not substring/regex: the fix's own docstring quotes the old
    # buggy expression in prose (documenting what it replaced), which a raw
    # text search would misfire on. Real code matches an ast.Attribute
    # (attr="pgid") whose value is a Call to read_process_identity(...);
    # text inside a docstring/string literal never produces such nodes.
    has_double_read_pattern = any(
        isinstance(node, ast.Attribute)
        and node.attr == "pgid"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "read_process_identity"
        for node in ast.walk(tree)
    )
    if has_double_read_pattern:
        result["errors"].append("TOCTOU_DOUBLE_READ_PATTERN_PRESENT")

    func_by_name = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    if "_revalidate_identity_for_group_signal" not in func_by_name:
        result["errors"].append("TOCTOU_FIX_HELPER_MISSING")

    authorized_targets = func_by_name.get("_authorized_targets")
    if authorized_targets is None:
        result["errors"].append("TOCTOU_FIX_AUTHORIZED_TARGETS_MISSING")
    else:
        calls_helper = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_revalidate_identity_for_group_signal"
            for n in ast.walk(authorized_targets)
        )
        if not calls_helper:
            result["errors"].append("TOCTOU_FIX_AUTHORIZED_TARGETS_NOT_USING_HELPER")
        uses_stale_validator = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "identity_still_valid"
            for n in ast.walk(authorized_targets)
        )
        if uses_stale_validator:
            result["errors"].append("TOCTOU_FIX_AUTHORIZED_TARGETS_STILL_USES_STALE_PATTERN")

    if "OTTOGUIDE_2H24_FAULT_INJECTION" not in text:
        result["errors"].append("TOCTOU_FIX_NO_FAULT_INJECTION_ENV_GUARD")
    if "fault_inject_hang_sandbox" not in text:
        result["errors"].append("TOCTOU_FIX_NO_HIDDEN_FAULT_FLAG")
    if "help=argparse.SUPPRESS" not in text:
        result["errors"].append("TOCTOU_FIX_FAULT_FLAG_NOT_HIDDEN")

    if not PARENT_CLI_TIMEOUT_TEST_FILE.is_file():
        result["errors"].append("PARENT_CLI_TIMEOUT_TEST_FILE_MISSING")
    if not PARENT_CLI_TIMEOUT_DRIVER_FILE.is_file():
        result["errors"].append("PARENT_CLI_TIMEOUT_DRIVER_FILE_MISSING")


def check_p0_pipeline_functional_contract(result: dict) -> None:
    """Fase 2H.2.4: the P0 read-only evidence pipeline must be a real,
    functional collector -> bundle -> manifest -> validator chain, not
    the 2H.2.3 skeleton (a shell script that only printed/discarded
    commands, validated against a validator that required only three of
    the seven files). Static, source-level guards only -- never executes
    the collector or validator.
    """
    if not P0_COLLECTOR_CORE_FILE.is_file():
        result["errors"].append("P0_COLLECTOR_CORE_MISSING")
        return
    if not P0_SCHEMA_FILE.is_file():
        result["errors"].append("P0_SCHEMA_MODULE_MISSING")
    if not P0_E2E_TEST_FILE.is_file():
        result["errors"].append("P0_E2E_TEST_FILE_MISSING")
    if not P0_CONTRACT_TEST_FILE.is_file():
        result["errors"].append("P0_CONTRACT_TEST_FILE_MISSING")

    collector_text = _read_text(P0_COLLECTOR_CORE_FILE)
    try:
        collector_tree = ast.parse(collector_text, filename=str(P0_COLLECTOR_CORE_FILE))
    except SyntaxError:
        result["errors"].append("P0_COLLECTOR_SYNTAX_ERROR")
        return

    # AST-level, not substring: the collector's own docstring legitimately
    # discusses "shell=True" as something it does NOT do.
    for node in ast.walk(collector_tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
                result["errors"].append("P0_COLLECTOR_USES_SHELL")
            if isinstance(node.func, ast.Name) and node.func.id == "eval":
                result["errors"].append("P0_COLLECTOR_USES_EVAL")
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    result["errors"].append("P0_COLLECTOR_USES_SHELL")

    required_symbols = (
        ("def build_bundle", "P0_COLLECTOR_NO_BUILD_BUNDLE"),
        ("def write_bundle", "P0_COLLECTOR_NO_WRITE_BUNDLE"),
        ("def resolve_mode", "P0_COLLECTOR_NO_MODE_RESOLUTION"),
        ("MODE_CONFLICT", "P0_COLLECTOR_NO_MODE_CONFLICT_GUARD"),
        ("FIXTURE_MODE_NOT_AUTHORIZED", "P0_COLLECTOR_NO_FIXTURE_GUARD"),
        ("P0_NOT_AUTHORIZED", "P0_COLLECTOR_NO_REAL_MODE_GUARD"),
        ("dry_run", "P0_COLLECTOR_NO_DRY_RUN_MODE"),
    )
    for symbol, code in required_symbols:
        if symbol not in collector_text:
            result["errors"].append(code)

    forbidden_movement_literals = (
        "send_goal", "topic\", \"pub", "service\", \"call", "lifecycle\", \"set", "ros2\", \"launch",
    )
    for needle in forbidden_movement_literals:
        if needle in collector_text:
            result["errors"].append(f"P0_COLLECTOR_FORBIDDEN_MOVEMENT_PRIMITIVE:{needle}")

    if P0_SCHEMA_FILE.is_file():
        schema_text = _read_text(P0_SCHEMA_FILE)
        for fname in (
            "p0_session_meta.json", "p0_ros_graph.json", "p0_tf_and_localization.json",
            "p0_sensors.json", "p0_cmd_vel_chain.json", "p0_safety_human_checklist.json",
            "p0_command_log.json", "p0_hash_manifest.json",
        ):
            if fname not in schema_text:
                result["errors"].append(f"P0_SCHEMA_MISSING_FILENAME:{fname}")
        for symbol, code in (
            ("MUST_BE_FALSE_FIELDS", "P0_SCHEMA_NO_READONLY_INVARIANTS"),
            ("SAFETY_REQUIRED_TRUE_FOR_GO", "P0_SCHEMA_NO_HUMAN_SAFETY_GATES"),
            ("atomic_write_json", "P0_SCHEMA_NO_ATOMIC_WRITE"),
            ("ensure_safe_output_dir", "P0_SCHEMA_NO_SAFE_DIR_GUARD"),
        ):
            if symbol not in schema_text:
                result["errors"].append(code)

    if not P0_VALIDATOR_FILE.is_file():
        result["errors"].append("P0_VALIDATOR_MISSING")
    else:
        validator_text = _read_text(P0_VALIDATOR_FILE)
        for symbol, code in (
            ("expected_head", "P0_VALIDATOR_NO_EXPECTED_HEAD_PARAM"),
            ("SAFETY_REQUIRED_TRUE_FOR_GO", "P0_VALIDATOR_NO_HUMAN_SAFETY_GATE"),
            ("DECISION_FIXTURE_ONLY", "P0_VALIDATOR_NO_FIXTURE_ONLY_DECISION"),
            ("DECISION_GO_CANDIDATE", "P0_VALIDATOR_NO_GO_CANDIDATE_DECISION"),
            ("bundle_integrity", "P0_VALIDATOR_NO_INTEGRITY_LAYER"),
            ("read_only_invariants", "P0_VALIDATOR_NO_READONLY_LAYER"),
            ("p0_field_decision", "P0_VALIDATOR_NO_FIELD_DECISION_LAYER"),
        ):
            if symbol not in validator_text:
                result["errors"].append(code)
        # A fixture bundle must never be able to reach GO_CANDIDATE: the
        # decision computation must gate DECISION_GO_CANDIDATE behind a
        # check that fixture_mode is falsy.
        if "fixture_mode" not in validator_text:
            result["errors"].append("P0_VALIDATOR_NO_FIXTURE_MODE_CHECK")

    if not P0_WRAPPER_FILE.is_file():
        result["errors"].append("P0_WRAPPER_MISSING")
    else:
        wrapper_text = _read_text(P0_WRAPPER_FILE)
        if "exec " not in wrapper_text:
            result["errors"].append("P0_WRAPPER_NOT_EXEC_BASED")
        if "--execute-read-only)" in wrapper_text or "--dry-run)" in wrapper_text:
            result["errors"].append("P0_WRAPPER_BRANCHES_ON_FLAGS")


def check_2h25_monotonic_lease_contract(result: dict) -> None:
    """Fase 2H.2.5: verify that the cleanup-lease v2 monotonic-timebase
    migration is present in the smoke test and covered by MonotonicLeaseTests.
    """
    target = MAIN_RUNTIME_NAVIGATION_SELECTION_SMOKE_TEST_FILE
    if not target.is_file():
        return
    text = _read_text(target)
    for symbol, code in (
        ("created_monotonic_ns", "LEASE_V2_NO_CREATED_MONOTONIC_NS"),
        ("updated_monotonic_ns", "LEASE_V2_NO_UPDATED_MONOTONIC_NS"),
        ("_lease_monotonic_ns", "LEASE_V2_NO_MONOTONIC_CLOCK_HELPER"),
        ("LEASE_MONOTONIC_TIMESTAMPS_MALFORMED", "LEASE_V2_NO_MALFORMED_ERROR_CODE"),
        ("LEASE_MONOTONIC_CREATED_IN_FUTURE", "LEASE_V2_NO_FUTURE_ERROR_CODE"),
        ("LEASE_MONOTONIC_UPDATED_BEFORE_CREATED", "LEASE_V2_NO_REGRESSION_ERROR_CODE"),
    ):
        if symbol not in text:
            result["errors"].append(code)

    if not MAIN_RUNTIME_TIMEOUT_CLEANUP_TEST_FILE.is_file():
        result["errors"].append("LEASE_V2_CLEANUP_TEST_FILE_MISSING")
    else:
        test_text = _read_text(MAIN_RUNTIME_TIMEOUT_CLEANUP_TEST_FILE)
        if "MonotonicLeaseTests" not in test_text:
            result["errors"].append("LEASE_V2_MONOTONIC_TEST_CLASS_MISSING")


def check_2h25_p0_decision_v2_contract(result: dict) -> None:
    """Fase 2H.2.5: verify that the P0 decision engine v2 additions are
    present: collection_completeness layer, physical_control_execution_performed
    in MUST_BE_FALSE_FIELDS, COLLECTOR_VERSION, and v2 contract test classes.
    """
    schema_text = _read_text(P0_SCHEMA_FILE) if P0_SCHEMA_FILE.is_file() else ""

    if P0_COLLECTOR_CORE_FILE.is_file():
        collector_text = _read_text(P0_COLLECTOR_CORE_FILE)
        # COLLECTOR_VERSION may be defined in p0_evidence_schema as a single
        # source of truth (Fase 2H.2.6); accept it in either file.
        if "COLLECTOR_VERSION" not in collector_text and "COLLECTOR_VERSION" not in schema_text:
            result["errors"].append("P0_V2_NO_COLLECTOR_VERSION")

    if P0_SCHEMA_FILE.is_file():
        if "physical_control_execution_performed" not in schema_text:
            result["errors"].append("P0_V2_MUST_BE_FALSE_MISSING_PHYSICAL_CONTROL_FIELD")
        if "SCHEMA_VERSION" not in schema_text:
            result["errors"].append("P0_V2_NO_SCHEMA_VERSION")

    if P0_VALIDATOR_FILE.is_file():
        validator_text = _read_text(P0_VALIDATOR_FILE)
        if "collection_completeness" not in validator_text:
            result["errors"].append("P0_V2_VALIDATOR_NO_COLLECTION_COMPLETENESS_LAYER")

    if P0_CONTRACT_TEST_FILE.is_file():
        contract_text = _read_text(P0_CONTRACT_TEST_FILE)
        if "TestV2BundleIntegrityContract" not in contract_text:
            result["errors"].append("P0_V2_CONTRACT_TEST_MISSING_V2_INTEGRITY_CLASS")
        if "TestV2FieldDecisionContract" not in contract_text:
            result["errors"].append("P0_V2_CONTRACT_TEST_MISSING_V2_FIELD_DECISION_CLASS")


def verify(runtime: bool = False) -> dict:
    result = {
        "ok": True,
        "decision": "PASS",
        "mode": "RUNTIME" if runtime else "STATIC",
        "errors": [],
        "warnings": [],
        "forbidden_matches": [],
        "checked_files": [],
    }

    files_to_scan = list(RUNTIME_SCAN_FILES) if runtime else [LAUNCH_FILE, PARAMS_FILE, MAP_YAML]

    check_map_default_versioned(result)
    check_forbidden_ip(result, files_to_scan)
    check_forbidden_topics(result, files_to_scan)
    check_velocity_topic_allowlist(result, files_to_scan)
    check_forbidden_bridges(result, files_to_scan)
    check_no_mission_components(result)
    check_namespace_offline(result)
    check_localhost_only_required(result, runtime=runtime)
    check_domain_id_required(result, runtime=runtime)
    check_no_physical_hal_import(result)
    check_collision_monitor_contract(result, files_to_scan)
    check_bt_navigator_contract(result)
    check_waypoint_follower_contract(result)
    check_architecture_reconciliation_contract(result)
    check_direct_nav2_action_bridge_contract(result, files_to_scan)
    check_direct_nav2_action_bridge_ownership_contract(result, files_to_scan)
    check_direct_nav2_action_bridge_close_degraded_contract(result, files_to_scan)
    check_direct_nav2_action_bridge_smoke_hardening_contract(result, files_to_scan)
    check_main_runtime_cleanup_lease_contract(result, files_to_scan)
    check_navigation_backend_selector_contract(result)
    check_main_runtime_navigation_selection_contract(result)
    check_readiness_fail_closed_missing_status_contract(result)
    check_test_central_classes_no_broad_skip(result)
    check_2h24_toctou_fix_contract(result, files_to_scan)
    check_p0_pipeline_functional_contract(result)
    check_2h25_monotonic_lease_contract(result)
    check_2h25_p0_decision_v2_contract(result)

    result["checked_files"] = sorted(set(result["checked_files"]) | {str(p) for p in files_to_scan if p.is_file()})
    result["errors"] = sorted(set(result["errors"]))
    result["warnings"] = sorted(set(result["warnings"]))

    if result["errors"]:
        result["ok"] = False
        result["decision"] = "FAIL"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help=(
            "Runtime isolation mode: ROS_LOCALHOST_ONLY!=1 and missing/zero "
            "ROS_DOMAIN_ID become errors instead of warnings, and the "
            "simulator and runtime wrapper files are also scanned."
        ),
    )
    args = parser.parse_args()

    result = verify(runtime=args.runtime)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
