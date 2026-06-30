from __future__ import annotations

import asyncio
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
        self.damp_started = asyncio.Event()

    async def initialize(self) -> bool:
        return True

    async def move(self, command: MotionCommand) -> None:
        self.order.append("zero")
        self.moves.append(command)

    async def damp(self) -> None:
        self.order.append("damp")
        self.damp_started.set()


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

    async def pause(self) -> None:
        return None

    async def resume(self) -> None:
        return None

    async def stop(self) -> None:
        self.stop_calls += 1

    async def emergency_stop(self) -> None:
        self.emergency_stop_calls += 1
        if self.block_emergency_stop:
            await asyncio.Event().wait()

    async def next_event(self, *, timeout_s: float | None = None) -> WorkerEventEnvelope:
        if self.next_event_exception is not None:
            raise self.next_event_exception
        self.next_event_active += 1
        self.next_event_max_active = max(self.next_event_max_active, self.next_event_active)
        try:
            if self.block_next_event:
                await asyncio.Event().wait()
            return await asyncio.wait_for(self.events.get(), timeout=timeout_s)
        finally:
            self.next_event_active -= 1

    async def close(self) -> None:
        self.close_calls += 1


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


async def _start_navigating(orchestrator: TourOrchestrator) -> None:
    await orchestrator.activate_initial_state()
    await orchestrator.dispatch_tour(_plan())
    await orchestrator._nav_bridge.navigation_started.wait()


@pytest.mark.asyncio
async def test_supervised_interaction_activates_with_unique_context() -> None:
    runtime = RuntimeFake([
        _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="interaction:1", sequence=0),
    ])
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)

    await orchestrator.request_interaction(np.zeros(1, dtype=np.float32))

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

    task = asyncio.create_task(orchestrator.request_interaction(np.zeros(1, dtype=np.float32)))
    await asyncio.sleep(0.05)

    assert orchestrator.state_id == "interacting"
    assert completions == []
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
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
async def test_emergency_runtime_call_does_not_delay_zero_velocity_or_damp() -> None:
    runtime = RuntimeFake()
    runtime.block_next_event = True
    orchestrator, _, completions, order = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    interaction_task = asyncio.create_task(orchestrator.request_interaction(np.zeros(1, dtype=np.float32)))
    await asyncio.sleep(0.05)

    orchestrator.context.last_error = "test emergency"
    await orchestrator.on_enter_emergency()
    result = orchestrator._last_emergency_result

    assert result is not None
    assert result.damp_succeeded is True
    assert runtime.emergency_stop_calls == 1
    assert order.index("damp") > order.index("zero")
    assert completions == []
    assert orchestrator._active_runtime_interaction_id is None
    await asyncio.gather(interaction_task, return_exceptions=True)
    await orchestrator.close()


@pytest.mark.asyncio
async def test_orchestrator_close_cancels_runtime_interaction_task() -> None:
    runtime = RuntimeFake()
    runtime.block_next_event = True
    orchestrator, _, _, _ = _make_orchestrator(runtime)
    await _start_navigating(orchestrator)
    interaction_task = asyncio.create_task(orchestrator.request_interaction(np.zeros(1, dtype=np.float32)))
    await asyncio.sleep(0.05)

    await orchestrator.close()

    assert orchestrator._interaction_task is None
    assert orchestrator._active_runtime_interaction_id is None
    assert runtime.stop_calls >= 1
    assert runtime.close_calls == 0
    assert runtime.start_calls == 0
    await asyncio.gather(interaction_task, return_exceptions=True)
