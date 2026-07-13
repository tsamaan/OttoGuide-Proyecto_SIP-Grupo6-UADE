from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
    return WorkerEventEnvelope(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id=f"standalone-test:{sequence}",
        interaction_id=interaction_id,
        event=event,
        sequence=sequence,
        emitted_at_monotonic_s=float(sequence + 1),
        payload=payload or {},
    )


class RecordingHardware:
    async def initialize(self) -> bool:
        return True

    async def move(self, command: MotionCommand) -> None:
        return None

    async def stop_motion(self) -> None:
        return None


class NoOpNav:
    def __init__(self) -> None:
        self.navigation_started = asyncio.Event()

    async def navigate_to_waypoints(self, waypoints: list[NavWaypoint]) -> bool:
        self.navigation_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise
        return True

    async def cancel_navigation(self) -> None:
        return None

    async def inject_absolute_pose(self, pose_estimate) -> None:
        return None


class VisionStub:
    visual_odometry_enabled = False

    async def get_next_estimate(self, timeout_s: float = 0.5):
        return None

    def close(self) -> None:
        return None


class RuntimeFake:
    def __init__(self, events: list[WorkerEventEnvelope] | None = None) -> None:
        # Events are only enqueued on activate(), matching the real
        # JsonlInteractionWorkerSupervisor: TRANSCRIPT_READY/RESPONSE_READY/etc. are emitted
        # in response to an in-progress interaction, never queued ahead of activate(). This
        # matters because the orchestrator's idle-drain task (MVP-R0) legitimately consumes
        # any event sitting in the queue before an interaction claims it (e.g. READY/HEARTBEAT);
        # pre-loading interaction-specific events at construction time would let the drain task
        # steal them before activate() is ever called, which cannot happen with the real worker.
        self.events = asyncio.Queue()
        self._pending_events = list(events or [])
        self.activate_contexts: list[InteractionContext] = []
        self.activate_calls = 0
        self.stop_calls = 0
        self.emergency_stop_calls = 0

    async def activate(self, context: InteractionContext) -> None:
        self.activate_calls += 1
        self.activate_contexts.append(context)
        for event in self._pending_events:
            self.events.put_nowait(event)
        self._pending_events = []

    async def next_event(self, *, timeout_s: float | None = None) -> WorkerEventEnvelope:
        return await asyncio.wait_for(self.events.get(), timeout=timeout_s)

    async def stop(self) -> None:
        self.stop_calls += 1

    async def emergency_stop(self) -> None:
        self.emergency_stop_calls += 1

    async def health(self):
        raise NotImplementedError

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def _make_orchestrator(runtime):
    local_strategy = MagicMock()
    local_strategy.close = MagicMock()
    cloud_strategy = MagicMock()
    cloud_strategy.close = MagicMock()
    cm = ConversationManager(local_strategy=local_strategy, cloud_strategy=cloud_strategy)
    bus = OttoEventBus()
    completion_payloads: list[object] = []

    async def _capture_completion(_event_type, data):
        completion_payloads.append(data)

    bus.subscribe(EventType.INTERACTION_COMPLETED, _capture_completion)
    orchestrator = TourOrchestrator(
        hardware_api=RecordingHardware(),
        nav_bridge=NoOpNav(),
        conversation_manager=cm,
        vision_processor=VisionStub(),
        event_bus=bus,
        interaction_runtime=runtime,
        audio_capture_timeout_s=0.2,
    )
    await orchestrator.activate_initial_state()
    return orchestrator, completion_payloads


@pytest.mark.asyncio
async def test_start_standalone_interaction_rejected_outside_idle() -> None:
    runtime = RuntimeFake()
    orchestrator, _ = await _make_orchestrator(runtime)
    plan = TourPlan(waypoints=[NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0)], tour_id="tour:mvp-r0")
    await orchestrator.dispatch_tour(plan)
    await orchestrator._nav_bridge.navigation_started.wait()
    assert orchestrator.state_id == "navigating"

    with pytest.raises(RuntimeError, match="se requiere 'idle'"):
        await orchestrator.start_standalone_interaction()

    await orchestrator._cancel_nav_task_safe()


@pytest.mark.asyncio
async def test_start_standalone_interaction_rejected_without_runtime() -> None:
    orchestrator, _ = await _make_orchestrator(None)
    assert orchestrator.state_id == "idle"

    with pytest.raises(RuntimeError, match="runtime no configurado"):
        await orchestrator.start_standalone_interaction()


@pytest.mark.asyncio
async def test_start_standalone_interaction_does_not_transition_fsm() -> None:
    runtime = RuntimeFake()
    orchestrator, _ = await _make_orchestrator(runtime)

    interaction_id = await orchestrator.start_standalone_interaction(locale="es", timeout_s=1.0)

    assert interaction_id.startswith("standalone:")
    # @SECURITY: standalone interaction never moves the mission FSM out of idle.
    assert orchestrator.state_id == "idle"
    await orchestrator._interaction_task
    assert runtime.activate_calls == 1
    assert runtime.activate_contexts[0].tour_id is None
    assert runtime.activate_contexts[0].waypoint_id is None


