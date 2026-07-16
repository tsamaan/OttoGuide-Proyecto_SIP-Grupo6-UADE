"""
@TASK: Regresion sistemica para TEST-INFRA-R1-SRC-MODULE-IDENTITY-HARDENING.
@INPUT: Los cuatro archivos primarios endurecidos (test_hardware_api.py,
        test_vision_processor.py, test_u2_qr_lifespan_wiring.py,
        test_navigation_runtime_selection.py) y el helper compartido
        tests/support/scoped_module_isolation.py.
@OUTPUT: Confirma, dentro del mismo proceso de pytest: (1) que ninguno de los
         cuatro archivos contiene un purge global de "src"/"src.*" a nivel de
         texto -- no solo de comportamiento -- para que una regresion futura
         falle inmediatamente sin depender del orden de coleccion; (2) que
         ModuleIsolationScope restaura exactamente los objetos originales,
         incluso tras una excepcion dentro del scope; (3) que scopes anidados
         se rechazan explicitamente; (4) que la identidad canonica de
         EventType/OttoEventBus permanece estable antes y despues de ejecutar
         los cuatro archivos objetivo.
@CONTEXT: Ver ROOT_CAUSE_AND_RISK.md del run de este hardening para el
          analisis completo. Este archivo NO duplica las corridas de Orden
          A/B/C (eso se ejecuta a nivel de suite via pytest, no re-
          implementado aqui).
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from tests.support.core_module_identity import ensure_core_event_modules
from tests.support.scoped_module_isolation import ModuleIsolationScope, fresh_reimport_scope

_TESTS_ROOT = Path(__file__).resolve().parents[1]

_PRIMARY_FILES = (
    _TESTS_ROOT / "integration" / "test_hardware_api.py",
    _TESTS_ROOT / "integration" / "test_vision_processor.py",
    _TESTS_ROOT / "integration" / "test_u2_qr_lifespan_wiring.py",
    _TESTS_ROOT / "unit" / "test_navigation_runtime_selection.py",
)

# Matches the exact forbidden shape: a loop over sys.modules that deletes any
# entry whose name is "src" or starts with "src." -- regardless of minor
# textual variations (comparison order, list()/tuple() wrapper, quote style).
_GLOBAL_SRC_PURGE_PATTERN = re.compile(
    r"""
    for\s+\w+\s+in\s+(?:list|tuple)?\(?\s*sys\.modules\s*\)?\s*:      # for X in (list(sys.modules)):
    .*?                                                               # anything (e.g. an `if`) ...
    ==\s*["']src["']                                                 # ... == "src"
    .*?
    startswith\(\s*["']src\.["']\s*\)                                # startswith("src.")
    """,
    re.VERBOSE | re.DOTALL,
)


class StaticNoGlobalSrcPurgeTests(unittest.TestCase):
    """Text-level guard: fails immediately on a regression, without depending
    on collection order to observe a broken identity at runtime."""

    def test_no_primary_file_contains_a_global_src_purge_loop(self):
        offenders = []
        for path in _PRIMARY_FILES:
            text = path.read_text(encoding="utf-8")
            if _GLOBAL_SRC_PURGE_PATTERN.search(text):
                offenders.append(str(path))
        self.assertEqual(
            offenders,
            [],
            f"Global src.* purge pattern reintroduced in: {offenders}",
        )

    def test_no_primary_file_purges_src_at_collection_time(self):
        """Collection-time = module top-level code (not inside a def/class).
        Detects an unconditional 'del sys.modules[...]' or
        'sys.modules.pop(...)' whose enclosing indentation is zero (i.e. not
        nested inside any function/class body)."""
        offenders = []
        for path in _PRIMARY_FILES:
            lines = path.read_text(encoding="utf-8").splitlines()
            in_def_or_class = False
            def_indent = None
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip(" "))
                if in_def_or_class and def_indent is not None and indent <= def_indent:
                    in_def_or_class = False
                if stripped.startswith("def ") or stripped.startswith("class "):
                    in_def_or_class = True
                    def_indent = indent
                    continue
                if in_def_or_class:
                    continue
                if "del sys.modules[" in stripped or "sys.modules.pop(" in stripped:
                    offenders.append(f"{path}: {stripped!r}")
        self.assertEqual(
            offenders,
            [],
            f"Collection-time (module top-level) sys.modules mutation found: {offenders}",
        )


class ModuleIsolationScopeTests(unittest.TestCase):
    """Behavioral guard for the shared helper itself."""

    def test_restores_exact_original_module_object_after_normal_exit(self):
        sentinel_name = "tests._scoped_isolation_probe_sentinel"
        import types

        original = types.ModuleType(sentinel_name)
        sys.modules[sentinel_name] = original
        try:
            with fresh_reimport_scope(frozenset({sentinel_name})):
                self.assertNotIn(sentinel_name, sys.modules)
                sys.modules[sentinel_name] = types.ModuleType(sentinel_name)
            self.assertIs(sys.modules[sentinel_name], original)
        finally:
            sys.modules.pop(sentinel_name, None)

    def test_restores_exact_original_module_object_after_exception(self):
        sentinel_name = "tests._scoped_isolation_probe_sentinel_exc"
        import types

        original = types.ModuleType(sentinel_name)
        sys.modules[sentinel_name] = original
        try:
            with self.assertRaises(ValueError):
                with fresh_reimport_scope(frozenset({sentinel_name})):
                    self.assertNotIn(sentinel_name, sys.modules)
                    raise ValueError("boom")
            self.assertIs(sys.modules[sentinel_name], original)
        finally:
            sys.modules.pop(sentinel_name, None)

    def test_preserved_names_are_never_removed(self):
        sentinel_name = "tests._scoped_isolation_probe_preserved"
        import types

        original = types.ModuleType(sentinel_name)
        sys.modules[sentinel_name] = original
        try:
            with fresh_reimport_scope(
                frozenset({sentinel_name}), preserve=frozenset({sentinel_name})
            ):
                self.assertIs(sys.modules[sentinel_name], original)
        finally:
            sys.modules.pop(sentinel_name, None)

    def test_nested_scopes_are_rejected(self):
        scope_outer = ModuleIsolationScope(frozenset({"tests._nonexistent_probe_name"}))
        scope_outer.open()
        try:
            scope_inner = ModuleIsolationScope(frozenset({"tests._nonexistent_probe_name_2"}))
            with self.assertRaises(RuntimeError):
                scope_inner.open()
        finally:
            scope_outer.close()


class EventIdentityStableAroundPrimaryFilesTests(unittest.TestCase):
    """Confirms that running the four hardened files does not disturb the
    canonical EventType/OttoEventBus identity relied on by the rest of the
    process (Regla 4)."""

    def test_event_identity_unchanged_by_hardened_files_execution(self):
        before = ensure_core_event_modules()
        before_event_type_id = id(before.EventType)
        before_event_bus_id = id(before.OttoEventBus)

        import subprocess

        code_root = _TESTS_ROOT.parent
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/integration/test_hardware_api.py",
                "tests/integration/test_vision_processor.py",
                "tests/unit/test_navigation_runtime_selection.py",
                "tests/integration/test_u2_qr_lifespan_wiring.py",
            ],
            cwd=str(code_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"Primary hardened files failed in isolated subprocess:\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

        after = ensure_core_event_modules()
        self.assertEqual(id(after.EventType), before_event_type_id)
        self.assertEqual(id(after.OttoEventBus), before_event_bus_id)


if __name__ == "__main__":
    unittest.main()
