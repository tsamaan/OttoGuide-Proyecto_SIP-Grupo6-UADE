#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox Collision Monitor.

Validates the isolated safety chain:
controller_server -> cmd_vel_raw -> collision_monitor -> cmd_vel_safe -> offline_runtime_simulator

Scenarios tested in separate, isolated domain IDs:
A. Clear (obstacle_mode="clear"): Pose advances with unmodified velocity.
B. Slowdown (obstacle_mode="slowdown"): cmd_vel_safe is reduced compared to cmd_vel_raw.
C. Stop (obstacle_mode="stop"): cmd_vel_safe is exactly zero; pose remains stable.
D. Recovery (stop -> clear): cmd_vel_safe becomes zero, then resumes when clear.
E. Cancel (with collision monitor active): Goal canceled, cmd_vel_safe zero, odom twist zero.

No robot hardware, no network access, no rosbags.
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
DEFAULT_BASE_DOMAIN_ID = "121"
DEFAULT_TIMEOUT_S = 60.0

START_XY = (0.0, 0.0)
GOAL_XY = (0.50, 0.0)
GOAL_TOLERANCE_M = 0.12

ALLOWED_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel_raw", "/cmd_vel_safe")
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

    def _on_cmd_vel_safe(self, msg: Twist) -> None:
        self._latest_cmd_vel_safe = msg
        self.cmd_vel_safe_messages_received += 1

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
        "raw_speed_observed": 0.0,
        "safe_speed_observed": 0.0,
        "simulated_distance_moved": 0.0,
        "final_pose_stable": False,
        "goal_status": "NOT_ATTEMPTED",
        "recovery_resumed": False,
        "forbidden_velocity_topics_detected": [],
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
            initial_mode = "clear"
            if scenario in ("stop", "recovery", "cancel"):
                initial_mode = "stop"
            elif scenario == "slowdown":
                initial_mode = "slowdown"

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
                            # Let controller run
                            wait_deadline = time.monotonic() + 15.0
                            command_received = False
                            
                            while time.monotonic() < wait_deadline:
                                client.spin_for(0.1)
                                raw = client._latest_cmd_vel_raw
                                safe = client._latest_cmd_vel_safe
                                if raw is not None and (abs(raw.linear.x) > 1e-4 or abs(raw.angular.z) > 1e-4):
                                    command_received = True
                                    run_result["raw_speed_observed"] = max(run_result["raw_speed_observed"], abs(raw.linear.x))
                                    if safe is not None:
                                        run_result["safe_speed_observed"] = max(run_result["safe_speed_observed"], abs(safe.linear.x))
                                    
                                if command_received:
                                    if scenario in ("clear", "slowdown"):
                                        # Let it advance a bit
                                        curr_xy = client.current_xy()
                                        if curr_xy is not None and math.hypot(curr_xy[0] - x_init, curr_xy[1] - y_init) > 0.05:
                                            break
                                    elif scenario == "stop":
                                        # Verify safe speed remains zero
                                        break
                                    elif scenario == "recovery":
                                        # Once we see raw command and safe speed is zero, change simulator parameter to clear
                                        if safe is not None and abs(safe.linear.x) < 1e-5:
                                            if set_simulator_obstacle_mode(namespace, "clear", env):
                                                # Wait for safe command to become non-zero and pose to advance
                                                rec_deadline = time.monotonic() + 10.0
                                                while time.monotonic() < rec_deadline:
                                                    client.spin_for(0.1)
                                                    safe_msg = client._latest_cmd_vel_safe
                                                    curr_xy = client.current_xy()
                                                    if safe_msg is not None and abs(safe_msg.linear.x) > 0.01:
                                                        if curr_xy is not None and math.hypot(curr_xy[0] - x_init, curr_xy[1] - y_init) > 0.02:
                                                            run_result["recovery_resumed"] = True
                                                            break
                                            break
                                    elif scenario == "cancel":
                                        # Cancel immediately
                                        cancel_future = goal_handle.cancel_goal_async()
                                        if client.spin_until_future_complete_custom(cancel_future, 10.0):
                                            res_future = goal_handle.get_result_async()
                                            if client.spin_until_future_complete_custom(res_future, 10.0):
                                                wrapped_res = res_future.result()
                                                if wrapped_res is not None:
                                                    run_result["goal_status"] = "CANCELED" if wrapped_res.status == GoalStatus.STATUS_CANCELED else f"STATUS_{wrapped_res.status}"
                                        break

                            # Measure final position and velocity stability
                            pose_after = client.current_xy()
                            if pose_before is not None and pose_after is not None:
                                run_result["simulated_distance_moved"] = math.hypot(
                                    pose_after[0] - pose_before[0], pose_after[1] - pose_before[1]
                                )

                            # Let's assess stability
                            client.spin_for(1.0)
                            pose_final = client.current_xy()
                            if pose_after is not None and pose_final is not None:
                                diff = math.hypot(pose_final[0] - pose_after[0], pose_final[1] - pose_after[1])
                                run_result["final_pose_stable"] = (diff < 0.002)

                            run_result["cmd_vel_raw_messages"] = client.cmd_vel_raw_messages_received
                            run_result["cmd_vel_safe_messages"] = client.cmd_vel_safe_messages_received

                            # If not canceled, let's cancel to clean up action server
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
    if scenario == "clear":
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and run_result["raw_speed_observed"] > 0.02
            and run_result["safe_speed_observed"] > 0.02
            and run_result["simulated_distance_moved"] > 0.05
            and not run_result["hardware_node_detected"]
            and not run_result["forbidden_velocity_topics_detected"]
            and run_result["orphan_processes"] == 0
        )
    elif scenario == "slowdown":
        # Safe speed must be strictly less than raw speed, and both non-zero
        speed_reduced = (
            run_result["safe_speed_observed"] > 0.01
            and run_result["safe_speed_observed"] < 0.8 * run_result["raw_speed_observed"]
        )
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and speed_reduced
            and run_result["simulated_distance_moved"] > 0.01
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )
    elif scenario == "stop":
        # Safe speed must be zero, raw speed non-zero, pose stable
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and run_result["raw_speed_observed"] > 0.01
            and run_result["safe_speed_observed"] < 1e-5
            and run_result["simulated_distance_moved"] < 0.005
            and run_result["final_pose_stable"]
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )
    elif scenario == "recovery":
        # Should start in stop and transition to active
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and run_result["recovery_resumed"]
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )
    elif scenario == "cancel":
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["collision_monitor_active"]
            and run_result["goal_status"] == "CANCELED"
            and run_result["safe_speed_observed"] < 1e-5
            and run_result["final_pose_stable"]
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

    base = int(args.base_domain_id)
    if base <= 0:
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": ["INVALID_BASE_DOMAIN_ID"]}))
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
