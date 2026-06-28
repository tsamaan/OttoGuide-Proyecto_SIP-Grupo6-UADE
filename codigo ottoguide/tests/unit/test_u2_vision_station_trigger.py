"""
@TASK: Validar el pipeline compartido VisionProcessor+QR y el adaptador VisionStationTrigger (U2)
@INPUT: Frame sintetico; decoder fake; registry temporal; sin camara real
@OUTPUT: Resultado de pytest: PASSED si el pipeline comparte la unica camara y el adaptador
         satisface StationTriggerPort
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_u2_vision_station_trigger.py -q
"""
from __future__ import annotations

import asyncio
import ast
import os
import sys
from datetime import timezone
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.stations.station_registry import StationDefinition, StationRegistry
from src.vision.qr_frame_detector import QRDecodeError, StableQRFrameDetector
from src.vision.station_trigger import QRStationDetected, StationTriggerPort, StationTriggerState
from src.vision.vision_processor import CameraModel, VisionProcessor
from src.vision.vision_station_trigger import StationTriggerUnavailableError, VisionStationTrigger


class FakeDecoder:
    def __init__(self, values: list[str | None]) -> None:
        self._values = list(values)
        self.calls = 0

    def decode(self, frame: object) -> str | None:
        self.calls += 1
        if not self._values:
            return None
        return self._values.pop(0)


class RaisingDecoder:
    def decode(self, frame: object) -> str | None:
        raise QRDecodeError("synthetic_failure")


def _make_registry(tmp_path: Path) -> StationRegistry:
    path = tmp_path / "qr_stations.yaml"
    path.write_text(
        "version: 1\nstations:\n  QR_KNOWN:\n    station_id: '1'\n    name: 'Known'\n",
        encoding="utf-8",
    )
    return StationRegistry.from_yaml(path)


def _make_camera_model() -> CameraModel:
    return CameraModel(
        camera_matrix=np.eye(3, dtype=np.float64),
        distortion_coefficients=np.zeros((5, 1), dtype=np.float64),
    )


def _synthetic_frame() -> np.ndarray:
    return np.zeros((480, 640, 3), dtype=np.uint8)


def test_no_qr_module_opens_second_video_capture() -> None:
    paths = [
        os.path.join(_PROJECT_ROOT, "src", "vision", "vision_station_trigger.py"),
        os.path.join(_PROJECT_ROOT, "src", "vision", "qr_frame_detector.py"),
    ]
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "VideoCapture":
                pytest.fail(f"{path} references VideoCapture")


