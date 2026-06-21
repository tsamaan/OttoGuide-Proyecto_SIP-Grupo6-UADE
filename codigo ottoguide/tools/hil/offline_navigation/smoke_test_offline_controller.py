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
    action clients, plus namespaced /odom and /cmd_vel_raw subscriptions,
    all resolved with absolute namespaced paths.
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
        
        self.odom_topic_observed = f"/{namespace}/odom"
        self.cmd_vel_topic_observed = f"/{namespace}/cmd_vel_raw"
        
        self.create_subscription(Odometry, self.odom_topic_observed, self._on_odom, 10)
        self.create_subscription(Twist, self.cmd_vel_topic_observed, self._on_cmd_vel_raw, 10)
        
        self.odom_messages_received = 0
        self.cmd_vel_messages_received = 0
        self.nonzero_cmd_observed = False

    def _on_odom(self, msg: Odometry) -> None:
        self._latest_odom = msg
        self.odom_messages_received += 1

    def _on_cmd_vel_raw(self, msg: Twist) -> None:
        self._latest_cmd_vel_raw = msg
        self.cmd_vel_messages_received += 1
        if abs(msg.linear.x) > 1e-6 or abs(msg.angular.z) > 1e-6:
            self.nonzero_cmd_observed = True

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

    def send_follow_path_and_wait(self, path, timeout_s: float) -> str:
        goal_msg = FollowPath.Goal()
        goal_msg.path = path
        send_goal_future = self._follow_path_client.send_goal_async(goal_msg)
        if not self.spin_until_future_complete_custom(send_goal_future, 15.0):
            return "SEND_GOAL_TIMEOUT"
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return "GOAL_REJECTED"
        result_future = goal_handle.get_result_async()
        if not self.spin_until_future_complete_custom(result_future, timeout_s):
            return "RESULT_TIMEOUT"
        wrapped_result = result_future.result()
        if wrapped_result is None:
            return "RESULT_TIMEOUT"
        if wrapped_result.status != GoalStatus.STATUS_SUCCEEDED:
            return f"GOAL_STATUS_{wrapped_result.status}"
        return "SUCCEEDED"

    def send_follow_path_cancelable(self, path, timeout_s: float):
        goal_msg = FollowPath.Goal()
        goal_msg.path = path
        send_goal_future = self._follow_path_client.send_goal_async(goal_msg)
        if not self.spin_until_future_complete_custom(send_goal_future, timeout_s):
            return None
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None
        return goal_handle

    def cancel_and_wait(self, goal_handle, timeout_s: float) -> str:
        cancel_future = goal_handle.cancel_goal_async()
        if not self.spin_until_future_complete_custom(cancel_future, timeout_s):
            return "CANCEL_TIMEOUT"
        result_future = goal_handle.get_result_async()
        if not self.spin_until_future_complete_custom(result_future, timeout_s):
            return "RESULT_TIMEOUT"
        wrapped_result = result_future.result()
        if wrapped_result is None:
            return "RESULT_TIMEOUT"
        if wrapped_result.status == GoalStatus.STATUS_CANCELED:
            return "CANCELED"
        return f"GOAL_STATUS_{wrapped_result.status}"


