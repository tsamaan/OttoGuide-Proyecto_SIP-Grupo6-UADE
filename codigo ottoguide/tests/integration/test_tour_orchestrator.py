from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# @TASK: Priorizar src local
# @INPUT: Ruta del archivo de prueba actual
# @OUTPUT: Root del workspace en sys.path[0]
# @CONTEXT: Evita colision con paquetes src de otros proyectos en entorno global
# STEP 1: Resolver raiz del proyecto desde tests/integration
# STEP 2: Insertar ruta al inicio de sys.path si aun no existe
# @SECURITY: Limita imports al workspace actual durante la suite
# @AI_CONTEXT: Corrige conflictos de importacion en runners compartidos
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for loaded_module in list(sys.modules):
    if loaded_module == "src" or loaded_module.startswith("src."):
        del sys.modules[loaded_module]

from tests.mocks.mock_nav2_bridge import MockNav2Bridge
from tests.mocks.mock_ros2 import install_mocks
from tests.mocks.mock_vision_processor import MockVisionProcessor

install_mocks(sys.modules)

from hardware.interface import RobotHardwareInterface
from hardware.interface import MotionCommand
from hardware.mock_adapter import MockHardwareAPI
from src.core import TourOrchestrator
from src.core import TourPlan
from src.interaction import ConversationManager, ConversationResponse
from src.navigation import NavWaypoint


class EmergencySpyHardware(RobotHardwareInterface):
    def __init__(self, calls: list[object], mode: str = "normal") -> None:
        self.calls = calls
        self.mode = mode

    async def initialize(self) -> None:
        self.calls.append("hardware.initialize")

    async def stand(self) -> None:
        self.calls.append("hardware.stand")

    async def damp(self) -> None:
        self.calls.append("hardware.damp.start")
        if self.mode == "damp_raises":
            self.calls.append("hardware.damp.raise")
            raise RuntimeError("damp failed")
        if self.mode == "damp_times_out":
            self.calls.append("hardware.damp.sleep")
            await asyncio.sleep(10)
        self.calls.append("hardware.damp.end")

    async def move(self, command: MotionCommand) -> None:
        self.calls.append(
            {
                "hardware.move.start": {
                    "linear_x": command.linear_x,
                    "angular_z": command.angular_z,
                    "duration_ms": command.duration_ms,
                }
            }
        )
        if self.mode == "move_raises":
            self.calls.append("hardware.move.raise")
            raise RuntimeError("move failed")
        if self.mode == "move_times_out":
            self.calls.append("hardware.move.sleep")
            await asyncio.sleep(10)
        self.calls.append("hardware.move.end")

    async def emergency_stop(self) -> None:
        self.calls.append("hardware.emergency_stop")
        await self.damp()

    async def get_state(self) -> dict:
        return {"calls": self.calls}


class EmergencySpyNavBridge(MockNav2Bridge):
    def __init__(self, calls: list[object]) -> None:
        super().__init__(navigation_delay_s=0.0)
        self.calls = calls

    async def cancel_navigation(self) -> None:
        self.calls.append("nav.cancel.start")
        await super().cancel_navigation()
        self.calls.append("nav.cancel.end")


def _make_conversation_manager() -> ConversationManager:
    local_strategy = MagicMock()
    local_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="respuesta local",
            source_pipeline="local",
            audio_stream_ready=False,
        )
    )
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="respuesta cloud",
            source_pipeline="cloud",
            audio_stream_ready=False,
        )
    )
    cloud_strategy.close = MagicMock()
    return ConversationManager(local_strategy=local_strategy, cloud_strategy=cloud_strategy)


async def _make_emergency_spy_orchestrator(mode: str) -> tuple[TourOrchestrator, list[object]]:
    calls: list[object] = []
    hardware = EmergencySpyHardware(calls, mode=mode)
    orchestrator = TourOrchestrator(
        hardware_api=hardware,
        nav_bridge=EmergencySpyNavBridge(calls),
        conversation_manager=_make_conversation_manager(),
        vision_processor=MockVisionProcessor(),
        damp_timeout_s=0.05,
    )
    await orchestrator.activate_initial_state()
    return orchestrator, calls


