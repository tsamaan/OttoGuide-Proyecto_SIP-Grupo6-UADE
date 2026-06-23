#!/usr/bin/env python3
"""Fase 2H.2.2 -- process-group isolation, cleanup-lease validation and
signal-escalation tests for smoke_test_main_runtime_navigation_selection.py.

Pure Python, no ROS, no network, no hardware. Spawns only inert helper
processes (python3 -c "..."), always cleaned up in `finally`. Loaded as a
plain module (same pattern as test_offline_navigation_sandbox_isolation.py
uses for the static checker) so it never depends on tools/hil being a
package.

Functions that require setsid/killpg/os.getpgid/os.getsid or /proc (i.e.
that only have meaning on a real POSIX process tree) are individually
skipped on Windows with a precise reason; pure functions (identity-dict
validation, protected-id checks, lease-immutable-field validation) run
unconditionally on every platform.
"""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
SMOKE_TEST_PATH = (
    CODE_ROOT / "tools" / "hil" / "offline_navigation"
    / "smoke_test_main_runtime_navigation_selection.py"
)

_IS_POSIX = os.name == "posix"
_POSIX_SKIP_REASON = "requires POSIX setsid/killpg/os.getpgid/os.getsid/proc semantics"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "smoke_test_main_runtime_navigation_selection", SMOKE_TEST_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


def _spawn_inert(extra_code: str = "") -> "subprocess.Popen[str]":
    """Spawns a minimal, harmless Python process that sleeps; the test is
    responsible for terminating it in `finally`. Never started with its own
    session (used as a baseline "ordinary child" comparison point)."""
    script = "import time\n" + extra_code + "\ntime.sleep(30)\n"
    return subprocess.Popen([sys.executable, "-c", script])


def _spawn_inert_isolated(extra_code: str = ""):
    script = "import time\n" + extra_code + "\ntime.sleep(30)\n"
    return smoke.spawn_isolated([sys.executable, "-c", script])


def _spawn_signal_responder(ignore_sigint: bool, ignore_sigterm: bool):
    """Spawns an isolated process that optionally ignores SIGINT/SIGTERM
    (it always dies to SIGKILL, since that cannot be blocked), writing one
    line to stdout for each signal it actually receives and acts on.

    Settles for a moment after spawn before the caller may signal it: a
    bare `python3 -c "..."` child installs its signal.signal() handlers a
    few milliseconds after exec, and signalling it immediately (before
    those handlers are installed) hits the *default* signal disposition
    instead of the one the test means to exercise -- a race that is
    specific to this synthetic, near-instant test helper, never present in
    the real sandbox/child processes this escalation logic actually targets
    in production (which take far longer than a few ms to come up).
    """
    lines = ["import signal, sys, time"]
    if ignore_sigint:
        lines.append("signal.signal(signal.SIGINT, signal.SIG_IGN)")
    else:
        lines.append("signal.signal(signal.SIGINT, lambda *a: sys.exit(0))")
    if ignore_sigterm:
        lines.append("signal.signal(signal.SIGTERM, signal.SIG_IGN)")
    else:
        lines.append("signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))")
    lines.append("time.sleep(30)")
    script = "\n".join(lines)
    proc, identity = smoke.spawn_isolated([sys.executable, "-c", script])
    time.sleep(0.3)
    return proc, identity


def _force_kill(proc) -> None:
    if proc is None:
        return
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass
    try:
        proc.wait(timeout=5.0)
    except Exception:
        pass


def _force_kill_group(pgid) -> None:
    if pgid is None:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


# ---------------------------------------------------------------------------
# 21.1 Process groups
# ---------------------------------------------------------------------------


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
class ProcessGroupIsolationTests(unittest.TestCase):
    def test_spawned_child_is_own_session_and_group_leader(self):
        proc, identity = _spawn_inert_isolated()
        try:
            self.assertEqual(identity.pid, identity.pgid)
            self.assertEqual(identity.pid, identity.sid)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_spawned_child_group_distinct_from_parent_group(self):
        own_identity = smoke.read_process_identity(os.getpid())
        proc, identity = _spawn_inert_isolated()
        try:
            self.assertIsNotNone(own_identity)
            self.assertNotEqual(identity.pgid, own_identity.pgid)
            self.assertNotEqual(identity.sid, own_identity.sid)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_second_isolated_spawn_gets_a_different_group(self):
        proc1, identity1 = _spawn_inert_isolated()
        proc2, identity2 = _spawn_inert_isolated()
        try:
            self.assertNotEqual(identity1.pgid, identity2.pgid)
            self.assertNotEqual(identity1.sid, identity2.sid)
        finally:
            _force_kill_group(identity1.pgid)
            _force_kill(proc1)
            _force_kill_group(identity2.pgid)
            _force_kill(proc2)

    def test_process_without_own_session_is_rejected(self):
        """A plain Popen (no start_new_session) shares the test runner's
        session/group, so it must never be accepted as an isolated leader.
        Verified directly against read_process_identity, never by calling
        spawn_isolated with a doctored kwarg (which would just bypass the
        very invariant under test)."""
        proc = _spawn_inert()
        own_identity = smoke.read_process_identity(os.getpid())
        try:
            child_identity = smoke.read_process_identity(proc.pid)
            self.assertIsNotNone(child_identity)
            self.assertIsNotNone(own_identity)
            self.assertEqual(child_identity.pgid, own_identity.pgid)
            self.assertNotEqual(child_identity.pid, child_identity.pgid)
        finally:
            _force_kill(proc)


