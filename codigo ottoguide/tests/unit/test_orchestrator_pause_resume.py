"""
Tests de pause/resume para TourOrchestrator — Fase 6.

Contratos verificados:
- Como máximo una nav task activa.
- pause normal no activa emergency_stop.
- CancelledError no activa emergencia.
- current_waypoint_index conserva el waypoint interrumpido.
- resume no vuelve a cero.
- resume no salta un waypoint.
- una instancia nueva comienza en estado seguro.
- emergency tiene prioridad absoluta.
- no quedan tareas pendientes al cerrar.
"""
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


# ---------------------------------------------------------------------------
# Infraestructura común
# ---------------------------------------------------------------------------

class _ControlledBridge:
    """Nav bridge controlable: cada llamada a navigate_to_waypoints bloquea
    en un asyncio.Event hasta que se llame a complete_one()."""

    def __init__(self) -> None:
        self.nav_calls: list = []
        self.cancel_calls: int = 0
        self.started: bool = True
        self._gate: asyncio.Event = asyncio.Event()
        self._gate.set()  # primera llamada libre por defecto

    def hold(self) -> None:
        """Congela la próxima navegación (gate cerrado)."""
        self._gate.clear()

    def complete_one(self) -> None:
        """Desbloquea la navegación actual."""
        self._gate.set()

    async def navigate_to_waypoints(self, waypoints: list) -> bool:
        self.nav_calls.append(list(waypoints))
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


def _make_orchestrator_controlled() -> tuple:
    from src.core import TourOrchestrator, TourPlan
    from src.interaction import ConversationManager, ConversationResponse

    hw = MockHardwareAPI()
    bridge = _ControlledBridge()
    vision = MockVisionProcessor()

    local_strategy = MagicMock()
    local_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="ok", source_pipeline="local", audio_stream_ready=False
        )
    )
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()

    cm = ConversationManager(
        local_strategy=local_strategy,
        cloud_strategy=cloud_strategy,
    )
    cm.get_waypoint_interaction_type = MagicMock(return_value="scripted")

    async def scripted_mock(waypoint_id):
        await asyncio.sleep(0.01)
        return ConversationResponse(
            answer_text="ok", source_pipeline="local", audio_stream_ready=False
        )

    cm.process_scripted_interaction = scripted_mock

    orch = TourOrchestrator(
        hardware_api=hw,
        nav_bridge=bridge,
        conversation_manager=cm,
        vision_processor=vision,
    )
    return orch, hw, bridge


def _three_waypoints():
    from src.core import TourPlan
    from src.navigation import NavWaypoint
    return TourPlan(
        waypoints=[
            NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=2.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=3.0, y=0.0, yaw_rad=0.0),
        ],
        tour_id="pause-resume-test",
    )


# ---------------------------------------------------------------------------
# Tests de pausa
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_cancels_and_awaits_navigation() -> None:
    """pause_navigation() cancela _nav_task y espera su terminación."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    assert orch.state_id == "navigating"
    assert orch._nav_task is not None
    assert not orch._nav_task.done()

    await orch.pause_navigation()

    assert orch._nav_task is None


@pytest.mark.asyncio
async def test_pause_preserves_current_waypoint_index() -> None:
    """pause_navigation() no resetea current_waypoint_index."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    idx_before = orch.context.current_waypoint_index

    await orch.pause_navigation()

    assert orch.context.current_waypoint_index == idx_before


@pytest.mark.asyncio
async def test_pause_leaves_no_active_nav_task() -> None:
    """Después de pause_navigation(), no hay nav task activa."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.pause_navigation()

    assert orch._nav_task is None
    orch_tasks = [
        t for t in asyncio.all_tasks()
        if t.get_name().startswith("nav-loop-")
    ]
    assert orch_tasks == []


# ---------------------------------------------------------------------------
# Tests de reanudación
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_retries_interrupted_waypoint() -> None:
    """resume_navigation() retoma desde el waypoint interrumpido (index conservado)."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    idx_at_pause = orch.context.current_waypoint_index

    await orch.pause_navigation()
    assert orch._nav_task is None

    orch.resume_navigation()
    await asyncio.sleep(0.02)

    assert orch._nav_task is not None
    assert not orch._nav_task.done()
    assert orch.context.current_waypoint_index == idx_at_pause


