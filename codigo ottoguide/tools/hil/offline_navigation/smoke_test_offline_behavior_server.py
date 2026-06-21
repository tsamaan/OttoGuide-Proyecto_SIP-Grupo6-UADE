#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox Behavior Server.

Validates the isolated behavior chain (Wait, Spin plugins only):
behavior_server -> cmd_vel_raw -> collision_monitor -> cmd_vel_safe -> offline_runtime_simulator

Scenarios tested in separate, isolated domain IDs:
A. Wait: Wait action SUCCEEDED with zero motion, zero odom twist, and no
   nonzero safe command ever observed.
B. Spin: Spin action with a small synthetic target_yaw observes nonzero raw
   and safe angular velocity, a yaw change, and SUCCEEDED with the final
   angular error within tolerance, minimal translation, and zero final twist.
C. Cancel Spin: Spin with a larger target_yaw is canceled mid-motion; the
   action reports CANCELED, cmd_vel_safe settles to zero, and the pose is
   stable for at least 0.5s afterward.

This script does not touch the real robot, does not open rosbags, does not
install packages, and does not kill ROS processes outside its own launched
process group. BT Navigator, Waypoint Follower and Simple Commander are not
exercised by this phase.
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
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import Twist
from nav2_msgs.action import Spin, Wait
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_BASE_DOMAIN_ID = "220"
DEFAULT_TIMEOUT_S = 60.0

WAIT_DURATION_S = 1.0
SPIN_TARGET_YAW_RAD = 0.50
SPIN_YAW_TOLERANCE_RAD = 0.15
CANCEL_SPIN_TARGET_YAW_RAD = 3.0

