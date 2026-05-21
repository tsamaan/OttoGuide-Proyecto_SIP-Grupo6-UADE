#!/usr/bin/env python3
"""Static Livox SDK2 pre-robot checks.

This script does not start ROS 2, Livox SDK2, sensors, or robot control. It only
validates repo files that must be coherent before copying the tree to the G1.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
BRIDGE_DIR = PROJECT_ROOT / "ros2_ws/src/ottoguide_livox_sdk_bridge"
CONFIG_PATH = PROJECT_ROOT / "config/livox/mid360_sdk2_bridge.json"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fail(message: str, failures: List[str]) -> None:
    failures.append(message)
    print(f"[FAIL] {message}")


def ok(message: str) -> None:
    print(f"[OK]   {message}")


def require_contains(path: Path, pattern: str, description: str, failures: List[str]) -> None:
    text = read_text(path)
    if re.search(pattern, text, flags=re.MULTILINE):
        ok(description)
    else:
        fail(f"{description}: pattern not found in {path.relative_to(REPO_ROOT)}", failures)


def validate_config(failures: List[str]) -> None:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report exact static failure
        fail(f"Livox config JSON is invalid: {exc}", failures)
        return

    ok("Livox config JSON parses")
    host_info = config.get("MID360", {}).get("host_net_info", [{}])[0]
    lidar_info = config.get("MID360", {}).get("lidar_net_info", {})
    lidar_configs = config.get("lidar_configs", [{}])

    expected_ports = {
        "cmd_data_port": 56100,
        "push_msg_port": 56200,
        "point_data_port": 56300,
        "imu_data_port": 56400,
        "log_data_port": 56500,
    }
    expected_host_ports = {
        "cmd_data_port": 56101,
        "push_msg_port": 56201,
        "point_data_port": 56301,
        "imu_data_port": 56401,
        "log_data_port": 56501,
    }

    if host_info.get("host_ip") == "192.168.123.164":
        ok("Livox host IP is 192.168.123.164")
    else:
        fail("Livox host IP must be 192.168.123.164", failures)

    if lidar_configs and lidar_configs[0].get("ip") == "192.168.123.120":
        ok("Livox MID360 default IP is 192.168.123.120")
    else:
        fail("Livox MID360 default IP must be 192.168.123.120", failures)

    for key, expected in expected_ports.items():
        if lidar_info.get(key) != expected:
            fail(f"LiDAR port {key} must be {expected}", failures)
    for key, expected in expected_host_ports.items():
        if host_info.get(key) != expected:
            fail(f"Host port {key} must be {expected}", failures)
    if not failures:
        ok("Livox SDK2 ports match the documented MID360 defaults")


def validate_bridge_sources(failures: List[str]) -> None:
    cmake = BRIDGE_DIR / "CMakeLists.txt"
    node = BRIDGE_DIR / "src/livox_sdk_bridge_node.cpp"
    launch = BRIDGE_DIR / "launch/mid360_sdk2_bridge.launch.py"
    readme = BRIDGE_DIR / "README.md"

    for path in (cmake, node, launch, readme, BRIDGE_DIR / "package.xml"):
        if path.exists():
            ok(f"Found {path.relative_to(REPO_ROOT)}")
        else:
            fail(f"Missing {path.relative_to(REPO_ROOT)}", failures)

    require_contains(cmake, r"livox_lidar_api\.h", "CMake searches Livox SDK2 header", failures)
    require_contains(cmake, r"livox_lidar_sdk_shared", "CMake links Livox SDK2 shared library", failures)
    require_contains(cmake, r"install\(DIRECTORY launch", "CMake installs launch directory", failures)
    require_contains(node, r"livox_lidar_api\.h", "Node includes official Livox SDK2 API", failures)
    require_contains(node, r"std::memcpy", "Node copies SDK payloads before reading typed samples", failures)
    require_contains(node, r"packet_dot_count_is_safe", "Node guards Livox dot_num before payload parsing", failures)
    require_contains(node, r"max_points_per_packet", "Node exposes configurable max points per packet", failures)
    require_contains(node, r"debug_dry_run_no_publish", "Node exposes dry-run mode without ROS publishing", failures)
    require_contains(node, r"debug_disable_livox_sdk", "Node can disable Livox SDK2 for staged diagnosis", failures)
    require_contains(node, r"debug_disable_callbacks", "Node can disable SDK2 callbacks for staged diagnosis", failures)
    require_contains(
        node,
        r"debug_stage_stop_before_sdk_init",
        "Node can stop before SDK2 init",
        failures,
    )
    require_contains(
        node,
        r"debug_stage_stop_after_sdk_init",
        "Node can stop after SDK2 init",
        failures,
    )
    require_contains(
        node,
        r"debug_stage_stop_after_callbacks_registered",
        "Node can stop after callback registration",
        failures,
    )
    require_contains(
        node,
        r"debug_stage_stop_before_sdk_start",
        "Node can stop before SDK2 start",
        failures,
    )
    require_contains(
        node,
        r"debug_stage_stop_after_sdk_start",
        "Node can stop after SDK2 start",
        failures,
    )
    require_contains(node, r"MARK_040_SDK_INIT_START", "Node logs SDK2 init start marker", failures)
    require_contains(node, r"MARK_060_SDK_START_START", "Node logs SDK2 start marker", failures)
    require_contains(node, r"std::bad_alloc", "Node catches std::bad_alloc around packet handling", failures)
    require_contains(node, r"packet_timestamp_hex", "Node logs Livox packet timestamp diagnostics", failures)
    require_contains(node, r"publish_queued_messages", "Node publishes from ROS timer path", failures)
    require_contains(node, r'"/utlidar/cloud"', "Node default cloud topic is /utlidar/cloud", failures)
    require_contains(node, r'"/livox/imu"', "Node default IMU topic is /livox/imu", failures)
    require_contains(node, r'"utlidar_lidar"', "Node default frame_id is utlidar_lidar", failures)
    require_contains(launch, r"mid360_sdk2_bridge\.json", "Launch resolves MID360 SDK2 config", failures)
    require_contains(launch, r"max_points_per_packet", "Launch exposes max_points_per_packet", failures)
    require_contains(launch, r"debug_dry_run_no_publish", "Launch exposes debug_dry_run_no_publish", failures)
    require_contains(launch, r"debug_disable_livox_sdk", "Launch exposes debug_disable_livox_sdk", failures)
    require_contains(launch, r"debug_disable_callbacks", "Launch exposes debug_disable_callbacks", failures)
    require_contains(
        launch,
        r"debug_stage_stop_before_sdk_init",
        "Launch exposes staged stop before SDK2 init",
        failures,
    )
    require_contains(
        launch,
        r"debug_stage_stop_after_sdk_start",
        "Launch exposes staged stop after SDK2 start",
        failures,
    )
    require_contains(readme, r"Do not run.*livox_ros_driver2", "README warns against dual Livox drivers", failures)


def validate_hil_scripts(failures: List[str]) -> None:
    script_paths = [
        PROJECT_ROOT / "scripts/hil_start_mapping.sh",
        PROJECT_ROOT / "scripts/hil_start_navigation.sh",
        PROJECT_ROOT / "scripts/hil_capture_mapping_bundle.sh",
        PROJECT_ROOT / "scripts/hil_mapping_recorder.sh",
        PROJECT_ROOT / "scripts/preflight_sensors.sh",
    ]

    for path in script_paths:
        text = read_text(path)
        if "livox_ros_driver2" in text:
            fail(f"{path.relative_to(REPO_ROOT)} still references livox_ros_driver2", failures)
        else:
            ok(f"{path.relative_to(REPO_ROOT)} does not reference livox_ros_driver2")

    require_contains(
        PROJECT_ROOT / "scripts/hil_start_mapping.sh",
        r"ottoguide_livox_sdk_bridge",
        "Mapping script launches the OttoGuide SDK2 bridge",
        failures,
    )
    require_contains(
        PROJECT_ROOT / "scripts/hil_start_navigation.sh",
        r"ottoguide_livox_sdk_bridge",
        "Navigation script launches the OttoGuide SDK2 bridge",
        failures,
    )
    require_contains(
        PROJECT_ROOT / "scripts/hil_capture_mapping_bundle.sh",
        r'"/utlidar/cloud"',
        "Capture bundle waits for /utlidar/cloud",
        failures,
    )
    require_contains(
        PROJECT_ROOT / "scripts/hil_mapping_recorder.sh",
        r"/utlidar/cloud",
        "Recorder captures /utlidar/cloud",
        failures,
    )
    require_contains(
        PROJECT_ROOT / "scripts/preflight_sensors.sh",
        r'"/livox/imu"',
        "Preflight validates /livox/imu",
        failures,
    )


def main() -> int:
    failures: List[str] = []
    validate_config(failures)
    validate_bridge_sources(failures)
    validate_hil_scripts(failures)

    if failures:
        print(f"\n[RESULT] Livox SDK2 static validation failed: {len(failures)} issue(s)")
        return 1

    print("\n[RESULT] Livox SDK2 static validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
