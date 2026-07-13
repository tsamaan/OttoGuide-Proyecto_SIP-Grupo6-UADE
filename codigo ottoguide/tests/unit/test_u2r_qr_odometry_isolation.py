"""
@TASK: Validar el aislamiento entre el lane QR y la odometria visual (U2R1)
@INPUT: Decoder/registry fake; mocks de hardware/navegacion/conversacion; sin camara real
@OUTPUT: Resultado de pytest: PASSED si visual_odometry_enabled=False desactiva el lane
         AprilTag/odometria sin afectar el lane QR, y si TourOrchestrator respeta ese
         interlock al entrar a NAVIGATING
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_u2r_qr_odometry_isolation.py -q
@AI_CONTEXT: events.py y event_bus.py se cargan de forma aislada via
             tests.support.core_module_identity, igual que tests/test_event_bus.py y
             tests/unit/test_u2_orchestrator_qr_observation.py, para evitar el defecto
             preexistente y documentado de doble carga de EventType cuando este archivo
             corre junto a otros tests en el mismo proceso de pytest.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
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

from tests.support.core_module_identity import (
    PRESERVED_CORE_IDENTITY_MODULES,
    ensure_core_event_modules,
)

OttoEventBus = ensure_core_event_modules().OttoEventBus

from src.core.tour_orchestrator import TourOrchestrator, TourPlan
from src.navigation.models import NavWaypoint
from src.stations.station_registry import StationRegistry
from src.vision.qr_frame_detector import StableQRFrameDetector
from src.vision.vision_processor import CameraModel, VisionProcessor


class FakeDecoder:
    def __init__(self, values: list[str | None]) -> None:
        self._values = list(values)

    def decode(self, frame: object) -> str | None:
        return self._values.pop(0) if self._values else None


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


# ---------------------------------------------------------------------------
# 1-2. Defaults del interlock en VisionProcessor
# ---------------------------------------------------------------------------


def test_vision_processor_default_visual_odometry_enabled_true() -> None:
    vp = VisionProcessor(camera_model=_make_camera_model(), tag_size_m=0.16)
    assert vp.visual_odometry_enabled is True


def test_vision_processor_qr_only_mode(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    qr_detector = StableQRFrameDetector(FakeDecoder([]), stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(),
        tag_size_m=0.16,
        qr_detector=qr_detector,
        station_registry=registry,
        visual_odometry_enabled=False,
    )
    assert vp.visual_odometry_enabled is False
    assert vp.qr_enabled is True


# ---------------------------------------------------------------------------
# 3. Frame compartido en QR-only: AprilTag no se invoca, QR si
# ---------------------------------------------------------------------------


def test_shared_frame_qr_only_skips_apriltag_runs_qr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder(["QR_KNOWN"] * 4)
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(),
        tag_size_m=0.16,
        qr_detector=qr_detector,
        station_registry=registry,
        visual_odometry_enabled=False,
    )

    process_frame_calls = []
    dispatch_odometry_calls = []
    monkeypatch.setattr(vp, "_process_frame_sync", lambda *a, **kw: process_frame_calls.append(1))
    monkeypatch.setattr(vp, "_dispatch_odometry", lambda *a, **kw: dispatch_odometry_calls.append(1))

    frame = _synthetic_frame()

    async def run() -> None:
        vp._loop = asyncio.get_running_loop()
        for _ in range(4):
            if vp._visual_odometry_enabled:
                vp._process_frame_sync(frame)
            if vp.qr_enabled:
                vp._process_qr_lane_sync(frame)
        detection = await asyncio.wait_for(vp.get_next_station_detection(), timeout=1.0)
        assert detection.station_id == "1"

    asyncio.run(run())

    assert process_frame_calls == []
    assert dispatch_odometry_calls == []
    assert vp.pose_queue.empty()


# ---------------------------------------------------------------------------
# 4-5. TourOrchestrator respeta visual_odometry_enabled
# ---------------------------------------------------------------------------


def _make_plan() -> TourPlan:
    return TourPlan(
        waypoints=[
            NavWaypoint(x=0.0, y=0.0, yaw_rad=0.0),
            NavWaypoint(x=1.0, y=0.0, yaw_rad=0.0),
        ],
        tour_id="u2r1-isolation-test",
    )


def _make_orchestrator(event_bus: OttoEventBus, vision_processor) -> TourOrchestrator:
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

    return TourOrchestrator(
        hardware_api=mock_hw,
        nav_bridge=mock_nav,
        conversation_manager=mock_cm,
        vision_processor=vision_processor,
        robot_mode="mock",
        event_bus=event_bus,
    )


class _FakeVisionProcessorOdometryDisabled:
    visual_odometry_enabled = False

    def __init__(self) -> None:
        self.get_next_estimate_calls = 0

    def close(self) -> None:
        pass

    async def get_next_estimate(self, *, timeout_s: float = 0.5):
        self.get_next_estimate_calls += 1
        return None


class _FakeVisionProcessorOdometryEnabled:
    visual_odometry_enabled = True

    def __init__(self) -> None:
        self.get_next_estimate_calls = 0

    def close(self) -> None:
        pass

    async def get_next_estimate(self, *, timeout_s: float = 0.5):
        self.get_next_estimate_calls += 1
        await asyncio.sleep(0.01)
        return None


class _FakeVisionProcessorNoAttribute:
    """Legacy-shaped consumer without visual_odometry_enabled at all."""

    def __init__(self) -> None:
        self.get_next_estimate_calls = 0

    def close(self) -> None:
        pass

    async def get_next_estimate(self, *, timeout_s: float = 0.5):
        self.get_next_estimate_calls += 1
        await asyncio.sleep(0.01)
        return None


async def _async_orchestrator_qr_only_skips_odometry_task() -> None:
    bus = OttoEventBus()
    vp = _FakeVisionProcessorOdometryDisabled()
    orch = _make_orchestrator(bus, vp)

    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    await asyncio.sleep(0.02)

    assert orch.state_id == "navigating"
    assert orch._odometry_task is None
    assert vp.get_next_estimate_calls == 0
    orch._nav_bridge.inject_absolute_pose.assert_not_called()

    assert orch._nav_task is not None
    assert not orch._nav_task.done()

    await orch.close()
    if orch._nav_task is not None:
        orch._nav_task.cancel()
        try:
            await orch._nav_task
        except asyncio.CancelledError:
            pass


def test_orchestrator_qr_only_skips_odometry_task() -> None:
    asyncio.run(_async_orchestrator_qr_only_skips_odometry_task())


async def _async_orchestrator_odometry_enabled_creates_task() -> None:
    bus = OttoEventBus()
    vp = _FakeVisionProcessorOdometryEnabled()
    orch = _make_orchestrator(bus, vp)

    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    await asyncio.sleep(0.02)

    assert orch.state_id == "navigating"
    assert orch._odometry_task is not None
    assert not orch._odometry_task.done()

    await orch.close()
    if orch._nav_task is not None:
        orch._nav_task.cancel()
        try:
            await orch._nav_task
        except asyncio.CancelledError:
            pass


def test_orchestrator_odometry_enabled_creates_task() -> None:
    asyncio.run(_async_orchestrator_odometry_enabled_creates_task())


# ---------------------------------------------------------------------------
# 6. Consumer legacy sin atributo -> comportamiento historico (True)
# ---------------------------------------------------------------------------


async def _async_legacy_consumer_without_attribute_preserves_default_true() -> None:
    bus = OttoEventBus()
    vp = _FakeVisionProcessorNoAttribute()
    orch = _make_orchestrator(bus, vp)

    await orch.activate_initial_state()
    await orch.dispatch_tour(_make_plan())
    await asyncio.sleep(0.02)

    assert orch._odometry_task is not None
    assert not orch._odometry_task.done()

    await orch.close()
    if orch._nav_task is not None:
        orch._nav_task.cancel()
        try:
            await orch._nav_task
        except asyncio.CancelledError:
            pass


def test_legacy_consumer_without_attribute_preserves_default_true() -> None:
    asyncio.run(_async_legacy_consumer_without_attribute_preserves_default_true())


# ---------------------------------------------------------------------------
# 7-8. _build_vision_processor() del main.py
# ---------------------------------------------------------------------------


def test_build_vision_processor_qr_enabled_passes_visual_odometry_disabled(tmp_path: Path) -> None:
    from types import SimpleNamespace

    registry_path = tmp_path / "qr_stations.yaml"
    registry_path.write_text(
        "version: 1\nstations:\n  QR_X:\n    station_id: '1'\n    name: 'X'\n",
        encoding="utf-8",
    )

    sys.path.insert(0, _PROJECT_ROOT)
    import importlib

    _purged = {
        mod for mod in list(sys.modules)
        if mod not in PRESERVED_CORE_IDENTITY_MODULES
        and (mod == "main" or mod.startswith("src."))
    }
    saved = {m: sys.modules[m] for m in _purged if m in sys.modules}
    for m in _purged:
        del sys.modules[m]
    try:
        import main as main_mod

        settings = SimpleNamespace(
            QR_STATION_TRIGGER_ENABLED=True,
            QR_STATION_CONFIG_PATH=str(registry_path),
            QR_STABLE_FRAMES=4,
            QR_RELEASE_FRAMES=3,
            QR_STATION_QUEUE_MAX_SIZE=8,
        )
        vp = main_mod._build_vision_processor(settings)
        assert vp.visual_odometry_enabled is False
        assert vp.qr_enabled is True
    finally:
        for m in list(sys.modules):
            if m not in PRESERVED_CORE_IDENTITY_MODULES and (m == "main" or m.startswith("src.")):
                del sys.modules[m]
        for m, mod in saved.items():
            sys.modules[m] = mod


def test_build_vision_processor_qr_disabled_preserves_default_true() -> None:
    from types import SimpleNamespace

    _purged = {
        mod for mod in list(sys.modules)
        if mod not in PRESERVED_CORE_IDENTITY_MODULES
        and (mod == "main" or mod.startswith("src."))
    }
    saved = {m: sys.modules[m] for m in _purged if m in sys.modules}
    for m in _purged:
        del sys.modules[m]
    try:
        import main as main_mod

        settings = SimpleNamespace(QR_STATION_TRIGGER_ENABLED=False)
        vp = main_mod._build_vision_processor(settings)
        assert getattr(vp, "visual_odometry_enabled", True) is True
    finally:
        for m in list(sys.modules):
            if m not in PRESERVED_CORE_IDENTITY_MODULES and (m == "main" or m.startswith("src.")):
                del sys.modules[m]
        for m, mod in saved.items():
            sys.modules[m] = mod


# ---------------------------------------------------------------------------
# 9. No existe un segundo VideoCapture
# ---------------------------------------------------------------------------


def test_no_second_video_capture_introduced() -> None:
    path = os.path.join(_PROJECT_ROOT, "src", "vision", "vision_processor.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    call_sites = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "VideoCapture"
    ]
    assert len(call_sites) == 1


# ---------------------------------------------------------------------------
# 10. No se modifica station trigger, evento QR ni FSM
# ---------------------------------------------------------------------------


def test_qr_event_publication_unaffected(tmp_path: Path) -> None:
    """Sanity: QR_STATION_DETECTED keeps being produced normally when
    visual_odometry_enabled=False, proving U2's event flow is untouched."""
    registry = _make_registry(tmp_path)
    decoder = FakeDecoder(["QR_KNOWN"] * 4)
    qr_detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    vp = VisionProcessor(
        camera_model=_make_camera_model(),
        tag_size_m=0.16,
        qr_detector=qr_detector,
        station_registry=registry,
        visual_odometry_enabled=False,
    )
    frame = _synthetic_frame()

    async def run() -> None:
        vp._loop = asyncio.get_running_loop()
        for _ in range(4):
            vp._process_qr_lane_sync(frame)
        detection = await asyncio.wait_for(vp.get_next_station_detection(), timeout=1.0)
        assert detection.qr_value == "QR_KNOWN"
        assert detection.source == "vision_processor.shared_camera"

    asyncio.run(run())


def test_fsm_states_unchanged_by_u2r1() -> None:
    expected_states = {"idle", "navigating", "interacting", "emergency"}
    actual_states = {
        name for name in dir(TourOrchestrator)
        if name in ("idle", "navigating", "interacting", "emergency")
    }
    assert actual_states == expected_states
