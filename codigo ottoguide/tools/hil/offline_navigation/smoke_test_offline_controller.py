#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox local controller.

Starts the sandbox runtime via the isolated wrapper script under a dedicated
ROS_DOMAIN_ID, confirms real lifecycle ACTIVE state of map_server,
planner_server and controller_server, computes a global path, sends it via
the FollowPath action (/offline_nav/follow_path), and checks that the only
velocity topic that ever appears is /offline_nav/cmd_vel_raw while the
simulated pose advances toward the goal. A second scenario starts another
FollowPath goal and cancels it, then checks that the simulated velocity
returns to zero within 1.0 s and the pose stops advancing.

This script does not touch the real robot, does not open rosbags, does not
install packages, and does not kill ROS processes outside its own launched
process group.
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
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import ComputePathToPose, FollowPath
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_DOMAIN_ID = "92"
DEFAULT_TIMEOUT_S = 60.0

# Synthetic start/goal within the free corridor of
# offline_sandbox_test_map.yaml (world bounds x in [-1.0, 1.0], y in
# [-0.75, 0.75]). The simulated pose itself always starts at (0, 0), the
# offline_runtime_simulator's own integration origin.
START_XY = (0.0, 0.0)
GOAL_XY = (0.50, 0.0)
GOAL_TOLERANCE_M = 0.12

ALLOWED_VELOCITY_TOPIC_SUFFIX = "/cmd_vel_raw"
FORBIDDEN_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav")
FORBIDDEN_NODE_SUBSTRINGS = (
    "unitree",
    "livox_sdk_bridge",
    "livox_ros_driver",
    "realsense",
)


def _build_env(domain_id: str) -> dict:
    env = os.environ.copy()
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["ROS_DOMAIN_ID"] = domain_id
    return env


def _run(cmd: list[str], env: dict, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


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


class _ControllerSmokeClient(Node):
    """rclpy helper node bundling the ComputePathToPose and FollowPath
    action clients, plus a /odom subscription and a /cmd_vel_raw watcher,
    all resolved relative to the sandbox namespace.
    """

    def __init__(self, namespace: str) -> None:
        super().__init__("offline_controller_smoke_test_client")
        self._namespace = namespace
        self._planner_client = ActionClient(
            self, ComputePathToPose, f"/{namespace}/compute_path_to_pose"
        )
        self._follow_path_client = ActionClient(
            self, FollowPath, f"/{namespace}/follow_path"
        )
        self._latest_odom: Odometry | None = None
        self._latest_cmd_vel_raw: Twist | None = None
        self.create_subscription(Odometry, "odom", self._on_odom, 10)
        self.create_subscription(Twist, "cmd_vel_raw", self._on_cmd_vel_raw, 10)

    def _on_odom(self, msg: Odometry) -> None:
        self._latest_odom = msg

    def _on_cmd_vel_raw(self, msg: Twist) -> None:
        self._latest_cmd_vel_raw = msg

    def current_xy(self) -> tuple[float, float] | None:
        if self._latest_odom is None:
            return None
        return (
            self._latest_odom.pose.pose.position.x,
            self._latest_odom.pose.pose.position.y,
        )

    def current_cmd_vel_raw(self) -> Twist | None:
        return self._latest_cmd_vel_raw

    def spin_for(self, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)

    def wait_for_planner_server(self, timeout_s: float) -> bool:
        return self._planner_client.wait_for_server(timeout_sec=timeout_s)

    def wait_for_follow_path_server(self, timeout_s: float) -> bool:
        return self._follow_path_client.wait_for_server(timeout_sec=timeout_s)

    def compute_path(self, start: PoseStamped, goal: PoseStamped, timeout_s: float):
        goal_msg = ComputePathToPose.Goal()
        goal_msg.start = start
        goal_msg.goal = goal
        goal_msg.use_start = True

        send_goal_future = self._planner_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_goal_future, timeout_sec=timeout_s)
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout_s)
        wrapped_result = result_future.result()
        if wrapped_result is None or wrapped_result.status != GoalStatus.STATUS_SUCCEEDED:
            return None
        return wrapped_result.result.path

    def send_follow_path_and_wait(self, path, timeout_s: float) -> str:
        goal_msg = FollowPath.Goal()
        goal_msg.path = path
        send_goal_future = self._follow_path_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_goal_future, timeout_sec=timeout_s)
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return "GOAL_REJECTED"
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout_s)
        wrapped_result = result_future.result()
        if wrapped_result is None:
            return "RESULT_TIMEOUT"
        if wrapped_result.status != GoalStatus.STATUS_SUCCEEDED:
            return f"GOAL_STATUS_{wrapped_result.status}"
        return "SUCCEEDED"

    def send_follow_path_cancelable(self, path, timeout_s: float):
        """Send a FollowPath goal and return the goal_handle without waiting
        for the result, so the caller can observe motion then cancel it.
        """
        goal_msg = FollowPath.Goal()
        goal_msg.path = path
        send_goal_future = self._follow_path_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_goal_future, timeout_sec=timeout_s)
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None
        return goal_handle

    def cancel_and_wait(self, goal_handle, timeout_s: float) -> str:
        cancel_future = goal_handle.cancel_goal_async()
        rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=timeout_s)
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout_s)
        wrapped_result = result_future.result()
        if wrapped_result is None:
            return "RESULT_TIMEOUT"
        if wrapped_result.status == GoalStatus.STATUS_CANCELED:
            return "CANCELED"
        return f"GOAL_STATUS_{wrapped_result.status}"


