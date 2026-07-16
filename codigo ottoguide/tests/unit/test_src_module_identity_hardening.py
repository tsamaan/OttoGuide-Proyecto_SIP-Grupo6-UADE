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


class ParentAttributeRestorationTests(unittest.TestCase):
    """TEST-INFRA-R1B: defects D5/D6 -- ModuleIsolationScope must restore
    'managed' parent attributes (ModuleType values whose __name__ falls
    within the scope's namespace) captured at open()-time directly, without
    ever re-deriving what to restore from a sys.modules diff at close()-time.
    Covers both a managed attribute that never had a corresponding
    sys.modules entry (D5) and one whose sys.modules entry was removed
    before close() ran (D6)."""

    def test_removes_attr_only_managed_child_without_sys_modules_entry(self):
        name = "sentinel_r1b_regression_d5"
        parent = types.ModuleType(name)
        sys.modules[name] = parent
        try:
            self.assertFalse(hasattr(parent, "child"))

            scope = ModuleIsolationScope(frozenset({name, f"{name}."}))
            scope.open()
            try:
                # Assign the attribute WITHOUT ever registering
                # "sentinel_r1b_regression_d5.child" in sys.modules.
                setattr(parent, "child", types.ModuleType(f"{name}.child"))
                self.assertNotIn(f"{name}.child", sys.modules)
            finally:
                scope.close()

            self.assertFalse(hasattr(parent, "child"))
        finally:
            sys.modules.pop(name, None)

    def test_removes_parent_attr_when_child_key_removed_before_close(self):
        name = "sentinel_r1b_regression_d6"
        child_name = f"{name}.child"
        parent = types.ModuleType(name)
        sys.modules[name] = parent
        try:
            scope = ModuleIsolationScope(frozenset({name, f"{name}."}))
            scope.open()
            try:
                child = types.ModuleType(child_name)
                sys.modules[child_name] = child
                setattr(parent, "child", child)
                # Remove the child key from sys.modules BEFORE close() runs,
                # leaving the parent attribute itself still in place.
                del sys.modules[child_name]
                self.assertTrue(hasattr(parent, "child"))
            finally:
                scope.close()

            self.assertFalse(hasattr(parent, "child"))
        finally:
            sys.modules.pop(name, None)
            sys.modules.pop(child_name, None)


class PreservedParentAttributeRestorationTests(unittest.TestCase):
    """TEST-INFRA-R1C: defects D9/D10 -- ModuleIsolationScope's managed-parent
    discovery (R10) must derive candidate parents from the scope's NAMESPACE,
    not merely from `_original_matching_names`, so it correctly reaches (D9)
    a PRESERVED parent package -- excluded from `_original_matching_names` by
    construction, since `preserve` is filtered out of
    `_current_matching_names()` -- and (D10) a prefix-only scope's own base
    package (e.g. only "pkg." given, never the exact name "pkg"), which was
    likewise absent from `_original_matching_names`."""

    def test_preserved_parent_new_child_attribute_is_removed(self):
        """D9: a parent package that is itself in `preserve` (so it is never
        deleted from sys.modules and never appears in
        _original_matching_names) must still have a managed attribute
        assigned to it during the scope removed at close()."""
        parent_name = "sentinel_r1c_regression_d9"
        child_name = f"{parent_name}.child"
        for name in (parent_name, child_name):
            sys.modules.pop(name, None)
        parent = types.ModuleType(parent_name)
        sys.modules[parent_name] = parent
        try:
            scope = ModuleIsolationScope(
                frozenset({parent_name, f"{parent_name}."}),
                preserve=frozenset({parent_name}),
            )
            scope.open()
            try:
                self.assertIs(sys.modules.get(parent_name), parent)
                child = types.ModuleType(child_name)
                sys.modules[child_name] = child
                setattr(parent, "child", child)
            finally:
                scope.close()

            self.assertIs(sys.modules.get(parent_name), parent)
            self.assertFalse(hasattr(parent, "child"))
            self.assertNotIn(child_name, sys.modules)
        finally:
            sys.modules.pop(parent_name, None)
            sys.modules.pop(child_name, None)

    def test_prefix_only_scope_captures_base_parent(self):
        """D10: a scope constructed with ONLY a dot-terminated prefix
        ("pkg.") and no exact name ("pkg") must still discover "pkg" itself
        as a managed parent, since it is the namespace base implied by that
        prefix."""
        base_name = "sentinel_r1c_regression_d10"
        child_name = f"{base_name}.child"
        for name in (base_name, child_name):
            sys.modules.pop(name, None)
        base_pkg = types.ModuleType(base_name)
        sys.modules[base_name] = base_pkg
        try:
            scope = ModuleIsolationScope(frozenset({f"{base_name}."}))
            scope.open()
            try:
                child = types.ModuleType(child_name)
                sys.modules[child_name] = child
                setattr(base_pkg, "child", child)
            finally:
                scope.close()

            self.assertFalse(hasattr(base_pkg, "child"))
            self.assertNotIn(child_name, sys.modules)
        finally:
            sys.modules.pop(base_name, None)
            sys.modules.pop(child_name, None)


