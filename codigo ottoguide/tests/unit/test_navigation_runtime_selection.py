"""Fase 2H.2 — seleccion fail-closed del backend de navegacion en main.py.

Cubre _resolve_navigation_backend, _check_direct_real_interlock,
_build_navigation_bridge, el lifespan completo de FastAPI (exito, fallo de
start, fallo de close), y la observabilidad de readiness/StatusResponse en
api/router.py. main.py no es importable directamente en este workstation
porque src.core -> src.interaction depende de pyttsx3/speech_recognition/
aiohttp (gap preexistente y no relacionado, documentado en
test_architecture_reconciliation_contract.py); estos tests instalan mocks
minimos de esos tres modulos antes de importar main, y los retiran despues.
Nunca depende de ROS 2 real: AsyncNav2Bridge y DirectNav2ActionBridge no
importan rclpy en __init__, solo en start().

config/settings.py depende de pydantic_settings, que no esta instalado en
el venv Python 3.12 de WSL Ubuntu-24.04/ROS 2 Jazzy usado para los smoke
tests ROS de este repositorio (gap de entorno preexistente, simetrico al
de pyttsx3/speech_recognition/aiohttp en Windows: ningun test anterior que
importa config.settings -- p.ej. tests/unit/test_settings.py -- puede
colectarse bajo esa misma WSL). Todas las clases de este modulo se
saltan (skip, no error) si pydantic_settings no esta disponible, en vez
de fallar la coleccion completa del archivo.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import subprocess
import sys
import textwrap
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from tests.support.core_module_identity import (  # noqa: E402
    PRESERVED_CORE_IDENTITY_MODULES,
    ensure_core_event_modules,
)
from tests.support.scoped_module_isolation import ModuleIsolationScope  # noqa: E402

_FRESH_IMPORT_PREFIXES = frozenset({"main", "src", "src.", "config", "config."})

# U2R2: cargar events.py/event_bus.py bajo su identidad canonica ANTES de la
# primera purga/reimport de main, para que ningun reimport posterior de este
# archivo (ni de ningun otro test del mismo proceso de pytest) reemplace la
# clase EventType/OttoEventBus ya en uso por el resto del proceso.
ensure_core_event_modules()

_PYDANTIC_SETTINGS_AVAILABLE = importlib.util.find_spec("pydantic_settings") is not None
_SKIP_REASON = "pydantic_settings not installed in this environment (pre-existing gap)"

# api/router.py imports fastapi at module scope; this is a second,
# independent pre-existing environment gap (the WSL ROS 2 Jazzy Python 3.12
# venv used for the ROS smoke tests in this repository has neither
# pydantic_settings nor fastapi installed -- no test under tests/unit/
# imported api.router before this phase, so this gap was never exercised).
_FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
_FASTAPI_SKIP_REASON = "fastapi not installed in this environment (pre-existing gap)"

# src.navigation.models is pure (no pydantic_settings/ROS), so it is always
# importable here -- only config.settings (and therefore main, which imports
# it) depends on pydantic_settings being installed.
from src.navigation.models import (  # noqa: E402
    NavigationResult,
    NavigationStatus,
    NavigationTerminalStatus,
)

if _PYDANTIC_SETTINGS_AVAILABLE:
    from config.settings import Settings, get_settings  # noqa: E402

_INTERACTION_DEPENDENCY_MOCKS = ("pyttsx3", "speech_recognition", "aiohttp")


def _install_interaction_dependency_mocks() -> dict:
    """Install minimal fakes for the three pre-existing, unrelated missing
    packages (pyttsx3/speech_recognition/aiohttp) so that `import main` can
    walk its real src.core -> src.interaction import chain on a workstation
    without them. Returns the set of names actually installed (vs already
    present), so the caller can remove only what it added."""
    installed = {}
    for name in _INTERACTION_DEPENDENCY_MOCKS:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
            installed[name] = True
    return installed


def _remove_interaction_dependency_mocks(installed: dict) -> None:
    for name in installed:
        sys.modules.pop(name, None)


_module_isolation_scope: ModuleIsolationScope | None = None


def _purge_app_modules() -> None:
    """Cierra el scope de aislamiento abierto por _fresh_import_main(),
    restaurando exactamente los objetos main/src.*/config.* que existian
    antes de ese import fresco (U2R2: preserva explicitamente
    src.core.events/event_bus/tour_orchestrator via PRESERVED_CORE_IDENTITY_MODULES,
    que sostienen la identidad canonica de EventType/OttoEventBus compartida
    por todo el proceso de pytest). A diferencia del purge anterior, esto NO
    deja main/src.*/config.* borrados indefinidamente: los restaura a los
    objetos exactos previos al scope, en vez de dejar que el siguiente
    reimport los recree desde cero."""
    global _module_isolation_scope
    if _module_isolation_scope is not None:
        _module_isolation_scope.close()
        _module_isolation_scope = None


def _fresh_import_main():
    """Reimport main.py from scratch with the interaction dependency mocks
    installed, returning (main_module, installed_mocks) for cleanup.

    R1A/R3: si la instalacion de mocks o el import de main fallan, el scope
    se cierra y la referencia global se limpia ANTES de propagar la
    excepcion original -- de lo contrario el scope queda abierto
    indefinidamente y el guard de hilo de ModuleIsolationScope queda
    activado para siempre, haciendo que todo test posterior en el mismo
    proceso falle con un RuntimeError de anidamiento en vez del error de
    import real. No se degrada el fallo a skip ni a fallback: la excepcion
    original siempre se re-lanza sin cambios."""
    global _module_isolation_scope
    if _module_isolation_scope is not None:
        _module_isolation_scope.close()
    scope = ModuleIsolationScope(
        _FRESH_IMPORT_PREFIXES, preserve=PRESERVED_CORE_IDENTITY_MODULES
    )
    scope.open()
    _module_isolation_scope = scope
    installed: dict = {}
    try:
        installed = _install_interaction_dependency_mocks()
        import main  # noqa: PLC0415
    except BaseException:
        _remove_interaction_dependency_mocks(installed)
        scope.close()
        _module_isolation_scope = None
        raise
    return main, installed


def _fake_settings(**overrides) -> SimpleNamespace:
    """Minimal SimpleNamespace replacing config.settings.Settings.

    All field defaults match config.settings.Settings' own defaults (Fase
    2H.2.2: corrected after an audit found several of these had drifted from
    the real model -- ROBOT_MODE, NAVIGATION_NODE_NAME and every NAVIGATION_*
    timeout, plus OLLAMA_MODEL/OLLAMA_HOST/UNITREE_FACTORY_TIMEOUT_S -- which
    risked masking a real Settings regression behind a passing fake). This
    can be swapped in transparently. validate_navigation_config() is a
    no-op; Pydantic validation is exercised separately in
    NavigationConfigValidationTests. See SettingsDefaultsParityTests below
    for the test that pins these defaults against the real Settings model
    whenever pydantic_settings is available.
    """
    fields: dict = dict(
        NAVIGATION_BACKEND="auto",
        ROBOT_MODE="mock",
        NAVIGATION_DIRECT_REAL_ENABLED=False,
        NAVIGATION_ALLOW_STUB_TOURS=False,
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
    )
    fields.update(overrides)
    ns = SimpleNamespace(**fields)
    ns.validate_navigation_config = lambda: None
    ns.validate_web_ui_config = lambda: None
    return ns


def _install_router_fakes() -> dict:
    """If fastapi is absent, install minimal fakes to allow api.router import.
    Returns names actually installed (only what this call added), for symmetric
    cleanup via _remove_router_fakes.  Current environments have fastapi
    installed, so this is a no-op in practice."""
    # If api.router is already cached, no fakes are ever needed.
    if "api.router" in sys.modules:
        return {}
    # find_spec raises ValueError when a module is in sys.modules with
    # __spec__=None (e.g. after user-site installs on some platforms).
    # Fall back to a direct sys.modules probe in that case.
    try:
        fastapi_found = importlib.util.find_spec("fastapi") is not None
    except (ValueError, ModuleNotFoundError):
        fastapi_found = (
            "fastapi" in sys.modules and sys.modules.get("fastapi") is not None
        )
    if fastapi_found:
        return {}

    installed: dict = {}

    if "fastapi" not in sys.modules:
        fake_fastapi = types.ModuleType("fastapi")

        class _APIRouter:
            def post(self, *a, **kw): return lambda f: f
            def get(self, *a, **kw): return lambda f: f
            def websocket(self, *a, **kw): return lambda f: f

        fake_fastapi.APIRouter = _APIRouter
        fake_fastapi.BackgroundTasks = MagicMock
        fake_fastapi.Depends = lambda f=None: f
        fake_fastapi.HTTPException = Exception
        fake_fastapi.Request = MagicMock
        fake_fastapi.WebSocket = MagicMock
        fake_fastapi.WebSocketDisconnect = Exception
        fake_fastapi.status = SimpleNamespace(
            HTTP_200_OK=200, HTTP_202_ACCEPTED=202, HTTP_404_NOT_FOUND=404,
            HTTP_409_CONFLICT=409, HTTP_422_UNPROCESSABLE_ENTITY=422,
            HTTP_500_INTERNAL_SERVER_ERROR=500, HTTP_503_SERVICE_UNAVAILABLE=503,
        )
        sys.modules["fastapi"] = fake_fastapi
        installed["fastapi"] = True

    if "statemachine" not in sys.modules:
        fake_sm = types.ModuleType("statemachine")
        sys.modules["statemachine"] = fake_sm
        installed["statemachine"] = True
    if "statemachine.exceptions" not in sys.modules:
        fake_sm_exc = types.ModuleType("statemachine.exceptions")
        fake_sm_exc.TransitionNotAllowed = Exception
        sys.modules["statemachine.exceptions"] = fake_sm_exc
        installed["statemachine.exceptions"] = True

    if "src.api.websocket_manager" not in sys.modules:
        fake_ws = types.ModuleType("src.api.websocket_manager")
        fake_ws.TelemetryManager = MagicMock
        sys.modules["src.api.websocket_manager"] = fake_ws
        installed["src.api.websocket_manager"] = True

    return installed


def _remove_router_fakes(installed: dict) -> None:
    for name in installed:
        sys.modules.pop(name, None)


class _FakeHardware:
    def __init__(self, *, state: Optional[dict] = None, initialize_exc: Optional[Exception] = None):
        self.initialize = AsyncMock(side_effect=initialize_exc)
        self.stop_motion = AsyncMock()
        self.move = AsyncMock()
        self.get_state = AsyncMock(return_value=state if state is not None else {"initialized": True})


class _FakeNavBridge:
    def __init__(
        self,
        *,
        remote_state_unknown: bool = False,
        action_name: Optional[str] = None,
        goal_uuid: Optional[str] = None,
        start_exc: Optional[Exception] = None,
        close_exc: Optional[Exception] = None,
    ):
        self.start = AsyncMock(side_effect=start_exc)
        self.close = AsyncMock(side_effect=close_exc)
        self.navigate_to_waypoints = AsyncMock(return_value=True)
        self.send_goal = AsyncMock(return_value=True)
        self.cancel_navigation = AsyncMock()
        self.inject_absolute_pose = AsyncMock()
        self.is_navigation_active = AsyncMock(return_value=False)
        self._status = NavigationStatus(
            remote_state_unknown=remote_state_unknown,
            action_name=action_name,
            goal_uuid=goal_uuid,
        )
        self.get_status = AsyncMock(return_value=self._status)
        self.get_last_result = AsyncMock(return_value=None)


class _FakeNavBridgeNoStatus:
    """NavigationPort-shaped fake without get_status — exercises the fail-closed
    absent-method path added in Phase 2H.2.1."""
    def __init__(self):
        self.start = AsyncMock()
        self.close = AsyncMock()
        self.navigate_to_waypoints = AsyncMock(return_value=True)
        self.send_goal = AsyncMock(return_value=True)
        self.cancel_navigation = AsyncMock()
        self.inject_absolute_pose = AsyncMock()
        self.is_navigation_active = AsyncMock(return_value=False)
        self.get_last_result = AsyncMock(return_value=None)
        # deliberately no get_status attribute


class _FakeState:
    pass


class _FakeApp:
    def __init__(self):
        self.state = _FakeState()


# ---------------------------------------------------------------------------
# _resolve_navigation_backend
# ---------------------------------------------------------------------------

class BackendResolutionTests(unittest.TestCase):
    def setUp(self):
        self.main, self._mocks = _fresh_import_main()

    def tearDown(self):
        _remove_interaction_dependency_mocks(self._mocks)
        _purge_app_modules()

    def _settings(self, backend: str, robot_mode: str) -> SimpleNamespace:
        return SimpleNamespace(NAVIGATION_BACKEND=backend, ROBOT_MODE=robot_mode)

    def test_auto_real_resolves_legacy(self):
        self.assertEqual(
            self.main._resolve_navigation_backend(self._settings("auto", "real")), "legacy"
        )

    def test_auto_mock_resolves_stub(self):
        self.assertEqual(
            self.main._resolve_navigation_backend(self._settings("auto", "mock")), "stub"
        )

    def test_auto_sim_resolves_stub(self):
        self.assertEqual(
            self.main._resolve_navigation_backend(self._settings("auto", "sim")), "stub"
        )

    def test_auto_demo_resolves_stub(self):
        self.assertEqual(
            self.main._resolve_navigation_backend(self._settings("auto", "demo")), "stub"
        )

    def test_legacy_explicit_resolves_legacy_in_any_mode(self):
        for mode in ("real", "sim", "mock", "demo"):
            self.assertEqual(
                self.main._resolve_navigation_backend(self._settings("legacy", mode)), "legacy"
            )

    def test_direct_explicit_resolves_direct_in_any_mode(self):
        for mode in ("real", "sim", "mock", "demo"):
            self.assertEqual(
                self.main._resolve_navigation_backend(self._settings("direct", mode)), "direct"
            )

    def test_stub_explicit_resolves_stub_in_non_real_mode(self):
        for mode in ("sim", "mock", "demo"):
            self.assertEqual(
                self.main._resolve_navigation_backend(self._settings("stub", mode)), "stub"
            )

    def test_stub_real_is_forbidden(self):
        with self.assertRaisesRegex(RuntimeError, "NAVIGATION_STUB_FORBIDDEN_IN_REAL_MODE"):
            self.main._resolve_navigation_backend(self._settings("stub", "real"))

    def test_disabled_real_resolves_disabled(self):
        self.assertEqual(
            self.main._resolve_navigation_backend(self._settings("disabled", "real")),
            "disabled",
        )


# ---------------------------------------------------------------------------
# _check_direct_real_interlock
# ---------------------------------------------------------------------------

class DirectRealInterlockTests(unittest.TestCase):
    def setUp(self):
        self.main, self._mocks = _fresh_import_main()

    def tearDown(self):
        _remove_interaction_dependency_mocks(self._mocks)
        _purge_app_modules()

    def _settings(self, robot_mode: str, latch: bool) -> SimpleNamespace:
        return SimpleNamespace(ROBOT_MODE=robot_mode, NAVIGATION_DIRECT_REAL_ENABLED=latch)

    def test_direct_real_latch_false_raises(self):
        with self.assertRaisesRegex(RuntimeError, "DIRECT_NAVIGATION_REAL_MODE_NOT_AUTHORIZED"):
            self.main._check_direct_real_interlock(self._settings("real", False), "direct")

    def test_direct_real_latch_true_permitted(self):
        self.main._check_direct_real_interlock(self._settings("real", True), "direct")  # no raise

    def test_direct_non_real_never_blocked_by_latch(self):
        for mode in ("sim", "mock", "demo"):
            self.main._check_direct_real_interlock(self._settings(mode, False), "direct")

    def test_legacy_and_stub_never_blocked_regardless_of_latch(self):
        for backend in ("legacy", "stub"):
            for latch in (False, True):
                self.main._check_direct_real_interlock(self._settings("real", latch), backend)


# ---------------------------------------------------------------------------
# _build_navigation_bridge
# ---------------------------------------------------------------------------

class NavigationBridgeFactoryTests(unittest.TestCase):
    def setUp(self):
        self.main, self._mocks = _fresh_import_main()

    def tearDown(self):
        _remove_interaction_dependency_mocks(self._mocks)
        _purge_app_modules()

    def test_legacy_builds_async_nav2_bridge(self):
        # AsyncNav2Bridge's module imports rclpy/cv2 at module scope (unlike
        # DirectNav2ActionBridge, which only imports rclpy lazily inside
        # start()), so building it even just for __init__ requires the same
        # ROS mocks used by ModelCompatibilityTests in
        # test_architecture_reconciliation_contract.py.
        from tests.mocks.mock_ros2 import install_mocks

        install_mocks(sys.modules)
        try:
            from src.navigation import AsyncNav2Bridge

            settings = SimpleNamespace(NAVIGATION_BACKEND="legacy")
            bridge = self.main._build_navigation_bridge(settings, "legacy")
            self.assertIsInstance(bridge, AsyncNav2Bridge)
        finally:
            for name in (
                "rclpy", "rclpy.executors", "rclpy.node",
                "geometry_msgs", "geometry_msgs.msg",
                "nav2_simple_commander", "nav2_simple_commander.robot_navigator",
            ):
                sys.modules.pop(name, None)

    def test_direct_builds_direct_bridge_with_every_setting(self):
        from src.navigation import DirectNav2ActionBridge

        settings = SimpleNamespace(
            NAVIGATION_BACKEND="direct",
            NAVIGATION_NODE_NAME="custom_node",
            NAVIGATION_NAMESPACE="custom_ns",
            NAVIGATION_NTP_ACTION="/custom_ns/navigate_to_pose",
            NAVIGATION_FW_ACTION="/custom_ns/follow_waypoints",
            NAVIGATION_INITIAL_POSE_TOPIC="/custom_initialpose",
            NAVIGATION_SERVER_TIMEOUT_S=1.0,
            NAVIGATION_GOAL_RESPONSE_TIMEOUT_S=2.0,
            NAVIGATION_RESULT_TIMEOUT_S=3.0,
            NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S=4.0,
            NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S=5.0,
        )
        bridge = self.main._build_navigation_bridge(settings, "direct")
        self.assertIsInstance(bridge, DirectNav2ActionBridge)
        self.assertEqual(bridge._node_name, "custom_node")
        self.assertEqual(bridge._namespace, "custom_ns")
        self.assertEqual(bridge._ntp_action, "/custom_ns/navigate_to_pose")
        self.assertEqual(bridge._fw_action, "/custom_ns/follow_waypoints")
        self.assertEqual(bridge._initial_pose_topic, "/custom_initialpose")
        self.assertEqual(bridge._server_timeout_s, 1.0)
        self.assertEqual(bridge._goal_response_timeout_s, 2.0)
        self.assertEqual(bridge._result_timeout_s, 3.0)
        self.assertEqual(bridge._cancel_response_timeout_s, 4.0)
        self.assertEqual(bridge._cancel_terminal_timeout_s, 5.0)

    def test_stub_builds_minimal_nav_stub(self):
        settings = SimpleNamespace(NAVIGATION_BACKEND="stub")
        bridge = self.main._build_navigation_bridge(settings, "stub")
        self.assertIsInstance(bridge, self.main._MinimalNavStub)

    def test_disabled_builds_without_importing_rclpy(self):
        for name in tuple(sys.modules):
            if name == "rclpy" or name.startswith("rclpy."):
                sys.modules.pop(name, None)

        bridge = self.main._build_navigation_bridge(SimpleNamespace(), "disabled")

        self.assertIsInstance(bridge, self.main._DisabledNavigationBridge)
        self.assertNotIn("rclpy", sys.modules)

    def test_disabled_start_is_noop_and_navigation_is_rejected(self):
        bridge = self.main._build_navigation_bridge(SimpleNamespace(), "disabled")

        async def exercise():
            self.assertIsNone(await bridge.start())
            self.assertFalse(await bridge.is_navigation_active())
            with self.assertRaisesRegex(RuntimeError, "NAVIGATION_DISABLED"):
                await bridge.send_goal(SimpleNamespace())

        asyncio.run(exercise())
        readiness = bridge.get_readiness()
        self.assertFalse(readiness.started)
        self.assertFalse(readiness.ntp_available)
        self.assertFalse(readiness.fw_available)

    def test_unknown_resolved_backend_fails_closed(self):
        settings = SimpleNamespace()
        with self.assertRaisesRegex(RuntimeError, "NAVIGATION_BACKEND_BUILD_FAILED:bogus"):
            self.main._build_navigation_bridge(settings, "bogus")

    def test_import_legacy_failure_never_falls_back_to_stub(self):
        import src.navigation as navigation_pkg

        original_getattr = navigation_pkg.__getattr__

        def failing_getattr(name):
            if name == "AsyncNav2Bridge":
                raise ImportError("simulated legacy import failure")
            return original_getattr(name)

        navigation_pkg.__getattr__ = failing_getattr
        try:
            settings = SimpleNamespace()
            with self.assertRaisesRegex(RuntimeError, "NAVIGATION_BACKEND_BUILD_FAILED:legacy"):
                self.main._build_navigation_bridge(settings, "legacy")
        finally:
            navigation_pkg.__getattr__ = original_getattr

    def test_import_direct_failure_never_falls_back_to_stub(self):
        import src.navigation as navigation_pkg

        original_getattr = navigation_pkg.__getattr__

        def failing_getattr(name):
            if name == "DirectNav2ActionBridge":
                raise ImportError("simulated direct import failure")
            return original_getattr(name)

        navigation_pkg.__getattr__ = failing_getattr
        try:
            settings = SimpleNamespace()
            with self.assertRaisesRegex(RuntimeError, "NAVIGATION_BACKEND_BUILD_FAILED:direct"):
                self.main._build_navigation_bridge(settings, "direct")
        finally:
            navigation_pkg.__getattr__ = original_getattr


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

@unittest.skipUnless(_PYDANTIC_SETTINGS_AVAILABLE, _SKIP_REASON)
class NavigationConfigValidationTests(unittest.TestCase):
    def test_negative_timeout_rejected(self):
        settings = Settings(NAVIGATION_SERVER_TIMEOUT_S=-1.0)
        with self.assertRaisesRegex(ValueError, "NAVIGATION_CONFIG_INVALID"):
            settings.validate_navigation_config()

    def test_zero_timeout_rejected(self):
        settings = Settings(NAVIGATION_RESULT_TIMEOUT_S=0.0)
        with self.assertRaisesRegex(ValueError, "NAVIGATION_CONFIG_INVALID"):
            settings.validate_navigation_config()

    def test_relative_action_name_rejected(self):
        settings = Settings(NAVIGATION_NTP_ACTION="navigate_to_pose")
        with self.assertRaisesRegex(ValueError, "NAVIGATION_CONFIG_INVALID"):
            settings.validate_navigation_config()

    def test_empty_action_name_rejected(self):
        settings = Settings(NAVIGATION_FW_ACTION="")
        with self.assertRaisesRegex(ValueError, "NAVIGATION_CONFIG_INVALID"):
            settings.validate_navigation_config()

    def test_relative_initial_pose_topic_rejected(self):
        settings = Settings(NAVIGATION_INITIAL_POSE_TOPIC="initialpose")
        with self.assertRaisesRegex(ValueError, "NAVIGATION_CONFIG_INVALID"):
            settings.validate_navigation_config()

    def test_empty_namespace_rejected(self):
        settings = Settings(NAVIGATION_NAMESPACE="")
        with self.assertRaisesRegex(ValueError, "NAVIGATION_CONFIG_INVALID"):
            settings.validate_navigation_config()

    def test_default_settings_pass_validation(self):
        Settings().validate_navigation_config()  # must not raise


# ---------------------------------------------------------------------------
# Fail-closed ordering: interlock before any hardware/ROS touch
# ---------------------------------------------------------------------------

class FailClosedOrderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.main, self._mocks = _fresh_import_main()
        try:
            from src.core.event_bus import OttoEventBus
            OttoEventBus.reset_for_testing()
        except Exception:
            pass

    def tearDown(self):
        try:
            from src.core.event_bus import OttoEventBus
            OttoEventBus.reset_for_testing()
        except Exception:
            pass
        _remove_interaction_dependency_mocks(self._mocks)
        _purge_app_modules()

    async def test_direct_real_latch_false_never_calls_hardware_adapter(self):
        app = _FakeApp()
        settings = _fake_settings(
            ROBOT_MODE="real",
            NAVIGATION_BACKEND="direct",
            NAVIGATION_DIRECT_REAL_ENABLED=False,
        )
        get_hardware_adapter_mock = MagicMock(side_effect=AssertionError("must not be called"))
        self.main.get_settings = lambda: settings
        self.main.get_hardware_adapter = get_hardware_adapter_mock

        with self.assertRaisesRegex(RuntimeError, "DIRECT_NAVIGATION_REAL_MODE_NOT_AUTHORIZED"):
            async with self.main.lifespan(app):
                pass

        get_hardware_adapter_mock.assert_not_called()
        self.assertEqual(app.state.navigation_backend_resolved, "direct")
        self.assertIsNotNone(app.state.navigation_startup_error)
        self.assertIn("DIRECT_NAVIGATION_REAL_MODE_NOT_AUTHORIZED", app.state.navigation_startup_error)


# ---------------------------------------------------------------------------
# Lifespan integration (direct backend, success / start failure / close failure)
# ---------------------------------------------------------------------------

class LifespanDirectBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.main, self._mocks = _fresh_import_main()
        try:
            from src.core.event_bus import OttoEventBus
            OttoEventBus.reset_for_testing()
        except Exception:
            pass

    def tearDown(self):
        try:
            from src.core.event_bus import OttoEventBus
            OttoEventBus.reset_for_testing()
        except Exception:
            pass
        _remove_interaction_dependency_mocks(self._mocks)
        _purge_app_modules()

    def _settings(self, **overrides) -> SimpleNamespace:
        base = dict(ROBOT_MODE="mock", NAVIGATION_BACKEND="direct")
        base.update(overrides)
        return _fake_settings(**base)

    async def test_success_path_starts_bridge_once_and_wires_same_instance(self):
        app = _FakeApp()
        fake_bridge = _FakeNavBridge()
        fake_hardware = _FakeHardware()

        self.main.get_settings = lambda: self._settings()
        self.main.get_hardware_adapter = lambda: fake_hardware
        self.main._build_navigation_bridge = lambda settings, backend: fake_bridge

        async with self.main.lifespan(app):
            self.assertIs(app.state.nav_bridge, fake_bridge)
            self.assertIs(app.state.orchestrator._nav_bridge, fake_bridge)
            self.assertEqual(app.state.navigation_backend_requested, "direct")
            self.assertEqual(app.state.navigation_backend_resolved, "direct")
            self.assertTrue(app.state.navigation_started)
            self.assertIsNone(app.state.navigation_startup_error)

        fake_bridge.start.assert_awaited_once()
        fake_bridge.close.assert_awaited_once()
        fake_hardware.initialize.assert_awaited_once()

    async def test_start_failure_fails_closed_no_orchestrator_no_fallback(self):
        app = _FakeApp()
        fake_bridge = _FakeNavBridge(start_exc=RuntimeError("boom"))
        fake_hardware = _FakeHardware()

        self.main.get_settings = lambda: self._settings()
        self.main.get_hardware_adapter = lambda: fake_hardware
        self.main._build_navigation_bridge = lambda settings, backend: fake_bridge

        with self.assertRaisesRegex(RuntimeError, "NAVIGATION_BACKEND_START_FAILED:direct:boom"):
            async with self.main.lifespan(app):
                pass

        self.assertFalse(hasattr(app.state, "orchestrator"))
        self.assertFalse(app.state.navigation_started)
        self.assertIsNotNone(app.state.navigation_startup_error)
        self.assertIn("NAVIGATION_BACKEND_START_FAILED", app.state.navigation_startup_error)
        # Hardware safety sequence still ran on the already-initialized hardware:
        fake_hardware.stop_motion.assert_awaited()
        fake_hardware.move.assert_awaited()
        # Partial bridge close was attempted even though start() failed:
        fake_bridge.close.assert_awaited_once()
        self.assertNotIsInstance(app.state.nav_bridge, self.main._MinimalNavStub)

    async def test_close_failure_does_not_block_zero_and_damp_and_is_observable(self):
        app = _FakeApp()
        fake_bridge = _FakeNavBridge(close_exc=RuntimeError("close boom"))
        fake_hardware = _FakeHardware()

        self.main.get_settings = lambda: self._settings()
        self.main.get_hardware_adapter = lambda: fake_hardware
        self.main._build_navigation_bridge = lambda settings, backend: fake_bridge

        async with self.main.lifespan(app):
            pass

        fake_hardware.stop_motion.assert_awaited()
        fake_hardware.move.assert_awaited()
        fake_bridge.close.assert_awaited_once()
        self.assertIsNotNone(app.state.navigation_shutdown_error)
        self.assertIn("NAVIGATION_BACKEND_CLOSE_FAILED:direct", app.state.navigation_shutdown_error)
        self.assertIn("close boom", app.state.navigation_shutdown_error)

    async def test_stub_backend_does_not_mark_navigation_started(self):
        app = _FakeApp()
        fake_hardware = _FakeHardware()

        self.main.get_settings = lambda: self._settings(NAVIGATION_BACKEND="stub")
        self.main.get_hardware_adapter = lambda: fake_hardware

        async with self.main.lifespan(app):
            self.assertEqual(app.state.navigation_backend_resolved, "stub")
            self.assertFalse(app.state.navigation_started)
            self.assertIsInstance(app.state.nav_bridge, self.main._MinimalNavStub)

    async def test_real_disabled_backend_initializes_hardware_but_not_navigation(self):
        app = _FakeApp()
        fake_hardware = _FakeHardware()

        self.main.get_settings = lambda: self._settings(
            ROBOT_MODE="real",
            NAVIGATION_BACKEND="disabled",
        )
        self.main.get_hardware_adapter = lambda: fake_hardware

        async with self.main.lifespan(app):
            self.assertEqual(app.state.navigation_backend_resolved, "disabled")
            self.assertFalse(app.state.navigation_started)
            self.assertIsInstance(app.state.nav_bridge, self.main._DisabledNavigationBridge)
            fake_hardware.initialize.assert_awaited_once()


# ---------------------------------------------------------------------------
# Readiness gating (api/router.py _resolve_readiness_errors)
# ---------------------------------------------------------------------------

class _FakeRequestApp:
    def __init__(self, state):
        self.state = state


class _FakeRequest:
    def __init__(self, state):
        self.app = _FakeRequestApp(state)


def _fake_orchestrator(*, state_id="idle", robot_mode="mock", hardware=None):
    return SimpleNamespace(state_id=state_id, _robot_mode=robot_mode, _hardware_api=hardware)


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._router_fakes = _install_router_fakes()
        # NOT "import api.router as router": api/__init__.py does
        # "from .router import router", which rebinds the *attribute*
        # api.router on the package object to the APIRouter instance,
        # shadowing the submodule. importlib.import_module reads
        # sys.modules['api.router'] directly, returning the real module.
        self.router = importlib.import_module("api.router")

    def tearDown(self):
        _remove_router_fakes(self._router_fakes)

    def _state(self, **overrides):
        state = _FakeState()
        state.nav_bridge = overrides.get("nav_bridge", _FakeNavBridge())
        state.navigation_backend_resolved = overrides.get("navigation_backend_resolved", "direct")
        state.navigation_started = overrides.get("navigation_started", True)
        state.navigation_stub_tours_allowed = overrides.get("navigation_stub_tours_allowed", False)
        return state

    async def test_nav_bridge_absent_blocks(self):
        state = self._state(nav_bridge=None, navigation_backend_resolved=None)
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertIn("navigation backend unavailable", errors)

    async def test_stub_without_allow_flag_blocks(self):
        state = self._state(navigation_backend_resolved="stub", navigation_started=False)
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertIn("navigation backend stub: autonomous tours disabled", errors)

    async def test_disabled_backend_blocks_with_status_only_reason(self):
        state = self._state(navigation_backend_resolved="disabled", navigation_started=False)
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertIn("navigation disabled: status-only real runtime", errors)

    async def test_stub_with_allow_flag_in_mock_permits(self):
        state = self._state(
            navigation_backend_resolved="stub",
            navigation_started=False,
            navigation_stub_tours_allowed=True,
        )
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertEqual(errors, [])

    async def test_direct_not_started_blocks(self):
        state = self._state(navigation_backend_resolved="direct", navigation_started=False)
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertIn("navigation backend not started", errors)

    async def test_direct_started_permits(self):
        state = self._state(navigation_backend_resolved="direct", navigation_started=True)
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertEqual(errors, [])

    async def test_remote_state_unknown_blocks(self):
        bridge = _FakeNavBridge(remote_state_unknown=True)
        state = self._state(nav_bridge=bridge, navigation_backend_resolved="direct", navigation_started=True)
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertIn("navigation remote state unknown", errors)

    async def test_get_status_failure_blocks(self):
        bridge = _FakeNavBridge()
        bridge.get_status = AsyncMock(side_effect=RuntimeError("boom"))
        state = self._state(nav_bridge=bridge, navigation_backend_resolved="direct", navigation_started=True)
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertTrue(any(e.startswith("navigation status unavailable:") for e in errors))

    async def test_non_idle_fsm_blocks(self):
        state = self._state()
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(
            request, _fake_orchestrator(state_id="navigating")
        )
        self.assertTrue(any("se requiere idle" in e for e in errors))

    async def test_missing_get_status_blocks_readiness(self):
        bridge = _FakeNavBridgeNoStatus()
        state = self._state(
            nav_bridge=bridge,
            navigation_backend_resolved="direct",
            navigation_started=True,
        )
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertIn("navigation status unavailable:missing", errors)

    async def test_noncallable_get_status_blocks_readiness(self):
        bridge = _FakeNavBridge()
        bridge.get_status = "not_a_callable"
        state = self._state(
            nav_bridge=bridge,
            navigation_backend_resolved="direct",
            navigation_started=True,
        )
        request = _FakeRequest(state)
        errors = await self.router._resolve_readiness_errors(request, _fake_orchestrator())
        self.assertIn("navigation status unavailable:missing", errors)


# ---------------------------------------------------------------------------
# StatusResponse navigation observability (api/router.py)
# ---------------------------------------------------------------------------

class StatusObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._router_fakes = _install_router_fakes()
        # NOT "import api.router as router": api/__init__.py does
        # "from .router import router", which rebinds the *attribute*
        # api.router on the package object to the APIRouter instance,
        # shadowing the submodule. importlib.import_module reads
        # sys.modules['api.router'] directly, returning the real module.
        self.router = importlib.import_module("api.router")

    def tearDown(self):
        _remove_router_fakes(self._router_fakes)

    async def test_resolves_requested_resolved_started_and_status_fields(self):
        state = _FakeState()
        state.navigation_backend_requested = "direct"
        state.navigation_backend_resolved = "direct"
        state.navigation_started = True
        state.nav_bridge = _FakeNavBridge(
            remote_state_unknown=True,
            action_name="/offline_nav/navigate_to_pose",
            goal_uuid="abc123",
        )
        request = _FakeRequest(state)

        observability = await self.router._resolve_navigation_observability(request)

        self.assertEqual(observability["navigation_backend_requested"], "direct")
        self.assertEqual(observability["navigation_backend_resolved"], "direct")
        self.assertTrue(observability["navigation_started"])
        self.assertTrue(observability["navigation_remote_state_unknown"])
        self.assertEqual(observability["navigation_action_name"], "/offline_nav/navigate_to_pose")
        self.assertEqual(observability["navigation_goal_uuid"], "abc123")

    async def test_get_status_failure_does_not_raise_and_uses_conservative_values(self):
        state = _FakeState()
        state.navigation_backend_requested = "direct"
        state.navigation_backend_resolved = "direct"
        state.navigation_started = True
        bridge = _FakeNavBridge()
        bridge.get_status = AsyncMock(side_effect=RuntimeError("boom"))
        state.nav_bridge = bridge
        request = _FakeRequest(state)

        observability = await self.router._resolve_navigation_observability(request)

        self.assertTrue(observability["navigation_remote_state_unknown"])
        self.assertIsNone(observability["navigation_action_name"])
        self.assertIsNone(observability["navigation_goal_uuid"])

    async def test_missing_state_fields_use_unknown_defaults(self):
        state = _FakeState()
        request = _FakeRequest(state)

        observability = await self.router._resolve_navigation_observability(request)

        self.assertEqual(observability["navigation_backend_requested"], "unknown")
        self.assertEqual(observability["navigation_backend_resolved"], "unknown")
        self.assertFalse(observability["navigation_started"])

    async def test_missing_get_status_marks_remote_state_unknown(self):
        state = _FakeState()
        state.navigation_backend_requested = "direct"
        state.navigation_backend_resolved = "direct"
        state.navigation_started = True
        state.nav_bridge = _FakeNavBridgeNoStatus()
        request = _FakeRequest(state)

        observability = await self.router._resolve_navigation_observability(request)

        self.assertTrue(observability["navigation_remote_state_unknown"])
        self.assertIsNone(observability["navigation_action_name"])
        self.assertIsNone(observability["navigation_goal_uuid"])


# ---------------------------------------------------------------------------
# Dependency-blocked import verification
# ---------------------------------------------------------------------------

class DependencyBlockedImportTests(unittest.TestCase):
    """main.py must be importable even when uvicorn/fastapi/pydantic_settings/
    statemachine/httpx are explicitly blocked in sys.modules."""

    def test_main_importable_with_blocked_critical_dependencies(self):
        script = textwrap.dedent(
            f"""\
            import sys
            sys.path.insert(0, {str(CODE_ROOT)!r})
            for _n in ('uvicorn', 'fastapi', 'pydantic_settings', 'statemachine', 'httpx'):
                sys.modules[_n] = None
            import types as _types
            for _n in ('pyttsx3', 'speech_recognition', 'aiohttp'):
                sys.modules[_n] = _types.ModuleType(_n)
            import main
            assert callable(getattr(main, '_resolve_navigation_backend', None)), \\
                '_resolve_navigation_backend not accessible'
            assert callable(getattr(main, '_check_direct_real_interlock', None)), \\
                '_check_direct_real_interlock not accessible'
            print('DEPENDENCY_BLOCKED_IMPORT=PASS')
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f"subprocess failed (exit {result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )
        self.assertIn("DEPENDENCY_BLOCKED_IMPORT=PASS", result.stdout)


