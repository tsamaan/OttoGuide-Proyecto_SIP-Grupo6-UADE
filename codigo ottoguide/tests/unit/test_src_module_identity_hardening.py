"""
@TASK: Regresion sistemica para TEST-INFRA-R1/R1A-SRC-MODULE-IDENTITY-HARDENING.
@INPUT: Los cuatro archivos primarios endurecidos (test_hardware_api.py,
        test_vision_processor.py, test_u2_qr_lifespan_wiring.py,
        test_navigation_runtime_selection.py) y el helper compartido
        tests/support/scoped_module_isolation.py.
@OUTPUT: Confirma, dentro del mismo proceso de pytest: (1) que ninguno de los
         cuatro archivos contiene un purge global de "src"/"src.*" a nivel de
         texto -- no solo de comportamiento -- para que una regresion futura
         falle inmediatamente sin depender del orden de coleccion; (2) que
         ModuleIsolationScope restaura exactamente los objetos originales,
         incluso tras una excepcion dentro del scope, o si open() mismo
         falla a mitad de camino; (3) que scopes anidados se rechazan
         explicitamente y el guard de hilo se libera correctamente incluso
         tras una falla; (4) que el conjunto EXACTO de nombres coincidentes
         se restaura -- incluyendo la eliminacion de cualquier modulo o
         atributo de paquete padre NUEVO introducido durante el scope, que
         no existia antes de abrirlo (TEST-INFRA-R1A defectos D1/D2); (5)
         que _fresh_import_main() en ambos archivos que la usan cierra el
         scope y libera el guard de hilo si el import falla (D3), sin
         degradar el fallo a skip/fallback; (6) que la identidad canonica de
         EventType/OttoEventBus permanece estable a traves de un ciclo real
         de apertura/mutacion/cierre DENTRO DEL MISMO PROCESO (ver
         ScopeIdentityRestorationTests -- reemplaza el test subprocess
         original, que media id() en el proceso padre antes y despues de
         ejecutar un hijo, lo cual no puede fallar nunca por construccion;
         ver DEFECT_D4_SUBPROCESS_PROOF_ANALYSIS.md del run de
         TEST-INFRA-R1A para el analisis completo).
@CONTEXT: Ver ROOT_CAUSE_AND_RISK.md (R1) e IMPLEMENTATION_DECISION.md (R1A)
          de los runs de este hardening para el analisis completo. Este
          archivo NO duplica las corridas de Orden A/B/C (eso se ejecuta a
          nivel de suite via pytest, no re-implementado aqui).
"""
from __future__ import annotations

import re
import subprocess
import sys
import types
import unittest
from pathlib import Path