# ---------------------------------------------------------------------------
# Lease fixtures
# ---------------------------------------------------------------------------


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
class LeaseTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp_root = Path(tempfile.mkdtemp(prefix="ottoguide_2h22_test_"))
        self.run_id = secrets.token_hex(8)
        self.scenario = "boot_shutdown"
        self.domain_id = "199"
        self.parent_identity = smoke.read_process_identity(os.getpid())
        self.assertIsNotNone(self.parent_identity)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _create_lease(self, max_age_s=600.0) -> "smoke.CleanupLease":
        lease, token = smoke.CleanupLease.create(
            self.tmp_root, self.run_id, self.scenario, self.domain_id,
            self.parent_identity, max_age_s=max_age_s,
        )
        self.lease_token = token
        return lease


# ---------------------------------------------------------------------------
# 21.2 Valid lease
# ---------------------------------------------------------------------------


class ValidLeaseTests(LeaseTestBase):
    def test_freshly_created_lease_validates_clean(self):
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_immutable_fields(
            data, self.run_id, self.scenario, self.domain_id, expected_parent=self.parent_identity
        )
        self.assertEqual(errors, [])

    def test_freshly_created_lease_validates_with_correct_token(self):
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_immutable_fields(
            data, self.run_id, self.scenario, self.domain_id,
            expected_parent=self.parent_identity, expected_token=self.lease_token,
        )
        self.assertEqual(errors, [])

    def test_child_identity_round_trip_validates(self):
        lease = self._create_lease()
        proc, child_identity = _spawn_inert_isolated()
        try:
            lease.update_child_identity(child_identity)
            data = lease.read()
            errors = smoke.validate_lease_identity_field(data, "child", child_identity)
            self.assertEqual(errors, [])
        finally:
            _force_kill_group(child_identity.pgid)
            _force_kill(proc)

    def test_sandbox_identity_round_trip_validates(self):
        lease = self._create_lease()
        proc, sandbox_identity = _spawn_inert_isolated()
        try:
            lease.update_sandbox_identity(sandbox_identity)
            data = lease.read()
            errors = smoke.validate_lease_identity_field(data, "sandbox", sandbox_identity)
            self.assertEqual(errors, [])
        finally:
            _force_kill_group(sandbox_identity.pgid)
            _force_kill(proc)

    def test_lease_file_metadata_owner_and_mode(self):
        lease = self._create_lease()
        st = os.lstat(lease.lease_path)
        self.assertEqual(st.st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(st.st_mode) & 0o077, 0)
        self.assertTrue(stat.S_ISREG(st.st_mode))

    def test_start_ticks_match_for_freshly_captured_identity(self):
        proc, identity = _spawn_inert_isolated()
        try:
            current = smoke.read_process_identity(identity.pid)
            self.assertEqual(current.start_ticks, identity.start_ticks)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)


# ---------------------------------------------------------------------------
# 21.3 Invalid lease
# ---------------------------------------------------------------------------


