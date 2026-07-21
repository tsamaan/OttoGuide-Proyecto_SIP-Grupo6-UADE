"""Static AST-based import gate for the R2-P0 package and CLI.

Rejects rclpy/nav_msgs/geometry_msgs/tf2_ros/cyclonedds/unitree_sdk2py/
socket/requests/httpx and any use of subprocess for external operations, per
checkpoint section 27. subprocess is only permitted in test/build tooling
explicitly outside this pure package -- so this gate scans exactly the
package + CLI files, not the test suite itself.
"""
import ast
import unittest
from pathlib import Path

FORBIDDEN_MODULES = {
    "rclpy",
    "nav_msgs",
    "geometry_msgs",
    "tf2_ros",
    "cyclonedds",
    "unitree_sdk2py",
    "socket",
    "requests",
    "httpx",
    "subprocess",
}

_CODIGO_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_PATHS = [
    _CODIGO_ROOT / "src" / "navigation" / "odometry_evidence_r2",
    _CODIGO_ROOT / "tools" / "hil" / "offline_navigation" / "ingest_physical_evidence_r2.py",
]


def _iter_python_files():
    for path in _SCANNED_PATHS:
        if path.is_file():
            yield path
        elif path.is_dir():
            for py_file in sorted(path.glob("*.py")):
                yield py_file


def _imported_root_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module.split(".")[0]


class TestStaticImportGate(unittest.TestCase):
    def test_scanned_paths_exist(self):
        # Fail closed rather than silently scanning zero files if the
        # package/CLI ever move.
        for path in _SCANNED_PATHS:
            self.assertTrue(path.exists(), f"expected scan target missing: {path}")

    def test_no_forbidden_imports(self):
        violations = []
        for py_file in _iter_python_files():
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for module in _imported_root_modules(tree):
                if module in FORBIDDEN_MODULES:
                    violations.append(f"{py_file}: imports forbidden module {module!r}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_at_least_one_file_scanned(self):
        self.assertGreater(len(list(_iter_python_files())), 0)


if __name__ == "__main__":
    unittest.main()