from tests.support.core_module_identity import ensure_core_event_modules
from tests.support.scoped_module_isolation import ModuleIsolationScope, fresh_reimport_scope
import tests.support.scoped_module_isolation as _smi_module

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

    def test_removes_new_matching_module_absent_before_scope(self):
        """TEST-INFRA-R1A D1: a module matching the scope's prefixes that did
        NOT exist before open() (e.g. a fresh submodule loaded by a reimport
        inside the scope) must be removed on close(), not left behind."""
        name = "sentinel_r1a_regression_d1"
        child = f"{name}.child"
        self.assertNotIn(name, sys.modules)
        self.assertNotIn(child, sys.modules)

        scope = ModuleIsolationScope(frozenset({name, f"{name}."}))
        scope.open()
        try:
            sys.modules[name] = types.ModuleType(name)
            sys.modules[child] = types.ModuleType(child)
            setattr(sys.modules[name], "child", sys.modules[child])
        finally:
            scope.close()

        self.assertNotIn(name, sys.modules)
        self.assertNotIn(child, sys.modules)

    def test_removes_new_parent_attribute_absent_before_scope(self):
        """TEST-INFRA-R1A D2: a parent-package attribute pointing at a
        submodule that did not exist before open() must be removed on
        close(), not left dangling on the parent object."""
        name = "sentinel_r1a_regression_d2"
        child = f"{name}.child"
        parent = types.ModuleType(name)
        sys.modules[name] = parent
        try:
            self.assertFalse(hasattr(parent, "child"))

            scope = ModuleIsolationScope(frozenset({name, f"{name}."}))
            scope.open()
            try:
                new_child = types.ModuleType(child)
                sys.modules[child] = new_child
                setattr(parent, "child", new_child)
            finally:
                scope.close()

            self.assertFalse(hasattr(parent, "child"))
        finally:
            sys.modules.pop(name, None)
            sys.modules.pop(child, None)

    def test_restores_exact_matching_key_set(self):
        """The set of sys.modules keys matching the scope's prefixes after
        close() must equal the set that matched before open() -- not merely
        a superset or a best-effort restoration of captured names."""
        base = "sentinel_r1a_regression_keyset"
        pre_existing = f"{base}.pre_existing"
        sys.modules[base] = types.ModuleType(base)
        sys.modules[pre_existing] = types.ModuleType(pre_existing)
        try:
            prefixes = frozenset({base, f"{base}."})

            def matching_names():
                return {n for n in sys.modules if n == base or n.startswith(f"{base}.")}

            before = matching_names()

            scope = ModuleIsolationScope(prefixes)
            scope.open()
            try:
                # Simulate a fresh reimport that both recreates a
                # pre-existing name AND introduces a brand-new one.
                sys.modules[pre_existing] = types.ModuleType(pre_existing)
                sys.modules[f"{base}.new_one"] = types.ModuleType(f"{base}.new_one")
            finally:
                scope.close()

            after = matching_names()
            self.assertEqual(after, before)
        finally:
            sys.modules.pop(base, None)
            sys.modules.pop(pre_existing, None)
            sys.modules.pop(f"{base}.new_one", None)

    def test_manual_scope_failure_releases_thread_guard(self):
        """TEST-INFRA-R1A D3: if open() itself fails partway through (e.g. an
        internal step raises), the thread guard must be released and
        _is_open must remain False, so a subsequent scope can still open."""
        original_matches = _smi_module._matches
        call_count = {"n": 0}

        def _flaky_matches(name, prefixes):
            call_count["n"] += 1
            if call_count["n"] > 1:
                raise RuntimeError("simulated_failure_mid_open")
            return original_matches(name, prefixes)

        name = "sentinel_r1a_regression_d3_manual"
        sys.modules[name] = types.ModuleType(name)
        _smi_module._matches = _flaky_matches
        scope = ModuleIsolationScope(frozenset({name}))
        try:
            with self.assertRaises(RuntimeError):
                scope.open()
        finally:
            _smi_module._matches = original_matches

        self.assertFalse(getattr(_smi_module._active, "engaged", False))
        self.assertFalse(scope._is_open)
        self.assertIn(name, sys.modules)
        sys.modules.pop(name, None)

        # A follow-up scope must be able to open cleanly right after.
        followup = ModuleIsolationScope(frozenset({"sentinel_r1a_regression_d3_followup"}))
        followup.open()
        followup.close()


