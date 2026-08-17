"""Unit tests for the posture-preserving canonical mock HAL."""
from __future__ import annotations

import pytest

from hardware.interface import MotionCommand, RobotHardwareInterface
from hardware.mock_adapter import MockRobotAdapter


def test_mock_implements_canonical_contract_only() -> None:
    adapter = MockRobotAdapter()
    assert isinstance(adapter, RobotHardwareInterface)
    for method in ("initialize", "move", "stop_motion", "get_state"):
        assert hasattr(adapter, method)
    for forbidden in ("stand", "damp", "emergency_stop"):
        assert not hasattr(adapter, forbidden)


@pytest.mark.asyncio
async def test_initialize_has_no_posture_side_effect() -> None:
    adapter = MockRobotAdapter()
    await adapter.initialize()
    state = await adapter.get_state()
    assert state["state"] == "initialized"
    assert state["position"] == {"x": 0.0, "y": 0.0, "yaw": 0.0}


@pytest.mark.asyncio
async def test_move_integrates_position() -> None:
    adapter = MockRobotAdapter()
    await adapter.initialize()
    await adapter.move(MotionCommand(linear_x=0.2, angular_z=0.1, duration_ms=1000))
    state = await adapter.get_state()
    assert state["state"] == "moving"
    assert state["position"]["x"] == pytest.approx(0.2)
    assert state["position"]["yaw"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_stop_motion_preserves_position_and_posture_state() -> None:
    adapter = MockRobotAdapter()
    await adapter.initialize()
    await adapter.move(MotionCommand(linear_x=0.2, angular_z=0.1, duration_ms=1000))
    before = await adapter.get_state()
    await adapter.stop_motion()
    after = await adapter.get_state()
    assert after["position"] == before["position"]
    assert after["state"] == before["state"]
    assert after["stop_motion_calls"] == 1


@pytest.mark.asyncio
async def test_stop_motion_is_idempotent() -> None:
    adapter = MockRobotAdapter()
    await adapter.initialize()
    await adapter.stop_motion()
    await adapter.stop_motion()
    state = await adapter.get_state()
    assert state["stop_motion_calls"] == 2
    assert state["state"] == "initialized"
