from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.mocks.mock_nav2_bridge import MockNav2Bridge
from tests.mocks.mock_ros2 import install_mocks
from tests.mocks.mock_vision_processor import MockVisionProcessor

install_mocks(sys.modules)

from hardware.mock_adapter import MockHardwareAPI

# Importaciones de src.* diferidas dentro de funciones para no fijar la version de
# src.core.event_bus en tiempo de coleccion — test_event_bus.py reemplaza ese modulo
# a nivel de modulo, y el orden de coleccion determinaria que version queda en cache.


def _make_orchestrator(nav_delay: float = 0.15) -> tuple:
    from src.core import TourOrchestrator, TourPlan  # noqa: PLC0415
    from src.interaction import ConversationManager, ConversationResponse  # noqa: PLC0415

    hardware_api = MockHardwareAPI()
    nav_bridge = MockNav2Bridge(navigation_delay_s=nav_delay)
    vision_processor = MockVisionProcessor()

    local_strategy = MagicMock()
    local_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="ok", source_pipeline="local", audio_stream_ready=False
        )
    )
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()

    conversation_manager = ConversationManager(
        local_strategy=local_strategy,
        cloud_strategy=cloud_strategy,
    )
    conversation_manager.get_waypoint_interaction_type = MagicMock(return_value="scripted")

    async def scripted_mock(waypoint_id):
        await asyncio.sleep(0.05)
        return ConversationResponse(
            answer_text="guion", source_pipeline="local", audio_stream_ready=False
        )

    conversation_manager.process_scripted_interaction = scripted_mock

    orchestrator = TourOrchestrator(
        hardware_api=hardware_api,
        nav_bridge=nav_bridge,
        conversation_manager=conversation_manager,
        vision_processor=vision_processor,
    )
    return orchestrator, hardware_api


def _three_waypoint_plan():
    from src.core import TourPlan  # noqa: PLC0415
    from src.navigation import NavWaypoint  # noqa: PLC0415
    return TourPlan(
        waypoints=[
            NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=2.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=3.0, y=0.0, yaw_rad=0.0),
        ],
        tour_id="lifecycle-test",
    )


@pytest.mark.asyncio
async def test_single_nav_task_created_on_dispatch() -> None:
    """Existe una única navigation task al entrar a NAVIGATING."""
    orchestrator, hw = _make_orchestrator()
    await hw.initialize()
    await orchestrator.activate_initial_state()

    await orchestrator.dispatch_tour(_three_waypoint_plan())
    await asyncio.sleep(0.02)

    assert orchestrator.state_id == "navigating"
    assert orchestrator._nav_task is not None
    assert not orchestrator._nav_task.done()

    orchestrator._nav_task.cancel()
    try:
        await orchestrator._nav_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_interaction_cancels_nav_task() -> None:
    """Entrar en interacción cancela el _nav_task y lo pone a None."""
    orchestrator, hw = _make_orchestrator(nav_delay=0.5)
    await hw.initialize()
    await orchestrator.activate_initial_state()

    await orchestrator.dispatch_tour(_three_waypoint_plan())
    await asyncio.sleep(0.02)
    assert orchestrator._nav_task is not None

    interaction_task = asyncio.create_task(
        orchestrator.request_interaction(np.zeros(1, dtype=np.float32), language="es")
    )
    await asyncio.sleep(0.02)

    assert orchestrator.state_id == "interacting"
    assert orchestrator._nav_task is None

    await interaction_task


@pytest.mark.asyncio
async def test_resume_recreates_nav_task_and_preserves_index() -> None:
    """Volver a NAVIGATING recrea _nav_task; la reanudación conserva el índice guardado."""
    orchestrator, hw = _make_orchestrator(nav_delay=0.2)
    await hw.initialize()
    await orchestrator.activate_initial_state()

    await orchestrator.dispatch_tour(_three_waypoint_plan())
    await asyncio.sleep(0.02)

    assert orchestrator.state_id == "navigating"
    assert orchestrator._nav_task is not None
    assert orchestrator.context.current_waypoint_index == 0

    interaction_task = asyncio.create_task(
        orchestrator.request_interaction(np.zeros(1, dtype=np.float32), language="es")
    )
    await asyncio.sleep(0.02)

    assert orchestrator.state_id == "interacting"
    assert orchestrator._nav_task is None

    await interaction_task

    assert orchestrator.state_id == "navigating"
    assert orchestrator._nav_task is not None
    assert not orchestrator._nav_task.done()
    assert orchestrator.context.current_waypoint_index == 0

    if orchestrator._nav_task is not None:
        await orchestrator._nav_task
    assert orchestrator.state_id == "idle"