@unittest.skipUnless(_PYDANTIC_SETTINGS_AVAILABLE, _SKIP_REASON)
class SettingsDefaultsParityTests(unittest.TestCase):
    """Fase 2H.2.2: pins _fake_settings() defaults against the real
    config.settings.Settings model. Without this, _fake_settings() can drift
    from Settings (as it previously did for ROBOT_MODE, NAVIGATION_NODE_NAME
    and every NAVIGATION_*/OLLAMA_*/UNITREE_FACTORY_TIMEOUT_S field) and
    every test built on the fake would keep passing while silently no longer
    representing production defaults."""

    _COMPARED_FIELDS = (
        "ROBOT_MODE",
        "NAVIGATION_BACKEND",
        "NAVIGATION_DIRECT_REAL_ENABLED",
        "NAVIGATION_ALLOW_STUB_TOURS",
        "NAVIGATION_NODE_NAME",
        "NAVIGATION_NAMESPACE",
        "NAVIGATION_NTP_ACTION",
        "NAVIGATION_FW_ACTION",
        "NAVIGATION_INITIAL_POSE_TOPIC",
        "NAVIGATION_SERVER_TIMEOUT_S",
        "NAVIGATION_GOAL_RESPONSE_TIMEOUT_S",
        "NAVIGATION_RESULT_TIMEOUT_S",
        "NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S",
        "NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S",
        "OLLAMA_MODEL",
        "OLLAMA_HOST",
        "UNITREE_FACTORY_BASE_URL",
        "UNITREE_FACTORY_TIMEOUT_S",
        "UNITREE_FACTORY_DIAGNOSTICS_ENABLED",
        "WEB_UI_ALLOWED_ORIGINS",
        "WEB_UI_PUBLIC_URL",
        "WEB_UI_ALLOW_MISSING_ORIGIN",
    )

    def test_fake_settings_defaults_match_real_settings_defaults(self):
        # Reads field defaults directly off the Settings model, never an
        # instantiated Settings() -- the real shell/.env environment on this
        # workstation legitimately overrides some fields (e.g. a system-wide
        # OLLAMA_HOST set by the local Ollama install), which would otherwise
        # produce a false mismatch unrelated to a real code-default drift.
        real_defaults = {
            name: field.default for name, field in Settings.model_fields.items()
        }
        fake = _fake_settings()
        mismatches = [
            f"{field}: fake={getattr(fake, field)!r} real_default={real_defaults[field]!r}"
            for field in self._COMPARED_FIELDS
            if getattr(fake, field) != real_defaults[field]
        ]
        self.assertEqual(mismatches, [], f"_fake_settings() drifted from Settings: {mismatches}")


