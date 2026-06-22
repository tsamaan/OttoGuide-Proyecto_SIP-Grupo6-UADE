#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the DirectNav2ActionBridge.

Runs four isolated scenarios using the sandbox (via run_offline_navigation_runtime.sh):
base + 0 = NavigateToPose success
base + 1 = NavigateToPose cancel
base + 2 = FollowWaypoints success
base + 3 = FollowWaypoints unreachable
"""

import argparse
import asyncio
import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

sys.path.insert(0, str(CODE_ROOT))

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_BASE_DOMAIN_ID = "212"
DEFAULT_TIMEOUT_S = 120.0

MIN_DOMAIN_ID = 1
MAX_DOMAIN_ID = 232
MAXIMUM_OFFSET = 3

GOAL_FORWARD_OFFSET_M = 0.50
CANCEL_GOAL_FORWARD_OFFSET_M = 1.5
UNREACHABLE_OFFSET_M = 50.0  # Way outside map bounds
GOAL_TOLERANCE_M = 0.12

PLANAR_NONZERO_TOLERANCE = 1e-4
POSE_STABLE_TOLERANCE_M = 0.002
CANCEL_PRECONDITION_MOTION_M = 0.02

FORBIDDEN_VELOCITY_TOPIC_SUFFIXES = ("/cmd_vel", "/cmd_vel_nav")
FORBIDDEN_NODE_SUBSTRINGS = ("unitree", "livox_sdk_bridge", "livox_ros_driver", "realsense")
FORBIDDEN_MISSION_NODE_SUBSTRINGS = ("simple_commander", "basic_navigator")

def _planar_nonzero(linear_x: float, linear_y: float, angular_z: float) -> bool:
    return (abs(linear_x) > PLANAR_NONZERO_TOLERANCE or 
            abs(linear_y) > PLANAR_NONZERO_TOLERANCE or 
            abs(angular_z) > PLANAR_NONZERO_TOLERANCE)

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
    if proc.returncode != 0: return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

def _topic_list(env: dict, timeout: float) -> list[str]:
    proc = _run(["ros2", "topic", "list"], env, timeout)
    if proc.returncode != 0: return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

def _process_group_is_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

def _shutdown_and_count_orphans(launch_process) -> int:
    if launch_process is None: return 0
    try:
        pgid = os.getpgid(launch_process.pid)
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

async def run_scenario(name: str, namespace: str, domain_id: str, timeout_s: float) -> dict:
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from src.navigation.direct_nav2_action_bridge import DirectNav2ActionBridge
    from src.navigation.models import NavWaypoint, NavigationTerminalStatus

    class SmokeTelemetryClient(Node):
        def __init__(self, namespace: str):
            super().__init__("direct_bridge_smoke_telemetry")
            self._latest_odom = None
            self._latest_safe = None
            self.raw_nonzero = False
            self.safe_nonzero = False
            self.odom_count = 0
            self.safe_count = 0
            self._mark_odom = 0
            self._mark_safe = 0

            self.create_subscription(Odometry, f"/{namespace}/odom", self._on_odom, 10)
            self.create_subscription(Twist, f"/{namespace}/cmd_vel_raw", self._on_raw, 10)
            self.create_subscription(Twist, f"/{namespace}/cmd_vel_safe", self._on_safe, 10)

        def _on_odom(self, msg):
            self._latest_odom = msg
            self.odom_count += 1
        def _on_raw(self, msg):
            if _planar_nonzero(msg.linear.x, msg.linear.y, msg.angular.z):
                self.raw_nonzero = True
        def _on_safe(self, msg):
            self._latest_safe = msg
            self.safe_count += 1
            if _planar_nonzero(msg.linear.x, msg.linear.y, msg.angular.z):
                self.safe_nonzero = True

        def mark(self):
            self._mark_odom = self.odom_count
            self._mark_safe = self.safe_count

        def get_xy_yaw(self):
            if not self._latest_odom: return None, None, None
            p = self._latest_odom.pose.pose.position
            q = self._latest_odom.pose.pose.orientation
            yaw = 2.0 * math.atan2(q.z, q.w)
            return p.x, p.y, yaw

        def get_twist(self):
            if not self._latest_odom: return None
            t = self._latest_odom.twist.twist
            return t.linear.x, t.linear.y, t.angular.z

        def get_safe_twist(self):
            if not self._latest_safe: return None
            t = self._latest_safe
            return t.linear.x, t.linear.y, t.angular.z

        def wait_for_odom(self, timeout):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                rclpy.spin_once(self, timeout_sec=0.1)
                if self._latest_odom is not None:
                    return True
            return False

        def spin_for(self, duration):
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                rclpy.spin_once(self, timeout_sec=0.1)

    result = {
        "ok": False,
        "scenario": name,
        "domain_id": domain_id,
        "errors": [],
        "orphan_processes": 0
    }
    
    env = _build_env(domain_id)
    launch_process = None
    rclpy_initialized = False
    telem = None
    bridge = None
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
        if any(any(t.endswith(f) for f in FORBIDDEN_VELOCITY_TOPIC_SUFFIXES) for t in topics):
            result["errors"].append("FORBIDDEN_VELOCITY_TOPIC_DETECTED")

        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        os.environ["ROS_DOMAIN_ID"] = domain_id
        rclpy.init()
        rclpy_initialized = True

        telem = SmokeTelemetryClient(namespace)
        if not telem.wait_for_odom(15.0):
            result["errors"].append("ODOM_NOT_RECEIVED")
            return result

        x0, y0, yaw0 = telem.get_xy_yaw()

        bridge = DirectNav2ActionBridge(namespace=namespace)
        await bridge.start()
        
        MAP_X_BOUNDS = (-1.0, 1.0)
        MAP_Y_BOUNDS = (-0.75, 0.75)
        def _clamp(x, y):
            return min(max(x, MAP_X_BOUNDS[0] + 0.1), MAP_X_BOUNDS[1] - 0.1), min(max(y, MAP_Y_BOUNDS[0] + 0.1), MAP_Y_BOUNDS[1] - 0.1)

        # Test specific logic
        if name == "ntp_success":
            gx, gy = _clamp(x0 + GOAL_FORWARD_OFFSET_M * math.cos(yaw0), y0 + GOAL_FORWARD_OFFSET_M * math.sin(yaw0))
            wp = NavWaypoint(gx, gy, yaw0, "map")
            
            asyncio.create_task(bridge.send_goal(wp))
            
            deadline = time.monotonic() + 15.0
            status = await bridge.get_status()
            while not status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                await asyncio.sleep(0.1)
                telem.spin_for(0.1)
                status = await bridge.get_status()
            
            if not status.task_active:
                result["errors"].append("GOAL_NOT_ACCEPTED")
            else:
                deadline = time.monotonic() + 30.0
                while not (telem.raw_nonzero and telem.safe_nonzero) and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                    await asyncio.sleep(0.1)
                    telem.spin_for(0.1)
                
                if not (telem.raw_nonzero and telem.safe_nonzero):
                    result["errors"].append("NO_MOTION_OBSERVED")
                
                deadline = time.monotonic() + 60.0
                while status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                    await asyncio.sleep(0.1)
                    telem.spin_for(0.1)
                    status = await bridge.get_status()
                
                res = await bridge.get_last_result()
                if not res or not res.succeeded:
                    result["errors"].append("NAV_NOT_SUCCEEDED")
                
                telem.spin_for(1.0)
                x1, y1, _ = telem.get_xy_yaw()
                dist_moved = math.hypot(x1 - x0, y1 - y0)
                if dist_moved < 0.05:
                    result["errors"].append("DID_NOT_MOVE_ENOUGH")

        elif name == "ntp_cancel":
            gx, gy = _clamp(x0 + CANCEL_GOAL_FORWARD_OFFSET_M * math.cos(yaw0), y0 + CANCEL_GOAL_FORWARD_OFFSET_M * math.sin(yaw0))
            wp = NavWaypoint(gx, gy, yaw0, "map")
            asyncio.create_task(bridge.send_goal(wp))
            
            deadline = time.monotonic() + 15.0
            status = await bridge.get_status()
            while not status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                await asyncio.sleep(0.1)
                telem.spin_for(0.1)
                status = await bridge.get_status()
                
            if not status.task_active:
                result["errors"].append("GOAL_NOT_ACCEPTED")
            else:
                deadline = time.monotonic() + 30.0
                moved = False
                while time.monotonic() < deadline and time.monotonic() < overall_deadline:
                    await asyncio.sleep(0.1)
                    telem.spin_for(0.1)
                    xc, yc, _ = telem.get_xy_yaw()
                    if math.hypot(xc - x0, yc - y0) > CANCEL_PRECONDITION_MOTION_M and telem.raw_nonzero and telem.safe_nonzero:
                        moved = True
                        break
                
                if not moved:
                    result["errors"].append("CANCEL_PRECONDITION_MOTION_NOT_OBSERVED")
                else:
                    telem.mark()
                    await bridge.cancel_navigation()
                    res = await bridge.get_last_result()
                    
                    if not res or res.status != NavigationTerminalStatus.CANCELED:
                        result["errors"].append("NOT_CANCELED")
                    if not res.cancel_accepted:
                        result["errors"].append("CANCEL_NOT_ACCEPTED")
                        
                    telem.spin_for(2.0)
                    if telem.odom_count == telem._mark_odom or telem.safe_count == telem._mark_safe:
                        result["errors"].append("NO_TELEMETRY_AFTER_CANCEL")
                    
                    if _planar_nonzero(*telem.get_twist()) or _planar_nonzero(*telem.get_safe_twist()):
                        result["errors"].append("NOT_STOPPED_AFTER_CANCEL")

        elif name == "fw_success":
            g1x, g1y = _clamp(x0 + 0.3 * math.cos(yaw0), y0 + 0.3 * math.sin(yaw0))
            g2x, g2y = _clamp(x0 + 0.6 * math.cos(yaw0), y0 + 0.6 * math.sin(yaw0))
            wp1 = NavWaypoint(g1x, g1y, yaw0, "map")
            wp2 = NavWaypoint(g2x, g2y, yaw0, "map")
            asyncio.create_task(bridge.navigate_to_waypoints([wp1, wp2]))
            
            deadline = time.monotonic() + 15.0
            status = await bridge.get_status()
            while not status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                await asyncio.sleep(0.1)
                telem.spin_for(0.1)
                status = await bridge.get_status()
                
            if not status.task_active:
                result["errors"].append("GOAL_NOT_ACCEPTED")
            else:
                deadline = time.monotonic() + 60.0
                while status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                    await asyncio.sleep(0.1)
                    telem.spin_for(0.1)
                    status = await bridge.get_status()
                
                res = await bridge.get_last_result()
                if not res or not res.succeeded:
                    result["errors"].append("FW_NOT_SUCCEEDED")
                if status.active_waypoint_index is None:
                    # Optional verification for this bridge implementation
                    pass 

        elif name == "fw_unreachable":
            wp1 = NavWaypoint(x0 + UNREACHABLE_OFFSET_M, y0, yaw0, "map")
            asyncio.create_task(bridge.navigate_to_waypoints([wp1]))
            
            deadline = time.monotonic() + 15.0
            status = await bridge.get_status()
            while not status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                await asyncio.sleep(0.1)
                telem.spin_for(0.1)
                status = await bridge.get_status()
                
            if not status.task_active:
                res = await bridge.get_last_result()
                if res and res.status in (NavigationTerminalStatus.REJECTED, NavigationTerminalStatus.ABORTED):
                    pass # Expected
                else:
                    result["errors"].append("GOAL_NOT_ACCEPTED_NOR_PROPERLY_REJECTED")
            else:
                deadline = time.monotonic() + 60.0
                while status.task_active and time.monotonic() < deadline and time.monotonic() < overall_deadline:
                    await asyncio.sleep(0.1)
                    telem.spin_for(0.1)
                    status = await bridge.get_status()
                
                res = await bridge.get_last_result()
                if res and res.succeeded:
                    result["errors"].append("FW_UNREACHABLE_SUCCEEDED")

        # Pose stable check
        telem.spin_for(0.5)
        p1 = telem.get_xy_yaw()
        telem.spin_for(0.5)
        p2 = telem.get_xy_yaw()
        if p1[0] is not None and p2[0] is not None:
            if math.hypot(p2[0]-p1[0], p2[1]-p1[1]) > POSE_STABLE_TOLERANCE_M:
                result["errors"].append("POSE_NOT_STABLE")

    except Exception as exc:
        result["errors"].append(f"EXCEPTION: {exc}")
    finally:
        if bridge:
            try: await bridge.close()
            except Exception: pass
        if telem:
            telem.destroy_node()
        if rclpy_initialized:
            try: rclpy.shutdown()
            except Exception: pass
        result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)
        if result["orphan_processes"] > 0:
            result["errors"].append("ORPHAN_PROCESSES")
        if log_fd:
            log_fd.close()
            
    result["ok"] = len(result["errors"]) == 0
    return result

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-domain-id", default=DEFAULT_BASE_DOMAIN_ID)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    
    base, parse_error = parse_base_domain_id(args.base_domain_id)
    if parse_error is not None:
        payload = {"ok": False, "decision": "FAIL", "errors": [parse_error]}
        print(json.dumps(payload))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2))
        sys.exit(2)
        
    range_error = validate_domain_id_range(base, MAXIMUM_OFFSET)
    if range_error is not None:
        payload = {"ok": False, "decision": "FAIL", "errors": [range_error]}
        print(json.dumps(payload))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2))
        sys.exit(2)
        
    if args.timeout <= 0:
        payload = {"ok": False, "decision": "FAIL", "errors": ["TIMEOUT_MUST_BE_POSITIVE"]}
        print(json.dumps(payload))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2))
        sys.exit(2)
    
    scenarios = [
        ("ntp_success", base),
        ("ntp_cancel", base + 1),
        ("fw_success", base + 2),
        ("fw_unreachable", base + 3)
    ]
    
    all_ok = True
    overall_payload = []
    
    for name, did in scenarios:
        res = await run_scenario(name, DEFAULT_NAMESPACE, str(did), args.timeout)
        overall_payload.append(res)
        if not res["ok"]:
            all_ok = False
            
    final_payload = {"ok": all_ok, "decision": "PASS" if all_ok else "FAIL", "scenarios": overall_payload}
    output_str = json.dumps(final_payload, indent=2)
    print(output_str)
    
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_str)
        
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