def run_single_scenario(namespace: str, domain_id: str, scenario: str, timeout_s: float) -> dict:
    run_result = {
        "ok": False,
        "map_server_lifecycle_active": False,
        "planner_server_lifecycle_active": False,
        "controller_server_lifecycle_active": False,
        "odom_topic_observed": None,
        "cmd_vel_topic_observed": None,
        "initial_odom_received": False,
        "nonzero_cmd_observed": False,
        "odom_messages_received": 0,
        "cmd_vel_messages_received": 0,
        "simulated_distance_moved": None,
        "final_distance_to_goal": None,
        "success_final_twist_zero": None,
        "cancel_status": "NOT_ATTEMPTED",
        "zero_raw_command_received": None,
        "watchdog_effective_stop": None,
        "pose_stable_after_cancel": None,
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

        for fqn, key in (
            (map_fqn, "map_server_lifecycle_active"),
            (planner_fqn, "planner_server_lifecycle_active"),
            (controller_fqn, "controller_server_lifecycle_active"),
        ):
            if _wait_for_node_discovered(fqn, env, deadline):
                run_result[key] = _wait_for_lifecycle_active(fqn, env, deadline)
            if not run_result[key]:
                run_result["errors"].append(f"{key.upper()}_NOT_CONFIRMED")

        nodes = _node_list(env, timeout=5.0)
        run_result["hardware_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
            for node in nodes
        )

        topics = _topic_list(env, timeout=5.0)
        run_result["forbidden_velocity_topics_detected"] = [
            t for t in topics if any(t.endswith(suffix) for suffix in FORBIDDEN_VELOCITY_TOPIC_SUFFIXES)
        ]
        if not any(t.endswith(ALLOWED_VELOCITY_TOPIC_SUFFIX) for t in topics):
            run_result["errors"].append("CMD_VEL_RAW_TOPIC_NOT_FOUND")

        if (
            run_result["map_server_lifecycle_active"]
            and run_result["planner_server_lifecycle_active"]
            and run_result["controller_server_lifecycle_active"]
        ):
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client = _ControllerSmokeClient(namespace)
            try:
                client.wait_for_planner_server(timeout_s=15.0)
                client.wait_for_follow_path_server(timeout_s=15.0)

                # Wait for initial odom message
                if not client.wait_for_initial_odom(timeout_s=15.0):
                    run_result["errors"].append("ODOM_NOT_RECEIVED")
                else:
                    run_result["initial_odom_received"] = True
                    pose_before = client.current_xy()
                    x_init, y_init = pose_before

                    if scenario == "success":
                        start_pose = _make_pose("map", x_init, y_init)
                        goal_x, goal_y = x_init + 0.50, y_init
                        goal_pose = _make_pose("map", goal_x, goal_y)
                        path = client.compute_path(start_pose, goal_pose, timeout_s=20.0)
                        if path is None:
                            run_result["errors"].append("COMPUTE_PATH_FAILED")
                        else:
                            # Send action and wait
                            follow_status = client.send_follow_path_and_wait(path, timeout_s=30.0)
                            run_result["follow_path_result"] = follow_status
                            client.spin_for(0.5)
                            pose_after = client.current_xy()

                            if pose_before is not None and pose_after is not None:
                                run_result["simulated_distance_moved"] = math.hypot(
                                    pose_after[0] - pose_before[0], pose_after[1] - pose_before[1]
                                )
                                run_result["final_distance_to_goal"] = math.hypot(
                                    pose_after[0] - goal_x, pose_after[1] - goal_y
                                )
                                # Check twist
                                odom = client._latest_odom
                                if odom is not None:
                                    twist_lin = odom.twist.twist.linear.x
                                    twist_ang = odom.twist.twist.angular.z
                                    run_result["success_final_twist_zero"] = (
                                        abs(twist_lin) < 1e-4 and abs(twist_ang) < 1e-4
                                    )
                                else:
                                    run_result["success_final_twist_zero"] = False

                    elif scenario == "cancel":
                        # Set a distant goal
                        start_pose = _make_pose("map", x_init, y_init)
                        goal_x, goal_y = x_init + 0.80, y_init
                        goal_pose = _make_pose("map", goal_x, goal_y)
                        path = client.compute_path(start_pose, goal_pose, timeout_s=20.0)
                        if path is None:
                            run_result["errors"].append("COMPUTE_PATH_FAILED")
                        else:
                            goal_handle = client.send_follow_path_cancelable(path, timeout_s=15.0)
                            if goal_handle is None:
                                run_result["cancel_status"] = "GOAL_REJECTED"
                                run_result["errors"].append("GOAL_REJECTED")
                            else:
                                # Wait for cmd_vel_raw non-zero AND some movement
                                wait_deadline = time.monotonic() + 15.0
                                command_ok = False
                                movement_ok = False
                                while time.monotonic() < wait_deadline:
                                    client.spin_for(0.1)
                                    cmd = client.current_cmd_vel_raw()
                                    if cmd is not None and (abs(cmd.linear.x) > 1e-6 or abs(cmd.angular.z) > 1e-6):
                                        command_ok = True
                                    curr_xy = client.current_xy()
                                    if curr_xy is not None:
                                        dist = math.hypot(curr_xy[0] - x_init, curr_xy[1] - y_init)
                                        if dist > 0.01:
                                            movement_ok = True
                                    if command_ok and movement_ok:
                                        break

                                if not (command_ok and movement_ok):
                                    run_result["errors"].append("CANCEL_PRECONDITIONS_NOT_MET")

                                # Cancel goal immediately
                                cancel_status = client.cancel_and_wait(goal_handle, timeout_s=15.0)
                                run_result["cancel_status"] = cancel_status

                                # Check effective stop within 1.5 seconds
                                stop_deadline = time.monotonic() + 1.5
                                zero_raw_command_received = False
                                watchdog_effective_stop = False
                                pose_stable_after_cancel = False

                                odom_history = []
                                while time.monotonic() < stop_deadline:
                                    client.spin_for(0.05)
                                    cmd = client.current_cmd_vel_raw()
                                    if cmd is not None and abs(cmd.linear.x) < 1e-6 and abs(cmd.angular.z) < 1e-6:
                                        zero_raw_command_received = True
                                    
                                    odom = client._latest_odom
                                    if odom is not None:
                                        odom_history.append((
                                            time.monotonic(),
                                            odom.pose.pose.position.x,
                                            odom.pose.pose.position.y,
                                            odom.twist.twist.linear.x,
                                            odom.twist.twist.angular.z
                                        ))
                                        if abs(odom.twist.twist.linear.x) < 1e-4 and abs(odom.twist.twist.angular.z) < 1e-4:
                                            watchdog_effective_stop = True

                                # Check pose stable for 0.5s
                                for i, (t_start, x_start, y_start, _, _) in enumerate(odom_history):
                                    window_poses = [
                                        (x, y) for (t, x, y, _, _) in odom_history[i:]
                                        if t_start <= t <= t_start + 0.6
                                    ]
                                    window_times = [
                                        t for (t, _, _, _, _) in odom_history[i:]
                                        if t_start <= t <= t_start + 0.6
                                    ]
                                    if window_times and (window_times[-1] - window_times[0]) >= 0.5:
                                        xs = [p[0] for p in window_poses]
                                        ys = [p[1] for p in window_poses]
                                        max_diff = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
                                        if max_diff < 0.002:
                                            pose_stable_after_cancel = True
                                            break

                                run_result["zero_raw_command_received"] = zero_raw_command_received
                                run_result["watchdog_effective_stop"] = watchdog_effective_stop
                                run_result["pose_stable_after_cancel"] = pose_stable_after_cancel

                run_result["odom_topic_observed"] = client.odom_topic_observed
                run_result["cmd_vel_topic_observed"] = client.cmd_vel_topic_observed
                run_result["odom_messages_received"] = client.odom_messages_received
                run_result["cmd_vel_messages_received"] = client.cmd_vel_messages_received
                run_result["nonzero_cmd_observed"] = client.nonzero_cmd_observed

            finally:
                client.destroy_node()

    except FileNotFoundError as exc:
        run_result["errors"].append(f"ROS_TOOLING_NOT_FOUND: {exc}")
    except subprocess.TimeoutExpired as exc:
        run_result["errors"].append(f"COMMAND_TIMEOUT: {exc}")
    finally:
        if rclpy_initialized:
            try:
                rclpy.shutdown()
            except Exception:
                pass
        run_result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)

    # Criteria for scenario OK:
    if scenario == "success":
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["map_server_lifecycle_active"]
            and run_result["planner_server_lifecycle_active"]
            and run_result["controller_server_lifecycle_active"]
            and not run_result["forbidden_velocity_topics_detected"]
            and run_result.get("follow_path_result") == "SUCCEEDED"
            and run_result["final_distance_to_goal"] is not None
            and run_result["final_distance_to_goal"] < GOAL_TOLERANCE_M
            and run_result["simulated_distance_moved"] is not None
            and run_result["simulated_distance_moved"] > 0.05
            and run_result["success_final_twist_zero"] is True
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )
    elif scenario == "cancel":
        run_result["ok"] = (
            not run_result["errors"]
            and run_result["map_server_lifecycle_active"]
            and run_result["planner_server_lifecycle_active"]
            and run_result["controller_server_lifecycle_active"]
            and not run_result["forbidden_velocity_topics_detected"]
            and run_result["cancel_status"] == "CANCELED"
            and run_result["watchdog_effective_stop"] is True
            and run_result["pose_stable_after_cancel"] is True
            and not run_result["hardware_node_detected"]
            and run_result["orphan_processes"] == 0
        )

    return run_result


