"""
@TASK: Validar la observacion pasiva de QR_STATION_DETECTED en TourOrchestrator (U2)
@INPUT: Mocks de hardware/navegacion/conversacion/vision; sin camara real
@OUTPUT: Resultado de pytest: PASSED si el handler actualiza TourContext sin alterar
         FSM, navegacion, interaccion o movimiento
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_u2_orchestrator_qr_observation.py -q
@AI_CONTEXT: events.py y event_bus.py se cargan de forma aislada bajo los nombres reales
             "src.core.events" / "src.core.event_bus" ANTES de importar tour_orchestrator,
             exactamente como en tests/test_event_bus.py, para que TourOrchestrator
             (from src.core.events import EventType) resuelva contra la misma clase
             EventType usada por este archivo. Esto evita el problema conocido de doble
             carga incompatible del enum cuando este test corre junto a test_event_bus.py
             en el mismo proceso de pytest.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _make_package_mock(name: str) -> MagicMock:
    mock = MagicMock()
    mock.__name__ = name
    mock.__path__ = []
    mock.__package__ = name
    mock.__spec__ = None
    return mock


_ROS2_STUBS = [
    "rclpy", "rclpy.node", "rclpy.action", "rclpy.action.client",
    "rclpy.executors", "rclpy.callback_groups", "rclpy.qos",
    "nav2_msgs", "nav2_msgs.action",
    "geometry_msgs", "geometry_msgs.msg",
    "tf2_ros", "tf2_ros.buffer", "tf2_ros.transform_listener",
    "action_msgs", "action_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "std_msgs", "std_msgs.msg",
]
for _mod_name in _ROS2_STUBS:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _make_package_mock(_mod_name)

if "src.core.events" not in sys.modules:
    _events_spec = importlib.util.spec_from_file_location(
        "src.core.events", os.path.join(_PROJECT_ROOT, "src", "core", "events.py")
    )
    _events_mod = importlib.util.module_from_spec(_events_spec)
    sys.modules["src.core.events"] = _events_mod
    _events_spec.loader.exec_module(_events_mod)

if "src.core.event_bus" not in sys.modules:
    _event_bus_spec = importlib.util.spec_from_file_location(
        "src.core.event_bus", os.path.join(_PROJECT_ROOT, "src", "core", "event_bus.py")
    )
    _event_bus_mod = importlib.util.module_from_spec(_event_bus_spec)
    sys.modules["src.core.event_bus"] = _event_bus_mod
    _event_bus_spec.loader.exec_module(_event_bus_mod)

EventType = sys.modules["src.core.events"].EventType
OttoEventBus = sys.modules["src.core.event_bus"].OttoEventBus

from src.core.tour_orchestrator import TourOrchestrator, TourPlan
from src.navigation.models import NavWaypoint
from src.vision.station_trigger import QRStationDetected


def _make_plan() -> TourPlan:
    return TourPlan(
        waypoints=[
            NavWaypoint(x=0.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=2.0, y=0.0, yaw_rad=0.0),
        ],
        tour_id="u2-qr-observation-test",
    )


def _make_detection(station_id: str = "1", qr_value: str = "QR_1") -> QRStationDetected:
    return QRStationDetected(
        station_id=station_id,
        qr_value=qr_value,
        detected_at=datetime.now(timezone.utc),
        confidence_or_stability=1.0,
        source="test",
    )


def _make_orchestrator(event_bus: OttoEventBus) -> TourOrchestrator:
    mock_hw = MagicMock()
    mock_hw.damp = AsyncMock()
    mock_hw.move = AsyncMock()
    mock_hw.get_state = AsyncMock(return_value={"battery_level": 100.0})

    mock_nav = MagicMock()
    mock_nav.cancel_navigation = AsyncMock()
    mock_nav.navigate_to_waypoints = AsyncMock(return_value=True)

    mock_cm = MagicMock()
    mock_cm.get_waypoint_interaction_type = MagicMock(return_value="free")
    mock_cm.set_active_zone = MagicMock()
    mock_cm.process_interaction = AsyncMock()

    mock_vp = MagicMock()
    mock_vp.close = MagicMock()
    mock_vp.get_next_estimate = AsyncMock(return_value=None)

    return TourOrchestrator(
        hardware_api=mock_hw,
        nav_bridge=mock_nav,
        conversation_manager=mock_cm,
        vision_processor=mock_vp,
        robot_mode="mock",
        event_bus=event_bus,
    )


async def _async_subscription_registered_exactly_once() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    subs = bus._subscribers.get(EventType.QR_STATION_DETECTED, [])
    assert len(subs) == 1
    await orch.close()


def test_subscription_registered_exactly_once() -> None:
    asyncio.run(_async_subscription_registered_exactly_once())


async def _async_valid_detection_in_navigating_updates_context() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    assert orch.state_id == "navigating"

    detection = _make_detection(station_id="I", qr_value="QR_I")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    assert orch.context.last_station_id == "I"
    assert orch.context.last_station_qr_value == "QR_I"
    assert orch.context.last_station_detected_at == detection.detected_at.isoformat()
    await orch.close()


def test_valid_detection_in_navigating_updates_context() -> None:
    asyncio.run(_async_valid_detection_in_navigating_updates_context())


async def _async_expected_station_id_calculated() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    orch.context.current_waypoint_index = 2  # logical id "2"

    detection = _make_detection(station_id="2")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    assert orch.context.last_station_matches_expected is True
    await orch.close()


def test_expected_station_id_calculated() -> None:
    asyncio.run(_async_expected_station_id_calculated())


async def _async_matches_expected_true_and_false() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    orch.context.current_waypoint_index = 0  # logical id "I"

    detection_match = _make_detection(station_id="I")
    await bus.publish(EventType.QR_STATION_DETECTED, detection_match)
    assert orch.context.last_station_matches_expected is True

    detection_mismatch = _make_detection(station_id="F")
    await bus.publish(EventType.QR_STATION_DETECTED, detection_mismatch)
    assert orch.context.last_station_matches_expected is False

    await orch.close()


def test_matches_expected_true_and_false() -> None:
    asyncio.run(_async_matches_expected_true_and_false())


async def _async_audit_payload_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    orch.context.current_waypoint_index = 0

    captured: dict = {}

    def fake_schedule(*, event_type, node_id, payload):
        captured["event_type"] = event_type
        captured["node_id"] = node_id
        captured["payload"] = payload

    monkeypatch.setattr(orch, "_schedule_audit_event", fake_schedule)

    detection = _make_detection(station_id="I", qr_value="QR_I")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    assert captured["event_type"] == "QR_STATION_DETECTED"
    payload = captured["payload"]
    assert payload["station_id"] == "I"
    assert payload["qr_value"] == "QR_I"
    assert payload["detected_at"] == detection.detected_at.isoformat()
    assert payload["confidence_or_stability"] == 1.0
    assert payload["source"] == "test"
    assert payload["expected_station_id"] == "I"
    assert payload["matches_expected"] is True

    await orch.close()


def test_audit_payload_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_async_audit_payload_complete(monkeypatch))


async def _async_invalid_payload_ignored() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())

    await bus.publish(EventType.QR_STATION_DETECTED, {"not": "a QRStationDetected"})
    await bus.publish(EventType.QR_STATION_DETECTED, None)
    await bus.publish(EventType.QR_STATION_DETECTED, "raw string")

    assert orch.context.last_station_id is None
    await orch.close()


def test_invalid_payload_ignored() -> None:
    asyncio.run(_async_invalid_payload_ignored())


async def _async_event_in_idle_does_not_change_operational_context() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    assert orch.state_id == "idle"

    detection = _make_detection(station_id="1")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    assert orch.context.last_station_id is None
    assert orch.state_id == "idle"
    await orch.close()


def test_event_in_idle_does_not_change_operational_context() -> None:
    asyncio.run(_async_event_in_idle_does_not_change_operational_context())


async def _async_event_in_emergency_ignored() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.emergency_stop(reason="test")
    assert orch.state_id == "emergency"

    detection = _make_detection(station_id="1")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    assert orch.context.last_station_id is None
    await orch.close()


def test_event_in_emergency_ignored() -> None:
    asyncio.run(_async_event_in_emergency_ignored())


async def _async_index_and_plan_unchanged() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    orch.context.current_waypoint_index = 1
    orch.context.waypoint_plan = []
    plan_before = orch.context.waypoint_plan

    detection = _make_detection(station_id="1")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    assert orch.context.current_waypoint_index == 1
    assert orch.context.waypoint_plan is plan_before
    await orch.close()


def test_index_and_plan_unchanged() -> None:
    asyncio.run(_async_index_and_plan_unchanged())


async def _async_fsm_state_unchanged() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    state_before = orch.state_id

    detection = _make_detection(station_id="1")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    assert orch.state_id == state_before
    await orch.close()


def test_fsm_state_unchanged() -> None:
    asyncio.run(_async_fsm_state_unchanged())


async def _async_no_hardware_move_invoked() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())

    detection = _make_detection(station_id="1")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    orch._hardware_api.move.assert_not_called()
    await orch.close()


def test_no_hardware_move_invoked() -> None:
    asyncio.run(_async_no_hardware_move_invoked())


async def _async_no_cancel_navigation_invoked() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())

    detection = _make_detection(station_id="1")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    orch._nav_bridge.cancel_navigation.assert_not_called()
    await orch.close()


def test_no_cancel_navigation_invoked() -> None:
    asyncio.run(_async_no_cancel_navigation_invoked())


async def _async_no_conversation_manager_invoked() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())

    detection = _make_detection(station_id="1")
    await bus.publish(EventType.QR_STATION_DETECTED, detection)

    orch._conversation_manager.process_interaction.assert_not_called()
    orch._conversation_manager.set_active_zone.assert_not_called()
    await orch.close()


def test_no_conversation_manager_invoked() -> None:
    asyncio.run(_async_no_conversation_manager_invoked())


async def _async_close_desubscribes_both_handlers() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)

    assert len(bus._subscribers.get(EventType.INTERACTION_STARTED, [])) == 1
    assert len(bus._subscribers.get(EventType.QR_STATION_DETECTED, [])) == 1

    await orch.close()

    assert len(bus._subscribers.get(EventType.INTERACTION_STARTED, [])) == 0
    assert len(bus._subscribers.get(EventType.QR_STATION_DETECTED, [])) == 0


def test_close_desubscribes_both_handlers() -> None:
    asyncio.run(_async_close_desubscribes_both_handlers())


async def _async_close_is_idempotent() -> None:
    bus = OttoEventBus()
    orch = _make_orchestrator(bus)
    await orch.close()
    await orch.close()  # must not raise


def test_close_is_idempotent() -> None:
    asyncio.run(_async_close_is_idempotent())