@pytest.mark.asyncio
async def test_supervised_task_triggers_emergency_on_exception() -> None:
    """Una excepción no controlada en una tarea supervisada activa emergency_stop."""
    orchestrator, hw = _make_orchestrator()
    await hw.initialize()
    await orchestrator.activate_initial_state()

    async def failing_coro():
        await asyncio.sleep(0.02)
        raise RuntimeError("error de prueba")

    orchestrator._create_supervised_task(failing_coro(), name="failing-task")
    await asyncio.sleep(0.1)

    assert orchestrator.state_id == "emergency"
    assert orchestrator.context.last_error == "Fallo critico en failing-task: error de prueba"


@pytest.mark.asyncio
async def test_close_cancels_and_awaits_tasks() -> None:
    """close() cancela y espera ambas tareas de fondo activas."""
    orchestrator, hw = _make_orchestrator(nav_delay=10.0)
    await hw.initialize()
    await orchestrator.activate_initial_state()

    await orchestrator.dispatch_tour(_three_waypoint_plan())
    await asyncio.sleep(0.02)

    assert orchestrator._nav_task is not None
    assert not orchestrator._nav_task.done()

    await orchestrator.close()

    assert orchestrator._nav_task is None
    assert orchestrator._odometry_task is None


@pytest.mark.asyncio
async def test_no_pending_tasks_after_close() -> None:
    """No quedan asyncio.Task pendientes relacionadas al orquestador tras close()."""
    orchestrator, hw = _make_orchestrator(nav_delay=10.0)
    await hw.initialize()
    await orchestrator.activate_initial_state()

    await orchestrator.dispatch_tour(_three_waypoint_plan())
    await asyncio.sleep(0.02)

    nav_task = orchestrator._nav_task
    odo_task = orchestrator._odometry_task

    await orchestrator.close()

    assert nav_task is None or nav_task.done()
    assert odo_task is None or odo_task.done()
    assert orchestrator._nav_task is None
    assert orchestrator._odometry_task is None


@pytest.mark.asyncio
async def test_close_removes_tasks_from_event_loop() -> None:
    """Gate 3: close() elimina las tareas del orquestador de asyncio.all_tasks()."""
    orchestrator, hw = _make_orchestrator(nav_delay=10.0)
    await hw.initialize()
    await orchestrator.activate_initial_state()

    await orchestrator.dispatch_tour(_three_waypoint_plan())
    await asyncio.sleep(0.02)

    orch_prefixes = ("nav-loop-", "odometry-injection-loop")

    before = [t for t in asyncio.all_tasks() if t.get_name().startswith(orch_prefixes)]
    assert len(before) >= 1, "debe haber al menos una tarea del orquestador antes de close()"

    await orchestrator.close()

    after = [t for t in asyncio.all_tasks() if t.get_name().startswith(orch_prefixes)]
    assert after == [], f"tareas del orquestador remanentes: {[t.get_name() for t in after]}"