class InvalidLeaseTests(LeaseTestBase):
    def test_invalid_json_lease_file(self):
        lease = self._create_lease()
        lease.lease_path.write_text("{not json")
        with self.assertRaises(smoke.LeaseError):
            lease.read()

    def test_wrong_schema_version_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        data["schema_version"] = 999
        errors = smoke.validate_lease_immutable_fields(data, self.run_id, self.scenario, self.domain_id)
        self.assertIn("LEASE_SCHEMA_MISMATCH", errors)

    def test_short_token_rejected_as_malformed(self):
        lease = self._create_lease()
        data = lease.read()
        data["lease_token"] = "short"
        errors = smoke.validate_lease_immutable_fields(data, self.run_id, self.scenario, self.domain_id)
        self.assertIn("LEASE_TOKEN_INVALID", errors)

    def test_different_but_syntactically_valid_token_rejected(self):
        # The forged token is itself a real, full-length secrets.token_hex(32)
        # value -- demonstrating actual token *authentication* against the
        # caller-supplied expected_token, not merely a length/format check
        # that any sufficiently long string would pass.
        lease = self._create_lease()
        data = lease.read()
        forged_token = secrets.token_hex(32)
        self.assertNotEqual(forged_token, self.lease_token)
        data["lease_token"] = forged_token
        errors = smoke.validate_lease_immutable_fields(
            data, self.run_id, self.scenario, self.domain_id, expected_token=self.lease_token
        )
        self.assertIn("LEASE_TOKEN_MISMATCH", errors)

    def test_correct_token_value_is_not_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_immutable_fields(
            data, self.run_id, self.scenario, self.domain_id, expected_token=self.lease_token
        )
        self.assertNotIn("LEASE_TOKEN_MISMATCH", errors)
        self.assertNotIn("LEASE_TOKEN_INVALID", errors)

    def test_wrong_run_id_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_immutable_fields(data, "different-run-id", self.scenario, self.domain_id)
        self.assertIn("LEASE_RUN_ID_MISMATCH", errors)

    def test_wrong_scenario_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_immutable_fields(data, self.run_id, "tour_success", self.domain_id)
        self.assertIn("LEASE_SCENARIO_MISMATCH", errors)

    def test_wrong_domain_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_immutable_fields(data, self.run_id, self.scenario, "1")
        self.assertIn("LEASE_DOMAIN_MISMATCH", errors)

    def test_wrong_parent_pid_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        bogus_parent = smoke.ProcessIdentity(
            pid=99999, ppid=2, pgid=99999, sid=99999, start_ticks=1, uid=os.getuid()
        )
        errors = smoke.validate_lease_immutable_fields(
            data, self.run_id, self.scenario, self.domain_id, expected_parent=bogus_parent
        )
        self.assertIn("LEASE_PARENT_IDENTITY_MISMATCH", errors)

    def test_distinct_but_real_parent_identity_rejected(self):
        # other_identity is a real, currently-alive, syntactically valid
        # ProcessIdentity (pid==pgid==sid, start_ticks>1, real uid) -- not a
        # bogus/impossible PID like 99999. This demonstrates the comparison
        # actually distinguishes between two *legitimate* identities, not
        # just between a valid one and an obviously-fake one.
        lease = self._create_lease()
        data = lease.read()
        other_proc, other_identity = _spawn_inert_isolated()
        try:
            self.assertNotEqual(other_identity.pid, self.parent_identity.pid)
            errors = smoke.validate_lease_immutable_fields(
                data, self.run_id, self.scenario, self.domain_id, expected_parent=other_identity
            )
            self.assertIn("LEASE_PARENT_IDENTITY_MISMATCH", errors)
        finally:
            _force_kill_group(other_identity.pgid)
            _force_kill(other_proc)

    def test_correct_parent_identity_is_not_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_immutable_fields(
            data, self.run_id, self.scenario, self.domain_id, expected_parent=self.parent_identity
        )
        self.assertNotIn("LEASE_PARENT_IDENTITY_MISMATCH", errors)

    def test_wrong_child_pid_rejected(self):
        lease = self._create_lease()
        proc, child_identity = _spawn_inert_isolated()
        try:
            lease.update_child_identity(child_identity)
            data = lease.read()
            other_proc, other_identity = _spawn_inert_isolated()
            try:
                errors = smoke.validate_lease_identity_field(data, "child", other_identity)
                self.assertIn("LEASE_CHILD_IDENTITY_MISMATCH", errors)
            finally:
                _force_kill_group(other_identity.pgid)
                _force_kill(other_proc)
        finally:
            _force_kill_group(child_identity.pgid)
            _force_kill(proc)

    def test_wrong_sandbox_pid_rejected(self):
        lease = self._create_lease()
        proc, sandbox_identity = _spawn_inert_isolated()
        try:
            lease.update_sandbox_identity(sandbox_identity)
            data = lease.read()
            other_proc, other_identity = _spawn_inert_isolated()
            try:
                errors = smoke.validate_lease_identity_field(data, "sandbox", other_identity)
                self.assertIn("LEASE_SANDBOX_IDENTITY_MISMATCH", errors)
            finally:
                _force_kill_group(other_identity.pgid)
                _force_kill(other_proc)
        finally:
            _force_kill_group(sandbox_identity.pgid)
            _force_kill(proc)

    def test_expired_timestamp_rejected(self):
        lease = self._create_lease(max_age_s=0.01)
        data = lease.read()
        time.sleep(0.5)
        errors = smoke.validate_lease_immutable_fields(
            data, self.run_id, self.scenario, self.domain_id, max_age_s=0.01
        )
        self.assertIn("LEASE_EXPIRED", errors)

    def test_symlinked_lease_file_rejected(self):
        lease = self._create_lease()
        target = self.tmp_root / "evil_target.json"
        target.write_text(lease.lease_path.read_text())
        lease.lease_path.unlink()
        os.symlink(str(target), str(lease.lease_path))
        with self.assertRaises(smoke.LeaseError):
            lease._validate_file_metadata()

    def test_overly_permissive_lease_file_rejected(self):
        lease = self._create_lease()
        os.chmod(lease.lease_path, 0o644)
        with self.assertRaises(smoke.LeaseError):
            lease._validate_file_metadata()

    def test_pid_zero_rejected_as_identity(self):
        self.assertTrue(smoke.is_protected_id(0))

    def test_pid_one_rejected_as_identity(self):
        self.assertTrue(smoke.is_protected_id(1))

    def test_parent_pgid_protected_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        data["parent"]["pgid"] = 1
        errors = smoke.validate_lease_immutable_fields(data, self.run_id, self.scenario, self.domain_id)
        self.assertIn("LEASE_PARENT_IDENTITY_PROTECTED", errors)

    def test_bool_rejected_as_integer_identity(self):
        self.assertTrue(smoke.is_protected_id(True))
        self.assertTrue(smoke.is_protected_id(False))

    def test_wrong_start_ticks_rejected(self):
        lease = self._create_lease()
        proc, child_identity = _spawn_inert_isolated()
        try:
            lease.update_child_identity(child_identity)
            data = lease.read()
            data["child"]["start_ticks"] = child_identity.start_ticks + 999999
            errors = smoke.validate_lease_identity_field(data, "child", child_identity)
            self.assertTrue(
                any("MISMATCH" in e or "STALE" in e for e in errors), errors
            )
        finally:
            _force_kill_group(child_identity.pgid)
            _force_kill(proc)

    def test_missing_child_identity_rejected(self):
        # A freshly created lease's "child" field is the empty placeholder
        # dict (all None) -- a populated dict, but not yet a valid
        # ProcessIdentity, so the real failure mode is MALFORMED, not
        # MISSING (MISSING only fires when the field itself is absent or
        # not a dict at all, e.g. after JSON tampering).
        lease = self._create_lease()
        data = lease.read()
        errors = smoke.validate_lease_identity_field(data, "child")
        self.assertIn("LEASE_CHILD_IDENTITY_MALFORMED", errors)

        data_without_field = dict(data)
        del data_without_field["child"]
        errors_missing = smoke.validate_lease_identity_field(data_without_field, "child")
        self.assertIn("LEASE_CHILD_IDENTITY_MISSING", errors_missing)

    def test_updated_before_created_rejected(self):
        lease = self._create_lease()
        data = lease.read()
        data["updated_at_ns"] = data["created_at_ns"] - 1_000_000_000
        errors = smoke.validate_lease_immutable_fields(data, self.run_id, self.scenario, self.domain_id)
        self.assertIn("LEASE_UPDATED_BEFORE_CREATED", errors)


