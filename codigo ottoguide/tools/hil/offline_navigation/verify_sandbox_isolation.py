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

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            is_import_error = (
                isinstance(node.type, ast.Name) and node.type.id == "ImportError"
            )
            body_is_only_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
            if is_import_error and body_is_only_pass:
                result["errors"].append("DIRECT_BRIDGE_SILENT_IMPORT_ERROR")


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

    # 3. Child output paths must carry a uniqueness token (time_ns()).
    has_time_ns = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "time_ns"
        for n in ast.walk(tree)
    )
    if not has_time_ns:
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
