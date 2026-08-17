#!/usr/bin/env python3
"""ROS 2 runtime smoke test for the Nav2 offline sandbox.

Starts the sandbox launch under a dedicated ROS_DOMAIN_ID, waits for at
least one message on the map/odom/scan topics, checks /tf and /tf_static
presence, checks absence of forbidden global topics and physical hardware
nodes, then shuts the launch down and reports whether any child process of
this smoke test is left orphaned.

This script does not touch the real robot, does not open rosbags, does not
install packages, and does not kill ROS processes that do not belong to
this smoke test's own dedicated domain/launch.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"

DEFAULT_NAMESPACE = "offline_nav"
DEFAULT_DOMAIN_ID = "78"
DEFAULT_TIMEOUT_S = 30.0

FORBIDDEN_NODE_SUBSTRINGS = (
    "unitree",
    "livox_sdk_bridge",
    "livox_ros_driver",
    "realsense",
)


def _run(cmd: list[str], env: dict, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )


def _build_env(domain_id: str) -> dict:
    env = os.environ.copy()
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["ROS_DOMAIN_ID"] = domain_id
    return env


def _topic_list(env: dict, timeout: float) -> list[str]:
    proc = _run(["ros2", "topic", "list"], env, timeout)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _node_list(env: dict, timeout: float) -> list[str]:
    proc = _run(["ros2", "node", "list"], env, timeout)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _topic_has_message(topic: str, env: dict, timeout: float) -> bool:
    proc = _run(
        ["ros2", "topic", "echo", "--once", "--timeout", str(timeout), topic],
        env,
        timeout + 5.0,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _process_group_is_alive(pgid: int) -> bool:
    """Probe whether any process in the given process group still exists.

    Sends signal 0 (no-op) to the group: this raises ProcessLookupError if
    nothing in the group exists anymore, without actually affecting any
    process. Only ever targets this script's own launched process group.
    """
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _shutdown_and_count_orphans(launch_process: "subprocess.Popen[str] | None") -> int:
    """Shut down the wrapper process group and verify it actually disappears.

    Returns the number of own process-group members still alive after a
    graceful SIGINT, a follow-up SIGTERM, and a final grace period. Never
    targets any process outside this script's own launched process group.
    """
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


def run_smoke_test(
    namespace: str, domain_id: str, timeout_s: float
) -> dict:
    result = {
        "ok": False,
        "decision": "FAIL",
        "namespace": namespace,
        "domain_id": domain_id,
        "map_message_received": False,
        "odom_message_received": False,
        "scan_message_received": False,
        "tf_available": False,
        "tf_static_available": False,
        "global_cmd_vel_detected": False,
        "global_cmd_vel_nav_detected": False,
        "hardware_node_detected": False,
        "orphan_processes": 0,
        "errors": [],
    }

    env = _build_env(domain_id)
    launch_process = None

    try:
        launch_process = subprocess.Popen(
            [
                "bash", str(RUNTIME_WRAPPER),
                f"sandbox_namespace:={namespace}",
                "use_rviz:=false",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )

        deadline = time.monotonic() + timeout_s
        topics: list[str] = []
        while time.monotonic() < deadline:
            topics = _topic_list(env, timeout=5.0)
            if any(t.endswith("/map") for t in topics) and any(
                t.endswith("/odom") for t in topics
            ) and any(t.endswith("/scan") for t in topics):
                break
            time.sleep(1.0)

        result["map_message_received"] = _topic_has_message(
            f"/{namespace}/map", env, timeout=5.0
        )
        result["odom_message_received"] = _topic_has_message(
            f"/{namespace}/odom", env, timeout=5.0
        )
        result["scan_message_received"] = _topic_has_message(
            f"/{namespace}/scan", env, timeout=5.0
        )

        # Re-poll topic discovery with retries: /tf_static uses a transient-local
        # publisher whose presence in `ros2 topic list` can lag briefly behind
        # the static_transform_publisher nodes actually coming up.
        tf_deadline = time.monotonic() + 10.0
        while time.monotonic() < tf_deadline:
            topics = _topic_list(env, timeout=5.0)
            if "/tf" in topics and "/tf_static" in topics:
                break
            time.sleep(1.0)

        result["tf_available"] = "/tf" in topics
        result["tf_static_available"] = "/tf_static" in topics

        result["global_cmd_vel_detected"] = "/cmd_vel" in topics
        result["global_cmd_vel_nav_detected"] = "/cmd_vel_nav" in topics

        nodes = _node_list(env, timeout=5.0)
        result["hardware_node_detected"] = any(
            any(forbidden in node.lower() for forbidden in FORBIDDEN_NODE_SUBSTRINGS)
            for node in nodes
        )

    except FileNotFoundError as exc:
        result["errors"].append(f"ROS_TOOLING_NOT_FOUND: {exc}")
    except subprocess.TimeoutExpired as exc:
        result["errors"].append(f"COMMAND_TIMEOUT: {exc}")
    finally:
        result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)

    result["ok"] = (
        not result["errors"]
        and result["map_message_received"]
        and result["odom_message_received"]
        and result["scan_message_received"]
        and result["tf_available"]
        and result["tf_static_available"]
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
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.domain_id == "0":
        print(json.dumps({"ok": False, "decision": "FAIL", "errors": ["DOMAIN_ID_ZERO_NOT_ALLOWED"]}))
        return 2

    result = run_smoke_test(args.namespace, args.domain_id, args.timeout)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