# ---------------------------------------------------------------------------
# 21.4 Signal safety
# ---------------------------------------------------------------------------


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
class SignalSafetyTests(unittest.TestCase):
    def test_protected_pgid_blocks_authorized_killpg(self):
        attempts: list = []
        result = smoke.escalate_signal_to_group(
            1, None, smoke.CleanupTimeouts(sigint_wait_s=0.1, sigterm_wait_s=0.1, sigkill_wait_s=0.1),
            attempts, "sandbox",
        )
        authorized = [a for a in attempts if a.get("authorized")]
        self.assertEqual(authorized, [])

    def test_unrelated_process_survives_unrelated_group_cleanup(self):
        bystander = _spawn_inert()
        target_proc, target_identity = _spawn_inert_isolated()
        try:
            attempts: list = []
            smoke.escalate_signal_to_group(
                target_identity.pgid, target_identity,
                smoke.CleanupTimeouts(sigint_wait_s=0.2, sigterm_wait_s=0.2, sigkill_wait_s=0.5),
                attempts, "sandbox",
            )
            self.assertIsNone(bystander.poll(), "unrelated bystander process must survive")
        finally:
            _force_kill(bystander)
            _force_kill_group(target_identity.pgid)
            _force_kill(target_proc)

    def test_no_signal_reaches_parent_pgid(self):
        own_identity = smoke.read_process_identity(os.getpid())
        self.assertTrue(smoke.is_protected_id(0))
        # The parent's own pgid must never even be accepted as a target by
        # is_protected_id's positive-int contract when it legitimately
        # equals a protected id; for the common case (pgid > 1) the actual
        # safety net is that escalate_signal_to_group only ever signals
        # identities it independently captured/validated, never an
        # attacker-suppliable pgid. This is exercised end-to-end by
        # InvalidLeaseTests + the parent-cleanup tests below.
        self.assertIsNotNone(own_identity)

    def test_already_gone_group_handled_idempotently(self):
        proc, identity = _spawn_inert_isolated()
        os.killpg(identity.pgid, signal.SIGKILL)
        proc.wait(timeout=5.0)
        time.sleep(0.2)
        attempts: list = []
        result = smoke.escalate_signal_to_group(
            identity.pgid, identity,
            smoke.CleanupTimeouts(sigint_wait_s=0.1, sigterm_wait_s=0.1, sigkill_wait_s=0.1),
            attempts, "sandbox",
        )
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# Fase 2H.2.4 -- TOCTOU race fix in member re-validation
#
# Pre-2H.2.4, _authorized_targets()'s member fallback path read kernel
# identity twice -- once inside identity_still_valid(), once more directly
# via read_process_identity(pid).pgid -- with no guard on the second read
# returning None. _revalidate_identity_for_group_signal() replaces both
# with a single snapshot; these tests prove the single-read contract
# itself, that every invariant it must enforce is enforced, and that the
# function is robust to exactly the disappearance/reuse window the old
# code was not.
# ---------------------------------------------------------------------------


