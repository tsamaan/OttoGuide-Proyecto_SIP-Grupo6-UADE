from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware import MotionCommand, RobotHardwareAPI
from tests.mocks.mock_unitree_sdk import MockHighLevelClient


@pytest.mark.asyncio
async def test_robot_hardware_api_accepts_motion_command_contract() -> None:
    # @TASK: Validar compatibilidad MotionCommand en wrapper SDK
    # @INPUT: MotionCommand usado por TourOrchestrator
    # @OUTPUT: Llamada Move registrada por cliente mock
    # @CONTEXT: Unifica contrato hardware entre orquestador y wrapper Unitree
    # @SECURITY: Ejecuta sin hardware real
    RobotHardwareAPI._instance = None
    mock_client = MockHighLevelClient(default_latency_s=0.001)
    api = RobotHardwareAPI.get_instance(
        client_factory=lambda: mock_client,
        call_timeout_s=0.2,
    )

    await api.move(MotionCommand(linear_x=0.1, angular_z=0.2, duration_ms=0))

    assert any(record.command == "Move" for record in mock_client.history)
    api.close()
    RobotHardwareAPI._instance = None