def _index_of_call(calls: list[object], key: str) -> int:
    for index, call in enumerate(calls):
        if call == key:
            return index
        if isinstance(call, dict) and key in call:
            return index
    raise AssertionError(f"{key!r} not found in calls: {calls!r}")


def _assert_no_locomotion_after_damp(calls: list[object]) -> None:
    damp_index = _index_of_call(calls, "hardware.damp.start")
    trailing = calls[damp_index + 1 :]
    forbidden = ("hardware.move", "nav.cancel", "hardware.stand", "hardware.emergency_stop")
    for call in trailing:
        text = next(iter(call)) if isinstance(call, dict) else str(call)
        assert not text.startswith(forbidden), calls


@dataclass(slots=True)
class OrchestratorBundle:
    orchestrator: TourOrchestrator
    hardware_api: RobotHardwareInterface
    conversation_manager: ConversationManager
    nav_bridge: MockNav2Bridge
    vision_processor: MockVisionProcessor


@pytest_asyncio.fixture
async def orchestrator_bundle() -> AsyncIterator[OrchestratorBundle]:
    # @TASK: Ensamblar orquestador test
    # @INPUT: Sin parametros
    # @OUTPUT: Bundle con orquestador y dependencias mockeadas
    # @CONTEXT: Fixture async base para pruebas de integracion SITL. Refleja el wiring real de
    #           main.py (Fase 2H.0): hardware_api es MockHardwareAPI, la misma clase que
    #           config.settings.get_hardware_adapter() resuelve para ROBOT_MODE=mock|demo.
    # STEP 1: Instanciar MockHardwareAPI (HAL canonica) e inicializarla
    # STEP 2: Construir ConversationManager y TourOrchestrator para pruebas
    # @SECURITY: Aisla pruebas de hardware y servicios externos
    # @AI_CONTEXT: MockHardwareAPI no usa patron singleton; instancia nueva por test
    hardware_api = MockHardwareAPI()
    await hardware_api.initialize()

    local_strategy = MagicMock()
    local_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="respuesta local",
            source_pipeline="local",
            audio_stream_ready=False,
        )
    )
    local_strategy.close = MagicMock()

    cloud_strategy = MagicMock()
    cloud_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="respuesta cloud",
            source_pipeline="cloud",
            audio_stream_ready=False,
        )
    )
    cloud_strategy.close = MagicMock()

    conversation_manager = ConversationManager(
        local_strategy=local_strategy,
        cloud_strategy=cloud_strategy,
    )

    nav_bridge = MockNav2Bridge(navigation_delay_s=0.1)
    vision_processor = MockVisionProcessor()

    orchestrator = TourOrchestrator(
        hardware_api=hardware_api,
        nav_bridge=nav_bridge,
        conversation_manager=conversation_manager,
        vision_processor=vision_processor,
    )
    await orchestrator.activate_initial_state()

    yield OrchestratorBundle(
        orchestrator=orchestrator,
        hardware_api=hardware_api,
        conversation_manager=conversation_manager,
        nav_bridge=nav_bridge,
        vision_processor=vision_processor,
    )