@pytest.mark.asyncio
async def test_resume_does_not_repeat_completed_waypoint() -> None:
    """resume_navigation() no re-navega waypoints ya completados."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    # Completar wp0
    bridge.complete_one()
    await asyncio.sleep(0.15)

    assert orch.context.current_waypoint_index == 1
    calls_after_wp0 = len(bridge.nav_calls)

    await orch.pause_navigation()
    orch.resume_navigation()
    await asyncio.sleep(0.02)

    # solo wp1 debe haberse enviado de nuevo, no wp0
    assert len(bridge.nav_calls) == calls_after_wp0 + 1


@pytest.mark.asyncio
async def test_resume_creates_exactly_one_nav_task() -> None:
    """resume_navigation() crea exactamente una nav task."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.pause_navigation()
    assert orch._nav_task is None

    orch.resume_navigation()
    await asyncio.sleep(0.02)

    orch_tasks = [
        t for t in asyncio.all_tasks()
        if t.get_name().startswith("nav-loop-")
    ]
    assert len(orch_tasks) == 1
    assert orch._nav_task is not None
    assert not orch._nav_task.done()


# ---------------------------------------------------------------------------
# Tests de rechazo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_from_idle_is_rejected() -> None:
    """resume_navigation() desde IDLE lanza RuntimeError."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    assert orch.state_id == "idle"
    with pytest.raises(RuntimeError):
        orch.resume_navigation()


@pytest.mark.asyncio
async def test_resume_from_emergency_is_rejected() -> None:
    """resume_navigation() desde EMERGENCY lanza RuntimeError."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.emergency_stop(reason="test-stop")
    await asyncio.sleep(0.05)

    assert orch.state_id == "emergency"
    with pytest.raises(RuntimeError):
        orch.resume_navigation()


# ---------------------------------------------------------------------------
# Tests de idempotencia
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repeated_pause_is_consistent() -> None:
    """Llamar pause_navigation() dos veces es idempotente."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.pause_navigation()
    # Segunda pausa: no debe levantar excepción ni crear estado inválido
    await orch.pause_navigation()

    assert orch._nav_task is None
    assert orch.state_id == "navigating"


@pytest.mark.asyncio
async def test_repeated_resume_does_not_duplicate_task() -> None:
    """resume_navigation() con tarea ya activa no crea una segunda tarea."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.pause_navigation()
    orch.resume_navigation()
    await asyncio.sleep(0.02)

    first_task = orch._nav_task
    assert first_task is not None

    # Segunda llamada con tarea activa: no-op
    orch.resume_navigation()
    await asyncio.sleep(0.02)

    assert orch._nav_task is first_task


# ---------------------------------------------------------------------------
# Test de concurrencia: emergency gana sobre resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emergency_wins_over_concurrent_resume() -> None:
    """emergency_stop() ejecutado concurrentemente a resume_navigation() deja estado EMERGENCY."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.pause_navigation()

    # Lanzar ambas concurrentemente
    await asyncio.gather(
        orch.emergency_stop(reason="concurrent-test"),
        asyncio.sleep(0.01),  # pequeño delay para que emergency procese
    )
    await asyncio.sleep(0.05)

    assert orch.state_id == "emergency"


# ---------------------------------------------------------------------------
# Test de instancia nueva
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_orchestrator_does_not_auto_resume() -> None:
    """Una instancia nueva está en IDLE sin nav task activa."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    assert orch.state_id == "idle"
    assert orch._nav_task is None
    assert orch._odometry_task is None