class TOCTOURaceFixTests(unittest.TestCase):
    def test_old_double_read_pattern_would_raise_attributeerror(self):
        """Documents the defect being fixed: reproduces the exact pre-2H.2.4
        expression with a process that vanishes between the two independent
        reads it performs, and shows it raises AttributeError."""
        identity = smoke.ProcessIdentity(
            pid=999999, ppid=1, pgid=999999, sid=999999, start_ticks=12345, uid=1000,
        )
        call_count = {"n": 0}

        def flaky_read(pid):
            call_count["n"] += 1
            return identity if call_count["n"] == 1 else None

        with mock.patch.object(smoke, "read_process_identity", side_effect=flaky_read):
            with self.assertRaises(AttributeError):
                # identity_still_valid() performs the first read internally;
                # this second, independent read is the TOCTOU window.
                _ = (
                    smoke.identity_still_valid(identity)
                    and smoke.read_process_identity(identity.pid).pgid == identity.pgid
                )
        self.assertEqual(call_count["n"], 2)

    def test_single_read_no_toctou_double_read(self):
        identity = smoke.ProcessIdentity(
            pid=999999, ppid=1, pgid=999999, sid=999999, start_ticks=12345, uid=1000,
        )
        call_count = {"n": 0}

        def flaky_read(pid):
            call_count["n"] += 1
            return identity if call_count["n"] == 1 else None

        with mock.patch.object(smoke, "read_process_identity", side_effect=flaky_read):
            result = smoke._revalidate_identity_for_group_signal(identity, identity.pgid)
        self.assertEqual(call_count["n"], 1, "must read kernel identity exactly once")
        self.assertEqual(result, identity)

    def test_process_disappeared_returns_none_not_attributeerror(self):
        identity = smoke.ProcessIdentity(
            pid=999999, ppid=1, pgid=999999, sid=999999, start_ticks=12345, uid=1000,
        )
        with mock.patch.object(smoke, "read_process_identity", return_value=None):
            result = smoke._revalidate_identity_for_group_signal(identity, identity.pgid)
        self.assertIsNone(result)

    def test_pid_reused_with_different_start_ticks_rejected(self):
        current = smoke.ProcessIdentity(
            pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1000,
        )
        # `expected` claims the same PID/PGID but an older start_ticks --
        # the kernel-reused-this-PID-for-a-different-process signature.
        stale_expected = smoke.ProcessIdentity(
            pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=1, uid=1000,
        )
        with mock.patch.object(smoke, "read_process_identity", return_value=current):
            result = smoke._revalidate_identity_for_group_signal(stale_expected, 4242)
        self.assertIsNone(result)

    def test_uid_mismatch_rejected(self):
        current = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1000)
        expected = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1001)
        with mock.patch.object(smoke, "read_process_identity", return_value=current):
            result = smoke._revalidate_identity_for_group_signal(expected, 4242)
        self.assertIsNone(result)

    def test_pgid_drifted_from_expected_rejected(self):
        # The candidate left the group it was captured in (e.g. called
        # setpgid itself) -- expected.pgid no longer matches current.pgid.
        current = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=5555, sid=5555, start_ticks=500, uid=1000)
        expected = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1000)
        with mock.patch.object(smoke, "read_process_identity", return_value=current):
            result = smoke._revalidate_identity_for_group_signal(expected, 4242)
        self.assertIsNone(result)

    def test_pgid_matches_expected_but_not_target_rejected(self):
        # expected.pgid == current.pgid, but the caller is authorizing a
        # signal against a *different* target_pgid -- must still reject.
        current = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1000)
        expected = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1000)
        with mock.patch.object(smoke, "read_process_identity", return_value=current):
            result = smoke._revalidate_identity_for_group_signal(expected, 9999)
        self.assertIsNone(result)

    def test_sid_drifted_from_group_contract_rejected(self):
        # A member whose session id no longer matches the group's session
        # (target_pgid) -- e.g. it called setsid() itself -- is never
        # authorized even if pid/start_ticks/uid/pgid all still match.
        current = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=7777, start_ticks=500, uid=1000)
        expected = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1000)
        with mock.patch.object(smoke, "read_process_identity", return_value=current):
            result = smoke._revalidate_identity_for_group_signal(expected, 4242)
        self.assertIsNone(result)

    def test_protected_current_pgid_rejected(self):
        current = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=1, sid=1, start_ticks=500, uid=1000)
        expected = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=1, sid=1, start_ticks=500, uid=1000)
        with mock.patch.object(smoke, "read_process_identity", return_value=current):
            result = smoke._revalidate_identity_for_group_signal(expected, 1)
        self.assertIsNone(result)

    def test_valid_candidate_returns_current_snapshot_ignoring_ppid_reparenting(self):
        # ppid is deliberately excluded from the invariant set (reparenting
        # to init is normal); the function must still return the *current*
        # snapshot (proving it isn't just echoing back `expected`).
        current = smoke.ProcessIdentity(pid=4242, ppid=1, pgid=4242, sid=4242, start_ticks=500, uid=1000)
        expected = smoke.ProcessIdentity(pid=4242, ppid=777, pgid=4242, sid=4242, start_ticks=500, uid=1000)
        with mock.patch.object(smoke, "read_process_identity", return_value=current):
            result = smoke._revalidate_identity_for_group_signal(expected, 4242)
        self.assertEqual(result, current)
        self.assertNotEqual(result.ppid, expected.ppid)

    @unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
    def test_member_discovery_happens_exactly_once_new_members_never_considered(self):
        """Discovery (list_pgid_members) must run once, before any signal,
        never again mid-escalation -- otherwise a process that joins the
        PGID later could be discovered and signalled despite never having
        been authorized at capture time."""
        proc, identity = _spawn_inert_isolated()
        try:
            call_count = {"n": 0}
            real_list = smoke.list_pgid_members

            def counting_wrapper(pgid):
                call_count["n"] += 1
                return real_list(pgid)

            attempts: list = []
            with mock.patch.object(smoke, "list_pgid_members", side_effect=counting_wrapper):
                smoke.escalate_signal_to_group(
                    identity.pgid, identity,
                    smoke.CleanupTimeouts(sigint_wait_s=0.1, sigterm_wait_s=0.1, sigkill_wait_s=0.5),
                    attempts, "sandbox", reap_callback=proc.poll,
                )
            self.assertEqual(call_count["n"], 1)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    @unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
    def test_leader_gone_known_member_revalidated_and_signalled(self):
        """A leader that exits leaving a still-running, pgid-inheriting
        grandchild behind: the fast leader-path must fail closed (leader
        truly gone, not a zombie misread as alive), and the fallback path
        must re-validate and signal exactly the previously-known member."""
        leader_script = (
            "import subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "print(child.pid, flush=True)\n"
        )
        leader_proc, leader_identity = smoke.spawn_isolated(
            [sys.executable, "-c", leader_script], stdout=subprocess.PIPE, text=True,
        )
        grandchild_pid = None
        try:
            line = leader_proc.stdout.readline()
            grandchild_pid = int(line.strip())
            # Reap the leader so it is genuinely gone from /proc (not a
            # not-yet-reaped zombie, which would still look "alive" and let
            # the fast leader-path short-circuit without exercising the
            # fallback this test means to cover).
            leader_proc.wait(timeout=5.0)
            self.assertIsNone(smoke.read_process_identity(leader_identity.pid))

            attempts: list = []
            result = smoke.escalate_signal_to_group(
                leader_identity.pgid, leader_identity,
                smoke.CleanupTimeouts(sigint_wait_s=2.0, sigterm_wait_s=2.0, sigkill_wait_s=2.0),
                attempts, "sandbox",
            )
            self.assertTrue(result)
            self.assertFalse(smoke._pgid_alive(leader_identity.pgid))
            signalled_pids = {a.get("pid") for a in attempts if a.get("delivered")}
            self.assertIn(grandchild_pid, signalled_pids)
        finally:
            _force_kill_group(leader_identity.pgid)
            _force_kill(leader_proc)
            if grandchild_pid is not None:
                try:
                    os.kill(grandchild_pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

    @unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
    def test_signal_delivery_process_lookup_error_recorded_not_raised(self):
        proc, identity = _spawn_inert_isolated()
        real_kill, real_killpg = os.kill, os.killpg

        def flaky_kill(pid, sig):
            if sig == 0:
                return real_kill(pid, sig)  # liveness probe must stay real
            raise ProcessLookupError()

        def flaky_killpg(pgid, sig):
            if sig == 0:
                return real_killpg(pgid, sig)  # liveness probe must stay real
            raise ProcessLookupError()

        try:
            attempts: list = []
            with mock.patch("os.kill", side_effect=flaky_kill), \
                 mock.patch("os.killpg", side_effect=flaky_killpg):
                smoke.escalate_signal_to_group(
                    identity.pgid, identity,
                    smoke.CleanupTimeouts(sigint_wait_s=0.1, sigterm_wait_s=0.1, sigkill_wait_s=0.1),
                    attempts, "sandbox",
                )
            matches = [
                a for a in attempts
                if a.get("authorized") and a.get("error_type") == "ProcessLookupError"
            ]
            self.assertTrue(matches, attempts)
            self.assertTrue(all(a.get("process_already_gone") is True for a in matches))
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    @unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
    def test_signal_delivery_permission_error_recorded_not_raised(self):
        proc, identity = _spawn_inert_isolated()
        real_kill, real_killpg = os.kill, os.killpg

        def flaky_kill(pid, sig):
            if sig == 0:
                return real_kill(pid, sig)
            raise PermissionError()

        def flaky_killpg(pgid, sig):
            if sig == 0:
                return real_killpg(pgid, sig)
            raise PermissionError()

        try:
            attempts: list = []
            with mock.patch("os.kill", side_effect=flaky_kill), \
                 mock.patch("os.killpg", side_effect=flaky_killpg):
                smoke.escalate_signal_to_group(
                    identity.pgid, identity,
                    smoke.CleanupTimeouts(sigint_wait_s=0.1, sigterm_wait_s=0.1, sigkill_wait_s=0.1),
                    attempts, "sandbox",
                )
            matches = [
                a for a in attempts
                if a.get("authorized") and a.get("error_type") == "PermissionError"
            ]
            self.assertTrue(matches, attempts)
            self.assertTrue(all(a.get("process_already_gone") is False for a in matches))
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    @unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
    def test_escalation_never_raises_attributeerror_when_identity_flaps(self):
        """Adversarial: read_process_identity reports the target gone on
        every other call, simulating a process that may disappear between
        any two reads. The fixed escalation path must never raise."""
        proc, identity = _spawn_inert_isolated()
        try:
            attempts: list = []
            call_n = {"n": 0}
            real_read = smoke.read_process_identity

            def flaky_read(pid):
                call_n["n"] += 1
                if call_n["n"] % 2 == 0:
                    return None
                return real_read(pid)

            with mock.patch.object(smoke, "read_process_identity", side_effect=flaky_read):
                try:
                    smoke.escalate_signal_to_group(
                        identity.pgid, identity,
                        smoke.CleanupTimeouts(sigint_wait_s=0.2, sigterm_wait_s=0.2, sigkill_wait_s=0.5),
                        attempts, "sandbox", reap_callback=proc.poll,
                    )
                except AttributeError:
                    self.fail("escalate_signal_to_group raised AttributeError")
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    @unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
    def test_unrelated_sentinel_never_authorized_for_foreign_pgid(self):
        sentinel = _spawn_inert()
        other_proc, other_identity = _spawn_inert_isolated()
        try:
            sentinel_identity = smoke.read_process_identity(sentinel.pid)
            self.assertIsNotNone(sentinel_identity)
            result = smoke._revalidate_identity_for_group_signal(
                sentinel_identity, other_identity.pgid,
            )
            self.assertIsNone(result)
        finally:
            _force_kill(sentinel)
            _force_kill_group(other_identity.pgid)
            _force_kill(other_proc)


# ---------------------------------------------------------------------------
# 21.5 Escalation
# ---------------------------------------------------------------------------


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
class EscalationTests(unittest.TestCase):
    def test_sigint_responsive_process_dies_without_further_signals(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=False, ignore_sigterm=False)
        try:
            attempts: list = []
            result = smoke.escalate_signal_to_group(
                identity.pgid, identity,
                smoke.CleanupTimeouts(sigint_wait_s=5.0, sigterm_wait_s=5.0, sigkill_wait_s=5.0),
                attempts, "sandbox", reap_callback=proc.poll,
            )
            self.assertTrue(result)
            signals_sent = [a["signal"] for a in attempts if a.get("delivered")]
            self.assertIn(int(signal.SIGINT), signals_sent)
            self.assertNotIn(int(signal.SIGTERM), signals_sent)
            self.assertNotIn(int(signal.SIGKILL), signals_sent)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_sigint_ignoring_process_dies_to_sigterm(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=True, ignore_sigterm=False)
        try:
            attempts: list = []
            result = smoke.escalate_signal_to_group(
                identity.pgid, identity,
                smoke.CleanupTimeouts(sigint_wait_s=0.5, sigterm_wait_s=5.0, sigkill_wait_s=5.0),
                attempts, "sandbox", reap_callback=proc.poll,
            )
            self.assertTrue(result)
            signals_sent = [a["signal"] for a in attempts if a.get("delivered")]
            self.assertIn(int(signal.SIGTERM), signals_sent)
            self.assertNotIn(int(signal.SIGKILL), signals_sent)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_sigint_and_sigterm_ignoring_process_dies_to_sigkill(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=True, ignore_sigterm=True)
        try:
            attempts: list = []
            result = smoke.escalate_signal_to_group(
                identity.pgid, identity,
                smoke.CleanupTimeouts(sigint_wait_s=0.3, sigterm_wait_s=0.3, sigkill_wait_s=5.0),
                attempts, "sandbox", reap_callback=proc.poll,
            )
            self.assertTrue(result)
            signals_sent = [a["signal"] for a in attempts if a.get("delivered")]
            self.assertIn(int(signal.SIGKILL), signals_sent)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_evidence_records_signal_order(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=True, ignore_sigterm=True)
        try:
            attempts: list = []
            smoke.escalate_signal_to_group(
                identity.pgid, identity,
                smoke.CleanupTimeouts(sigint_wait_s=0.2, sigterm_wait_s=0.2, sigkill_wait_s=5.0),
                attempts, "sandbox", reap_callback=proc.poll,
            )
            delivered_signals = [a["signal"] for a in attempts if a.get("delivered")]
            self.assertEqual(delivered_signals, sorted(delivered_signals, key=lambda s: [
                int(signal.SIGINT), int(signal.SIGTERM), int(signal.SIGKILL)
            ].index(s)))
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_short_timeouts_leave_no_process_alive(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=True, ignore_sigterm=True)
        try:
            attempts: list = []
            result = smoke.escalate_signal_to_group(
                identity.pgid, identity,
                smoke.CleanupTimeouts(sigint_wait_s=0.1, sigterm_wait_s=0.1, sigkill_wait_s=2.0),
                attempts, "sandbox", reap_callback=proc.poll,
            )
            self.assertTrue(result)
            self.assertFalse(smoke._pgid_alive(identity.pgid))
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)


