#!/usr/bin/env python3
"""Fase 2H.2.4 -- shared schema, constants and safe I/O helpers for the P0
PHYSICAL READ-ONLY evidence pipeline.

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
import secrets
import stat
import tempfile
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 1
COLLECTOR_VERSION = "2H.2.4"

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

# --- cmd_vel chain (p0_cmd_vel_chain.json) ------------------------------
CMD_VEL_TOPICS = ("/cmd_vel", "/cmd_vel_raw", "/cmd_vel_safe")

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

# --- git untracked-file policy ------------------------------------------
# The only untracked paths a P0 session may carry without forcing NO_GO:
# the offline-navigation mission logs this same phase's own tooling
# produces. Shared by collector (records untracked_paths) and validator
# (independently re-derives untracked_allowlist_only -- never trusts the
# collector's own classification of itself).
UNTRACKED_ALLOWLIST_PREFIXES = ("codigo ottoguide/logs/",)


def untracked_allowlist_only(untracked_paths: "list[str]") -> bool:
    return all(
        any(path.startswith(prefix) for prefix in UNTRACKED_ALLOWLIST_PREFIXES)
        for path in untracked_paths
    )

# --- safe local I/O ------------------------------------------------------
SAFE_DIR_MODE = 0o700
SAFE_FILE_MODE = 0o600

# Command-log output size discipline: never persist unbounded stdout/stderr.
COMMAND_OUTPUT_TRUNCATE_CHARS = 4000


class UnsafePathError(Exception):
    """Raised when a path that must be a real, owned, non-symlinked
    directory or regular file fails that check."""


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_session_id() -> str:
    return uuid.uuid4().hex


def base_envelope(session_id: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "collected_at_utc": utc_now_iso(),
        "collector_version": COLLECTOR_VERSION,
    }


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


def ensure_safe_output_dir(path: Path) -> None:
    """Creates `path` (and parents) if absent, mode 0700, and verifies the
    final component is a real directory owned by the current user, never a
    symlink. Fails closed (raises UnsafePathError) rather than silently
    following/adopting an attacker-influenced path.
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


def atomic_write_json(path: Path, data: dict) -> None:
    """Writes `data` as JSON to `path` via a unique temp file in the same
    directory, flush + fsync, then os.replace -- never a partial or
    half-written bundle file, and never following a pre-existing symlink
    at the destination name (os.replace() on POSIX replaces the directory
    entry itself, it does not follow a symlink at `path` into some other
    location).
    """
    directory = path.parent
    payload = json.dumps(data, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(directory))
    try:
        os.chmod(tmp_name, SAFE_FILE_MODE)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
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
            pass  # Best-effort directory-entry durability; never fatal.
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


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