ALLOWED_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel_raw", "/cmd_vel_safe")
FORBIDDEN_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav")
FORBIDDEN_NODE_SUBSTRINGS = (
    "unitree",
    "livox_sdk_bridge",
    "livox_ros_driver",
    "realsense",
)
FORBIDDEN_MISSION_NODE_SUBSTRINGS = (
    "bt_navigator",
    "waypoint_follower",
    "simple_commander",
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


class _BehaviorServerSmokeClient(Node):
    """rclpy helper node bundling the Wait/Spin action clients, an odom
    subscription, and cmd_vel_raw/cmd_vel_safe watchers, all resolved
    relative to the sandbox namespace.
    """

    def __init__(self, namespace: str) -> None:
        super().__init__("offline_behavior_server_smoke_test_client")
        self._namespace = namespace
        self._wait_client = ActionClient(self, Wait, f"/{namespace}/wait")
        self._spin_client = ActionClient(self, Spin, f"/{namespace}/spin")
        self._latest_odom: Odometry | None = None
        self._latest_cmd_vel_raw: Twist | None = None
        self._latest_cmd_vel_safe: Twist | None = None
        self.raw_angular_observed: float | None = None
        self.safe_angular_observed: float | None = None

        self.create_subscription(Odometry, f"/{namespace}/odom", self._on_odom, 10)
        self.create_subscription(Twist, f"/{namespace}/cmd_vel_raw", self._on_cmd_vel_raw, 10)
        self.create_subscription(Twist, f"/{namespace}/cmd_vel_safe", self._on_cmd_vel_safe, 10)

    def _on_odom(self, msg: Odometry) -> None:
        self._latest_odom = msg

    def _on_cmd_vel_raw(self, msg: Twist) -> None:
        self._latest_cmd_vel_raw = msg
        if abs(msg.angular.z) > 1e-4:
            if self.raw_angular_observed is None or abs(msg.angular.z) > self.raw_angular_observed:
                self.raw_angular_observed = abs(msg.angular.z)

    def _on_cmd_vel_safe(self, msg: Twist) -> None:
        self._latest_cmd_vel_safe = msg
        if abs(msg.angular.z) > 1e-4:
            if self.safe_angular_observed is None or abs(msg.angular.z) > self.safe_angular_observed:
                self.safe_angular_observed = abs(msg.angular.z)

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

    def wait_for_wait_server(self, timeout_s: float) -> bool:
        return self._wait_client.wait_for_server(timeout_sec=timeout_s)

    def wait_for_spin_server(self, timeout_s: float) -> bool:
        return self._spin_client.wait_for_server(timeout_sec=timeout_s)

    def wait_for_initial_odom(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self._latest_odom is not None:
                return True
        return False

    def send_wait(self, duration_s: float, timeout_s: float) -> tuple[str, object]:
        goal_msg = Wait.Goal()
        goal_msg.time = Duration(sec=int(duration_s), nanosec=int((duration_s % 1.0) * 1e9))
        send_goal_future = self._wait_client.send_goal_async(goal_msg)
        if not self.spin_until_future_complete_custom(send_goal_future, 15.0):
            return "GOAL_SEND_TIMEOUT", None
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return "GOAL_REJECTED", None
        result_future = goal_handle.get_result_async()
        if not self.spin_until_future_complete_custom(result_future, timeout_s):
            return "RESULT_TIMEOUT", None
        wrapped_result = result_future.result()
        if wrapped_result is None:
            return "RESULT_NONE", None
        if wrapped_result.status != GoalStatus.STATUS_SUCCEEDED:
            return f"GOAL_STATUS_{wrapped_result.status}", None
        return "SUCCEEDED", wrapped_result.result

    def send_spin_cancelable(self, target_yaw: float, time_allowance_s: float):
        goal_msg = Spin.Goal()
        goal_msg.target_yaw = float(target_yaw)
        goal_msg.time_allowance = Duration(sec=int(time_allowance_s), nanosec=0)
        send_goal_future = self._spin_client.send_goal_async(goal_msg)
        if not self.spin_until_future_complete_custom(send_goal_future, 15.0):
            return None
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None
        return goal_handle

    def wait_for_spin_result(self, goal_handle, timeout_s: float) -> tuple[str, object]:
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

    def cancel_and_wait(self, goal_handle, timeout_s: float) -> str:
        cancel_future = goal_handle.cancel_goal_async()
        if not self.spin_until_future_complete_custom(cancel_future, timeout_s):
            return "CANCEL_REQUEST_TIMEOUT"
        status, _ = self.wait_for_spin_result(goal_handle, timeout_s)
        return status


def _discover_and_activate(
    namespace: str, env: dict, deadline: float, result: dict
) -> None:
    map_fqn = f"/{namespace}/map_server"
    planner_fqn = f"/{namespace}/planner_server"
    controller_fqn = f"/{namespace}/controller_server"
    collision_monitor_fqn = f"/{namespace}/collision_monitor"
    behavior_server_fqn = f"/{namespace}/behavior_server"

    for fqn, key in (
        (map_fqn, "map_server_active"),
        (planner_fqn, "planner_server_active"),
        (controller_fqn, "controller_server_active"),
        (collision_monitor_fqn, "collision_monitor_active"),
        (behavior_server_fqn, "behavior_server_active"),
    ):
        if _wait_for_node_discovered(fqn, env, deadline):
            result[key] = _wait_for_lifecycle_active(fqn, env, deadline)
        if not result[key]:
            result["errors"].append(f"{key.upper()}_NOT_CONFIRMED")


def run_wait_scenario(namespace: str, domain_id: str, timeout_s: float) -> dict:
    result = {
        "ok": False,
        "scenario": "wait",
        "domain_id": domain_id,
        "map_server_active": False,
        "planner_server_active": False,
        "controller_server_active": False,
        "collision_monitor_active": False,
        "behavior_server_active": False,
        "wait_result": "NOT_ATTEMPTED",
        "pose_stable": False,
        "odom_twist_zero": False,
        "safe_nonzero_detected": False,
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

            client = _BehaviorServerSmokeClient(namespace)
            try:
                client.wait_for_wait_server(timeout_s=15.0)
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    pose_before = client.current_xy()
                    status, _ = client.send_wait(WAIT_DURATION_S, timeout_s=20.0)
                    result["wait_result"] = status

                    client.spin_for(0.5)
                    pose_after = client.current_xy()
                    if pose_before is not None and pose_after is not None:
                        diff = math.hypot(
                            pose_after[0] - pose_before[0], pose_after[1] - pose_before[1]
                        )
                        result["pose_stable"] = diff < 0.002

                    twist = client.current_twist()
                    if twist is not None:
                        result["odom_twist_zero"] = abs(twist[0]) < 1e-5 and abs(twist[1]) < 1e-5

                    result["safe_nonzero_detected"] = client.safe_angular_observed is not None
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
        and result["behavior_server_active"]
        and result["wait_result"] == "SUCCEEDED"
        and result["pose_stable"]
        and result["odom_twist_zero"]
        and not result["safe_nonzero_detected"]
        and not result["forbidden_velocity_topics_detected"]
        and not result["hardware_node_detected"]
        and not result["mission_node_detected"]
        and result["orphan_processes"] == 0
    )
    return result


def run_spin_scenario(namespace: str, domain_id: str, timeout_s: float) -> dict:
    result = {
        "ok": False,
        "scenario": "spin",
        "domain_id": domain_id,
        "map_server_active": False,
        "planner_server_active": False,
        "controller_server_active": False,
        "collision_monitor_active": False,
        "behavior_server_active": False,
        "spin_result": "NOT_ATTEMPTED",
        "raw_angular_observed": None,
        "safe_angular_observed": None,
        "yaw_change": None,
        "final_angular_error": None,
        "translation": None,
        "final_twist_zero": False,
        "pose_stable_after": False,
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

            client = _BehaviorServerSmokeClient(namespace)
            try:
                client.wait_for_spin_server(timeout_s=15.0)
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    pose_before = client.current_xy()
                    yaw_before = client.current_yaw()

                    goal_handle = client.send_spin_cancelable(
                        SPIN_TARGET_YAW_RAD, time_allowance_s=10.0
                    )
                    if goal_handle is None:
                        result["errors"].append("SPIN_GOAL_REJECTED")
                    else:
                        status, _ = client.wait_for_spin_result(goal_handle, timeout_s=20.0)
                        result["spin_result"] = status

                        result["raw_angular_observed"] = client.raw_angular_observed
                        result["safe_angular_observed"] = client.safe_angular_observed

                        # Let the simulator's cmd_vel watchdog (0.5s) expire
                        # and the explicit zero cmd_vel that behavior_server
                        # publishes on completion propagate and settle.
                        client.spin_for(1.0)
                        pose_after = client.current_xy()
                        yaw_after = client.current_yaw()

                        if yaw_before is not None and yaw_after is not None:
                            result["yaw_change"] = abs(yaw_after - yaw_before)
                            result["final_angular_error"] = abs(
                                result["yaw_change"] - SPIN_TARGET_YAW_RAD
                            )
                        if pose_before is not None and pose_after is not None:
                            result["translation"] = math.hypot(
                                pose_after[0] - pose_before[0], pose_after[1] - pose_before[1]
                            )

                        twist = client.current_twist()
                        if twist is not None:
                            result["final_twist_zero"] = (
                                abs(twist[0]) < 1e-5 and abs(twist[1]) < 1e-5
                            )

                        pose_t0 = client.current_xy()
                        client.spin_for(0.5)
                        pose_t1 = client.current_xy()
                        if pose_t0 is not None and pose_t1 is not None:
                            diff = math.hypot(
                                pose_t1[0] - pose_t0[0], pose_t1[1] - pose_t0[1]
                            )
                            result["pose_stable_after"] = diff < 0.002
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
        and result["behavior_server_active"]
        and result["raw_angular_observed"] is not None
        and result["safe_angular_observed"] is not None
        and result["yaw_change"] is not None and result["yaw_change"] > 0.05
        and result["spin_result"] == "SUCCEEDED"
        and result["final_angular_error"] is not None
        and result["final_angular_error"] < SPIN_YAW_TOLERANCE_RAD
        and result["translation"] is not None and result["translation"] < 0.02
        and result["final_twist_zero"]
        and result["pose_stable_after"]
        and not result["forbidden_velocity_topics_detected"]
        and not result["hardware_node_detected"]
        and not result["mission_node_detected"]
        and result["orphan_processes"] == 0
    )
    return result


def run_cancel_spin_scenario(namespace: str, domain_id: str, timeout_s: float) -> dict:
    result = {
        "ok": False,
        "scenario": "cancel_spin",
        "domain_id": domain_id,
        "map_server_active": False,
        "planner_server_active": False,
        "controller_server_active": False,
        "collision_monitor_active": False,
        "behavior_server_active": False,
        "motion_observed": False,
        "raw_angular_observed": None,
        "safe_angular_observed": None,
        "cancel_result": "NOT_ATTEMPTED",
        "safe_angular_zero_after_cancel": False,
        "odom_twist_zero": False,
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

            client = _BehaviorServerSmokeClient(namespace)
            try:
                client.wait_for_spin_server(timeout_s=15.0)
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    yaw_before = client.current_yaw()
                    goal_handle = client.send_spin_cancelable(
                        CANCEL_SPIN_TARGET_YAW_RAD, time_allowance_s=20.0
                    )
                    if goal_handle is None:
                        result["errors"].append("SPIN_GOAL_REJECTED")
                    else:
                        # Wait for raw+safe angular motion before canceling.
                        motion_deadline = time.monotonic() + 10.0
                        while time.monotonic() < motion_deadline:
                            client.spin_for(0.1)
                            if (
                                client.raw_angular_observed is not None
                                and client.safe_angular_observed is not None
                            ):
                                yaw_now = client.current_yaw()
                                if yaw_before is not None and yaw_now is not None:
                                    if abs(yaw_now - yaw_before) > 0.02:
                                        result["motion_observed"] = True
                                        break

                        result["raw_angular_observed"] = client.raw_angular_observed
                        result["safe_angular_observed"] = client.safe_angular_observed

                        cancel_status = client.cancel_and_wait(goal_handle, timeout_s=15.0)
                        result["cancel_result"] = cancel_status

                        if cancel_status == "CANCELED":
                            client.spin_for(1.5)
                            safe = client._latest_cmd_vel_safe
                            if safe is not None:
                                result["safe_angular_zero_after_cancel"] = abs(safe.angular.z) < 1e-5

                            twist = client.current_twist()
                            if twist is not None:
                                result["odom_twist_zero"] = (
                                    abs(twist[0]) < 1e-5 and abs(twist[1]) < 1e-5
                                )

                            pose_t0 = client.current_xy()
                            client.spin_for(0.5)
                            pose_t1 = client.current_xy()
                            if pose_t0 is not None and pose_t1 is not None:
                                diff = math.hypot(
                                    pose_t1[0] - pose_t0[0], pose_t1[1] - pose_t0[1]
                                )
                                result["pose_stable"] = diff < 0.002
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
        and result["behavior_server_active"]
        and result["motion_observed"]
        and result["raw_angular_observed"] is not None
        and result["safe_angular_observed"] is not None
        and result["cancel_result"] == "CANCELED"
        and result["safe_angular_zero_after_cancel"]
        and result["odom_twist_zero"]
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

    base = int(args.base_domain_id)
    if base <= 0:
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": ["INVALID_BASE_DOMAIN_ID"]}))
        return 2

    domain_wait = str(base)
    domain_spin = str(base + 1)
    domain_cancel = str(base + 2)

    print(f"--- Running scenario: WAIT on ROS_DOMAIN_ID={domain_wait} ---")
    wait_result = run_wait_scenario(args.namespace, domain_wait, args.timeout)
    print(f"Scenario WAIT outcome: {'PASS' if wait_result['ok'] else 'FAIL'}")

    print(f"--- Running scenario: SPIN on ROS_DOMAIN_ID={domain_spin} ---")
    spin_result = run_spin_scenario(args.namespace, domain_spin, args.timeout)
    print(f"Scenario SPIN outcome: {'PASS' if spin_result['ok'] else 'FAIL'}")

    print(f"--- Running scenario: CANCEL_SPIN on ROS_DOMAIN_ID={domain_cancel} ---")
    cancel_spin_result = run_cancel_spin_scenario(args.namespace, domain_cancel, args.timeout)
    print(f"Scenario CANCEL_SPIN outcome: {'PASS' if cancel_spin_result['ok'] else 'FAIL'}")

    all_ok = wait_result["ok"] and spin_result["ok"] and cancel_spin_result["ok"]
    decision = "PASS" if all_ok else "FAIL"

    report = {
        "ok": all_ok,
        "decision": decision,
        "namespace": args.namespace,
        "base_domain_id": args.base_domain_id,
        "scenarios": {
            "wait": wait_result,
            "spin": spin_result,
            "cancel_spin": cancel_spin_result,
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
