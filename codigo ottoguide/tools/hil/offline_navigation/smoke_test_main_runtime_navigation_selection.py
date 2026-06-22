#!/usr/bin/env python3
"""ROS 2 runtime smoke test for main.py's navigation backend selection (Fase 2H.2).

Public CLI (normal usage): --base-domain-id, --timeout, --output.

The parent process validates inputs, derives four independent ROS_DOMAIN_ID
values from --base-domain-id (offsets 0..3), then launches one isolated
child process per scenario via this same script with the internal
--scenario flag. Each child performs exactly one rclpy lifecycle against a
single ROS_DOMAIN_ID, brings up the offline sandbox, then drives main.py's
real lifespan() (with NAVIGATION_BACKEND=direct) and the real
TourOrchestrator it builds -- never the bridge directly. No Uvicorn is
started and no socket is opened: lifespan() is entered as an async context
manager over a minimal fake FastAPI app (only `.state` is needed by
lifespan/TourOrchestrator/api.router). The parent never touches ROS itself;
it only spawns children sequentially, collects their JSON results, and
aggregates the final decision.

Scenarios (base + offset):
  base + 0 = boot_shutdown      lifespan boot + clean shutdown, no tour
  base + 1 = tour_success       one reachable waypoint via TourOrchestrator
  base + 2 = interaction_cancel long goal cancelled by request_interaction()
  base + 3 = emergency_cancel    long goal cancelled by emergency_stop()

This file never reaudits DirectNav2ActionBridge's own internal cancel/
terminal-ownership contract (already accepted in the 2H.1 series); it only
exercises main.py's selection/lifespan/readiness wiring around it.
"""

import argparse
import asyncio
import json
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
DEFAULT_BASE_DOMAIN_ID = "204"
DEFAULT_TIMEOUT_S = 150.0

MIN_DOMAIN_ID = 1
MAX_DOMAIN_ID = 232
MAXIMUM_OFFSET = 3

SCENARIOS = ("boot_shutdown", "tour_success", "interaction_cancel", "emergency_cancel")

GOAL_FORWARD_OFFSET_M = 0.50
LONG_GOAL_FORWARD_OFFSET_M = 1.5

REQUIRED_COMPONENTS = (
    "map_server",
    "planner_server",
    "controller_server",
    "collision_monitor",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
)
FORBIDDEN_NODE_SUBSTRINGS = ("unitree", "livox_sdk_bridge", "livox_ros_driver", "realsense")
FORBIDDEN_MISSION_NODE_SUBSTRINGS = ("simple_commander", "basic_navigator")

_INTERACTION_DEPENDENCY_MOCKS = ("pyttsx3", "speech_recognition", "aiohttp")
_APP_MODULE_PREFIXES = ("main", "src", "src.", "config", "config.")


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


def _list_pids_in_pgid(pgid: int) -> list[int]:
    """Enumerates exactly the PIDs currently in the given process group, for
    the targeted-SIGKILL fallback step (never a wildcard/by-name kill)."""
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,pgid", "--no-headers"],
            capture_output=True, text=True, timeout=5.0,
        )
    except Exception:
        return []
    pids: list[int] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, group = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if group == pgid:
            pids.append(pid)
    return pids