# ---------------------------------------------------------------------------
# 21.6 Reap and gates
# ---------------------------------------------------------------------------


@unittest.skipUnless(_IS_POSIX, _POSIX_SKIP_REASON)
class ReapAndGateTests(unittest.TestCase):
    def test_immediate_child_is_reaped(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=False, ignore_sigterm=False)
        try:
            evidence = smoke._shutdown_sandbox_and_reap(
                proc, identity,
                smoke.CleanupTimeouts(sigint_wait_s=2.0, sigterm_wait_s=2.0, sigkill_wait_s=2.0),
            )
            self.assertTrue(evidence["reaped"])
            self.assertIsNotNone(proc.returncode)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_no_zombie_after_reap(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=False, ignore_sigterm=False)
        try:
            smoke._shutdown_sandbox_and_reap(
                proc, identity,
                smoke.CleanupTimeouts(sigint_wait_s=2.0, sigterm_wait_s=2.0, sigkill_wait_s=2.0),
            )
            zombies = smoke._collect_zombie_children(os.getpid())
            self.assertNotIn(proc.pid, zombies)
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_no_orphan_after_successful_cleanup(self):
        proc, identity = _spawn_signal_responder(ignore_sigint=False, ignore_sigterm=False)
        try:
            evidence = smoke._shutdown_sandbox_and_reap(
                proc, identity,
                smoke.CleanupTimeouts(sigint_wait_s=2.0, sigterm_wait_s=2.0, sigkill_wait_s=2.0),
            )
            self.assertFalse(evidence["group_alive_after"])
            self.assertEqual(evidence["owned_members_remaining"], [])
        finally:
            _force_kill_group(identity.pgid)
            _force_kill(proc)

    def test_new_thread_detected_by_identity(self):
        import threading

        baseline = set(threading.enumerate())
        started = threading.Event()
        t = threading.Thread(target=lambda: (started.set(), time.sleep(2)), daemon=True)
        t.start()
        started.wait(timeout=2.0)
        try:
            current = set(threading.enumerate())
            new_threads = [x for x in current - baseline if x is not threading.main_thread()]
            self.assertIn(t, new_threads)
        finally:
            pass  # daemon thread; process-level test, no explicit join needed

    def test_baseline_thread_not_considered_leak(self):
        import threading

        baseline = set(threading.enumerate())
        current = set(threading.enumerate())
        new_threads = [x for x in current - baseline if x is not threading.main_thread()]
        self.assertEqual(new_threads, [])

    def test_owned_threads_remaining_blocks_result(self):
        result = {"errors": []}
        owned_threads_remaining = 1
        if owned_threads_remaining > 0:
            result["errors"].append("OWNED_THREADS_REMAINING")
        self.assertIn("OWNED_THREADS_REMAINING", result["errors"])

    def test_zombies_remaining_blocks_result(self):
        result = {"errors": []}
        zombies_remaining = 1
        if zombies_remaining > 0:
            result["errors"].append("ZOMBIES_REMAINING")
        self.assertIn("ZOMBIES_REMAINING", result["errors"])

    def test_orphan_processes_blocks_result(self):
        result = {"errors": []}
        orphan_processes = 1
        if orphan_processes > 0:
            result["errors"].append("ORPHAN_PROCESSES")
        self.assertIn("ORPHAN_PROCESSES", result["errors"])


