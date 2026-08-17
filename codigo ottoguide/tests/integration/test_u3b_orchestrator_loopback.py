from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.mocks.mock_nav2_bridge import MockNav2Bridge
from tests.mocks.mock_ros2 import install_mocks

install_mocks(sys.modules)

from hardware.mock_adapter import MockHardwareAPI
from src.core.event_bus import OttoEventBus
from src.core.events import EventType
from src.core.tour_orchestrator import TourOrchestrator, TourPlan
from src.interaction import ConversationManager
from src.interaction.jsonl_worker_supervisor import (
    JsonlInteractionWorkerSupervisor,
    JsonlWorkerSupervisorConfig,
)
from src.navigation import NavWaypoint


class VisionStub:
    visual_odometry_enabled = False

    async def get_next_estimate(self, timeout_s: float = 0.5):
        return None

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_loopback_runtime_completion_returns_to_navigating() -> None:
    worker = PROJECT_ROOT / "tests" / "support" / "u3a_loopback_worker.py"
    runtime = JsonlInteractionWorkerSupervisor(
        JsonlWorkerSupervisorConfig(
            argv=(sys.executable, str(worker), "normal"),
            startup_timeout_s=2.0,
            heartbeat_timeout_s=2.0,
            shutdown_timeout_s=1.0,
            terminate_timeout_s=1.0,
        )
    )
    await runtime.start()

    bus = OttoEventBus()
    completions: list[object] = []

    async def _capture_completion(_event_type, data):
        completions.append(data)

    bus.subscribe(EventType.INTERACTION_COMPLETED, _capture_completion)

    local_strategy = MagicMock()
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()
    cm = ConversationManager(local_strategy=local_strategy, cloud_strategy=cloud_strategy)
    orchestrator = TourOrchestrator(
        hardware_api=MockHardwareAPI(),
        nav_bridge=MockNav2Bridge(navigation_delay_s=10.0),
        conversation_manager=cm,
        vision_processor=VisionStub(),
        event_bus=bus,
        interaction_runtime=runtime,
        audio_capture_timeout_s=2.0,
    )
    await orchestrator.activate_initial_state()
    await orchestrator.dispatch_tour(
        TourPlan(
            waypoints=[NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0)],
            tour_id="tour:u3b-loopback",
        )
    )

    try:
        await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
        task = orchestrator._interaction_task
        if task is not None:
            await task

        assert len(completions) == 1
        assert completions[0]["interaction_id"] == "interaction:1"
        assert completions[0]["playback_completed"] is True
        assert orchestrator.state_id == "navigating"
    finally:
        await orchestrator.close()
        await runtime.close()
