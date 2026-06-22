#!/usr/bin/env python3
"""Pure unittest suite for the Fase 2H.0 navigation/hardware contract reconciliation.

Runs without ROS and without the broader src.interaction dependency chain
(aiohttp, pyttsx3, speech_recognition): source-level checks use ast inspection
instead of importing src.core/src.interaction, since those packages have a
pre-existing, unrelated dependency gap on this workstation (see
ARCHITECTURE_RECONCILIATION_2H0_REPORT.md, "Limitaciones").
"""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"

MODELS_FILE = CODE_ROOT / "src" / "navigation" / "models.py"
PORT_FILE = CODE_ROOT / "src" / "navigation" / "port.py"
NAV_INIT_FILE = CODE_ROOT / "src" / "navigation" / "__init__.py"
NAV2_BRIDGE_FILE = CODE_ROOT / "src" / "navigation" / "nav2_bridge.py"
TOUR_ORCHESTRATOR_FILE = CODE_ROOT / "src" / "core" / "tour_orchestrator.py"
MAIN_FILE = CODE_ROOT / "main.py"
SETTINGS_FILE = CODE_ROOT / "config" / "settings.py"
MOCK_NAV2_BRIDGE_FILE = CODE_ROOT / "tests" / "mocks" / "mock_nav2_bridge.py"
OFFLINE_LAUNCH_FILE = CODE_ROOT / "launch" / "offline_nav_sandbox.launch.py"
OFFLINE_PARAMS_FILE = CODE_ROOT / "config" / "navigation" / "nav2_offline_sandbox_params.yaml"

if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _async_method_names(tree: ast.Module, class_name: str) -> set[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name
                for item in node.body
                if isinstance(item, ast.AsyncFunctionDef)
            }
    raise AssertionError(f"class {class_name!r} not found")


NAVIGATION_PORT_METHODS = {
    "start",
    "close",
    "navigate_to_waypoints",
    "send_goal",
    "cancel_navigation",
    "inject_absolute_pose",
    "is_navigation_active",
    "get_status",
    "get_last_result",
}


