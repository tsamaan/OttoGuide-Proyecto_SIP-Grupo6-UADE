#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the DirectNav2ActionBridge (Fase 2H.1.2).

Public CLI (normal usage): --base-domain-id, --timeout, --output.

The parent process validates inputs, derives four independent ROS_DOMAIN_ID
values from --base-domain-id (offsets 0..3), then launches one isolated
child process per scenario via this same script with the internal
--scenario flag. Each child performs exactly one rclpy.init() against a
single ROS_DOMAIN_ID, brings up the offline sandbox, creates one
DirectNav2ActionBridge and one independent telemetry observer, runs its
scenario, tears everything down, and exits. The parent never initializes
rclpy itself; it only spawns children sequentially, collects their JSON
results, and aggregates the final decision.

Scenarios (base + offset):
  base + 0 = ntp_success      NavigateToPose success
  base + 1 = ntp_cancel       NavigateToPose cancel
  base + 2 = fw_success       FollowWaypoints success (3 fixed relative waypoints)
  base + 3 = fw_unreachable   FollowWaypoints with one waypoint outside the map
"""

import argparse
import asyncio
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"
THIS_FILE = Path(__file__).resolve()

sys.path.insert(0, str(CODE_ROOT))

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_BASE_DOMAIN_ID = "212"
DEFAULT_TIMEOUT_S = 120.0

MIN_DOMAIN_ID = 1
MAX_DOMAIN_ID = 232
MAXIMUM_OFFSET = 3

SCENARIOS = ("ntp_success", "ntp_cancel", "fw_success", "fw_unreachable")

GOAL_FORWARD_OFFSET_M = 0.50
CANCEL_GOAL_FORWARD_OFFSET_M = 1.5
UNREACHABLE_ABSOLUTE_XY = (5.0, 5.0)
GOAL_TOLERANCE_M = 0.12
GOAL_OUTSIDE_MAP_ERROR_CODE = 204

FW_SUCCESS_RELATIVE_WAYPOINTS = ((0.30, 0.00), (0.30, 0.20), (0.00, 0.20))
FW_UNREACHABLE_REACHABLE_OFFSET_M = (0.30, 0.00)

PLANAR_NONZERO_TOLERANCE = 1e-4
POSE_STABLE_TOLERANCE_M = 0.002
CANCEL_PRECONDITION_MOTION_M = 0.02
CANCEL_DISTANCE_REMAINING_REDUCTION_M = 0.02

FORBIDDEN_GLOBAL_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav")
FORBIDDEN_BRIDGE_NODE_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav", "/cmd_vel_raw", "/cmd_vel_safe")
FORBIDDEN_NODE_SUBSTRINGS = ("unitree", "livox_sdk_bridge", "livox_ros_driver", "realsense")
FORBIDDEN_MISSION_NODE_SUBSTRINGS = ("simple_commander", "basic_navigator")

BRIDGE_NODE_NAME = "direct_nav2_action_bridge"


def _planar_nonzero(linear_x: float, linear_y: float, angular_z: float) -> bool:
    return (
        abs(linear_x) > PLANAR_NONZERO_TOLERANCE
        or abs(linear_y) > PLANAR_NONZERO_TOLERANCE
        or abs(angular_z) > PLANAR_NONZERO_TOLERANCE
    )


def _rotate_relative(x0: float, y0: float, yaw0: float, dx: float, dy: float) -> tuple[float, float]:
    """Transforms a (dx, dy) offset in the robot's initial frame into map coordinates."""
    gx = x0 + dx * math.cos(yaw0) - dy * math.sin(yaw0)
    gy = y0 + dx * math.sin(yaw0) + dy * math.cos(yaw0)
    return gx, gy


def _normalize_progress(sequence: list[int]) -> list[int]:
    """Collapses only consecutive duplicates; never treats gaps/regressions as equivalent."""
    normalized: list[int] = []
    for value in sequence:
        if not normalized or normalized[-1] != value:
            normalized.append(value)
    return normalized


def _build_env(domain_id: str) -> dict:
    env = os.environ.copy()
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["ROS_DOMAIN_ID"] = domain_id
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = str(CODE_ROOT)
    else:
        env["PYTHONPATH"] = f"{CODE_ROOT}:{env['PYTHONPATH']}"
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


def _action_list(env: dict, timeout: float) -> list[str]:
    proc = _run(["ros2", "action", "list"], env, timeout)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _node_info_text(node_fqn: str, env: dict, timeout: float) -> str | None:
    proc = _run(["ros2", "node", "info", node_fqn], env, timeout)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout


