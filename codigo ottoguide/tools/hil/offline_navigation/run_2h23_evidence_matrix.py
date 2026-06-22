#!/usr/bin/env python3
"""Fase 2H.2.3 -- end-to-end evidence driver for the *parent timeout cleanup*
path of smoke_test_main_runtime_navigation_selection.py.

Why this file exists
--------------------
Every one of the eight 2H.2.2 official/diagnostic runs reported
``parent_timeout_cleanup_executed = false``: the child always finished long
before the parent's ``communicate(timeout=...)`` could expire, so the
parent's ``_parent_timeout_cleanup`` -- the very code that re-validates the
lease, re-validates kernel identities and escalates SIGINT->SIGTERM->SIGKILL
to the sandbox and child groups during a timeout -- was never actually
exercised at runtime. That left the timeout branch proven only by unit
tests, never by a real process tree.

This driver closes that gap *without modifying any application code and
without modifying the production smoke test*. It imports the smoke test's
real primitives (``CleanupLease``, ``spawn_isolated``,
``_parent_timeout_cleanup``, ``read_process_identity``, ...) and drives the
genuine production timeout transition (``subprocess.TimeoutExpired`` ->
``_parent_timeout_cleanup``) against a real, isolated process tree, then
records the full §16.3 evidence set.

Fault injection (strictly guarded, off by default)
--------------------------------------------------
The injected "child" is a self re-invocation of THIS driver in
``--fault-child`` mode. It only stalls if ``OTTOGUIDE_2H23_FAULT_INJECTION=1``
is present in its environment; without that variable it refuses to stall and
exits non-zero immediately. The stall is reached *only after* the child has:
created/validated the lease, written its own kernel identity into the lease,
spawned a real isolated sandbox process group, and written the sandbox's
kernel identity into the lease -- i.e. only once the lease carries usable
identities the parent can validate and act on (§16.2). No new sockets, no
ROS bring-up, no hardware, no external network: the "sandbox" is an inert
sleeper whose only job is to be a real, distinct, isolated process group for
the escalation logic to target.

Offline only. POSIX only (/proc, setsid, killpg). On non-POSIX it exits with
a clear UNSUPPORTED_PLATFORM decision and a non-zero code.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
TOOLS_DIR = THIS_FILE.parent
SMOKE_TEST_PATH = TOOLS_DIR / "smoke_test_main_runtime_navigation_selection.py"

FAULT_INJECTION_ENV = "OTTOGUIDE_2H23_FAULT_INJECTION"
DEFAULT_DOMAIN_ID = "104"  # §17 timeout-E2E band 104-107; never 0.
SCENARIO_NAME = "fault_injection_timeout"

# Bringup deadline: how long the parent waits for the child to populate the
# lease with usable child + sandbox identities before it is willing to force
# the timeout. Never force a timeout before identities are usable (§16.2).
BRINGUP_DEADLINE_S = 30.0
# Once bringup is confirmed, the parent forces the production timeout branch
# with a deliberately short communicate() window.
PARENT_FORCE_TIMEOUT_S = 5.0
# How long the injected child sleeps once stalled (must outlast the whole
# parent escalation comfortably so the *parent*, never the child's own exit,
# is what tears the tree down).
CHILD_STALL_S = 600
SANDBOX_SLEEP_S = 600
SENTINEL_SLEEP_S = 900


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "smoke_test_main_runtime_navigation_selection", SMOKE_TEST_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


def _is_posix() -> bool:
    return os.name == "posix" and Path("/proc").is_dir()


# ---------------------------------------------------------------------------
# Injected child (self re-invocation, guarded)
# ---------------------------------------------------------------------------


def _fault_child(args: argparse.Namespace) -> int:
    """Runs ONLY when re-invoked with --fault-child. Refuses to stall unless
    the explicit fault-injection env var is set (§16.1)."""
    if os.environ.get(FAULT_INJECTION_ENV) != "1":
        sys.stderr.write(
            "FAULT_INJECTION_NOT_AUTHORIZED: "
            f"{FAULT_INJECTION_ENV}=1 required; refusing to stall.\n"
        )
        return 3

    expected_parent = smoke.ProcessIdentity(
        pid=args.expected_parent_pid,
        ppid=args.expected_parent_ppid,
        pgid=args.expected_parent_pgid,
        sid=args.expected_parent_sid,
        start_ticks=args.expected_parent_start_ticks,
        uid=args.expected_parent_uid,
    )

    own_identity = smoke.read_process_identity(os.getpid())
    if own_identity is None:
        sys.stderr.write("CHILD_IDENTITY_UNAVAILABLE\n")
        return 4

    lease = smoke.CleanupLease.open_existing(Path(args.lease_dir))
    data = lease.read()
    lease_errors = smoke.validate_lease_immutable_fields(
        data, args.run_id, SCENARIO_NAME, args.domain_id,
        expected_parent=expected_parent, expected_token=args.lease_token,
    )
    if lease_errors:
        sys.stderr.write(f"LEASE_VALIDATION_FAILED:{lease_errors}\n")
        return 5

    # 1) child identity written into the lease
    lease.update_child_identity(own_identity)

    # 2) spawn a real, isolated, inert sandbox process group (no ROS, no
    #    sockets) -- its only purpose is to be a distinct group the parent's
    #    escalation logic can target via the lease.
    sandbox_proc, sandbox_identity = smoke.spawn_isolated(
        [sys.executable, "-c", f"import time; time.sleep({SANDBOX_SLEEP_S})"]
    )
    if sandbox_identity.pgid == own_identity.pgid or sandbox_identity.sid == own_identity.sid:
        sys.stderr.write("SANDBOX_GROUP_NOT_DISTINCT_FROM_CHILD\n")
        return 6

    # 3) sandbox identity written into the lease
    lease.update_sandbox_identity(sandbox_identity)

    # 4) stall well past the parent's controlled timeout. A bare time.sleep
    #    keeps the default SIGINT disposition, so the parent's first SIGINT
    #    tears this child down cleanly -- we are proving the parent acts, not
    #    that the child resists.
    sys.stderr.write("FAULT_CHILD_STALLING\n")
    sys.stderr.flush()
    time.sleep(CHILD_STALL_S)
    return 0


# ---------------------------------------------------------------------------
# Parent / driver (the actual timeout-E2E)
# ---------------------------------------------------------------------------


def _wait_lease_populated(lease: "smoke.CleanupLease", deadline: float) -> "tuple[bool, dict]":
    """Polls the lease until both child and sandbox identities are populated
    and individually kernel-valid, or until `deadline`. Returns
    (ok, last_data)."""
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = lease.read()
        except smoke.LeaseError:
            time.sleep(0.2)
            continue
        child_ok = not smoke.validate_lease_identity_field(last, "child")
        sandbox_ok = not smoke.validate_lease_identity_field(last, "sandbox")
        if child_ok and sandbox_ok:
            return True, last
        time.sleep(0.2)
    return False, last


def _spawn_sentinel() -> "tuple[subprocess.Popen, smoke.ProcessIdentity]":
    """An unrelated, inert process in its own session/PGID. It must never be
    signalled by the cleanup (which only targets the sandbox/child groups),
    and is reaped here by its own owner in finally()."""
    return smoke.spawn_isolated(
        [sys.executable, "-c", f"import time; time.sleep({SENTINEL_SLEEP_S})"]
    )


def _reap_sentinel(proc: "subprocess.Popen", identity: "smoke.ProcessIdentity") -> None:
    """Terminate + reap the sentinel by its own owner. Targets only the
    sentinel's own validated group."""
    try:
        if smoke.identity_still_valid(identity) and not smoke.is_protected_id(identity.pgid):
            try:
                os.killpg(identity.pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            time.sleep(0.3)
            if smoke._pgid_alive(identity.pgid):
                try:
                    os.killpg(identity.pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
    finally:
        try:
            proc.wait(timeout=5.0)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5.0)
            except Exception:
                pass


def _driver(args: argparse.Namespace) -> int:
    result: dict = {
        "schema_version": 1,
        "scenario": SCENARIO_NAME,
        "domain_id": args.domain_id,
        "decision": "FAIL",
        "ok": False,
        "fault_injection_guard": {
            "env_var": FAULT_INJECTION_ENV,
            "required_for_stall": True,
            "set_for_this_run": os.environ.get(FAULT_INJECTION_ENV) == "1",
        },
        "parent_timeout_cleanup_executed": False,
        "errors": [],
        "sentinel": {},
        "cleanup_evidence": None,
    }

    if not _is_posix():
        result["decision"] = "UNSUPPORTED_PLATFORM"
        result["errors"].append("REQUIRES_POSIX_PROC_KILLPG")
        _emit(result, args.output)
        return 2

    if os.environ.get(FAULT_INJECTION_ENV) != "1":
        result["errors"].append("FAULT_INJECTION_NOT_AUTHORIZED")
        _emit(result, args.output)
        return 2

    parent_identity = smoke.read_process_identity(os.getpid())
    if parent_identity is None:
        result["errors"].append("PARENT_IDENTITY_UNAVAILABLE")
        _emit(result, args.output)
        return 2

    run_id = smoke_token()
    sentinel_proc = sentinel_identity = None
    lease = lease_token = lease_dir = None
    child_proc = child_identity = None

    try:
        # Unrelated sentinel, spawned BEFORE the timeout so we can prove it
        # survives a cleanup that never targets its group.
        sentinel_proc, sentinel_identity = _spawn_sentinel()
        result["sentinel"] = {
            "pid": sentinel_identity.pid,
            "pgid": sentinel_identity.pgid,
            "sid": sentinel_identity.sid,
            "alive_before_timeout": smoke.identity_still_valid(sentinel_identity),
            "start_ticks": sentinel_identity.start_ticks,
        }

        lease, lease_token = smoke.CleanupLease.create(
            Path(tempfile.gettempdir()), run_id, SCENARIO_NAME, args.domain_id, parent_identity,
        )
        lease_dir = lease.lease_dir

        env = os.environ.copy()
        env["ROS_LOCALHOST_ONLY"] = "1"
        env["ROS_DOMAIN_ID"] = args.domain_id
        env[FAULT_INJECTION_ENV] = "1"

        child_cmd = [
            sys.executable, str(THIS_FILE), "--fault-child",
            "--run-id", run_id,
            "--domain-id", args.domain_id,
            "--lease-dir", str(lease_dir),
            "--lease-token", lease_token,
            "--expected-parent-pid", str(parent_identity.pid),
            "--expected-parent-ppid", str(parent_identity.ppid),
            "--expected-parent-pgid", str(parent_identity.pgid),
            "--expected-parent-sid", str(parent_identity.sid),
            "--expected-parent-start-ticks", str(parent_identity.start_ticks),
            "--expected-parent-uid", str(parent_identity.uid),
        ]
        child_proc, child_identity = smoke.spawn_isolated(
            child_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        # §16.2: do NOT force the timeout before the lease carries usable
        # child + sandbox identities.
        populated, lease_data = _wait_lease_populated(
            lease, time.monotonic() + BRINGUP_DEADLINE_S
        )
        result["lease_populated_before_timeout"] = populated
        if not populated:
            result["errors"].append("CHILD_DID_NOT_REACH_SANDBOX_REGISTERED")
            # Still attempt cleanup so we never leak the tree.
            raise _BringupTimeout()

        result["sandbox_registered_identity"] = lease_data.get("sandbox")
        result["child_registered_identity"] = lease_data.get("child")

        # Force the genuine production timeout branch.
        try:
            child_proc.communicate(timeout=PARENT_FORCE_TIMEOUT_S)
            # Child exited on its own before the timeout -- fault injection
            # did not hold; this run cannot prove the timeout path.
            result["errors"].append("CHILD_EXITED_BEFORE_TIMEOUT")
            raise _BringupTimeout()
        except subprocess.TimeoutExpired:
            pass

        # The real production cleanup, against the real tree.
        cleanup = smoke._parent_timeout_cleanup(
            child_proc, child_identity, run_id, SCENARIO_NAME, args.domain_id,
            lease_dir, parent_identity, smoke.DEFAULT_LEASE_MAX_AGE_S, lease_token,
        )
        result["parent_timeout_cleanup_executed"] = True
        result["cleanup_evidence"] = cleanup

        # Sentinel must be untouched: still alive, identity unchanged, and no
        # signal attempt in the evidence ever named its group.
        sentinel_alive_after = smoke.identity_still_valid(sentinel_identity)
        signalled_pgids = {a.get("pgid") for a in cleanup.get("signal_attempts", [])}
        sentinel_signalled = sentinel_identity.pgid in signalled_pgids
        result["sentinel"].update({
            "alive_after_timeout": sentinel_alive_after,
            "received_signal": sentinel_signalled,
            "identity_unchanged": sentinel_alive_after,
        })

        # Zombie / orphan accounting for the driver's own direct children.
        zombies = smoke._collect_zombie_children(os.getpid())
        result["zombies_remaining"] = len(zombies)
        result["zombie_pids"] = zombies

        # Compose the §16.3 acceptance set.
        ok = (
            cleanup.get("executed") is True
            and cleanup.get("lease_validation", {}).get("ok") is True
            and cleanup.get("child_identity_validation", {}).get("ok") is True
            and cleanup.get("child_reaped") is True
            and cleanup.get("child_group_alive_after") is False
            and cleanup.get("sandbox_group_alive_after") is False
            and cleanup.get("owned_members_remaining") == []
            and len(zombies) == 0
            and sentinel_alive_after is True
            and sentinel_signalled is False
        )
        result["ok"] = bool(ok)
        result["decision"] = "PASS" if ok else "FAIL"
        if not ok:
            result["errors"].append("ACCEPTANCE_SET_NOT_FULLY_SATISFIED")

    except _BringupTimeout:
        # Cleanup still runs so the tree never leaks.
        if child_proc is not None and child_identity is not None:
            try:
                cleanup = smoke._parent_timeout_cleanup(
                    child_proc, child_identity, run_id, SCENARIO_NAME, args.domain_id,
                    lease_dir, parent_identity, smoke.DEFAULT_LEASE_MAX_AGE_S, lease_token,
                )
                result["cleanup_evidence"] = cleanup
                result["parent_timeout_cleanup_executed"] = True
            except Exception as exc:  # noqa: BLE001 - record, never swallow silently
                result["errors"].append(f"CLEANUP_AFTER_BRINGUP_TIMEOUT_FAILED:{exc}")
    finally:
        # Defensive: ensure child reaped even if cleanup did not.
        if child_proc is not None:
            try:
                if child_proc.poll() is None:
                    child_proc.kill()
                child_proc.wait(timeout=5.0)
            except Exception:
                pass
        # Reap the sentinel by its own owner.
        if sentinel_proc is not None and sentinel_identity is not None:
            _reap_sentinel(sentinel_proc, sentinel_identity)
            result["sentinel"]["reaped"] = sentinel_proc.poll() is not None
        # Destroy the lease directory we created.
        if lease is not None:
            try:
                lease.destroy()
            except Exception:
                pass

    _emit(result, args.output)
    return 0 if result.get("ok") else 1


class _BringupTimeout(Exception):
    pass


def smoke_token() -> str:
    import secrets
    return secrets.token_hex(16)


def _emit(result: dict, output: "Path | None") -> None:
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(payload, end="")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--domain-id", default=DEFAULT_DOMAIN_ID)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id", dest="run_id", help=argparse.SUPPRESS)
    parser.add_argument("--lease-dir", dest="lease_dir", help=argparse.SUPPRESS)
    parser.add_argument("--lease-token", dest="lease_token", help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-pid", type=int, dest="expected_parent_pid", help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-ppid", type=int, dest="expected_parent_ppid", help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-pgid", type=int, dest="expected_parent_pgid", help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-sid", type=int, dest="expected_parent_sid", help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-start-ticks", type=int, dest="expected_parent_start_ticks", help=argparse.SUPPRESS)
    parser.add_argument("--expected-parent-uid", type=int, dest="expected_parent_uid", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.fault_child:
        return _fault_child(args)
    return _driver(args)


if __name__ == "__main__":
    sys.exit(main())