def _shutdown_and_count_orphans(launch_process) -> int:
    """Shuts down only the process group this smoke test itself created.

    pgid is always resolved (or the function returns) before any signal is
    sent: a ProcessLookupError while resolving it means the launch process
    already terminated on its own -- 0 orphans, never an error to retry
    against an unresolved identifier.

    Liveness is polled on the *process group* directly (not on
    launch_process.wait(), which only tracks the immediate bash-wrapper
    child) because run_offline_navigation_runtime.sh's own `wait
    "${LAUNCH_PID}"` inside its SIGINT/TERM trap can return before every
    nav2 lifecycle node it spawned has actually exited. The full escalation
    -- SIGINT, wait, SIGTERM, wait, SIGKILL targeted at exactly the PIDs
    still present, final check -- matches the cleanup protocol required for
    this phase; it is never a wildcard/by-name kill.
    """
    if launch_process is None:
        return 0

    pgid: int | None = None
    try:
        pgid = os.getpgid(launch_process.pid)
    except ProcessLookupError:
        return 0

    def _wait_until_gone(deadline: float) -> bool:
        while time.monotonic() < deadline:
            # launch_process is this process's own immediate child (the
            # bash wrapper). Without periodically polling/reaping it,
            # Python leaves it as a zombie in this process's table once it
            # exits -- and a zombie's PID is still a live member of its own
            # process group, so _process_group_is_alive(pgid) would keep
            # reporting "alive" forever even after every real descendant
            # (ros2 launch, every nav2 node) has actually terminated. This
            # was the actual root cause of a false-positive ORPHAN_PROCESSES
            # observed during development, not a real leak: manual
            # `ps`-based verification after the smoke test process itself
            # exited (which auto-reaps any of its own remaining zombies)
            # always showed zero leftover processes.
            launch_process.poll()
            if not _process_group_is_alive(pgid):
                return True
            time.sleep(0.5)
        launch_process.poll()
        return not _process_group_is_alive(pgid)

    try:
        os.killpg(pgid, signal.SIGINT)
    except Exception:
        pass
    if _wait_until_gone(time.monotonic() + 15.0):
        return 0

    try:
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        pass
    if _wait_until_gone(time.monotonic() + 10.0):
        return 0

    for pid in _list_pids_in_pgid(pgid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            pass

    if _wait_until_gone(time.monotonic() + 10.0):
        return 0
    return 1 if _process_group_is_alive(pgid) else 0


def _build_child_output_path(parent_pid: int, scenario: str, domain: str, token_ns: int) -> Path:
    """One-time-use output path keyed on the parent-generated token_ns so
    the output and control files share the same unique identifier."""
    token = f"{parent_pid}_{token_ns}_{scenario}_{domain}"
    return Path(f"/tmp/ottoguide_main_runtime_2h2_child_{token}.json")


def _build_control_file_path(parent_pid: int, scenario: str, domain: str, token_ns: int) -> Path:
    """Atomic lease/control file: written by parent before child launch,
    updated atomically by child with its own PID/PGID and sandbox PID/PGID.
    Parent reads it during timeout cleanup to find the exact processes to
    kill without relying on names or wildcards."""
    token = f"{parent_pid}_{token_ns}_{scenario}_{domain}"
    return Path(f"/tmp/ottoguide_main_runtime_2h2_ctrl_{token}.json")


def _write_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically via os.replace (write to .tmp then rename)."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(str(tmp), str(path))


def _collect_zombie_children() -> list[int]:
    """Returns PIDs of zombie direct children of this process (stat Z*)."""
    my_pid = os.getpid()
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,ppid,stat", "--no-headers"],
            capture_output=True, text=True, timeout=5.0,
        )
    except Exception:
        return []
    zombies: list[int] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if ppid == my_pid and parts[2].startswith("Z"):
            zombies.append(pid)
    return zombies


