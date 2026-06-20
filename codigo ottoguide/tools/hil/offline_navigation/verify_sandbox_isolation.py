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
FORBIDDEN_HAL_IMPORT_MODULES = {
    "unitree_sdk2py",
    "real_adapter",
    "src.hardware.real_adapter",
}

SIMULATOR_FILE = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "offline_runtime_simulator.py"
)
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"
RUNTIME_SCAN_FILES = [LAUNCH_FILE, PARAMS_FILE, MAP_YAML, SIMULATOR_FILE, RUNTIME_WRAPPER]
EXPECTED_REAL_NAMESPACE = "offline_nav"


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


def check_forbidden_topics(result: dict, files: list[Path]) -> None:
    for path in files:
        if not path.is_file():
            continue
        text = _strip_comment_lines(_read_text(path))
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


def check_namespace_offline(result: dict) -> None:
    """Require a *real* ROS namespace, not just the textual word 'offline'.

    A real namespace means a DeclareLaunchArgument named 'sandbox_namespace'
    whose default value is EXPECTED_REAL_NAMESPACE, and at least one Node(...)
    call in the launch file that passes namespace= using that argument.
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
    nodes_with_namespace_kwarg = 0

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
            for kw in node.keywords:
                if kw.arg == "namespace":
                    nodes_with_namespace_kwarg += 1

    if not has_namespace_arg_declaration:
        result["errors"].append("NO_SANDBOX_NAMESPACE_ARGUMENT_DECLARED")
    elif not has_namespace_arg_correct_default:
        result["errors"].append("SANDBOX_NAMESPACE_DEFAULT_NOT_OFFLINE_NAV")

    if nodes_with_namespace_kwarg == 0:
        result["errors"].append("NO_NODE_APPLIES_NAMESPACE_KWARG")


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
    check_forbidden_bridges(result, files_to_scan)
    check_namespace_offline(result)
    check_localhost_only_required(result, runtime=runtime)
    check_domain_id_required(result, runtime=runtime)
    check_no_physical_hal_import(result)

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