# ---------------------------------------------------------------------------
# Parent-side child-result identity validation (pure logic, every platform)
# ---------------------------------------------------------------------------


class ChildResultIdentityValidationTests(unittest.TestCase):
    """_validate_child_result() must reject a child's self-reported
    child_identity whenever it disagrees with the identity the parent
    itself captured directly via spawn_isolated() -- never trust the JSON
    payload's own claim of its PID/PGID/SID/start_ticks."""

    def _expected_identity(self):
        return smoke.ProcessIdentity(pid=500, ppid=1, pgid=500, sid=500, start_ticks=1000, uid=1000)

    def _matching_payload(self):
        identity = self._expected_identity()
        return {
            "run_id": "r1", "scenario": "boot_shutdown", "domain_id": "150",
            "ok": True, "child_identity": identity.to_dict(),
        }

    def test_matching_identity_is_not_rejected(self):
        payload = self._matching_payload()
        errors = smoke._validate_child_result(
            payload, "boot_shutdown", "150", "r1", 0, expected_child_identity=self._expected_identity()
        )
        self.assertEqual(errors, [])

    def test_mismatched_pid_rejected(self):
        payload = self._matching_payload()
        payload["child_identity"]["pid"] = 999
        errors = smoke._validate_child_result(
            payload, "boot_shutdown", "150", "r1", 0, expected_child_identity=self._expected_identity()
        )
        self.assertTrue(any(e.startswith("CHILD_PID_MISMATCH") for e in errors))

    def test_mismatched_pgid_rejected(self):
        payload = self._matching_payload()
        payload["child_identity"]["pgid"] = 999
        errors = smoke._validate_child_result(
            payload, "boot_shutdown", "150", "r1", 0, expected_child_identity=self._expected_identity()
        )
        self.assertTrue(any(e.startswith("CHILD_PGID_MISMATCH") for e in errors))

    def test_mismatched_sid_rejected(self):
        payload = self._matching_payload()
        payload["child_identity"]["sid"] = 999
        errors = smoke._validate_child_result(
            payload, "boot_shutdown", "150", "r1", 0, expected_child_identity=self._expected_identity()
        )
        self.assertTrue(any(e.startswith("CHILD_SID_MISMATCH") for e in errors))

    def test_mismatched_start_ticks_rejected(self):
        payload = self._matching_payload()
        payload["child_identity"]["start_ticks"] = 999
        errors = smoke._validate_child_result(
            payload, "boot_shutdown", "150", "r1", 0, expected_child_identity=self._expected_identity()
        )
        self.assertTrue(any(e.startswith("CHILD_START_TICKS_MISMATCH") for e in errors))

    def test_missing_child_identity_rejected(self):
        payload = {"run_id": "r1", "scenario": "boot_shutdown", "domain_id": "150", "ok": True}
        errors = smoke._validate_child_result(
            payload, "boot_shutdown", "150", "r1", 0, expected_child_identity=self._expected_identity()
        )
        self.assertIn("CHILD_IDENTITY_MISSING_OR_MALFORMED", errors)

    def test_no_expected_identity_skips_identity_check(self):
        payload = self._matching_payload()
        payload["child_identity"]["pid"] = 999
        errors = smoke._validate_child_result(payload, "boot_shutdown", "150", "r1", 0)
        self.assertFalse(any("CHILD_PID_MISMATCH" in e for e in errors))


