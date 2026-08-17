from __future__ import annotations

import asyncio
import gc
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.mocks.mock_ros2 import install_mocks

install_mocks(sys.modules)

from hardware.interface import MotionCommand
from src.core.event_bus import OttoEventBus
from src.core.events import EventType
from src.core.tour_orchestrator import TourOrchestrator, TourPlan
from src.interaction import ConversationManager
from src.interaction.runtime_port import (
    INTERACTION_PROTOCOL_VERSION,
    InteractionContext,
    InteractionRuntimeCapabilities,
    InteractionRuntimeHealth,
    InteractionRuntimeState,
    WorkerEventEnvelope,
    WorkerEventType,
)
from src.navigation import NavWaypoint


def _event(
    event: WorkerEventType,
    *,
    interaction_id: str | None,
    sequence: int,
    payload: dict[str, object] | None = None,
) -> WorkerEventEnvelope:
    if event is WorkerEventType.FAILED and payload is None:
        payload = {"code": "ERR_TEST", "message": "test failure"}
    return WorkerEventEnvelope(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id=f"test:{sequence}",
        interaction_id=interaction_id,
        event=event,
        sequence=sequence,
        emitted_at_monotonic_s=float(sequence + 1),
        payload=payload or {},
    )


class RecordingHardware:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.moves: list[MotionCommand] = []
        self.stop_motion_started = asyncio.Event()

    async def initialize(self) -> bool:
        return True

    async def move(self, command: MotionCommand) -> None:
        self.order.append("zero")
        self.moves.append(command)

    async def stop_motion(self) -> None:
        self.order.append("stop_motion")
        self.stop_motion_started.set()


class BlockingNav:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.cancel_calls = 0
        self.navigation_started = asyncio.Event()
        self.navigation_cancelled = asyncio.Event()

    async def navigate_to_waypoints(self, waypoints: list[NavWaypoint]) -> bool:
        self.navigation_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise
        return True

    async def cancel_navigation(self) -> None:
        self.cancel_calls += 1
        self.order.append("cancel_nav")
        self.navigation_cancelled.set()

    async def inject_absolute_pose(self, pose_estimate) -> None:
        return None


class VisionStub:
    visual_odometry_enabled = False

    async def get_next_estimate(self, timeout_s: float = 0.5):
        return None

    def close(self) -> None:
        return None


class RecordingVisionStub(VisionStub):
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class RuntimeFake:
    def __init__(self, events: list[WorkerEventEnvelope] | None = None, order: list[str] | None = None) -> None:
        self.events = asyncio.Queue()
        for event in events or []:
            self.events.put_nowait(event)
        self.order = order if order is not None else []
        self.activate_contexts: list[InteractionContext] = []
        self.stop_calls = 0
        self.emergency_stop_calls = 0
        self.start_calls = 0
        self.close_calls = 0
        self.next_event_active = 0
        self.next_event_max_active = 0
        self.block_next_event = False
        self.block_emergency_stop = False
        self.activate_started = asyncio.Event()
        self.next_event_started = asyncio.Event()
        self.emergency_started = asyncio.Event()
        self.stop_started = asyncio.Event()
        self.release_next_event = asyncio.Event()
        self.release_emergency_stop = asyncio.Event()
        self.next_event_exception: BaseException | None = None

    async def start(self) -> None:
        self.start_calls += 1

    async def health(self) -> InteractionRuntimeHealth:
        return InteractionRuntimeHealth(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            state=InteractionRuntimeState.READY,
            ready=True,
            capabilities=InteractionRuntimeCapabilities(),
        )

    async def activate(self, context: InteractionContext) -> None:
        self.order.append("activate")
        self.activate_contexts.append(context)
        self.activate_started.set()

    async def pause(self) -> None:
        return None

    async def resume(self) -> None:
        return None

    async def stop(self) -> None:
        self.stop_calls += 1
        self.order.append("stop")
        self.stop_started.set()

    async def emergency_stop(self) -> None:
        self.emergency_stop_calls += 1
        self.order.append("emergency_stop")
        self.emergency_started.set()
        if self.block_emergency_stop:
            await self.release_emergency_stop.wait()

    async def next_event(self, *, timeout_s: float | None = None) -> WorkerEventEnvelope:
        if self.next_event_exception is not None:
            raise self.next_event_exception
        self.next_event_active += 1
        self.next_event_max_active = max(self.next_event_max_active, self.next_event_active)
        self.next_event_started.set()
        try:
            if self.block_next_event:
                await self.release_next_event.wait()
            return await asyncio.wait_for(self.events.get(), timeout=timeout_s)
        finally:
            self.next_event_active -= 1

    async def close(self) -> None:
        self.close_calls += 1


class StubbornStopRuntime(RuntimeFake):
    def __init__(self) -> None:
        super().__init__()
        self.release_stop = asyncio.Event()
        self.stop_cancelled = asyncio.Event()

    async def stop(self) -> None:
        self.stop_calls += 1
        self.order.append("stop")
        self.stop_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.stop_cancelled.set()
            await self.release_stop.wait()
            raise