@pytest.mark.asyncio
async def test_dispatch_tour_enters_navigating(orchestrator_bundle: OrchestratorBundle) -> None:
    # @TASK: Validar despacho nominal
    # @INPUT: orchestrator_bundle
    # @OUTPUT: dispatch_tour completa y el estado pasa a navigating
    # @CONTEXT: Cobertura del contrato publico actual del orquestador
    # STEP 1: Despachar un plan con un waypoint
    # STEP 2: Validar persistencia de contexto y llamada al bridge
    # @SECURITY: No usa hardware real ni ROS2 real
    # @AI_CONTEXT: Verifica la ruta activa usada por FastAPI
    orchestrator = orchestrator_bundle.orchestrator
    plan = TourPlan(
        waypoints=[NavWaypoint(x=0.0, y=0.0, yaw_rad=0.0)],
        tour_id="tour-001",
    )

    await orchestrator.dispatch_tour(plan)
    await asyncio.sleep(0.05)

    assert orchestrator.state_id == "navigating"
    assert orchestrator.context.tour_id == "tour-001"
    assert orchestrator_bundle.nav_bridge.navigation_calls


@pytest.mark.asyncio
async def test_emergency_stop_triggers_damp(orchestrator_bundle: OrchestratorBundle) -> None:
    # @TASK: Validar emergencia con Damp
    # @INPUT: orchestrator_bundle
    # @OUTPUT: Estado del adaptador HAL canonico reportado como "damped"
    # @CONTEXT: Verifica rutina de seguridad en estado final EMERGENCY contra MockHardwareAPI
    #           (HAL canonica), reemplazando el historial de comandos del SDK legacy.
    # STEP 1: Forzar emergencia
    # STEP 2: Asertar estado final de la FSM y damp() ejecutado en el adaptador HAL
    # @SECURITY: Ruta failsafe critica
    # @AI_CONTEXT: Cubre la transicion de maxima prioridad
    orchestrator = orchestrator_bundle.orchestrator
    hardware_api = orchestrator_bundle.hardware_api

    await orchestrator.emergency_stop("forced-test-error")

    assert orchestrator.state_id == "emergency"
    state = await hardware_api.get_state()
    assert state["state"] == "damped"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ["normal", "move_raises", "move_times_out", "damp_raises", "damp_times_out"],
)
async def test_emergency_stop_terminal_damp_contract(mode: str) -> None:
    orchestrator, calls = await _make_emergency_spy_orchestrator(mode)

    await orchestrator.emergency_stop(f"forced-{mode}")

    assert orchestrator.state_id == "emergency"
    nav_index = _index_of_call(calls, "nav.cancel.start")
    move_index = _index_of_call(calls, "hardware.move.start")
    damp_index = _index_of_call(calls, "hardware.damp.start")
    assert nav_index < move_index < damp_index
    _assert_no_locomotion_after_damp(calls)


@pytest.mark.asyncio
async def test_emergency_stop_attempts_damp_after_move_exception() -> None:
    orchestrator, calls = await _make_emergency_spy_orchestrator("move_raises")

    await orchestrator.emergency_stop("move-exception")

    assert "hardware.move.raise" in calls
    assert "hardware.damp.start" in calls


@pytest.mark.asyncio
async def test_emergency_stop_attempts_damp_after_move_timeout() -> None:
    orchestrator, calls = await _make_emergency_spy_orchestrator("move_times_out")

    await orchestrator.emergency_stop("move-timeout")

    assert "hardware.move.sleep" in calls
    assert "hardware.damp.start" in calls


@pytest.mark.asyncio
async def test_handle_user_question_returns_response(orchestrator_bundle: OrchestratorBundle) -> None:
    # @TASK: Validar question path
    # @INPUT: orchestrator_bundle
    # @OUTPUT: Response de ConversationManager y contexto actualizado
    # @CONTEXT: Cobertura de compatibilidad para la API de texto directa
    # STEP 1: Enviar pregunta de texto
    # STEP 2: Asertar que se registra la ultima interaccion
    # @SECURITY: Sin dependencia de voz ni hardware
    # @AI_CONTEXT: Conserva contrato usado por endpoints de soporte
    orchestrator = orchestrator_bundle.orchestrator

    response_obj = await asyncio.wait_for(
        orchestrator.handle_user_question("¿Dónde está la salida?"),
        timeout=0.5,
    )

    assert response_obj.answer_text
    assert orchestrator.context.last_interaction is response_obj
