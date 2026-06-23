#!/usr/bin/env python3
"""Fase 2H.2.6 -- P0 PHYSICAL READ-ONLY evidence collector (Python core).

STATUS: PREPARED_NOT_AUTHORIZED / NOT_EXECUTED.

Standard library only. Every external command is represented as an argv
list (never a shell string, never shell=True, never eval) and run under a
bounded timeout. Three mutually exclusive modes:

* --dry-run (default): executes nothing, describes what real execution
  would do (commands, output files, guards, the expected-HEAD
  requirement), and never writes a bundle.

* --execute-read-only: real introspection (git, ros2, environment), double-
  and triple-gated -- requires the environment variable
  OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES *and* every one of
  --expected-head/--operator-present/--hardstop-present/--area-cleared/
  --movement-not-authorized-acknowledged/--operator-role/--hardstop-type/
  --hardstop-tested-before-session yes/--robot-physically-supervised yes/
  --dual-control-prohibited-acknowledged yes/--output-dir. This mode is
  prepared here but is NEVER invoked by this repository's own tests or
  tooling -- only a future, explicitly authorized field session may run
  it, on the robot's own host.

* --fixture-dir: offline-only simulation for tests. Requires
  OTTOGUIDE_P0_FIXTURE_MODE=YES. Never executes git/ros2/printenv/hostname
  or any other external command; consumes a single canned JSON file and
  produces the exact same bundle shape real execution would, marked
  fixture_mode=true. A fixture can never produce a GO_CANDIDATE bundle
  (the validator enforces this independently), and the read-only
  invariant fields are hardcoded False by this collector regardless of
  what a fixture claims -- a fixture cannot talk this tool into reporting
  a movement it never performed in any mode.

This tool never sends an action goal, never publishes a topic, never
calls a control service, never changes a lifecycle state or a parameter,
and never invokes any motion/velocity/mode command. It is introspection
only, by construction, in every mode.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
P0_DIR = THIS_FILE.parent
CODE_ROOT = P0_DIR.parents[2]
REPO_ROOT = CODE_ROOT.parent

sys.path.insert(0, str(P0_DIR))
import p0_evidence_schema as schema  # noqa: E402

READ_ONLY_AUTHORIZED_ENV = "OTTOGUIDE_P0_READ_ONLY_AUTHORIZED"
FIXTURE_MODE_ENV = "OTTOGUIDE_P0_FIXTURE_MODE"
HEAD_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class CollectorAuthorizationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _CommandResult:
    __slots__ = ("stdout", "stderr", "returncode", "timed_out", "error_class")

    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        timed_out: bool = False,
        error_class: str = "NONE",
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timed_out = timed_out
        self.error_class = error_class


def normalize_command_output(value: "bytes | str | None") -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class _BaseContext:
    fixture_mode = False
    field_collection_executed = False
    physical_control_execution_performed = False

    def __init__(self):
        self.command_log: "list[dict]" = []

    def run(self, label: str, argv: "list[str]", timeout: float = 10.0) -> _CommandResult:
        started = time.monotonic()
        started_utc = schema.utc_now_iso()
        result = self._run_impl(label, argv, timeout)
        ended_utc = schema.utc_now_iso()
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout, stdout_truncated = schema.truncate_output(result.stdout)
        stderr, stderr_truncated = schema.truncate_output(result.stderr)
        self.command_log.append({
            "label": label,
            "argv": list(argv),
            "started_utc": started_utc,
            "ended_utc": ended_utc,
            "duration_ms": duration_ms,
            "exit_code": result.returncode,
            "timed_out": result.timed_out,
            "error_class": result.error_class,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "read_only_classification": "read_only",
        })
        return result

    def _run_impl(self, label: str, argv: "list[str]", timeout: float) -> _CommandResult:
        raise NotImplementedError

    def environment_info(self) -> dict:
        raise NotImplementedError


class _RealContext(_BaseContext):
    """--execute-read-only mode. Never invoked by this repository's own
    tests; prepared for a future, separately authorized field session."""

    field_collection_executed = True
    physical_control_execution_performed = False

    def _run_impl(self, label: str, argv: "list[str]", timeout: float) -> _CommandResult:
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
            )
            error_class = "NONE" if proc.returncode == 0 else "NONZERO_EXIT"
            return _CommandResult(proc.stdout, proc.stderr, proc.returncode, False, error_class)
        except subprocess.TimeoutExpired as exc:
            stdout = normalize_command_output(exc.stdout)
            stderr = normalize_command_output(exc.stderr)
            if stderr:
                stderr = f"{stderr}\nTIMEOUT"
            else:
                stderr = "TIMEOUT"
            return _CommandResult(stdout, stderr, 124, True, "TIMEOUT")
        except OSError as exc:
            return _CommandResult("", f"OSERROR:{exc}", 127, False, "PROCESS_ERROR")

    def environment_info(self) -> dict:
        return {
            "ros_distro": os.environ.get("ROS_DISTRO"),
            "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION"),
            "cyclonedds_uri": os.environ.get("CYCLONEDDS_URI"),
            "hostname": socket.gethostname(),
            "uid": os.getuid() if hasattr(os, "getuid") else None,
            "username": os.environ.get("USER") or os.environ.get("USERNAME"),
        }


class _FixtureContext(_BaseContext):
    """--fixture-dir mode. Offline-only, deterministic, host-independent:
    never reads the real environment or spawns any real command."""

    fixture_mode = True
    field_collection_executed = False
    physical_control_execution_performed = False

    def __init__(self, fixture_data: dict):
        super().__init__()
        self.fixture_data = fixture_data
        self.commands = fixture_data.get("commands", {})

    def _run_impl(self, label: str, argv: "list[str]", timeout: float) -> _CommandResult:
        canned = self.commands.get(label)
        if canned is None:
            return _CommandResult("", f"FIXTURE_LABEL_MISSING:{label}", 1, False, "NONZERO_EXIT")
        return _CommandResult(
            normalize_command_output(canned.get("stdout", "")),
            normalize_command_output(canned.get("stderr", "")),
            int(canned.get("exit_code", 0)),
            bool(canned.get("timed_out", False)),
            str(canned.get("error_class", "NONE")),
        )

    def environment_info(self) -> dict:
        return dict(self.fixture_data.get("environment", {}))

    def topic_list_override(self) -> "list[str] | None":
        return self.fixture_data.get("topic_list")

    def safety_overrides(self) -> dict:
        return dict(self.fixture_data.get("safety_human_checklist", {}))


# ---------------------------------------------------------------------------
# Gather functions -- shared by real and fixture modes via `ctx.run()`.
# ---------------------------------------------------------------------------


def _parse_typed_list(text: str) -> "list[dict]":
    entries = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\S+)\s*(?:\[([^\]]+)\])?$", line)
        if m:
            entries.append({"name": m.group(1), "type": m.group(2)})
    return entries


def gather_git_info(ctx: _BaseContext, repo_root: Path) -> dict:
    branch = ctx.run("git_branch", ["git", "-C", str(repo_root), "branch", "--show-current"]).stdout.strip()
    head = ctx.run("git_head", ["git", "-C", str(repo_root), "rev-parse", "HEAD"]).stdout.strip()
    status = ctx.run(
        "git_status",
        ["git", "-C", str(repo_root), "status", "--short", "--branch", "--untracked-files=all"],
    ).stdout
    tracked_changes: "list[str]" = []
    untracked_paths: "list[str]" = []
    for line in status.splitlines():
        if line.startswith("##"):
            continue
        if line.startswith("??"):
            path = line[2:].strip().strip('"')
            untracked_paths.append(path)
        elif line.strip():
            tracked_changes.append(line.rstrip())
    raw_remote = ctx.run(
        "git_remote_origin", ["git", "-C", str(repo_root), "remote", "get-url", "origin"]
    ).stdout.strip()
    remote = schema.redact_git_url(raw_remote)
    # Fixture mode never touches the real filesystem for this (untracked
    # paths are synthetic), so the symlink check is real-mode only; a
    # fixture's untracked_symlinks is always [] by construction.
    untracked_symlinks: "list[str]" = []
    if not isinstance(ctx, _FixtureContext):
        for rel_path in untracked_paths:
            candidate = repo_root / rel_path
            try:
                if candidate.is_symlink():
                    untracked_symlinks.append(rel_path)
            except OSError:
                pass
    return {
        "actual_branch": branch,
        "actual_head": head,
        "tracked_changes": tracked_changes,
        "tracked_worktree_clean": len(tracked_changes) == 0,
        "untracked_paths": untracked_paths,
        "untracked_symlinks": untracked_symlinks,
        "untracked_allowlist_only": schema.untracked_allowlist_only(untracked_paths),
        "git_remote_metadata": {"origin_url": remote},
    }


def gather_ros_graph(ctx: _BaseContext, topic_list_override: "list[str] | None" = None) -> "tuple[dict, list, list]":
    nodes = [n["name"] for n in _parse_typed_list(ctx.run("ros2_node_list", ["ros2", "node", "list"]).stdout)]
    topics = _parse_typed_list(ctx.run("ros2_topic_list", ["ros2", "topic", "list", "-t"]).stdout)
    services = _parse_typed_list(ctx.run("ros2_service_list", ["ros2", "service", "list", "-t"]).stdout)
    actions = _parse_typed_list(ctx.run("ros2_action_list", ["ros2", "action", "list", "-t"]).stdout)
    topic_names = topic_list_override if topic_list_override is not None else [t["name"] for t in topics]
    critical_names = set(schema.CMD_VEL_TOPICS) | set(schema.SENSOR_TOPICS)
    graph = {
        "nodes": nodes,
        "topics": topics,
        "services": services,
        "actions": actions,
        "critical_topics": [t for t in topics if t["name"] in critical_names],
        "critical_actions": list(actions),
    }
    return graph, topic_names, nodes


def gather_tf_and_localization(ctx: _BaseContext, topic_names: "list[str]") -> dict:
    tf_present = "/tf" in topic_names
    tf_static_present = "/tf_static" in topic_names
    odom_present = "/odom" in topic_names
    map_present = "/map" in topic_names
    map_metadata_present = "/map_metadata" in topic_names

    tf_sample = None
    tf_static_sample = None
    tf_edges_observed: "list[dict]" = []

    def _extract_tf_edges(sample: str, source_topic: str, command_label: str, is_static: bool) -> "list[dict]":
        parent_frames = re.findall(r"(?<!child_)frame_id:\s*(\S+)", sample)
        child_frames = re.findall(r"child_frame_id:\s*(\S+)", sample)
        observed_at = schema.monotonic_now_ns()
        return [
            {
                "parent": parent,
                "child": child,
                "edge": f"{parent}->{child}",
                "source_topic": source_topic,
                "command_label": command_label,
                "observed_at_monotonic_ns": observed_at,
                "is_static": is_static,
            }
            for parent, child in zip(parent_frames, child_frames)
        ]

    if tf_present:
        tf_sample = ctx.run(
            "tf_echo_once", ["ros2", "topic", "echo", "--once", "/tf"], timeout=8.0
        ).stdout or None
        if tf_sample:
            tf_edges_observed.extend(_extract_tf_edges(tf_sample, "/tf", "tf_echo_once", False))
    if tf_static_present:
        tf_static_sample = ctx.run(
            "tf_static_echo_once", ["ros2", "topic", "echo", "--once", "/tf_static"], timeout=8.0
        ).stdout or None
        if tf_static_sample:
            tf_edges_observed.extend(_extract_tf_edges(tf_static_sample, "/tf_static", "tf_static_echo_once", True))

    odom_sample = None
    odom_frequency = {
        "measurement_status": "NOT_ATTEMPTED",
        "sample_count": None,
        "message_window_size": None,
        "window_seconds": None,
        "average_hz": None,
        "minimum_hz": None,
        "maximum_hz": None,
        "command_label": "odom_hz",
        "observed_at_monotonic_ns": None,
    }
    candidate_frame_id = None
    candidate_child_frame_id = None
    if odom_present:
        odom_sample = ctx.run(
            "odom_echo_once", ["ros2", "topic", "echo", "--once", "/odom"], timeout=8.0
        ).stdout or None
        hz_result = ctx.run("odom_hz", ["ros2", "topic", "hz", "/odom"], timeout=8.0)
        hz_text = hz_result.stdout or ""
        avg_m = re.search(r"average rate:\s*([\d.]+)", hz_text)
        min_m = re.search(r"min:\s*([\d.]+)", hz_text)
        max_m = re.search(r"max:\s*([\d.]+)", hz_text)
        window_m = re.search(r"window:\s*(\d+)", hz_text)
        if hz_result.timed_out:
            status = "TIMEOUT"
        elif hz_result.returncode != 0:
            status = "COMMAND_ERROR"
        elif avg_m:
            status = "MEASURED"
        else:
            status = "UNKNOWN"
        _window_count = int(window_m.group(1)) if window_m else None
        odom_frequency = {
            "measurement_status": status,
            "sample_count": _window_count,
            "message_window_size": _window_count,
            "window_seconds": None,
            "average_hz": float(avg_m.group(1)) if avg_m else None,
            "minimum_hz": float(min_m.group(1)) if min_m else None,
            "maximum_hz": float(max_m.group(1)) if max_m else None,
            "command_label": "odom_hz",
            "observed_at_monotonic_ns": schema.monotonic_now_ns(),
        }
        frame_m = re.search(r"frame_id:\s*(\S+)", odom_sample or "")
        child_m = re.search(r"child_frame_id:\s*(\S+)", odom_sample or "")
        candidate_frame_id = frame_m.group(1) if frame_m else None
        candidate_child_frame_id = child_m.group(1) if child_m else None

    return {
        "tf_topic_present": tf_present,
        "tf_static_topic_present": tf_static_present,
        "odom_topic_present": odom_present,
        "map_topic_present": map_present,
        "map_metadata_topic_present": map_metadata_present,
        "single_sample_tf": tf_sample,
        "single_sample_tf_static": tf_static_sample,
        "single_sample_odom": odom_sample,
        "candidate_odom_source": "/odom" if odom_present else None,
        "candidate_odom_type": "nav_msgs/msg/Odometry" if odom_present else None,
        "candidate_odom_frequency": odom_frequency,
        "candidate_odom_frame_id": candidate_frame_id,
        "candidate_child_frame_id": candidate_child_frame_id,
        "map_source": "/map" if map_present else None,
        "map_frame": "map" if map_present else None,
        "tf_edges_observed": tf_edges_observed,
        "required_tf_edges": list(schema.REQUIRED_TF_EDGES),
        "l2_odometry": schema.READINESS_CANDIDATE_OBSERVED if odom_present else schema.READINESS_NOT_READY,
        "l3_localization_map": (
            schema.READINESS_CANDIDATE_OBSERVED if (map_present and tf_present) else schema.READINESS_NOT_READY
        ),
    }


def gather_sensors(ctx: _BaseContext, topic_names: "list[str]") -> dict:
    sensors: dict = {}
    for topic in schema.SENSOR_TOPICS:
        label = topic.strip("/").replace("/", "_")
        if topic not in topic_names:
            sensors[topic] = {
                "present": False, "type": None, "publisher_count": None,
                "frequency_attempted": False, "frequency_result": None,
                "frame_id": None, "sample_collected": False,
                "errors": ["NOT_DISCOVERED"],
            }
            continue
        info_text = ctx.run(f"topic_info_{label}", ["ros2", "topic", "info", "-v", topic], timeout=8.0).stdout
        type_m = re.search(r"Type:\s*(\S+)", info_text or "")
        pub_m = re.search(r"Publisher count:\s*(\d+)", info_text or "")
        topic_type = type_m.group(1) if type_m else None
        is_point_cloud = bool(topic_type and "PointCloud2" in topic_type)
        hz_result = None
        if not is_point_cloud:
            hz_text = ctx.run(f"topic_hz_{label}", ["ros2", "topic", "hz", topic], timeout=5.0).stdout
            hz_m = re.search(r"average rate:\s*([\d.]+)", hz_text or "")
            hz_result = float(hz_m.group(1)) if hz_m else None
        sensors[topic] = {
            "present": True,
            "type": topic_type,
            "publisher_count": int(pub_m.group(1)) if pub_m else None,
            "frequency_attempted": not is_point_cloud,
            "frequency_result": hz_result,
            "frame_id": None,
            "sample_collected": False,
            "errors": [],
        }
    return sensors


def gather_cmd_vel_chain(ctx: _BaseContext, topic_names: "list[str]", nodes: "list[str]") -> dict:
    topics: dict = {}
    for topic in schema.CMD_VEL_TOPICS:
        label = topic.strip("/").replace("/", "_")
        if topic not in topic_names:
            topics[topic] = {
                "topic": topic,
                "present": False,
                "message_type": None,
                "type": None,
                "publisher_count": None,
                "subscriber_count": None,
                "publisher_identities": [],
                "subscriber_identities": [],
                "publishers": [],
                "subscribers": [],
                "physical_consumer_candidate": None,
                "unexpected_owners": [],
                "command_label": f"cmd_vel_info_{label}",
                "observed_at_monotonic_ns": None,
                "qos": None,
            }
            continue
        info_text = ctx.run(f"cmd_vel_info_{label}", ["ros2", "topic", "info", "-v", topic], timeout=8.0).stdout
        type_m = re.search(r"Type:\s*(\S+)", info_text or "")
        pub_m = re.search(r"Publisher count:\s*(\d+)", info_text or "")
        sub_m = re.search(r"Subscription count:\s*(\d+)", info_text or "")
        publisher_ids = re.findall(r"Node name:\s*(\S+)", info_text or "")
        subscriber_ids = re.findall(r"Subscription node name:\s*(\S+)", info_text or "")
        # physical_consumer_candidate: derived from observed subscriber identities.
        # Only set when exactly one subscriber is observed (evidence-based, never invented).
        # Multiple subscribers: first is candidate, rest are unexpected_owners.
        if len(subscriber_ids) == 1:
            physical_consumer_candidate: "str | None" = subscriber_ids[0]
            unexpected_owners: "list[str]" = []
        elif len(subscriber_ids) > 1:
            physical_consumer_candidate = subscriber_ids[0]
            unexpected_owners = subscriber_ids[1:]
        else:
            physical_consumer_candidate = None
            unexpected_owners = []
        topics[topic] = {
            "topic": topic,
            "present": True,
            "message_type": type_m.group(1) if type_m else None,
            "type": type_m.group(1) if type_m else None,
            "publisher_count": int(pub_m.group(1)) if pub_m else None,
            "subscription_count": int(sub_m.group(1)) if sub_m else None,
            "subscriber_count": int(sub_m.group(1)) if sub_m else None,
            "publisher_identities": publisher_ids,
            "subscriber_identities": subscriber_ids,
            "physical_consumer_candidate": physical_consumer_candidate,
            "unexpected_owners": unexpected_owners,
            "command_label": f"cmd_vel_info_{label}",
            "observed_at_monotonic_ns": schema.monotonic_now_ns(),
            "publishers": publisher_ids, "subscribers": subscriber_ids,
            "qos": info_text or None,
        }
    # unexpected_global_cmd_vel: True only when /cmd_vel has at least one active
    # publisher (someone bypassing the safety chain). A topic declared with 0
    # publishers is normal topology bookkeeping, not an active bypass.
    cmd_vel_info = topics.get("/cmd_vel", {})
    cmd_vel_pub_count = cmd_vel_info.get("publisher_count")
    unexpected_global_cmd_vel = (
        isinstance(cmd_vel_pub_count, int)
        and not isinstance(cmd_vel_pub_count, bool)
        and cmd_vel_pub_count > 0
    )
    return {
        "topics": topics,
        "unexpected_global_cmd_vel": unexpected_global_cmd_vel,
        "collision_monitor_observed": any("collision_monitor" in n for n in nodes),
        "controller_server_observed": any("controller_server" in n for n in nodes),
        "consumer_observed": None,
        "status": "OBSERVED_PENDING_PHYSICAL_ANALYSIS",
    }


def gather_safety_checklist(args: argparse.Namespace, ctx: _BaseContext) -> dict:
    overrides = ctx.safety_overrides() if isinstance(ctx, _FixtureContext) else {}

    def _flag(name: str, cli_value: "bool | None") -> bool:
        if name in overrides:
            return bool(overrides[name])
        return bool(cli_value)

    def _text(name: str, cli_value: "str | None") -> "str | None":
        if name in overrides:
            v = overrides[name]
            return str(v) if v is not None else None
        return cli_value

    operator_present = _flag("operator_present", args.operator_present == "yes")
    hardstop_present = _flag("hardstop_present", args.hardstop_present == "yes")
    area_cleared = _flag("area_cleared", args.area_cleared == "yes")
    movement_ack = _flag(
        "movement_not_authorized_acknowledged", args.movement_not_authorized_acknowledged == "yes"
    )
    # v2: explicit CLI flags; never inferred or defaulted.
    operator_identity_or_role = _text("operator_identity_or_role", getattr(args, "operator_role", None))
    hardstop_type = _text("hardstop_type", getattr(args, "hardstop_type", None))
    hardstop_tested = _flag(
        "hardstop_tested_before_session",
        getattr(args, "hardstop_tested_before_session", None) == "yes",
    )
    robot_physically_supervised = _flag(
        "robot_physically_supervised",
        getattr(args, "robot_physically_supervised", None) == "yes",
    )
    dual_control_ack = _flag(
        "dual_control_prohibited_acknowledged",
        getattr(args, "dual_control_prohibited_acknowledged", None) == "yes",
    )
    return {
        "operator_present": operator_present,
        "operator_identity_or_role": operator_identity_or_role,
        "hardstop_present": hardstop_present,
        "hardstop_type": hardstop_type,
        "hardstop_tested_before_session": hardstop_tested,
        "area_cleared": area_cleared,
        "robot_physically_supervised": robot_physically_supervised,
        "dual_control_prohibited_acknowledged": dual_control_ack,
        "movement_not_authorized_acknowledged": movement_ack,
        "notes": overrides.get("notes"),
    }


# ---------------------------------------------------------------------------
# Mode resolution + authorization
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Describe collection without executing it (default).")
    parser.add_argument(
        "--execute-read-only", dest="execute_read_only", action="store_true",
        help="Run real read-only introspection (requires OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES and all gates).",
    )
    parser.add_argument("--fixture-dir", dest="fixture_dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", dest="output_dir", type=Path, default=Path("./p0_readonly_evidence"))
    parser.add_argument("--expected-head", dest="expected_head")
    # Original four gates
    parser.add_argument("--operator-present", dest="operator_present", choices=("yes", "no"))
    parser.add_argument("--hardstop-present", dest="hardstop_present", choices=("yes", "no"))
    parser.add_argument("--area-cleared", dest="area_cleared", choices=("yes", "no"))
    parser.add_argument(
        "--movement-not-authorized-acknowledged", dest="movement_not_authorized_acknowledged",
        choices=("yes", "no"),
    )
    # v2 explicit gates -- required for real mode, optional for fixture/dry-run
    parser.add_argument("--operator-role", dest="operator_role",
                        help="Operator role or identity (non-empty text, required for real mode).")
    parser.add_argument("--hardstop-type", dest="hardstop_type",
                        help="Hardstop type description (non-empty text, required for real mode).")
    parser.add_argument("--hardstop-tested-before-session", dest="hardstop_tested_before_session",
                        choices=("yes", "no"),
                        help="Hardstop was tested before this session (required for real mode).")
    parser.add_argument("--robot-physically-supervised", dest="robot_physically_supervised",
                        choices=("yes", "no"),
                        help="Robot is physically supervised during collection (required for real mode).")
    parser.add_argument("--dual-control-prohibited-acknowledged", dest="dual_control_prohibited_acknowledged",
                        choices=("yes", "no"),
                        help="Dual control prohibition acknowledged (required for real mode).")
    return parser


def resolve_mode(args: argparse.Namespace) -> str:
    """Returns one of 'dry_run', 'real', 'fixture'. Raises
    CollectorAuthorizationError (never executes anything) on any gate
    failure or mode conflict."""
    if args.execute_read_only and args.fixture_dir:
        raise CollectorAuthorizationError("MODE_CONFLICT")

    if args.fixture_dir:
        if os.environ.get(FIXTURE_MODE_ENV) != "YES":
            raise CollectorAuthorizationError("FIXTURE_MODE_NOT_AUTHORIZED")
        return "fixture"

    if args.execute_read_only:
        if os.environ.get(READ_ONLY_AUTHORIZED_ENV) != "YES":
            raise CollectorAuthorizationError("P0_NOT_AUTHORIZED")
        missing = []
        if not args.expected_head or not HEAD_PATTERN.match(args.expected_head.lower()):
            missing.append("--expected-head")
        if args.operator_present != "yes":
            missing.append("--operator-present yes")
        if args.hardstop_present != "yes":
            missing.append("--hardstop-present yes")
        if args.area_cleared != "yes":
            missing.append("--area-cleared yes")
        if args.movement_not_authorized_acknowledged != "yes":
            missing.append("--movement-not-authorized-acknowledged yes")
        if not args.output_dir:
            missing.append("--output-dir")
        # v2 gates
        if not args.operator_role or not args.operator_role.strip():
            missing.append("--operator-role <non-empty>")
        if not args.hardstop_type or not args.hardstop_type.strip():
            missing.append("--hardstop-type <non-empty>")
        if args.hardstop_tested_before_session != "yes":
            missing.append("--hardstop-tested-before-session yes")
        if args.robot_physically_supervised != "yes":
            missing.append("--robot-physically-supervised yes")
        if args.dual_control_prohibited_acknowledged != "yes":
            missing.append("--dual-control-prohibited-acknowledged yes")
        if missing:
            raise CollectorAuthorizationError("P0_NOT_AUTHORIZED:" + ",".join(missing))
        return "real"

    return "dry_run"


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------


def build_bundle(ctx: _BaseContext, args: argparse.Namespace, session_id: str) -> dict:
    session_started_ns = schema.monotonic_now_ns()
    env_info = ctx.environment_info()
    git_info = gather_git_info(ctx, REPO_ROOT)
    topic_override = ctx.topic_list_override() if isinstance(ctx, _FixtureContext) else None
    graph, topic_names, nodes = gather_ros_graph(ctx, topic_override)
    tf_loc = gather_tf_and_localization(ctx, topic_names)
    sensors = gather_sensors(ctx, topic_names)
    cmd_vel = gather_cmd_vel_chain(ctx, topic_names, nodes)
    safety = gather_safety_checklist(args, ctx)

    expected_head = args.expected_head
    actual_head = git_info["actual_head"]
    # Normalize to lowercase for case-insensitive comparison
    head_matches_expected = (
        bool(expected_head)
        and bool(actual_head)
        and actual_head.lower() == expected_head.lower()
    )

    collection_mode = schema.COLLECTION_MODE_FIXTURE if ctx.fixture_mode else schema.COLLECTION_MODE_REAL
    session_ended_ns = schema.monotonic_now_ns()

    def envelope() -> dict:
        return schema.base_envelope(
            session_id,
            session_started_monotonic_ns=session_started_ns,
            session_ended_monotonic_ns=session_ended_ns,
        )

    session_meta = {
        **envelope(),
        "actual_repo_root": str(REPO_ROOT),
        "actual_branch": git_info["actual_branch"],
        "expected_branch": schema.EXPECTED_BRANCH,
        "actual_head": actual_head,
        "expected_head": expected_head,
        "head_matches_expected": head_matches_expected,
        "tracked_worktree_clean": git_info["tracked_worktree_clean"],
        "tracked_changes": git_info["tracked_changes"],
        "untracked_paths": git_info["untracked_paths"],
        "untracked_symlinks": git_info["untracked_symlinks"],
        "untracked_allowlist_only": git_info["untracked_allowlist_only"],
        "git_remote_metadata": git_info["git_remote_metadata"],
        "ros_distro": env_info.get("ros_distro"),
        "rmw_implementation": env_info.get("rmw_implementation"),
        "cyclonedds_uri": env_info.get("cyclonedds_uri"),
        "hostname": env_info.get("hostname"),
        "uid": env_info.get("uid"),
        "username": env_info.get("username"),
        "collector_dry_run": False,
        "fixture_mode": ctx.fixture_mode,
        # v2: explicit collection mode fields
        "collection_mode": collection_mode,
        "field_collection_executed": ctx.field_collection_executed,
        "operator_present": safety["operator_present"],
        "hardstop_present": safety["hardstop_present"],
        # Hardcoded by construction, never derived from any command output
        # or fixture-supplied override: this tool never performs any of
        # these actions in any mode.
        "movement_command_sent": False,
        "goal_sent": False,
        "cmd_vel_published": False,
        "damp_invoked": False,
        "control_service_called": False,
        "lifecycle_changed": False,
        "parameter_changed": False,
        "physical_control_execution_performed": False,
    }

    ros_graph = {**envelope(), **graph}
    tf_and_localization = {**envelope(), **tf_loc}
    sensors_doc = {**envelope(), "sensors": sensors}
    cmd_vel_chain = {**envelope(), **cmd_vel}
    safety_checklist = {**envelope(), **safety}
    command_log_doc = {**envelope(), "commands": ctx.command_log}

    return {
        schema.SESSION_META: session_meta,
        schema.ROS_GRAPH: ros_graph,
        schema.TF_AND_LOCALIZATION: tf_and_localization,
        schema.SENSORS: sensors_doc,
        schema.CMD_VEL_CHAIN: cmd_vel_chain,
        schema.SAFETY_HUMAN_CHECKLIST: safety_checklist,
        schema.COMMAND_LOG: command_log_doc,
    }


def _file_metadata_entry(path: Path, filename: str) -> dict:
    """Builds a manifest entry for a bundle file including filesystem
    metadata fields required by v2."""
    file_stat = path.stat()
    lst = path.lstat()
    entry = {
        "filename": filename,
        "sha256": schema.sha256_file(path),
        "size_bytes": file_stat.st_size,
        "file_type": "regular",
        "nlink": lst.st_nlink,
    }
    if hasattr(lst, "st_mode"):
        entry["mode"] = oct(stat.S_IMODE(lst.st_mode))
    if hasattr(lst, "st_uid"):
        entry["uid"] = lst.st_uid
    return entry


def write_bundle(output_dir: Path, bundle: "dict[str, dict]") -> dict:
    """Writes all bundle files and the manifest+sidecar.
    For production: output_dir must NOT exist (use create_new_output_dir).
    For tests/fixture that pre-create a dir: callers may use ensure_safe_output_dir.
    This function accepts any pre-validated directory.
    """
    import stat as _stat
    manifest_files = []
    for filename, data in bundle.items():
        path = output_dir / filename
        schema.atomic_write_json(path, data)
        entry = _file_metadata_entry(path, filename)
        manifest_files.append(entry)
    session_id = bundle[schema.SESSION_META]["session_id"]
    manifest = {
        **schema.base_envelope(
            session_id,
            session_started_monotonic_ns=bundle[schema.SESSION_META]["session_started_monotonic_ns"],
            session_ended_monotonic_ns=bundle[schema.SESSION_META]["session_ended_monotonic_ns"],
        ),
        "files": manifest_files,
    }
    manifest_path = output_dir / schema.HASH_MANIFEST
    schema.atomic_write_json(manifest_path, manifest)
    # Sidecar: atomic write of the manifest hash
    manifest_hash = schema.sha256_file(manifest_path)
    sidecar_payload = (manifest_hash + "\n").encode("utf-8")
    schema.atomic_write_bytes(output_dir / schema.HASH_MANIFEST_SIDECAR, sidecar_payload)
    return manifest


# ---------------------------------------------------------------------------
# Dry-run description
# ---------------------------------------------------------------------------


def describe_dry_run(args: argparse.Namespace) -> dict:
    return {
        "status": "NOT_EXECUTED",
        "authorization": "NOT_AUTHORIZED",
        "notice": "EXPECTED_HEAD_REQUIRED_FOR_FIELD_EXECUTION",
        "output_dir": str(args.output_dir),
        "files_to_be_generated": list(schema.ALL_BUNDLE_FILES) + [schema.HASH_MANIFEST_SIDECAR],
        "command_labels": [
            "git_branch", "git_head", "git_status", "git_remote_origin",
            "ros2_node_list", "ros2_topic_list", "ros2_service_list", "ros2_action_list",
            "tf_echo_once", "tf_static_echo_once", "odom_echo_once", "odom_hz",
            *[f"topic_info_{t.strip('/').replace('/', '_')}" for t in schema.SENSOR_TOPICS],
            *[f"topic_hz_{t.strip('/').replace('/', '_')}" for t in schema.SENSOR_TOPICS if t != "/utlidar/cloud"],
            *[f"cmd_vel_info_{t.strip('/').replace('/', '_')}" for t in schema.CMD_VEL_TOPICS],
        ],
        "guards": [
            "dry_run_default",
            "execute_read_only_requires_env_and_all_cli_gates",
            "fixture_mode_requires_env",
            "fixture_and_execute_read_only_mutually_exclusive",
            "argv_only_no_shell_no_eval",
            "topic_hz_skipped_if_topic_not_discovered",
            "movement_invariants_hardcoded_false",
            "output_dir_must_not_exist",
            "sidecar_written_atomically",
            "expected_head_required_for_real_mode",
            "all_human_inputs_explicit_not_inferred",
        ],
        "expected_branch": schema.EXPECTED_BRANCH,
        "expected_ros_distro": schema.EXPECTED_ROS_DISTRO,
        "expected_rmw_implementation": schema.EXPECTED_RMW_IMPLEMENTATION,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: "list[str] | None" = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        mode = resolve_mode(args)
    except CollectorAuthorizationError as exc:
        print(json.dumps({"ok": False, "status": exc.code}), file=sys.stderr)
        return 3

    if mode == "dry_run":
        print(json.dumps(describe_dry_run(args), indent=2, sort_keys=True))
        return 0

    session_id = schema.new_session_id()
    if mode == "real":
        ctx: _BaseContext = _RealContext()
        try:
            schema.create_new_output_dir(args.output_dir)
        except schema.UnsafePathError as exc:
            print(json.dumps({"ok": False, "status": f"UNSAFE_OUTPUT_DIR:{exc}"}), file=sys.stderr)
            return 3
    else:
        fixture_path = args.fixture_dir / "fixture.json"
        try:
            fixture_data = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "status": f"FIXTURE_LOAD_FAILED:{exc}"}), file=sys.stderr)
            return 3
        ctx = _FixtureContext(fixture_data)
        try:
            schema.create_new_output_dir(args.output_dir)
        except schema.UnsafePathError as exc:
            print(json.dumps({"ok": False, "status": f"UNSAFE_OUTPUT_DIR:{exc}"}), file=sys.stderr)
            return 3

    bundle = build_bundle(ctx, args, session_id)
    try:
        manifest = write_bundle(args.output_dir, bundle)
    except (schema.UnsafePathError, OSError) as exc:
        print(json.dumps({"ok": False, "status": f"BUNDLE_WRITE_FAILED:{exc}"}), file=sys.stderr)
        return 3

    print(json.dumps({
        "ok": True,
        "status": "FIXTURE_BUNDLE_WRITTEN" if mode == "fixture" else "REAL_BUNDLE_WRITTEN",
        "output_dir": str(args.output_dir),
        "session_id": session_id,
        "files": [f["filename"] for f in manifest["files"]],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