class PureModelsAndPortImportTests(unittest.TestCase):
    """14.1: models.py and port.py import without ROS."""

    def test_models_module_has_no_ros_imports(self):
        modules = _imported_modules(_parse(MODELS_FILE))
        for forbidden in ("rclpy", "cv2", "nav2_simple_commander"):
            self.assertNotIn(forbidden, modules)

    def test_port_module_has_no_ros_imports(self):
        modules = _imported_modules(_parse(PORT_FILE))
        for forbidden in ("rclpy", "cv2", "nav2_simple_commander"):
            self.assertNotIn(forbidden, modules)

    def test_models_module_actually_imports_at_runtime_in_clean_subprocess(self):
        # A fresh subprocess is the only way to make this assertion meaningful:
        # within the shared test-session process, any earlier test that legitimately
        # imports nav2_bridge (e.g. ModelCompatibilityTests, for the identity checks)
        # leaves the real cv2 C extension resident in sys.modules for the rest of the
        # process -- that is expected and is not a defect in models.py itself.
        code = (
            "import sys; "
            "import src.navigation.models as models; "
            "assert hasattr(models, 'NavWaypoint'); "
            "assert hasattr(models, 'NavigationStatus'); "
            "forbidden = [m for m in ('rclpy', 'cv2', 'nav2_simple_commander') if m in sys.modules]; "
            "assert not forbidden, forbidden; "
            "print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)

    def test_port_module_actually_imports_at_runtime_in_clean_subprocess(self):
        code = (
            "import sys; "
            "import src.navigation.port as port; "
            "assert hasattr(port, 'NavigationPort'); "
            "forbidden = [m for m in ('rclpy', 'cv2', 'nav2_simple_commander') if m in sys.modules]; "
            "assert not forbidden, forbidden; "
            "print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)


_ROS_MOCK_MODULE_NAMES = (
    "rclpy",
    "rclpy.executors",
    "rclpy.node",
    "geometry_msgs",
    "geometry_msgs.msg",
    "nav2_simple_commander",
    "nav2_simple_commander.robot_navigator",
)


class ModelCompatibilityTests(unittest.TestCase):
    """14.2: NavWaypoint/NavigationStatus resolve to the same class regardless of import path.

    Installs fake rclpy/geometry_msgs/nav2_simple_commander modules to let the legacy
    nav2_bridge import chain resolve without real ROS 2. Must remove them in tearDown:
    leaving them in sys.modules would make later tests in the same pytest session
    (e.g. test_offline_navigation_sandbox_isolation.py's `import rclpy` availability
    probes) wrongly believe ROS 2 is installed.
    """

    def setUp(self):
        self._preexisting_ros_mocks = {
            name: sys.modules[name] for name in _ROS_MOCK_MODULE_NAMES if name in sys.modules
        }
        for mod in list(sys.modules):
            if mod == "src" or mod.startswith("src."):
                del sys.modules[mod]
        from tests.mocks.mock_ros2 import install_mocks  # noqa: PLC0415

        install_mocks(sys.modules)

    def tearDown(self):
        for name in _ROS_MOCK_MODULE_NAMES:
            sys.modules.pop(name, None)
        sys.modules.update(self._preexisting_ros_mocks)
        for mod in list(sys.modules):
            if mod == "src" or mod.startswith("src."):
                del sys.modules[mod]

    def test_navwaypoint_identity_across_import_paths(self):
        from src.navigation import NavWaypoint  # noqa: PLC0415
        from src.navigation.models import NavWaypoint as ModelNavWaypoint  # noqa: PLC0415
        from src.navigation.nav2_bridge import NavWaypoint as LegacyNavWaypoint  # noqa: PLC0415

        self.assertIs(NavWaypoint, ModelNavWaypoint)
        self.assertIs(ModelNavWaypoint, LegacyNavWaypoint)

    def test_navigationstatus_identity_across_import_paths(self):
        from src.navigation import NavigationStatus  # noqa: PLC0415
        from src.navigation.models import NavigationStatus as ModelNavigationStatus  # noqa: PLC0415
        from src.navigation.nav2_bridge import NavigationStatus as LegacyNavigationStatus  # noqa: PLC0415

        self.assertIs(NavigationStatus, ModelNavigationStatus)
        self.assertIs(ModelNavigationStatus, LegacyNavigationStatus)

    def test_navigation_port_exported_from_package(self):
        from src.navigation import NavigationPort  # noqa: PLC0415
        from src.navigation.port import NavigationPort as DirectNavigationPort  # noqa: PLC0415

        self.assertIs(NavigationPort, DirectNavigationPort)


class TourOrchestratorContractTests(unittest.TestCase):
    """14.3: tour_orchestrator.py depends on canonical contracts, not legacy implementations."""

    def setUp(self):
        self.tree = _parse(TOUR_ORCHESTRATOR_FILE)
        self.imports = _imported_modules(self.tree)

    def test_imports_hardware_interface(self):
        self.assertIn("hardware.interface", self.imports)

    def test_imports_navigation_port(self):
        self.assertIn("src.navigation.port", self.imports)

    def test_does_not_import_src_hardware(self):
        self.assertFalse(any(m == "src.hardware" or m.startswith("src.hardware.") for m in self.imports))

    def test_does_not_import_nav2_bridge_module(self):
        self.assertFalse(any("nav2_bridge" in m for m in self.imports))

    def test_constructor_type_hints_use_canonical_contracts(self):
        source = TOUR_ORCHESTRATOR_FILE.read_text(encoding="utf-8")
        self.assertIn("hardware_api: RobotHardwareInterface", source)
        self.assertIn("nav_bridge: NavigationPort", source)
        self.assertNotIn("hardware_api: RobotHardwareAPI", source)
        self.assertNotIn("nav_bridge: AsyncNav2Bridge", source)


class CanonicalRuntimeTests(unittest.TestCase):
    """14.4: main.py and config/settings.py wire the canonical hardware/navigation stack."""

    def test_main_imports_robot_hardware_interface(self):
        imports = _imported_modules(_parse(MAIN_FILE))
        self.assertIn("hardware.interface", imports)

    def test_main_does_not_import_src_hardware(self):
        imports = _imported_modules(_parse(MAIN_FILE))
        self.assertFalse(any(m == "src.hardware" or m.startswith("src.hardware.") for m in imports))

    def test_settings_factory_uses_canonical_adapters(self):
        source = SETTINGS_FILE.read_text(encoding="utf-8")
        self.assertIn("from hardware.real_adapter import UnitreeG1Adapter", source)
        self.assertIn("from hardware.sim_adapter import UnitreeG1SimAdapter", source)
        self.assertIn("from hardware.mock_adapter import MockHardwareAPI", source)
        self.assertNotIn("src.hardware", source)


class LegacyQuarantineTests(unittest.TestCase):
    """14.5: BasicNavigator/cmd_vel_nav legacy symbols stay confined to legacy files."""

    FORBIDDEN_SYMBOLS = ("BasicNavigator", "/cmd_vel_nav", "CMD_VEL_FILTERED_TOPIC")

    CANONICAL_FILES = (
        MAIN_FILE,
        TOUR_ORCHESTRATOR_FILE,
        MODELS_FILE,
        PORT_FILE,
        CODE_ROOT / "config" / "settings.py",
    )

    def test_forbidden_symbols_absent_from_canonical_files(self):
        for path in self.CANONICAL_FILES:
            source = path.read_text(encoding="utf-8")
            for symbol in self.FORBIDDEN_SYMBOLS:
                self.assertNotIn(
                    symbol,
                    source,
                    msg=f"{symbol!r} must not appear in canonical file {path}",
                )

    def test_canonical_hardware_directory_has_no_forbidden_symbols(self):
        hardware_dir = CODE_ROOT / "hardware"
        for path in hardware_dir.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for symbol in self.FORBIDDEN_SYMBOLS:
                self.assertNotIn(symbol, source, msg=f"{symbol!r} found in {path}")

    def test_basic_navigator_still_confined_to_legacy_bridge(self):
        source = NAV2_BRIDGE_FILE.read_text(encoding="utf-8")
        self.assertIn("BasicNavigator", source)


class DuplicateHardwareLayerTests(unittest.TestCase):
    """14.6: two hardware layers exist, but only hardware/ is reachable from canonical runtime."""

    def test_canonical_hardware_package_exists(self):
        self.assertTrue((CODE_ROOT / "hardware" / "interface.py").is_file())

    def test_legacy_hardware_package_still_exists(self):
        self.assertTrue((CODE_ROOT / "src" / "hardware" / "interface.py").is_file())

    def test_main_does_not_import_legacy_hardware(self):
        imports = _imported_modules(_parse(MAIN_FILE))
        self.assertFalse(any(m.startswith("src.hardware") for m in imports))

    def test_tour_orchestrator_does_not_import_legacy_hardware(self):
        imports = _imported_modules(_parse(TOUR_ORCHESTRATOR_FILE))
        self.assertFalse(any(m.startswith("src.hardware") for m in imports))


class StructuralConformanceTests(unittest.TestCase):
    """14.7: _MinimalNavStub, MockNav2Bridge and AsyncNav2Bridge expose the NavigationPort contract.

    Uses ast inspection (not instantiation) for AsyncNav2Bridge and _MinimalNavStub to avoid
    creating ROS 2 threads/resources, per the section 14.7 instruction.
    """

    def test_minimal_nav_stub_has_all_navigation_port_methods(self):
        methods = _async_method_names(_parse(MAIN_FILE), "_MinimalNavStub")
        missing = NAVIGATION_PORT_METHODS - methods
        self.assertEqual(missing, set(), f"missing methods on _MinimalNavStub: {missing}")

    def test_async_nav2_bridge_has_all_navigation_port_methods(self):
        methods = _async_method_names(_parse(NAV2_BRIDGE_FILE), "AsyncNav2Bridge")
        missing = NAVIGATION_PORT_METHODS - methods
        self.assertEqual(missing, set(), f"missing methods on AsyncNav2Bridge: {missing}")

    def test_direct_nav2_action_bridge_has_all_navigation_port_methods(self):
        methods = _async_method_names(_parse(CODE_ROOT / "src" / "navigation" / "direct_nav2_action_bridge.py"), "DirectNav2ActionBridge")
        missing = NAVIGATION_PORT_METHODS - methods
        self.assertEqual(missing, set(), f"missing methods on DirectNav2ActionBridge: {missing}")

    def test_mock_nav2_bridge_conforms_via_isinstance(self):
        for mod in list(sys.modules):
            if mod == "src" or mod.startswith("src."):
                del sys.modules[mod]
        from tests.mocks.mock_nav2_bridge import MockNav2Bridge  # noqa: PLC0415
        from src.navigation.port import NavigationPort  # noqa: PLC0415

        instance = MockNav2Bridge()
        self.assertIsInstance(instance, NavigationPort)


class NoNavigationBehaviorChangeTests(unittest.TestCase):
    """14.8: the offline sandbox launch/params were not touched in this phase."""

    def test_offline_launch_file_unchanged_markers_present(self):
        source = OFFLINE_LAUNCH_FILE.read_text(encoding="utf-8")
        self.assertIn("waypoint_follower_node", source)
        self.assertIn("lifecycle_manager_waypoint_follower_node", source)

    def test_offline_params_file_unchanged_markers_present(self):
        source = OFFLINE_PARAMS_FILE.read_text(encoding="utf-8")
        self.assertIn("waypoint_follower:", source)
        self.assertIn("wait_at_waypoint", source)


if __name__ == "__main__":
    unittest.main()
