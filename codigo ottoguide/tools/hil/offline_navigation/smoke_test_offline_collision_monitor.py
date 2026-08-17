#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox Collision Monitor.

Validates the isolated safety chain:
controller_server -> cmd_vel_raw -> collision_monitor -> cmd_vel_safe -> offline_runtime_simulator

Scenarios tested in separate, isolated domain IDs:
A. Clear (obstacle_mode="clear"): Pose advances with unmodified velocity (safe/raw ratio median ~1.0).
B. Slowdown (obstacle_mode="slowdown"): cmd_vel_safe reduced to ~40% of cmd_vel_raw (ratio median ~0.40).
C. Stop (obstacle_mode="stop"): cmd_vel_safe explicitly zero after raw nonzero; pose stable.
D. Recovery (stop -> clear): raw nonzero -> safe zero -> mode=clear -> safe nonzero -> dist > 0.01m.
E. Cancel (obstacle_mode="clear"): motion > 0.01m before cancel, goal CANCELED, safe zero, odom zero, pose stable 0.5s.

No robot hardware, no network access, no rosbags.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import ComputePathToPose, FollowPath
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_BASE_DOMAIN_ID = "121"
DEFAULT_TIMEOUT_S = 60.0

START_XY = (0.0, 0.0)
GOAL_XY = (0.50, 0.0)
GOAL_TOLERANCE_M = 0.12

MIN_DOMAIN_ID = 1
MAX_DOMAIN_ID = 232
MAXIMUM_OFFSET = 4


def validate_domain_id_range(base: int, maximum_offset: int) -> str | None:
    """Validate base and base+maximum_offset against the 1..232 FastDDS-safe
    range required for this sandbox before any ROS process is started.
    Returns an error code string, or None if the range is valid.
    """
    if not isinstance(base, int) or base < MIN_DOMAIN_ID or base > MAX_DOMAIN_ID:
        return "INVALID_DOMAIN_ID"
    if base + maximum_offset > MAX_DOMAIN_ID:
        return "DERIVED_DOMAIN_ID_OUT_OF_RANGE"
    return None


def parse_base_domain_id(raw_value: str) -> tuple[int | None, str | None]:
    """Parse --base-domain-id into a strict base-10 int without ever raising.
    Rejects non-integer strings (e.g. "abc", "12.5", "", "   ") the same way
    an out-of-range integer is rejected: by returning INVALID_DOMAIN_ID
    instead of letting int() raise ValueError into an uncaught traceback.
    """
    try:
        return int(raw_value), None
    except (TypeError, ValueError):
        return None, "INVALID_DOMAIN_ID"


ALLOWED_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel_raw", "/cmd_vel_safe")
FORBIDDEN_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav")
FORBIDDEN_NODE_SUBSTRINGS = (
    "unitree",
    "livox_sdk_bridge",
    "livox_ros_driver",
    "realsense",
)

# Minimum valid pairs required for ratio check
MIN_VALID_PAIRS = 3

# Maximum time-delta between a safe sample and the most recent raw sample (causal)
MAX_PAIR_DT_S = 0.25

# Minimum raw speed to include a pair in the ratio calculation
MIN_RAW_FOR_PAIR = 0.02


def _build_env(domain_id: str) -> dict:
    env = os.environ.copy()
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["ROS_DOMAIN_ID"] = domain_id
    return env


def _run(cmd: list[str], env: dict, timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # A transient slow ros2 CLI call must not abort the calling retry
        # loop (_wait_for_node_discovered / _wait_for_lifecycle_active);
        # surface it as a failed-but-retryable CompletedProcess instead.
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="TIMEOUT")


def _node_list(env: dict, timeout: float) -> list[str]:
    proc = _run(["ros2", "node", "list"], env, timeout)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _topic_list(env: dict, timeout: float) -> list[str]:
    proc = _run(["ros2", "topic", "list"], env, timeout)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _lifecycle_get(node_fqn: str, env: dict, timeout: float) -> str | None:
    proc = _run(["ros2", "lifecycle", "get", node_fqn], env, timeout)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().split()[0].lower()