@pytest.mark.asyncio
async def test_waypoint_index_advances_and_preserved_on_resume() -> None:
    """Gate 5: current_waypoint_index = indice del waypoint actualmente en ejecucion.

    Secuencia: wp0 completado -> wp1 interrumpido -> interaccion -> resume desde wp1.
    Detecta tanto repeticion (wp0 re-navegado) como salto (wp2 ejecutado antes que wp1).
    """

    class _ControlledBridge:
        """Nav bridge con gate asyncio.Event: navega cuando se llama a complete_one()."""

        def __init__(self) -> None:
            self.navigation_calls: list = []
            self.cancel_calls: int = 0
            self.started: bool = True
            self._gate: asyncio.Event = asyncio.Event()

        def complete_one(self) -> None:
            self._gate.set()

        async def navigate_to_waypoints(self, waypoints: list) -> bool:
            self.navigation_calls.append(list(waypoints))
            self._gate.clear()
            try:
                await self._gate.wait()
            except asyncio.CancelledError:
                self.cancel_calls += 1
                raise
            return True

        async def cancel_navigation(self) -> None:
            self.cancel_calls += 1
            self._gate.set()

        async def inject_absolute_pose(self, pose_estimate) -> None:
            pass

        async def is_navigation_active(self) -> bool:
            return not self._gate.is_set()

        async def get_status(self):
            from src.navigation.models import NavigationStatus
            return NavigationStatus()

        async def get_last_result(self):
            return None

        async def close(self) -> None:
            self.started = False

    from src.core import TourOrchestrator  # noqa: PLC0415
    from src.interaction import ConversationManager, ConversationResponse  # noqa: PLC0415

    hardware_api = MockHardwareAPI()
    bridge = _ControlledBridge()
    vision_processor = MockVisionProcessor()

    local_strategy = MagicMock()
    local_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="ok", source_pipeline="local", audio_stream_ready=False
        )
    )
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()

    conversation_manager = ConversationManager(
        local_strategy=local_strategy,
        cloud_strategy=cloud_strategy,
    )
    conversation_manager.get_waypoint_interaction_type = MagicMock(return_value="scripted")

    async def scripted_mock(waypoint_id):
        await asyncio.sleep(0.01)
        return ConversationResponse(
            answer_text="guion", source_pipeline="local", audio_stream_ready=False
        )

    conversation_manager.process_scripted_interaction = scripted_mock

    orchestrator = TourOrchestrator(
        hardware_api=hardware_api,
        nav_bridge=bridge,
        conversation_manager=conversation_manager,
        vision_processor=vision_processor,
    )
    await hardware_api.initialize()
    await orchestrator.activate_initial_state()

    await orchestrator.dispatch_tour(_three_waypoint_plan())
    await asyncio.sleep(0.01)

    assert orchestrator.context.current_waypoint_index == 0
    assert len(bridge.navigation_calls) == 1, "wp0 debe estar en progreso"

    # Completar wp0 — el loop avanzara a wp1 tras WAYPOINT_POLL_INTERVAL_S (0.1 s)
    bridge.complete_one()
    await asyncio.sleep(0.15)

    assert orchestrator.context.current_waypoint_index == 1, "loop debe estar en wp1"
    nav_calls_at_wp1 = len(bridge.navigation_calls)
    assert nav_calls_at_wp1 == 2, "solo wp0 y wp1 deben haberse iniciado"

    # Guardar referencia a la tarea activa antes de interrumpir
    old_nav_task = orchestrator._nav_task

    # Interrumpir en wp1: la interaccion cancela nav task y auto-reanuda (todo en un await)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32), language="es")

    # Contrato: indice se conservo en 1 (no reseteado a 0, no avanzado a 2)
    assert orchestrator.context.current_waypoint_index == 1, "indice debe ser 1, no 0 ni 2"

    # Resume: nueva tarea diferente de la anterior
    assert orchestrator.state_id == "navigating"
    new_nav_task = orchestrator._nav_task
    assert new_nav_task is not None
    assert old_nav_task is not new_nav_task, "la nueva tarea debe ser un objeto diferente"
    assert old_nav_task.done(), "la tarea antigua debe estar terminada"

    # wp1 re-navegado tras resume (no saltado)
    await asyncio.sleep(0.01)
    assert len(bridge.navigation_calls) == nav_calls_at_wp1 + 1, "wp1 debe re-navegarse (no saltarse)"

    # Completar wp1 resumido -> avanzar a wp2
    bridge.complete_one()
    await asyncio.sleep(0.15)

    assert orchestrator.context.current_waypoint_index == 2, "wp2 debe ser el siguiente"
    assert len(bridge.navigation_calls) == nav_calls_at_wp1 + 2, "wp2 debe iniciarse despues"

    # Completar wp2 -> tour finaliza
    bridge.complete_one()
    await asyncio.sleep(0.15)

    assert orchestrator.state_id == "idle", "tour debe finalizar en IDLE"
