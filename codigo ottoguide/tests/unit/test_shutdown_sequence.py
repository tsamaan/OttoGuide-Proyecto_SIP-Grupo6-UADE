"""Regression tests for posture-preserving graceful shutdown."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _hardware():
    hardware = MagicMock()
    hardware.move = AsyncMock()
    hardware.stop_motion = AsyncMock()
    return hardware


def _result(*, succeeded: bool, attempted: bool = True):
    from src.core.tour_orchestrator import EmergencyStopResult

    return EmergencyStopResult(
        nav_cancel_attempted=True,
        nav_cancel_succeeded=True,
        zero_velocity_attempted=True,
        zero_velocity_succeeded=True,
        stop_motion_attempted=attempted,
        stop_motion_succeeded=succeeded,
        posture_change_attempted=False,
        posture_preserved=True,
        mission_locked=True,
        software_motion_terminal=succeeded,
        operator_intervention_required=True,
        terminal_safe=succeeded,
        errors=[] if succeeded else ["stop_motion_failed:simulated"],
    )


def _orchestrator(*, result=None, side_effect=None):
    orch = MagicMock()
    orch.emergency_stop = AsyncMock(return_value=result, side_effect=side_effect)
    orch.close = AsyncMock()
    return orch


@pytest.mark.asyncio
async def test_orchestrator_is_single_stop_motion_authority():
    import main

    hardware = _hardware()
    orch = _orchestrator(result=_result(succeeded=True))
    await main._run_shutdown_sequence(hardware, orch)
    hardware.move.assert_not_awaited()
    hardware.stop_motion.assert_not_awaited()
    orch.emergency_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_orchestrator_stop_is_not_duplicated():
    import main

    hardware = _hardware()
    orch = _orchestrator(result=_result(succeeded=False))
    await main._run_shutdown_sequence(hardware, orch)
    hardware.move.assert_not_awaited()
    hardware.stop_motion.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_uses_zero_then_stopmove_once():
    import main

    hardware = _hardware()
    orch = _orchestrator(side_effect=asyncio.TimeoutError())
    await main._run_shutdown_sequence(hardware, orch)
    hardware.move.assert_awaited_once()
    hardware.stop_motion.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_orchestrator_uses_zero_then_stopmove_once():
    import main

    hardware = _hardware()
    await main._run_shutdown_sequence(hardware, None)
    hardware.move.assert_awaited_once()
    hardware.stop_motion.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_never_uses_posture_commands():
    import main

    hardware = _hardware()
    await main._run_shutdown_sequence(hardware, None)
    for forbidden in ("damp", "stand", "start", "StandUp", "BalanceStand"):
        assert forbidden not in hardware.method_calls


@pytest.mark.asyncio
async def test_close_helpers_execute_once():
    import main

    cm = MagicMock()
    cm.close = MagicMock()
    orch = MagicMock()
    orch.close = AsyncMock()
    orch.conversation_manager = cm
    await main._close_orchestrator_and_conversation_manager(orch)
    orch.close.assert_awaited_once()
    cm.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_helper_none_is_noop():
    import main

    await main._close_orchestrator_and_conversation_manager(None)