def _wait_for_node_discovered(node_fqn: str, env: dict, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if node_fqn in _node_list(env, timeout=5.0):
            return True
        time.sleep(1.0)
    return False


def _wait_for_lifecycle_active(node_fqn: str, env: dict, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if _lifecycle_get(node_fqn, env, timeout=5.0) == "active":
            return True
        time.sleep(1.0)
    return False


def _make_pose(frame_id: str, x: float, y: float) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = frame_id
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = 0.0
    pose.pose.orientation.x = 0.0
    pose.pose.orientation.y = 0.0
    pose.pose.orientation.z = 0.0
    pose.pose.orientation.w = 1.0
    return pose


def _process_group_is_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _shutdown_and_count_orphans(launch_process) -> int:
    if launch_process is None:
        return 0
    try:
        pgid = os.getpgid(launch_process.pid)
    except ProcessLookupError:
        return 0
    try:
        os.killpg(pgid, signal.SIGINT)
        launch_process.wait(timeout=15.0)
    except ProcessLookupError:
        return 0
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGTERM)
            launch_process.wait(timeout=10.0)
        except ProcessLookupError:
            return 0
        except subprocess.TimeoutExpired:
            pass
    time.sleep(1.0)
    return 1 if _process_group_is_alive(pgid) else 0


def _compute_causal_pairs(
    raw_history: list[tuple[float, float]],
    safe_history: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Causal pairing: for each safe sample, find the most recent raw sample
    whose timestamp is <= safe timestamp, with dt <= MAX_PAIR_DT_S.
    Each safe sample is used at most once. Pairs with abs(raw) < MIN_RAW_FOR_PAIR
    are discarded.
    Returns list of (raw_speed, safe_speed) pairs.
    """
    pairs = []
    used_safe = set()
    for s_idx, (s_val, s_t) in enumerate(safe_history):
        if s_idx in used_safe:
            continue
        # Find most recent raw sample at or before s_t
        best_raw = None
        best_raw_t = None
        for r_val, r_t in raw_history:
            if r_t <= s_t and (s_t - r_t) <= MAX_PAIR_DT_S:
                if best_raw_t is None or r_t > best_raw_t:
                    best_raw = r_val
                    best_raw_t = r_t
        if best_raw is not None and abs(best_raw) >= MIN_RAW_FOR_PAIR:
            pairs.append((best_raw, s_val))
            used_safe.add(s_idx)
    return pairs


class _CollisionMonitorSmokeClient(Node):
    """rclpy helper node for monitoring topics and interacting with actions."""

    def __init__(self, namespace: str) -> None:
        super().__init__("offline_collision_monitor_smoke_test_client")
        self._namespace = namespace
        self._planner_client = ActionClient(
            self, ComputePathToPose, f"/{namespace}/compute_path_to_pose"
        )
        self._follow_path_client = ActionClient(
            self, FollowPath, f"/{namespace}/follow_path"
        )
        self._latest_odom: Odometry | None = None
        self._latest_cmd_vel_raw: Twist | None = None
        self._latest_cmd_vel_safe: Twist | None = None
        self.raw_history: list[tuple[float, float]] = []
        self.safe_history: list[tuple[float, float]] = []

        self.odom_topic_observed = f"/{namespace}/odom"
        self.cmd_vel_raw_topic_observed = f"/{namespace}/cmd_vel_raw"
        self.cmd_vel_safe_topic_observed = f"/{namespace}/cmd_vel_safe"

        self.create_subscription(Odometry, self.odom_topic_observed, self._on_odom, 10)
        self.create_subscription(Twist, self.cmd_vel_raw_topic_observed, self._on_cmd_vel_raw, 10)
        self.create_subscription(Twist, self.cmd_vel_safe_topic_observed, self._on_cmd_vel_safe, 10)

        self.odom_messages_received = 0
        self.cmd_vel_raw_messages_received = 0
        self.cmd_vel_safe_messages_received = 0

    def _on_odom(self, msg: Odometry) -> None:
        self._latest_odom = msg
        self.odom_messages_received += 1

    def _on_cmd_vel_raw(self, msg: Twist) -> None:
        self._latest_cmd_vel_raw = msg
        self.cmd_vel_raw_messages_received += 1
        self.raw_history.append((msg.linear.x, time.monotonic()))

    def _on_cmd_vel_safe(self, msg: Twist) -> None:
        self._latest_cmd_vel_safe = msg
        self.cmd_vel_safe_messages_received += 1
        self.safe_history.append((msg.linear.x, time.monotonic()))

    def get_causal_pairs(self) -> list[tuple[float, float]]:
        return _compute_causal_pairs(self.raw_history, self.safe_history)

    def current_xy(self) -> tuple[float, float] | None:
        if self._latest_odom is None:
            return None
        return (
            self._latest_odom.pose.pose.position.x,
            self._latest_odom.pose.pose.position.y,
        )

    def current_twist(self) -> tuple[float, float] | None:
        if self._latest_odom is None:
            return None
        return (
            self._latest_odom.twist.twist.linear.x,
            self._latest_odom.twist.twist.angular.z,
        )

    def spin_for(self, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)

    def spin_until_future_complete_custom(self, future, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and not future.done():
            rclpy.spin_once(self, timeout_sec=0.05)
        return future.done()

    def wait_for_planner_server(self, timeout_s: float) -> bool:
        return self._planner_client.wait_for_server(timeout_sec=timeout_s)

    def wait_for_follow_path_server(self, timeout_s: float) -> bool:
        return self._follow_path_client.wait_for_server(timeout_sec=timeout_s)

    def wait_for_initial_odom(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self._latest_odom is not None:
                return True
        return False

    def compute_path(self, start: PoseStamped, goal: PoseStamped, timeout_s: float):
        goal_msg = ComputePathToPose.Goal()
        goal_msg.start = start
        goal_msg.goal = goal
        goal_msg.use_start = True

        send_goal_future = self._planner_client.send_goal_async(goal_msg)
        if not self.spin_until_future_complete_custom(send_goal_future, 15.0):
            return None
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None
        result_future = goal_handle.get_result_async()
        if not self.spin_until_future_complete_custom(result_future, timeout_s):
            return None
        wrapped_result = result_future.result()
        if wrapped_result is None or wrapped_result.status != GoalStatus.STATUS_SUCCEEDED:
            return None
        return wrapped_result.result.path

    def send_follow_path_async(self, path) -> any:
        goal_msg = FollowPath.Goal()
        goal_msg.path = path
        send_goal_future = self._follow_path_client.send_goal_async(goal_msg)
        if not self.spin_until_future_complete_custom(send_goal_future, 15.0):
            return None
        return send_goal_future.result()


def check_topic_routing(namespace: str, env: dict) -> list[str]:
    errors = []
    # Verify raw topic
    raw_topic = f"/{namespace}/cmd_vel_raw"
    proc_raw = _run(["ros2", "topic", "info", "-v", raw_topic], env, timeout=5.0)
    if proc_raw.returncode == 0:
        stdout = proc_raw.stdout
        if "controller_server" not in stdout:
            errors.append("CONTROLLER_SERVER_NOT_PUBLISHING_RAW")
        if "collision_monitor" not in stdout:
            errors.append("COLLISION_MONITOR_NOT_SUBSCRIBED_TO_RAW")
    else:
        errors.append("COULD_NOT_QUERY_RAW_TOPIC")

    # Verify safe topic
    safe_topic = f"/{namespace}/cmd_vel_safe"
    proc_safe = _run(["ros2", "topic", "info", "-v", safe_topic], env, timeout=5.0)
    if proc_safe.returncode == 0:
        stdout = proc_safe.stdout
        if "collision_monitor" not in stdout:
            errors.append("COLLISION_MONITOR_NOT_PUBLISHING_SAFE")
        if "offline_runtime_simulator" not in stdout:
            errors.append("SIMULATOR_NOT_SUBSCRIBED_TO_SAFE")
    else:
        errors.append("COULD_NOT_QUERY_SAFE_TOPIC")

    return errors


def set_simulator_obstacle_mode(namespace: str, mode: str, env: dict) -> bool:
    proc = _run(
        ["ros2", "param", "set", f"/{namespace}/offline_runtime_simulator", "obstacle_mode", mode],
        env,
        timeout=10.0,
    )
    return proc.returncode == 0


def run_single_scenario(namespace: str, domain_id: str, scenario: str, timeout_s: float) -> dict:
    run_result = {
        "ok": False,
        "map_server_active": False,
        "planner_server_active": False,
        "controller_server_active": False,
        "collision_monitor_active": False,
        "topic_routing_errors": [],
        "initial_odom_received": False,
        "cmd_vel_raw_messages": 0,
        "cmd_vel_safe_messages": 0,
        "raw_speed_observed": None,
        "safe_speed_observed": None,
        "simulated_distance_moved": 0.0,
        "final_pose_stable": False,
        "goal_status": "NOT_ATTEMPTED",
        "recovery_resumed": False,
        "forbidden_velocity_topics_detected": [],
        "hardware_node_detected": False,
        "orphan_processes": 0,
        "errors": [],
        # Paired speeds / slowdown metrics
        "paired_raw_speed": None,
        "paired_safe_speed": None,
        "paired_slowdown_ratio": None,
        "valid_pairs_count": 0,
        "median_ratio": None,
        # STOP metrics
        "safe_zero_sample_observed": False,
        # RECOVERY metrics
        "stop_safe_zero_observed": False,
        "recovery_safe_nonzero_observed": False,
        "recovery_distance_moved": 0.0,
        # CANCEL metrics
        "cancel_motion_observed": False,
        "cancel_safe_nonzero_before_cancel": False,
        "cancel_safe_zero_after_cancel": False,
        "cancel_odom_twist_zero": False,
        "cancel_pose_stable": False,
    }

    env = _build_env(domain_id)
    launch_process = None
    rclpy_initialized = False
    client = None

    try:
        launch_process = subprocess.Popen(
            ["bash", str(RUNTIME_WRAPPER), f"sandbox_namespace:={namespace}", "use_rviz:=false"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )

        deadline = time.monotonic() + timeout_s
        map_fqn = f"/{namespace}/map_server"
        planner_fqn = f"/{namespace}/planner_server"
        controller_fqn = f"/{namespace}/controller_server"
        collision_monitor_fqn = f"/{namespace}/collision_monitor"

        for fqn, key in (
            (map_fqn, "map_server_active"),
            (planner_fqn, "planner_server_active"),
            (controller_fqn, "controller_server_active"),
            (collision_monitor_fqn, "collision_monitor_active"),
        ):
            if _wait_for_node_discovered(fqn, env, deadline):
                run_result[key] = _wait_for_lifecycle_active(fqn, env, deadline)
            if not run_result[key]:
                run_result["errors"].append(f"{key.upper()}_NOT_CONFIRMED")

        # Detect hardware nodes
        nodes = _node_list(env, timeout=5.0)
        run_result["hardware_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
            for node in nodes
        )

        # Detect velocity topics
        topics = _topic_list(env, timeout=5.0)
        run_result["forbidden_velocity_topics_detected"] = [
            t for t in topics if any(t.endswith(suffix) for suffix in FORBIDDEN_VELOCITY_TOPIC_SUFFIXES)
        ]

        if not run_result["errors"]:
            # Set obstacle mode initially in simulator
            # All scenarios start with their designated initial mode
            initial_mode = "clear"
            if scenario in ("stop", "recovery"):
                initial_mode = "stop"
            elif scenario == "slowdown":
                initial_mode = "slowdown"
            # clear and cancel both start in clear mode

            if not set_simulator_obstacle_mode(namespace, initial_mode, env):
                run_result["errors"].append("SET_OBSTACLE_MODE_FAILED")

            # Check routing
            routing_errs = check_topic_routing(namespace, env)
            run_result["topic_routing_errors"] = routing_errs
            if routing_errs:
                run_result["errors"].extend(routing_errs)

        if not run_result["errors"]:
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _CollisionMonitorSmokeClient(namespace)
            try:
                client.wait_for_planner_server(timeout_s=15.0)
                client.wait_for_follow_path_server(timeout_s=15.0)

                if not client.wait_for_initial_odom(timeout_s=15.0):
                    run_result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    run_result["initial_odom_received"] = True
                    pose_before = client.current_xy()
                    x_init, y_init = pose_before

                    # Send goal
                    start_pose = _make_pose("map", x_init, y_init)
                    goal_pose = _make_pose("map", x_init + 0.60, y_init)
                    path = client.compute_path(start_pose, goal_pose, timeout_s=20.0)

                    if path is None:
                        run_result["errors"].append("COMPUTE_PATH_FAILED")
                    else:
                        goal_handle = client.send_follow_path_async(path)
                        if goal_handle is None or not goal_handle.accepted:
                            run_result["errors"].append("FOLLOW_PATH_GOAL_REJECTED")
                        else:
                            wait_deadline = time.monotonic() + 15.0

                            if scenario in ("clear", "slowdown"):
                                wait_start = time.monotonic()
                                while time.monotonic() < wait_deadline:
                                    client.spin_for(0.1)
                                    raw = client._latest_cmd_vel_raw
                                    safe = client._latest_cmd_vel_safe
                                    if raw is not None and abs(raw.linear.x) > 1e-4:
                                        if run_result["raw_speed_observed"] is None or abs(raw.linear.x) > run_result["raw_speed_observed"]:
                                            run_result["raw_speed_observed"] = abs(raw.linear.x)
                                    if safe is not None and abs(safe.linear.x) > 1e-4:
                                        if run_result["safe_speed_observed"] is None or abs(safe.linear.x) > run_result["safe_speed_observed"]:
                                            run_result["safe_speed_observed"] = abs(safe.linear.x)

                                    curr_xy = client.current_xy()
                                    if time.monotonic() - wait_start > 3.0:
                                        dist_moved = math.hypot(curr_xy[0] - x_init, curr_xy[1] - y_init) if curr_xy else 0.0
                                        if dist_moved > (0.05 if scenario == "clear" else 0.01):
                                            break

                            elif scenario == "stop":
                                raw_nonzero_seen = False
                                safe_zero_seen_after_raw = False
                                while time.monotonic() < wait_deadline:
                                    client.spin_for(0.1)
                                    raw = client._latest_cmd_vel_raw
                                    safe = client._latest_cmd_vel_safe
                                    if raw is not None and abs(raw.linear.x) > 0.01:
                                        raw_nonzero_seen = True
                                        if run_result["raw_speed_observed"] is None or abs(raw.linear.x) > run_result["raw_speed_observed"]:
                                            run_result["raw_speed_observed"] = abs(raw.linear.x)
                                    if safe is not None:
                                        if run_result["safe_speed_observed"] is None or abs(safe.linear.x) > run_result["safe_speed_observed"]:
                                            run_result["safe_speed_observed"] = abs(safe.linear.x)
                                        if raw_nonzero_seen and abs(safe.linear.x) < 1e-5:
                                            safe_zero_seen_after_raw = True
                                run_result["safe_zero_sample_observed"] = safe_zero_seen_after_raw

                            elif scenario == "recovery":
                                # Sequence: raw nonzero -> safe zero (stop) -> mode=clear -> safe nonzero -> dist > 0.01m
                                state = 0
                                x_stop, y_stop = x_init, y_init
                                while time.monotonic() < wait_deadline:
                                    client.spin_for(0.1)
                                    raw = client._latest_cmd_vel_raw
                                    safe = client._latest_cmd_vel_safe
                                    curr_xy = client.current_xy()

                                    if raw is not None and abs(raw.linear.x) > 0.01:
                                        if run_result["raw_speed_observed"] is None or abs(raw.linear.x) > run_result["raw_speed_observed"]:
                                            run_result["raw_speed_observed"] = abs(raw.linear.x)
                                    if safe is not None:
                                        if run_result["safe_speed_observed"] is None or abs(safe.linear.x) > run_result["safe_speed_observed"]:
                                            run_result["safe_speed_observed"] = abs(safe.linear.x)

                                    if state == 0:
                                        # Wait for: raw nonzero AND safe zero (stop condition)
                                        if raw is not None and abs(raw.linear.x) > 0.01 and safe is not None and abs(safe.linear.x) < 1e-5:
                                            run_result["stop_safe_zero_observed"] = True
                                            if curr_xy is not None:
                                                x_stop, y_stop = curr_xy
                                            if set_simulator_obstacle_mode(namespace, "clear", env):
                                                state = 1
                                            else:
                                                run_result["errors"].append("SET_OBSTACLE_MODE_CLEAR_FAILED")
                                                break
                                    elif state == 1:
                                        # Wait for safe nonzero after mode=clear
                                        if safe is not None and abs(safe.linear.x) > 0.01:
                                            run_result["recovery_safe_nonzero_observed"] = True
                                            state = 2
                                    elif state == 2:
                                        # Wait for actual distance moved > 0.01m from stop point
                                        if curr_xy is not None:
                                            dist = math.hypot(curr_xy[0] - x_stop, curr_xy[1] - y_stop)
                                            run_result["recovery_distance_moved"] = dist
                                            if dist > 0.01:
                                                run_result["recovery_resumed"] = True
                                                break

                            elif scenario == "cancel":
                                # obstacle_mode is already "clear" (initial_mode for cancel)
                                # Require: raw nonzero, safe nonzero, dist > 0.01m BEFORE canceling
                                state = 0
                                while time.monotonic() < wait_deadline:
                                    client.spin_for(0.1)
                                    raw = client._latest_cmd_vel_raw
                                    safe = client._latest_cmd_vel_safe
                                    curr_xy = client.current_xy()

                                    if raw is not None and abs(raw.linear.x) > 0.01:
                                        if run_result["raw_speed_observed"] is None or abs(raw.linear.x) > run_result["raw_speed_observed"]:
                                            run_result["raw_speed_observed"] = abs(raw.linear.x)
                                    if safe is not None:
                                        if run_result["safe_speed_observed"] is None or abs(safe.linear.x) > run_result["safe_speed_observed"]:
                                            run_result["safe_speed_observed"] = abs(safe.linear.x)

                                    if state == 0:
                                        if raw is not None and abs(raw.linear.x) > 0.01:
                                            if safe is not None and abs(safe.linear.x) > 0.01:
                                                run_result["cancel_safe_nonzero_before_cancel"] = True
                                                if curr_xy is not None:
                                                    dist = math.hypot(curr_xy[0] - x_init, curr_xy[1] - y_init)
                                                    if dist > 0.01:
                                                        run_result["cancel_motion_observed"] = True
                                                        cancel_future = goal_handle.cancel_goal_async()
                                                        if client.spin_until_future_complete_custom(cancel_future, 10.0):
                                                            res_future = goal_handle.get_result_async()
                                                            if client.spin_until_future_complete_custom(res_future, 10.0):
                                                                wrapped_res = res_future.result()
                                                                if wrapped_res is not None:
                                                                    if wrapped_res.status == GoalStatus.STATUS_CANCELED:
                                                                        run_result["goal_status"] = "CANCELED"
                                                                    else:
                                                                        run_result["goal_status"] = f"STATUS_{wrapped_res.status}"
                                                        state = 1
                                                        break

                                if run_result["goal_status"] == "CANCELED":
                                    # Spin 1.5s to let watchdog expire and safe/odom settle
                                    client.spin_for(1.5)
                                    post_safe = client._latest_cmd_vel_safe
                                    if post_safe is not None and abs(post_safe.linear.x) < 1e-5:
                                        run_result["cancel_safe_zero_after_cancel"] = True

                                    twist = client.current_twist()
                                    if twist is not None and abs(twist[0]) < 1e-5 and abs(twist[1]) < 1e-5:
                                        run_result["cancel_odom_twist_zero"] = True

                                    # Pose stability check over 0.5s
                                    pose_t0 = client.current_xy()
                                    client.spin_for(0.5)
                                    pose_t1 = client.current_xy()
                                    if pose_t0 is not None and pose_t1 is not None:
                                        diff = math.hypot(pose_t1[0] - pose_t0[0], pose_t1[1] - pose_t0[1])
                                        run_result["cancel_pose_stable"] = (diff < 0.002)

                            # Measure final position
                            pose_after = client.current_xy()
                            if pose_before is not None and pose_after is not None:
                                run_result["simulated_distance_moved"] = math.hypot(
                                    pose_after[0] - pose_before[0], pose_after[1] - pose_before[1]
                                )

                            # Assess pose stability (only meaningful for stop)
                            client.spin_for(1.0)
                            pose_final = client.current_xy()
                            if pose_after is not None and pose_final is not None:
                                diff = math.hypot(pose_final[0] - pose_after[0], pose_final[1] - pose_after[1])
                                run_result["final_pose_stable"] = (diff < 0.002)

                            run_result["cmd_vel_raw_messages"] = client.cmd_vel_raw_messages_received
                            run_result["cmd_vel_safe_messages"] = client.cmd_vel_safe_messages_received

                            # Cancel to clean up if not already canceled
                            if scenario != "cancel":
                                try:
                                    goal_handle.cancel_goal_async()
                                except Exception:
                                    pass

            finally:
                client.destroy_node()

    except Exception as exc:
        run_result["errors"].append(f"EXCEPTION: {exc}")
    finally:
        if rclpy_initialized:
            try:
                rclpy.shutdown()
            except Exception:
                pass
        run_result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)

    # Evaluate scenario correctness
    if scenario in ("clear", "slowdown"):
        # Causal pairing: independent of expected ratio
        pairs = _compute_causal_pairs(
            client.raw_history if client is not None else [],
            client.safe_history if client is not None else [],
        )
        run_result["valid_pairs_count"] = len(pairs)
        ratio_ok = False
        if len(pairs) >= MIN_VALID_PAIRS:
            ratios = [abs(s) / abs(r) for r, s in pairs if abs(r) >= MIN_RAW_FOR_PAIR]
            if len(ratios) >= MIN_VALID_PAIRS:
                median_ratio = statistics.median(ratios)
                run_result["median_ratio"] = median_ratio
                # Populate paired metrics from the pair closest to median ratio
                closest_pair = min(pairs, key=lambda p: abs(abs(p[1]) / abs(p[0]) - median_ratio))
                run_result["paired_raw_speed"] = abs(closest_pair[0])
                run_result["paired_safe_speed"] = abs(closest_pair[1])
                run_result["paired_slowdown_ratio"] = abs(closest_pair[1]) / abs(closest_pair[0])
                if scenario == "clear":
                    ratio_ok = 0.90 <= median_ratio <= 1.10
                else:  # slowdown
                    ratio_ok = 0.35 <= median_ratio <= 0.45

        if scenario == "clear":
            run_result["ok"] = (
                not run_result["errors"]
                and run_result["collision_monitor_active"]
                and run_result["cmd_vel_raw_messages"] > 0
                and run_result["cmd_vel_safe_messages"] > 0
                and len(pairs) >= MIN_VALID_PAIRS
                and ratio_ok
                and run_result["simulated_distance_moved"] > 0.05
                and not run_result["hardware_node_detected"]
                and not run_result["forbidden_velocity_topics_detected"]
                and run_result["orphan_processes"] == 0
            )
        else:  # slowdown
            run_result["ok"] = (
                not run_result["errors"]
                and run_result["collision_monitor_active"]
                and run_result["cmd_vel_raw_messages"] > 0
                and run_result["cmd_vel_safe_messages"] > 0
                and len(pairs) >= MIN_VALID_PAIRS
                and ratio_ok
                and run_result["simulated_distance_moved"] > 0.01
                and not run_result["hardware_node_detected"]
                and run_result["orphan_processes"] == 0
            )
    elif scenario == "stop":
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and run_result["cmd_vel_raw_messages"] > 0
            and run_result["cmd_vel_safe_messages"] > 0
            and run_result["raw_speed_observed"] is not None and run_result["raw_speed_observed"] > 0.01
            and run_result["safe_zero_sample_observed"]
            and run_result["simulated_distance_moved"] < 0.005
            and run_result["final_pose_stable"]
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )
    elif scenario == "recovery":
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and run_result["stop_safe_zero_observed"]
            and run_result["recovery_safe_nonzero_observed"]
            and run_result["recovery_resumed"]
            and run_result["recovery_distance_moved"] > 0.01
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )
    elif scenario == "cancel":
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and run_result["cancel_motion_observed"]
            and run_result["cancel_safe_nonzero_before_cancel"]
            and run_result["goal_status"] == "CANCELED"
            and run_result["cancel_safe_zero_after_cancel"]
            and run_result["cancel_odom_twist_zero"]
            and run_result["cancel_pose_stable"]
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )
    return run_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--base-domain-id", default=DEFAULT_BASE_DOMAIN_ID)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base, parse_error = parse_base_domain_id(args.base_domain_id)
    if parse_error is not None:
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": [parse_error]}))
        return 2

    domain_error = validate_domain_id_range(base, MAXIMUM_OFFSET)
    if domain_error is not None:
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": [domain_error]}))
        return 2

    # Map scenarios to domain offsets
    scenarios = ["clear", "slowdown", "stop", "recovery", "cancel"]
    results = {}
    all_ok = True

    for i, sc in enumerate(scenarios):
        dom = str(base + i)
        print(f"--- Running scenario: {sc.upper()} on ROS_DOMAIN_ID={dom} ---")
        res = run_single_scenario(args.namespace, dom, sc, args.timeout)
        results[sc] = res
        print(f"Scenario {sc.upper()} outcome: {'PASS' if res['ok'] else 'FAIL'}")
        if not res["ok"]:
            all_ok = False

    decision = "PASS" if all_ok else "FAIL"

    # Compile unified report
    report = {
        "ok": all_ok,
        "decision": decision,
        "namespace": args.namespace,
        "base_domain_id": args.base_domain_id,
        "scenarios": results,
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")

    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