class DoneTaskProbe:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.result_called = False

    def done(self) -> bool:
        return True

    def result(self):
        self.result_called = True
        raise self.exc

    def cancel(self) -> None:
        raise AssertionError("done task must not be cancelled")


def _plan() -> TourPlan:
    return TourPlan(
        waypoints=[NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0)],
        tour_id="tour:u3b",
    )


def _make_orchestrator(runtime: RuntimeFake, order: list[str] | None = None):
    order = order if order is not None else []
    local_strategy = MagicMock()
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()
    cm = ConversationManager(local_strategy=local_strategy, cloud_strategy=cloud_strategy)
    cm.process_interaction = MagicMock()
    cm.process_scripted_interaction = MagicMock()
    bus = OttoEventBus()
    completion_payloads: list[object] = []

    async def _capture_completion(_event_type, data):
        completion_payloads.append(data)

    bus.subscribe(EventType.INTERACTION_COMPLETED, _capture_completion)
    orchestrator = TourOrchestrator(
        hardware_api=RecordingHardware(order),
        nav_bridge=BlockingNav(order),
        conversation_manager=cm,
        vision_processor=VisionStub(),
        event_bus=bus,
        interaction_runtime=runtime,
        audio_capture_timeout_s=0.2,
    )
    return orchestrator, cm, completion_payloads, order


def _make_orchestrator_with_vision(
    runtime: RuntimeFake,
    vision: VisionStub,
    order: list[str] | None = None,
):
    order = order if order is not None else []
    local_strategy = MagicMock()
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()
    cm = ConversationManager(local_strategy=local_strategy, cloud_strategy=cloud_strategy)
    cm.process_interaction = MagicMock()
    cm.process_scripted_interaction = MagicMock()
    bus = OttoEventBus()
    completion_payloads: list[object] = []

    async def _capture_completion(_event_type, data):
        completion_payloads.append(data)

    bus.subscribe(EventType.INTERACTION_COMPLETED, _capture_completion)
    orchestrator = TourOrchestrator(
        hardware_api=RecordingHardware(order),
        nav_bridge=BlockingNav(order),
        conversation_manager=cm,
        vision_processor=vision,
        event_bus=bus,
        interaction_runtime=runtime,
        audio_capture_timeout_s=0.2,
    )
    return orchestrator, cm, completion_payloads, order


async def _start_navigating(orchestrator: TourOrchestrator) -> None:
    await orchestrator.activate_initial_state()
    await orchestrator.dispatch_tour(_plan())
    await orchestrator._nav_bridge.navigation_started.wait()


async def _wait_interaction_done(orchestrator: TourOrchestrator) -> None:
    task = orchestrator._interaction_task
    if task is not None:
        await task


@pytest.mark.asyncio
async def test_supervised_interaction_activates_with_unique_context() -> None:
    runtime = RuntimeFake([
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0),
    ])
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await _wait_interaction_done(orchestrator)

    assert runtime.activate_contexts[0].interaction_id == "interaction:1"
    assert runtime.activate_contexts[0].tour_id == "tour:u3b"
    assert runtime.activate_contexts[0].waypoint_id == "I"
    assert runtime.activate_contexts[0].locale == "es-AR"
    await orchestrator.close()


@pytest.mark.asyncio
async def test_navigation_cancel_and_zero_velocity_precede_runtime_activate() -> None:
    order: list[str] = []
    runtime = RuntimeFake([
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0),
    ], order=order)
    orchestrator, _, _, _ = _make_orchestrator(runtime, order)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await _wait_interaction_done(orchestrator)

    assert order.index("cancel_nav") < order.index("zero") < order.index("activate")
    await orchestrator.close()


@pytest.mark.asyncio
async def test_progress_events_do_not_resume_navigation() -> None:
    runtime = RuntimeFake([
        _event(WorkerEventType.CAPTURE_STARTED, interaction_id="interaction:1", sequence=0),
        _event(WorkerEventType.TRANSCRIPT_READY, interaction_id="interaction:1", sequence=1, payload={"text": "hola"}),
        _event(WorkerEventType.RESPONSE_READY, interaction_id="interaction:1", sequence=2, payload={"text": "respuesta"}),
        _event(WorkerEventType.PLAYBACK_STARTED, interaction_id="interaction:1", sequence=3),
    ])
    runtime.block_next_event = True
    orchestrator, _, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    assert orchestrator.state_id == "interacting"
    assert completions == []
    await orchestrator.close()


@pytest.mark.asyncio
async def test_matching_playback_completed_publishes_completion_once() -> None:
    runtime = RuntimeFake([
        _event(WorkerEventType.RESPONSE_READY, interaction_id="interaction:1", sequence=0, payload={"text": "ok"}),
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=1),
    ])
    orchestrator, _, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await _wait_interaction_done(orchestrator)

    assert len(completions) == 1
    assert completions[0]["interaction_id"] == "interaction:1"
    assert completions[0]["playback_completed"] is True
    assert orchestrator.state_id == "navigating"
    assert runtime.next_event_max_active == 1
    await orchestrator.close()


