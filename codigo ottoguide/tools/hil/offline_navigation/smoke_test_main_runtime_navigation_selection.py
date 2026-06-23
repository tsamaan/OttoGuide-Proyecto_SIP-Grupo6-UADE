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

Fase 2H.2.2 process/lease model
-------------------------------
Every process this script spawns (the child interpreter per scenario, and
the sandbox wrapper spawned by that child) is created with
``start_new_session=True`` so it becomes the leader of its own session and
process group, distinct from its spawner's. Ownership of a process group is
never assumed from a PID alone: it is established once via the kernel
identity captured immediately after spawn (``ProcessIdentity``, sourced from
``/proc/<pid>/stat``: pid, ppid, pgid, sid, start_ticks, uid) and re-verified
against the live kernel before every signal, so a PID/PGID that has been
reused by an unrelated process can never be signalled as if it were still
the original target.

A ``CleanupLease`` (a private 0700 directory containing a 0600 JSON file,
created with O_CREAT|O_EXCL|O_NOFOLLOW and updated only via write-temp +
fsync + os.replace) carries the parent/child/sandbox identities across the
parent/child boundary so the parent can re-validate the sandbox's identity
during a timeout before it ever sends a signal to a PGID it did not itself
observe at spawn time. If the lease cannot be validated at any stage, the
sandbox is never signalled by the parent; only the immediate child (whose
identity the parent captured directly via Popen) is targeted, and the
scenario is marked failed.
"""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
CODE_ROOT = TOOLS_DIR.parents[2]
RUNTIME_WRAPPER = CODE_ROOT / "scripts" / "run_offline_navigation_runtime.sh"
THIS_FILE = Path(__file__).resolve()

sys.path.insert(0, str(CODE_ROOT))


def _get_tested_commit_sha() -> "str | None":
    """Return the current HEAD SHA via git, or None on failure."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5.0,
            cwd=str(CODE_ROOT.parent),
        )
        sha = r.stdout.strip()
        return sha if len(sha) == 40 else None
    except Exception:
        return None


def _bounded_log_tail_hash(log_path: "Path | None", tail_lines: int = 200) -> "str | None":
    """Return SHA-256 hex of the last `tail_lines` lines of log_path, or None."""
    if log_path is None or not log_path.is_file():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-tail_lines:])
        return hashlib.sha256(tail.encode("utf-8")).hexdigest()
    except Exception:
        return None

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

LEASE_SCHEMA_VERSION = 2
LEASE_DIR_MODE = 0o700
LEASE_FILE_MODE = 0o600

# Identifiers a signal may never target, regardless of what a lease or
# control file claims. PID/PGID/SID 0 and 1 are kernel/init-reserved; the
# parent's own ids must never be treated as a child/sandbox target.
PROTECTED_IDS = frozenset({0, 1})

# Cleanup escalation timeouts (seconds). Overridable for tests via
# CleanupTimeouts; production callers use the defaults.
DEFAULT_SIGINT_WAIT_S = 15.0
DEFAULT_SIGTERM_WAIT_S = 10.0
DEFAULT_SIGKILL_WAIT_S = 5.0
DEFAULT_CHILD_SIGINT_WAIT_S = 5.0
DEFAULT_CHILD_SIGTERM_WAIT_S = 5.0
DEFAULT_CHILD_SIGKILL_WAIT_S = 5.0

# Fase 2H.2.4 -- hidden, offline-only fault injection so the *real* parent
# CLI timeout path (main() -> _parent_main() -> communicate(timeout=...) ->
# TimeoutExpired -> _parent_timeout_cleanup) can be exercised end-to-end by
# a driver, without ever touching ROS or ros2 launch. Without this exact
# env var present, the hidden --fault-inject-hang-sandbox flag is refused;
# it never appears in --help (argparse.SUPPRESS) and never changes any
# behavior unless explicitly requested via the flag.
FAULT_INJECTION_ENV_2H24 = "OTTOGUIDE_2H24_FAULT_INJECTION"
# Authorized-only override for _parent_main's communicate() timeout margin
# (normally a fixed 150.0s on top of --timeout), so a fault-injection
# driver does not have to wait out the full production margin to observe
# a TimeoutExpired. Never consulted unless fault injection is authorized.
FAULT_TIMEOUT_MARGIN_ENV_2H24 = "OTTOGUIDE_2H24_FAULT_TIMEOUT_MARGIN_S"
DEFAULT_COMMUNICATE_TIMEOUT_MARGIN_S = 150.0
# How long the fault-injected stand-in sandbox sleeps. Default signal
# disposition (no custom handler): it dies promptly on the first SIGINT
# the real cleanup path sends it, exactly like the inert sandboxes used by
# the Fase 2H.2.3 evidence driver -- this proves the parent acts, not that
# the stand-in resists.
FAULT_SANDBOX_SLEEP_S = 99999


def _fault_injection_2h24_authorized() -> bool:
    return os.environ.get(FAULT_INJECTION_ENV_2H24) == "1"


def _communicate_timeout_margin_s() -> float:
    if _fault_injection_2h24_authorized():
        override = os.environ.get(FAULT_TIMEOUT_MARGIN_ENV_2H24)
        if override is not None:
            try:
                return float(override)
            except ValueError:
                pass
    return DEFAULT_COMMUNICATE_TIMEOUT_MARGIN_S

# Lease vigencia: must comfortably exceed the longest single scenario
# (sandbox startup + full nav exercise + cleanup escalation) so a slow but
# legitimate run is never rejected as expired.
DEFAULT_LEASE_MAX_AGE_S = 600.0


def _lease_monotonic_ns() -> int:
    """Centralised monotonic clock for lease timestamps. Tests can monkeypatch
    this module-level function to inject deterministic sequences."""
    return time.monotonic_ns()