class OpenRollbackTests(unittest.TestCase):
    """TEST-INFRA-R1B: defects D7 (exception masking during rollback) and
    the R6 requirement that open()'s failure path restore from its own
    incremental snapshots rather than re-scanning sys.modules."""

    def test_open_rollback_preserves_primary_exception(self):
        """If open() fails (primary exception) and its own rollback also
        fails (secondary exception), the PRIMARY exception must still be
        what propagates to the caller, with the rollback failure chained as
        __cause__ -- not replaced by the rollback's exception."""
        name = "sentinel_r1b_regression_d7"
        sys.modules[name] = types.ModuleType(name)

        original_matches = _smi_module._matches
        call_count = {"n": 0}

        def _matches_raises_primary(match_name, prefixes):
            call_count["n"] += 1
            if call_count["n"] > 1:
                raise ValueError("original_open_failure")
            return original_matches(match_name, prefixes)

        scope = ModuleIsolationScope(frozenset({name}))
        original_rollback = _smi_module.ModuleIsolationScope._rollback_partial_open

        def _rollback_raises(self):
            raise RuntimeError("cleanup_failure")

        _smi_module.ModuleIsolationScope._rollback_partial_open = _rollback_raises
        _smi_module._matches = _matches_raises_primary
        try:
            with self.assertRaises(ValueError) as ctx:
                scope.open()
        finally:
            _smi_module._matches = original_matches
            _smi_module.ModuleIsolationScope._rollback_partial_open = original_rollback
            sys.modules.pop(name, None)
            _smi_module._active.engaged = False

        self.assertEqual(str(ctx.exception), "original_open_failure")
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
        self.assertEqual(str(ctx.exception.__cause__), "cleanup_failure")

    def test_open_rollback_chains_secondary_cleanup_failure(self):
        """The thread guard must still be released via the emergency path
        even when the rollback itself raises."""
        name = "sentinel_r1b_regression_d7_guard"
        sys.modules[name] = types.ModuleType(name)

        original_matches = _smi_module._matches
        call_count = {"n": 0}

        def _matches_raises(match_name, prefixes):
            call_count["n"] += 1
            if call_count["n"] > 1:
                raise ValueError("boom")
            return original_matches(match_name, prefixes)

        scope = ModuleIsolationScope(frozenset({name}))
        original_rollback = _smi_module.ModuleIsolationScope._rollback_partial_open

        def _rollback_raises(self):
            raise RuntimeError("rollback_boom")

        _smi_module.ModuleIsolationScope._rollback_partial_open = _rollback_raises
        _smi_module._matches = _matches_raises
        try:
            with self.assertRaises(ValueError):
                scope.open()
        finally:
            _smi_module._matches = original_matches
            _smi_module.ModuleIsolationScope._rollback_partial_open = original_rollback

        self.assertFalse(getattr(_smi_module._active, "engaged", False))
        self.assertFalse(scope._is_open)
        sys.modules.pop(name, None)

        # A follow-up scope must open cleanly right after.
        followup = ModuleIsolationScope(frozenset({"sentinel_r1b_regression_d7_followup"}))
        followup.open()
        followup.close()

    def test_failed_open_restores_partially_removed_modules(self):
        """R1C/R16: strengthened from the R1B version, which forced its
        failure inside _capture_managed_parent_attributes() -- a point that
        runs strictly BEFORE the deletion loop, so the deletion loop's body
        never executed even once (D13: CURRENT_TEST_DELETIONS_COMPLETED_BEFORE_FAILURE
        was always 0, making the test unable to fail even if the deletion
        loop's own undo logic were deleted entirely). This version installs
        a controlled sys.modules substitute in a subprocess whose
        __delitem__ genuinely deletes the first matching name for real, then
        raises while deleting the second -- so the deletion loop
        demonstrably completes at least one real removal before failing.
        Confirms: the first name is restored by identity (not merely
        "never removed"), the second name was never lost, and the thread
        guard is released. Runs in an isolated subprocess so the controlled
        sys.modules substitution never corrupts this test process's own
        module cache."""
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import types
from tests.support.scoped_module_isolation import ModuleIsolationScope, _active