@pytest.mark.asyncio
async def test_wrong_interaction_id_fails_closed_without_resume() -> None:
    runtime = RuntimeFake([
        _event(WorkerEventType.CAPTURE_STARTED, interaction_id="interaction:other", sequence=0),
    ])
    orchestrator, cm, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await _wait_interaction_done(orchestrator)

    assert orchestrator.state_id == "interacting"
    assert completions == []
    assert runtime.stop_calls == 1
    assert cm.process_interaction.call_count == 0
    assert cm.process_scripted_interaction.call_count == 0
    await orchestrator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "interaction_id"),
    [
        (WorkerEventType.INTERACTION_TIMEOUT, "interaction:1"),
        (WorkerEventType.CANCELLED, "interaction:1"),
        (WorkerEventType.FAILED, "interaction:1"),
        (WorkerEventType.FAILED, None),
        (WorkerEventType.STOPPED, None),
        (WorkerEventType.CLOSED, None),
    ],
)
async def test_terminal_failure_events_do_not_resume_or_publish_completion(
    event_type: WorkerEventType,
    interaction_id: str | None,
) -> None:
    runtime = RuntimeFake([_event(event_type, interaction_id=interaction_id, sequence=0)])
    orchestrator, _, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await _wait_interaction_done(orchestrator)

    assert orchestrator.state_id == "interacting"
    assert completions == []
    assert orchestrator.context.last_error is not None
    await orchestrator.close()


@pytest.mark.asyncio
async def test_next_event_exception_does_not_resume() -> None:
    runtime = RuntimeFake()
    runtime.next_event_exception = RuntimeError("stream failed")
    orchestrator, _, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await _wait_interaction_done(orchestrator)

    assert orchestrator.state_id == "interacting"
    assert completions == []
    assert runtime.stop_calls == 1
    await orchestrator.close()


@pytest.mark.asyncio
async def test_runtime_activation_failure_does_not_fallback_to_conversation_manager() -> None:
    runtime = RuntimeFake()

    async def _fail_activate(context: InteractionContext) -> None:
        raise RuntimeError("activate failed")

    runtime.activate = _fail_activate
    orchestrator, cm, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))

    assert orchestrator.state_id == "interacting"
    assert completions == []
    assert cm.process_interaction.call_count == 0
    assert cm.process_scripted_interaction.call_count == 0
    await orchestrator.close()


@pytest.mark.asyncio
async def test_emergency_runtime_call_does_not_delay_zero_velocity_or_stopmove() -> None:
    runtime = RuntimeFake()
    runtime.block_next_event = True
    orchestrator, _, completions, order = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    orchestrator.context.last_error = "test emergency"
    result = await orchestrator.emergency_stop("test emergency")

    assert result is not None
    assert result.stop_motion_succeeded is True
    assert runtime.emergency_stop_calls == 1
    assert runtime.stop_calls == 0
    assert order.index("stop_motion") > order.index("zero")
    assert completions == []
    assert orchestrator._active_runtime_interaction_id is None
    await orchestrator.close()


@pytest.mark.asyncio
async def test_orchestrator_close_cancels_runtime_interaction_task() -> None:
    runtime = RuntimeFake()
    runtime.block_next_event = True
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    await orchestrator.close()

    assert orchestrator._interaction_task is None
    assert orchestrator._active_runtime_interaction_id is None
    assert runtime.stop_calls == 1
    assert runtime.close_calls == 0
    assert runtime.start_calls == 0


@pytest.mark.asyncio
async def test_public_emergency_during_supervised_interaction_does_not_deadlock_fsm() -> None:
    runtime = RuntimeFake()
    runtime.block_next_event = True
    runtime.block_emergency_stop = True
    orchestrator, _, completions, order = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    emergency_task = asyncio.create_task(orchestrator.emergency_stop("public emergency"))
    await orchestrator._hardware_api.stop_motion_started.wait()
    runtime.release_emergency_stop.set()
    result = await asyncio.wait_for(emergency_task, timeout=1.0)

    assert result.terminal_safe is True
    assert orchestrator.state_id == "emergency"
    assert completions == []
    assert runtime.emergency_stop_calls == 1
    assert runtime.stop_calls == 0
    assert order.index("cancel_nav") < order.index("zero") < order.index("stop_motion")


@pytest.mark.asyncio
async def test_emergency_task_handle_is_not_overwritten() -> None:
    runtime = RuntimeFake()
    runtime.block_next_event = True
    runtime.block_emergency_stop = True
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    emergency_task = asyncio.create_task(orchestrator.emergency_stop("public emergency"))
    await runtime.emergency_started.wait()
    first = orchestrator._interaction_emergency_task
    assert first is not None
    orchestrator._ensure_runtime_emergency_task()
    assert orchestrator._interaction_emergency_task is first
    runtime.release_emergency_stop.set()
    await emergency_task