# ---------------------------------------------------------------------------
# U2R2: identidad estable de EventType/OttoEventBus a traves de reimports
# ---------------------------------------------------------------------------

class FreshMainReimportIdentityTests(unittest.TestCase):
    """_fresh_import_main() purga y reimporta main.py repetidas veces; esta
    suite confirma que esas purgas/reimports NUNCA cambian la identidad de
    EventType/OttoEventBus, y que el singleton de OttoEventBus no acumula
    suscriptores entre reimports (lo cual indicaria una fuga de TourOrchestrator
    instances colgando del bus global)."""

    def tearDown(self):
        _remove_interaction_dependency_mocks(self._mocks)
        _purge_app_modules()

    def test_event_type_and_event_bus_identity_stable_across_three_reimports(self):
        from src.core.events import EventType as initial_event_type
        from src.core.event_bus import OttoEventBus as initial_event_bus

        initial_event_type_id = id(initial_event_type)
        initial_event_bus_id = id(initial_event_bus)

        observed_event_type_ids = []
        observed_event_bus_ids = []

        for _ in range(3):
            self.main, self._mocks = _fresh_import_main()
            from src.core.events import EventType as reimported_event_type
            from src.core.event_bus import OttoEventBus as reimported_event_bus

            observed_event_type_ids.append(id(reimported_event_type))
            observed_event_bus_ids.append(id(reimported_event_bus))
            _remove_interaction_dependency_mocks(self._mocks)

        self.assertTrue(
            all(eid == initial_event_type_id for eid in observed_event_type_ids),
            f"EventType cambio de identidad entre reimports: {observed_event_type_ids} "
            f"(inicial={initial_event_type_id})",
        )
        self.assertTrue(
            all(bid == initial_event_bus_id for bid in observed_event_bus_ids),
            f"OttoEventBus cambio de identidad entre reimports: {observed_event_bus_ids} "
            f"(inicial={initial_event_bus_id})",
        )

    def test_fresh_main_reimports_do_not_accumulate_subscribers_on_singleton(self):
        from src.core.event_bus import OttoEventBus
        from src.core.events import EventType

        OttoEventBus.reset_for_testing()
        bus = OttoEventBus.get_instance()
        baseline_subs = len(bus._subscribers.get(EventType.INTERACTION_STARTED, []))

        for _ in range(3):
            self.main, self._mocks = _fresh_import_main()
            _remove_interaction_dependency_mocks(self._mocks)

        from src.core.event_bus import OttoEventBus as bus_after
        from src.core.events import EventType as event_type_after

        bus_after_reimports = bus_after.get_instance()
        self.assertIs(bus_after_reimports, bus)
        final_subs = len(bus_after_reimports._subscribers.get(event_type_after.INTERACTION_STARTED, []))
        self.assertEqual(
            final_subs, baseline_subs,
            "El reimport repetido de main.py no debe acumular suscriptores en el "
            "singleton global de OttoEventBus (cada TourOrchestrator descartado entre "
            "reimports nunca se construyo con event_bus=OttoEventBus.get_instance(), "
            "por lo que esta cuenta debe permanecer estable)",
        )
        OttoEventBus.reset_for_testing()


if __name__ == "__main__":
    unittest.main()
