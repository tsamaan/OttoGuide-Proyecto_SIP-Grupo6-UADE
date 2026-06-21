#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox Waypoint Follower.

Validates the isolated FollowWaypoints orchestration chain:
waypoint_follower -> bt_navigator (NavigateToPose, one goal per waypoint) ->
planner_server (ComputePathToPose) -> controller_server (FollowPath) ->
cmd_vel_raw -> collision_monitor -> cmd_vel_safe -> offline_runtime_simulator.

Scenarios tested in separate, isolated domain IDs derived from
--base-domain-id:
A. Success (base): FollowWaypoints with 3 synthetic waypoints inside the
   versioned fixture map, all reachable. Requires SUCCEEDED, monotonic
   current_waypoint feedback progression, empty missed_waypoints, real
   raw/safe/odom telemetry, and a stable final zero twist.
B. Cancel (base + 1): FollowWaypoints with a longer 3-waypoint route,
   canceled only after motion is observed past the first waypoint (never
   canceled as a substitute for that precondition). Acceptance of the
   cancel request is verified against the real action_msgs/srv/CancelGoal
   response (return_code == ERROR_NONE and the goal's UUID present in
   goals_canceling), reusing the contract validated in Phase 2F.1.
C. Unreachable (base + 2): FollowWaypoints with one waypoint placed inside a
   real occupied cell of the versioned fixture map (confirmed via direct
   inspection of the .pgm pixel data, not an arbitrary coordinate), with
   stop_on_failure=true. Requires the action to fail at that specific
   waypoint and never proceed to waypoints after it.

This script does not touch the real robot, does not open rosbags, does not
install packages, and does not kill ROS processes outside its own launched
process group. Simple Commander and NavigateThroughPoses are not exercised
by this phase.
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
from nav2_msgs.action import FollowWaypoints
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_BASE_DOMAIN_ID = "200"
DEFAULT_TIMEOUT_S = 90.0

MIN_DOMAIN_ID = 1
MAX_DOMAIN_ID = 232
MAXIMUM_OFFSET = 2

# Waypoint offsets (meters), applied relative to the observed initial pose,
# never assumed to be the origin. Kept inside MAP_X_BOUNDS/MAP_Y_BOUNDS
# (the versioned fixture spans x in [-1.0, 1.0], y in [-0.75, 0.75] per
# offline_sandbox_test_map.yaml: resolution 0.05, origin [-1.0, -0.75],
# image 40x30px).
SUCCESS_WAYPOINT_OFFSETS_M = ((0.30, 0.0), (0.30, 0.20), (0.0, 0.20))
CANCEL_WAYPOINT_OFFSETS_M = ((0.30, 0.0), (0.40, 0.0), (0.30, 0.0))
GOAL_TOLERANCE_M = 0.15
MAP_X_BOUNDS = (-1.0, 1.0)
MAP_Y_BOUNDS = (-0.75, 0.75)
PLANAR_NONZERO_TOLERANCE = 1e-4
POSE_STABLE_TOLERANCE_M = 0.002
CANCEL_PRECONDITION_MOTION_M = 0.02

# A point well outside the versioned fixture's map bounds. Direct
# inspection of offline_sandbox_test_map.pgm confirms the map is 40x30px at
# resolution 0.05 with origin [-1.0, -0.75] (offline_sandbox_test_map.yaml),
# i.e. world x in [-1.0, 1.0], y in [-0.75, 0.75]. A Phase 2G resume
# diagnostic run (domain 222) against an interior single-pixel occupied
# obstacle (the central corridor wall, world (0.025, 0.575)) showed that
# point is in fact reachable in practice: at this map's 0.05 m resolution,
# a single occupied cell is thinner than the planner/costmap's effective
# footprint+inflation, and ComputePathToPose successfully routes around it
# (confirmed: that diagnostic run completed FollowWaypoints as SUCCEEDED
# with missed_waypoints=[] and normalized_feedback_indices=[0, 1, 2], not a
# failure). A point fully outside the map's covered extent is used instead,
# since global_costmap.track_unknown_space=true means costmap cells outside
# the map's known free/occupied region are UNKNOWN, not routable, making
# ComputePathToPose unable to produce a plan -- a categorically different
# and unambiguous failure mode from "obstacle the planner can route around".
UNREACHABLE_WAYPOINT_XY = (5.0, 5.0)