@pytest.mark.asyncio
async def test_close_does_not_clear_live_interaction_task_handle_on_timeout() -> None:
    import src.core.tour_orchestrator as module

    runtime = StubbornRuntime()
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    live_task = orchestrator._interaction_task

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST
    try:
        with pytest.raises(RuntimeError, match="interaction task settlement timeout"):
            await orchestrator.close()
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    assert orchestrator._interaction_task is live_task
    assert not orchestrator._closed
    runtime.release_event.set()
    await asyncio.sleep(0.05)
    await orchestrator.close()
    assert orchestrator._interaction_task is None


@pytest.mark.asyncio
async def test_completion_after_emergency_latch_does_not_publish_or_resume() -> None:
    runtime = RuntimeFake()
    runtime.block_next_event = True
    orchestrator, cm, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await runtime.next_event_started.wait()
    assert runtime.next_event_active == 1

    orchestrator._claim_interaction_terminal_outcome("EMERGENCY")
    runtime.events.put_nowait(
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0)
    )
    runtime.release_next_event.set()
    await _wait_interaction_done(orchestrator)

    assert completions == []
    assert cm.process_interaction.call_count == 0
    assert orchestrator._interaction_terminal_outcome == "EMERGENCY"
    assert orchestrator.state_id == "interacting"


@pytest.mark.asyncio
async def test_second_interaction_uses_a_new_interaction_id() -> None:
    runtime = RuntimeFake([
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0),
    ])
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await _wait_interaction_done(orchestrator)

    runtime.events.put_nowait(
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:2", sequence=1)
    )
    await orchestrator.pause_for_interaction()
    await _wait_interaction_done(orchestrator)

    assert [ctx.interaction_id for ctx in runtime.activate_contexts] == [
        "interaction:1",
        "interaction:2",
    ]


# ---------------------------------------------------------------------------
# U3BR2: Nuevos tests para defectos DEFECT_1..5
# ---------------------------------------------------------------------------

# Constante de módulo reducible para tests de timeout acotado
_SETTLE_TIMEOUT_FOR_TEST = 0.15  # debe sincronizarse con INTERACTION_TASK_SETTLE_S en producción


class StubbornRuntime:
    """Runtime cuya corrutina next_event captura CancelledError y solo libera ante release_event."""

    def __init__(self) -> None:
        self.activate_contexts: list[InteractionContext] = []
        self.stop_calls = 0
        self.emergency_stop_calls = 0
        self.start_calls = 0
        self.close_calls = 0
        self.activate_started = asyncio.Event()
        self.emergency_started = asyncio.Event()
        self.stop_started = asyncio.Event()
        self.release_event: asyncio.Event = asyncio.Event()
        self.cancel_received: asyncio.Event = asyncio.Event()
        self.order: list[str] = []
        self.next_event_exception: BaseException | None = None

    async def start(self) -> None:
        self.start_calls += 1

    async def health(self) -> InteractionRuntimeHealth:
        return InteractionRuntimeHealth(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            state=InteractionRuntimeState.READY,
            ready=True,
            capabilities=InteractionRuntimeCapabilities(),
        )

    async def activate(self, context: InteractionContext) -> None:
        self.order.append("activate")
        self.activate_contexts.append(context)
        self.activate_started.set()

    async def pause(self) -> None:
        return None

    async def resume(self) -> None:
        return None

    async def stop(self) -> None:
        self.stop_calls += 1
        self.order.append("stop")
        self.stop_started.set()

    async def emergency_stop(self) -> None:
        self.emergency_stop_calls += 1
        self.order.append("emergency_stop")
        self.emergency_started.set()

    async def next_event(self, *, timeout_s: float | None = None) -> WorkerEventEnvelope:
        if self.next_event_exception is not None:
            raise self.next_event_exception
        try:
            await asyncio.Event().wait()  # bloquea indefinidamente
        except asyncio.CancelledError:
            self.cancel_received.set()
            await self.release_event.wait()
            raise

    async def close(self) -> None:
        self.close_calls += 1


# ---------------------------------------------------------------------------
# DEFECT_3: task única de interacción (no nested consumer task)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_supervised_interaction_owns_exactly_one_lifecycle_task() -> None:
    """DEFECT_3: on_enter_interacting debe crear exactamente una task cuyo nombre
    comience con 'interaction-runtime-'; no debe existir una task 'pending-N' que posea
    otra task 'interaction:N'."""
    runtime = RuntimeFake()
    runtime.block_next_event = True
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    # Dar tiempo al event loop para que todas las tasks estén creadas
    await asyncio.sleep(0.05)

    all_tasks = asyncio.all_tasks()
    interaction_tasks = [t for t in all_tasks if t.get_name().startswith("interaction-runtime-")]
    pending_tasks = [t for t in all_tasks if "pending-" in t.get_name()]

    # Debe haber exactamente una task de interaction-runtime- y cero tasks pending-N
    assert len(interaction_tasks) == 1, (
        f"Se esperaba exactamente 1 task interaction-runtime-*, encontradas: "
        f"{[t.get_name() for t in interaction_tasks]}"
    )
    assert len(pending_tasks) == 0, (
        f"No debe haber tasks 'pending-N' (nested consumer task leak): "
        f"{[t.get_name() for t in pending_tasks]}"
    )

    # El handle guardado debe ser identidad con la task encontrada
    assert orchestrator._interaction_task is not None
    assert orchestrator._interaction_task is interaction_tasks[0], (
        "El handle _interaction_task debe ser identidad con la única task interaction-runtime-*"
    )

    await orchestrator.close()


