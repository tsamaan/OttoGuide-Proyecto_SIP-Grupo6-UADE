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
from pathlib import Path

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
# executables/packages must never appear in the launch file.
FORBIDDEN_MISSION_COMPONENT_PATTERN = re.compile(
    r"bt_navigator|nav2_bt_navigator|waypoint_follower|nav2_waypoint_follower|"
    r"nav2_simple_commander|simple_commander"
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
]
EXPECTED_REAL_NAMESPACE = "offline_nav"

# Required ROS entities in the launch file: a Node call must carry a real
# namespace= kwarg, or (for ExecuteProcess-launched rclpy scripts) the cmd
# list must include a '-r' remap of '__ns:=/<namespace>'.
REQUIRED_NODE_NAMES = {
    "map_server",
    "planner_server",
    "controller_server",
    "collision_monitor",
    "behavior_server",
    "lifecycle_manager_navigation",
    "lifecycle_manager_controller",
    "lifecycle_manager_collision_monitor",
    "lifecycle_manager_behavior_server",
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
    """BT Navigator, Waypoint Follower and Simple Commander are explicitly
    out of scope for every phase implemented so far; the launch file must
    never reference them.
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