# ---------------------------------------------------------------------------
# Kernel process identity (Fase 2H.2.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    ppid: int
    pgid: int
    sid: int
    start_ticks: int
    uid: int

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ProcessIdentity | None":
        try:
            return ProcessIdentity(
                pid=int(data["pid"]),
                ppid=int(data["ppid"]),
                pgid=int(data["pgid"]),
                sid=int(data["sid"]),
                start_ticks=int(data["start_ticks"]),
                uid=int(data["uid"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _is_strict_positive_int(value) -> bool:
    """True only for a real int (never bool) strictly greater than 1."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 1


def is_protected_id(value) -> bool:
    """An identifier is unsafe to ever signal if it is not a strict
    positive int (>1), or if it equals a protected/reserved id (0, 1)."""
    if not isinstance(value, int) or isinstance(value, bool):
        return True
    return value in PROTECTED_IDS or value <= 1


def _parse_proc_stat(text: str) -> "tuple[str, str, list[str]] | None":
    """Splits /proc/<pid>/stat into (pid_field, comm, remaining_fields).

    comm (field 2) is parenthesized and may itself contain spaces or
    parentheses (e.g. a process named "a)b(c"); this finds the *last* ')'
    rather than the first, which is the only way to parse it correctly.
    """
    first_paren = text.find("(")
    last_paren = text.rfind(")")
    if first_paren == -1 or last_paren == -1 or last_paren <= first_paren:
        return None
    pid_field = text[:first_paren].strip()
    comm = text[first_paren + 1:last_paren]
    rest = text[last_paren + 1:].strip().split()
    return pid_field, comm, rest


def read_process_identity(pid: int) -> "ProcessIdentity | None":
    """Reads kernel-authoritative identity for `pid` from /proc/<pid>/stat
    and /proc/<pid> ownership. Returns None if the process does not exist,
    /proc is unavailable (e.g. native Windows), or the stat line cannot be
    parsed -- this is always a normal, expected outcome for an already-gone
    process, never silently coerced into a fabricated identity.
    """
    if is_protected_id(pid):
        return None
    proc_dir = Path(f"/proc/{pid}")
    stat_path = proc_dir / "stat"
    try:
        text = stat_path.read_text()
        owner_uid = proc_dir.stat().st_uid
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None

    parsed = _parse_proc_stat(text)
    if parsed is None:
        return None
    pid_field, _comm, rest = parsed
    # rest[0] = state (field 3, 1-indexed), rest[1] = ppid (field 4),
    # rest[2] = pgrp (field 5), rest[3] = session (field 6) -- rest[i]
    # always corresponds to overall field (i+3). starttime is field 22, so
    # it is rest[22-3] = rest[19].
    try:
        pid_value = int(pid_field)
        ppid = int(rest[1])
        pgid = int(rest[2])
        sid = int(rest[3])
        start_ticks = int(rest[19])
    except (IndexError, ValueError):
        return None
    if pid_value != pid:
        return None
    return ProcessIdentity(
        pid=pid_value, ppid=ppid, pgid=pgid, sid=sid, start_ticks=start_ticks, uid=owner_uid
    )


def identity_still_valid(expected: ProcessIdentity) -> bool:
    """Re-validates a previously captured identity against the live kernel:
    same pid, same start_ticks (defeats PID reuse), same owner."""
    current = read_process_identity(expected.pid)
    if current is None:
        return False
    return (
        current.pid == expected.pid
        and current.start_ticks == expected.start_ticks
        and current.uid == expected.uid
    )


def list_pgid_members(pgid: int) -> "list[ProcessIdentity]":
    """Enumerates every process currently claiming membership in `pgid` by
    scanning /proc/<pid>/stat directly (no `ps`, no name matching)."""
    if is_protected_id(pgid):
        return []
    members: list[ProcessIdentity] = []
    try:
        candidates = [int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()]
    except OSError:
        return []
    for pid in candidates:
        identity = read_process_identity(pid)
        if identity is not None and identity.pgid == pgid:
            members.append(identity)
    return members


def _terminate_and_reap_unsafe_spawn(proc: "subprocess.Popen") -> None:
    """Best-effort termination + mandatory reap of a Popen this function is
    about to discard because its identity could not be established or
    validated as safely isolated. Always targets only this exact PID
    (never a group/PGID, which is precisely what could not be trusted
    yet), and always calls wait() so the process can never be leaked as a
    Popen reference with no terminator and no reap.
    """
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass
    try:
        proc.wait(timeout=5.0)
    except Exception:
        try:
            proc.wait(timeout=5.0)
        except Exception:
            pass


def spawn_isolated(cmd: list, **popen_kwargs) -> "tuple[subprocess.Popen, ProcessIdentity]":
    """Spawns `cmd` as the leader of a brand-new session and process group
    (start_new_session=True, never preexec_fn=os.setsid), then immediately
    captures and validates its kernel identity. Raises RuntimeError if the
    spawned process did not actually obtain its own session/group -- this
    is a fail-closed precondition for every later signal/lease step, never
    silently downgraded to "best effort". Before raising, the just-spawned
    process is always terminated and reaped here -- the caller only ever
    sees the exception, never the Popen, so it would otherwise have no way
    to clean up a process it cannot trust the identity of.
    """
    proc = subprocess.Popen(cmd, start_new_session=True, **popen_kwargs)
    identity = read_process_identity(proc.pid)
    if identity is None:
        # Process may have already exited; give it one more chance to be
        # observed before giving up (covers a benign race on very fast
        # exits without papering over a genuine isolation failure).
        time.sleep(0.05)
        identity = read_process_identity(proc.pid)
    if identity is None:
        _terminate_and_reap_unsafe_spawn(proc)
        raise RuntimeError(f"SPAWN_IDENTITY_UNAVAILABLE:pid={proc.pid}")
    if identity.pid != identity.pgid or identity.pid != identity.sid:
        _terminate_and_reap_unsafe_spawn(proc)
        raise RuntimeError(
            f"SPAWN_NOT_OWN_SESSION:pid={identity.pid},pgid={identity.pgid},sid={identity.sid}"
        )
    if is_protected_id(identity.pgid) or is_protected_id(identity.sid):
        _terminate_and_reap_unsafe_spawn(proc)
        raise RuntimeError(f"SPAWN_PROTECTED_GROUP:pgid={identity.pgid},sid={identity.sid}")
    return proc, identity


# ---------------------------------------------------------------------------
# Cleanup lease (Fase 2H.2.2)
# ---------------------------------------------------------------------------


class LeaseError(Exception):
    pass


def _fsync_replace(path: Path, payload: bytes) -> None:
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", dir=str(directory))
    try:
        os.chmod(tmp_name, LEASE_FILE_MODE)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _open_nofollow_flags() -> int:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    return flags | nofollow


class CleanupLease:
    """A private-directory, validated lease that proves identity and
    vigency across the parent/child process boundary -- never a bare
    JSON control file. See module docstring for the threat model.
    """

    FILE_NAME = "cleanup_lease.json"

    def __init__(self, lease_dir: Path):
        self.lease_dir = lease_dir
        self.lease_path = lease_dir / self.FILE_NAME

    # -- creation (parent, before spawning the child) --------------------

    @classmethod
    def create(
        cls,
        base_tmp_dir: Path,
        run_id: str,
        scenario: str,
        domain_id: str,
        parent_identity: ProcessIdentity,
        max_age_s: float = DEFAULT_LEASE_MAX_AGE_S,
    ) -> "tuple[CleanupLease, str]":
        """Returns (lease, lease_token). The token is also written inside
        the lease file (so the child, which only ever sees the lease
        directory, can read it back from there), but the *expected* value
        a caller validates against must always come from this return value
        -- passed to the child out-of-band via an explicit CLI argument,
        never re-derived from the lease file's own contents, which is what
        validate_lease_immutable_fields()'s `expected_token` parameter is
        for. Comparing the file's self-reported token against itself would
        validate nothing: any attacker-controlled lease file could simply
        carry its own forged token alongside forged identities.
        """
        lease_dir = base_tmp_dir / f"ottoguide_main_runtime_2h22_{run_id}"
        lease_dir.mkdir(mode=LEASE_DIR_MODE, parents=False, exist_ok=False)
        os.chmod(lease_dir, LEASE_DIR_MODE)
        dir_stat = lease_dir.stat()
        if stat.S_ISLNK(os.lstat(lease_dir).st_mode):
            raise LeaseError("LEASE_DIR_IS_SYMLINK")
        if dir_stat.st_uid != os.getuid():
            raise LeaseError("LEASE_DIR_WRONG_OWNER")

        lease = cls(lease_dir)
        now_wallclock_ns = time.time_ns()
        mono_ns = _lease_monotonic_ns()
        token = secrets.token_hex(32)
        payload = {
            "schema_version": LEASE_SCHEMA_VERSION,
            "run_id": run_id,
            "lease_token": token,
            "scenario": scenario,
            "domain_id": domain_id,
            "max_age_s": max_age_s,
            # Wall-clock fields are human-readable audit only; never used for
            # ordering, expiry or regression detection.
            "created_at_ns": now_wallclock_ns,
            "updated_at_ns": now_wallclock_ns,
            # Monotonic fields are the sole authority for ordering, vigency,
            # age and expiry. They survive NTP jumps and wall-clock rollbacks.
            "created_monotonic_ns": mono_ns,
            "updated_monotonic_ns": mono_ns,
            "parent": parent_identity.to_dict(),
            "child": _EMPTY_IDENTITY_DICT,
            "sandbox": _EMPTY_IDENTITY_DICT,
        }
        flags = _open_nofollow_flags()
        fd = os.open(str(lease.lease_path), flags, LEASE_FILE_MODE)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(json.dumps(payload).encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            raise
        lease._validate_file_metadata()
        return lease, token

    # -- reopen (child / parent re-attaching to an existing lease) -------

    @classmethod
    def open_existing(cls, lease_dir: Path) -> "CleanupLease":
        lease = cls(lease_dir)
        lease._validate_file_metadata()
        return lease

    def _validate_file_metadata(self) -> None:
        try:
            lstat_result = os.lstat(self.lease_path)
        except OSError as exc:
            raise LeaseError(f"LEASE_FILE_STAT_FAILED:{exc}") from exc
        if stat.S_ISLNK(lstat_result.st_mode):
            raise LeaseError("LEASE_FILE_IS_SYMLINK")
        if not stat.S_ISREG(lstat_result.st_mode):
            raise LeaseError("LEASE_FILE_NOT_REGULAR")
        if lstat_result.st_nlink != 1:
            raise LeaseError("LEASE_FILE_UNEXPECTED_NLINK")
        if lstat_result.st_uid != os.getuid():
            raise LeaseError("LEASE_FILE_WRONG_OWNER")
        if stat.S_IMODE(lstat_result.st_mode) & 0o077:
            raise LeaseError("LEASE_FILE_PERMISSIONS_TOO_OPEN")

    def read(self) -> dict:
        self._validate_file_metadata()
        try:
            text = self.lease_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LeaseError(f"LEASE_FILE_READ_FAILED:{exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LeaseError(f"LEASE_FILE_INVALID_JSON:{exc}") from exc
        if not isinstance(data, dict):
            raise LeaseError("LEASE_FILE_NOT_OBJECT")
        return data

    def _write(self, data: dict) -> None:
        self._validate_file_metadata()
        payload = json.dumps(data).encode("utf-8")
        _fsync_replace(self.lease_path, payload)
        self._validate_file_metadata()

    def update_child_identity(self, child_identity: ProcessIdentity) -> dict:
        data = self.read()
        new_mono_ns = _lease_monotonic_ns()
        prev_mono_ns = data.get("updated_monotonic_ns")
        created_mono_ns = data.get("created_monotonic_ns")
        if isinstance(prev_mono_ns, int) and isinstance(created_mono_ns, int):
            if new_mono_ns < created_mono_ns or new_mono_ns < prev_mono_ns:
                raise LeaseError("LEASE_MONOTONIC_REGRESSION")
        data["child"] = child_identity.to_dict()
        data["updated_at_ns"] = time.time_ns()
        data["updated_monotonic_ns"] = new_mono_ns
        self._write(data)
        return data

    def update_sandbox_identity(self, sandbox_identity: ProcessIdentity) -> dict:
        data = self.read()
        new_mono_ns = _lease_monotonic_ns()
        prev_mono_ns = data.get("updated_monotonic_ns")
        created_mono_ns = data.get("created_monotonic_ns")
        if isinstance(prev_mono_ns, int) and isinstance(created_mono_ns, int):
            if new_mono_ns < created_mono_ns or new_mono_ns < prev_mono_ns:
                raise LeaseError("LEASE_MONOTONIC_REGRESSION")
        data["sandbox"] = sandbox_identity.to_dict()
        data["updated_at_ns"] = time.time_ns()
        data["updated_monotonic_ns"] = new_mono_ns
        self._write(data)
        return data

    def destroy(self) -> None:
        try:
            self.lease_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            self.lease_dir.rmdir()
        except OSError:
            pass


_EMPTY_IDENTITY_DICT = {
    "pid": None, "ppid": None, "pgid": None, "sid": None, "start_ticks": None, "uid": None,
}


def validate_lease_immutable_fields(
    data: dict,
    expected_run_id: str,
    expected_scenario: str,
    expected_domain_id: str,
    expected_parent: "ProcessIdentity | None" = None,
    max_age_s: float = DEFAULT_LEASE_MAX_AGE_S,
    expected_token: "str | None" = None,
) -> "list[str]":
    """Validates the fields that must never change after creation, plus
    vigency. Returns a list of error codes (empty list = valid). Never
    raises on a malformed lease -- malformed input is itself a validation
    failure to report, not an exception to propagate.

    `expected_token`, when given, must be the exact token value the caller
    obtained out-of-band from CleanupLease.create()'s return value (e.g.
    passed to a child via an explicit CLI argument) -- never read back from
    the lease file itself, which would make the check circular. Comparison
    uses secrets.compare_digest for a constant-time match.
    """
    errors: list[str] = []

    if data.get("schema_version") != LEASE_SCHEMA_VERSION:
        errors.append("LEASE_SCHEMA_MISMATCH")
        return errors  # Nothing else can be trusted if the schema itself is wrong.

    token = data.get("lease_token")
    if not isinstance(token, str) or len(token) < 32:
        errors.append("LEASE_TOKEN_INVALID")
    elif expected_token is not None:
        if not isinstance(expected_token, str) or not secrets.compare_digest(token, expected_token):
            errors.append("LEASE_TOKEN_MISMATCH")

    if data.get("run_id") != expected_run_id:
        errors.append("LEASE_RUN_ID_MISMATCH")
    if data.get("scenario") != expected_scenario:
        errors.append("LEASE_SCENARIO_MISMATCH")
    if str(data.get("domain_id")) != str(expected_domain_id):
        errors.append("LEASE_DOMAIN_MISMATCH")

    parent_data = data.get("parent")
    if not isinstance(parent_data, dict):
        errors.append("LEASE_PARENT_IDENTITY_MISSING")
    else:
        parent_identity = ProcessIdentity.from_dict(parent_data)
        if parent_identity is None:
            errors.append("LEASE_PARENT_IDENTITY_MALFORMED")
        elif is_protected_id(parent_identity.pid) or is_protected_id(parent_identity.pgid):
            errors.append("LEASE_PARENT_IDENTITY_PROTECTED")
        elif expected_parent is not None and (
            parent_identity.pid != expected_parent.pid
            or parent_identity.ppid != expected_parent.ppid
            or parent_identity.pgid != expected_parent.pgid
            or parent_identity.sid != expected_parent.sid
            or parent_identity.start_ticks != expected_parent.start_ticks
            or parent_identity.uid != expected_parent.uid
        ):
            errors.append("LEASE_PARENT_IDENTITY_MISMATCH")

    # --- Monotonic timestamps: sole authority for ordering, vigency, age ---
    # Wall-clock fields (created_at_ns / updated_at_ns) are retained for
    # human audit only; they are never consulted for authorization decisions.
    created_mono = data.get("created_monotonic_ns")
    updated_mono = data.get("updated_monotonic_ns")
    if not isinstance(created_mono, int) or not isinstance(updated_mono, int):
        errors.append("LEASE_MONOTONIC_TIMESTAMPS_MALFORMED")
    else:
        now_mono = _lease_monotonic_ns()
        if now_mono < created_mono:
            errors.append("LEASE_MONOTONIC_CREATED_IN_FUTURE")
        if updated_mono < created_mono:
            errors.append("LEASE_MONOTONIC_UPDATED_BEFORE_CREATED")
        age_s = (now_mono - created_mono) / 1_000_000_000
        if age_s > max_age_s:
            errors.append("LEASE_EXPIRED")

    return errors


def validate_lease_identity_field(
    data: dict, field_name: str, expected: "ProcessIdentity | None" = None
) -> "list[str]":
    """Validates data[field_name] (child or sandbox) as a populated,
    kernel-consistent ProcessIdentity. `field_name` is 'child' or
    'sandbox'."""
    errors: list[str] = []
    raw = data.get(field_name)
    if not isinstance(raw, dict):
        return [f"LEASE_{field_name.upper()}_IDENTITY_MISSING"]

    identity = ProcessIdentity.from_dict(raw)
    if identity is None:
        return [f"LEASE_{field_name.upper()}_IDENTITY_MALFORMED"]

    if is_protected_id(identity.pid) or is_protected_id(identity.pgid) or is_protected_id(identity.sid):
        errors.append(f"LEASE_{field_name.upper()}_IDENTITY_PROTECTED")

    if expected is not None:
        if (
            identity.pid != expected.pid
            or identity.pgid != expected.pgid
            or identity.sid != expected.sid
            or identity.start_ticks != expected.start_ticks
        ):
            errors.append(f"LEASE_{field_name.upper()}_IDENTITY_MISMATCH")

    if not identity_still_valid(identity):
        errors.append(f"LEASE_{field_name.upper()}_IDENTITY_STALE")

    return errors


# ---------------------------------------------------------------------------
# Signal escalation with kernel re-validation (Fase 2H.2.2)
# ---------------------------------------------------------------------------


@dataclass
class CleanupTimeouts:
    sigint_wait_s: float = DEFAULT_SIGINT_WAIT_S
    sigterm_wait_s: float = DEFAULT_SIGTERM_WAIT_S
    sigkill_wait_s: float = DEFAULT_SIGKILL_WAIT_S
    poll_interval_s: float = 0.5


def _pgid_alive(pgid: int) -> bool:
    if is_protected_id(pgid):
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _revalidate_identity_for_group_signal(
    expected: "ProcessIdentity", target_pgid: int
) -> "ProcessIdentity | None":
    """Fase 2H.2.4 -- the sole authority for "is it still safe to signal
    this PID as a member of `target_pgid`". Takes exactly one fresh kernel
    read of `expected.pid` and returns that *same* snapshot only if every
    invariant holds against it; returns None otherwise (process gone,
    reused, reparented out of the group, or never safe to begin with).

    This replaces the previous two-read pattern
    (``identity_still_valid(member) and read_process_identity(pid).pgid``)
    which read the kernel twice: once inside identity_still_valid() and
    once more directly. Between those two independent reads the PID could
    disappear (the second read returning None, and ``.pgid`` on None
    raising AttributeError) or -- far more dangerous -- exit and have its
    number reused by an unrelated process that the first read's
    start_ticks/uid check never re-confirmed. Callers must signal using
    the ProcessIdentity returned here, not `expected`, and must never
    issue a second, independent ``read_process_identity`` call to
    double-check this result.
    """
    current = read_process_identity(expected.pid)
    if current is None:
        return None
    if (
        current.pid != expected.pid
        or current.start_ticks != expected.start_ticks
        or current.uid != expected.uid
    ):
        return None
    if current.pgid != expected.pgid or current.pgid != target_pgid:
        return None
    # Session-contract invariant: every member of a group this module
    # spawned shares that group's session id (the leader created its own
    # session via start_new_session=True, so sid == pgid for the whole
    # tree) -- a candidate whose sid has drifted is never authorized.
    if current.sid != target_pgid:
        return None
    if (
        is_protected_id(current.pid)
        or is_protected_id(current.pgid)
        or is_protected_id(current.sid)
    ):
        return None
    return current


def escalate_signal_to_group(
    pgid: int,
    expected_leader: "ProcessIdentity | None",
    timeouts: CleanupTimeouts,
    attempts_log: "list[dict]",
    target_kind: str,
    reap_callback=None,
) -> bool:
    """Sends SIGINT, then SIGTERM, then targeted SIGKILL to exactly the
    members of `pgid`, re-validating the leader's kernel identity (when
    still alive) before each step, and falling back to per-member identity
    revalidation if the leader has already exited but members remain.
    Returns True if the group is confirmed gone afterwards. Every attempt
    (authorized or not, delivered or not) is appended to `attempts_log`.

    `reap_callback`, if given, is invoked (with no arguments) on every poll
    iteration of the wait loop. When the group leader is this caller's own
    *direct* child, `os.killpg(pgid, 0)` keeps reporting the group as alive
    even after the leader has fully exited, until that child is actually
    wait()/poll()ed -- an un-reaped zombie's PID is still a live member of
    its own process group. `reap_callback` should be the owning Popen's
    `.poll`, so the leader is reaped as soon as it exits instead of only at
    the end of the whole escalation.
    """
    if is_protected_id(pgid):
        attempts_log.append({
            "target_kind": target_kind, "pgid": pgid, "signal": None,
            "authorized": False, "delivered": False,
            "process_already_gone": False, "error_type": "PROTECTED_PGID",
            "timestamp_ns": time.time_ns(),
        })
        return not _pgid_alive(pgid)

    known_members: "dict[int, ProcessIdentity]" = {}
    if expected_leader is not None:
        known_members[expected_leader.pid] = expected_leader
    for member in list_pgid_members(pgid):
        known_members.setdefault(member.pid, member)

    def _authorized_targets() -> "list[ProcessIdentity]":
        if expected_leader is not None:
            leader_current = _revalidate_identity_for_group_signal(expected_leader, pgid)
            if leader_current is not None:
                return [leader_current]
        # Leader gone, mismatched, or never known: fall back to the
        # member identities captured once above (never re-discovered),
        # each re-validated individually against a single fresh snapshot.
        # Never trust a newly-discovered member that was not part of that
        # original capture.
        valid: "list[ProcessIdentity]" = []
        for member in known_members.values():
            current = _revalidate_identity_for_group_signal(member, pgid)
            if current is not None:
                valid.append(current)
        return valid

    def _wait_gone(deadline: float) -> bool:
        while time.monotonic() < deadline:
            if reap_callback is not None:
                reap_callback()
            if not _pgid_alive(pgid):
                return True
            time.sleep(timeouts.poll_interval_s)
        if reap_callback is not None:
            reap_callback()
        return not _pgid_alive(pgid)

    def _send(sig: int) -> None:
        targets = _authorized_targets()
        if not targets:
            attempts_log.append({
                "target_kind": target_kind, "pgid": pgid, "signal": int(sig),
                "authorized": False, "delivered": False,
                "process_already_gone": True, "error_type": None,
                "timestamp_ns": time.time_ns(),
            })
            return
        for target in targets:
            try:
                if target.pid == pgid:
                    os.killpg(pgid, sig)
                else:
                    os.kill(target.pid, sig)
                attempts_log.append({
                    "target_kind": target_kind, "pid": target.pid, "pgid": pgid,
                    "signal": int(sig), "authorized": True, "delivered": True,
                    "process_already_gone": False, "error_type": None,
                    "timestamp_ns": time.time_ns(),
                })
            except ProcessLookupError:
                attempts_log.append({
                    "target_kind": target_kind, "pid": target.pid, "pgid": pgid,
                    "signal": int(sig), "authorized": True, "delivered": False,
                    "process_already_gone": True, "error_type": "ProcessLookupError",
                    "timestamp_ns": time.time_ns(),
                })
            except PermissionError:
                attempts_log.append({
                    "target_kind": target_kind, "pid": target.pid, "pgid": pgid,
                    "signal": int(sig), "authorized": True, "delivered": False,
                    "process_already_gone": False, "error_type": "PermissionError",
                    "timestamp_ns": time.time_ns(),
                })
            except OSError as exc:
                attempts_log.append({
                    "target_kind": target_kind, "pid": target.pid, "pgid": pgid,
                    "signal": int(sig), "authorized": True, "delivered": False,
                    "process_already_gone": False, "error_type": type(exc).__name__,
                    "timestamp_ns": time.time_ns(),
                })

    if reap_callback is not None:
        reap_callback()
    if not _pgid_alive(pgid):
        return True

    _send(signal.SIGINT)
    if _wait_gone(time.monotonic() + timeouts.sigint_wait_s):
        return True

    _send(signal.SIGTERM)
    if _wait_gone(time.monotonic() + timeouts.sigterm_wait_s):
        return True

    _send(signal.SIGKILL)
    return _wait_gone(time.monotonic() + timeouts.sigkill_wait_s)


# ---------------------------------------------------------------------------
# Legacy helpers retained for ros2-cli interaction (unaffected by 2H.2.2)
# ---------------------------------------------------------------------------


def _build_env(domain_id: str) -> dict:
    env = os.environ.copy()
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["ROS_DOMAIN_ID"] = domain_id
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = str(CODE_ROOT)
    else:
        env["PYTHONPATH"] = f"{CODE_ROOT}:{env['PYTHONPATH']}"
    return env


def _run(cmd: list, env: dict, timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="TIMEOUT")


def _node_list(env: dict, timeout: float) -> list:
    proc = _run(["ros2", "node", "list"], env, timeout)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _lifecycle_get(node_fqn: str, env: dict, timeout: float) -> "str | None":
    proc = _run(["ros2", "lifecycle", "get", node_fqn], env, timeout)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().split()[0].lower()


def wait_for_components_deterministic(
    fqns: list, env: dict, deadline: float,
    _telemetry: "dict | None" = None,
) -> "tuple[bool, dict]":
    """Fase 2H.2.2: single shared deadline, single `ros2 node list` call per
    iteration (instead of looping sequentially per-component with its own
    sub-deadline, which could starve later components of their fair share of
    time even while they were coming up correctly). Returns
    (all_active, status_by_fqn) where status_by_fqn values are one of
    'active', 'NOT_DISCOVERED', 'NOT_ACTIVE:<state>', or
    'LIFECYCLE_QUERY_FAILED'.

    If _telemetry is provided (a mutable dict), it is populated with:
      lifecycle_query_attempts, lifecycle_query_errors,
      first_discovery_monotonic_ns, first_lifecycle_state,
      deadline_remaining_ms (set only on successful return).
    """
    last_status: dict = {fqn: "NOT_DISCOVERED" for fqn in fqns}
    attempt_count = 0
    error_count = 0
    first_discovery_ns: "int | None" = None
    first_lifecycle_state: "str | None" = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        list_timeout = min(5.0, max(0.5, remaining))
        discovered = set(_node_list(env, timeout=list_timeout))
        attempt_count += 1

        all_active = True
        for fqn in fqns:
            if fqn not in discovered:
                last_status[fqn] = "NOT_DISCOVERED"
                all_active = False
                continue
            if first_discovery_ns is None:
                first_discovery_ns = time.monotonic_ns()
            remaining2 = deadline - time.monotonic()
            if remaining2 <= 0:
                all_active = False
                continue
            lifecycle_timeout = min(5.0, max(0.5, remaining2))
            state = _lifecycle_get(fqn, env, timeout=lifecycle_timeout)
            if state is None:
                last_status[fqn] = "LIFECYCLE_QUERY_FAILED"
                error_count += 1
                all_active = False
            elif state == "active":
                last_status[fqn] = "active"
            else:
                last_status[fqn] = f"NOT_ACTIVE:{state}"
                all_active = False
            if first_lifecycle_state is None:
                first_lifecycle_state = last_status[fqn]

        if all_active:
            if _telemetry is not None:
                _telemetry["lifecycle_query_attempts"] = attempt_count
                _telemetry["lifecycle_query_errors"] = error_count
                _telemetry["first_discovery_monotonic_ns"] = first_discovery_ns
                _telemetry["first_lifecycle_state"] = first_lifecycle_state
                _telemetry["deadline_remaining_ms"] = max(0.0, deadline - time.monotonic()) * 1000.0
            return True, last_status
        if time.monotonic() >= deadline:
            break
        time.sleep(1.0)

    if _telemetry is not None:
        _telemetry["lifecycle_query_attempts"] = attempt_count
        _telemetry["lifecycle_query_errors"] = error_count
        _telemetry["first_discovery_monotonic_ns"] = first_discovery_ns
        _telemetry["first_lifecycle_state"] = first_lifecycle_state
        _telemetry["deadline_remaining_ms"] = 0.0
    return False, last_status


def _collect_zombie_children(parent_pid: "int | None" = None) -> list:
    """Returns PIDs of zombie children of `parent_pid` (default: this
    process), read directly from /proc -- never via `ps`."""
    target_ppid = parent_pid if parent_pid is not None else os.getpid()
    zombies: list = []
    try:
        candidates = [int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()]
    except OSError:
        return []
    for pid in candidates:
        stat_path = Path(f"/proc/{pid}/stat")
        try:
            text = stat_path.read_text()
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
        parsed = _parse_proc_stat(text)
        if parsed is None:
            continue
        _pid_field, _comm, rest = parsed
        try:
            state = rest[0]
            ppid = int(rest[1])
        except (IndexError, ValueError):
            continue
        if ppid == target_ppid and state.startswith("Z"):
            zombies.append(pid)
    return zombies


# ---------------------------------------------------------------------------
# Child <-> parent result/output paths
# ---------------------------------------------------------------------------


def _build_child_output_path(run_id: str) -> Path:
    return Path(tempfile.gettempdir()) / f"ottoguide_main_runtime_2h22_child_{run_id}.json"


def _write_atomic(path: Path, data: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(str(tmp), str(path))


def _validate_child_result(
    payload: dict,
    expected_scenario: str,
    expected_domain: str,
    expected_run_id: str,
    returncode: int,
    expected_child_identity: "ProcessIdentity | None" = None,
) -> list:
    """Pure identity/exit-code validation of a child's reported JSON. Never
    trusts the child's self-reported ok/scenario/domain_id/run_id/identity
    alone -- expected_child_identity (when given) must be the identity this
    parent itself captured directly via spawn_isolated() at the moment it
    launched the child, never re-derived from the JSON payload being
    validated.
    """
    errors: list = []

    if payload.get("run_id") != expected_run_id:
        errors.append(f"CHILD_RUN_ID_MISMATCH:{payload.get('run_id')!r}!={expected_run_id!r}")
    if payload.get("scenario") != expected_scenario:
        errors.append(
            f"CHILD_SCENARIO_MISMATCH:{payload.get('scenario')!r}!={expected_scenario!r}"
        )
    if str(payload.get("domain_id")) != str(expected_domain):
        errors.append(
            f"CHILD_DOMAIN_MISMATCH:{payload.get('domain_id')!r}!={expected_domain!r}"
        )

    if expected_child_identity is not None:
        reported = ProcessIdentity.from_dict(payload.get("child_identity") or {})
        if reported is None:
            errors.append("CHILD_IDENTITY_MISSING_OR_MALFORMED")
        else:
            if reported.pid != expected_child_identity.pid:
                errors.append(f"CHILD_PID_MISMATCH:{reported.pid}!={expected_child_identity.pid}")
            if reported.pgid != expected_child_identity.pgid:
                errors.append(f"CHILD_PGID_MISMATCH:{reported.pgid}!={expected_child_identity.pgid}")
            if reported.sid != expected_child_identity.sid:
                errors.append(f"CHILD_SID_MISMATCH:{reported.sid}!={expected_child_identity.sid}")
            if reported.start_ticks != expected_child_identity.start_ticks:
                errors.append(
                    f"CHILD_START_TICKS_MISMATCH:{reported.start_ticks}!={expected_child_identity.start_ticks}"
                )

    ok = payload.get("ok")
    if ok is True and returncode != 0:
        errors.append(f"CHILD_EXIT_CODE_MISMATCH:ok=True,returncode={returncode}")
    elif ok is False and returncode != 1:
        errors.append(f"CHILD_EXIT_CODE_MISMATCH:ok=False,returncode={returncode}")

    return errors


def validate_child_output_file_metadata(path: Path) -> "list[str]":
    """Validates the child output file's filesystem metadata before it is
    ever parsed as JSON: regular file, owned by this process's own uid,
    mode not group/other-writable, single hard link, never a symlink.
    Returns a list of error codes (empty list = valid)."""
    errors: list[str] = []
    try:
        lstat_result = path.lstat()
    except OSError as exc:
        return [f"CHILD_OUTPUT_STAT_FAILED:{exc}"]
    if stat.S_ISLNK(lstat_result.st_mode):
        errors.append("CHILD_OUTPUT_IS_SYMLINK")
        return errors
    if not stat.S_ISREG(lstat_result.st_mode):
        errors.append("CHILD_OUTPUT_NOT_REGULAR")
    if hasattr(os, "getuid") and lstat_result.st_uid != os.getuid():
        errors.append("CHILD_OUTPUT_WRONG_OWNER")
    if lstat_result.st_nlink != 1:
        errors.append("CHILD_OUTPUT_UNEXPECTED_NLINK")
    if stat.S_IMODE(lstat_result.st_mode) & 0o022:
        errors.append("CHILD_OUTPUT_PERMISSIONS_TOO_OPEN")
    return errors


def validate_domain_id_range(base: int, maximum_offset: int) -> "str | None":
    if not isinstance(base, int) or base < MIN_DOMAIN_ID or base > MAX_DOMAIN_ID:
        return "INVALID_DOMAIN_ID"
    if base + maximum_offset > MAX_DOMAIN_ID:
        return "DERIVED_DOMAIN_ID_OUT_OF_RANGE"
    return None


def parse_base_domain_id(raw_value: str) -> "tuple[int | None, str | None]":
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
        self.move_calls: list = []
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
    plan = TourPlan(waypoints=[wp], tour_id="smoke-2h22-tour-success")
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


async def _wait_goal_active_with_feedback(nav_bridge, timeout_s: float):
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
    plan = TourPlan(waypoints=[wp], tour_id="smoke-2h22-interaction-cancel")
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
    plan = TourPlan(waypoints=[wp], tour_id="smoke-2h22-emergency-cancel")
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
        orchestrator.emergency_stop(reason="smoke_test_2h22_emergency"), timeout=timeout_s
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


# ---------------------------------------------------------------------------
# Child entry point
# ---------------------------------------------------------------------------


async def _run_scenario_body(
    name: str,
    namespace: str,
    domain_id: str,
    timeout_s: float,
    sandbox_proc: "subprocess.Popen | None",
    result: dict,
    spawn_monotonic_ns: int = 0,
) -> None:
    env = _build_env(domain_id)
    log_fd = None
    main_module = None
    installed_mocks: dict = {}

    try:
        fqns = [f"/{namespace}/{component}" for component in REQUIRED_COMPONENTS]
        deadline = time.monotonic() + timeout_s
        _wfc_telemetry: dict = {}
        all_active, status_by_fqn = wait_for_components_deterministic(
            fqns, env, deadline, _telemetry=_wfc_telemetry,
        )
        active_monotonic_ns = time.monotonic_ns()
        result["metrics"]["component_status"] = status_by_fqn
        result["metrics"]["instrumentation_2h25"] = {
            "process_spawn_monotonic_ns": spawn_monotonic_ns or None,
            "launch_start_monotonic_ns": spawn_monotonic_ns or None,
            "first_discovery_monotonic_ns": _wfc_telemetry.get("first_discovery_monotonic_ns"),
            "discovery_elapsed_ms": (
                ((_wfc_telemetry.get("first_discovery_monotonic_ns") or 0) - spawn_monotonic_ns) / 1e6
                if spawn_monotonic_ns and _wfc_telemetry.get("first_discovery_monotonic_ns")
                else None
            ),
            "lifecycle_query_attempts": _wfc_telemetry.get("lifecycle_query_attempts"),
            "lifecycle_query_errors": _wfc_telemetry.get("lifecycle_query_errors"),
            "first_lifecycle_state": _wfc_telemetry.get("first_lifecycle_state"),
            "active_monotonic_ns": active_monotonic_ns if all_active else None,
            "active_elapsed_ms": (
                (active_monotonic_ns - spawn_monotonic_ns) / 1e6
                if all_active and spawn_monotonic_ns else None
            ),
            "deadline_budget_ms": timeout_s * 1000.0,
            "deadline_remaining_ms": _wfc_telemetry.get("deadline_remaining_ms"),
            "process_poll": None,
            "process_exit_code": None,
            "last_error": None,
        }
        if not all_active:
            for fqn, status in status_by_fqn.items():
                if status != "active":
                    result["errors"].append(f"{fqn}_{status}")
            return

        nodes = _node_list(env, timeout=5.0)
        if any(any(f in n.lower() for f in FORBIDDEN_NODE_SUBSTRINGS) for n in nodes):
            result["errors"].append("HARDWARE_NODE_DETECTED")
        if any(any(f in n.lower() for f in FORBIDDEN_MISSION_NODE_SUBSTRINGS) for n in nodes):
            result["errors"].append("MISSION_NODE_DETECTED")
        if result["errors"]:
            return

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
        # sequence + nav_bridge.close() already happened. It never calls
        # ConversationManager.close() itself (a main.py gap outside this
        # phase's allowlist/frozen-file scope -- main.py cannot be edited
        # here); ConversationManager.close()'s own docstring documents that
        # main.py's shutdown is its intended caller. Closing it directly
        # from the smoke test exercises that already-existing, real method
        # without modifying any frozen file, so the ProcessPoolExecutor/
        # ThreadPoolExecutor pair it owns (and their QueueFeederThread) are
        # never counted as an owned-thread leak belonging to this scenario.
        conversation_manager = getattr(orchestrator, "_conversation_manager", None)
        close_fn = getattr(conversation_manager, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception as exc:
                result["errors"].append(f"CONVERSATION_MANAGER_CLOSE_FAILED:{exc}")

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
        if log_fd:
            log_fd.close()


def _shutdown_sandbox_and_reap(
    sandbox_proc: "subprocess.Popen | None",
    sandbox_identity: "ProcessIdentity | None",
    timeouts: CleanupTimeouts,
) -> dict:
    """Normal (non-timeout) sandbox cleanup: directed escalation against the
    sandbox's own kernel-validated process group, followed by a mandatory
    wait() on the immediate Popen object so it can never remain a zombie.
    Returns structured evidence; never a bare 0/1.
    """
    evidence = {
        "attempted": sandbox_proc is not None,
        "signal_attempts": [],
        "group_alive_after": None,
        "reaped": False,
        "returncode": None,
        "owned_members_remaining": [],
    }
    if sandbox_proc is None:
        evidence["group_alive_after"] = False
        evidence["reaped"] = True
        return evidence

    if sandbox_identity is not None:
        escalate_signal_to_group(
            sandbox_identity.pgid, sandbox_identity, timeouts, evidence["signal_attempts"], "sandbox",
            reap_callback=sandbox_proc.poll,
        )
        evidence["group_alive_after"] = _pgid_alive(sandbox_identity.pgid)
        if evidence["group_alive_after"]:
            evidence["owned_members_remaining"] = [
                m.to_dict() for m in list_pgid_members(sandbox_identity.pgid)
            ]
    else:
        evidence["group_alive_after"] = None

    try:
        sandbox_proc.wait(timeout=timeouts.sigkill_wait_s + 5.0)
        evidence["reaped"] = True
    except subprocess.TimeoutExpired:
        evidence["reaped"] = sandbox_proc.poll() is not None
    evidence["returncode"] = sandbox_proc.returncode

    return evidence


def _scenario_main(args: argparse.Namespace) -> int:
    """Child entry point: exactly one rclpy lifecycle, one ROS_DOMAIN_ID.

    Owns the sandbox wrapper Popen directly (spawned with its own session
    via spawn_isolated) and updates the cleanup lease with its own and the
    sandbox's kernel identity as soon as each is known, so the parent can
    validate and -- only if valid -- act on them during a timeout.
    """
    domain_id = args.base_domain_id
    namespace = DEFAULT_NAMESPACE
    run_id = args.run_id
    lease_dir = Path(args.lease_dir) if args.lease_dir else None

    expected_parent: "ProcessIdentity | None" = None
    if args.expected_parent_pid is not None:
        try:
            expected_parent = ProcessIdentity(
                pid=int(args.expected_parent_pid),
                ppid=int(args.expected_parent_ppid),
                pgid=int(args.expected_parent_pgid),
                sid=int(args.expected_parent_sid),
                start_ticks=int(args.expected_parent_start_ticks),
                uid=int(args.expected_parent_uid),
            )
        except (TypeError, ValueError):
            expected_parent = None

    result = {
        "schema_version": LEASE_SCHEMA_VERSION,
        "run_id": run_id,
        "ok": False,
        "scenario": args.scenario,
        "domain_id": domain_id,
        "errors": [],
        "metrics": {},
        "child_identity": None,
        "sandbox_identity": None,
        "cleanup_evidence": None,
        "owned_threads_remaining": 0,
        "owned_thread_names": [],
        "zombies_remaining": 0,
        "zombie_pids": [],
        "orphan_processes": 0,
    }

    if getattr(args, "fault_inject_hang_sandbox", False) and not _fault_injection_2h24_authorized():
        result["errors"].append("FAULT_INJECTION_NOT_AUTHORIZED")
        payload = json.dumps(result, indent=2)
        print(payload)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload)
        return 1

    own_identity = read_process_identity(os.getpid())
    result["child_identity"] = own_identity.to_dict() if own_identity else None

    lease: "CleanupLease | None" = None
    if lease_dir is not None and expected_parent is not None:
        try:
            lease = CleanupLease.open_existing(lease_dir)
            data = lease.read()
            lease_errors = validate_lease_immutable_fields(
                data, run_id, args.scenario, domain_id, expected_parent=expected_parent,
                max_age_s=args.lease_max_age_s, expected_token=args.lease_token,
            )
            if lease_errors:
                result["errors"].extend(f"LEASE_VALIDATION_FAILED:{e}" for e in lease_errors)
                lease = None
            elif own_identity is not None:
                lease.update_child_identity(own_identity)
        except LeaseError as exc:
            result["errors"].append(f"LEASE_VALIDATION_FAILED:{exc}")
            lease = None
    elif lease_dir is not None:
        result["errors"].append("LEASE_VALIDATION_FAILED:EXPECTED_PARENT_IDENTITY_MISSING")

    if result["errors"]:
        result["ok"] = False
        payload = json.dumps(result, indent=2)
        print(payload)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload)
        return 1

    sandbox_proc: "subprocess.Popen | None" = None
    sandbox_identity: "ProcessIdentity | None" = None
    log_path: "Path | None" = None
    thread_baseline_objects = set(threading.enumerate())

    try:
        log_path = (
            Path(str(args.output).replace(".json", ".log"))
            if args.output
            else Path(tempfile.gettempdir()) / f"ottoguide_main_runtime_2h22_{args.scenario}_{domain_id}.log"
        )
        log_fd = open(log_path, "w")
        fault_inject = getattr(args, "fault_inject_hang_sandbox", False)
        launch_start_monotonic_ns = time.monotonic_ns()
        try:
            if fault_inject:
                # Fase 2H.2.4 fault injection, already authorization-gated
                # above: an inert, isolated stand-in -- never the real ROS
                # sandbox wrapper -- whose only job is to be a real,
                # distinct, isolated process group for the parent's
                # lease-based escalation to target during a forced timeout.
                sandbox_cmd = [sys.executable, "-c", f"import time; time.sleep({FAULT_SANDBOX_SLEEP_S})"]
                sandbox_env = {}
            else:
                sandbox_cmd = ["bash", str(RUNTIME_WRAPPER), f"sandbox_namespace:={namespace}", "use_rviz:=false"]
                sandbox_env = _build_env(domain_id)
            sandbox_proc, sandbox_identity = spawn_isolated(
                sandbox_cmd, env=sandbox_env, stdout=log_fd, stderr=subprocess.STDOUT, text=True,
            )
        except RuntimeError as exc:
            result["errors"].append(f"SANDBOX_SPAWN_NOT_ISOLATED:{exc}")
            log_fd.close()
            payload = json.dumps(result, indent=2)
            print(payload)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload)
            return 1
        process_spawn_monotonic_ns = time.monotonic_ns()
        result["metrics"]["launch_start_monotonic_ns"] = launch_start_monotonic_ns
        result["metrics"]["process_spawn_monotonic_ns"] = process_spawn_monotonic_ns

        result["sandbox_identity"] = sandbox_identity.to_dict()
        if own_identity is not None and (
            sandbox_identity.pgid == own_identity.pgid or sandbox_identity.sid == own_identity.sid
        ):
            result["errors"].append("SANDBOX_GROUP_NOT_DISTINCT_FROM_CHILD")

        if lease is not None:
            try:
                data = lease.read()
                lease_errors = validate_lease_immutable_fields(
                    data, run_id, args.scenario, domain_id, expected_parent=expected_parent,
                    max_age_s=args.lease_max_age_s, expected_token=args.lease_token,
                )
                lease_errors += validate_lease_identity_field(data, "child", own_identity)
                if lease_errors:
                    result["errors"].extend(f"LEASE_VALIDATION_FAILED:{e}" for e in lease_errors)
                else:
                    lease.update_sandbox_identity(sandbox_identity)
            except LeaseError as exc:
                result["errors"].append(f"LEASE_VALIDATION_FAILED:{exc}")

        if not result["errors"]:
            if fault_inject:
                # Deliberately stall (no ROS, no asyncio) until the parent's
                # own timeout/cleanup logic signals this child's group or
                # the stand-in sandbox's group -- proving the *real* CLI
                # timeout transition, not a direct call to the cleanup
                # function. Default SIGINT disposition: this process exits
                # promptly once signalled, running the `finally` below.
                sandbox_proc.wait()
            else:
                asyncio.run(
                    _run_scenario_body(
                        args.scenario, namespace, domain_id, args.timeout, sandbox_proc, result,
                        spawn_monotonic_ns=process_spawn_monotonic_ns,
                    )
                )
    finally:
        instr = result["metrics"].get("instrumentation_2h25")
        if instr is not None:
            instr["process_poll"] = sandbox_proc.poll() if sandbox_proc else None
        cleanup_evidence = _shutdown_sandbox_and_reap(sandbox_proc, sandbox_identity, CleanupTimeouts())
        result["cleanup_evidence"] = cleanup_evidence
        if cleanup_evidence["group_alive_after"]:
            result["errors"].append("ORPHAN_PROCESSES")
            result["orphan_processes"] = len(cleanup_evidence["owned_members_remaining"])
        if not cleanup_evidence["reaped"]:
            result["errors"].append("SANDBOX_NOT_REAPED")
        try:
            log_fd.close()
        except Exception:
            pass

        # Thread leak detection: compare thread *objects*, not just counts,
        # against the baseline captured before the sandbox/lifespan work.
        # ConversationManager.close() (called above, inside
        # _run_scenario_body's success path) shuts its executors down with
        # wait=False by design, so their worker/feeder threads can still be
        # in the process of exiting for a brief moment after close()
        # returns; poll with a short, bounded settle window instead of
        # judging on a single immediate snapshot.
        settle_deadline = time.monotonic() + 5.0
        new_threads: list = []
        while True:
            current_threads = set(threading.enumerate())
            new_threads = [
                t for t in current_threads - thread_baseline_objects
                if t is not threading.main_thread()
            ]
            if not new_threads or time.monotonic() >= settle_deadline:
                break
            time.sleep(0.2)
        result["owned_threads_remaining"] = len(new_threads)
        result["owned_thread_names"] = [t.name for t in new_threads]
        if new_threads:
            result["errors"].append("OWNED_THREADS_REMAINING")

        # Stray-descendant detection: any process other than this one that
        # is still a member of *this child's own* process group (own_pgid).
        # ros2cli's discovery daemon (`ros2-daemon`) is the concrete
        # example found during 2H.2.2 runtime validation: `ros2 node
        # list`/`ros2 lifecycle get` lazily spawn it once, it inherits this
        # child's session/group, and it is a long-lived background daemon
        # by ros2cli's own design -- it never exits on its own and is never
        # touched by _shutdown_sandbox_and_reap (which only ever targets
        # the *sandbox's* group, never this child's own). Targeted
        # os.kill() per stray PID is used here, never os.killpg() on
        # own_pgid, because that would also signal this process itself.
        own_identity_now = read_process_identity(os.getpid())
        if own_identity_now is not None:
            own_pgid = own_identity_now.pgid
            stray_members = [
                m for m in list_pgid_members(own_pgid) if m.pid != os.getpid()
            ]
            if stray_members:
                for member in stray_members:
                    try:
                        os.kill(member.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                time.sleep(0.3)
                still_alive = [
                    m for m in stray_members if identity_still_valid(m)
                ]
                if still_alive:
                    for member in still_alive:
                        try:
                            os.kill(member.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError, OSError):
                            pass
                    time.sleep(0.3)
                final_remaining = [
                    m.to_dict() for m in stray_members if identity_still_valid(m)
                ]
                if final_remaining:
                    result["orphan_processes"] += len(final_remaining)
                    if "ORPHAN_PROCESSES" not in result["errors"]:
                        result["errors"].append("ORPHAN_PROCESSES")

        zombie_pids = _collect_zombie_children(os.getpid())
        result["zombies_remaining"] = len(zombie_pids)
        result["zombie_pids"] = zombie_pids
        if zombie_pids:
            result["errors"].append("ZOMBIES_REMAINING")

    # Finalize instrumentation fields available only after cleanup.
    instr = result["metrics"].get("instrumentation_2h25")
    if instr is not None:
        ce = result.get("cleanup_evidence") or {}
        instr["process_exit_code"] = ce.get("returncode")
        instr["last_error"] = result["errors"][-1] if result["errors"] else None
        instr["bounded_log_tail_hash"] = _bounded_log_tail_hash(log_path)

    # Metadata for audit traceability (Fase 2H.2.5 Section 11.4).
    result["runtime_metadata_2h25"] = {
        "run_id": run_id,
        "scenario": args.scenario,
        "ROS_DOMAIN_ID": domain_id,
        "ROS_LOCALHOST_ONLY": os.environ.get("ROS_LOCALHOST_ONLY", "1"),
        "ROS_DISTRO": os.environ.get("ROS_DISTRO", "jazzy"),
        "RMW_IMPLEMENTATION": os.environ.get("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp"),
        "tested_commit_sha": _get_tested_commit_sha(),
    }

    result["ok"] = len(result["errors"]) == 0
    payload = json.dumps(result, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    return 0 if result["ok"] else 1


def _parent_timeout_cleanup(
    child_proc: "subprocess.Popen[str]",
    child_identity: "ProcessIdentity | None",
    run_id: str,
    scenario: str,
    domain_id: str,
    lease_dir: "Path | None",
    parent_identity: "ProcessIdentity | None",
    lease_max_age_s: float,
    lease_token: "str | None" = None,
) -> dict:
    """Structured timeout cleanup, never returning None. The sandbox is only
    ever signalled if the lease can be re-validated end-to-end (schema,
    token, run_id, scenario, domain, parent identity, child identity, and
    vigency); otherwise sandbox cleanup is explicitly skipped and only the
    immediate child (whose identity the parent captured directly at spawn
    time) is targeted. The child's own `finally` block, if it still gets to
    run before being killed, attempts to clean up its own sandbox.

    The child is torn down and reaped *before* the sandbox is escalated
    (Fase 2H.2.3). The sandbox processes are children of the stalled child,
    never of this parent, so this parent can never reap them directly; if the
    sandbox were signalled while the child were still alive, the killed
    sandbox processes would become unreaped zombies under the stalled child,
    and a zombie's PID stays a member of its own process group -- making
    os.killpg(sandbox_pgid, 0) report the group as alive even though every
    process in it is already dead. Reaping the child first reparents the
    orphaned sandbox to init, so escalating the sandbox afterwards lets init
    reap the resulting zombies and the liveness check reflects the true
    post-teardown state. Lease validation still happens before any sandbox
    signal, so the safety contract is unchanged by the ordering.
    """
    timeouts = CleanupTimeouts()
    evidence = {
        "executed": True,
        "ok": False,
        "lease_validation": {"ok": False, "errors": []},
        "child_identity_validation": {"ok": False, "errors": []},
        "targets": {},
        "signal_attempts": [],
        "child_reaped": False,
        "child_returncode": None,
        "child_group_alive_after": None,
        "sandbox_group_alive_after": None,
        "owned_members_remaining": [],
        "errors": [],
    }

    if child_identity is not None and identity_still_valid(child_identity):
        evidence["child_identity_validation"] = {"ok": True, "errors": []}
    else:
        evidence["child_identity_validation"] = {"ok": False, "errors": ["CHILD_IDENTITY_STALE_OR_MISSING"]}

    sandbox_identity: "ProcessIdentity | None" = None
    if lease_dir is not None:
        try:
            lease = CleanupLease.open_existing(lease_dir)
            data = lease.read()
            lease_errors = validate_lease_immutable_fields(
                data, run_id, scenario, domain_id, expected_parent=parent_identity,
                max_age_s=lease_max_age_s, expected_token=lease_token,
            )
            lease_errors += validate_lease_identity_field(data, "child", child_identity)
            sandbox_errors = validate_lease_identity_field(data, "sandbox")
            if not lease_errors and not sandbox_errors:
                evidence["lease_validation"] = {"ok": True, "errors": []}
                sandbox_raw = data.get("sandbox", {})
                sandbox_identity = ProcessIdentity.from_dict(sandbox_raw)
            else:
                evidence["lease_validation"] = {"ok": False, "errors": lease_errors + sandbox_errors}
        except LeaseError as exc:
            evidence["lease_validation"] = {"ok": False, "errors": [f"LEASE_ERROR:{exc}"]}
    else:
        evidence["lease_validation"] = {"ok": False, "errors": ["LEASE_DIR_NOT_PROVIDED"]}

    # The lease (which proves the sandbox identity) is validated above,
    # before any signal, so the safety contract is order-independent. Capture
    # whether the sandbox is authorized for cleanup, but defer escalating it
    # until the child has been reaped (see the docstring: signalling the
    # sandbox while the child is still alive leaves unreaped zombies under the
    # stalled child that keep the sandbox group spuriously "alive").
    sandbox_authorized = evidence["lease_validation"]["ok"] and sandbox_identity is not None
    if not sandbox_authorized:
        evidence["errors"].append("SANDBOX_CLEANUP_NOT_AUTHORIZED")

    # 1) Child cleanup uses exclusively the identity captured directly by this
    #    parent at spawn time -- never the lease's copy of it.
    child_timeouts = CleanupTimeouts(
        sigint_wait_s=DEFAULT_CHILD_SIGINT_WAIT_S,
        sigterm_wait_s=DEFAULT_CHILD_SIGTERM_WAIT_S,
        sigkill_wait_s=DEFAULT_CHILD_SIGKILL_WAIT_S,
    )
    if child_identity is not None:
        evidence["targets"]["child_pgid"] = child_identity.pgid
        escalate_signal_to_group(
            child_identity.pgid, child_identity, child_timeouts, evidence["signal_attempts"], "child",
            reap_callback=child_proc.poll,
        )
        evidence["child_group_alive_after"] = _pgid_alive(child_identity.pgid)
        if evidence["child_group_alive_after"]:
            evidence["owned_members_remaining"].extend(
                m.to_dict() for m in list_pgid_members(child_identity.pgid)
            )
            evidence["errors"].append("CHILD_GROUP_SURVIVED_ESCALATION")
    else:
        evidence["errors"].append("CHILD_IDENTITY_UNAVAILABLE")

    try:
        child_proc.wait(timeout=10.0)
        evidence["child_reaped"] = True
    except subprocess.TimeoutExpired:
        evidence["child_reaped"] = child_proc.poll() is not None
        if not evidence["child_reaped"]:
            evidence["errors"].append("CHILD_NOT_REAPED")
    evidence["child_returncode"] = child_proc.returncode

    # 2) Sandbox cleanup, only now that the child is reaped and the sandbox
    #    has been reparented to init. escalate_signal_to_group's own
    #    _wait_gone loop returns as soon as the group is empty; once the
    #    orphaned sandbox is killed, init reaps it promptly, so a short bounded
    #    settle covers any reap latency before the final liveness measurement.
    if sandbox_authorized:
        evidence["targets"]["sandbox_pgid"] = sandbox_identity.pgid
        escalate_signal_to_group(
            sandbox_identity.pgid, sandbox_identity, timeouts, evidence["signal_attempts"], "sandbox"
        )
        settle_deadline = time.monotonic() + 8.0
        while _pgid_alive(sandbox_identity.pgid) and time.monotonic() < settle_deadline:
            time.sleep(0.2)
        evidence["sandbox_group_alive_after"] = _pgid_alive(sandbox_identity.pgid)
        if evidence["sandbox_group_alive_after"]:
            evidence["owned_members_remaining"].extend(
                m.to_dict() for m in list_pgid_members(sandbox_identity.pgid)
            )
            evidence["errors"].append("SANDBOX_GROUP_SURVIVED_ESCALATION")

    evidence["ok"] = len(evidence["errors"]) == 0
    return evidence


def _parent_main(args: argparse.Namespace) -> int:
    def _fail(errors: list) -> int:
        payload = {"ok": False, "decision": "FAIL", "errors": errors}
        output_str = json.dumps(payload)
        print(output_str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output_str)
        return 2

    if getattr(args, "fault_inject_hang_sandbox", False) and not _fault_injection_2h24_authorized():
        return _fail(["FAULT_INJECTION_NOT_AUTHORIZED"])

    base, parse_error = parse_base_domain_id(args.base_domain_id)
    if parse_error is not None:
        return _fail([parse_error])

    range_error = validate_domain_id_range(base, MAXIMUM_OFFSET)
    if range_error is not None:
        return _fail([range_error])

    if args.timeout <= 0:
        return _fail(["TIMEOUT_MUST_BE_POSITIVE"])

    scenarios = list(zip(SCENARIOS, (base + i for i in range(len(SCENARIOS)))))

    parent_identity = read_process_identity(os.getpid())

    all_ok = True
    overall_payload = []

    for name, domain in scenarios:
        domain_str = str(domain)
        run_id = secrets.token_hex(16)
        child_output = _build_child_output_path(run_id)

        if child_output.exists():
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_OUTPUT_PREEXISTING"]}
            overall_payload.append(res)
            all_ok = False
            continue

        lease: "CleanupLease | None" = None
        lease_dir: "Path | None" = None
        lease_token: "str | None" = None
        if parent_identity is not None:
            try:
                lease, lease_token = CleanupLease.create(
                    Path(tempfile.gettempdir()), run_id, name, domain_str, parent_identity
                )
                lease_dir = lease.lease_dir
            except (LeaseError, OSError) as exc:
                res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": [f"LEASE_CREATE_FAILED:{exc}"]}
                overall_payload.append(res)
                all_ok = False
                continue
        else:
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["PARENT_IDENTITY_UNAVAILABLE"]}
            overall_payload.append(res)
            all_ok = False
            continue

        child_cmd = [
            sys.executable, str(THIS_FILE),
            "--scenario", name,
            "--base-domain-id", domain_str,
            "--timeout", str(args.timeout),
            "--output", str(child_output),
            "--run-id", run_id,
            "--lease-dir", str(lease_dir),
            "--lease-max-age-s", str(args.lease_max_age_s),
            "--lease-token", lease_token,
            "--expected-parent-pid", str(parent_identity.pid),
            "--expected-parent-ppid", str(parent_identity.ppid),
            "--expected-parent-pgid", str(parent_identity.pgid),
            "--expected-parent-sid", str(parent_identity.sid),
            "--expected-parent-start-ticks", str(parent_identity.start_ticks),
            "--expected-parent-uid", str(parent_identity.uid),
        ]
        if getattr(args, "fault_inject_hang_sandbox", False):
            child_cmd.append("--fault-inject-hang-sandbox")
        try:
            child_proc, child_identity = spawn_isolated(
                child_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        except RuntimeError as exc:
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": [f"CHILD_SPAWN_NOT_ISOLATED:{exc}"]}
            overall_payload.append(res)
            all_ok = False
            lease.destroy()
            continue

        parent_timeout_cleanup_executed = False
        try:
            # Margin on top of the child's own timeout_s (which already
            # includes sandbox bringup and cleanup), covering the full
            # sandbox+child escalation performed by _parent_timeout_cleanup.
            # Only a fault-injection-authorized run may shrink this margin
            # (see _communicate_timeout_margin_s); production behavior is
            # the literal 150.0 it always was.
            child_stdout, _child_stderr = child_proc.communicate(
                timeout=args.timeout + _communicate_timeout_margin_s()
            )
        except subprocess.TimeoutExpired:
            cleanup_evidence = _parent_timeout_cleanup(
                child_proc, child_identity, run_id, name, domain_str, lease_dir,
                parent_identity, args.lease_max_age_s, lease_token,
            )
            parent_timeout_cleanup_executed = True
            res = {
                "ok": False,
                "scenario": name,
                "domain_id": domain_str,
                "errors": ["CHILD_PROCESS_TIMEOUT"],
                "parent_timeout_cleanup_executed": True,
                "parent_timeout_cleanup_evidence": cleanup_evidence,
            }
            overall_payload.append(res)
            all_ok = False
            lease.destroy()
            continue

        completed_returncode = child_proc.returncode
        lease.destroy()

        if not child_output.is_file():
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_OUTPUT_MISSING"]}
            overall_payload.append(res)
            all_ok = False
            continue

        metadata_errors = validate_child_output_file_metadata(child_output)
        if metadata_errors:
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": metadata_errors}
            overall_payload.append(res)
            all_ok = False
            try:
                child_output.unlink(missing_ok=True)
            except Exception:
                pass
            continue

        try:
            res = json.loads(child_output.read_text())
        except Exception:
            res = {"ok": False, "scenario": name, "domain_id": domain_str, "errors": ["CHILD_OUTPUT_INVALID_JSON"]}
            overall_payload.append(res)
            all_ok = False
            continue
        finally:
            try:
                child_output.unlink(missing_ok=True)
            except Exception:
                pass

        identity_errors = _validate_child_result(
            res, name, domain_str, run_id, completed_returncode, expected_child_identity=child_identity
        )
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
    parser.add_argument("--run-id", dest="run_id", help=argparse.SUPPRESS)
    parser.add_argument("--lease-dir", dest="lease_dir", help=argparse.SUPPRESS)
    parser.add_argument("--lease-token", dest="lease_token", help=argparse.SUPPRESS)
    parser.add_argument(
        "--lease-max-age-s", dest="lease_max_age_s", type=float,
        default=DEFAULT_LEASE_MAX_AGE_S, help=argparse.SUPPRESS,
    )
    parser.add_argument("--expected-parent-pid", dest="expected_parent_pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-ppid", dest="expected_parent_ppid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-pgid", dest="expected_parent_pgid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-sid", dest="expected_parent_sid", type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        "--expected-parent-start-ticks", dest="expected_parent_start_ticks", type=int, help=argparse.SUPPRESS
    )
    parser.add_argument("--expected-parent-uid", dest="expected_parent_uid", type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        "--fault-inject-hang-sandbox", dest="fault_inject_hang_sandbox",
        action="store_true", help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.scenario:
        return _scenario_main(args)
    return _parent_main(args)


if __name__ == "__main__":
    sys.exit(main())