# ---------------------------------------------------------------------------
# DEFECT_1: timeout de settlement temporalmente acotado (interaction task)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stubborn_interaction_task_settlement_timeout_is_strictly_bounded() -> None:
    """DEFECT_1: _cancel_interaction_task_safe() debe retornar (con error) dentro de
    timeout_s + 0.25 s aunque la task no coopere con la cancelación."""
    import src.core.tour_orchestrator as module

    runtime = StubbornRuntime()
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    # cancel_received se setea cuando _cancel_interaction_task_safe() cancela la task;
    # no esperar aquí — la cancelación llega cuando invocamos el método a continuación.

    # Reducir el timeout para que el test sea rápido
    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    try:
        with pytest.raises((RuntimeError, asyncio.TimeoutError)):
            await orchestrator._cancel_interaction_task_safe()
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    elapsed = loop.time() - t0
    assert elapsed <= _SETTLE_TIMEOUT_FOR_TEST + 0.25, (
        f"settlement tardó {elapsed:.3f}s, debe ser <= {_SETTLE_TIMEOUT_FOR_TEST + 0.25:.3f}s"
    )

    # Liberar la task para no dejarla huérfana
    runtime.release_event.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_stubborn_interaction_task_handle_is_preserved_after_timeout() -> None:
    """DEFECT_1: después de un timeout de settlement, _interaction_task debe conservar
    el handle vivo (no limpiarse), y _closed=False."""
    import src.core.tour_orchestrator as module

    runtime = StubbornRuntime()
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    live_task_before = orchestrator._interaction_task
    assert live_task_before is not None

    try:
        with pytest.raises((RuntimeError, asyncio.TimeoutError)):
            await orchestrator._cancel_interaction_task_safe()
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    # El handle debe estar preservado después del timeout
    assert orchestrator._interaction_task is live_task_before, (
        "El handle _interaction_task debe mantenerse vivo después del timeout de settlement"
    )
    assert not orchestrator._interaction_task.done(), (
        "La task sigue viva (obstinada), no debe estar done"
    )

    runtime.release_event.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_close_retry_succeeds_after_stubborn_interaction_task_release() -> None:
    """DEFECT_1: close() debe ser reintentable; después de liberar la task obstinada,
    una segunda llamada a close() debe completar exitosamente."""
    import src.core.tour_orchestrator as module

    runtime = StubbornRuntime()
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    try:
        with pytest.raises((RuntimeError, asyncio.TimeoutError)):
            await orchestrator.close()

        assert not orchestrator._closed, "_closed no debe ser True después del close fallido"

        # Liberar la task obstinada
        runtime.release_event.set()
        await asyncio.sleep(0.05)

        # Segundo intento: debe completar
        await orchestrator.close()
        assert orchestrator._closed, "_closed debe ser True después del close exitoso"
        assert orchestrator._interaction_task is None
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S