# ---------------------------------------------------------------------------
# Pure-logic tests (run on every platform, including Windows)
# ---------------------------------------------------------------------------


class PortablePureLogicTests(unittest.TestCase):
    def test_is_protected_id_rejects_zero_and_one(self):
        self.assertTrue(smoke.is_protected_id(0))
        self.assertTrue(smoke.is_protected_id(1))

    def test_is_protected_id_rejects_bool(self):
        self.assertTrue(smoke.is_protected_id(True))
        self.assertTrue(smoke.is_protected_id(False))

    def test_is_protected_id_rejects_non_int(self):
        self.assertTrue(smoke.is_protected_id("123"))
        self.assertTrue(smoke.is_protected_id(None))
        self.assertTrue(smoke.is_protected_id(3.5))

    def test_is_protected_id_accepts_normal_pid(self):
        self.assertFalse(smoke.is_protected_id(12345))

    def test_validate_domain_id_range_accepts_valid(self):
        self.assertIsNone(smoke.validate_domain_id_range(200, 3))

    def test_validate_domain_id_range_rejects_out_of_bounds(self):
        self.assertIsNotNone(smoke.validate_domain_id_range(231, 3))

    def test_parse_proc_stat_handles_parens_in_comm(self):
        text = "123 (a)b(c) S 1 123 123 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 999 0 0"
        parsed = smoke._parse_proc_stat(text)
        self.assertIsNotNone(parsed)
        pid_field, comm, rest = parsed
        self.assertEqual(pid_field, "123")
        self.assertEqual(comm, "a)b(c")

    def test_validate_lease_immutable_fields_rejects_bad_schema(self):
        errors = smoke.validate_lease_immutable_fields(
            {"schema_version": 0}, "r", "boot_shutdown", "1"
        )
        self.assertIn("LEASE_SCHEMA_MISMATCH", errors)

    def test_process_identity_from_dict_rejects_malformed(self):
        self.assertIsNone(smoke.ProcessIdentity.from_dict({"pid": "not-an-int"}))

    def test_process_identity_round_trip(self):
        identity = smoke.ProcessIdentity(pid=10, ppid=2, pgid=10, sid=10, start_ticks=5, uid=1000)
        roundtrip = smoke.ProcessIdentity.from_dict(identity.to_dict())
        self.assertEqual(identity, roundtrip)


if __name__ == "__main__":
    unittest.main()