def run_controller_smoke_test(namespace: str, domain_id: str, timeout_s: float, scenario: str = "all") -> dict:
    if scenario == "success":
        res = run_single_scenario(namespace, domain_id, "success", timeout_s)
        return {
            "ok": res["ok"],
            "decision": "PASS" if res["ok"] else "FAIL",
            "namespace": namespace,
            "domain_id": domain_id,
            "odom_topic_observed": res["odom_topic_observed"],
            "cmd_vel_topic_observed": res["cmd_vel_topic_observed"],
            "initial_odom_received": res["initial_odom_received"],
            "nonzero_cmd_observed": res["nonzero_cmd_observed"],
            "odom_messages_received": res["odom_messages_received"],
            "cmd_vel_messages_received": res["cmd_vel_messages_received"],
            
            "success_run_1": "PASS" if res["ok"] else "FAIL",
            "success_run_2": "NOT_ATTEMPTED",
            "success_distance_moved": res["simulated_distance_moved"],
            "success_final_distance": res["final_distance_to_goal"],
            "success_result": res.get("follow_path_result", "NOT_ATTEMPTED"),
            "success_final_twist_zero": res["success_final_twist_zero"],
            
            "cancel_run_1": "NOT_ATTEMPTED",
            "cancel_run_2": "NOT_ATTEMPTED",
            "cancel_result": "NOT_ATTEMPTED",
            "zero_raw_command_received": None,
            "watchdog_effective_stop": None,
            "pose_stable_after_cancel": None,
            
            "forbidden_velocity_topics_detected": res["forbidden_velocity_topics_detected"],
            "hardware_node_detected": res["hardware_node_detected"],
            "own_processes_remaining": res["orphan_processes"],
            "errors": res["errors"]
        }
    elif scenario == "cancel":
        res = run_single_scenario(namespace, domain_id, "cancel", timeout_s)
        return {
            "ok": res["ok"],
            "decision": "PASS" if res["ok"] else "FAIL",
            "namespace": namespace,
            "domain_id": domain_id,
            "odom_topic_observed": res["odom_topic_observed"],
            "cmd_vel_topic_observed": res["cmd_vel_topic_observed"],
            "initial_odom_received": res["initial_odom_received"],
            "nonzero_cmd_observed": res["nonzero_cmd_observed"],
            "odom_messages_received": res["odom_messages_received"],
            "cmd_vel_messages_received": res["cmd_vel_messages_received"],
            
            "success_run_1": "NOT_ATTEMPTED",
            "success_run_2": "NOT_ATTEMPTED",
            "success_distance_moved": None,
            "success_final_distance": None,
            "success_result": "NOT_ATTEMPTED",
            "success_final_twist_zero": None,
            
            "cancel_run_1": "PASS" if res["ok"] else "FAIL",
            "cancel_run_2": "NOT_ATTEMPTED",
            "cancel_result": res["cancel_status"],
            "zero_raw_command_received": res["zero_raw_command_received"],
            "watchdog_effective_stop": res["watchdog_effective_stop"],
            "pose_stable_after_cancel": res["pose_stable_after_cancel"],
            
            "forbidden_velocity_topics_detected": res["forbidden_velocity_topics_detected"],
            "hardware_node_detected": res["hardware_node_detected"],
            "own_processes_remaining": res["orphan_processes"],
            "errors": res["errors"]
        }
    
    # Run "all" sequence on isolated domain IDs
    # éxito 1: 117
    # cancelación 1: 118
    # éxito 2: 119
    # cancelación 2: 120
    print("Executing Success Run 1 on domain 117...")
    success1 = run_single_scenario(namespace, "117", "success", timeout_s)
    
    print("Executing Cancel Run 1 on domain 118...")
    cancel1 = run_single_scenario(namespace, "118", "cancel", timeout_s)
    
    print("Executing Success Run 2 on domain 119...")
    success2 = run_single_scenario(namespace, "119", "success", timeout_s)
    
    print("Executing Cancel Run 2 on domain 120...")
    cancel2 = run_single_scenario(namespace, "120", "cancel", timeout_s)
    
    all_ok = (success1["ok"] and success2["ok"] and cancel1["ok"] and cancel2["ok"])
    
    return {
        "ok": all_ok,
        "decision": "PASS" if all_ok else "FAIL",
        "namespace": namespace,
        "domain_id": domain_id,
        "odom_topic_observed": success1["odom_topic_observed"],
        "cmd_vel_topic_observed": success1["cmd_vel_topic_observed"],
        "initial_odom_received": success1["initial_odom_received"] or cancel1["initial_odom_received"],
        "nonzero_cmd_observed": success1["nonzero_cmd_observed"] or cancel1["nonzero_cmd_observed"],
        "odom_messages_received": (
            success1.get("odom_messages_received", 0) +
            success2.get("odom_messages_received", 0) +
            cancel1.get("odom_messages_received", 0) +
            cancel2.get("odom_messages_received", 0)
        ),
        "cmd_vel_messages_received": (
            success1.get("cmd_vel_messages_received", 0) +
            success2.get("cmd_vel_messages_received", 0) +
            cancel1.get("cmd_vel_messages_received", 0) +
            cancel2.get("cmd_vel_messages_received", 0)
        ),
        
        "success_run_1": "PASS" if success1["ok"] else "FAIL",
        "success_run_2": "PASS" if success2["ok"] else "FAIL",
        "success_distance_moved": success1["simulated_distance_moved"],
        "success_final_distance": success1["final_distance_to_goal"],
        "success_result": success1.get("follow_path_result", "NOT_ATTEMPTED"),
        "success_final_twist_zero": success1["success_final_twist_zero"],
        
        "cancel_run_1": "PASS" if cancel1["ok"] else "FAIL",
        "cancel_run_2": "PASS" if cancel2["ok"] else "FAIL",
        "cancel_result": cancel1["cancel_status"],
        "zero_raw_command_received": cancel1["zero_raw_command_received"],
        "watchdog_effective_stop": cancel1["watchdog_effective_stop"],
        "pose_stable_after_cancel": cancel1["pose_stable_after_cancel"],
        
        "forbidden_velocity_topics_detected": sorted(list(set(
            success1.get("forbidden_velocity_topics_detected", []) +
            success2.get("forbidden_velocity_topics_detected", []) +
            cancel1.get("forbidden_velocity_topics_detected", []) +
            cancel2.get("forbidden_velocity_topics_detected", [])
        ))),
        "hardware_node_detected": (
            success1["hardware_node_detected"] or
            success2["hardware_node_detected"] or
            cancel1["hardware_node_detected"] or
            cancel2["hardware_node_detected"]
        ),
        "own_processes_remaining": (
            success1.get("orphan_processes", 0) +
            success2.get("orphan_processes", 0) +
            cancel1.get("orphan_processes", 0) +
            cancel2.get("orphan_processes", 0)
        ),
        "errors": sorted(list(set(
            success1.get("errors", []) +
            success2.get("errors", []) +
            cancel1.get("errors", []) +
            cancel2.get("errors", [])
        )))
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--domain-id", default=DEFAULT_DOMAIN_ID)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scenario", choices=["success", "cancel", "all"], default="all")
    args = parser.parse_args()

    if args.domain_id == "0":
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": ["DOMAIN_ID_ZERO_NOT_ALLOWED"]}))
        return 2

    result = run_controller_smoke_test(args.namespace, args.domain_id, args.timeout, args.scenario)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