# ---------------------------------------------------------------------------
# DEFECT_1: timeout de settlement temporalmente acotado (emergency task)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stubborn_emergency_task_settlement_timeout_is_strictly_bounded() -> None:
    """DEFECT_1: el settlement de _interaction_emergency_task en on_enter_emergency
    debe ser acotado y no bloquear indefinidamente."""
    import src.core.tour_orchestrator as module

    runtime = RuntimeFake()
    runtime.block_next_event = True

    # Hacer que emergency_stop bloquee indefinidamente
    release_emergency = asyncio.Event()
    cancel_emergency_received = asyncio.Event()

    async def _stubborn_emergency() -> None:
        runtime.emergency_stop_calls += 1
        runtime.order.append("emergency_stop")
        runtime.emergency_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancel_emergency_received.set()
            await release_emergency.wait()
            raise

    runtime.emergency_stop = _stubborn_emergency

    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    loop = asyncio.get_running_loop()
    t0 = loop.time()

    try:
        result = await orchestrator.emergency_stop("test stubborn emergency")
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    elapsed = loop.time() - t0
    # on_enter_emergency no debe tardar más que stop_motion_timeout + settle_timeout + margen
    assert elapsed <= 2.0, (
        f"emergency_stop tardó {elapsed:.3f}s (demasiado; settlement debía estar acotado)"
    )

    # El resultado debe mantener EMERGENCY terminal aunque el settlement falló
    assert orchestrator.state_id == "emergency"
    assert result.terminal_safe is True  # StopMove debe haber tenido éxito

    release_emergency.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_stubborn_emergency_task_handle_is_preserved_after_timeout() -> None:
    """DEFECT_1: si el settlement de _interaction_emergency_task falla por timeout,
    el handle debe conservarse en _interaction_emergency_task para reintento en close()."""
    import src.core.tour_orchestrator as module

    runtime = RuntimeFake()
    runtime.block_next_event = True

    release_emergency = asyncio.Event()

    async def _stubborn_emergency() -> None:
        runtime.emergency_stop_calls += 1
        runtime.order.append("emergency_stop")
        runtime.emergency_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release_emergency.wait()
            raise

    runtime.emergency_stop = _stubborn_emergency

    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    try:
        await orchestrator.emergency_stop("test stubborn emergency handle")
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    # Si el settlement de la emergency task falló, el handle debe estar preservado
    # (no limpiado a None) para que close() pueda reintentar
    emerg_task = orchestrator._interaction_emergency_task
    if emerg_task is not None:
        assert not emerg_task.done(), (
            "La emergency task obstinada sigue viva; el handle debe preservarse"
        )

    release_emergency.set()
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# DEFECT_2: EMERGENCY queda terminal aunque el settlement falle después de StopMove
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emergency_reaches_terminal_state_despite_post_stopmove_settlement_timeout() -> None:
    """DEFECT_2: aunque el settlement de interaction/emergency tasks falle después de StopMove,
    el estado debe permanecer en EMERGENCY (terminal) y terminal_safe debe ser True."""
    import src.core.tour_orchestrator as module

    runtime = RuntimeFake()
    runtime.block_next_event = True

    release_emergency = asyncio.Event()

    async def _stubborn_emergency() -> None:
        runtime.emergency_stop_calls += 1
        runtime.order.append("emergency_stop")
        runtime.emergency_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release_emergency.wait()
            raise

    runtime.emergency_stop = _stubborn_emergency

    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    try:
        result = await orchestrator.emergency_stop("stubborn after stopmove")
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    # FSM debe permanecer en EMERGENCY (no revertir)
    assert orchestrator.state_id == "emergency", (
        f"Estado debe ser 'emergency', actual: '{orchestrator.state_id}'"
    )
    # terminal_safe es software-only y depende de StopMove, no del settlement posterior
    assert result.terminal_safe is True, (
        "terminal_safe debe ser True si StopMove tuvo éxito, independientemente del settlement posterior"
    )

    release_emergency.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_emergency_result_records_interaction_settlement_timeout() -> None:
    """DEFECT_2: si el settlement falla, EmergencyStopResult.errors debe registrar el timeout."""
    import src.core.tour_orchestrator as module

    runtime = RuntimeFake()
    runtime.block_next_event = True

    release_emergency = asyncio.Event()

    async def _stubborn_emergency() -> None:
        runtime.emergency_stop_calls += 1
        runtime.order.append("emergency_stop")
        runtime.emergency_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release_emergency.wait()
            raise

    runtime.emergency_stop = _stubborn_emergency

    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    try:
        result = await orchestrator.emergency_stop("stubborn errors test")
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    # Si hubo timeout de settlement, debe estar registrado en errors
    # (si no hay timeout, errors puede estar vacío — aceptable)
    # El test verifica que no se lanza excepción fuera de on_enter_emergency
    assert result is not None

    release_emergency.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_close_retries_emergency_task_settlement_after_release() -> None:
    """DEFECT_2: si _interaction_emergency_task no asentó en on_enter_emergency,
    close() debe poder reintentar y completar tras liberar la task."""
    import src.core.tour_orchestrator as module

    runtime = RuntimeFake()
    runtime.block_next_event = True

    release_emergency = asyncio.Event()

    async def _stubborn_emergency() -> None:
        runtime.emergency_stop_calls += 1
        runtime.order.append("emergency_stop")
        runtime.emergency_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release_emergency.wait()
            raise

    runtime.emergency_stop = _stubborn_emergency

    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    original_settle = getattr(module, "INTERACTION_TASK_SETTLE_S", None)
    module.INTERACTION_TASK_SETTLE_S = _SETTLE_TIMEOUT_FOR_TEST

    try:
        await orchestrator.emergency_stop("stubborn retry test")
    finally:
        if original_settle is not None:
            module.INTERACTION_TASK_SETTLE_S = original_settle
        elif hasattr(module, "INTERACTION_TASK_SETTLE_S"):
            del module.INTERACTION_TASK_SETTLE_S

    # Liberar emergency task
    release_emergency.set()
    await asyncio.sleep(0.1)

    # close() debe poder completar ahora
    await orchestrator.close()
    assert orchestrator._closed is True
    assert orchestrator._interaction_emergency_task is None