class FreshImportMainRollbackTests(unittest.TestCase):
    """TEST-INFRA-R1A R3: _fresh_import_main() in both files that use
    ModuleIsolationScope must close the scope and release the thread guard
    if the mock-install step or `import main` itself fails, instead of
    leaving the guard engaged for the rest of the pytest process. Uses a
    forced, deterministic monkeypatch -- never a real missing dependency or
    network failure -- run in an isolated subprocess so a successful
    reproduction never corrupts this test process's own sys.modules/thread
    guard state."""

    _CODE_ROOT = _TESTS_ROOT.parent

    def _run(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(self._CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_fresh_import_main_failure_closes_scope_navigation(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.unit.test_navigation_runtime_selection as mod
import tests.support.scoped_module_isolation as smi_module

def _raising_install(*a, **kw):
    raise RuntimeError("simulated_forced_failure_after_scope_open")

mod._install_interaction_dependency_mocks = _raising_install

raised = False
try:
    mod._fresh_import_main()
except RuntimeError:
    raised = True

assert raised, "expected _fresh_import_main() to propagate the original exception"
assert not getattr(smi_module._active, "engaged", False), "thread guard left engaged"
assert mod._module_isolation_scope is None, "global scope reference not cleared"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = self._run(script)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

    def test_fresh_import_main_failure_closes_scope_qr(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.integration.test_u2_qr_lifespan_wiring as mod
import tests.support.scoped_module_isolation as smi_module

import builtins
real_import = builtins.__import__

def _raising_import(name, *a, **kw):
    if name == "main":
        raise RuntimeError("simulated_forced_import_failure")
    return real_import(name, *a, **kw)

builtins.__import__ = _raising_import
raised = False
try:
    mod._fresh_import_main()
except RuntimeError:
    raised = True
finally:
    builtins.__import__ = real_import

assert raised, "expected _fresh_import_main() to propagate the original exception"
assert not getattr(smi_module._active, "engaged", False), "thread guard left engaged"
assert mod._module_isolation_scope is None, "global scope reference not cleared"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = self._run(script)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

    def test_followup_scope_can_open_after_failure(self):
        """After a forced _fresh_import_main() failure, a genuine follow-up
        fresh import must succeed cleanly -- the thread guard/global scope
        cleanup in the except-block must not itself leave residue."""
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.integration.test_u2_qr_lifespan_wiring as mod

import builtins
real_import = builtins.__import__

def _raising_import(name, *a, **kw):
    if name == "main":
        raise RuntimeError("simulated_forced_import_failure")
    return real_import(name, *a, **kw)

builtins.__import__ = _raising_import
try:
    mod._fresh_import_main()
except RuntimeError:
    pass
finally:
    builtins.__import__ = real_import

# Genuine follow-up import after the failure must succeed with no lingering
# thread-guard/global-scope state from the failed attempt.
main_module = mod._fresh_import_main()
assert main_module is not None
mod._purge_app_modules()
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = self._run(script)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )


class ScopeIdentityRestorationTests(unittest.TestCase):
    """TEST-INFRA-R1A R4: same-process replacement for the removed
    subprocess-based "identity" test (see
    DEFECT_D4_SUBPROCESS_PROOF_ANALYSIS.md -- measuring id() in a parent
    process before/after running code in a child subprocess can never fail,
    since the child cannot touch the parent's objects). This test performs
    the mutation and the assertion in the SAME process, so a real
    restoration regression can actually be observed."""

    def test_scope_restores_real_module_objects_across_fresh_import(self):
        before = ensure_core_event_modules()
        before_events_module = sys.modules["src.core.events"]
        before_event_bus_module = sys.modules["src.core.event_bus"]
        before_event_type = before.EventType
        before_otto_event_bus = before.OttoEventBus

        from tests.support.core_module_identity import PRESERVED_CORE_IDENTITY_MODULES

        nav_models_name = "src.navigation.models"
        before_nav_models_module = sys.modules.get(nav_models_name)

        # Exercise the exact prefixes _fresh_import_main() uses, but exclude
        # the canonical identity modules the same way the real callers do.
        scope = ModuleIsolationScope(
            frozenset({"src", "src."}), preserve=PRESERVED_CORE_IDENTITY_MODULES
        )
        scope.open()
        try:
            # Simulate what a fresh `import main` does to a non-preserved
            # src.* module: replace it with a brand-new object under the
            # same name.
            self.assertNotIn(nav_models_name, sys.modules)  # removed by scope.open()
            fake_replacement = types.ModuleType(nav_models_name)
            sys.modules[nav_models_name] = fake_replacement
        finally:
            scope.close()

        after_events_module = sys.modules["src.core.events"]
        after_event_bus_module = sys.modules["src.core.event_bus"]
        after = ensure_core_event_modules()

        self.assertIs(after_events_module, before_events_module)
        self.assertIs(after_event_bus_module, before_event_bus_module)
        self.assertIs(after.EventType, before_event_type)
        self.assertIs(after.OttoEventBus, before_otto_event_bus)

        # The fake replacement introduced inside the scope must be gone --
        # restored to the exact original object, never left as the fake.
        self.assertIs(sys.modules.get(nav_models_name), before_nav_models_module)
        self.assertIsNot(sys.modules.get(nav_models_name), fake_replacement)


class SubprocessSmokeTests(unittest.TestCase):
    """Smoke test only: confirms the four primary hardened files' own test
    suites pass when collected and run in a genuinely fresh interpreter.
    This does NOT and cannot validate module-identity restoration across
    the parent/child process boundary -- see
    DEFECT_D4_SUBPROCESS_PROOF_ANALYSIS.md. Retained because running these
    files in isolation is still useful signal for unrelated regressions
    (e.g. an accidental real ROS/hardware import)."""

    def test_target_files_pass_in_isolated_subprocess(self):
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


if __name__ == "__main__":
    unittest.main()