def _parent_timeout_cleanup(child_proc: "subprocess.Popen[str]", control_file: Path) -> None:
    """Full process-group cleanup escalation used when communicate() times out.

    Sequence:
      SIGINT  → sandbox PGID (from control file) → wait 15 s
      SIGTERM → sandbox PGID                     → wait 10 s
      SIGKILL → exact sandbox PIDs               → wait  5 s
      SIGINT  → child PGID                       → wait  5 s
      SIGTERM → child PGID                       → wait  5 s
      SIGKILL → exact child PIDs                 → wait  5 s
    Never sends signals by name or via wildcards.
    """
    ctrl: dict = {}
    try:
        ctrl = json.loads(control_file.read_text())
    except Exception:
        pass
    sandbox_pgid: int | None = ctrl.get("sandbox_pgid")

    def _wait_pgid_gone(pgid: int, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                pass
            time.sleep(0.5)
        return False

    if sandbox_pgid:
        try:
            os.killpg(sandbox_pgid, signal.SIGINT)
        except Exception:
            pass
        if not _wait_pgid_gone(sandbox_pgid, 15.0):
            try:
                os.killpg(sandbox_pgid, signal.SIGTERM)
            except Exception:
                pass
            if not _wait_pgid_gone(sandbox_pgid, 10.0):
                for pid in _list_pids_in_pgid(sandbox_pgid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except Exception:
                        pass
                _wait_pgid_gone(sandbox_pgid, 5.0)

    # SIGINT → child PGID (resolved live when possible, falls back to ctrl)
    child_pgid: int | None = None
    try:
        child_pgid = os.getpgid(child_proc.pid)
    except Exception:
        child_pgid = ctrl.get("child_pgid")

    if child_pgid:
        try:
            os.killpg(child_pgid, signal.SIGINT)
        except Exception:
            pass
        deadline2 = time.monotonic() + 5.0
        while child_proc.poll() is None and time.monotonic() < deadline2:
            time.sleep(0.5)

        if child_proc.poll() is None:
            try:
                os.killpg(child_pgid, signal.SIGTERM)
            except Exception:
                pass
            deadline3 = time.monotonic() + 5.0
            while child_proc.poll() is None and time.monotonic() < deadline3:
                time.sleep(0.5)

        if child_proc.poll() is None:
            for pid in _list_pids_in_pgid(child_pgid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            try:
                child_proc.wait(timeout=5.0)
            except Exception:
                pass


def _validate_child_result(
    payload: dict, expected_scenario: str, expected_domain: str, returncode: int
) -> list[str]:
    """Pure identity/exit-code validation of a child's reported JSON. Never
    trusts the child's self-reported ok/scenario/domain_id alone."""
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


def _install_interaction_dependency_mocks() -> dict:
    """Installs minimal fakes for the pre-existing, unrelated missing
    packages (pyttsx3/speech_recognition/aiohttp) that block the real
    src.core -> src.interaction import chain on this workstation -- the
    same gap documented in test_architecture_reconciliation_contract.py
    and worked around the same way in test_navigation_runtime_selection.py.
    """
    from unittest.mock import MagicMock

    installed = {}
    for name in _INTERACTION_DEPENDENCY_MOCKS:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
            installed[name] = True
    return installed


def _remove_interaction_dependency_mocks(installed: dict) -> None:
    for name in installed:
        sys.modules.pop(name, None)


def _purge_app_modules() -> None:
    for mod in list(sys.modules):
        if mod == "main" or mod == "src" or mod.startswith("src.") or mod == "config" or mod.startswith("config."):
            del sys.modules[mod]


class _RecordingMockHardware:
    """Wraps the real hardware.mock_adapter.MockHardwareAPI, recording every
    move()/damp() call so the smoke test can assert MotionCommand(0) and
    damp() were actually observed, without inventing a parallel hardware
    implementation."""

    def __init__(self):
        from hardware.mock_adapter import MockHardwareAPI

        self._delegate = MockHardwareAPI()
        self.move_calls: list[tuple[float, float, int]] = []
        self.damp_calls = 0

    async def initialize(self) -> None:
        await self._delegate.initialize()

    async def stand(self) -> None:
        await self._delegate.stand()

    async def damp(self) -> None:
        self.damp_calls += 1
        await self._delegate.damp()

    async def move(self, command) -> None:
        self.move_calls.append((command.linear_x, command.angular_z, command.duration_ms))
        await self._delegate.move(command)

    async def get_state(self) -> dict:
        return await self._delegate.get_state()

    async def emergency_stop(self) -> None:
        await self.damp()


class _FakeState:
    pass


class _FakeApp:
    def __init__(self):
        self.state = _FakeState()


class _FakeRequest:
    """Minimal stand-in for fastapi.Request: api.router._resolve_readiness_errors
    only ever reads request.app.state."""

    def __init__(self, app):
        self.app = app


async def _run_boot_shutdown(orchestrator, app, result: dict) -> None:
    import importlib

    router = importlib.import_module("api.router")
    readiness_errors = await router._resolve_readiness_errors(_FakeRequest(app), orchestrator)
    result["metrics"]["readiness_errors"] = readiness_errors
    if readiness_errors:
        result["errors"].append(f"READINESS_ERRORS_NOT_EMPTY:{readiness_errors}")


async def _run_tour_success(orchestrator, app, result: dict, timeout_s: float) -> None:
    from src.core import TourPlan
    from src.navigation.models import NavWaypoint, NavigationTerminalStatus

    if orchestrator.state_id != "idle":
        result["errors"].append(f"FSM_NOT_IDLE_BEFORE_DISPATCH:{orchestrator.state_id}")
        return

    wp = NavWaypoint(x=GOAL_FORWARD_OFFSET_M, y=0.0, yaw_rad=0.0, frame_id="map")
    plan = TourPlan(waypoints=[wp], tour_id="smoke-2h2-tour-success")
    await orchestrator.dispatch_tour(plan)

    deadline = time.monotonic() + timeout_s
    while orchestrator.state_id == "idle" and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    if orchestrator.state_id != "navigating":
        result["errors"].append(f"FSM_DID_NOT_REACH_NAVIGATING:{orchestrator.state_id}")
        return

    nav_task = orchestrator._nav_task
    if nav_task is not None:
        try:
            await asyncio.wait_for(nav_task, timeout=timeout_s)
        except asyncio.TimeoutError:
            result["errors"].append("NAV_TASK_TIMEOUT")
            return

    deadline2 = time.monotonic() + 10.0
    while orchestrator.state_id == "navigating" and time.monotonic() < deadline2:
        await asyncio.sleep(0.1)

    nav_bridge = app.state.nav_bridge
    res = await nav_bridge.get_last_result()
    status = await nav_bridge.get_status()

    result["metrics"]["final_fsm_state"] = orchestrator.state_id
    result["metrics"]["last_result_status"] = res.status.value if res else None
    result["metrics"]["task_active"] = status.task_active
    result["metrics"]["remote_state_unknown"] = status.remote_state_unknown

    if orchestrator.state_id != "idle":
        result["errors"].append(f"FSM_DID_NOT_RETURN_TO_IDLE:{orchestrator.state_id}")
    if not (res and res.status == NavigationTerminalStatus.SUCCEEDED and res.succeeded):
        result["errors"].append("TOUR_NOT_SUCCEEDED")
    if status.task_active:
        result["errors"].append("GOAL_STILL_ACTIVE")
    if status.remote_state_unknown:
        result["errors"].append("REMOTE_STATE_UNKNOWN")


async def _wait_goal_active_with_feedback(nav_bridge, timeout_s: float) -> "object":
    deadline = time.monotonic() + timeout_s
    status = await nav_bridge.get_status()
    while not status.task_active and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        status = await nav_bridge.get_status()
    if not status.task_active:
        return status
    deadline2 = time.monotonic() + timeout_s
    while status.feedback_count <= 0 and time.monotonic() < deadline2:
        await asyncio.sleep(0.1)
        status = await nav_bridge.get_status()
    return status


async def _run_interaction_cancel(
    orchestrator, app, recording_hardware: _RecordingMockHardware, result: dict, timeout_s: float
) -> None:
    import numpy as np

    from src.core import TourPlan
    from src.navigation.models import NavWaypoint, NavigationTerminalStatus

    wp = NavWaypoint(x=LONG_GOAL_FORWARD_OFFSET_M, y=0.0, yaw_rad=0.0, frame_id="map")
    plan = TourPlan(waypoints=[wp], tour_id="smoke-2h2-interaction-cancel")
    await orchestrator.dispatch_tour(plan)

    nav_bridge = app.state.nav_bridge
    status = await _wait_goal_active_with_feedback(nav_bridge, timeout_s)
    if not status.task_active:
        result["errors"].append("GOAL_NOT_ACTIVE_BEFORE_INTERACTION")
        return
    result["metrics"]["goal_active_before_interaction"] = True

    move_calls_before = len(recording_hardware.move_calls)

    # on_enter_interacting() cancels the nav goal and sends zero velocity
    # as its first two steps, then runs the (offline, likely error/timeout)
    # dialogue pipeline before resume_tour(); this phase only cares about
    # the cancellation contract, never about the dialogue outcome or about
    # the mission resuming -- that policy is explicitly deferred to 2I.
    await asyncio.wait_for(
        orchestrator.request_interaction(np.zeros(1, dtype=np.float32), language="es"),
        timeout=timeout_s,
    )

    res = await nav_bridge.get_last_result()
    status_after = await nav_bridge.get_status()

    result["metrics"]["cancel_requested"] = bool(res and res.cancel_requested)
    result["metrics"]["cancel_accepted"] = bool(res and res.cancel_accepted)
    result["metrics"]["cancel_terminal_status"] = res.status.value if res else None
    result["metrics"]["task_active_after"] = status_after.task_active
    result["metrics"]["remote_state_unknown"] = status_after.remote_state_unknown
    result["metrics"]["mission_resume_policy"] = "DEFERRED_2I"

    if not res or not res.cancel_requested:
        result["errors"].append("CANCEL_NOT_REQUESTED")
    if not res or not res.cancel_accepted:
        result["errors"].append("CANCEL_NOT_ACCEPTED")
    if not res or res.status != NavigationTerminalStatus.CANCELED:
        result["errors"].append("NOT_CANCELED")
    if status_after.task_active:
        result["errors"].append("GOAL_STILL_ACTIVE_AFTER_CANCEL")
    if status_after.remote_state_unknown:
        result["errors"].append("REMOTE_STATE_UNKNOWN")

    zero_command_observed = any(
        abs(vx) < 1e-9 and abs(wz) < 1e-9
        for vx, wz, _dur in recording_hardware.move_calls[move_calls_before:]
    )
    result["metrics"]["zero_command_observed"] = zero_command_observed
    if not zero_command_observed:
        result["errors"].append("ZERO_MOTION_COMMAND_NOT_OBSERVED")

    nav_task = orchestrator._nav_task
    if nav_task is not None and not nav_task.done():
        nav_task.cancel()
        try:
            await nav_task
        except asyncio.CancelledError:
            pass


async def _run_emergency_cancel(
    orchestrator, app, recording_hardware: _RecordingMockHardware, result: dict, timeout_s: float
) -> None:
    from src.core import TourPlan
    from src.navigation.models import NavWaypoint, NavigationTerminalStatus

    wp = NavWaypoint(x=LONG_GOAL_FORWARD_OFFSET_M, y=0.0, yaw_rad=0.0, frame_id="map")
    plan = TourPlan(waypoints=[wp], tour_id="smoke-2h2-emergency-cancel")
    await orchestrator.dispatch_tour(plan)

    nav_bridge = app.state.nav_bridge
    status = await _wait_goal_active_with_feedback(nav_bridge, timeout_s)
    if not status.task_active:
        result["errors"].append("GOAL_NOT_ACTIVE_BEFORE_EMERGENCY")
        return
    result["metrics"]["goal_active_before_emergency"] = True

    move_calls_before = len(recording_hardware.move_calls)
    damp_calls_before = recording_hardware.damp_calls

    await asyncio.wait_for(
        orchestrator.emergency_stop(reason="smoke_test_2h2_emergency"), timeout=timeout_s
    )

    res = await nav_bridge.get_last_result()
    status_after = await nav_bridge.get_status()

    result["metrics"]["final_fsm_state"] = orchestrator.state_id
    result["metrics"]["cancel_terminal_status"] = res.status.value if res else None
    result["metrics"]["damp_calls"] = recording_hardware.damp_calls
    result["metrics"]["task_active_after"] = status_after.task_active
    result["metrics"]["remote_state_unknown"] = status_after.remote_state_unknown

    if orchestrator.state_id != "emergency":
        result["errors"].append(f"FSM_NOT_EMERGENCY:{orchestrator.state_id}")
    if not res or res.status != NavigationTerminalStatus.CANCELED:
        result["errors"].append("NOT_CANCELED")
    if not res or not res.cancel_requested:
        result["errors"].append("CANCEL_NOT_REQUESTED")
    if recording_hardware.damp_calls <= damp_calls_before:
        result["errors"].append("DAMP_NOT_OBSERVED")
    if status_after.task_active:
        result["errors"].append("GOAL_STILL_ACTIVE_AFTER_EMERGENCY")
    if status_after.remote_state_unknown:
        result["errors"].append("REMOTE_STATE_UNKNOWN")

    zero_command_observed = any(
        abs(vx) < 1e-9 and abs(wz) < 1e-9
        for vx, wz, _dur in recording_hardware.move_calls[move_calls_before:]
    )
    result["metrics"]["zero_command_observed"] = zero_command_observed
    if not zero_command_observed:
        result["errors"].append("ZERO_MOTION_COMMAND_NOT_OBSERVED")


async def run_single_scenario(
    name: str,
    namespace: str,
    domain_id: str,
    timeout_s: float,
    control_file: "Path | None" = None,
    child_log_path: "Path | None" = None,
) -> dict:
    result = {
        "ok": False,
        "scenario": name,
        "domain_id": domain_id,
        "errors": [],
        "orphan_processes": 0,
        "metrics": {},
        "owned_threads_remaining": 0,
        "owned_thread_names": [],
        "zombies_remaining": 0,
        "zombie_pids": [],
    }

    thread_baseline = threading.active_count()

    # Write child identity into control file as soon as possible.
    if control_file is not None:
        try:
            ctrl_data: dict = {}
            try:
                ctrl_data = json.loads(control_file.read_text())
            except Exception:
                pass
            ctrl_data["child_pid"] = os.getpid()
            try:
                ctrl_data["child_pgid"] = os.getpgid(os.getpid())
            except Exception:
                ctrl_data["child_pgid"] = None
            ctrl_data["started_at_ns"] = time.time_ns()
            _write_atomic(control_file, ctrl_data)
        except Exception:
            pass

    env = _build_env(domain_id)
    launch_process = None
    log_fd = None
    main_module = None
    installed_mocks: dict = {}

    try:
        log_path_str = (
            str(child_log_path)
            if child_log_path is not None
            else f"/tmp/ottoguide_main_runtime_2h2_{name}_{domain_id}.log"
        )
        log_fd = open(log_path_str, "w")
        launch_process = subprocess.Popen(
            ["bash", str(RUNTIME_WRAPPER), f"sandbox_namespace:={namespace}", "use_rviz:=false"],
            env=env, stdout=log_fd, stderr=subprocess.STDOUT, text=True, preexec_fn=os.setsid
        )

        # Update control file with sandbox PID/PGID now that it's running.
        if control_file is not None:
            try:
                ctrl_data = {}
                try:
                    ctrl_data = json.loads(control_file.read_text())
                except Exception:
                    pass
                ctrl_data["sandbox_pid"] = launch_process.pid
                try:
                    ctrl_data["sandbox_pgid"] = os.getpgid(launch_process.pid)
                except Exception:
                    ctrl_data["sandbox_pgid"] = None
                _write_atomic(control_file, ctrl_data)
            except Exception:
                pass

        fqns = [f"/{namespace}/{component}" for component in REQUIRED_COMPONENTS]
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
        if result["errors"]:
            return result

        # This process's own rclpy.init() (inside DirectNav2ActionBridge,
        # constructed lazily by main.lifespan()) reads ROS_DOMAIN_ID/
        # ROS_LOCALHOST_ONLY from os.environ at call time; the env= passed
        # to the sandbox subprocess above does not affect this process.
        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        os.environ["ROS_DOMAIN_ID"] = domain_id
        os.environ["ROBOT_MODE"] = "mock"
        os.environ["NAVIGATION_BACKEND"] = "direct"
        os.environ["NAVIGATION_DIRECT_REAL_ENABLED"] = "false"
        os.environ["NAVIGATION_ALLOW_STUB_TOURS"] = "false"
        os.environ["NAVIGATION_NAMESPACE"] = namespace
        os.environ["NAVIGATION_NTP_ACTION"] = f"/{namespace}/navigate_to_pose"
        os.environ["NAVIGATION_FW_ACTION"] = f"/{namespace}/follow_waypoints"
        os.environ["NAVIGATION_INITIAL_POSE_TOPIC"] = "/initialpose"

        installed_mocks = _install_interaction_dependency_mocks()
        _purge_app_modules()
        import main as main_module  # noqa: PLC0415

        main_module.get_settings.cache_clear()
        try:
            from src.core.event_bus import OttoEventBus as _OttoEventBus
            _OttoEventBus.reset_for_testing()
        except Exception:
            pass

        recording_hardware = _RecordingMockHardware()
        main_module.get_hardware_adapter = lambda: recording_hardware

        app = _FakeApp()

        async with main_module.lifespan(app):
            from src.navigation import DirectNav2ActionBridge

            if app.state.navigation_backend_requested != "direct":
                result["errors"].append(
                    f"REQUESTED_BACKEND_NOT_DIRECT:{app.state.navigation_backend_requested}"
                )
            if app.state.navigation_backend_resolved != "direct":
                result["errors"].append(
                    f"RESOLVED_BACKEND_NOT_DIRECT:{app.state.navigation_backend_resolved}"
                )
            if not isinstance(app.state.nav_bridge, DirectNav2ActionBridge):
                result["errors"].append("BRIDGE_CLASS_NOT_DIRECT")
            if not app.state.navigation_started:
                result["errors"].append("NAVIGATION_NOT_STARTED")

            orchestrator = app.state.orchestrator
            if orchestrator._nav_bridge is not app.state.nav_bridge:
                result["errors"].append("ORCHESTRATOR_NOT_USING_APP_STATE_BRIDGE")

            result["metrics"]["requested_backend"] = app.state.navigation_backend_requested
            result["metrics"]["resolved_backend"] = app.state.navigation_backend_resolved
            result["metrics"]["bridge_class"] = type(app.state.nav_bridge).__name__
            result["metrics"]["navigation_started"] = app.state.navigation_started

            if not result["errors"]:
                if name == "boot_shutdown":
                    await _run_boot_shutdown(orchestrator, app, result)
                elif name == "tour_success":
                    await _run_tour_success(orchestrator, app, result, timeout_s)
                elif name == "interaction_cancel":
                    await _run_interaction_cancel(orchestrator, app, recording_hardware, result, timeout_s)
                elif name == "emergency_cancel":
                    await _run_emergency_cancel(orchestrator, app, recording_hardware, result, timeout_s)
                else:
                    result["errors"].append(f"UNKNOWN_SCENARIO:{name}")

        # The lifespan's own finally block has now run: hardware safety
        # sequence + nav_bridge.close() already happened.
        shutdown_error = getattr(app.state, "navigation_shutdown_error", None)
        result["metrics"]["shutdown_error"] = shutdown_error
        if shutdown_error:
            result["errors"].append(f"SHUTDOWN_ERROR:{shutdown_error}")

        bridge_after_close = app.state.nav_bridge
        if getattr(bridge_after_close, "_spin_thread", "missing") is not None:
            result["errors"].append("BRIDGE_SPIN_THREAD_NOT_CLOSED")

    except Exception as exc:
        result["errors"].append(f"EXCEPTION:{exc}")
    finally:
        if main_module is not None:
            _remove_interaction_dependency_mocks(installed_mocks)
            _purge_app_modules()
        result["orphan_processes"] = _shutdown_and_count_orphans(launch_process)
        if result["orphan_processes"] > 0:
            result["errors"].append("ORPHAN_PROCESSES")
        if log_fd:
            log_fd.close()

        # Thread leak detection: count threads that outlived the cleanup.
        thread_count_after = threading.active_count()
        owned_remaining = max(0, thread_count_after - thread_baseline)
        result["owned_threads_remaining"] = owned_remaining
        result["owned_thread_names"] = [
            t.name for t in threading.enumerate()
            if t is not threading.main_thread()
        ]

        # Zombie detection: direct children of this process that were not reaped.
        zombie_pids = _collect_zombie_children()
        result["zombies_remaining"] = len(zombie_pids)
        result["zombie_pids"] = zombie_pids

    result["ok"] = len(result["errors"]) == 0
    return result


def _scenario_main(args: argparse.Namespace) -> int:
    """Child entry point: exactly one rclpy lifecycle, one ROS_DOMAIN_ID."""
    domain_id = args.base_domain_id
    control_file: "Path | None" = args.control_file
    child_log_path: "Path | None" = (
        Path(str(args.output).replace(".json", ".log")) if args.output else None
    )
    result = asyncio.run(
        run_single_scenario(
            args.scenario,
            DEFAULT_NAMESPACE,
            domain_id,
            args.timeout,
            control_file=control_file,
            child_log_path=child_log_path,
        )
    )
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

    parent_pid = os.getpid()

    for name, domain in scenarios:
        domain_str = str(domain)
        token_ns = time.time_ns()
        child_output = _build_child_output_path(parent_pid, name, domain_str, token_ns)
        control_file = _build_control_file_path(parent_pid, name, domain_str, token_ns)

        if child_output.exists():
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_OUTPUT_PREEXISTING"]}
            overall_payload.append(res)
            all_ok = False
            continue

        # Write the initial control file before the child starts so it can
        # be read back on timeout even if the child never updates it.
        try:
            _write_atomic(control_file, {
                "token_ns": token_ns,
                "scenario": name,
                "domain_id": domain_str,
                "parent_pid": parent_pid,
                "child_pid": None,
                "child_pgid": None,
                "sandbox_pid": None,
                "sandbox_pgid": None,
                "started_at_ns": None,
            })
        except Exception:
            pass

        child_cmd = [
            sys.executable, str(THIS_FILE),
            "--scenario", name,
            "--base-domain-id", domain_str,
            "--timeout", str(args.timeout),
            "--output", str(child_output),
            "--control-file", str(control_file),
        ]
        child_proc = subprocess.Popen(
            child_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        parent_timeout_cleanup_executed = False
        try:
            # Margin: SIGINT(15s)+SIGTERM(10s)+SIGKILL-settle(5s) sandbox +
            # SIGINT(5s)+SIGTERM(5s)+SIGKILL(5s) child = 45s on top of the
            # child's own timeout_s (which already includes sandbox bringup
            # and cleanup). Using Popen instead of subprocess.run means we
            # can do the full escalation here on TimeoutExpired rather than
            # only killing the immediate child wrapper.
            child_stdout, _child_stderr = child_proc.communicate(timeout=args.timeout + 150.0)
        except subprocess.TimeoutExpired:
            _parent_timeout_cleanup(child_proc, control_file)
            try:
                child_stdout, _child_stderr = child_proc.communicate(timeout=10.0)
            except subprocess.TimeoutExpired:
                child_stdout = ""
            parent_timeout_cleanup_executed = True
            res = {
                "ok": False,
                "scenario": name,
                "domain_id": domain_str,
                "errors": ["CHILD_PROCESS_TIMEOUT"],
                "parent_timeout_cleanup_executed": True,
            }
            overall_payload.append(res)
            all_ok = False
            try:
                control_file.unlink(missing_ok=True)
            except Exception:
                pass
            continue

        completed_returncode = child_proc.returncode
        try:
            control_file.unlink(missing_ok=True)
        except Exception:
            pass

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

        identity_errors = _validate_child_result(res, name, domain_str, completed_returncode)
        if identity_errors:
            res = dict(res)
            res["errors"] = list(res.get("errors", [])) + identity_errors
            res["ok"] = False

        res["parent_timeout_cleanup_executed"] = parent_timeout_cleanup_executed
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
    parser.add_argument("--control-file", type=Path, dest="control_file", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.scenario:
        return _scenario_main(args)
    return _parent_main(args)


if __name__ == "__main__":
    sys.exit(main())