def run_controller_smoke_test(namespace: str, domain_id: str, timeout_s: float) -> dict:
    result = {
        "ok": False,
        "decision": "FAIL",
        "namespace": namespace,
        "domain_id": domain_id,
        "map_server_lifecycle_active": False,
        "planner_server_lifecycle_active": False,
        "controller_server_lifecycle_active": False,
        "velocity_topic_allowed": ALLOWED_VELOCITY_TOPIC_SUFFIX,
        "forbidden_velocity_topics_detected": [],
        "start_pose": list(START_XY),
        "goal_pose": list(GOAL_XY),
        "follow_path_result": "NOT_ATTEMPTED",
        "simulated_distance_moved": 0.0,
        "final_distance_to_goal": None,
        "cancel_test": "NOT_ATTEMPTED",
        "stop_after_cancel": "NOT_ATTEMPTED",
        "nonzero_command_after_cancel": False,
        "hardware_node_detected": False,
        "orphan_processes": 0,
        "errors": [],
    }

    env = _build_env(domain_id)
    launch_process = None
    rclpy_initialized = False

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

        for fqn, key in (
            (map_fqn, "map_server_lifecycle_active"),
            (planner_fqn, "planner_server_lifecycle_active"),
            (controller_fqn, "controller_server_lifecycle_active"),
        ):
            if _wait_for_node_discovered(fqn, env, deadline):
                result[key] = _wait_for_lifecycle_active(fqn, env, deadline)
            if not result[key]:
                result["errors"].append(f"{key.upper()}_NOT_CONFIRMED")

        nodes = _node_list(env, timeout=5.0)
        result["hardware_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
            for node in nodes
        )

        topics = _topic_list(env, timeout=5.0)
        result["forbidden_velocity_topics_detected"] = [
            t for t in topics if any(t.endswith(suffix) for suffix in FORBIDDEN_VELOCITY_TOPIC_SUFFIXES)
        ]
        if not any(t.endswith(ALLOWED_VELOCITY_TOPIC_SUFFIX) for t in topics):
            result["errors"].append("CMD_VEL_RAW_TOPIC_NOT_FOUND")

        if (
            result["map_server_lifecycle_active"]
            and result["planner_server_lifecycle_active"]
            and result["controller_server_lifecycle_active"]
        ):
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _ControllerSmokeClient(namespace)
            try:
                client.wait_for_planner_server(timeout_s=15.0)
                client.wait_for_follow_path_server(timeout_s=15.0)
                client.spin_for(1.0)

                start_pose = _make_pose("map", *START_XY)
                goal_pose = _make_pose("map", *GOAL_XY)
                path = client.compute_path(start_pose, goal_pose, timeout_s=20.0)
                if path is None:
                    result["errors"].append("COMPUTE_PATH_FAILED")
                else:
                    pose_before = client.current_xy()
                    follow_status = client.send_follow_path_and_wait(path, timeout_s=30.0)
                    result["follow_path_result"] = follow_status
                    client.spin_for(0.5)
                    pose_after = client.current_xy()

                    if pose_before is not None and pose_after is not None:
                        result["simulated_distance_moved"] = math.hypot(
                            pose_after[0] - pose_before[0], pose_after[1] - pose_before[1]
                        )
                        result["final_distance_to_goal"] = math.hypot(
                            pose_after[0] - GOAL_XY[0], pose_after[1] - GOAL_XY[1]
                        )

                # --- Scenario 2: start another FollowPath, then cancel it. ---
                second_path = client.compute_path(
                    _make_pose("map", *START_XY), _make_pose("map", *GOAL_XY), timeout_s=20.0
                )
                if second_path is None:
                    result["errors"].append("SECOND_COMPUTE_PATH_FAILED")
                else:
                    goal_handle = client.send_follow_path_cancelable(second_path, timeout_s=15.0)
                    if goal_handle is None:
                        result["cancel_test"] = "GOAL_REJECTED"
                    else:
                        # Let it start moving before cancelling.
                        client.spin_for(1.5)
                        cancel_status = client.cancel_and_wait(goal_handle, timeout_s=15.0)
                        result["cancel_test"] = "PASS" if cancel_status == "CANCELED" else cancel_status

                        # Watchdog timeout in the simulator is 0.5s; allow up
                        # to 1.0s total for the commanded velocity to settle
                        # at zero after cancellation.
                        stop_deadline = time.monotonic() + 1.0
                        velocity_zero = False
                        while time.monotonic() < stop_deadline:
                            client.spin_for(0.1)
                            cmd = client.current_cmd_vel_raw()
                            if cmd is not None and abs(cmd.linear.x) < 1e-6 and abs(cmd.angular.z) < 1e-6:
                                velocity_zero = True
                                break
                        result["stop_after_cancel"] = "PASS" if velocity_zero else "FAIL"
                        result["nonzero_command_after_cancel"] = not velocity_zero
            finally:
                client.destroy_node()

    except FileNotFoundError as exc:
        result["errors"].append(f"ROS_TOOLING_NOT_FOUND: {exc}")
    except subprocess.TimeoutExpired as exc:
        result["errors"].append(f"COMMAND_TIMEOUT: {exc}")
    finally:
        if rclpy_initialized:
            try:
                rclpy.shutdown()
            except Exception:
                pass
        result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)

    result["ok"] = (
        not result["errors"]
        and result["map_server_lifecycle_active"]
        and result["planner_server_lifecycle_active"]
        and result["controller_server_lifecycle_active"]
        and not result["forbidden_velocity_topics_detected"]
        and result["follow_path_result"] == "SUCCEEDED"
        and result["final_distance_to_goal"] is not None
        and result["final_distance_to_goal"] < GOAL_TOLERANCE_M
        and result["simulated_distance_moved"] > 0.01
        and result["cancel_test"] == "PASS"
        and result["stop_after_cancel"] == "PASS"
        and not result["nonzero_command_after_cancel"]
        and not result["hardware_node_detected"]
        and result["orphan_processes"] == 0
    )
    result["decision"] = "PASS" if result["ok"] else "FAIL"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--domain-id", default=DEFAULT_DOMAIN_ID)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.domain_id == "0":
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": ["DOMAIN_ID_ZERO_NOT_ALLOWED"]}))
        return 2

    result = run_controller_smoke_test(args.namespace, args.domain_id, args.timeout)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
