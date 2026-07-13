"""Integration regressions for TourOrchestrator motion authority."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hardware.interface import MotionCommand, RobotHardwareInterface
from hardware.mock_adapter import MockHardwareAPI
from src.core import TourOrchestrator, TourPlan
from src.interaction import ConversationManager, ConversationResponse
from src.navigation import NavWaypoint
from tests.mocks.mock_nav2_bridge import MockNav2Bridge
from tests.mocks.mock_vision_processor import MockVisionProcessor


def _conversation_manager() -> ConversationManager:
    local = MagicMock()
    local.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="respuesta local",
            source_pipeline="local",
            audio_stream_ready=False,
        )
    )
    local.close = MagicMock()
    cloud = MagicMock()
    cloud.generate = AsyncMock(return_value=local.generate.return_value)
    cloud.close = MagicMock()
    return ConversationManager(local_strategy=local, cloud_strategy=cloud)


class SpyHardware(RobotHardwareInterface):
    def __init__(self, calls: list[object], mode: str = "normal") -> None:
        self.calls = calls
        self.mode = mode

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def move(self, command: MotionCommand) -> None:
        self.calls.append(("move", command.linear_x, command.angular_z))
        if self.mode == "zero_fails":
            raise RuntimeError("zero failed")

    async def stop_motion(self) -> None:
        self.calls.append("stop_motion")
        if self.mode == "stop_fails":
            raise RuntimeError("stop failed")
        if self.mode == "stop_times_out":
            await asyncio.sleep(10)

    async def get_state(self) -> dict:
        return {"calls": list(self.calls)}


async def _orchestrator(mode: str = "normal") -> tuple[TourOrchestrator, list[object]]:
    calls: list[object] = []
    orch = TourOrchestrator(
        hardware_api=SpyHardware(calls, mode),
        nav_bridge=MockNav2Bridge(navigation_delay_s=0.0),
        conversation_manager=_conversation_manager(),
        vision_processor=MockVisionProcessor(),
        stop_motion_timeout_s=0.05,
    )
    await orch.activate_initial_state()
    return orch, calls


@pytest.mark.asyncio
async def test_dispatch_tour_enters_navigating() -> None:
    hardware = MockHardwareAPI()
    await hardware.initialize()
    orch = TourOrchestrator(
        hardware_api=hardware,
        nav_bridge=MockNav2Bridge(navigation_delay_s=0.1),
        conversation_manager=_conversation_manager(),
        vision_processor=MockVisionProcessor(),
    )
    await orch.activate_initial_state()
    await orch.dispatch_tour(
        TourPlan(
            waypoints=[NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0, frame_id="map")],
            tour_id="test",
        )
    )
    assert orch.state_id == "navigating"
    await orch.emergency_stop("test-cleanup")


@pytest.mark.asyncio
async def test_emergency_order_and_posture_contract() -> None:
    orch, calls = await _orchestrator()
    result = await orch.emergency_stop("operator")
    assert calls[-2:] == [("move", 0.0, 0.0), "stop_motion"]
    assert result.nav_cancel_succeeded
    assert result.zero_velocity_succeeded
    assert result.stop_motion_succeeded
    assert result.software_motion_terminal
    assert result.posture_change_attempted is False
    assert result.posture_preserved is True
    assert result.operator_intervention_required is True
    assert result.mission_locked is True
    assert result.damp_attempted is False
    assert result.damp_succeeded is False


@pytest.mark.asyncio
async def test_emergency_stopmove_failure_is_reported_without_posture_change() -> None:
    orch, calls = await _orchestrator("stop_fails")
    result = await orch.emergency_stop("failure")
    assert calls.count("stop_motion") == 1
    assert result.stop_motion_attempted
    assert not result.stop_motion_succeeded
    assert not result.software_motion_terminal
    assert result.posture_preserved
    assert any(error.startswith("stop_motion_failed:") for error in result.errors)


@pytest.mark.asyncio
async def test_emergency_stopmove_timeout_is_bounded() -> None:
    orch, calls = await _orchestrator("stop_times_out")
    result = await orch.emergency_stop("timeout")
    assert calls.count("stop_motion") == 1
    assert any(error.startswith("stop_motion_timeout:") for error in result.errors)


@pytest.mark.asyncio
async def test_emergency_is_idempotent_and_never_reissues_motion() -> None:
    orch, calls = await _orchestrator()
    first = await orch.emergency_stop("first")
    count = len(calls)
    second = await orch.emergency_stop("second")
    assert first.stop_motion_succeeded
    assert second.already_emergency
    assert len(calls) == count


@pytest.mark.asyncio
async def test_zero_velocity_failure_still_attempts_stopmove_once() -> None:
    orch, calls = await _orchestrator("zero_fails")
    result = await orch.emergency_stop("zero failure")
    assert calls.count("stop_motion") == 1
    assert not result.zero_velocity_succeeded
    assert result.stop_motion_succeeded


@pytest.mark.asyncio
async def test_handle_user_question_returns_response() -> None:
    hardware = MockHardwareAPI()
    await hardware.initialize()
    orch = TourOrchestrator(
        hardware_api=hardware,
        nav_bridge=MockNav2Bridge(),
        conversation_manager=_conversation_manager(),
        vision_processor=MockVisionProcessor(),
    )
    await orch.activate_initial_state()
    response = await orch.handle_user_question("hola")
    assert response.answer_text == "respuesta local"