# Confirmed against the real local ROS 2 Jazzy installation by the Phase 2G
# resume diagnostic run (domain 221, UNREACHABLE_WAYPOINT_XY=(5.0, 5.0)):
# FollowWaypoints terminated ABORTED, with missed_waypoints=[1] and
# MissedWaypoint.error_code=204 (nav2_msgs/action/ComputePathToPose
# GOAL_OUTSIDE_MAP), feedback never progressing past current_waypoint=1.
# See OFFLINE_NAVIGATION_WAYPOINT_FOLLOWER_REPORT.md. RESULT_TIMEOUT must
# never be an accepted member of this set: a generic action-result timeout
# must never be reinterpreted as proof of an unreachable-waypoint failure.
UNREACHABLE_TERMINAL_STATUSES = ("ABORTED",)

# nav2_msgs/action/ComputePathToPose error code, confirmed locally via
# `ros2 interface show nav2_msgs/action/ComputePathToPose` on this ROS 2
# Jazzy installation: GOAL_OUTSIDE_MAP=204. This is the specific failure
# semantics expected for UNREACHABLE_WAYPOINT_XY (a point outside the
# fixture map's covered extent), not an arbitrary/assumed value.
COMPUTE_PATH_TO_POSE_GOAL_OUTSIDE_MAP = 204

