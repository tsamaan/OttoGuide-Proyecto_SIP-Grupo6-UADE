"""
@TASK: Validar StationTriggerCoordinator (U2)
@INPUT: StationTriggerPort fake; OttoEventBus de test
@OUTPUT: Resultado de pytest: PASSED si el coordinador publica QR_STATION_DETECTED
         correctamente y se detiene limpiamente ante cancelacion o fallo de provider
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_u2_station_trigger_coordinator.py -q
@AI_CONTEXT: events.py y event_bus.py se cargan de forma aislada (mismo patron que
             tests/test_event_bus.py) para no fijar en sys.modules una copia de
             EventType incompatible con otros tests del mismo proceso.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from datetime import datetime, timezone

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_isolated(module_name: str, relative_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(_PROJECT_ROOT, *relative_path.split("/"))
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_events_mod = _load_isolated("src.core.events", "src/core/events.py")
_event_bus_mod = _load_isolated("src.core.event_bus", "src/core/event_bus.py")

EventType = _events_mod.EventType
OttoEventBus = _event_bus_mod.OttoEventBus

from src.vision.station_trigger import QRStationDetected, StationTriggerHealth, StationTriggerState

_coordinator_mod = _load_isolated(
    "_u2_isolated_station_trigger_coordinator", "src/core/station_trigger_coordinator.py"
)
StationTriggerCoordinator = _coordinator_mod.StationTriggerCoordinator

assert _coordinator_mod.EventType is EventType
assert _coordinator_mod.OttoEventBus is OttoEventBus


def _make_detection(station_id: str = "1") -> QRStationDetected:
    return QRStationDetected(
        station_id=station_id,
        qr_value=f"QR_{station_id}",
        detected_at=datetime.now(timezone.utc),
        confidence_or_stability=1.0,
        source="test",
    )


class FakeStationTrigger:
    def __init__(self, detections: list[QRStationDetected | Exception]) -> None:
        self._detections = list(detections)
        self.start_calls = 0
        self.close_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def next_detection(self) -> QRStationDetected:
        if not self._detections:
            await asyncio.sleep(3600)
        item = self._detections.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def health(self) -> StationTriggerHealth:
        return StationTriggerHealth(state=StationTriggerState.READY, ready=True, source="fake")

    async def stop(self) -> None:
        pass

    async def close(self) -> None:
        self.close_calls += 1


async def _async_start_creates_single_task() -> None:
    bus = OttoEventBus()
    trigger = FakeStationTrigger([])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)

    await coordinator.start()
    task1 = coordinator._task
    await coordinator.start()
    task2 = coordinator._task

    assert task1 is task2
    assert trigger.start_calls == 1

    await coordinator.close()


def test_start_creates_single_task() -> None:
    asyncio.run(_async_start_creates_single_task())


async def _async_detection_produces_exactly_one_event() -> None:
    bus = OttoEventBus()
    received: list[tuple] = []

    async def handler(event_type, data):
        received.append((event_type, data))

    bus.subscribe(EventType.QR_STATION_DETECTED, handler)

    detection = _make_detection()
    trigger = FakeStationTrigger([detection])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)

    await coordinator.start()
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0][0] == EventType.QR_STATION_DETECTED
    assert received[0][1] is detection
    assert isinstance(received[0][1], QRStationDetected)

    await coordinator.close()


def test_detection_produces_exactly_one_event() -> None:
    asyncio.run(_async_detection_produces_exactly_one_event())


async def _async_payload_is_qr_station_detected() -> None:
    bus = OttoEventBus()
    received: list = []

    async def handler(event_type, data):
        received.append(data)

    bus.subscribe(EventType.QR_STATION_DETECTED, handler)
    detection = _make_detection(station_id="F")
    trigger = FakeStationTrigger([detection])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)

    await coordinator.start()
    await asyncio.sleep(0.05)

    assert isinstance(received[0], QRStationDetected)
    assert received[0].station_id == "F"

    await coordinator.close()


def test_payload_is_qr_station_detected() -> None:
    asyncio.run(_async_payload_is_qr_station_detected())


async def _async_no_duplicate_publisher() -> None:
    bus = OttoEventBus()
    received: list = []

    async def handler(event_type, data):
        received.append(data)

    bus.subscribe(EventType.QR_STATION_DETECTED, handler)
    d1, d2, d3 = _make_detection("1"), _make_detection("2"), _make_detection("3")
    trigger = FakeStationTrigger([d1, d2, d3])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)

    await coordinator.start()
    await asyncio.sleep(0.05)

    assert len(received) == 3
    assert [d.station_id for d in received] == ["1", "2", "3"]

    await coordinator.close()


def test_no_duplicate_publisher() -> None:
    asyncio.run(_async_no_duplicate_publisher())


async def _async_cancelled_error_closes_cleanly() -> None:
    bus = OttoEventBus()
    trigger = FakeStationTrigger([])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)

    await coordinator.start()
    await asyncio.sleep(0.01)
    await coordinator.stop()

    assert coordinator._task is None


def test_cancelled_error_closes_cleanly() -> None:
    asyncio.run(_async_cancelled_error_closes_cleanly())


async def _async_provider_failure_stops_loop_without_fallback() -> None:
    bus = OttoEventBus()
    received: list = []

    async def handler(event_type, data):
        received.append(data)

    bus.subscribe(EventType.QR_STATION_DETECTED, handler)
    trigger = FakeStationTrigger([RuntimeError("provider broke")])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)

    await coordinator.start()
    await asyncio.sleep(0.05)

    assert received == []
    assert coordinator.last_error is not None
    assert "RuntimeError" in coordinator.last_error
    assert coordinator._task.done()

    await coordinator.close()


def test_provider_failure_stops_loop_without_fallback() -> None:
    asyncio.run(_async_provider_failure_stops_loop_without_fallback())


async def _async_stop_is_idempotent() -> None:
    bus = OttoEventBus()
    trigger = FakeStationTrigger([])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)
    await coordinator.start()
    await coordinator.stop()
    await coordinator.stop()  # idempotent, must not raise


def test_stop_is_idempotent() -> None:
    asyncio.run(_async_stop_is_idempotent())


async def _async_close_closes_port() -> None:
    bus = OttoEventBus()
    trigger = FakeStationTrigger([])
    coordinator = StationTriggerCoordinator(station_trigger=trigger, event_bus=bus)
    await coordinator.start()
    await coordinator.close()
    await coordinator.close()  # idempotent
    assert trigger.close_calls == 1


def test_close_closes_port() -> None:
    asyncio.run(_async_close_closes_port())


def test_coordinator_module_has_no_motion_audio_llm_camera_symbols() -> None:
    path = os.path.join(_PROJECT_ROOT, "src", "core", "station_trigger_coordinator.py")
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    for forbidden in (
        "MotionCommand",
        "hardware.move",
        "cv2",
        "ConversationManager",
        "subprocess",
        "multiprocessing",
        "threading.Thread",
    ):
        assert forbidden not in source
