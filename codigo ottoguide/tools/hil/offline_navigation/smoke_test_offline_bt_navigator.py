#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox BT Navigator.

Validates the isolated NavigateToPose orchestration chain:
bt_navigator -> planner_server (ComputePathToPose) -> controller_server
(FollowPath) -> cmd_vel_raw -> collision_monitor -> cmd_vel_safe ->
offline_runtime_simulator.

Scenarios tested in separate, isolated domain IDs derived from
--base-domain-id:
A. Success (base): NavigateToPose to a goal ~0.4-0.6m ahead of the observed
   initial pose, computed relative to that pose (never assumed to be the
   origin). Requires SUCCEEDED, real raw/safe telemetry, observed motion,
   arrival within tolerance, and a stable final zero twist.
B. Cancel (base + 1): NavigateToPose to a farther goal, canceled only after
   raw/safe motion is observed (never canceled as a substitute for that
   precondition). Acceptance of the cancel request is verified against the
   real action_msgs/srv/CancelGoal response (return_code == ERROR_NONE and
   the goal's UUID present in goals_canceling), not merely the completion of
   the cancel future. Requires CANCELED, a safe/odom message strictly after
   the cancel request, both settling to zero, and a stable pose afterward.

This script does not touch the real robot, does not open rosbags, does not
install packages, and does not kill ROS processes outside its own launched
process group. Waypoint Follower, Simple Commander and NavigateThroughPoses
are not exercised by this phase.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import rclpy
from action_msgs.msg import GoalStatus
from action_msgs.srv import CancelGoal
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_BASE_DOMAIN_ID = "180"
DEFAULT_TIMEOUT_S = 60.0

MIN_DOMAIN_ID = 1
MAX_DOMAIN_ID = 232
MAXIMUM_OFFSET = 1

GOAL_FORWARD_OFFSET_M = 0.50
CANCEL_GOAL_FORWARD_OFFSET_M = 1.5
GOAL_TOLERANCE_M = 0.12
MAP_X_BOUNDS = (-1.0, 1.0)
MAP_Y_BOUNDS = (-0.75, 0.75)
PLANAR_NONZERO_TOLERANCE = 1e-4
POSE_STABLE_TOLERANCE_M = 0.002
CANCEL_PRECONDITION_MOTION_M = 0.02

ALLOWED_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel_raw", "/cmd_vel_safe")
FORBIDDEN_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav")
FORBIDDEN_NODE_SUBSTRINGS = (
    "unitree",
    "livox_sdk_bridge",
    "livox_ros_driver",
    "realsense",
)
FORBIDDEN_MISSION_NODE_SUBSTRINGS = (
    "waypoint_follower",
    "simple_commander",
)


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


def _planar_nonzero(linear_x: float, linear_y: float, angular_z: float) -> bool:
    return (
        abs(linear_x) > PLANAR_NONZERO_TOLERANCE
        or abs(linear_y) > PLANAR_NONZERO_TOLERANCE
        or abs(angular_z) > PLANAR_NONZERO_TOLERANCE
    )


def _build_env(domain_id: str) -> dict:
    env = os.environ.copy()
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["ROS_DOMAIN_ID"] = domain_id
    return env


def _run(cmd: list[str], env: dict, timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
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


def _topic_info_verbose(topic: str, env: dict, timeout: float) -> str:
    proc = _run(["ros2", "topic", "info", "-v", topic], env, timeout)
    if proc.returncode != 0:
        return ""
    return proc.stdout


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


def _yaw_from_quaternion(qz: float, qw: float) -> float:
    return 2.0 * math.atan2(qz, qw)


def _make_pose(frame_id: str, x: float, y: float, yaw: float = 0.0) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = frame_id
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = 0.0
    half_yaw = yaw * 0.5
    pose.pose.orientation.z = math.sin(half_yaw)
    pose.pose.orientation.w = math.cos(half_yaw)
    return pose


def _clamp_goal_within_map(x: float, y: float) -> tuple[float, float]:
    x_clamped = min(max(x, MAP_X_BOUNDS[0] + 0.1), MAP_X_BOUNDS[1] - 0.1)
    y_clamped = min(max(y, MAP_Y_BOUNDS[0] + 0.1), MAP_Y_BOUNDS[1] - 0.1)
    return x_clamped, y_clamped


class _BtNavigatorSmokeClient(Node):
    """rclpy helper node bundling the NavigateToPose action client, an odom
    subscription, and cmd_vel_raw/cmd_vel_safe watchers, all resolved
    relative to the sandbox namespace.
    """

    def __init__(self, namespace: str) -> None:
        super().__init__("offline_bt_navigator_smoke_test_client")
        self._namespace = namespace
        self._nav_client = ActionClient(
            self, NavigateToPose, f"/{namespace}/navigate_to_pose"
        )
        self._latest_odom: Odometry | None = None
        self._latest_cmd_vel_raw: Twist | None = None
        self._latest_cmd_vel_safe: Twist | None = None

        self.odom_messages_received = 0
        self.raw_messages_received = 0
        self.safe_messages_received = 0
        self.raw_nonzero_observed = False
        self.safe_nonzero_observed = False
        self.odom_messages_received_since_mark = 0
        self.safe_messages_received_since_mark = 0
        self._mark_odom_count = 0
        self._mark_safe_count = 0

        self.create_subscription(Odometry, f"/{namespace}/odom", self._on_odom, 10)
        self.create_subscription(Twist, f"/{namespace}/cmd_vel_raw", self._on_cmd_vel_raw, 10)
        self.create_subscription(Twist, f"/{namespace}/cmd_vel_safe", self._on_cmd_vel_safe, 10)

    def _on_odom(self, msg: Odometry) -> None:
        self._latest_odom = msg
        self.odom_messages_received += 1

    def _on_cmd_vel_raw(self, msg: Twist) -> None:
        self._latest_cmd_vel_raw = msg
        self.raw_messages_received += 1
        if _planar_nonzero(msg.linear.x, msg.linear.y, msg.angular.z):
            self.raw_nonzero_observed = True

    def _on_cmd_vel_safe(self, msg: Twist) -> None:
        self._latest_cmd_vel_safe = msg
        self.safe_messages_received += 1
        if _planar_nonzero(msg.linear.x, msg.linear.y, msg.angular.z):
            self.safe_nonzero_observed = True

    def mark_post_cancel_baseline(self) -> None:
        self._mark_odom_count = self.odom_messages_received
        self._mark_safe_count = self.safe_messages_received

    def odom_message_received_after_mark(self) -> bool:
        return self.odom_messages_received > self._mark_odom_count

    def safe_message_received_after_mark(self) -> bool:
        return self.safe_messages_received > self._mark_safe_count

    def current_xy(self) -> tuple[float, float] | None:
        if self._latest_odom is None:
            return None
        return (
            self._latest_odom.pose.pose.position.x,
            self._latest_odom.pose.pose.position.y,
        )

    def current_yaw(self) -> float | None:
        if self._latest_odom is None:
            return None
        q = self._latest_odom.pose.pose.orientation
        return _yaw_from_quaternion(q.z, q.w)

    def current_twist(self) -> tuple[float, float, float] | None:
        if self._latest_odom is None:
            return None
        twist = self._latest_odom.twist.twist
        return (twist.linear.x, twist.linear.y, twist.angular.z)

    def latest_safe_twist(self) -> tuple[float, float, float] | None:
        if self._latest_cmd_vel_safe is None:
            return None
        t = self._latest_cmd_vel_safe
        return (t.linear.x, t.linear.y, t.angular.z)

    def spin_for(self, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)

    def spin_until_future_complete_custom(self, future, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and not future.done():
            rclpy.spin_once(self, timeout_sec=0.05)
        return future.done()

    def wait_for_nav_server(self, timeout_s: float) -> bool:
        return self._nav_client.wait_for_server(timeout_sec=timeout_s)

    def wait_for_initial_odom(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self._latest_odom is not None:
                return True
        return False

    def send_navigate_to_pose(self, goal_pose: PoseStamped):
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = goal_pose
        send_goal_future = self._nav_client.send_goal_async(goal_msg)
        if not self.spin_until_future_complete_custom(send_goal_future, 15.0):
            return None
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None
        return goal_handle

    def wait_for_navigate_result(self, goal_handle, timeout_s: float) -> tuple[str, object]:
        result_future = goal_handle.get_result_async()
        if not self.spin_until_future_complete_custom(result_future, timeout_s):
            return "RESULT_TIMEOUT", None
        wrapped_result = result_future.result()
        if wrapped_result is None:
            return "RESULT_NONE", None
        if wrapped_result.status == GoalStatus.STATUS_SUCCEEDED:
            return "SUCCEEDED", wrapped_result.result
        if wrapped_result.status == GoalStatus.STATUS_CANCELED:
            return "CANCELED", wrapped_result.result
        return f"GOAL_STATUS_{wrapped_result.status}", wrapped_result.result

    def request_cancel_and_check_acceptance(self, goal_handle, timeout_s: float) -> dict:
        """Send the cancel request and inspect the real action_msgs/srv/
        CancelGoal response instead of treating future completion as proof
        of acceptance. Per the local ROS 2 Jazzy interface
        (action_msgs/srv/CancelGoal), return_code == ERROR_NONE (0) means
        the goal(s) transitioned to CANCELING, and the accepted goal's UUID
        must appear in goals_canceling. A nonzero return_code or an absent
        goal_id in goals_canceling means the server did NOT actually accept
        cancellation for this goal, even if the future completed normally.
        """
        outcome = {
            "cancel_response_received": False,
            "cancel_request_accepted": False,
            "errors": [],
        }
        cancel_future = goal_handle.cancel_goal_async()
        if not self.spin_until_future_complete_custom(cancel_future, timeout_s):
            outcome["errors"].append("CANCEL_RESPONSE_TIMEOUT")
            return outcome

        response = cancel_future.result()
        if response is None:
            outcome["errors"].append("CANCEL_RESPONSE_TIMEOUT")
            return outcome

        outcome["cancel_response_received"] = True

        if response.return_code != CancelGoal.Response.ERROR_NONE:
            outcome["errors"].append("CANCEL_REQUEST_NOT_ACCEPTED")
            return outcome

        canceling_goal_ids = {
            bytes(goal_info.goal_id.uuid) for goal_info in response.goals_canceling
        }
        if bytes(goal_handle.goal_id.uuid) not in canceling_goal_ids:
            outcome["errors"].append("CANCEL_REQUEST_NOT_ACCEPTED")
            return outcome

        outcome["cancel_request_accepted"] = True
        return outcome


def _discover_and_activate(namespace: str, env: dict, deadline: float, result: dict) -> None:
    fqns = {
        "map_server_active": f"/{namespace}/map_server",
        "planner_server_active": f"/{namespace}/planner_server",
        "controller_server_active": f"/{namespace}/controller_server",
        "collision_monitor_active": f"/{namespace}/collision_monitor",
        "behavior_server_active": f"/{namespace}/behavior_server",
        "bt_navigator_active": f"/{namespace}/bt_navigator",
    }
    for key, fqn in fqns.items():
        if _wait_for_node_discovered(fqn, env, deadline):
            result[key] = _wait_for_lifecycle_active(fqn, env, deadline)
        if not result[key]:
            result["errors"].append(f"{key.upper()}_NOT_CONFIRMED")


def _check_no_direct_velocity_publisher(namespace: str, env: dict, result: dict) -> None:
    """Confirm bt_navigator is never a publisher of cmd_vel_raw/cmd_vel_safe,
    and that controller_server is the actual publisher of cmd_vel_raw.
    """
    raw_info = _topic_info_verbose(f"/{namespace}/cmd_vel_raw", env, timeout=5.0)
    safe_info = _topic_info_verbose(f"/{namespace}/cmd_vel_safe", env, timeout=5.0)

    result["controller_raw_publisher_confirmed"] = "controller_server" in raw_info
    result["collision_monitor_safe_publisher_confirmed"] = "collision_monitor" in safe_info
    result["bt_navigator_direct_velocity_publisher"] = (
        "bt_navigator" in raw_info or "bt_navigator" in safe_info
    )
    if not result["controller_raw_publisher_confirmed"]:
        result["errors"].append("CONTROLLER_SERVER_NOT_PUBLISHING_RAW")
    if result["bt_navigator_direct_velocity_publisher"]:
        result["errors"].append("BT_NAVIGATOR_DIRECT_VELOCITY_PUBLISHER_DETECTED")


def run_success_scenario(namespace: str, domain_id: str, timeout_s: float) -> dict:
    result = {
        "ok": False,
        "scenario": "success",
        "domain_id": domain_id,
        "map_server_active": False,
        "planner_server_active": False,
        "controller_server_active": False,
        "collision_monitor_active": False,
        "behavior_server_active": False,
        "bt_navigator_active": False,
        "goal_accepted": False,
        "navigate_result": "NOT_ATTEMPTED",
        "odom_messages_received": 0,
        "raw_messages_received": 0,
        "safe_messages_received": 0,
        "raw_nonzero_observed": False,
        "safe_nonzero_observed": False,
        "initial_pose": None,
        "goal_pose": None,
        "final_pose": None,
        "distance_moved": None,
        "final_distance_to_goal": None,
        "final_twist_zero": False,
        "pose_stable": False,
        "controller_raw_publisher_confirmed": False,
        "collision_monitor_safe_publisher_confirmed": False,
        "bt_navigator_direct_velocity_publisher": False,
        "forbidden_velocity_topics_detected": [],
        "hardware_node_detected": False,
        "mission_node_detected": False,
        "orphan_processes": 0,
        "errors": [],
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
        _discover_and_activate(namespace, env, deadline, result)

        nodes = _node_list(env, timeout=5.0)
        result["hardware_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
            for node in nodes
        )
        result["mission_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_MISSION_NODE_SUBSTRINGS)
            for node in nodes
        )

        topics = _topic_list(env, timeout=5.0)
        result["forbidden_velocity_topics_detected"] = [
            t for t in topics if any(t.endswith(suffix) for suffix in FORBIDDEN_VELOCITY_TOPIC_SUFFIXES)
        ]

        if not result["errors"]:
            _check_no_direct_velocity_publisher(namespace, env, result)

        if not result["errors"]:
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _BtNavigatorSmokeClient(namespace)
            try:
                client.wait_for_nav_server(timeout_s=15.0)
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    initial_xy = client.current_xy()
                    initial_yaw = client.current_yaw() or 0.0
                    result["initial_pose"] = initial_xy

                    goal_x_raw = initial_xy[0] + GOAL_FORWARD_OFFSET_M * math.cos(initial_yaw)
                    goal_y_raw = initial_xy[1] + GOAL_FORWARD_OFFSET_M * math.sin(initial_yaw)
                    goal_x, goal_y = _clamp_goal_within_map(goal_x_raw, goal_y_raw)
                    result["goal_pose"] = (goal_x, goal_y)

                    goal_pose = _make_pose("map", goal_x, goal_y, initial_yaw)
                    goal_handle = client.send_navigate_to_pose(goal_pose)
                    if goal_handle is None:
                        result["errors"].append("GOAL_REJECTED")
                    else:
                        result["goal_accepted"] = True

                        nav_deadline = time.monotonic() + min(timeout_s, 40.0)
                        while time.monotonic() < nav_deadline:
                            client.spin_for(0.2)
                            if client.raw_nonzero_observed and client.safe_nonzero_observed:
                                break

                        status, _ = client.wait_for_navigate_result(goal_handle, timeout_s=40.0)
                        result["navigate_result"] = status

                        result["odom_messages_received"] = client.odom_messages_received
                        result["raw_messages_received"] = client.raw_messages_received
                        result["safe_messages_received"] = client.safe_messages_received
                        result["raw_nonzero_observed"] = client.raw_nonzero_observed
                        result["safe_nonzero_observed"] = client.safe_nonzero_observed

                        client.spin_for(1.0)
                        final_xy = client.current_xy()
                        result["final_pose"] = final_xy
                        if final_xy is not None:
                            result["distance_moved"] = math.hypot(
                                final_xy[0] - initial_xy[0], final_xy[1] - initial_xy[1]
                            )
                            result["final_distance_to_goal"] = math.hypot(
                                final_xy[0] - goal_x, final_xy[1] - goal_y
                            )

                        twist = client.current_twist()
                        if twist is not None:
                            result["final_twist_zero"] = not _planar_nonzero(*twist)

                        pose_t0 = client.current_xy()
                        client.spin_for(0.5)
                        pose_t1 = client.current_xy()
                        if pose_t0 is not None and pose_t1 is not None:
                            diff = math.hypot(pose_t1[0] - pose_t0[0], pose_t1[1] - pose_t0[1])
                            result["pose_stable"] = diff < POSE_STABLE_TOLERANCE_M
            finally:
                client.destroy_node()

    except Exception as exc:
        result["errors"].append(f"EXCEPTION: {exc}")
    finally:
        if rclpy_initialized:
            try:
                rclpy.shutdown()
            except Exception:
                pass
        result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)

    result["ok"] = (
        not result["errors"]
        and result["bt_navigator_active"]
        and result["goal_accepted"]
        and result["navigate_result"] == "SUCCEEDED"
        and result["odom_messages_received"] > 0
        and result["raw_messages_received"] > 0
        and result["safe_messages_received"] > 0
        and result["raw_nonzero_observed"]
        and result["safe_nonzero_observed"]
        and result["distance_moved"] is not None and result["distance_moved"] > 0.05
        and result["final_distance_to_goal"] is not None and result["final_distance_to_goal"] < GOAL_TOLERANCE_M
        and result["final_twist_zero"]
        and result["pose_stable"]
        and not result["forbidden_velocity_topics_detected"]
        and not result["bt_navigator_direct_velocity_publisher"]
        and not result["hardware_node_detected"]
        and not result["mission_node_detected"]
        and result["orphan_processes"] == 0
    )
    return result


def run_cancel_scenario(namespace: str, domain_id: str, timeout_s: float) -> dict:
    result = {
        "ok": False,
        "scenario": "cancel",
        "domain_id": domain_id,
        "map_server_active": False,
        "planner_server_active": False,
        "controller_server_active": False,
        "collision_monitor_active": False,
        "behavior_server_active": False,
        "bt_navigator_active": False,
        "goal_accepted": False,
        "cancel_precondition_motion_observed": False,
        "raw_nonzero_observed": False,
        "safe_nonzero_observed": False,
        "cancel_response_received": False,
        "cancel_request_accepted": False,
        "cancel_result": "NOT_ATTEMPTED",
        "safe_message_after_cancel": False,
        "odom_message_after_cancel": False,
        "safe_zero_after_cancel": False,
        "odom_zero_after_cancel": False,
        "pose_stable": False,
        "forbidden_velocity_topics_detected": [],
        "hardware_node_detected": False,
        "mission_node_detected": False,
        "orphan_processes": 0,
        "errors": [],
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
        _discover_and_activate(namespace, env, deadline, result)

        nodes = _node_list(env, timeout=5.0)
        result["hardware_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
            for node in nodes
        )
        result["mission_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_MISSION_NODE_SUBSTRINGS)
            for node in nodes
        )

        topics = _topic_list(env, timeout=5.0)
        result["forbidden_velocity_topics_detected"] = [
            t for t in topics if any(t.endswith(suffix) for suffix in FORBIDDEN_VELOCITY_TOPIC_SUFFIXES)
        ]

        if not result["errors"]:
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _BtNavigatorSmokeClient(namespace)
            try:
                client.wait_for_nav_server(timeout_s=15.0)
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    initial_xy = client.current_xy()
                    initial_yaw = client.current_yaw() or 0.0

                    goal_x_raw = initial_xy[0] + CANCEL_GOAL_FORWARD_OFFSET_M * math.cos(initial_yaw)
                    goal_y_raw = initial_xy[1] + CANCEL_GOAL_FORWARD_OFFSET_M * math.sin(initial_yaw)
                    goal_x, goal_y = _clamp_goal_within_map(goal_x_raw, goal_y_raw)

                    goal_pose = _make_pose("map", goal_x, goal_y, initial_yaw)
                    goal_handle = client.send_navigate_to_pose(goal_pose)
                    if goal_handle is None:
                        result["errors"].append("GOAL_REJECTED")
                    else:
                        result["goal_accepted"] = True

                        motion_deadline = time.monotonic() + min(timeout_s, 30.0)
                        while time.monotonic() < motion_deadline:
                            client.spin_for(0.1)
                            current_xy = client.current_xy()
                            moved = (
                                current_xy is not None
                                and math.hypot(
                                    current_xy[0] - initial_xy[0], current_xy[1] - initial_xy[1]
                                ) > CANCEL_PRECONDITION_MOTION_M
                            )
                            if client.raw_nonzero_observed and client.safe_nonzero_observed and moved:
                                result["cancel_precondition_motion_observed"] = True
                                break

                        result["raw_nonzero_observed"] = client.raw_nonzero_observed
                        result["safe_nonzero_observed"] = client.safe_nonzero_observed

                        if not result["cancel_precondition_motion_observed"]:
                            result["errors"].append("CANCEL_PRECONDITION_MOTION_NOT_OBSERVED")
                        else:
                            client.mark_post_cancel_baseline()
                            cancel_outcome = client.request_cancel_and_check_acceptance(
                                goal_handle, timeout_s=15.0
                            )
                            result["cancel_response_received"] = cancel_outcome["cancel_response_received"]
                            result["cancel_request_accepted"] = cancel_outcome["cancel_request_accepted"]
                            if cancel_outcome["errors"]:
                                result["errors"].extend(cancel_outcome["errors"])

                            status, _ = client.wait_for_navigate_result(goal_handle, timeout_s=30.0)
                            result["cancel_result"] = status

                            if status == "CANCELED":
                                # Wait for the full settle window (controller's
                                # stopRobot()/the simulator's cmd_vel watchdog,
                                # 0.5s) to actually bring velocity to zero,
                                # rather than measuring on the first post-cancel
                                # message, which may still carry nonzero motion
                                # from before the stop took effect.
                                client.spin_for(2.0)

                                result["safe_message_after_cancel"] = client.safe_message_received_after_mark()
                                result["odom_message_after_cancel"] = client.odom_message_received_after_mark()

                                safe_twist = client.latest_safe_twist()
                                if safe_twist is not None and result["safe_message_after_cancel"]:
                                    result["safe_zero_after_cancel"] = not _planar_nonzero(*safe_twist)

                                odom_twist = client.current_twist()
                                if odom_twist is not None and result["odom_message_after_cancel"]:
                                    result["odom_zero_after_cancel"] = not _planar_nonzero(*odom_twist)

                                pose_t0 = client.current_xy()
                                client.spin_for(0.5)
                                pose_t1 = client.current_xy()
                                if pose_t0 is not None and pose_t1 is not None:
                                    diff = math.hypot(
                                        pose_t1[0] - pose_t0[0], pose_t1[1] - pose_t0[1]
                                    )
                                    result["pose_stable"] = diff < POSE_STABLE_TOLERANCE_M
            finally:
                client.destroy_node()

    except Exception as exc:
        result["errors"].append(f"EXCEPTION: {exc}")
    finally:
        if rclpy_initialized:
            try:
                rclpy.shutdown()
            except Exception:
                pass
        result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)

    result["ok"] = (
        not result["errors"]
        and result["bt_navigator_active"]
        and result["goal_accepted"]
        and result["cancel_precondition_motion_observed"]
        and result["raw_nonzero_observed"]
        and result["safe_nonzero_observed"]
        and result["cancel_response_received"]
        and result["cancel_request_accepted"]
        and result["cancel_result"] == "CANCELED"
        and result["safe_message_after_cancel"]
        and result["odom_message_after_cancel"]
        and result["safe_zero_after_cancel"]
        and result["odom_zero_after_cancel"]
        and result["pose_stable"]
        and not result["forbidden_velocity_topics_detected"]
        and not result["hardware_node_detected"]
        and not result["mission_node_detected"]
        and result["orphan_processes"] == 0
    )
    return result


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

    domain_success = str(base)
    domain_cancel = str(base + 1)

    print(f"--- Running scenario: SUCCESS on ROS_DOMAIN_ID={domain_success} ---")
    success_result = run_success_scenario(args.namespace, domain_success, args.timeout)
    print(f"Scenario SUCCESS outcome: {'PASS' if success_result['ok'] else 'FAIL'}")

    print(f"--- Running scenario: CANCEL on ROS_DOMAIN_ID={domain_cancel} ---")
    cancel_result = run_cancel_scenario(args.namespace, domain_cancel, args.timeout)
    print(f"Scenario CANCEL outcome: {'PASS' if cancel_result['ok'] else 'FAIL'}")

    all_ok = success_result["ok"] and cancel_result["ok"]
    decision = "PASS" if all_ok else "FAIL"

    report = {
        "ok": all_ok,
        "decision": decision,
        "namespace": args.namespace,
        "base_domain_id": args.base_domain_id,
        "scenarios": {
            "success": success_result,
            "cancel": cancel_result,
        },
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")

    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
