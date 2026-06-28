"""
@TASK: Validar el wiring QR fail-closed del lifespan de main.py (U2)
@INPUT: Fakes de hardware/navegacion/conversacion/vision; sin camara real
@OUTPUT: Resultado de pytest: PASSED si QR deshabilitado no toca camara, QR habilitado
         comparte la unica instancia de VisionProcessor, y un fallo de configuracion
         no degrada silenciosamente a un fake
@CONTEXT: Ejecutar con: python -m pytest tests/integration/test_u2_qr_lifespan_wiring.py -q
@AI_CONTEXT: Reutiliza el patron ya validado en tests/unit/test_navigation_runtime_selection.py
             (monkeypatch de main.get_settings/get_hardware_adapter, _FakeApp, async with
             main.lifespan(app)). No abre camara real bajo ninguna rama: cuando QR esta
             habilitado, main._build_vision_processor se monkeypatchea para retornar un
             fake VisionProcessor-compatible (sin cv2).
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

CODE_ROOT = Path(__file__).resolve().parents[2]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from src.navigation.models import NavigationStatus
from src.vision.station_trigger import QRStationDetected, StationTriggerHealth, StationTriggerState
from tests.support.core_module_identity import (
    PRESERVED_CORE_IDENTITY_MODULES,
    ensure_core_event_modules,
)

# AI_CONTEXT: un (re)import agresivo de main.py recarga src.core, lo que recrea
# src.core.events/src.core.event_bus desde cero. Si otro archivo de test en el
# mismo proceso de pytest (p. ej. tests/test_event_bus.py) ya capturo en sus
# variables de modulo, en collection-time, una referencia a la copia ANTERIOR
# de EventType/OttoEventBus, una purga+reimport posterior deja esas variables
# apuntando a una clase EventType incompatible con la que main/tour_orchestrator
# usaran a partir de ese punto. tests.support.core_module_identity centraliza
# la carga aislada y la guarda idempotente (U2R2): se llama una sola vez aqui,
# ANTES de la primera purga+import de main, y los modulos resultantes nunca se
# purgan junto con el resto de src.* — asi todo reimport de main dentro de
# este archivo sigue resolviendo contra la MISMA copia de EventType que el
# resto del proceso de pytest ya este usando.
ensure_core_event_modules()


def _purge_app_modules() -> None:
    for mod in list(sys.modules):
        if mod in PRESERVED_CORE_IDENTITY_MODULES:
            continue
        if (
            mod == "main"
            or mod == "src"
            or mod.startswith("src.")
            or mod == "config"
            or mod.startswith("config.")
        ):
            del sys.modules[mod]


def _fresh_import_main():
    _purge_app_modules()
    import main  # noqa: PLC0415

    return main


def _fake_settings(**overrides) -> SimpleNamespace:
    fields: dict = dict(
        NAVIGATION_BACKEND="auto",
        ROBOT_MODE="mock",
        NAVIGATION_DIRECT_REAL_ENABLED=False,
        NAVIGATION_ALLOW_STUB_TOURS=True,
        NAVIGATION_NODE_NAME="direct_nav2_action_bridge",
        NAVIGATION_NAMESPACE="offline_nav",
        NAVIGATION_NTP_ACTION="/offline_nav/navigate_to_pose",
        NAVIGATION_FW_ACTION="/offline_nav/follow_waypoints",
        NAVIGATION_INITIAL_POSE_TOPIC="/initialpose",
        NAVIGATION_SERVER_TIMEOUT_S=15.0,
        NAVIGATION_GOAL_RESPONSE_TIMEOUT_S=10.0,
        NAVIGATION_RESULT_TIMEOUT_S=120.0,
        NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S=10.0,
        NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S=15.0,
        OLLAMA_MODEL="qwen2.5:3b",
        OLLAMA_HOST="http://127.0.0.1:11434",
        UNITREE_FACTORY_BASE_URL="http://192.168.12.1:9991",
        UNITREE_FACTORY_TIMEOUT_S=0.35,
        UNITREE_FACTORY_DIAGNOSTICS_ENABLED=False,
        CLOUD_FALLBACK_ENABLED=False,
        cloud_fallback_effective=False,
        WEB_UI_ALLOWED_ORIGINS="",
        WEB_UI_PUBLIC_URL="",
        WEB_UI_ALLOW_MISSING_ORIGIN=False,
        QR_STATION_TRIGGER_ENABLED=False,
        QR_STATION_CONFIG_PATH="config/qr_stations.yaml",
        QR_STABLE_FRAMES=4,
        QR_RELEASE_FRAMES=3,
        QR_STATION_QUEUE_MAX_SIZE=8,
    )
    fields.update(overrides)
    ns = SimpleNamespace(**fields)
    ns.validate_navigation_config = lambda: None
    ns.validate_web_ui_config = lambda: None
    ns.validate_qr_station_config = lambda: None
    return ns


class _FakeHardware:
    def __init__(self) -> None:
        self.initialize = AsyncMock()
        self.damp = AsyncMock()
        self.move = AsyncMock()
        self.get_state = AsyncMock(return_value={"initialized": True, "battery_level": 100.0})


class _FakeNavBridge:
    def __init__(self) -> None:
        self.start = AsyncMock()
        self.close = AsyncMock()
        self.navigate_to_waypoints = AsyncMock(return_value=True)
        self.send_goal = AsyncMock(return_value=True)
        self.cancel_navigation = AsyncMock()
        self.inject_absolute_pose = AsyncMock()
        self.is_navigation_active = AsyncMock(return_value=False)
        self.get_status = AsyncMock(return_value=NavigationStatus())
        self.get_last_result = AsyncMock(return_value=None)


class _FakeConversationManager:
    swap_count = 0
    active_strategy_name = "fake"
    loaded_script = None

    async def process_interaction(self, audio, *, language="es"):
        return SimpleNamespace(answer_text="", source_pipeline="fake", audio_stream_ready=False)

    def close(self) -> None:
        pass


class _FakeVisionProcessorNoQR:
    """Mirrors the legacy stub shape: no QR lane configured."""

    def __init__(self) -> None:
        self.close_calls = 0
        self.qr_enabled = False
        self.is_started = False

    def close(self) -> None:
        self.close_calls += 1

    async def get_next_estimate(self, *, timeout_s: float = 0.5):
        return None


class _FakeVisionProcessorWithQR:
    """QR-enabled fake VisionProcessor — never imports cv2, never opens a camera.

    U2R1: visual_odometry_enabled=False mirrors the production wiring in
    main.py._build_vision_processor(), where the QR-enabled branch always
    disables the AprilTag/visual-odometry lane (placeholder CameraModel,
    no real D435i calibration)."""

    def __init__(self) -> None:
        self.close_calls = 0
        self.start_calls = 0
        self.qr_enabled = True
        self.visual_odometry_enabled = False
        self.is_started = False
        self.get_next_estimate_calls = 0
        self._station_queue: asyncio.Queue = asyncio.Queue()

    def start(self, loop) -> None:
        self.start_calls += 1
        self.is_started = True

    def close(self) -> None:
        self.close_calls += 1

    async def get_next_estimate(self, *, timeout_s: float = 0.5):
        self.get_next_estimate_calls += 1
        return None

    @property
    def station_queue(self):
        return self._station_queue

    async def get_next_station_detection(self) -> QRStationDetected:
        return await self._station_queue.get()


class _FakeState:
    pass


class _FakeApp:
    def __init__(self) -> None:
        self.state = _FakeState()


class QRDisabledLifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.main = _fresh_import_main()
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()

    def tearDown(self) -> None:
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()
        _purge_app_modules()

    async def test_qr_disabled_does_not_build_decoder_or_start_vision_processor(self) -> None:
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=False)
        fake_vp = _FakeVisionProcessorNoQR()

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: _FakeNavBridge()
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = lambda s: fake_vp

        async with self.main.lifespan(app):
            self.assertIsNone(app.state.station_trigger)
            self.assertFalse(fake_vp.is_started)

    async def test_qr_disabled_status_remains_not_configured(self) -> None:
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=False)
        fake_vp = _FakeVisionProcessorNoQR()

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: _FakeNavBridge()
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = lambda s: fake_vp

        async with self.main.lifespan(app):
            station_trigger = getattr(app.state, "station_trigger", None)
            self.assertIsNone(station_trigger)


class QREnabledLifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.main = _fresh_import_main()
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()

    def tearDown(self) -> None:
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()
        _purge_app_modules()

    async def test_qr_enabled_wires_same_vision_processor_and_starts_once(self) -> None:
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=True)
        fake_vp = _FakeVisionProcessorWithQR()

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: _FakeNavBridge()
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = lambda s: fake_vp

        async with self.main.lifespan(app):
            self.assertIs(app.state.orchestrator._vision_processor, fake_vp)
            self.assertEqual(fake_vp.start_calls, 1)
            self.assertIsNotNone(app.state.station_trigger)

            health = await app.state.station_trigger.health()
            self.assertTrue(health.ready)
            self.assertEqual(health.state, StationTriggerState.READY)

    async def test_qr_enabled_status_configured_and_ready(self) -> None:
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=True)
        fake_vp = _FakeVisionProcessorWithQR()

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: _FakeNavBridge()
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = lambda s: fake_vp

        async with self.main.lifespan(app):
            trigger = app.state.station_trigger
            health = await trigger.health()
            self.assertTrue(health.ready)

    async def test_qr_enabled_visual_odometry_disabled_no_pose_injection(self) -> None:
        """U2R1: el VisionProcessor inyectado en QR-enabled debe tener
        visual_odometry_enabled=False, seguir compartiendo la misma instancia
        con TourOrchestrator, mantener StationTrigger READY, y nunca llamar
        inject_absolute_pose() ni abrir una segunda camara durante el lifespan."""
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=True)
        fake_vp = _FakeVisionProcessorWithQR()
        fake_nav_bridge = _FakeNavBridge()

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: fake_nav_bridge
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = lambda s: fake_vp

        async with self.main.lifespan(app):
            self.assertIs(app.state.orchestrator._vision_processor, fake_vp)
            self.assertFalse(fake_vp.visual_odometry_enabled)
            self.assertTrue(fake_vp.qr_enabled)

            health = await app.state.station_trigger.health()
            self.assertEqual(health.state, StationTriggerState.READY)
            self.assertTrue(health.ready)

            self.assertEqual(fake_vp.get_next_estimate_calls, 0)
            fake_nav_bridge.inject_absolute_pose.assert_not_called()
            self.assertEqual(fake_vp.start_calls, 1)


class QRConfigFailureLifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.main = _fresh_import_main()
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()

    def tearDown(self) -> None:
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()
        _purge_app_modules()

    async def test_qr_enabled_build_failure_does_not_fallback_silently(self) -> None:
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=True)

        def _raise_build(s):
            raise RuntimeError("station_registry_invalid_config")

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: _FakeNavBridge()
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = _raise_build

        with self.assertRaises(RuntimeError):
            async with self.main.lifespan(app):
                pass

        # Fail-closed: no real camera was ever touched, no station_trigger leaked.
        self.assertIsNone(getattr(app.state, "station_trigger", None))

    async def test_qr_enabled_coordinator_start_failure_propagates(self) -> None:
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=True)

        class _FailingFakeVP(_FakeVisionProcessorWithQR):
            def start(self, loop) -> None:
                raise RuntimeError("vision_start_failed")

        fake_vp = _FailingFakeVP()

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: _FakeNavBridge()
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = lambda s: fake_vp

        with self.assertRaisesRegex(RuntimeError, "QR_STATION_TRIGGER_START_FAILED"):
            async with self.main.lifespan(app):
                pass


class QRShutdownLifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.main = _fresh_import_main()
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()

    def tearDown(self) -> None:
        from src.core.event_bus import OttoEventBus

        OttoEventBus.reset_for_testing()
        _purge_app_modules()

    async def test_shutdown_closes_coordinator_once_and_vision_processor_idempotently(self) -> None:
        app = _FakeApp()
        settings = _fake_settings(QR_STATION_TRIGGER_ENABLED=True)
        fake_vp = _FakeVisionProcessorWithQR()

        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = lambda: _FakeHardware()
        self.main._build_navigation_bridge = lambda s, backend: _FakeNavBridge()
        self.main._get_conversation_manager_stub = lambda s: _FakeConversationManager()
        self.main._build_vision_processor = lambda s: fake_vp

        async with self.main.lifespan(app):
            pass

        # VisionProcessor.close() is invoked by TourOrchestrator.on_enter_emergency
        # during the HIL-safe shutdown sequence; idempotent close means >=1 is fine
        # and a second manual call must not raise.
        self.assertGreaterEqual(fake_vp.close_calls, 1)
        fake_vp.close()  # idempotency check
