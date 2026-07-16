"""
@TASK: Proveer un aislamiento de sys.modules acotado y reversible, para
       reemplazar los purges globales/allowlist de src.* usados por
       test_navigation_runtime_selection.py y test_u2_qr_lifespan_wiring.py.
@INPUT: Un conjunto cerrado de nombres exactos y/o prefijos ("pkg.") a
        retirar temporalmente de sys.modules.
@OUTPUT: Mientras el scope esta abierto, los nombres retirados estan ausentes
         de sys.modules (permitiendo un import fresco, p.ej. `import main`).
         Al cerrarse el scope -- incluso si algo lanzo mientras estaba
         abierto, o si open() mismo lanzo -- se restaura EXACTAMENTE el
         conjunto de nombres que coincidian con los prefijos antes de abrir
         el scope, Y el conjunto exacto de atributos "administrados" de cada
         paquete padre alcanzado por esos prefijos -- incluyendo paquetes
         padre PRESERVADOS, que nunca se retiran de sys.modules pero cuyos
         atributos administrados igual se restauran exactamente: los
         modulos originales se restauran por identidad, los atributos
         administrados originales de los paquetes padre se restauran o se
         eliminan segun corresponda (incluso si la entrada hija
         correspondiente ya no existe en sys.modules al momento de cerrar),
         y cualquier nombre/atributo NUEVO que haya aparecido durante el
         scope se elimina, no se conserva. Si el rollback de un open()
         fallido tambien falla, el scope queda "poisoned" (R1C/R12): un
         intento posterior de open() sobre el MISMO objeto scope se rechaza
         de forma deterministica antes de mutar sys.modules, en vez de
         reutilizar snapshots residuales de un intento anterior que nunca
         se limpiaron.
@CONTEXT: R1 solo restauraba los nombres que ya existian al abrir el scope
          (fugaba nombres/atributos nuevos: R1A defectos D1/D2). R1A corrigio
          eso re-calculando el conjunto de nombres coincidentes al cerrar,
          pero derivaba que atributos de paquete padre arreglar EXCLUSIVAMENTE
          de diffs sobre sys.modules -- lo cual seguia fugando: (D5) un
          atributo asignado directamente a un padre sin registrar la entrada
          hija en sys.modules es invisible a ese diff; (D6) un atributo cuya
          entrada hija SI se registro pero fue retirada de sys.modules antes
          de close() tambien es invisible. R1A tampoco preservaba la
          excepcion primaria si el propio rollback de open() fallaba (D7).
          R1B corrigio D5/D6/D7 capturando los atributos administrados al
          abrir, independientemente de sys.modules, y separando la ruta de
          rollback de open() fallido de close(), con encadenamiento de
          excepciones. Pero R1B seguia derivando la lista de paquetes padre
          administrados EXCLUSIVAMENTE de `_original_matching_names` -- lo
          cual sigue fugando: (D9) un paquete padre PRESERVADO (excluido de
          `_original_matching_names` por definicion, ya que `preserve` se
          filtra en `_current_matching_names()`) nunca entra en
          `_managed_parents`, asi que un atributo asignado a el durante el
          scope nunca se captura ni se restaura; (D10) un scope que usa
          solo un prefijo ("pkg.", sin el nombre exacto "pkg" en absoluto)
          tampoco captura el paquete base "pkg" como padre administrado por
          el mismo motivo. R1B tampoco poisoning-aba un scope cuyo rollback
          fallo (D11): reutilizar el mismo objeto scope despues de eso deja
          sobrevivir snapshots residuales del intento fallido (p.ej.
          `_captured_modules` nunca se limpio porque `_clear_internal_state()`
          jamas se alcanzo), que un intento posterior puede usar para
          restaurar objetos incorrectos. Y los dos callers (D14) reemplazaban
          la excepcion primaria de `import main` con la excepcion de un
          `scope.close()` fallido en el cleanup, en vez de encadenarla.
          Esta version (R1C) corrige todo lo anterior: (R10) descubre los
          paquetes padre administrados desde el NAMESPACE del scope (nombres
          base de prefijos, nombres exactos, sus padres inmediatos, y
          cualquier modulo preservado dentro de ese namespace), no solo
          desde `_original_matching_names`; (R11) un paquete preservado
          nunca se elimina de sys.modules pero sus atributos administrados
          se restauran exactamente igual que cualquier otro padre; (R12) si
          el rollback de open() tambien falla, el scope se marca
          "poisoned" y rechaza cualquier open() posterior sin mutar
          sys.modules; (R13) el registro de mocks instalados se actualiza
          ANTES de cada mutacion real de sys.modules, no despues; (R14/R15)
          ambos callers preservan la excepcion primaria de `import main`
          encadenando cualquier fallo secundario de cleanup como causa, y
          limpian la referencia global ANTES de intentar el cleanup
          fallible, no despues.
@AI_CONTEXT: No reemplaza tests.support.core_module_identity -- las claves en
             `preserve` deben incluir PRESERVED_CORE_IDENTITY_MODULES cuando
             el llamador purga src.*, exactamente como antes. Soporta dos
             estilos de uso: `with fresh_reimport_scope(...): import main`
             (purga+restaura dentro del mismo bloque) o
             `scope = ModuleIsolationScope(...); scope.open(); ...;
             scope.close()` (abrir en setUp, cerrar en tearDown).
"""
from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from types import ModuleType
from typing import Iterator