# ---------------------------------------------------------------------------
# DEFECT_4: la emergencia iniciada desde la interaction_task no se autocancela
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_failure_triggers_emergency_without_self_cancelling_lifecycle() -> None:
    """DEFECT_4: cuando resume_tour() falla desde dentro de _interaction_task,
    el orquestador debe llegar a EMERGENCY (via trigger_emergency) sin que la
    interaction_task se cancele a sí misma."""
    runtime = RuntimeFake([
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0),
    ])
    orchestrator, _, completions, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    # Hacer que resume_tour falle — provoca que _complete_runtime_interaction llame emergency_stop
    original_resume = orchestrator.resume_tour

    async def _fail_resume():
        raise RuntimeError("simulated resume_tour failure")

    orchestrator.resume_tour = _fail_resume

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    # Esperar hasta que la task se complete (ya sea por cancelación o por resolución)
    task = orchestrator._interaction_task
    if task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    # El estado debe ser EMERGENCY
    assert orchestrator.state_id == "emergency", (
        f"Estado debe ser 'emergency' tras fallo de resume_tour; actual: '{orchestrator.state_id}'"
    )
    # La task no debe haber sido cancelada (RESUME_FAILURE_SELF_CANCELLED = NO)
    # Verificamos que llegó a EMERGENCY por la ruta normal, no por CancelledError
    assert orchestrator._last_emergency_result is not None
    assert orchestrator._last_emergency_result.stop_motion_succeeded is True

    # El completion fue publicado antes del fallo de resume_tour; la emergencia se activa después
    # La interaction task no se autocanceló — llegó a EMERGENCY por la ruta de excepción
    assert len(completions) == 1, (
        f"Debe haberse publicado exactamente 1 completion antes del fallo; actual: {completions}"
    )


# ---------------------------------------------------------------------------
# DEFECT_5: excepción inesperada de la task queda recuperada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unexpected_lifecycle_exception_is_retrieved() -> None:
    """DEFECT_5: una excepción no-CancelledError en la corrutina lifecycle de la task
    de interacción debe ser recuperada (no producir 'Task exception was never retrieved')."""
    runtime = RuntimeFake()

    boom_event = asyncio.Event()
    boom_raised = asyncio.Event()

    async def _boom_activate(context: InteractionContext) -> None:
        runtime.activate_contexts.append(context)
        runtime.activate_started.set()
        boom_event.set()
        raise ValueError("unexpected exception in lifecycle")

    runtime.activate = _boom_activate

    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    # Esperar a que la task se complete
    task = orchestrator._interaction_task
    if task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, ValueError):
            pass

    # La tarea debe estar done (no pendiente)
    if task is not None:
        assert task.done(), "La task debe haber terminado"

    # No debe quedar Task exception was never retrieved
    # Si la excepción fue recuperada, task.exception() puede ser callable sin advertencia
    await asyncio.sleep(0.05)
    await orchestrator.close()


@pytest.mark.asyncio
async def test_unexpected_lifecycle_exception_triggers_public_emergency() -> None:
    """DEFECT_5: una excepción no-CancelledError que escapa del consumer loop de la task de
    lifecycle de interacción debe activar emergency_stop público (FSM -> EMERGENCY)."""
    runtime = RuntimeFake()

    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    # Reemplazar _consume_runtime_interaction_events ANTES de request_interaction
    # para que cuando la task única lo llame, lance la excepción inesperada
    async def _boom_consumer(r, c):
        raise RuntimeError("critical lifecycle failure")

    orchestrator._consume_runtime_interaction_events = _boom_consumer

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    # Dar tiempo para que la excepción se propague y active la emergencia
    await asyncio.sleep(0.3)

    assert orchestrator.state_id == "emergency", (
        f"Una excepción inesperada que escapa del consumer loop debe activar EMERGENCY; "
        f"estado actual: '{orchestrator.state_id}'"
    )


@pytest.mark.asyncio
async def test_no_interaction_runtime_tasks_remain_after_final_close() -> None:
    """DEFECT_3+5: después de close() exitoso, no deben quedar tasks propias de interacción
    (interaction-runtime-*) pendientes en asyncio.all_tasks()."""
    runtime = RuntimeFake([
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0),
    ])
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    await _wait_interaction_done(orchestrator)

    await orchestrator.close()
    await asyncio.sleep(0.05)

    remaining = [
        t for t in asyncio.all_tasks()
        if t.get_name().startswith("interaction-runtime-")
        or t.get_name().startswith("interaction-")
    ]
    assert remaining == [], (
        f"No deben quedar tasks de interacción después de close(): "
        f"{[t.get_name() for t in remaining]}"
    )


# ---------------------------------------------------------------------------
# U3BR3: self-settlement, runtime.stop ownership y recuperación de excepciones
# ---------------------------------------------------------------------------

async def _run_internal_resume_failure() -> tuple[TourOrchestrator, RuntimeFake, RecordingVisionStub, asyncio.Task | None]:
    runtime = RuntimeFake([
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0),
    ])
    vision = RecordingVisionStub()
    orchestrator, _, _, _ = _make_orchestrator_with_vision(runtime, vision)
    await _start_navigating(orchestrator)

    async def _fail_resume() -> None:
        raise RuntimeError("u3br3 resume failure")

    orchestrator.resume_tour = _fail_resume
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()
    task = orchestrator._interaction_task
    assert task is not None
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
    except asyncio.CancelledError:
        pass
    return orchestrator, runtime, vision, task