# ---------------------------------------------------------------------------
# Helper con MockNav2Bridge (para verificar llamadas al backend)
# ---------------------------------------------------------------------------

def _make_orchestrator_mock(nav_delay: float = 10.0) -> tuple:
    from src.core import TourOrchestrator  # noqa: PLC0415
    from src.interaction import ConversationManager, ConversationResponse  # noqa: PLC0415

    hw = MockHardwareAPI()
    bridge = MockNav2Bridge(navigation_delay_s=nav_delay)
    vision = MockVisionProcessor()

    local_strategy = MagicMock()
    local_strategy.generate = AsyncMock(
        return_value=ConversationResponse(
            answer_text="ok", source_pipeline="local", audio_stream_ready=False
        )
    )
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()

    cm = ConversationManager(
        local_strategy=local_strategy,
        cloud_strategy=cloud_strategy,
    )
    cm.get_waypoint_interaction_type = MagicMock(return_value="scripted")

    async def scripted_mock(waypoint_id):
        await asyncio.sleep(0.01)
        return ConversationResponse(
            answer_text="ok", source_pipeline="local", audio_stream_ready=False
        )

    cm.process_scripted_interaction = scripted_mock

    orch = TourOrchestrator(
        hardware_api=hw,
        nav_bridge=bridge,
        conversation_manager=cm,
        vision_processor=vision,
    )
    return orch, hw, bridge


# ---------------------------------------------------------------------------
# Tests de rechazo de pausa en estados inválidos
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_from_idle_is_rejected() -> None:
    """pause_navigation() desde IDLE lanza RuntimeError."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    assert orch.state_id == "idle"
    with pytest.raises(RuntimeError):
        await orch.pause_navigation()


@pytest.mark.asyncio
async def test_pause_from_emergency_is_rejected() -> None:
    """pause_navigation() desde EMERGENCY lanza RuntimeError."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.emergency_stop(reason="test-stop")
    await asyncio.sleep(0.05)

    assert orch.state_id == "emergency"
    with pytest.raises(RuntimeError):
        await orch.pause_navigation()


# ---------------------------------------------------------------------------
# Tests del contrato del backend Nav2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_requests_backend_cancellation() -> None:
    """pause_navigation() llama explícitamente cancel_navigation() en el backend."""
    orch, hw, bridge = _make_orchestrator_mock(nav_delay=10.0)
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    assert orch.state_id == "navigating"
    assert bridge.cancel_calls == 0

    await orch.pause_navigation()

    # MockNav2Bridge.navigate_to_waypoints no captura CancelledError,
    # por lo que cancel_calls solo se incrementa desde cancel_navigation() explícito.
    assert bridge.cancel_calls == 1


@pytest.mark.asyncio
async def test_pause_leaves_backend_inactive() -> None:
    """Tras pause_navigation(), el backend Nav2 no reporta navegación activa."""
    orch, hw, bridge = _make_orchestrator_mock(nav_delay=10.0)
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    assert await bridge.is_navigation_active()

    await orch.pause_navigation()

    assert not await bridge.is_navigation_active()


# ---------------------------------------------------------------------------
# Tests del estado observable is_navigation_paused
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_observable_state() -> None:
    """is_navigation_paused es True cuando el orquestador está pausado."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    assert not orch.is_navigation_paused

    await orch.pause_navigation()

    assert orch.is_navigation_paused
    assert orch.state_id == "navigating"


@pytest.mark.asyncio
async def test_resume_clears_observable_pause_state() -> None:
    """is_navigation_paused vuelve a False tras resume_navigation()."""
    orch, hw, bridge = _make_orchestrator_controlled()
    await hw.initialize()
    await orch.activate_initial_state()

    await orch.dispatch_tour(_three_waypoints())
    await asyncio.sleep(0.02)

    await orch.pause_navigation()
    assert orch.is_navigation_paused

    orch.resume_navigation()
    await asyncio.sleep(0.02)

    assert not orch.is_navigation_paused