def test_same_frame_feeds_apriltag_and_qr_lanes(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder(["QR_KNOWN", "QR_KNOWN", "QR_KNOWN", "QR_KNOWN"])
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    vp = VisionProcessor(
        camera_model=_make_camera_model(),
        tag_size_m=0.16,
        qr_detector=qr_detector,
        station_registry=registry,
    )

    frame = _synthetic_frame()

    async def run() -> None:
        vp._loop = asyncio.get_running_loop()
        for _ in range(4):
            pose = vp._process_frame_sync(frame)
            vp._process_qr_lane_sync(frame)
            assert pose is None  # black frame: no AprilTag, but lane still ran
        detection = await asyncio.wait_for(vp.get_next_station_detection(), timeout=1.0)
        assert detection.qr_value == "QR_KNOWN"
        assert decoder.calls == 4

    asyncio.run(run())


def test_known_qr_generates_qr_station_detected(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder(["QR_KNOWN"] * 4)
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(), tag_size_m=0.16,
        qr_detector=qr_detector, station_registry=registry,
    )
    frame = _synthetic_frame()

    async def run() -> None:
        vp._loop = asyncio.get_running_loop()
        for _ in range(4):
            vp._process_qr_lane_sync(frame)
        detection = await asyncio.wait_for(vp.get_next_station_detection(), timeout=1.0)
        assert isinstance(detection, QRStationDetected)
        assert detection.station_id == "1"
        assert detection.source == "vision_processor.shared_camera"
        assert detection.detected_at.tzinfo is timezone.utc or detection.detected_at.tzinfo is not None

    asyncio.run(run())


def test_unknown_qr_generates_no_event(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder(["QR_UNKNOWN"] * 4)
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(), tag_size_m=0.16,
        qr_detector=qr_detector, station_registry=registry,
    )
    frame = _synthetic_frame()

    async def run() -> None:
        vp._loop = asyncio.get_running_loop()
        for _ in range(4):
            vp._process_qr_lane_sync(frame)
        await asyncio.sleep(0)
        assert vp.station_queue.empty()
        assert vp.stats.qr_unknown_values == 1
        assert vp.stats.qr_known_detections == 0

    asyncio.run(run())


def test_qr_errors_do_not_stop_apriltag_lane(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    qr_detector = StableQRFrameDetector(RaisingDecoder(), stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(), tag_size_m=0.16,
        qr_detector=qr_detector, station_registry=registry,
    )
    frame = _synthetic_frame()

    # QRDecodeError is absorbed inside _process_qr_lane_sync; AprilTag lane unaffected.
    vp._loop = None
    pose = vp._process_frame_sync(frame)
    vp._process_qr_lane_sync(frame)  # must not raise
    assert pose is None


def test_apriltag_errors_do_not_stop_qr_lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder(["QR_KNOWN"] * 4)
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(), tag_size_m=0.16,
        qr_detector=qr_detector, station_registry=registry,
    )
    frame = _synthetic_frame()

    def _raise(*args, **kwargs):
        raise RuntimeError("synthetic apriltag failure")

    monkeypatch.setattr(vp, "_process_frame_sync", _raise)

    async def run() -> None:
        vp._loop = asyncio.get_running_loop()
        for _ in range(4):
            try:
                vp._process_frame_sync(frame)
            except RuntimeError:
                pass
            vp._process_qr_lane_sync(frame)
        detection = await asyncio.wait_for(vp.get_next_station_detection(), timeout=1.0)
        assert detection.station_id == "1"

    asyncio.run(run())


def test_queue_full_keeps_most_recent_detection(tmp_path: Path) -> None:
    registry = StationRegistry(
        stations=tuple(
            StationDefinition(qr_value=f"QR_{i}", station_id=str(i), name=f"S{i}")
            for i in range(1, 4)
        )
    )
    decoder = FakeDecoder([])
    qr_detector = StableQRFrameDetector(decoder, stable_frames=1, release_frames=1)
    vp = VisionProcessor(
        camera_model=_make_camera_model(), tag_size_m=0.16,
        qr_detector=qr_detector, station_registry=registry,
        station_queue_maxsize=1,
    )
    frame = _synthetic_frame()

    async def run() -> None:
        vp._loop = asyncio.get_running_loop()
        for value in ("QR_1", "QR_2", "QR_3"):
            decoder._values = [value]
            qr_detector.reset()
            vp._process_qr_lane_sync(frame)
            await asyncio.sleep(0)

        assert vp.station_queue.qsize() == 1
        detection = await asyncio.wait_for(vp.get_next_station_detection(), timeout=1.0)
        assert detection.qr_value == "QR_3"
        assert vp.stats.qr_queue_drops >= 1

    asyncio.run(run())


def test_vision_station_trigger_satisfies_station_trigger_port() -> None:
    vp = VisionProcessor(camera_model=_make_camera_model(), tag_size_m=0.16)
    trigger = VisionStationTrigger(vp)
    assert isinstance(trigger, StationTriggerPort)


async def _async_start_requires_processor_started(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder([])
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(), tag_size_m=0.16,
        qr_detector=qr_detector, station_registry=registry,
    )
    trigger = VisionStationTrigger(vp)
    with pytest.raises(StationTriggerUnavailableError):
        await trigger.start()


def test_start_requires_vision_processor_started(tmp_path: Path) -> None:
    asyncio.run(_async_start_requires_processor_started(tmp_path))


async def _async_stop_does_not_close_vision_processor() -> None:
    vp = VisionProcessor(camera_model=_make_camera_model(), tag_size_m=0.16)
    closed_calls = []
    original_close = vp.close
    vp.close = lambda: closed_calls.append(True)  # type: ignore[method-assign]

    trigger = VisionStationTrigger(vp)
    trigger._state = StationTriggerState.READY
    await trigger.stop()
    assert closed_calls == []
    vp.close = original_close


def test_stop_does_not_close_vision_processor() -> None:
    asyncio.run(_async_stop_does_not_close_vision_processor())


async def _async_close_is_idempotent() -> None:
    vp = VisionProcessor(camera_model=_make_camera_model(), tag_size_m=0.16)
    trigger = VisionStationTrigger(vp)
    await trigger.close()
    await trigger.close()
    health = await trigger.health()
    assert health.state == StationTriggerState.CLOSED


def test_close_is_idempotent() -> None:
    asyncio.run(_async_close_is_idempotent())


async def _async_health_reports_correctly(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder([])
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(), tag_size_m=0.16,
        qr_detector=qr_detector, station_registry=registry,
    )
    trigger = VisionStationTrigger(vp)
    health = await trigger.health()
    assert health.state == StationTriggerState.NOT_STARTED
    assert health.ready is False
    assert health.source == "vision_processor.shared_camera"


def test_health_reports_correctly(tmp_path: Path) -> None:
    asyncio.run(_async_health_reports_correctly(tmp_path))