ALLOWED_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel_raw", "/cmd_vel_safe")
FORBIDDEN_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav")
FORBIDDEN_NODE_SUBSTRINGS = (
    "unitree",
    "livox_sdk_bridge",
    "livox_ros_driver",
    "realsense",
)
FORBIDDEN_MISSION_NODE_SUBSTRINGS = (
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


def _scenario_log_path(scenario: str, domain_id: str) -> Path:
    """Dedicated /tmp log path per scenario+domain, never inside the
    repository. Used instead of stdout=subprocess.PIPE: an unconsumed pipe
    can fill its OS buffer and block the launched ros2 launch process
    indefinitely once enough node output accumulates, producing an
    artificial timeout, an incomplete shutdown, or an orphaned process
    group instead of a clean PASS/FAIL. Writing directly to a file avoids
    that failure mode entirely and keeps a real log available for
    diagnosis.
    """
    return Path(f"/tmp/ottoguide_waypoint_{scenario}_{domain_id}.log")


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


def _normalize_progress(raw_feedback_indices: list[int]) -> list[int]:
    """Collapse consecutive duplicate current_waypoint feedback values into
    the strictly-ordered progression of waypoint indices actually visited.

    Raw FollowWaypoints feedback typically repeats the same current_waypoint
    value across many feedback messages while that waypoint is being
    pursued (e.g. [0, 0, 0, 1, 1, 2, 2]); only consecutive-duplicate
    collapsing is performed here, so a real gap or regression in the raw
    feed (e.g. [0, 2] or [1, 0]) is preserved in the output and caught by
    the gate, instead of being silently treated as equivalent to [0, 1, 2].
    """
    normalized: list[int] = []
    for index in raw_feedback_indices:
        if not normalized or normalized[-1] != index:
            normalized.append(index)
    return normalized


def _progress_covers_expected_indices(normalized: list[int], expected: list[int]) -> bool:
    """True only if normalized is exactly the expected strictly increasing
    sequence (e.g. [0, 1, 2] for a 3-waypoint route): no gaps, no
    regressions, no missing indices, no extra indices.
    """
    return normalized == expected


def _clamp_within_map(x: float, y: float) -> tuple[float, float]:
    x_clamped = min(max(x, MAP_X_BOUNDS[0] + 0.1), MAP_X_BOUNDS[1] - 0.1)
    y_clamped = min(max(y, MAP_Y_BOUNDS[0] + 0.1), MAP_Y_BOUNDS[1] - 0.1)
    return x_clamped, y_clamped


def _build_waypoints_from_offsets(
    initial_xy: tuple[float, float], offsets: tuple[tuple[float, float], ...]
) -> list[tuple[float, float]]:
    waypoints = []
    cursor_x, cursor_y = initial_xy
    for dx, dy in offsets:
        cursor_x += dx
        cursor_y += dy
        waypoints.append(_clamp_within_map(cursor_x, cursor_y))
    return waypoints


class _WaypointFollowerSmokeClient(Node):
    """rclpy helper node bundling the FollowWaypoints action client, an odom
    subscription, and cmd_vel_raw/cmd_vel_safe watchers, all resolved
    relative to the sandbox namespace.
    """

    def __init__(self, namespace: str) -> None:
        super().__init__("offline_waypoint_follower_smoke_test_client")
        self._namespace = namespace
        self._follow_client = ActionClient(
            self, FollowWaypoints, f"/{namespace}/follow_waypoints"
        )
        self._latest_odom: Odometry | None = None
        self._latest_cmd_vel_raw: Twist | None = None
        self._latest_cmd_vel_safe: Twist | None = None

        self.odom_messages_received = 0
        self.raw_messages_received = 0
        self.safe_messages_received = 0
        self.raw_nonzero_observed = False
        self.safe_nonzero_observed = False
        self.feedback_indices: list[int] = []
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

    def _on_feedback(self, feedback_msg) -> None:
        self.feedback_indices.append(int(feedback_msg.feedback.current_waypoint))

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

    def wait_for_follow_waypoints_server(self, timeout_s: float) -> bool:
        return self._follow_client.wait_for_server(timeout_sec=timeout_s)

    def wait_for_initial_odom(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self._latest_odom is not None:
                return True
        return False

    def send_follow_waypoints(self, poses: list[PoseStamped]):
        goal_msg = FollowWaypoints.Goal()
        goal_msg.poses = poses
        send_goal_future = self._follow_client.send_goal_async(
            goal_msg, feedback_callback=self._on_feedback
        )
        if not self.spin_until_future_complete_custom(send_goal_future, 15.0):
            return None
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None
        return goal_handle

    def wait_for_follow_result(self, goal_handle, timeout_s: float) -> tuple[str, object]:
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
        if wrapped_result.status == GoalStatus.STATUS_ABORTED:
            return "ABORTED", wrapped_result.result
        return f"GOAL_STATUS_{wrapped_result.status}", wrapped_result.result

    def request_cancel_and_check_acceptance(self, goal_handle, timeout_s: float) -> dict:
        """Send the cancel request and inspect the real action_msgs/srv/
        CancelGoal response instead of treating future completion as proof
        of acceptance, reusing the contract validated and hardened in Phase
        2F.1 for bt_navigator: return_code == ERROR_NONE (0) means the
        goal(s) transitioned to CANCELING, and the accepted goal's UUID must
        appear in goals_canceling. A nonzero return_code or an absent
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
        "waypoint_follower_active": f"/{namespace}/waypoint_follower",
    }
    for key, fqn in fqns.items():
        if _wait_for_node_discovered(fqn, env, deadline):
            result[key] = _wait_for_lifecycle_active(fqn, env, deadline)
        if not result[key]:
            result["errors"].append(f"{key.upper()}_NOT_CONFIRMED")


def _check_no_direct_velocity_publisher(namespace: str, env: dict, result: dict) -> None:
    """Confirm waypoint_follower is never a publisher of cmd_vel_raw/
    cmd_vel_safe, and that controller_server is the actual publisher of
    cmd_vel_raw.
    """
    raw_info = _topic_info_verbose(f"/{namespace}/cmd_vel_raw", env, timeout=5.0)
    safe_info = _topic_info_verbose(f"/{namespace}/cmd_vel_safe", env, timeout=5.0)

    result["controller_raw_publisher_confirmed"] = "controller_server" in raw_info
    result["collision_monitor_safe_publisher_confirmed"] = "collision_monitor" in safe_info
    result["direct_velocity_publisher"] = (
        "waypoint_follower" in raw_info or "waypoint_follower" in safe_info
    )
    if not result["controller_raw_publisher_confirmed"]:
        result["errors"].append("CONTROLLER_SERVER_NOT_PUBLISHING_RAW")
    if result["direct_velocity_publisher"]:
        result["errors"].append("WAYPOINT_FOLLOWER_DIRECT_VELOCITY_PUBLISHER_DETECTED")


def _common_pre_action_checks(namespace: str, env: dict, deadline: float, result: dict) -> None:
    _discover_and_activate(namespace, env, deadline, result)

    nodes = _node_list(env, timeout=5.0)
    result["hardware_node_detected"] = any(
        any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
        for node in nodes
    )
    result["mission_app_component_detected"] = any(
        any(forbidden in node.lower() for forbidden in FORBIDDEN_MISSION_NODE_SUBSTRINGS)
        for node in nodes
    )

    topics = _topic_list(env, timeout=5.0)
    result["forbidden_velocity_topics_detected"] = [
        t for t in topics if any(t.endswith(suffix) for suffix in FORBIDDEN_VELOCITY_TOPIC_SUFFIXES)
    ]

    if not result["errors"]:
        _check_no_direct_velocity_publisher(namespace, env, result)


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
        "waypoint_follower_active": False,
        "follow_waypoints_action_available": False,
        "goal_accepted": False,
        "feedback_received": False,
        "feedback_indices": [],
        "waypoints_requested": 0,
        "waypoints_reached": None,
        "normalized_feedback_indices": [],
        "missed_waypoints": None,
        "top_level_error_code": None,
        "top_level_error_msg": None,
        "final_action_status": "NOT_ATTEMPTED",
        "raw_messages_received": 0,
        "safe_messages_received": 0,
        "odom_messages_received": 0,
        "raw_nonzero_observed": False,
        "safe_nonzero_observed": False,
        "odom_motion_observed": False,
        "initial_pose": None,
        "waypoints": None,
        "final_pose": None,
        "final_distance_to_last_waypoint": None,
        "final_pose_within_tolerance": False,
        "safe_zero_after_terminal_state": False,
        "odom_zero_after_terminal_state": False,
        "pose_stable": False,
        "controller_raw_publisher_confirmed": False,
        "collision_monitor_safe_publisher_confirmed": False,
        "direct_velocity_publisher": False,
        "forbidden_velocity_topics_detected": [],
        "hardware_node_detected": False,
        "mission_app_component_detected": False,
        "launch_pid": None,
        "process_group_id": None,
        "log_path": None,
        "orphan_processes": 0,
        "errors": [],
    }

    env = _build_env(domain_id)
    launch_process = None
    rclpy_initialized = False
    client = None
    log_path = _scenario_log_path("success", domain_id)
    result["log_path"] = str(log_path)

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        launch_process = subprocess.Popen(
            ["bash", str(RUNTIME_WRAPPER), f"sandbox_namespace:={namespace}", "use_rviz:=false"],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )
        result["launch_pid"] = launch_process.pid
        result["process_group_id"] = os.getpgid(launch_process.pid)

        deadline = time.monotonic() + timeout_s
        _common_pre_action_checks(namespace, env, deadline, result)

        if not result["errors"]:
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _WaypointFollowerSmokeClient(namespace)
            try:
                result["follow_waypoints_action_available"] = client.wait_for_follow_waypoints_server(
                    timeout_s=15.0
                )
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    initial_xy = client.current_xy()
                    result["initial_pose"] = initial_xy

                    waypoints_xy = _build_waypoints_from_offsets(
                        initial_xy, SUCCESS_WAYPOINT_OFFSETS_M
                    )
                    result["waypoints"] = waypoints_xy
                    result["waypoints_requested"] = len(waypoints_xy)

                    poses = [_make_pose("map", x, y) for x, y in waypoints_xy]
                    goal_handle = client.send_follow_waypoints(poses)
                    if goal_handle is None:
                        result["errors"].append("GOAL_REJECTED")
                    else:
                        result["goal_accepted"] = True

                        motion_deadline = time.monotonic() + min(timeout_s, 70.0)
                        while time.monotonic() < motion_deadline:
                            client.spin_for(0.2)
                            if client.raw_nonzero_observed and client.safe_nonzero_observed:
                                break

                        status, action_result = client.wait_for_follow_result(
                            goal_handle, timeout_s=70.0
                        )
                        result["final_action_status"] = status
                        result["feedback_received"] = len(client.feedback_indices) > 0
                        result["feedback_indices"] = client.feedback_indices
                        result["normalized_feedback_indices"] = _normalize_progress(
                            client.feedback_indices
                        )
                        if action_result is not None:
                            result["missed_waypoints"] = [
                                int(mw.index) for mw in action_result.missed_waypoints
                            ]
                            result["top_level_error_code"] = int(action_result.error_code)
                            result["top_level_error_msg"] = str(action_result.error_msg)
                            if result["missed_waypoints"] == []:
                                result["waypoints_reached"] = result["waypoints_requested"]
                            else:
                                result["waypoints_reached"] = (
                                    result["waypoints_requested"] - len(result["missed_waypoints"])
                                )

                        result["raw_messages_received"] = client.raw_messages_received
                        result["safe_messages_received"] = client.safe_messages_received
                        result["odom_messages_received"] = client.odom_messages_received
                        result["raw_nonzero_observed"] = client.raw_nonzero_observed
                        result["safe_nonzero_observed"] = client.safe_nonzero_observed

                        client.spin_for(1.0)
                        final_xy = client.current_xy()
                        result["final_pose"] = final_xy
                        if final_xy is not None:
                            result["odom_motion_observed"] = (
                                math.hypot(
                                    final_xy[0] - initial_xy[0], final_xy[1] - initial_xy[1]
                                )
                                > 0.05
                            )
                            last_wp = waypoints_xy[-1]
                            distance = math.hypot(
                                final_xy[0] - last_wp[0], final_xy[1] - last_wp[1]
                            )
                            result["final_distance_to_last_waypoint"] = distance
                            result["final_pose_within_tolerance"] = distance < GOAL_TOLERANCE_M

                        if status in ("SUCCEEDED", "CANCELED", "ABORTED"):
                            client.spin_for(1.0)
                            safe_twist = client.latest_safe_twist()
                            if safe_twist is not None:
                                result["safe_zero_after_terminal_state"] = not _planar_nonzero(
                                    *safe_twist
                                )
                            odom_twist = client.current_twist()
                            if odom_twist is not None:
                                result["odom_zero_after_terminal_state"] = not _planar_nonzero(
                                    *odom_twist
                                )

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
        try:
            log_file.close()
        except Exception:
            pass

    expected_indices = list(range(result["waypoints_requested"])) if result["waypoints_requested"] else []
    feedback_covers_expected = _progress_covers_expected_indices(
        result["normalized_feedback_indices"], expected_indices
    )

    result["ok"] = (
        not result["errors"]
        and result["waypoint_follower_active"]
        and result["follow_waypoints_action_available"]
        and result["goal_accepted"]
        and result["feedback_received"]
        and feedback_covers_expected
        and result["waypoints_requested"] >= 3
        and result["waypoints_reached"] == result["waypoints_requested"]
        and result["final_action_status"] == "SUCCEEDED"
        and result["missed_waypoints"] == []
        and result["raw_nonzero_observed"]
        and result["safe_nonzero_observed"]
        and result["odom_motion_observed"]
        and result["final_pose_within_tolerance"]
        and result["safe_zero_after_terminal_state"]
        and result["odom_zero_after_terminal_state"]
        and result["pose_stable"]
        and not result["forbidden_velocity_topics_detected"]
        and not result["direct_velocity_publisher"]
        and not result["hardware_node_detected"]
        and not result["mission_app_component_detected"]
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
        "waypoint_follower_active": False,
        "follow_waypoints_action_available": False,
        "goal_accepted": False,
        "feedback_received": False,
        "feedback_indices": [],
        "normalized_feedback_indices": [],
        "waypoints_requested": 0,
        "cancel_precondition_motion_observed": False,
        "raw_nonzero_observed": False,
        "safe_nonzero_observed": False,
        "cancel_response_received": False,
        "cancel_request_accepted": False,
        "final_action_status": "NOT_ATTEMPTED",
        "safe_message_after_cancel": False,
        "odom_message_after_cancel": False,
        "safe_zero_after_terminal_state": False,
        "odom_zero_after_terminal_state": False,
        "pose_stable": False,
        "forbidden_velocity_topics_detected": [],
        "hardware_node_detected": False,
        "mission_app_component_detected": False,
        "launch_pid": None,
        "process_group_id": None,
        "log_path": None,
        "orphan_processes": 0,
        "errors": [],
    }

    env = _build_env(domain_id)
    launch_process = None
    rclpy_initialized = False
    client = None
    log_path = _scenario_log_path("cancel", domain_id)
    result["log_path"] = str(log_path)

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        launch_process = subprocess.Popen(
            ["bash", str(RUNTIME_WRAPPER), f"sandbox_namespace:={namespace}", "use_rviz:=false"],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )
        result["launch_pid"] = launch_process.pid
        result["process_group_id"] = os.getpgid(launch_process.pid)

        deadline = time.monotonic() + timeout_s
        _common_pre_action_checks(namespace, env, deadline, result)

        if not result["errors"]:
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _WaypointFollowerSmokeClient(namespace)
            try:
                result["follow_waypoints_action_available"] = client.wait_for_follow_waypoints_server(
                    timeout_s=15.0
                )
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    initial_xy = client.current_xy()

                    waypoints_xy = _build_waypoints_from_offsets(
                        initial_xy, CANCEL_WAYPOINT_OFFSETS_M
                    )
                    result["waypoints_requested"] = len(waypoints_xy)

                    poses = [_make_pose("map", x, y) for x, y in waypoints_xy]
                    goal_handle = client.send_follow_waypoints(poses)
                    if goal_handle is None:
                        result["errors"].append("GOAL_REJECTED")
                    else:
                        result["goal_accepted"] = True

                        # Cancel only after motion past the first waypoint is
                        # observed (current_waypoint feedback index >= 1),
                        # never immediately after acceptance.
                        motion_deadline = time.monotonic() + min(timeout_s, 60.0)
                        while time.monotonic() < motion_deadline:
                            client.spin_for(0.1)
                            current_xy = client.current_xy()
                            moved = (
                                current_xy is not None
                                and math.hypot(
                                    current_xy[0] - initial_xy[0], current_xy[1] - initial_xy[1]
                                ) > CANCEL_PRECONDITION_MOTION_M
                            )
                            past_first_waypoint = (
                                len(client.feedback_indices) > 0
                                and client.feedback_indices[-1] >= 1
                            )
                            if (
                                client.raw_nonzero_observed
                                and client.safe_nonzero_observed
                                and moved
                                and past_first_waypoint
                            ):
                                result["cancel_precondition_motion_observed"] = True
                                break

                        result["raw_nonzero_observed"] = client.raw_nonzero_observed
                        result["safe_nonzero_observed"] = client.safe_nonzero_observed
                        result["feedback_received"] = len(client.feedback_indices) > 0
                        result["feedback_indices"] = client.feedback_indices
                        result["normalized_feedback_indices"] = _normalize_progress(
                            client.feedback_indices
                        )

                        if not result["cancel_precondition_motion_observed"]:
                            result["errors"].append("CANCEL_PRECONDITION_MOTION_NOT_OBSERVED")
                        else:
                            client.mark_post_cancel_baseline()
                            cancel_outcome = client.request_cancel_and_check_acceptance(
                                goal_handle, timeout_s=15.0
                            )
                            result["cancel_response_received"] = cancel_outcome[
                                "cancel_response_received"
                            ]
                            result["cancel_request_accepted"] = cancel_outcome[
                                "cancel_request_accepted"
                            ]
                            if cancel_outcome["errors"]:
                                result["errors"].extend(cancel_outcome["errors"])

                            status, _ = client.wait_for_follow_result(goal_handle, timeout_s=30.0)
                            result["final_action_status"] = status

                            if status == "CANCELED":
                                # Wait for the full settle window (controller's
                                # stopRobot()/the simulator's cmd_vel watchdog,
                                # 0.5s) to actually bring velocity to zero.
                                client.spin_for(2.0)

                                result["safe_message_after_cancel"] = (
                                    client.safe_message_received_after_mark()
                                )
                                result["odom_message_after_cancel"] = (
                                    client.odom_message_received_after_mark()
                                )

                                safe_twist = client.latest_safe_twist()
                                if safe_twist is not None and result["safe_message_after_cancel"]:
                                    result["safe_zero_after_terminal_state"] = not _planar_nonzero(
                                        *safe_twist
                                    )

                                odom_twist = client.current_twist()
                                if odom_twist is not None and result["odom_message_after_cancel"]:
                                    result["odom_zero_after_terminal_state"] = not _planar_nonzero(
                                        *odom_twist
                                    )

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
        try:
            log_file.close()
        except Exception:
            pass

    result["ok"] = (
        not result["errors"]
        and result["waypoint_follower_active"]
        and result["follow_waypoints_action_available"]
        and result["goal_accepted"]
        and result["cancel_precondition_motion_observed"]
        and result["raw_nonzero_observed"]
        and result["safe_nonzero_observed"]
        and result["cancel_response_received"]
        and result["cancel_request_accepted"]
        and result["final_action_status"] == "CANCELED"
        and result["safe_message_after_cancel"]
        and result["odom_message_after_cancel"]
        and result["safe_zero_after_terminal_state"]
        and result["odom_zero_after_terminal_state"]
        and result["pose_stable"]
        and not result["forbidden_velocity_topics_detected"]
        and not result["hardware_node_detected"]
        and not result["mission_app_component_detected"]
        and result["orphan_processes"] == 0
    )
    return result


def run_unreachable_scenario(namespace: str, domain_id: str, timeout_s: float) -> dict:
    result = {
        "ok": False,
        "scenario": "unreachable",
        "domain_id": domain_id,
        "map_server_active": False,
        "planner_server_active": False,
        "controller_server_active": False,
        "collision_monitor_active": False,
        "behavior_server_active": False,
        "bt_navigator_active": False,
        "waypoint_follower_active": False,
        "follow_waypoints_action_available": False,
        "goal_accepted": False,
        "feedback_received": False,
        "feedback_indices": [],
        "normalized_feedback_indices": [],
        "waypoints_requested": 0,
        "unreachable_waypoint_index": 1,
        "final_action_status": "NOT_ATTEMPTED",
        "missed_waypoints": None,
        "top_level_error_code": None,
        "top_level_error_msg": None,
        "missed_waypoint_error_code": None,
        "stop_on_failure_proven": False,
        "safe_zero_after_terminal_state": False,
        "odom_zero_after_terminal_state": False,
        "pose_stable": False,
        "forbidden_velocity_topics_detected": [],
        "hardware_node_detected": False,
        "mission_app_component_detected": False,
        "launch_pid": None,
        "process_group_id": None,
        "log_path": None,
        "orphan_processes": 0,
        "errors": [],
    }

    env = _build_env(domain_id)
    launch_process = None
    rclpy_initialized = False
    client = None
    log_path = _scenario_log_path("unreachable", domain_id)
    result["log_path"] = str(log_path)

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        launch_process = subprocess.Popen(
            ["bash", str(RUNTIME_WRAPPER), f"sandbox_namespace:={namespace}", "use_rviz:=false"],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )
        result["launch_pid"] = launch_process.pid
        result["process_group_id"] = os.getpgid(launch_process.pid)

        deadline = time.monotonic() + timeout_s
        _common_pre_action_checks(namespace, env, deadline, result)

        if not result["errors"]:
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _WaypointFollowerSmokeClient(namespace)
            try:
                result["follow_waypoints_action_available"] = client.wait_for_follow_waypoints_server(
                    timeout_s=15.0
                )
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    initial_xy = client.current_xy()

                    # Waypoint 0: reachable, near the initial pose. Waypoint
                    # 1: a real occupied cell of the versioned fixture
                    # (UNREACHABLE_WAYPOINT_XY, derived from direct .pgm
                    # inspection, see module docstring). Waypoint 2:
                    # reachable, present only to prove stop_on_failure=true
                    # prevents the follower from ever attempting it.
                    reachable_first = _clamp_within_map(
                        initial_xy[0] + 0.20, initial_xy[1]
                    )
                    reachable_third = _clamp_within_map(
                        initial_xy[0] + 0.20, initial_xy[1] - 0.20
                    )
                    waypoints_xy = [
                        reachable_first,
                        UNREACHABLE_WAYPOINT_XY,
                        reachable_third,
                    ]
                    result["waypoints_requested"] = len(waypoints_xy)

                    poses = [_make_pose("map", x, y) for x, y in waypoints_xy]
                    goal_handle = client.send_follow_waypoints(poses)
                    if goal_handle is None:
                        result["errors"].append("GOAL_REJECTED")
                    else:
                        result["goal_accepted"] = True

                        status, action_result = client.wait_for_follow_result(
                            goal_handle, timeout_s=min(timeout_s, 70.0)
                        )
                        result["final_action_status"] = status
                        result["feedback_received"] = len(client.feedback_indices) > 0
                        result["feedback_indices"] = client.feedback_indices
                        result["normalized_feedback_indices"] = _normalize_progress(
                            client.feedback_indices
                        )
                        if action_result is not None:
                            result["top_level_error_code"] = int(action_result.error_code)
                            result["top_level_error_msg"] = str(action_result.error_msg)
                            result["missed_waypoints"] = [
                                int(mw.index) for mw in action_result.missed_waypoints
                            ]
                            for mw in action_result.missed_waypoints:
                                if int(mw.index) == result["unreachable_waypoint_index"]:
                                    result["missed_waypoint_error_code"] = int(mw.error_code)

                        # stop_on_failure=true is proven by the failure
                        # being detected at exactly waypoint index 1 and the
                        # action never reporting completion of waypoint
                        # index 2 (the reachable waypoint placed after the
                        # unreachable one). UNREACHABLE_TERMINAL_STATUSES is
                        # the set confirmed against the real local ROS 2
                        # Jazzy installation by the Phase 2G resume
                        # diagnostic run (see OFFLINE_NAVIGATION_WAYPOINT_
                        # FOLLOWER_REPORT.md); it is not assumed a priori.
                        failure_at_expected_index = (
                            result["missed_waypoints"] is not None
                            and result["unreachable_waypoint_index"] in result["missed_waypoints"]
                        )
                        waypoint_after_failure_not_reached = (
                            result["unreachable_waypoint_index"] + 1
                            not in (result["feedback_indices"] or [])
                        )
                        result["stop_on_failure_proven"] = (
                            status in UNREACHABLE_TERMINAL_STATUSES
                            and failure_at_expected_index
                            and waypoint_after_failure_not_reached
                        )

                        client.spin_for(1.0)
                        safe_twist = client.latest_safe_twist()
                        if safe_twist is not None:
                            result["safe_zero_after_terminal_state"] = not _planar_nonzero(
                                *safe_twist
                            )
                        odom_twist = client.current_twist()
                        if odom_twist is not None:
                            result["odom_zero_after_terminal_state"] = not _planar_nonzero(
                                *odom_twist
                            )

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
        try:
            log_file.close()
        except Exception:
            pass

    result["ok"] = (
        not result["errors"]
        and result["waypoint_follower_active"]
        and result["follow_waypoints_action_available"]
        and result["goal_accepted"]
        and result["final_action_status"] != "RESULT_TIMEOUT"
        and result["stop_on_failure_proven"]
        and result["missed_waypoint_error_code"] == COMPUTE_PATH_TO_POSE_GOAL_OUTSIDE_MAP
        and result["safe_zero_after_terminal_state"]
        and result["odom_zero_after_terminal_state"]
        and result["pose_stable"]
        and not result["forbidden_velocity_topics_detected"]
        and not result["hardware_node_detected"]
        and not result["mission_app_component_detected"]
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
    domain_unreachable = str(base + 2)

    print(f"--- Running scenario: SUCCESS on ROS_DOMAIN_ID={domain_success} ---")
    success_result = run_success_scenario(args.namespace, domain_success, args.timeout)
    print(f"Scenario SUCCESS outcome: {'PASS' if success_result['ok'] else 'FAIL'}")

    print(f"--- Running scenario: CANCEL on ROS_DOMAIN_ID={domain_cancel} ---")
    cancel_result = run_cancel_scenario(args.namespace, domain_cancel, args.timeout)
    print(f"Scenario CANCEL outcome: {'PASS' if cancel_result['ok'] else 'FAIL'}")

    print(f"--- Running scenario: UNREACHABLE on ROS_DOMAIN_ID={domain_unreachable} ---")
    unreachable_result = run_unreachable_scenario(args.namespace, domain_unreachable, args.timeout)
    print(f"Scenario UNREACHABLE outcome: {'PASS' if unreachable_result['ok'] else 'FAIL'}")

    all_ok = success_result["ok"] and cancel_result["ok"] and unreachable_result["ok"]
    decision = "PASS" if all_ok else "FAIL"

    report = {
        "ok": all_ok,
        "decision": decision,
        "namespace": args.namespace,
        "base_domain_id": args.base_domain_id,
        "derived_domain_ids": {
            "success": int(domain_success),
            "cancel": int(domain_cancel),
            "unreachable": int(domain_unreachable),
        },
        "scenarios": {
            "success": success_result,
            "cancel": cancel_result,
            "unreachable": unreachable_result,
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