name_a = "sentinel_r1c_regression_r16_a"
name_b = "sentinel_r1c_regression_r16_b"
real_a = types.ModuleType(name_a)
real_b = types.ModuleType(name_b)
sys.modules[name_a] = real_a
sys.modules[name_b] = real_b

class ExplodingModules(dict):
    # Allows deleting name_a for real (so the deletion loop's first
    # iteration genuinely completes), but raises on name_b -- forcing a
    # real mid-loop failure with one confirmed prior real deletion.
    def __delitem__(self, key):
        if key == name_b:
            raise RuntimeError("simulated_failure_during_second_deletion")
        super().__delitem__(key)

original_sys_modules = sys.modules
sys.modules = ExplodingModules(original_sys_modules)

scope = ModuleIsolationScope(frozenset({{name_a, name_b}}))
raised_type = None
try:
    scope.open()
except BaseException as e:
    raised_type = type(e).__name__
finally:
    sys.modules = original_sys_modules

assert raised_type == "RuntimeError", f"unexpected raised type: {{raised_type}}"
assert name_a in sys.modules, "name_a lost after rollback"
assert sys.modules[name_a] is real_a, "name_a not restored by identity"
assert name_b in sys.modules, "name_b lost after failed deletion"
assert sys.modules[name_b] is real_b, "name_b not the original object"
assert not getattr(_active, "engaged", False), "thread guard left engaged"
assert not scope._is_open, "scope left marked open after failed open()"

