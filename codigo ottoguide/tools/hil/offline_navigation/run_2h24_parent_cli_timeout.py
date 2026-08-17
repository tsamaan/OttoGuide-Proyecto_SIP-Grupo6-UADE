#!/usr/bin/env python3
"""Fase 2H.2.4 -- end-to-end evidence driver for the *real parent CLI*
timeout path of smoke_test_main_runtime_navigation_selection.py.

Why this file exists
--------------------
The Fase 2H.2.3 driver (run_2h23_evidence_matrix.py) proved
``_parent_timeout_cleanup`` itself end-to-end, but it did so by *importing*
the smoke test module and calling that function directly. The genuine
production entrypoint -- ``main()`` -> ``_parent_main()`` ->
``child_proc.communicate(timeout=...)`` -> ``except
subprocess.TimeoutExpired`` -> ``_parent_timeout_cleanup`` -> JSON printed
to stdout -> process exit code -- was never actually driven as a real CLI
invocation. This driver closes that remaining gap: it shells out to the
smoke test script exactly as a human/CI invocation would, observes its
stdout/exit code, and only then inspects the cleanup evidence it printed.

Fault injection (strictly guarded, off by default)
----------------------------------------------------
The smoke test child the CLI spawns internally never touches ROS in this
mode: smoke_test_main_runtime_navigation_selection.py's own hidden
``--fault-inject-hang-sandbox`` flag (gated by
``OTTOGUIDE_2H24_FAULT_INJECTION=1``, see that module) swaps the real ROS
sandbox launch for an inert, isolated stand-in and blocks instead of
running the ROS-dependent scenario body -- so the *parent* (running inside
that same CLI subprocess) genuinely times out waiting for it. This driver
only sets that env var for the CLI subprocess it spawns; without it, the
smoke test refuses fault injection on its own (fail-closed) regardless of
what this driver does.

Offline only. POSIX only (/proc, setsid, killpg). On non-POSIX it exits
with a clear UNSUPPORTED_PLATFORM decision and a non-zero code.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
TOOLS_DIR = THIS_FILE.parent
SMOKE_TEST_PATH = TOOLS_DIR / "smoke_test_main_runtime_navigation_selection.py"

FAULT_INJECTION_ENV = "OTTOGUIDE_2H24_FAULT_INJECTION"
FAULT_MARGIN_ENV = "OTTOGUIDE_2H24_FAULT_TIMEOUT_MARGIN_S"
# §22 timeout-E2E band for the 2H.2.4 *CLI-level* driver -- distinct from
# every band already used by 2H.2.3 (function-level fault injection:
# 104-107; runtime-stability diagnostic + 3 reruns: 112-115, 120-123,
# 128-131, 136-139) and from the runtime-stability bands this phase's own
# smoke-test reruns use (184-211). This driver never starts real ROS
# (fault injection never launches the sandbox wrapper), so reusing a
# number could never cause an actual DDS collision -- kept distinct
# anyway, purely for bookkeeping clarity. Never 0; comfortably inside
# 1..232.
DEFAULT_DOMAIN_ID = "220"
CHILD_TIMEOUT_S = 1.0
FAULT_MARGIN_S = 2.0
# Upper bound the *driver* will wait for the whole CLI invocation (covers
# all four SCENARIOS, each forced to time out) before treating it as a
# driver-level anomaly distinct from the expected per-scenario timeout.
CLI_WAIT_BUDGET_S = 120.0
SENTINEL_SLEEP_S = 180


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


def _spawn_sentinel() -> "tuple[subprocess.Popen, smoke.ProcessIdentity]":
    """An unrelated, inert process in its own session/PGID. It must never be
    signalled by any cleanup performed inside the CLI subprocess (which only
    ever targets the *CLI's own* child/sandbox groups), and is reaped here
    by its own owner in finally()."""
    return smoke.spawn_isolated([sys.executable, "-c", f"import time; time.sleep({SENTINEL_SLEEP_S})"])


def _reap_sentinel(proc: "subprocess.Popen", identity: "smoke.ProcessIdentity") -> None:
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


def _emit(result: dict, output: "Path | None") -> None:
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(payload, end="")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")


def _driver(args: argparse.Namespace) -> int:
    result: dict = {
        "schema_version": 1,
        "scenario": "parent_cli_fault_injection_timeout",
        "domain_id": args.domain_id,
        "cleanup_decision": "FAIL",
        "scenario_decision": "UNKNOWN",
        "ok": False,
        "fault_injection_guard": {
            "env_var": FAULT_INJECTION_ENV,
            "required_for_stall": True,
            "set_for_this_run": os.environ.get(FAULT_INJECTION_ENV) == "1",
        },
        "errors": [],
        "sentinel": {},
        "parent_cli_exit_code": None,
        "parent_cli_decision": None,
        "scenarios": [],
        "zombies_remaining": None,
        "orphans_remaining": None,
    }

    if not _is_posix():
        result["cleanup_decision"] = "UNSUPPORTED_PLATFORM"
        result["errors"].append("REQUIRES_POSIX_PROC_KILLPG")
        _emit(result, args.output)
        return 2

    if os.environ.get(FAULT_INJECTION_ENV) != "1":
        result["errors"].append("FAULT_INJECTION_NOT_AUTHORIZED")
        _emit(result, args.output)
        return 2

    sentinel_proc = sentinel_identity = None
    try:
        sentinel_proc, sentinel_identity = _spawn_sentinel()
        result["sentinel"] = {
            "pid": sentinel_identity.pid,
            "pgid": sentinel_identity.pgid,
            "sid": sentinel_identity.sid,
            "alive_before": smoke.identity_still_valid(sentinel_identity),
        }

        env = os.environ.copy()
        env["ROS_LOCALHOST_ONLY"] = "1"
        env["ROS_DOMAIN_ID"] = args.domain_id
        env[FAULT_INJECTION_ENV] = "1"
        env[FAULT_MARGIN_ENV] = str(args.fault_margin_s)

        cli_cmd = [
            sys.executable, str(SMOKE_TEST_PATH),
            "--base-domain-id", args.domain_id,
            "--timeout", str(args.child_timeout_s),
            "--fault-inject-hang-sandbox",
        ]
        cli_proc, _cli_identity = smoke.spawn_isolated(
            cli_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            cli_stdout, cli_stderr = cli_proc.communicate(timeout=CLI_WAIT_BUDGET_S)
        except subprocess.TimeoutExpired:
            result["errors"].append("PARENT_CLI_DRIVER_LEVEL_TIMEOUT")
            cli_proc.kill()
            cli_stdout, cli_stderr = cli_proc.communicate(timeout=10.0)

        result["parent_cli_exit_code"] = cli_proc.returncode
        result["parent_cli_stderr_tail"] = cli_stderr[-2000:] if cli_stderr else ""

        try:
            cli_payload = json.loads(cli_stdout)
        except (json.JSONDecodeError, TypeError):
            result["errors"].append("PARENT_CLI_OUTPUT_NOT_JSON")
            cli_payload = {}

        result["parent_cli_decision"] = cli_payload.get("decision")
        scenarios = cli_payload.get("scenarios", [])
        result["scenarios"] = scenarios

        if not scenarios:
            result["errors"].append("PARENT_CLI_NO_SCENARIOS_REPORTED")

        signalled_pgids: set = set()
        all_cleanup_ok = bool(scenarios)
        all_timed_out = bool(scenarios)
        for sc in scenarios:
            if not sc.get("parent_timeout_cleanup_executed"):
                all_cleanup_ok = False
                continue
            evidence = sc.get("parent_timeout_cleanup_evidence") or {}
            for attempt in evidence.get("signal_attempts", []):
                pgid = attempt.get("pgid")
                if pgid is not None:
                    signalled_pgids.add(pgid)
            scenario_ok = (
                evidence.get("executed") is True
                and evidence.get("lease_validation", {}).get("ok") is True
                and evidence.get("child_identity_validation", {}).get("ok") is True
                and evidence.get("child_reaped") is True
                and evidence.get("child_group_alive_after") is False
                and evidence.get("sandbox_group_alive_after") is False
                and evidence.get("owned_members_remaining") == []
            )
            if not scenario_ok:
                all_cleanup_ok = False
            if "CHILD_PROCESS_TIMEOUT" not in sc.get("errors", []):
                all_timed_out = False

        result["scenario_decision"] = "EXPECTED_TIMEOUT" if all_timed_out else "UNEXPECTED"
        if not all_timed_out:
            result["errors"].append("NOT_ALL_SCENARIOS_REPORTED_EXPECTED_TIMEOUT")

        sentinel_alive_after = smoke.identity_still_valid(sentinel_identity)
        sentinel_signalled = sentinel_identity.pgid in signalled_pgids
        result["sentinel"].update({
            "alive_after": sentinel_alive_after,
            "signalled": sentinel_signalled,
        })

        zombies = smoke._collect_zombie_children(os.getpid())
        result["zombies_remaining"] = len(zombies)
        result["zombie_pids"] = zombies

        cleanup_ok = (
            all_cleanup_ok
            and result["parent_cli_exit_code"] is not None
            and result["parent_cli_exit_code"] != 0
            and sentinel_alive_after is True
            and sentinel_signalled is False
            and len(zombies) == 0
            and "PARENT_CLI_DRIVER_LEVEL_TIMEOUT" not in result["errors"]
            and "PARENT_CLI_OUTPUT_NOT_JSON" not in result["errors"]
            and "PARENT_CLI_NO_SCENARIOS_REPORTED" not in result["errors"]
        )
        result["cleanup_decision"] = "PASS" if cleanup_ok else "FAIL"
        result["ok"] = bool(cleanup_ok)
        if not cleanup_ok and not result["errors"]:
            result["errors"].append("ACCEPTANCE_SET_NOT_FULLY_SATISFIED")

    finally:
        if sentinel_proc is not None and sentinel_identity is not None:
            _reap_sentinel(sentinel_proc, sentinel_identity)
            result["sentinel"]["reaped"] = sentinel_proc.poll() is not None

    _emit(result, args.output)
    return 0 if result.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain-id", dest="domain_id", default=DEFAULT_DOMAIN_ID)
    parser.add_argument("--child-timeout-s", dest="child_timeout_s", type=float, default=CHILD_TIMEOUT_S)
    parser.add_argument("--fault-margin-s", dest="fault_margin_s", type=float, default=FAULT_MARGIN_S)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    return _driver(args)


if __name__ == "__main__":
    sys.exit(main())