_SENTINEL = object()
_active = threading.local()


def _matches(name: str, prefixes: frozenset[str]) -> bool:
    for prefix in prefixes:
        if prefix.endswith("."):
            if name.startswith(prefix):
                return True
        elif name == prefix:
            return True
    return False


def _parent_and_leaf(name: str) -> tuple[str, str] | None:
    if "." not in name:
        return None
    parent, _, leaf = name.rpartition(".")
    return parent, leaf


def _is_managed_attribute_value(value: object, prefixes: frozenset[str]) -> bool:
    """A parent attribute is 'managed' -- eligible for capture/restoration --
    iff its current value is a ModuleType whose __name__ falls within the
    scope's exact-name-or-prefix namespace. This excludes any non-module
    attribute (plain data, functions, classes) from ever being touched."""
    if not isinstance(value, ModuleType):
        return False
    module_name = getattr(value, "__name__", None)
    if not isinstance(module_name, str):
        return False
    return _matches(module_name, prefixes)


def _namespace_base_names(prefixes: frozenset[str]) -> set[str]:
    """R10: the set of 'root' names implied directly by the scope's own
    prefixes/exact-names -- e.g. {"src"} for prefix "src.", or {"pkg"} for
    exact name "pkg". This is namespace-derived, independent of whatever
    happens to be in sys.modules or in _original_matching_names at any given
    moment."""
    bases: set[str] = set()
    for prefix in prefixes:
        if prefix.endswith("."):
            bases.add(prefix[:-1])
        else:
            bases.add(prefix)
    return bases


def _is_namespace_ancestor(candidate_name: str, prefixes: frozenset[str]) -> bool:
    """True iff `candidate_name` equals one of the scope's namespace base
    names, or is an ancestor package of one (e.g. "src" is an ancestor of
    "src.core" if "src.core." were a prefix)."""
    bases = _namespace_base_names(prefixes)
    if candidate_name in bases:
        return True
    for base in bases:
        if base == candidate_name:
            return True
        if base.startswith(candidate_name + "."):
            return True
    return False


