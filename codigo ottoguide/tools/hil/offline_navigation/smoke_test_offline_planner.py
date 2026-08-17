#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox global planner.

Starts the sandbox runtime via the isolated wrapper script under a dedicated
ROS_DOMAIN_ID, waits for planner_server and map_server to become active,
sends a ComputePathToPose action goal over the synthetic map, and checks the
resulting path. Accepts the presence and active status of controller_server in
the integrated runtime, but only exercises planning.

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
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose
from rclpy.action import ActionClient
from rclpy.node import Node

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_DOMAIN_ID = "85"
DEFAULT_TIMEOUT_S = 40.0

# Synthetic start/goal chosen to lie within the free corridor of
# offline_sandbox_test_map.yaml (origin [-1.0, -0.75], resolution 0.05,
# 40x30 px -> world bounds x in [-1.0, 1.0], y in [-0.75, 0.75]).
DEFAULT_START_XY = (-0.75, 0.0)
DEFAULT_GOAL_XY = (0.75, 0.0)
PATH_ENDPOINT_TOLERANCE_M = 0.10

FORBIDDEN_NODE_SUBSTRINGS = (
    "unitree",
    "livox_sdk_bridge",
    "livox_ros_driver",
    "realsense",
)
FORBIDDEN_CONTROLLER_NODE_SUBSTRING = "controller_server"


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
    """Query the real lifecycle state of a node via `ros2 lifecycle get`.

    Returns the state name (e.g. "active") or None if the query failed or
    the node does not expose a lifecycle service.
    """
    proc = _run(["ros2", "lifecycle", "get", node_fqn], env, timeout)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    # Output format is "<state> [<id>]"; take the first token.
    return proc.stdout.strip().split()[0].lower()


def _wait_for_node_discovered(env: dict, namespace: str, deadline: float) -> list[str]:
    """Wait until map_server and planner_server appear in `ros2 node list`.

    This only confirms node *discovery*, not lifecycle state; callers must
    separately query `_lifecycle_get` to confirm the node is actually active.
    """
    nodes: list[str] = []
    while time.monotonic() < deadline:
        nodes = _node_list(env, timeout=5.0)
        if f"/{namespace}/map_server" in nodes and f"/{namespace}/planner_server" in nodes:
            return nodes
        time.sleep(1.0)
    return nodes


def _wait_for_lifecycle_active(node_fqn: str, env: dict, deadline: float) -> bool:
    while time.monotonic() < deadline:
        state = _lifecycle_get(node_fqn, env, timeout=5.0)
        if state == "active":
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


class _PlannerSmokeClient(Node):
    def __init__(self, namespace: str) -> None:
        super().__init__("offline_planner_smoke_test_client")
        action_name = f"/{namespace}/compute_path_to_pose"
        self._client = ActionClient(self, ComputePathToPose, action_name)
        self._action_name = action_name

    def wait_for_server(self, timeout_s: float) -> bool:
        return self._client.wait_for_server(timeout_sec=timeout_s)

    def compute_path(self, start: PoseStamped, goal: PoseStamped, timeout_s: float):
        goal_msg = ComputePathToPose.Goal()
        goal_msg.start = start
        goal_msg.goal = goal
        goal_msg.use_start = True

        send_goal_future = self._client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_goal_future, timeout_sec=timeout_s)
        goal_handle = send_goal_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return None, "GOAL_REJECTED"

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout_s)
        wrapped_result = result_future.result()
        if wrapped_result is None:
            return None, "RESULT_TIMEOUT"
        if wrapped_result.status != GoalStatus.STATUS_SUCCEEDED:
            return None, f"GOAL_STATUS_{wrapped_result.status}"
        return wrapped_result.result.path, "SUCCEEDED"


def _path_summary(path) -> dict:
    poses = path.poses
    summary = {
        "pose_count": len(poses),
        "frame": path.header.frame_id,
        "all_finite": True,
        "first_pose": None,
        "last_pose": None,
    }
    for pose_stamped in poses:
        x = pose_stamped.pose.position.x
        y = pose_stamped.pose.position.y
        if not (math.isfinite(x) and math.isfinite(y)):
            summary["all_finite"] = False
    if poses:
        summary["first_pose"] = (poses[0].pose.position.x, poses[0].pose.position.y)
        summary["last_pose"] = (poses[-1].pose.position.x, poses[-1].pose.position.y)
    return summary


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


