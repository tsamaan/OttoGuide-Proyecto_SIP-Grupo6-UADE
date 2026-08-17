#!/usr/bin/env python3
"""Fase 2H.2.6 -- shared schema, constants and safe I/O helpers for the P0
PHYSICAL READ-ONLY evidence pipeline (schema version 3).

Imported by both collect_p0_readonly_evidence.py (producer) and
validate_p0_readonly_evidence.py (consumer) so the two can never silently
drift apart on file names, required fields, or what "safe" atomic I/O
means. Standard library only -- no third-party dependency, no ROS import.

P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED. Nothing in this module
executes a command, opens a socket, or touches a robot; it only defines
data shapes and local filesystem helpers.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 3
COLLECTOR_VERSION = "2H.2.6"

EXPECTED_BRANCH = "robot"
EXPECTED_ROS_DISTRO = "foxy"
EXPECTED_RMW_IMPLEMENTATION = "rmw_cyclonedds_cpp"

# --- bundle file names -------------------------------------------------
SESSION_META = "p0_session_meta.json"
ROS_GRAPH = "p0_ros_graph.json"
TF_AND_LOCALIZATION = "p0_tf_and_localization.json"
SENSORS = "p0_sensors.json"
CMD_VEL_CHAIN = "p0_cmd_vel_chain.json"
SAFETY_HUMAN_CHECKLIST = "p0_safety_human_checklist.json"
COMMAND_LOG = "p0_command_log.json"
HASH_MANIFEST = "p0_hash_manifest.json"
HASH_MANIFEST_SIDECAR = "p0_hash_manifest.sha256"

# Every file the hash manifest itself must cover (never includes the
# manifest, which cannot meaningfully hash itself).
BUNDLE_DATA_FILES = (
    SESSION_META, ROS_GRAPH, TF_AND_LOCALIZATION, SENSORS,
    CMD_VEL_CHAIN, SAFETY_HUMAN_CHECKLIST, COMMAND_LOG,
)
ALL_BUNDLE_FILES = BUNDLE_DATA_FILES + (HASH_MANIFEST,)

# --- read-only invariants (p0_session_meta.json) -----------------------
# Every one of these must be the literal boolean False in a valid bundle,
# real or fixture -- the collector hardcodes them, never derives them from
# any command output or fixture-supplied data.
MUST_BE_FALSE_FIELDS = (
    "movement_command_sent",
    "goal_sent",
    "cmd_vel_published",
    "damp_invoked",
    "control_service_called",
    "lifecycle_changed",
    "parameter_changed",
    # v2: replaces ambiguous physical_execution_performed
    "physical_control_execution_performed",
)

# --- human safety checklist (p0_safety_human_checklist.json) -----------
# Fields that must be *defined* (present, boolean) for a bundle to be
# well-formed, regardless of their value.
SAFETY_REQUIRED_DEFINED_FIELDS = (
    "operator_present",
    "operator_identity_or_role",
    "hardstop_present",
    "hardstop_type",
    "hardstop_tested_before_session",
    "area_cleared",
    "robot_physically_supervised",
    "dual_control_prohibited_acknowledged",
    "movement_not_authorized_acknowledged",
    "notes",
)
# Subset that must be literally True for any GO_CANDIDATE decision.
SAFETY_REQUIRED_TRUE_FOR_GO = (
    "operator_present",
    "hardstop_present",
    "area_cleared",
    "robot_physically_supervised",
    "movement_not_authorized_acknowledged",
    "dual_control_prohibited_acknowledged",
)

# --- ROS graph (p0_ros_graph.json) --------------------------------------
GRAPH_LIST_FIELDS = ("nodes", "topics", "services", "actions", "critical_actions", "critical_topics")

# --- sensors (p0_sensors.json) ------------------------------------------
SENSOR_TOPICS = (
    "/scan",
    "/utlidar/cloud",
    "/livox/imu",
    "/camera/color/image_raw",
    "/camera/depth/image_rect_raw",
)

CRITICAL_TOPIC_TYPES = {
    "/scan": "sensor_msgs/msg/LaserScan",
    "/odom": "nav_msgs/msg/Odometry",
    "/tf": "tf2_msgs/msg/TFMessage",
    "/tf_static": "tf2_msgs/msg/TFMessage",
    "/map": "nav_msgs/msg/OccupancyGrid",
    "/map_metadata": "nav_msgs/msg/MapMetaData",
    "/cmd_vel": "geometry_msgs/msg/Twist",
    "/cmd_vel_raw": "geometry_msgs/msg/Twist",
    "/cmd_vel_safe": "geometry_msgs/msg/Twist",
}

# --- cmd_vel chain (p0_cmd_vel_chain.json) ------------------------------
CMD_VEL_TOPICS = ("/cmd_vel", "/cmd_vel_raw", "/cmd_vel_safe")

# The one node that must be the sole subscriber of /cmd_vel_safe in a valid
# physical topology. The collector uses this to set ownership_status; the
# validator uses it to gate GO_CANDIDATE.
EXPECTED_CMD_VEL_SAFE_CONSUMER = "/unitree_locomotion_bridge"

# --- tf / localization (p0_tf_and_localization.json) -------------------
REQUIRED_TF_EDGES = (
    "map->odom",
    "odom->base_link",
    "base_link->utlidar_lidar",
    "base_link->imu_link",
)
READINESS_NOT_READY = "NOT_READY"
READINESS_CANDIDATE_OBSERVED = "CANDIDATE_OBSERVED_PENDING_ANALYSIS"

# --- field decision / collection mode -----------------------------------
DECISION_GO_CANDIDATE = "GO_CANDIDATE"
DECISION_NO_GO = "NO_GO"
DECISION_FIXTURE_ONLY = "FIXTURE_ONLY"
COLLECTION_MODE_FIXTURE = "fixture"
COLLECTION_MODE_REAL = "real_read_only"

UNSUPPORTED_SCHEMA_VERSION = "UNSUPPORTED_SCHEMA_VERSION"


def _topic_label(topic: str) -> str:
    return topic.strip("/").replace("/", "_")


def expected_command_argv(label: str, repo_root: "str | None" = None) -> "list[str] | None":
    """Return the exact argv expected for a command label.

    ``repo_root`` is required for git labels because the collector records
    the concrete ``-C`` path. Non-git labels are path-independent.
    """
    git_commands = {
        "git_branch": ["git", "-C", repo_root, "branch", "--show-current"],
        "git_head": ["git", "-C", repo_root, "rev-parse", "HEAD"],
        "git_status": ["git", "-C", repo_root, "status", "--short", "--branch", "--untracked-files=all"],
        "git_remote_origin": ["git", "-C", repo_root, "remote", "get-url", "origin"],
    }
    if label in git_commands:
        if not repo_root:
            return None
        return git_commands[label]
    fixed = {
        "ros2_node_list": ["ros2", "node", "list"],
        "ros2_topic_list": ["ros2", "topic", "list", "-t"],
        "ros2_service_list": ["ros2", "service", "list", "-t"],
        "ros2_action_list": ["ros2", "action", "list", "-t"],
        "tf_echo_once": ["ros2", "topic", "echo", "--once", "/tf"],
        "tf_static_echo_once": ["ros2", "topic", "echo", "--once", "/tf_static"],
        "odom_echo_once": ["ros2", "topic", "echo", "--once", "/odom"],
        "odom_hz": ["ros2", "topic", "hz", "/odom"],
    }
    if label in fixed:
        return fixed[label]
    for topic in SENSOR_TOPICS:
        encoded = _topic_label(topic)
        if label == f"topic_info_{encoded}":
            return ["ros2", "topic", "info", "-v", topic]
        if label == f"topic_hz_{encoded}":
            return ["ros2", "topic", "hz", topic]
    for topic in CMD_VEL_TOPICS:
        if label == f"cmd_vel_info_{_topic_label(topic)}":
            return ["ros2", "topic", "info", "-v", topic]
    return None

# --- git untracked-file policy (v2: exact regex, not prefix) -----------
# The only untracked paths a P0 session may carry without forcing NO_GO.
# Must be normalized to forward-slash before matching.
UNTRACKED_EXACT_PATTERN = re.compile(
    r'^codigo ottoguide/logs/mission_[A-Za-z0-9_.-]+\.json$'
)

# Legacy prefix list (v1) retained only so v1-era bundles are detected and
# rejected, never trusted.
UNTRACKED_ALLOWLIST_PREFIXES_V1 = ("codigo ottoguide/logs/",)


def _normalize_untracked_path(path: str) -> str:
    """Normalize path separators to forward-slash and strip leading/trailing
    whitespace. Does NOT strip quotes (the caller must have done that)."""
    return path.replace("\\", "/").strip()


def _is_safe_untracked_path(path: str) -> bool:
    """Returns True only if the path is safe to normalise and match: not
    absolute, no '..' segments, not empty, not a symlink label."""
    if not path:
        return False
    normalized = _normalize_untracked_path(path)
    if normalized.startswith("/"):
        return False
    if ".." in normalized.split("/"):
        return False
    return True


def untracked_allowlist_only(untracked_paths: "list[str]") -> bool:
    """v2 policy: each path must match UNTRACKED_EXACT_PATTERN exactly.
    Paths that are unsafe (absolute, path-traversal, empty) are rejected
    before the regex is applied."""
    for path in untracked_paths:
        if not _is_safe_untracked_path(path):
            return False
        normalized = _normalize_untracked_path(path)
        if not UNTRACKED_EXACT_PATTERN.match(normalized):
            return False
    return True


# --- safe local I/O ------------------------------------------------------
SAFE_DIR_MODE = 0o700
SAFE_FILE_MODE = 0o600

# Command-log output size discipline: never persist unbounded stdout/stderr.
COMMAND_OUTPUT_TRUNCATE_CHARS = 4000


class UnsafePathError(Exception):
    """Raised when a path that must be a real, owned, non-symlinked
    directory or regular file fails that check."""


# --- clock trust (v3) --------------------------------------------------
# Year threshold below which the wall clock is considered invalid
# (covers epoch 0 / 1970 and similarly invalid timestamps).
CLOCK_TRUSTED_YEAR_MIN = 2020
CLOCK_TRUSTED = "TRUSTED"
CLOCK_UNTRUSTED = "CLOCK_UNTRUSTED"

def wall_clock_trust() -> "tuple[str, str]":
    """Returns (trust_status, wall_clock_value_iso).

    trust_status is CLOCK_TRUSTED or CLOCK_UNTRUSTED.
    CLOCK_UNTRUSTED does not invalidate structural evidence but prohibits
    using the wall-clock timestamp for freshness, ordering, or lease gates.
    No gate uses wall clock for authorization.
    """
    t = time.gmtime()
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", t)
    if t.tm_year < CLOCK_TRUSTED_YEAR_MIN:
        return CLOCK_UNTRUSTED, iso
    return CLOCK_TRUSTED, iso


def monotonic_now_ns() -> int:
    return time.monotonic_ns()


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_session_id() -> str:
    return uuid.uuid4().hex


def base_envelope(
    session_id: str,
    session_started_monotonic_ns: "int | None" = None,
    *,
    document_collected_monotonic_ns: "int | None" = None,
    session_ended_monotonic_ns: "int | None" = None,
    monotonic_started_ns: "int | None" = None,
) -> dict:
    trust, wall_value = wall_clock_trust()
    mono_now = monotonic_now_ns()
    if session_started_monotonic_ns is None:
        session_started_monotonic_ns = monotonic_started_ns if monotonic_started_ns is not None else mono_now
    if document_collected_monotonic_ns is None:
        document_collected_monotonic_ns = mono_now
    envelope: dict = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "collected_at_utc": wall_value,
        "collector_version": COLLECTOR_VERSION,
        "wall_clock_value": wall_value,
        "wall_clock_trusted": trust == CLOCK_TRUSTED,
        "wall_clock_source": "time.gmtime()",
        "session_started_monotonic_ns": session_started_monotonic_ns,
        "document_collected_monotonic_ns": document_collected_monotonic_ns,
    }
    # Legacy aliases retained for older in-repo test helpers while schema v3
    # consumers use the explicit session_* names.
    envelope["monotonic_started_ns"] = session_started_monotonic_ns
    envelope["monotonic_ended_ns"] = document_collected_monotonic_ns
    if session_ended_monotonic_ns is not None:
        envelope["session_ended_monotonic_ns"] = session_ended_monotonic_ns
        envelope["session_duration_ms"] = (
            session_ended_monotonic_ns - session_started_monotonic_ns
        ) // 1_000_000
    return envelope


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def truncate_output(text: "str | None") -> "tuple[str, bool]":
    """Returns (possibly-truncated text, was_truncated). Never persists
    unbounded command output into a versioned/auditable bundle."""
    if text is None:
        return "", False
    if len(text) <= COMMAND_OUTPUT_TRUNCATE_CHARS:
        return text, False
    return text[:COMMAND_OUTPUT_TRUNCATE_CHARS], True


def create_new_output_dir(path: Path) -> None:
    """Creates `path` with mode 0700. Fails closed (raises UnsafePathError)
    if the path already exists, is a symlink, or is the wrong owner.
    This is the v2 policy: output directories must be brand-new.
    """
    if path.exists() or path.is_symlink():
        raise UnsafePathError(f"OUTPUT_DIR_ALREADY_EXISTS:{path}")
    path.mkdir(mode=SAFE_DIR_MODE, parents=False, exist_ok=False)
    os.chmod(path, SAFE_DIR_MODE)
    final_stat = path.stat()
    if hasattr(os, "getuid") and final_stat.st_uid != os.getuid():
        raise UnsafePathError(f"OUTPUT_DIR_WRONG_OWNER:{path}")


def ensure_safe_output_dir(path: Path) -> None:
    """Legacy v1 helper retained for callers that explicitly re-use dirs
    (e.g. test helpers that write multiple files to a pre-created tmpdir).
    New production bundles must use create_new_output_dir() instead.
    """
    if path.exists() or path.is_symlink():
        lst = os.lstat(path)
        if stat.S_ISLNK(lst.st_mode):
            raise UnsafePathError(f"OUTPUT_DIR_IS_SYMLINK:{path}")
        if not path.is_dir():
            raise UnsafePathError(f"OUTPUT_DIR_NOT_A_DIRECTORY:{path}")
    else:
        path.mkdir(mode=SAFE_DIR_MODE, parents=True, exist_ok=False)
    os.chmod(path, SAFE_DIR_MODE)
    final_stat = path.stat()
    if hasattr(os, "getuid") and final_stat.st_uid != os.getuid():
        raise UnsafePathError(f"OUTPUT_DIR_WRONG_OWNER:{path}")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Writes `data` (raw bytes) to `path` via a unique temp file in the
    same directory, flush + fsync, then os.replace. Used for the sidecar
    and any other non-JSON payload. Never follows a pre-existing symlink at
    the destination name."""
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(directory))
    try:
        os.chmod(tmp_name, SAFE_FILE_MODE)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
        try:
            dir_fd = os.open(str(directory), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: dict) -> None:
    """Writes `data` as JSON to `path` via a unique temp file in the same
    directory, flush + fsync, then os.replace -- never a partial or
    half-written bundle file, and never following a pre-existing symlink
    at the destination name."""
    payload = json.dumps(data, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    atomic_write_bytes(path, payload)


def load_json_file(path: Path) -> "tuple[dict | list | None, str | None]":
    """Returns (data, error_code). Never raises on a missing/malformed
    file -- that is itself a validation finding, not an exception."""
    if not path.is_file():
        return None, f"MISSING_FILE:{path.name}"
    if path.is_symlink():
        return None, f"FILE_IS_SYMLINK:{path.name}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"INVALID_JSON:{path.name}:{exc}"


def random_session_token() -> str:
    return secrets.token_hex(16)


def redact_git_url(url: str) -> str:
    """Redact credentials from a Git remote URL before persisting.
    Handles https://user:token@host/path patterns."""
    return re.sub(r"(https?://)([^@]*@)", r"\1<redacted>@", url)