class ModuleIsolationScope:
    """Retira temporalmente de sys.modules los nombres que matchean
    `prefixes` (nombres exactos, o prefijos que terminan en '.') y no estan
    en `preserve`. Al cerrarse, restaura el conjunto EXACTO de nombres
    coincidentes y de atributos administrados de paquetes padre -- incluidos
    los preservados -- que existia antes de abrir, capturado directamente al
    abrir, nunca re-derivado de un diff de sys.modules al cerrar -- incluyendo
    la eliminacion de cualquier nombre/atributo nuevo introducido durante el
    scope. `open()` es transaccional: si cualquier paso falla, revierte
    exactamente lo ya capturado/retirado por ESE intento de open() (sin
    re-escanear sys.modules) antes de propagar la excepcion original, incluso
    si el propio rollback falla -- en cuyo caso el scope queda "poisoned" y
    rechaza cualquier open() posterior (R1C/R12), en vez de arriesgarse a que
    un intento posterior reutilice snapshots residuales del intento fallido.

    Rechaza explicitamente scopes anidados en el mismo hilo: no hay ningun
    caller actual que necesite componer dos scopes, y apilar snapshots sin un
    caso de uso real que lo valide es mas riesgo que beneficio.
    """

    def __init__(self, prefixes: frozenset[str], *, preserve: frozenset[str] = frozenset()):
        self._prefixes = prefixes
        self._preserve = preserve
        # ORIGINAL_MATCHING_SYS_MODULE_NAMES
        self._original_matching_names: set[str] = set()
        # ORIGINAL_MODULE_OBJECTS
        self._captured_modules: dict[str, ModuleType] = {}
        # MANAGED_PARENT_MODULE_OBJECTS -- keyed by parent name, capturing the
        # actual parent module OBJECT (not just its name), so close() inspects
        # the real object even if sys.modules[parent_name] is later rebound.
        self._managed_parents: dict[str, ModuleType] = {}
        # ORIGINAL_MANAGED_CHILD_ATTRIBUTES / ORIGINAL_MANAGED_CHILD_ATTRIBUTE_PRESENCE
        # -- keyed by (parent_name, leaf), value is the original attribute
        # value or _SENTINEL if the attribute did not exist originally.
        self._managed_attr_originals: dict[tuple[str, str], object] = {}
        # Incrementally tracks exactly what THIS open() call has removed so
        # far, so a failure mid-open() can be undone without re-scanning
        # sys.modules (R6).
        self._deleted_so_far: list[str] = []
        self._is_open = False
        # R1C/R12: once True, this scope object refuses any further open()
        # deterministically -- set only when open()'s own rollback path
        # itself fails, since at that point internal snapshots may be
        # incomplete/stale and cannot be trusted for a future restore.
        self._poisoned = False

    def _current_matching_names(self) -> set[str]:
        return {
            name
            for name in list(sys.modules)
            if name not in self._preserve and _matches(name, self._prefixes)
        }

    def _discover_managed_parent_names(self) -> set[str]:
        """R10: discovers every parent-package name whose attributes this
        scope must manage, derived from the scope's NAMESPACE -- not merely
        from whichever names happen to be in `_original_matching_names` at
        this particular open() (which excludes anything in `preserve` by
        construction, and excludes a namespace's own base package when only
        a dotted prefix like "pkg." is given, never the exact name "pkg").

        Includes:
          1. the base name of every dot-terminated prefix ("src" for "src.");
          2. every exact name declared in `prefixes`;
          3. the immediate parent package of every exact name in `prefixes`;
          4. any module currently in sys.modules whose name equals the
             namespace base or is an ancestor of it (covers a PRESERVED
             parent package, e.g. "src" when "src" itself is in `preserve`);
          5. the immediate parent of any name currently matching the scope
             OR currently preserved, as long as that name falls in the
             namespace (covers both currently-matching and preserved
             children uniformly).

        Must work correctly even when `_original_matching_names` is empty,
        and even when the only relevant package is itself in `preserve`.
        Never walks or touches any module outside the scope's own
        namespace."""
        candidate_names: set[str] = set(_namespace_base_names(self._prefixes))

        for prefix in self._prefixes:
            if not prefix.endswith("."):
                candidate_names.add(prefix)
                parent_info = _parent_and_leaf(prefix)
                if parent_info is not None:
                    candidate_names.add(parent_info[0])

        for name in list(sys.modules):
            in_namespace = _matches(name, self._prefixes) or _is_namespace_ancestor(
                name, self._prefixes
            )
            if not in_namespace:
                continue
            candidate_names.add(name)
            parent_info = _parent_and_leaf(name)
            if parent_info is not None:
                candidate_names.add(parent_info[0])

        return candidate_names

    def _capture_managed_parent_attributes(self) -> None:
        """Walks every parent package discovered by
        `_discover_managed_parent_names()` (R10 -- namespace-derived, so it
        includes preserved parents and prefix-only base packages, closing
        D9/D10) and records, for every attribute whose value is currently a
        'managed' module (per _is_managed_attribute_value), its original
        value -- independent of whether that value is also present in
        sys.modules under its own name. This is what makes D5 (attribute
        without a sys.modules entry) and D6 (sys.modules entry removed
        before close) both visible, for BOTH ordinary and preserved
        parents."""
        for parent_name in self._discover_managed_parent_names():
            parent_module = sys.modules.get(parent_name)
            if parent_module is None or not isinstance(parent_module, ModuleType):
                continue
            self._managed_parents[parent_name] = parent_module
            for leaf, value in list(vars(parent_module).items()):
                if leaf.startswith("__") and leaf.endswith("__"):
                    continue
                if _is_managed_attribute_value(value, self._prefixes):
                    self._managed_attr_originals[(parent_name, leaf)] = value

    def open(self) -> None:
        if self._poisoned:
            raise RuntimeError(
                "ModuleIsolationScope.open() rejected: this scope object is "
                "poisoned because a previous open() attempt's rollback "
                "itself failed, leaving its internal snapshots untrustworthy "
                "-- construct a new ModuleIsolationScope instead of reusing "
                "this one"
            )
        if self._is_open:
            raise RuntimeError("ModuleIsolationScope.open() called while already open")
        if getattr(_active, "engaged", False):
            raise RuntimeError(
                "fresh_reimport_scope/ModuleIsolationScope called while already "
                "active in this thread — nested scopes are not supported"
            )
        _active.engaged = True

        try:
            self._original_matching_names = self._current_matching_names()

            for name in self._original_matching_names:
                self._captured_modules[name] = sys.modules[name]

            self._capture_managed_parent_attributes()

            for name in self._original_matching_names:
                del sys.modules[name]
                self._deleted_so_far.append(name)

            self._is_open = True
        except BaseException as primary:
            # R6: undo exactly what THIS open() call captured/removed so
            # far, without re-scanning sys.modules (that general-purpose
            # diff logic in _restore_and_reset() assumes a completed
            # open(), which this one is not).
            try:
                self._rollback_partial_open()
            except BaseException as rollback_error:
                # R7/R12: the rollback itself failed. The PRIMARY exception
                # must still be what propagates -- release the guard via a
                # last-resort path that touches nothing but internal flags,
                # poison the scope so no future open() on this SAME object
                # can reuse now-untrustworthy residual snapshots (D11), and
                # chain the rollback failure as the cause for diagnostics,
                # without letting it replace the primary error.
                self._force_release_guard()
                self._poisoned = True
                raise primary.with_traceback(primary.__traceback__) from rollback_error
            raise

    def _rollback_partial_open(self) -> None:
        """Restores exactly what this open() call captured/deleted so far,
        using only the incremental snapshots taken during this attempt --
        never a fresh sys.modules scan. Used only from open()'s failure
        path (R6)."""
        for name in reversed(self._deleted_so_far):
            if name in self._captured_modules:
                sys.modules[name] = self._captured_modules[name]
        for (parent_name, leaf), original_value in self._managed_attr_originals.items():
            parent_module = self._managed_parents.get(parent_name)
            if parent_module is None:
                continue
            if original_value is _SENTINEL:
                if hasattr(parent_module, leaf):
                    delattr(parent_module, leaf)
            else:
                setattr(parent_module, leaf, original_value)
        self._clear_internal_state()

    def _force_release_guard(self) -> None:
        """Last-resort emergency release: touches ONLY the thread guard and
        internal open/closed flags, never sys.modules or parent attributes
        again -- used when we can no longer trust the state enough to retry
        a full restore (R7)."""
        self._is_open = False
        _active.engaged = False

    def _clear_internal_state(self) -> None:
        self._original_matching_names = set()
        self._captured_modules.clear()
        self._managed_parents.clear()
        self._managed_attr_originals.clear()
        self._deleted_so_far = []
        self._is_open = False
        _active.engaged = False

    def _restore_and_reset(self) -> None:
        """Restores sys.modules and managed parent attributes (including
        preserved parents, R11) to the exact pre-open() state, then clears
        all internal snapshots and releases the thread guard. Used by
        close() following a SUCCESSFUL open()."""
        try:
            current_matching_names = self._current_matching_names()
            leaked_names = current_matching_names - self._original_matching_names

            # D1: anything matching the prefixes that did NOT exist before
            # the scope opened is a leak (e.g. a submodule freshly imported
            # during the scope) -- remove it, there is nothing to restore it
            # to since it never existed originally.
            for name in leaked_names:
                sys.modules.pop(name, None)

            # Restore every originally-matching module object by identity.
            for name, module in self._captured_modules.items():
                sys.modules[name] = module

            # R5/R11 (fixes D5/D6/D9/D10): restore/clear managed parent
            # attributes from the snapshots captured at open()-time -- never
            # by re-deriving "what changed" from a fresh sys.modules scan.
            # `self._managed_parents` already includes preserved parents and
            # prefix-only base packages (R10's namespace-derived discovery),
            # so this loop handles them uniformly with ordinary parents:
            # the parent OBJECT and the leaf NAME were captured directly at
            # open()-time, regardless of whether the parent itself is ever
            # deleted from sys.modules (preserved parents never are).
            for parent_name, parent_module in self._managed_parents.items():
                # First, restore/clear every leaf that was captured at
                # open()-time for this parent.
                captured_leaves_for_parent = {
                    leaf
                    for (p, leaf) in self._managed_attr_originals
                    if p == parent_name
                }
                for leaf in captured_leaves_for_parent:
                    original_value = self._managed_attr_originals[(parent_name, leaf)]
                    if original_value is _SENTINEL:
                        if hasattr(parent_module, leaf):
                            delattr(parent_module, leaf)
                    else:
                        setattr(parent_module, leaf, original_value)
                # Then, strip any NEW managed attribute introduced during the
                # scope that was never captured (it did not exist
                # originally, so there is nothing to restore it to).
                for leaf, value in list(vars(parent_module).items()):
                    if leaf.startswith("__") and leaf.endswith("__"):
                        continue
                    if leaf in captured_leaves_for_parent:
                        continue
                    if _is_managed_attribute_value(value, self._prefixes):
                        delattr(parent_module, leaf)
        finally:
            self._clear_internal_state()

    def close(self) -> None:
        if not self._is_open:
            return
        self._restore_and_reset()


@contextmanager
def fresh_reimport_scope(
    prefixes: frozenset[str],
    *,
    preserve: frozenset[str] = frozenset(),
) -> Iterator[None]:
    """Context-manager form of ModuleIsolationScope: purges on enter,
    restores on exit (even if the block raised, or if entering itself
    failed partway through)."""
    scope = ModuleIsolationScope(prefixes, preserve=preserve)
    scope.open()
    try:
        yield
    finally:
        scope.close()


__all__ = ["ModuleIsolationScope", "fresh_reimport_scope"]