@pytest.mark.asyncio
async def test_start_standalone_interaction_rejects_second_call_while_active() -> None:
    runtime = RuntimeFake()
    orchestrator, _ = await _make_orchestrator(runtime)

    await orchestrator.start_standalone_interaction(locale="es", timeout_s=5.0)
    with pytest.raises(RuntimeError, match="ya existe una interaccion activa"):
        await orchestrator.start_standalone_interaction(locale="es", timeout_s=5.0)

    orchestrator._interaction_task.cancel()
    await asyncio.gather(orchestrator._interaction_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_standalone_interaction_completes_and_publishes_event() -> None:
    runtime = RuntimeFake(
        events=[
            _event(WorkerEventType.READY, interaction_id=None, sequence=0),
            _event(
                WorkerEventType.TRANSCRIPT_READY,
                interaction_id="standalone:1",
                sequence=1,
                payload={"text": "hola"},
            ),
            _event(
                WorkerEventType.RESPONSE_READY,
                interaction_id="standalone:1",
                sequence=2,
                payload={"text": "hola humano"},
            ),
            _event(WorkerEventType.PLAYBACK_STARTED, interaction_id="standalone:1", sequence=3),
            _event(WorkerEventType.PLAYBACK_COMPLETED, interaction_id="standalone:1", sequence=4),
        ]
    )
    orchestrator, completion_payloads = await _make_orchestrator(runtime)

    interaction_id = await orchestrator.start_standalone_interaction(locale="es", timeout_s=2.0)
    await orchestrator._interaction_task

    assert orchestrator.standalone_interaction_session["state"] == "completed"
    assert orchestrator.state_id == "idle"
    assert len(completion_payloads) == 1
    assert completion_payloads[0]["interaction_id"] == interaction_id


@pytest.mark.asyncio
async def test_standalone_interaction_timeout_marks_session_failed() -> None:
    runtime = RuntimeFake(events=[])
    orchestrator, _ = await _make_orchestrator(runtime)

    await orchestrator.start_standalone_interaction(locale="es", timeout_s=0.05)
    await orchestrator._interaction_task

    assert orchestrator.standalone_interaction_session["state"] == "timeout"
    assert runtime.stop_calls == 1


@pytest.mark.asyncio
async def test_emergency_stop_cancels_active_standalone_interaction() -> None:
    runtime = RuntimeFake(events=[])
    orchestrator, _ = await _make_orchestrator(runtime)

    await orchestrator.start_standalone_interaction(locale="es", timeout_s=5.0)
    await asyncio.sleep(0)

    result = await orchestrator.emergency_stop(reason="test emergency during standalone")

    assert orchestrator.state_id == "emergency"
    assert result.stop_motion_succeeded is True
    assert result.damp_attempted is False
    assert result.posture_change_attempted is False
    assert runtime.emergency_stop_calls >= 1


@pytest.mark.asyncio
async def test_standalone_session_status_defaults_to_idle() -> None:
    orchestrator, _ = await _make_orchestrator(None)
    session = orchestrator.standalone_interaction_session
    assert session["session_id"] is None
    assert session["state"] == "idle"
    assert session["last_event"] is None


class HeartbeatOnlyRuntime:
    """
    Emits an unbounded stream of HEARTBEAT events via next_event(), simulating a real
    JsonlInteractionWorkerSupervisor idling between interactions (FINAL-MVP-R0-C2 full-stack
    E2E against the compiled otto_jsonl_shim.exe found that nothing drained these outside an
    active interaction, overflowing the supervisor's internal event queue after ~60s idle and
    forcing the runtime to `failed`). This fake has no internal queue bound — it exists purely
    to prove start_idle_drain() keeps calling next_event() (never letting heartbeats pile up
    anywhere) and that activate() still works correctly afterwards.
    """

    def __init__(self) -> None:
        self.heartbeat_count = 0
        self.activate_calls = 0
        self.next_event_calls_during_idle = 0

    async def next_event(self, *, timeout_s: float | None = None):
        # A tiny await models the real supervisor's I/O wait on its event queue; without it
        # this fake would spin the event loop as fast as possible with zero cooperative yields,
        # starving every other task/test on the same loop.
        await asyncio.sleep(0.01)
        self.heartbeat_count += 1
        self.next_event_calls_during_idle += 1
        return _event(WorkerEventType.HEARTBEAT, interaction_id=None, sequence=self.heartbeat_count)

    async def activate(self, context: InteractionContext) -> None:
        self.activate_calls += 1

    async def stop(self) -> None:
        return None

    async def emergency_stop(self) -> None:
        return None

    async def health(self):
        raise NotImplementedError

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_start_idle_drain_continuously_consumes_heartbeats_without_overflow() -> None:
    runtime = HeartbeatOnlyRuntime()
    orchestrator, _ = await _make_orchestrator(runtime)

    orchestrator.start_idle_drain()
    await asyncio.sleep(0.3)

    assert runtime.heartbeat_count > 5, (
        "idle drain must continuously consume next_event() while no interaction is active, "
        "or the worker's internal event queue overflows (event queue full -> runtime failed)"
    )

    await orchestrator._cancel_idle_drain_task_safe()


@pytest.mark.asyncio
async def test_idle_drain_pauses_before_real_activation_and_resumes_after() -> None:
    runtime = HeartbeatOnlyRuntime()
    orchestrator, _ = await _make_orchestrator(runtime)

    orchestrator.start_idle_drain()
    await asyncio.sleep(0.05)
    assert runtime.activate_calls == 0

    await orchestrator.start_standalone_interaction(locale="es", timeout_s=0.2)
    await orchestrator._interaction_task

    assert runtime.activate_calls == 1
    # Idle drain must have resumed after the interaction settled (timeout, since
    # HeartbeatOnlyRuntime never emits a terminal event).
    await asyncio.sleep(0.05)
    assert orchestrator._interaction_idle_drain_task is not None
    assert not orchestrator._interaction_idle_drain_task.done()

    await orchestrator._cancel_idle_drain_task_safe()