sys.modules.pop(name_a, None)
sys.modules.pop(name_b, None)
print("OK")
""".format(code_root=str(_TESTS_ROOT.parent))
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(_TESTS_ROOT.parent),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )


class PoisonedScopeTests(unittest.TestCase):
    """TEST-INFRA-R1C: defect D11 -- if open()'s own rollback also fails
    (the D7/R7 scenario), reusing the SAME ModuleIsolationScope object for a
    later open() attempt let residual internal snapshots from the failed
    attempt survive uncleaned (since _clear_internal_state() is never
    reached when _rollback_partial_open() itself raises), risking a later
    close() restoring stale/incorrect objects instead of the ones that
    actually existed before that later attempt. R12 fixes this by marking
    the scope object "poisoned" whenever its rollback fails, and rejecting
    any further open() on that same object deterministically, before it can
    mutate sys.modules again."""

    def test_failed_rollback_poisoned_scope_cannot_restore_stale_snapshot(self):
        name_a = "sentinel_r1c_regression_d11_a"
        name_b = "sentinel_r1c_regression_d11_b"
        for name in (name_a, name_b):
            sys.modules.pop(name, None)
        sys.modules[name_a] = types.ModuleType(name_a)
        sys.modules[name_b] = types.ModuleType(name_b)

        scope = ModuleIsolationScope(frozenset({name_a, name_b}))

        original_capture = _smi_module.ModuleIsolationScope._capture_managed_parent_attributes
        original_rollback = _smi_module.ModuleIsolationScope._rollback_partial_open

        def _capture_raises(self):
            raise RuntimeError("primary_failure_for_d11")

        def _rollback_raises(self):
            raise RuntimeError("rollback_failure_for_d11")

        _smi_module.ModuleIsolationScope._capture_managed_parent_attributes = _capture_raises
        _smi_module.ModuleIsolationScope._rollback_partial_open = _rollback_raises
        try:
            with self.assertRaises(RuntimeError) as ctx:
                scope.open()
            self.assertEqual(str(ctx.exception), "primary_failure_for_d11")
        finally:
            _smi_module.ModuleIsolationScope._capture_managed_parent_attributes = original_capture
            _smi_module.ModuleIsolationScope._rollback_partial_open = original_rollback

        self.assertTrue(scope._poisoned)
        self.assertFalse(getattr(_smi_module._active, "engaged", False))

        # Reusing the SAME poisoned scope object must be rejected
        # deterministically, before it can touch sys.modules again.
        with self.assertRaises(RuntimeError) as ctx:
            scope.open()
        self.assertIn("poisoned", str(ctx.exception))

        # A brand-new scope object over the same names must work normally.
        fresh_scope = ModuleIsolationScope(frozenset({name_a, name_b}))
        fresh_scope.open()
        fresh_scope.close()
        self.assertIn(name_a, sys.modules)
        self.assertIn(name_b, sys.modules)

        sys.modules.pop(name_a, None)
        sys.modules.pop(name_b, None)


class TransactionalMockInstallTests(unittest.TestCase):
    """TEST-INFRA-R1B D8/R8: _install_interaction_dependency_mocks() must
    leave no partial mocks behind if it fails partway through -- the caller
    (_fresh_import_main()) passes a mutable registry that is updated before
    each mutation, so the caller's own except-block cleanup sees everything
    installed up to the point of failure, run in an isolated subprocess so a
    successful reproduction never corrupts this test process's own
    sys.modules state."""

    _CODE_ROOT = _TESTS_ROOT.parent

    def test_partial_mock_install_failure_removes_all_new_mocks(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.unit.test_navigation_runtime_selection as mod

pyttsx3_absent_before = "pyttsx3" not in sys.modules
speech_recognition_absent_before = "speech_recognition" not in sys.modules

def _partial_install_then_raise(installed):
    from unittest.mock import MagicMock
    installed["pyttsx3"] = True
    sys.modules["pyttsx3"] = MagicMock()
    raise RuntimeError("simulated_failure_after_partial_install")

mod._install_interaction_dependency_mocks = _partial_install_then_raise

raised = False
try:
    mod._fresh_import_main()
except RuntimeError:
    raised = True

assert pyttsx3_absent_before
assert raised
assert "pyttsx3" not in sys.modules, "partial mock leaked past the failed call"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(self._CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )


class GlobalScopeReferenceTests(unittest.TestCase):
    """TEST-INFRA-R1B R9: the module-level _module_isolation_scope reference
    in both files must stay None if scope.open() itself fails inside
    _fresh_import_main() -- it must never be assigned to a scope whose
    open() did not complete successfully. Uses a forced monkeypatch on the
    shared helper's _matches(), run in an isolated subprocess."""

    _CODE_ROOT = _TESTS_ROOT.parent

    def test_new_scope_open_failure_leaves_global_scope_none_navigation(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.unit.test_navigation_runtime_selection as mod
import tests.support.scoped_module_isolation as smi_module

original_matches = smi_module._matches
call_count = {{"n": 0}}

def _matches_raises(name, prefixes):
    call_count["n"] += 1
    if call_count["n"] > 1:
        raise RuntimeError("simulated_open_failure")
    return original_matches(name, prefixes)

smi_module._matches = _matches_raises
raised = False
try:
    mod._fresh_import_main()
except RuntimeError:
    raised = True
finally:
    smi_module._matches = original_matches

assert raised, "expected _fresh_import_main() to propagate open()'s failure"
assert mod._module_isolation_scope is None, "global scope reference assigned despite failed open()"
assert not getattr(smi_module._active, "engaged", False), "thread guard left engaged"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(self._CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

    def test_new_scope_open_failure_leaves_global_scope_none_qr(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.integration.test_u2_qr_lifespan_wiring as mod
import tests.support.scoped_module_isolation as smi_module

original_matches = smi_module._matches
call_count = {{"n": 0}}

def _matches_raises(name, prefixes):
    call_count["n"] += 1
    if call_count["n"] > 1:
        raise RuntimeError("simulated_open_failure")
    return original_matches(name, prefixes)

smi_module._matches = _matches_raises
raised = False
try:
    mod._fresh_import_main()
except RuntimeError:
    raised = True
finally:
    smi_module._matches = original_matches

assert raised, "expected _fresh_import_main() to propagate open()'s failure"
assert mod._module_isolation_scope is None, "global scope reference assigned despite failed open()"
assert not getattr(smi_module._active, "engaged", False), "thread guard left engaged"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(self._CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )


class RegistryOrderingTests(unittest.TestCase):
    """TEST-INFRA-R1C: defect D12/R13 -- _install_interaction_dependency_mocks()
    must register each name into the caller-owned `installed` dict BEFORE
    mutating sys.modules for that name, not after. If the registry write
    itself fails (e.g. the caller passed a dict-like object whose
    __setitem__ raises), the OLD ordering had already mutated sys.modules by
    that point, leaving a mock the registry never recorded -- invisible to
    any cleanup relying on the registry to know what to pop()."""

    def test_real_installer_registers_before_sys_modules_mutation(self):
        import tests.unit.test_navigation_runtime_selection as tnr

        class ExplodingRegistry(dict):
            def __setitem__(self, key, value):
                if key == "pyttsx3":
                    raise RuntimeError("registry_write_failure_for_d12")
                super().__setitem__(key, value)

        for name in tnr._INTERACTION_DEPENDENCY_MOCKS:
            sys.modules.pop(name, None)
        try:
            registry = ExplodingRegistry()
            with self.assertRaises(RuntimeError):
                tnr._install_interaction_dependency_mocks(registry)

            # The failed registry write must mean the corresponding
            # sys.modules mutation for THAT name never happened either --
            # registering must run strictly before mutating, not after.
            self.assertNotIn("pyttsx3", sys.modules)
            self.assertNotIn("pyttsx3", registry)
        finally:
            for name in tnr._INTERACTION_DEPENDENCY_MOCKS:
                sys.modules.pop(name, None)


class CallerExceptionPreservationTests(unittest.TestCase):
    """TEST-INFRA-R1C: defect D14 -- both _fresh_import_main() callers must
    preserve the PRIMARY import-path exception even when their own cleanup
    (_remove_interaction_dependency_mocks / scope.close()) also fails, by
    chaining the cleanup failure as __cause__ rather than letting it replace
    the primary exception -- exactly the same pattern D7/R7 already enforces
    inside ModuleIsolationScope.open() itself, applied here one level up at
    the caller. Also covers R15: _purge_app_modules() must clear the global
    scope reference BEFORE calling close(), so it is left None even if
    close() raises."""

    _CODE_ROOT = _TESTS_ROOT.parent

    def _run(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(self._CODE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_navigation_import_failure_preserved_when_close_fails(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.unit.test_navigation_runtime_selection as mod
from tests.support.scoped_module_isolation import ModuleIsolationScope

def failing_install(installed):
    raise ValueError("primary_import_failure")

def patched_close(self):
    raise RuntimeError("scope_close_failure")

mod._install_interaction_dependency_mocks = failing_install
original_close = ModuleIsolationScope.close
ModuleIsolationScope.close = patched_close

propagated = None
try:
    mod._fresh_import_main()
except BaseException as e:
    propagated = e
finally:
    ModuleIsolationScope.close = original_close

assert type(propagated).__name__ == "ValueError", f"wrong type propagated: {{type(propagated).__name__}}"
assert str(propagated) == "primary_import_failure"
assert isinstance(propagated.__cause__, RuntimeError), "rollback failure not chained as cause"
assert str(propagated.__cause__) == "scope_close_failure"
assert mod._module_isolation_scope is None, "global scope reference not cleared"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = self._run(script)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

    def test_qr_import_failure_preserved_when_close_fails(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import builtins
import tests.integration.test_u2_qr_lifespan_wiring as mod
from tests.support.scoped_module_isolation import ModuleIsolationScope

real_import = builtins.__import__

def failing_import(name, *args, **kwargs):
    if name == "main":
        raise ValueError("primary_import_failure")
    return real_import(name, *args, **kwargs)

def patched_close(self):
    raise RuntimeError("scope_close_failure")

builtins.__import__ = failing_import
original_close = ModuleIsolationScope.close
ModuleIsolationScope.close = patched_close

propagated = None
try:
    mod._fresh_import_main()
except BaseException as e:
    propagated = e
finally:
    builtins.__import__ = real_import
    ModuleIsolationScope.close = original_close

assert type(propagated).__name__ == "ValueError", f"wrong type propagated: {{type(propagated).__name__}}"
assert str(propagated) == "primary_import_failure"
assert isinstance(propagated.__cause__, RuntimeError), "rollback failure not chained as cause"
assert str(propagated.__cause__) == "scope_close_failure"
assert mod._module_isolation_scope is None, "global scope reference not cleared"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = self._run(script)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

    def test_purge_navigation_clears_global_before_close(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.unit.test_navigation_runtime_selection as mod
from tests.support.scoped_module_isolation import ModuleIsolationScope

mod._fresh_import_main()
assert mod._module_isolation_scope is not None

def patched_close(self):
    raise RuntimeError("scope_close_failure_during_purge")

original_close = ModuleIsolationScope.close
ModuleIsolationScope.close = patched_close
try:
    raised = False
    try:
        mod._purge_app_modules()
    except RuntimeError:
        raised = True
finally:
    ModuleIsolationScope.close = original_close

assert raised, "expected _purge_app_modules() to propagate close()'s failure"
assert mod._module_isolation_scope is None, "global scope reference must be None even when close() raised"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = self._run(script)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )

    def test_purge_qr_clears_global_before_close(self):
        script = r"""
import sys
sys.path.insert(0, r"{code_root}")
import tests.integration.test_u2_qr_lifespan_wiring as mod
from tests.support.scoped_module_isolation import ModuleIsolationScope

mod._fresh_import_main()
assert mod._module_isolation_scope is not None

def patched_close(self):
    raise RuntimeError("scope_close_failure_during_purge")

original_close = ModuleIsolationScope.close
ModuleIsolationScope.close = patched_close
try:
    raised = False
    try:
        mod._purge_app_modules()
    except RuntimeError:
        raised = True
finally:
    ModuleIsolationScope.close = original_close

assert raised, "expected _purge_app_modules() to propagate close()'s failure"
assert mod._module_isolation_scope is None, "global scope reference must be None even when close() raised"
print("OK")
""".format(code_root=str(self._CODE_ROOT))
        result = self._run(script)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )


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