def _parse_node_info_sections(text: str) -> dict[str, list[str]]:
    """Parses 'ros2 node info' output into {section_name: [entity_names]}.

    Section headers are lines ending in ':' with no leading whitespace beyond
    indentation; entity lines look like '  /topic/name: msg/Type'.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if line == stripped and not stripped.startswith("/"):
            # Top-level, non-indented line that isn't the node name itself.
            continue
        if stripped.endswith(":") and not stripped.startswith("/"):
            current = stripped[:-1].strip()
            sections[current] = []
            continue
        if current is not None:
            name = stripped.split(":", 1)[0].strip()
            if name:
                sections[current].append(name)
    return sections


def _process_group_is_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _shutdown_and_count_orphans(launch_process) -> int:
    """Shuts down only the process group this smoke test itself created.

    pgid is always assigned (or the function returns) before any signal is
    sent: a ProcessLookupError while resolving the PGID means the launch
    process already terminated on its own, which is 0 orphans, not an
    error to retry against an unresolved/stale identifier.
    """
    if launch_process is None:
        return 0

    pgid: int | None = None
    try:
        pgid = os.getpgid(launch_process.pid)
    except ProcessLookupError:
        return 0

    try:
        os.killpg(pgid, signal.SIGINT)
        launch_process.wait(timeout=15.0)
    except Exception:
        pass
    try:
        if _process_group_is_alive(pgid):
            os.killpg(pgid, signal.SIGTERM)
            launch_process.wait(timeout=10.0)
    except Exception:
        pass
    time.sleep(1.0)
    return 1 if _process_group_is_alive(pgid) else 0


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


def _build_child_output_path(parent_pid: int, scenario: str, domain: str) -> Path:
    """Builds a one-time-use output path: PID + time_ns() + scenario +
    domain. Never reused across invocations, so a stale JSON from a
    previous run can never be silently re-read as if it were fresh.
    """
    token = f"{parent_pid}_{time.time_ns()}_{scenario}_{domain}"
    return Path(f"/tmp/ottoguide_direct_bridge_child_{token}.json")


def _validate_child_result(
    payload: dict, expected_scenario: str, expected_domain: str, returncode: int
) -> list[str]:
    """Pure identity/exit-code validation of a child's reported JSON.

    Never trusts the child's self-reported ok/scenario/domain_id alone:
    cross-checks them against what the parent actually requested and
    against the process's real exit code.
    """
    errors: list[str] = []

    if payload.get("scenario") != expected_scenario:
        errors.append(
            f"CHILD_SCENARIO_MISMATCH:{payload.get('scenario')!r}!={expected_scenario!r}"
        )
    if str(payload.get("domain_id")) != str(expected_domain):
        errors.append(
            f"CHILD_DOMAIN_MISMATCH:{payload.get('domain_id')!r}!={expected_domain!r}"
        )

    ok = payload.get("ok")
    if ok is True and returncode != 0:
        errors.append(f"CHILD_EXIT_CODE_MISMATCH:ok=True,returncode={returncode}")
    elif ok is False and returncode != 1:
        errors.append(f"CHILD_EXIT_CODE_MISMATCH:ok=False,returncode={returncode}")

    return errors


def validate_domain_id_range(base: int, maximum_offset: int) -> str | None:
    if not isinstance(base, int) or base < MIN_DOMAIN_ID or base > MAX_DOMAIN_ID:
        return "INVALID_DOMAIN_ID"
    if base + maximum_offset > MAX_DOMAIN_ID:
        return "DERIVED_DOMAIN_ID_OUT_OF_RANGE"
    return None


def parse_base_domain_id(raw_value: str) -> tuple[int | None, str | None]:
    try:
        return int(raw_value), None
    except (TypeError, ValueError):
        return None, "INVALID_DOMAIN_ID"


class TelemetryObserver:
    """Independent telemetry observer: its own ROS context, node, and a
    dedicated background thread/executor. Never shares the bridge's
    asyncio loop or the bridge's own internal spin thread, and never
    blocks any coroutine with rclpy.spin_once().
    """

    def __init__(self, namespace: str):
        import rclpy
        import rclpy.context
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor

        self._rclpy = rclpy
        self._context = rclpy.context.Context()
        rclpy.init(context=self._context)
        self._node = rclpy.create_node("direct_bridge_smoke_observer", context=self._context)

        self._lock = threading.Lock()
        self._latest_odom = None
        self._latest_safe = None
        self.raw_nonzero = False
        self.safe_nonzero = False
        self.odom_count = 0
        self.safe_count = 0
        self._mark_odom = 0
        self._mark_safe = 0

        self._node.create_subscription(Odometry, f"/{namespace}/odom", self._on_odom, 10)
        self._node.create_subscription(Twist, f"/{namespace}/cmd_vel_raw", self._on_raw, 10)
        self._node.create_subscription(Twist, f"/{namespace}/cmd_vel_safe", self._on_safe, 10)

        self._executor = SingleThreadedExecutor(context=self._context)
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._thread.start()

    def _on_odom(self, msg) -> None:
        with self._lock:
            self._latest_odom = msg
            self.odom_count += 1

    def _on_raw(self, msg) -> None:
        if _planar_nonzero(msg.linear.x, msg.linear.y, msg.angular.z):
            with self._lock:
                self.raw_nonzero = True

    def _on_safe(self, msg) -> None:
        with self._lock:
            self._latest_safe = msg
            self.safe_count += 1
            if _planar_nonzero(msg.linear.x, msg.linear.y, msg.angular.z):
                self.safe_nonzero = True

    def mark(self) -> None:
        with self._lock:
            self._mark_odom = self.odom_count
            self._mark_safe = self.safe_count

    def telemetry_advanced_since_mark(self) -> bool:
        with self._lock:
            return self.odom_count != self._mark_odom or self.safe_count != self._mark_safe

    def get_xy_yaw(self):
        with self._lock:
            if self._latest_odom is None:
                return None, None, None
            p = self._latest_odom.pose.pose.position
            q = self._latest_odom.pose.pose.orientation
            yaw = 2.0 * math.atan2(q.z, q.w)
            return p.x, p.y, yaw

    def get_twist(self):
        with self._lock:
            if self._latest_odom is None:
                return None
            t = self._latest_odom.twist.twist
            return t.linear.x, t.linear.y, t.angular.z

    def get_safe_twist(self):
        with self._lock:
            if self._latest_safe is None:
                return None
            t = self._latest_safe
            return t.linear.x, t.linear.y, t.angular.z

    def wait_for_odom(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._latest_odom is not None:
                    return True
            time.sleep(0.05)
        return False

    def shutdown(self) -> None:
        """Tears down executor/node/context/thread.

        Non-critical teardown failures (executor/node/context) are
        accumulated and raised together as OBSERVER_SHUTDOWN_FAILED. A
        thread that fails to terminate after join() is never silenced: it
        always raises the distinct OBSERVER_THREAD_STILL_ALIVE, even if
        every other teardown step succeeded.
        """
        errors: list[str] = []
        try:
            self._executor.shutdown(timeout_sec=1.0)
        except Exception as exc:
            errors.append(f"executor_shutdown:{exc}")
        try:
            self._node.destroy_node()
        except Exception as exc:
            errors.append(f"node_destroy:{exc}")
        try:
            if self._rclpy.ok(context=self._context):
                self._rclpy.shutdown(context=self._context)
        except Exception as exc:
            errors.append(f"context_shutdown:{exc}")

        thread_still_alive = False
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
            thread_still_alive = self._thread.is_alive()

        if thread_still_alive:
            raise RuntimeError("OBSERVER_THREAD_STILL_ALIVE")
        if errors:
            raise RuntimeError("OBSERVER_SHUTDOWN_FAILED:" + ";".join(errors))


async def run_single_scenario(name: str, namespace: str, domain_id: str, timeout_s: float) -> dict:
    from src.navigation.direct_nav2_action_bridge import DirectNav2ActionBridge
    from src.navigation.models import NavWaypoint, NavigationTerminalStatus

    result = {
        "ok": False,
        "scenario": name,
        "domain_id": domain_id,
        "errors": [],
        "orphan_processes": 0,
        "metrics": {},
    }

    env = _build_env(domain_id)
    launch_process = None
    observer: TelemetryObserver | None = None
    bridge: DirectNav2ActionBridge | None = None
    log_fd = None

    try:
        log_path = f"/tmp/ottoguide_direct_bridge_{name}_{domain_id}.log"
        log_fd = open(log_path, "w")
        launch_process = subprocess.Popen(
            ["bash", str(RUNTIME_WRAPPER), f"sandbox_namespace:={namespace}", "use_rviz:=false"],
            env=env, stdout=log_fd, stderr=subprocess.STDOUT, text=True, preexec_fn=os.setsid
        )

        overall_deadline = time.monotonic() + timeout_s

        fqns = [
            f"/{namespace}/map_server",
            f"/{namespace}/planner_server",
            f"/{namespace}/controller_server",
            f"/{namespace}/collision_monitor",
            f"/{namespace}/behavior_server",
            f"/{namespace}/bt_navigator",
        ]
        deadline = time.monotonic() + timeout_s
        for fqn in fqns:
            if _wait_for_node_discovered(fqn, env, deadline):
                if not _wait_for_lifecycle_active(fqn, env, deadline):
                    result["errors"].append(f"{fqn}_NOT_ACTIVE")
            else:
                result["errors"].append(f"{fqn}_NOT_DISCOVERED")
        if result["errors"]:
            return result

        nodes = _node_list(env, timeout=5.0)
        if any(any(f in n.lower() for f in FORBIDDEN_NODE_SUBSTRINGS) for n in nodes):
            result["errors"].append("HARDWARE_NODE_DETECTED")
        if any(any(f in n.lower() for f in FORBIDDEN_MISSION_NODE_SUBSTRINGS) for n in nodes):
            result["errors"].append("MISSION_NODE_DETECTED")

        topics = _topic_list(env, timeout=5.0)
        if any(any(t.endswith(f) for f in FORBIDDEN_GLOBAL_VELOCITY_TOPIC_SUFFIXES) for t in topics):
            result["errors"].append("FORBIDDEN_VELOCITY_TOPIC_DETECTED")
        if result["errors"]:
            return result

        # This process's own rclpy.init() calls (observer and bridge, each
        # with its own isolated Context) read ROS_DOMAIN_ID/ROS_LOCALHOST_ONLY
        # from os.environ at call time; the env= passed to the sandbox
        # subprocess above does not affect this process's own environment.
        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        os.environ["ROS_DOMAIN_ID"] = domain_id

        # Independent observer: its own context/node/thread, never shares
        # the bridge's asyncio loop or internal spin thread.
        observer = TelemetryObserver(namespace)
        if not observer.wait_for_odom(15.0):
            result["errors"].append("ODOM_NOT_RECEIVED")
            return result

        x0, y0, yaw0 = observer.get_xy_yaw()

        bridge = DirectNav2ActionBridge(namespace=namespace)
        await bridge.start()

        # Bridge node graph inspection: the bridge's own node must carry no
        # publisher/subscriber for any velocity topic. Ownership is never
        # inferred from a global topic list -- only from this node's own
        # publishers/subscribers section.
        bridge_node_fqn = f"/{namespace}/{BRIDGE_NODE_NAME}"
        node_info_text = None
        node_info_deadline = time.monotonic() + 15.0
        while node_info_text is None and time.monotonic() < node_info_deadline:
            node_info_text = _node_info_text(bridge_node_fqn, env, timeout=10.0)
            if node_info_text is None:
                await asyncio.sleep(1.0)
        if node_info_text is None:
            result["errors"].append("BRIDGE_NODE_INFO_UNAVAILABLE")
            return result
        sections = _parse_node_info_sections(node_info_text)
        bridge_pub_sub = set(sections.get("Publishers", [])) | set(sections.get("Subscribers", []))
        forbidden_in_bridge_graph = [
            t for t in bridge_pub_sub
            if any(t.endswith(suffix) for suffix in FORBIDDEN_BRIDGE_NODE_VELOCITY_TOPIC_SUFFIXES)
        ]
        if forbidden_in_bridge_graph:
            result["errors"].append(f"BRIDGE_NODE_HAS_VELOCITY_IO:{forbidden_in_bridge_graph}")

        actions = _action_list(env, timeout=5.0)
        for required_action in (f"/{namespace}/navigate_to_pose", f"/{namespace}/follow_waypoints"):
            if required_action not in actions:
                result["errors"].append(f"ACTION_NOT_AVAILABLE:{required_action}")
        if result["errors"]:
            return result

        MAP_X_BOUNDS = (-1.0, 1.0)
        MAP_Y_BOUNDS = (-0.75, 0.75)

        def _clamp(x, y):
            return (
                min(max(x, MAP_X_BOUNDS[0] + 0.1), MAP_X_BOUNDS[1] - 0.1),
                min(max(y, MAP_Y_BOUNDS[0] + 0.1), MAP_Y_BOUNDS[1] - 0.1),
            )

        if name == "ntp_success":
            await _run_ntp_success(bridge, observer, x0, y0, yaw0, overall_deadline, result, _clamp, NavWaypoint, NavigationTerminalStatus)
        elif name == "ntp_cancel":
            await _run_ntp_cancel(bridge, observer, x0, y0, yaw0, overall_deadline, result, _clamp, NavWaypoint, NavigationTerminalStatus)
        elif name == "fw_success":
            await _run_fw_success(bridge, observer, x0, y0, yaw0, overall_deadline, result, NavWaypoint, NavigationTerminalStatus)
        elif name == "fw_unreachable":
            await _run_fw_unreachable(bridge, observer, x0, y0, yaw0, overall_deadline, result, _clamp, NavWaypoint, NavigationTerminalStatus)
        else:
            result["errors"].append(f"UNKNOWN_SCENARIO:{name}")
            return result

        # Pose stability check, common to every scenario.
        await asyncio.sleep(0.5)
        p1 = observer.get_xy_yaw()
        await asyncio.sleep(0.5)
        p2 = observer.get_xy_yaw()
        pose_stable = False
        if p1[0] is not None and p2[0] is not None:
            pose_stable = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) <= POSE_STABLE_TOLERANCE_M
        result["metrics"]["pose_stable"] = pose_stable
        if not pose_stable:
            result["errors"].append("POSE_NOT_STABLE")

        final_twist = observer.get_twist()
        final_safe_twist = observer.get_safe_twist()
        if final_twist is not None and _planar_nonzero(*final_twist):
            result["errors"].append("FINAL_ODOM_TWIST_NOT_ZERO")
        if final_safe_twist is not None and _planar_nonzero(*final_safe_twist):
            result["errors"].append("FINAL_SAFE_TWIST_NOT_ZERO")

    except Exception as exc:
        result["errors"].append(f"EXCEPTION: {exc}")
    finally:
        if bridge:
            try:
                await bridge.close()
            except Exception as exc:
                result["errors"].append(f"BRIDGE_CLOSE_FAILED:{exc}")
        if observer:
            try:
                observer.shutdown()
            except Exception as exc:
                result["errors"].append(str(exc))
        result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)
        if result["orphan_processes"] > 0:
            result["errors"].append("ORPHAN_PROCESSES")
        if log_fd:
            log_fd.close()

    result["ok"] = len(result["errors"]) == 0
    return result


async def _run_ntp_success(bridge, observer, x0, y0, yaw0, overall_deadline, result, clamp, NavWaypoint, NavigationTerminalStatus):
    gx, gy = clamp(*_rotate_relative(x0, y0, yaw0, GOAL_FORWARD_OFFSET_M, 0.0))
    wp = NavWaypoint(gx, gy, yaw0, "map")

    nav_task = asyncio.create_task(bridge.send_goal(wp))

    distance_samples: list[float] = []
    deadline = time.monotonic() + 15.0
    status = await bridge.get_status()
    while not status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
        await asyncio.sleep(0.1)
        status = await bridge.get_status()

    if not status.task_active:
        result["errors"].append("GOAL_NOT_ACCEPTED")
        return

    goal_uuid = status.goal_uuid
    deadline = time.monotonic() + 60.0
    while status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
        await asyncio.sleep(0.1)
        status = await bridge.get_status()
        if status.distance_remaining_m is not None:
            if not distance_samples or distance_samples[-1] != status.distance_remaining_m:
                distance_samples.append(status.distance_remaining_m)

    nav_task_result = await nav_task
    res = await bridge.get_last_result()

    result["metrics"]["goal_accepted"] = bool(goal_uuid)
    result["metrics"]["goal_uuid"] = goal_uuid
    result["metrics"]["feedback_count"] = status.feedback_count
    result["metrics"]["distance_sample_count"] = len(distance_samples)
    result["metrics"]["navigation_task_result"] = nav_task_result

    if not goal_uuid:
        result["errors"].append("GOAL_UUID_EMPTY")
    if status.feedback_count <= 0:
        result["errors"].append("NO_FEEDBACK_RECEIVED")
    if len(distance_samples) < 2:
        result["errors"].append("INSUFFICIENT_DISTANCE_SAMPLES")
    elif distance_samples[0] <= distance_samples[-1]:
        result["errors"].append("DISTANCE_REMAINING_DID_NOT_DECREASE")
    if not (res and res.status == NavigationTerminalStatus.SUCCEEDED and res.succeeded):
        result["errors"].append("NAV_NOT_SUCCEEDED")
    if not nav_task_result:
        result["errors"].append("NAVIGATION_TASK_RESULT_FALSE")
    if not observer.raw_nonzero:
        result["errors"].append("RAW_NEVER_NONZERO")
    if not observer.safe_nonzero:
        result["errors"].append("SAFE_NEVER_NONZERO")

    await asyncio.sleep(0.5)
    x1, y1, _ = observer.get_xy_yaw()
    dist_moved = math.hypot(x1 - x0, y1 - y0) if x1 is not None else 0.0
    final_goal_distance = math.hypot(gx - x1, gy - y1) if x1 is not None else float("inf")
    result["metrics"]["distance_moved_m"] = dist_moved
    result["metrics"]["final_goal_distance_m"] = final_goal_distance
    if dist_moved <= 0.05:
        result["errors"].append("DID_NOT_MOVE_ENOUGH")
    if final_goal_distance >= GOAL_TOLERANCE_M:
        result["errors"].append("FINAL_GOAL_DISTANCE_OUT_OF_TOLERANCE")


async def _run_ntp_cancel(bridge, observer, x0, y0, yaw0, overall_deadline, result, clamp, NavWaypoint, NavigationTerminalStatus):
    gx, gy = clamp(*_rotate_relative(x0, y0, yaw0, CANCEL_GOAL_FORWARD_OFFSET_M, 0.0))
    wp = NavWaypoint(gx, gy, yaw0, "map")

    nav_task = asyncio.create_task(bridge.send_goal(wp))

    deadline = time.monotonic() + 15.0
    status = await bridge.get_status()
    while not status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
        await asyncio.sleep(0.1)
        status = await bridge.get_status()

    if not status.task_active:
        result["errors"].append("GOAL_NOT_ACCEPTED")
        return

    goal_uuid = status.goal_uuid
    distance_samples: list[float] = []
    moved = False
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and time.monotonic() < overall_deadline:
        await asyncio.sleep(0.1)
        status = await bridge.get_status()
        if status.distance_remaining_m is not None:
            if not distance_samples or distance_samples[-1] != status.distance_remaining_m:
                distance_samples.append(status.distance_remaining_m)
        xc, yc, _ = observer.get_xy_yaw()
        if xc is None:
            continue
        displaced = math.hypot(xc - x0, yc - y0)
        distance_reduced = (
            len(distance_samples) >= 2 and (distance_samples[0] - distance_samples[-1]) >= CANCEL_DISTANCE_REMAINING_REDUCTION_M
        )
        if (
            displaced > CANCEL_PRECONDITION_MOTION_M
            and observer.raw_nonzero
            and observer.safe_nonzero
            and status.feedback_count > 0
            and distance_reduced
        ):
            moved = True
            break

    result["metrics"]["goal_uuid"] = goal_uuid
    result["metrics"]["feedback_count"] = status.feedback_count
    result["metrics"]["distance_sample_count"] = len(distance_samples)
    if len(distance_samples) >= 2:
        result["metrics"]["distance_remaining_reduction_m"] = distance_samples[0] - distance_samples[-1]

    if not moved:
        result["errors"].append("CANCEL_PRECONDITION_MOTION_NOT_OBSERVED")
        nav_task.cancel()
        return

    observer.mark()
    await bridge.cancel_navigation()
    nav_task_result = await nav_task
    res = await bridge.get_last_result()

    result["metrics"]["cancel_requested"] = bool(res and res.cancel_requested)
    result["metrics"]["cancel_accepted"] = bool(res and res.cancel_accepted)
    result["metrics"]["cancel_terminal_status"] = res.status.value if res else None
    result["metrics"]["navigation_task_result"] = nav_task_result

    if not res or res.status != NavigationTerminalStatus.CANCELED:
        result["errors"].append("NOT_CANCELED")
    if not res or not res.cancel_requested:
        result["errors"].append("CANCEL_NOT_REQUESTED")
    if not res or not res.cancel_accepted:
        result["errors"].append("CANCEL_NOT_ACCEPTED")
    if res and res.goal_uuid != goal_uuid:
        result["errors"].append("CANCEL_UUID_MISMATCH")
    if nav_task_result:
        result["errors"].append("NAVIGATION_TASK_RESULT_TRUE_AFTER_CANCEL")

    await asyncio.sleep(2.0)
    if not observer.telemetry_advanced_since_mark():
        result["errors"].append("NO_TELEMETRY_AFTER_CANCEL")
    twist_after = observer.get_twist()
    safe_after = observer.get_safe_twist()
    if twist_after is not None and _planar_nonzero(*twist_after):
        result["errors"].append("NOT_STOPPED_AFTER_CANCEL")
    if safe_after is not None and _planar_nonzero(*safe_after):
        result["errors"].append("SAFE_NOT_STOPPED_AFTER_CANCEL")


def _build_cumulative_waypoints_xy(x0: float, y0: float, yaw0: float, offsets) -> list[tuple[float, float]]:
    """Each offset is a delta from the *previous* waypoint (cumulative path),
    not independently relative to the start -- matching the resolution
    already established by the existing, validated
    smoke_test_offline_waypoint_follower.py for this exact offset tuple.
    Treating each offset as independently relative to x0/y0 would require
    a near-180-degree in-place reversal on the third leg, which the
    sandbox's unmodifiable DWB tuning (movement_time_allowance=10.0s,
    Oscillation critic) cannot complete.
    """
    cx, cy = x0, y0
    waypoints_xy = []
    for dx, dy in offsets:
        cx, cy = _rotate_relative(cx, cy, yaw0, dx, dy)
        waypoints_xy.append((cx, cy))
    return waypoints_xy


async def _run_fw_success(bridge, observer, x0, y0, yaw0, overall_deadline, result, NavWaypoint, NavigationTerminalStatus):
    waypoints_xy = _build_cumulative_waypoints_xy(x0, y0, yaw0, FW_SUCCESS_RELATIVE_WAYPOINTS)
    waypoints = [NavWaypoint(wx, wy, yaw0, "map") for wx, wy in waypoints_xy]

    nav_task = asyncio.create_task(bridge.navigate_to_waypoints(waypoints))

    progress: list[int] = []
    deadline = time.monotonic() + 15.0
    status = await bridge.get_status()
    while not status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
        await asyncio.sleep(0.1)
        status = await bridge.get_status()

    if not status.task_active:
        result["errors"].append("GOAL_NOT_ACCEPTED")
        return

    deadline = time.monotonic() + 60.0
    while status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
        await asyncio.sleep(0.1)
        status = await bridge.get_status()
        progress.append(status.active_waypoint_index)

    nav_task_result = await nav_task
    res = await bridge.get_last_result()
    normalized = _normalize_progress(progress)

    result["metrics"]["requested_waypoint_count"] = len(waypoints)
    result["metrics"]["feedback_progression"] = normalized
    result["metrics"]["missed_waypoints"] = [
        {"index": mw.index, "error_code": mw.error_code} for mw in (res.missed_waypoints if res else ())
    ]
    result["metrics"]["final_waypoint_index"] = res.final_waypoint_index if res else None
    result["metrics"]["navigation_task_result"] = nav_task_result

    if normalized != [0, 1, 2]:
        result["errors"].append(f"FEEDBACK_PROGRESSION_NOT_012:{normalized}")
    if not (res and res.status == NavigationTerminalStatus.SUCCEEDED and res.succeeded):
        result["errors"].append("FW_NOT_SUCCEEDED")
    if res and res.missed_waypoints:
        result["errors"].append("FW_HAS_MISSED_WAYPOINTS")
    if not nav_task_result:
        result["errors"].append("NAVIGATION_TASK_RESULT_FALSE")
    if not observer.raw_nonzero:
        result["errors"].append("RAW_NEVER_NONZERO")
    if not observer.safe_nonzero:
        result["errors"].append("SAFE_NEVER_NONZERO")

    await asyncio.sleep(0.5)
    x1, y1, _ = observer.get_xy_yaw()
    gx, gy = waypoints_xy[-1]
    dist_moved = math.hypot(x1 - x0, y1 - y0) if x1 is not None else 0.0
    final_goal_distance = math.hypot(gx - x1, gy - y1) if x1 is not None else float("inf")
    result["metrics"]["distance_moved_m"] = dist_moved
    result["metrics"]["final_goal_distance_m"] = final_goal_distance
    if dist_moved <= 0.1:
        result["errors"].append("DID_NOT_MOVE_ENOUGH")
    if final_goal_distance >= GOAL_TOLERANCE_M:
        result["errors"].append("FINAL_GOAL_DISTANCE_OUT_OF_TOLERANCE")


def _validate_fw_unreachable_result(
    res, normalized_progress: list[int], nav_task_result: bool, NavigationTerminalStatus
) -> list[str]:
    """Pure validation of the FollowWaypoints-unreachable contract.

    Never accepts REJECTED, TIMEOUT, or ERROR as a substitute for the
    required ABORTED terminal, and never short-circuits: every check below
    always runs against the final nav_task result, regardless of whether
    local polling ever observed task_active=True (a goal can abort before
    a single poll iteration completes).
    """
    errors: list[str] = []

    if res is None:
        errors.append("FW_UNREACHABLE_NO_RESULT")
        return errors

    if res.status == NavigationTerminalStatus.REJECTED:
        errors.append("FW_UNREACHABLE_REJECTED_NOT_ALLOWED")
    if res.status == NavigationTerminalStatus.TIMEOUT:
        errors.append("FW_UNREACHABLE_REPORTED_AS_TIMEOUT")
    if res.status == NavigationTerminalStatus.ERROR:
        errors.append("FW_UNREACHABLE_REPORTED_AS_ERROR")
    if res.status != NavigationTerminalStatus.ABORTED:
        errors.append(f"FW_UNREACHABLE_WRONG_TERMINAL_STATUS:{res.status}")

    missed_by_index = {mw.index: mw.error_code for mw in res.missed_waypoints}
    if 1 not in missed_by_index:
        errors.append("MISSED_WAYPOINT_INDEX_1_ABSENT")
    elif missed_by_index[1] != GOAL_OUTSIDE_MAP_ERROR_CODE:
        errors.append(f"MISSED_WAYPOINT_ERROR_CODE_NOT_204:{missed_by_index[1]}")

    if 2 in normalized_progress:
        errors.append("FEEDBACK_PROGRESSED_TO_INDEX_2")
    if nav_task_result:
        errors.append("NAVIGATION_TASK_RESULT_TRUE_FOR_UNREACHABLE")

    return errors


async def _run_fw_unreachable(bridge, observer, x0, y0, yaw0, overall_deadline, result, clamp, NavWaypoint, NavigationTerminalStatus):
    rx, ry = clamp(*_rotate_relative(x0, y0, yaw0, *FW_UNREACHABLE_REACHABLE_OFFSET_M))
    waypoints = [
        NavWaypoint(rx, ry, yaw0, "map"),
        NavWaypoint(UNREACHABLE_ABSOLUTE_XY[0], UNREACHABLE_ABSOLUTE_XY[1], yaw0, "map"),
        NavWaypoint(rx, ry, yaw0, "map"),
    ]

    nav_task = asyncio.create_task(bridge.navigate_to_waypoints(waypoints))

    # A single bounded wait on nav_task.done() covers both a goal that
    # aborts before any poll iteration observes task_active=True, and a
    # goal that runs through normal feedback first -- there is no early
    # branch that returns without validating the full contract below.
    progress: list[int] = []
    deadline = time.monotonic() + 60.0
    while not nav_task.done() and time.monotonic() < deadline and time.monotonic() < overall_deadline:
        await asyncio.sleep(0.1)
        status = await bridge.get_status()
        progress.append(status.active_waypoint_index)

    if not nav_task.done():
        nav_task.cancel()
        result["errors"].append("FW_UNREACHABLE_DID_NOT_COMPLETE")
        return

    nav_task_result = await nav_task
    res = await bridge.get_last_result()
    normalized = _normalize_progress(progress)

    result["metrics"]["terminal_status"] = res.status.value if res else None
    result["metrics"]["missed_waypoints"] = {mw.index: mw.error_code for mw in (res.missed_waypoints if res else ())}
    result["metrics"]["feedback_progression"] = normalized
    result["metrics"]["navigation_task_result"] = nav_task_result

    result["errors"].extend(
        _validate_fw_unreachable_result(res, normalized, nav_task_result, NavigationTerminalStatus)
    )


def _scenario_main(args: argparse.Namespace) -> int:
    """Child entry point: exactly one rclpy lifecycle, one ROS_DOMAIN_ID."""
    domain_id = args.base_domain_id
    result = asyncio.run(run_single_scenario(args.scenario, DEFAULT_NAMESPACE, domain_id, args.timeout))
    payload = json.dumps(result, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    return 0 if result["ok"] else 1


def _parent_main(args: argparse.Namespace) -> int:
    def _fail(errors: list[str]) -> int:
        payload = {"ok": False, "decision": "FAIL", "errors": errors}
        output_str = json.dumps(payload)
        print(output_str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output_str)
        return 2

    base, parse_error = parse_base_domain_id(args.base_domain_id)
    if parse_error is not None:
        return _fail([parse_error])

    range_error = validate_domain_id_range(base, MAXIMUM_OFFSET)
    if range_error is not None:
        return _fail([range_error])

    if args.timeout <= 0:
        return _fail(["TIMEOUT_MUST_BE_POSITIVE"])

    scenarios = list(zip(SCENARIOS, (base + i for i in range(len(SCENARIOS)))))

    all_ok = True
    overall_payload = []

    for name, domain in scenarios:
        domain_str = str(domain)
        child_output = _build_child_output_path(os.getpid(), name, domain_str)
        if child_output.exists():
            # A token derived from time_ns() must never already exist;
            # if it does, refuse to read it rather than risk reusing a
            # stale result from an unrelated invocation.
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_OUTPUT_PREEXISTING"]}
            overall_payload.append(res)
            all_ok = False
            continue

        child_cmd = [
            sys.executable, str(THIS_FILE),
            "--scenario", name,
            "--base-domain-id", domain_str,
            "--timeout", str(args.timeout),
            "--output", str(child_output),
        ]
        try:
            completed = subprocess.run(
                child_cmd, capture_output=True, text=True, timeout=args.timeout + 60.0
            )
        except subprocess.TimeoutExpired:
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_PROCESS_TIMEOUT"]}
            overall_payload.append(res)
            all_ok = False
            continue

        if not child_output.is_file():
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_OUTPUT_MISSING"]}
            overall_payload.append(res)
            all_ok = False
            continue

        try:
            res = json.loads(child_output.read_text())
        except Exception:
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_OUTPUT_INVALID_JSON"]}
            overall_payload.append(res)
            all_ok = False
            continue

        identity_errors = _validate_child_result(res, name, domain_str, completed.returncode)
        if identity_errors:
            res = dict(res)
            res["errors"] = list(res.get("errors", [])) + identity_errors
            res["ok"] = False

        overall_payload.append(res)
        if not res.get("ok"):
            all_ok = False

    final_payload = {"ok": all_ok, "decision": "PASS" if all_ok else "FAIL", "scenarios": overall_payload}
    output_str = json.dumps(final_payload, indent=2)
    print(output_str)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_str)

    return 0 if all_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-domain-id", default=DEFAULT_BASE_DOMAIN_ID)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scenario", choices=SCENARIOS, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.scenario:
        return _scenario_main(args)
    return _parent_main(args)


if __name__ == "__main__":
    sys.exit(main())