def run_planner_smoke_test(
    namespace: str,
    domain_id: str,
    timeout_s: float,
    start_xy: tuple[float, float],
    goal_xy: tuple[float, float],
) -> dict:
    result = {
        "ok": False,
        "decision": "FAIL",
        "namespace": namespace,
        "domain_id": domain_id,
        "start_pose": list(start_xy),
        "goal_pose": list(goal_xy),
        "map_server_node_discovered": False,
        "planner_server_node_discovered": False,
        "map_server_lifecycle_active": False,
        "planner_server_lifecycle_active": False,
        "planner_server_active": False,
        "action_server_available": False,
        "path_result": "NOT_ATTEMPTED",
        "path_pose_count": 0,
        "path_frame": None,
        "path_first_pose_near_start": False,
        "path_last_pose_near_goal": False,
        "path_all_finite": False,
        "controller_server_present": False,
        "collision_monitor_present": False,
        "global_cmd_vel_detected": False,
        "global_cmd_vel_nav_detected": False,
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

        node_deadline = time.monotonic() + timeout_s
        nodes = _wait_for_node_discovered(env, namespace, node_deadline)
        map_server_fqn = f"/{namespace}/map_server"
        planner_server_fqn = f"/{namespace}/planner_server"
        controller_server_fqn = f"/{namespace}/controller_server"
        collision_monitor_fqn = f"/{namespace}/collision_monitor"
        result["map_server_node_discovered"] = map_server_fqn in nodes
        result["planner_server_node_discovered"] = planner_server_fqn in nodes
        # In the integrated runtime, controller_server and collision_monitor are
        # present and active; this test only exercises planning and reports
        # their presence as information, never as a failure condition.
        result["controller_server_present"] = controller_server_fqn in nodes
        result["collision_monitor_present"] = collision_monitor_fqn in nodes
        result["hardware_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
            for node in nodes
        )

        if result["map_server_node_discovered"]:
            result["map_server_lifecycle_active"] = _wait_for_lifecycle_active(
                map_server_fqn, env, node_deadline
            )
        if result["planner_server_node_discovered"]:
            result["planner_server_lifecycle_active"] = _wait_for_lifecycle_active(
                planner_server_fqn, env, node_deadline
            )
        result["planner_server_active"] = result["planner_server_lifecycle_active"]

        if not result["planner_server_node_discovered"]:
            result["errors"].append("PLANNER_SERVER_NOT_DISCOVERED_WITHIN_TIMEOUT")
        elif not result["planner_server_lifecycle_active"]:
            result["errors"].append("PLANNER_SERVER_NOT_ACTIVE_WITHIN_TIMEOUT")
        else:
            os.environ["ROS_LOCALHOST_ONLY"] = "1"
            os.environ["ROS_DOMAIN_ID"] = domain_id
            rclpy.init(args=None)
            rclpy_initialized = True

            client_node = _PlannerSmokeClient(namespace)
            try:
                result["action_server_available"] = client_node.wait_for_server(
                    timeout_s=min(15.0, timeout_s)
                )
                if not result["action_server_available"]:
                    result["errors"].append("ACTION_SERVER_NOT_AVAILABLE")
                else:
                    start_pose = _make_pose("map", *start_xy)
                    goal_pose = _make_pose("map", *goal_xy)
                    path, status = client_node.compute_path(
                        start_pose, goal_pose, timeout_s=min(20.0, timeout_s)
                    )
                    result["path_result"] = status
                    if path is not None:
                        summary = _path_summary(path)
                        result["path_pose_count"] = summary["pose_count"]
                        result["path_frame"] = summary["frame"]
                        result["path_all_finite"] = summary["all_finite"]
                        if summary["first_pose"] is not None:
                            fx, fy = summary["first_pose"]
                            result["path_first_pose_near_start"] = (
                                math.hypot(fx - start_xy[0], fy - start_xy[1]) < PATH_ENDPOINT_TOLERANCE_M
                            )
                        if summary["last_pose"] is not None:
                            lx, ly = summary["last_pose"]
                            result["path_last_pose_near_goal"] = (
                                math.hypot(lx - goal_xy[0], ly - goal_xy[1]) < PATH_ENDPOINT_TOLERANCE_M
                            )
            finally:
                client_node.destroy_node()

        topics = _topic_list(env, timeout=5.0)
        result["global_cmd_vel_detected"] = "/cmd_vel" in topics
        result["global_cmd_vel_nav_detected"] = "/cmd_vel_nav" in topics

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
        and result["planner_server_active"]
        and result["action_server_available"]
        and result["path_result"] == "SUCCEEDED"
        and result["path_pose_count"] >= 2
        and result["path_frame"] == "map"
        and result["path_all_finite"]
        and result["path_first_pose_near_start"]
        and result["path_last_pose_near_goal"]
        and not result["global_cmd_vel_detected"]
        and not result["global_cmd_vel_nav_detected"]
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
    parser.add_argument("--start-x", type=float, default=DEFAULT_START_XY[0])
    parser.add_argument("--start-y", type=float, default=DEFAULT_START_XY[1])
    parser.add_argument("--goal-x", type=float, default=DEFAULT_GOAL_XY[0])
    parser.add_argument("--goal-y", type=float, default=DEFAULT_GOAL_XY[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.domain_id == "0":
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": ["DOMAIN_ID_ZERO_NOT_ALLOWED"]}))
        return 2

    result = run_planner_smoke_test(
        args.namespace,
        args.domain_id,
        args.timeout,
        (args.start_x, args.start_y),
        (args.goal_x, args.goal_y),
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
