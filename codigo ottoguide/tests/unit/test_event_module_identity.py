"""
@TASK: Verificar la identidad canonica unica de EventType/OttoEventBus dentro de un proceso (U2R2)
@INPUT: Mocks de hardware/navegacion/conversacion/vision; sin camara real, sin hardware, sin ROS
@OUTPUT: Resultado de pytest: PASSED si EventType y OttoEventBus mantienen una unica identidad
         de clase a traves de reimports repetidos de main.py, y si TourOrchestrator se suscribe/
         desuscribe correctamente usando esa misma identidad
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_event_module_identity.py -q
@AI_CONTEXT: Usa tests.support.core_module_identity.ensure_core_event_modules() como unico punto
             de carga de events.py/event_bus.py, igual que el resto de los archivos de test
             remediados en U2R2. No abre hardware, camara, ROS, red ni audio.
"""
from __future__ import annotations

import asyncio
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

from tests.support.core_module_identity import ensure_core_event_modules

_core_modules = ensure_core_event_modules()
EventType = _core_modules.EventType
OttoEventBus = _core_modules.OttoEventBus

from src.core.tour_orchestrator import TourOrchestrator, TourPlan
from src.navigation.models import NavWaypoint
from src.vision.station_trigger import QRStationDetected


# ---------------------------------------------------------------------------
# A. Identidad de EventType: events.py vs event_bus.py vs tour_orchestrator
# ---------------------------------------------------------------------------


def test_event_type_identity_shared_by_events_and_event_bus_modules() -> None:
    assert sys.modules["src.core.events"].EventType is EventType
    assert sys.modules["src.core.event_bus"].EventType is EventType


def test_event_type_identity_shared_by_tour_orchestrator() -> None:
    import src.core.tour_orchestrator as tour_orchestrator_module

    assert tour_orchestrator_module.EventType is EventType


# ---------------------------------------------------------------------------
# B. Identidad de OttoEventBus: event_bus.py vs tour_orchestrator
# ---------------------------------------------------------------------------


def test_otto_event_bus_identity_shared_by_event_bus_module() -> None:
    assert sys.modules["src.core.event_bus"].OttoEventBus is OttoEventBus


def test_otto_event_bus_identity_shared_by_tour_orchestrator() -> None:
    import src.core.tour_orchestrator as tour_orchestrator_module

    bus = OttoEventBus()
    orchestrator = _make_orchestrator(bus)
    assert isinstance(orchestrator._event_bus, OttoEventBus)


# ---------------------------------------------------------------------------
# C. Reimportacion de main: las identidades no cambian
# ---------------------------------------------------------------------------


def test_event_type_and_event_bus_identity_stable_across_three_main_reimports() -> None:
    from tests.unit.test_navigation_runtime_selection import (
        _fresh_import_main,
        _purge_app_modules,
        _remove_interaction_dependency_mocks,
    )

    initial_event_type_id = id(EventType)
    initial_event_bus_id = id(OttoEventBus)

    try:
        for _ in range(3):
            _main_mod, mocks = _fresh_import_main()
            from src.core.events import EventType as reimported_event_type
            from src.core.event_bus import OttoEventBus as reimported_event_bus

            assert id(reimported_event_type) == initial_event_type_id
            assert id(reimported_event_bus) == initial_event_bus_id
            _remove_interaction_dependency_mocks(mocks)
    finally:
        _purge_app_modules()


# ---------------------------------------------------------------------------
# D. Suscripcion: INTERACTION_STARTED y QR_STATION_DETECTED, despacho correcto
# ---------------------------------------------------------------------------


def _make_plan() -> TourPlan:
    return TourPlan(
        waypoints=[
            NavWaypoint(x=0.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0),
        ],
        tour_id="u2r2-identity-test",
    )


def _make_orchestrator(event_bus: OttoEventBus) -> TourOrchestrator:
    mock_hw = MagicMock()
    mock_hw.stop_motion = AsyncMock()
    mock_hw.move = AsyncMock()
    mock_hw.get_state = AsyncMock(return_value={"battery_level": 100.0})

    mock_nav = MagicMock()
    mock_nav.cancel_navigation = AsyncMock()
    mock_nav.navigate_to_waypoints = AsyncMock(return_value=True)
    mock_nav.inject_absolute_pose = AsyncMock()

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


def test_orchestrator_subscribes_exactly_once_to_both_canonical_events() -> None:
    bus = OttoEventBus()
    orchestrator = _make_orchestrator(bus)

    interaction_subs = bus._subscribers.get(EventType.INTERACTION_STARTED, [])
    qr_subs = bus._subscribers.get(EventType.QR_STATION_DETECTED, [])

    assert len(interaction_subs) == 1
    assert len(qr_subs) == 1
    assert interaction_subs[0].__func__.__name__ == "_on_interaction_started"
    assert qr_subs[0].__func__.__name__ == "_on_qr_station_detected"


async def _async_publish_dispatches_with_canonical_enum() -> None:
    bus = OttoEventBus()
    orchestrator = _make_orchestrator(bus)

    await orchestrator.activate_initial_state()
    await orchestrator.dispatch_tour(_make_plan())
    await asyncio.sleep(0.02)

    qr_event = QRStationDetected(
        station_id="1",
        qr_value="QR_TEST",
        detected_at=datetime.now(timezone.utc),
        confidence_or_stability=1.0,
        source="test_event_module_identity",
    )
    await bus.publish(EventType.QR_STATION_DETECTED, data=qr_event)
    await asyncio.sleep(0.02)

    assert orchestrator._context.last_station_id == "1"
    assert orchestrator._context.last_station_qr_value == "QR_TEST"

    await orchestrator.close()
    if orchestrator._nav_task is not None:
        orchestrator._nav_task.cancel()
        try:
            await orchestrator._nav_task
        except asyncio.CancelledError:
            pass

    return orchestrator, bus


def test_publish_dispatches_using_canonical_enum() -> None:
    asyncio.run(_async_publish_dispatches_with_canonical_enum())


# ---------------------------------------------------------------------------
# E. Limpieza: close() desuscribe ambos handlers; singleton reseteable
# ---------------------------------------------------------------------------


async def _async_close_unsubscribes_both_handlers() -> None:
    bus = OttoEventBus()
    orchestrator = _make_orchestrator(bus)

    assert len(bus._subscribers.get(EventType.INTERACTION_STARTED, [])) == 1
    assert len(bus._subscribers.get(EventType.QR_STATION_DETECTED, [])) == 1

    await orchestrator.close()

    assert len(bus._subscribers.get(EventType.INTERACTION_STARTED, [])) == 0
    assert len(bus._subscribers.get(EventType.QR_STATION_DETECTED, [])) == 0


def test_close_unsubscribes_both_handlers_and_singleton_resettable() -> None:
    asyncio.run(_async_close_unsubscribes_both_handlers())

    OttoEventBus.reset_for_testing()
    fresh = OttoEventBus.get_instance()
    assert len(fresh._subscribers.get(EventType.INTERACTION_STARTED, [])) == 0
    OttoEventBus.reset_for_testing()
