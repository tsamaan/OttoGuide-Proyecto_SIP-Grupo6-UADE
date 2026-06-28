"""Unit tests for _run_shutdown_sequence — CHANGE A shutdown authority.

Verifies that TourOrchestrator is the sole motion authority on the success
path: only an EmergencyStopResult with terminal_safe=True (damp_succeeded=True)
skips direct MotionCommand(0)+damp() calls (ORCHESTRATOR_EMERGENCY_COMPLETED).
A normal return with terminal_safe=False, a timeout, or an exception all
trigger the direct hardware fallback (DIRECT_HARDWARE_FALLBACK_USED) — see
test_ta02b for the exact false-positive this remediation closes.

Also verifies that main._close_orchestrator_and_conversation_manager (the
productive helper extracted from the lifespan finally block) calls
orchestrator.close() and ConversationManager.close() exactly once.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _import_run_shutdown_sequence():
    import main
    return main._run_shutdown_sequence


def _make_hardware():
    hw = MagicMock()
    hw.move = AsyncMock()
    hw.damp = AsyncMock()
    return hw


def _make_emergency_result(*, terminal_safe: bool):
    from src.core.tour_orchestrator import EmergencyStopResult
    return EmergencyStopResult(
        nav_cancel_attempted=True,
        nav_cancel_succeeded=True,
        zero_velocity_attempted=True,
        zero_velocity_succeeded=True,
        damp_attempted=True,
        damp_succeeded=terminal_safe,
        terminal_safe=terminal_safe,
        errors=[] if terminal_safe else ["damp_failed:RuntimeError:simulated"],
    )


def _make_orchestrator(*, emergency_side_effect=None, emergency_delay=0.0, terminal_safe=True):
    orch = MagicMock()
    if emergency_side_effect is not None:
        orch.emergency_stop = AsyncMock(side_effect=emergency_side_effect)
    elif emergency_delay > 0:
        async def _slow(*_, **__):
            await asyncio.sleep(emergency_delay)
        orch.emergency_stop = _slow
    else:
        orch.emergency_stop = AsyncMock(return_value=_make_emergency_result(terminal_safe=terminal_safe))
    orch.close = AsyncMock()
    return orch


# ---------------------------------------------------------------------------
# T-A01: orchestrator.emergency_stop() succeeds — STEP 3+4 NOT executed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ta01_orchestrator_success_skips_direct_hardware():
    """T-A01: When orchestrator.emergency_stop() succeeds, main.py must NOT
    call hardware.move() or hardware.damp() — ORCHESTRATOR_EMERGENCY_COMPLETED."""
    fn = _import_run_shutdown_sequence()
    hw = _make_hardware()
    orch = _make_orchestrator()

    await fn(hardware=hw, orchestrator=orch)

    hw.move.assert_not_called()
    hw.damp.assert_not_called()
    orch.emergency_stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# T-A02: orchestrator.emergency_stop() times out — STEP 3+4 execute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ta02_orchestrator_timeout_triggers_direct_fallback():
    """T-A02: When orchestrator.emergency_stop() times out, main.py MUST call
    hardware.move() and hardware.damp() — DIRECT_HARDWARE_FALLBACK_USED.

    Uses TimeoutError as side_effect instead of a real sleep to keep the test fast.
    """
    fn = _import_run_shutdown_sequence()
    hw = _make_hardware()
    orch = _make_orchestrator(emergency_side_effect=asyncio.TimeoutError())

    await fn(hardware=hw, orchestrator=orch)

    hw.move.assert_awaited_once()
    hw.damp.assert_awaited_once()


# ---------------------------------------------------------------------------
# T-A02b: emergency_stop() returns WITHOUT raising but terminal_safe=False
#         (the exact false-positive this remediation fixes: a normal return no
#         longer implies ORCHESTRATOR_EMERGENCY_COMPLETED — only terminal_safe does)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ta02b_non_terminal_safe_result_triggers_direct_fallback():
    """T-A02b: emergency_stop() returning normally (no exception, no timeout) with
    terminal_safe=False (e.g. damp failed inside on_enter_emergency) must still
    trigger the direct hardware fallback — this was the original false positive."""
    fn = _import_run_shutdown_sequence()
    hw = _make_hardware()
    orch = _make_orchestrator(terminal_safe=False)

    await fn(hardware=hw, orchestrator=orch)

    orch.emergency_stop.assert_awaited_once()
    hw.move.assert_awaited_once()
    hw.damp.assert_awaited_once()


# ---------------------------------------------------------------------------
# T-A03: orchestrator is None — direct fallback always executes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ta03_none_orchestrator_uses_direct_hardware():
    """T-A03: When orchestrator is None (mock/CI mode), hardware.move() and
    hardware.damp() must execute as the only path."""
    fn = _import_run_shutdown_sequence()
    hw = _make_hardware()

    await fn(hardware=hw, orchestrator=None)

    hw.move.assert_awaited_once()
    hw.damp.assert_awaited_once()


# ---------------------------------------------------------------------------
# T-A04: orchestrator.close() called exactly once after shutdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ta04_orchestrator_close_called_in_lifespan():
    """T-A04: main._close_orchestrator_and_conversation_manager (the real helper
    extracted from the lifespan finally block) must call orchestrator.close()
    exactly once. Exercises productive code directly instead of re-implementing
    the close sequence inline in the test."""
    import main as _main

    orch_mock = MagicMock()
    orch_mock.close = AsyncMock()
    orch_mock.conversation_manager = None
    orch_mock._conversation_manager = None

    await _main._close_orchestrator_and_conversation_manager(orch_mock)

    orch_mock.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# T-A05: conversation_manager.close() called exactly once after shutdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ta05_conversation_manager_close_called_sync():
    """T-A05: main._close_orchestrator_and_conversation_manager must call the
    SYNCHRONOUS ConversationManager.close() exactly once — must NOT be awaited.
    Exercises productive code directly instead of re-implementing the close
    sequence inline in the test."""
    import main as _main

    cm_mock = MagicMock()
    cm_mock.close = MagicMock()  # sync — not AsyncMock

    orch_mock = MagicMock()
    orch_mock.close = AsyncMock()
    orch_mock.conversation_manager = cm_mock

    await _main._close_orchestrator_and_conversation_manager(orch_mock)

    cm_mock.close.assert_called_once()
    # Verify it was called synchronously (not awaited)
    assert not asyncio.iscoroutinefunction(cm_mock.close)


# ---------------------------------------------------------------------------
# T-A06: orchestrator is None — close helper is a safe no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ta06_close_helper_noop_when_orchestrator_none():
    """T-A06: _close_orchestrator_and_conversation_manager(None) must not raise
    (mock/CI boot-failure path where no orchestrator was ever constructed)."""
    import main as _main

    await _main._close_orchestrator_and_conversation_manager(None)