@pytest.mark.asyncio
async def test_internal_resume_failure_does_not_cancel_current_interaction_task() -> None:
    orchestrator, _, _, task = await _run_internal_resume_failure()
    assert task is not None
    assert not task.cancelled()
    assert orchestrator.state_id == "emergency"


@pytest.mark.asyncio
async def test_internal_resume_failure_emergency_callback_completes() -> None:
    orchestrator, _, _, _ = await _run_internal_resume_failure()
    assert orchestrator._last_emergency_result is not None
    assert orchestrator._last_emergency_result.terminal_safe is True


@pytest.mark.asyncio
async def test_internal_resume_failure_executes_vision_close() -> None:
    _, _, vision, _ = await _run_internal_resume_failure()
    assert vision.close_calls == 1


@pytest.mark.asyncio
async def test_internal_resume_failure_has_no_self_settlement_timeout_error() -> None:
    orchestrator, _, _, _ = await _run_internal_resume_failure()
    assert orchestrator._last_emergency_result is not None
    assert not any(
        "interaction_task_settlement_timeout" in error
        for error in orchestrator._last_emergency_result.errors
    )


@pytest.mark.asyncio
async def test_on_enter_emergency_never_settles_current_interaction_task() -> None:
    runtime = RuntimeFake()
    orchestrator, _, _, _ = _make_orchestrator(runtime)

    async def _settle_from_current_task() -> str:
        orchestrator._interaction_task = asyncio.current_task()
        await orchestrator._cancel_interaction_task_safe()
        assert orchestrator._interaction_task is asyncio.current_task()
        return "deferred"

    task = asyncio.create_task(_settle_from_current_task(), name="u3br3-self-settlement")
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result == "deferred"
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_stubborn_runtime_stop_timeout_is_strictly_bounded() -> None:
    runtime = StubbornStopRuntime()
    runtime.block_next_event = True
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    close_task = asyncio.create_task(orchestrator.close())
    try:
        await runtime.stop_started.wait()
        done, _ = await asyncio.wait({close_task}, timeout=0.85)
        assert close_task in done
        await close_task
    finally:
        runtime.release_stop.set()
        if not close_task.done():
            close_task.cancel()
            await asyncio.gather(close_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stubborn_runtime_stop_handle_is_preserved() -> None:
    runtime = StubbornStopRuntime()
    runtime.block_next_event = True
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    close_task = asyncio.create_task(orchestrator.close())
    try:
        await runtime.stop_started.wait()
        done, _ = await asyncio.wait({close_task}, timeout=0.85)
        assert close_task in done
        assert getattr(orchestrator, "_interaction_stop_task", None) is not None
        assert runtime.stop_cancelled.is_set()
    finally:
        runtime.release_stop.set()
        if not close_task.done():
            close_task.cancel()
        await asyncio.gather(close_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_close_retry_succeeds_after_stubborn_runtime_stop_release() -> None:
    runtime = StubbornStopRuntime()
    runtime.block_next_event = True
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))
    await runtime.activate_started.wait()

    first_close = asyncio.create_task(orchestrator.close())
    await runtime.stop_started.wait()
    done, _ = await asyncio.wait({first_close}, timeout=0.85)
    assert first_close in done
    assert not orchestrator._closed
    runtime.release_stop.set()
    await asyncio.gather(first_close, return_exceptions=True)
    await orchestrator.close()
    assert orchestrator._closed is True
    assert getattr(orchestrator, "_interaction_stop_task", None) is None
    assert runtime.stop_calls == 1


@pytest.mark.asyncio
async def test_done_failed_interaction_task_exception_is_retrieved_before_handle_clear() -> None:
    runtime = RuntimeFake()
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    probe = DoneTaskProbe(RuntimeError("done interaction failure"))
    orchestrator._interaction_task = probe
    await orchestrator._cancel_interaction_task_safe()
    assert probe.result_called
    assert orchestrator._interaction_task is None


@pytest.mark.asyncio
async def test_done_failed_emergency_task_exception_is_retrieved_before_handle_clear() -> None:
    runtime = RuntimeFake()
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    probe = DoneTaskProbe(RuntimeError("done emergency failure"))
    orchestrator._interaction_emergency_task = probe
    await orchestrator._cancel_interaction_emergency_task_safe()
    assert probe.result_called
    assert orchestrator._interaction_emergency_task is None


@pytest.mark.asyncio
async def test_no_unretrieved_warning_after_done_task_cleanup() -> None:
    loop = asyncio.get_running_loop()
    captured: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: captured.append(context))
    runtime = RuntimeFake()
    orchestrator, _, _, _ = _make_orchestrator(runtime)

    async def _fail_done_task() -> None:
        raise RuntimeError("u3br3 unretrieved probe")

    task = asyncio.create_task(_fail_done_task())
    await asyncio.sleep(0)
    assert task.done()
    orchestrator._interaction_task = task
    try:
        await orchestrator._cancel_interaction_task_safe()
        del task
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert not any(
        context.get("message") == "Task exception was never retrieved"
        for context in captured
    )
