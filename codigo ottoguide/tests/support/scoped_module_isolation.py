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
         paquete padre alcanzado por esos prefijos: los modulos originales se
         restauran por identidad, los atributos administrados originales de
         los paquetes padre se restauran o se eliminan segun corresponda
         (incluso si la entrada hija correspondiente ya no existe en
         sys.modules al momento de cerrar), y cualquier nombre/atributo NUEVO
         que haya aparecido durante el scope se elimina, no se conserva.
@CONTEXT: R1 solo restauraba los nombres que ya existian al abrir el scope
          (fugaba nombres/atributos nuevos: R1A defectos D1/D2). R1A corrigio
          eso re-calculando el conjunto de nombres coincidentes al cerrar,
          pero derivaba que atributos de paquete padre arreglar EXCLUSIVAMENTE
          de diffs sobre sys.modules -- lo cual sigue fugando: (D5) un
          atributo asignado directamente a un padre sin registrar la entrada
          hija en sys.modules es invisible a ese diff; (D6) un atributo cuya
          entrada hija SI se registro pero fue retirada de sys.modules antes
          de close() tambien es invisible, porque el diff se computa en el
          momento de cerrar, no en el momento en que el atributo se asigno.
          R1A tampoco preservaba la excepcion primaria si el propio rollback
          de open() fallaba (D7): la excepcion del rollback reemplazaba a la
          original en vez de propagarse como causa encadenada.
          Esta version (R1B) corrige los tres huecos: captura al abrir QUE
          atributos de cada paquete padre son "administrados" (ModuleType
          cuyo __name__ cae dentro del namespace exacto/prefijo del scope) y
          sus valores originales, independientemente de sys.modules; restaura
          esos atributos exactos al cerrar sin volver a derivarlos de un
          diff de sys.modules; y separa la ruta de rollback de open() fallido
          de la logica general de close(), preservando la excepcion primaria
          incluso si el propio rollback falla.
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


class ModuleIsolationScope:
    """Retira temporalmente de sys.modules los nombres que matchean
    `prefixes` (nombres exactos, o prefijos que terminan en '.') y no estan
    en `preserve`. Al cerrarse, restaura el conjunto EXACTO de nombres
    coincidentes y de atributos administrados de paquetes padre que existia
    antes de abrir -- capturado directamente al abrir, nunca re-derivado de
    un diff de sys.modules al cerrar -- incluyendo la eliminacion de
    cualquier nombre/atributo nuevo introducido durante el scope. `open()`
    es transaccional: si cualquier paso falla, revierte exactamente lo ya
    capturado/retirado por ESE intento de open() (sin re-escanear
    sys.modules) antes de propagar la excepcion original, incluso si el
    propio rollback falla.

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

    def _current_matching_names(self) -> set[str]:
        return {
            name
            for name in list(sys.modules)
            if name not in self._preserve and _matches(name, self._prefixes)
        }

    def _capture_managed_parent_attributes(self) -> None:
        """Walks every parent package reachable from
        self._original_matching_names' prefixes and records, for every
        attribute whose value is currently a 'managed' module (per
        _is_managed_attribute_value), its original value -- independent of
        whether that value is also present in sys.modules under its own
        name. This is what makes D5 (attribute without a sys.modules entry)
        and D6 (sys.modules entry removed before close) both visible."""
        # A parent candidate is either (a) the immediate parent package of a
        # matching name (e.g. "src.navigation" for "src.navigation.models"),
        # or (b) a matching name itself, since a matched module/package can
        # also directly receive a managed attribute assignment on itself
        # (e.g. "sentinel.child = ModuleType(...)" where "sentinel" is
        # itself one of original_matching_names).
        parent_names = set(self._original_matching_names)
        for name in self._original_matching_names:
            parent_info = _parent_and_leaf(name)
            if parent_info is not None:
                parent_names.add(parent_info[0])
        for parent_name in parent_names:
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
                # R7: the rollback itself failed. The PRIMARY exception must
                # still be what propagates -- release the guard via a
                # last-resort path that touches nothing but internal flags,
                # and chain the rollback failure as the cause for
                # diagnostics, without letting it replace the primary error.
                self._force_release_guard()
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
        """Restores sys.modules and managed parent attributes to the exact
        pre-open() state, then clears all internal snapshots and releases
        the thread guard. Used by close() following a SUCCESSFUL open()."""
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

            # R5 (fixes D5/D6): restore/clear managed parent attributes from
            # the snapshots captured at open()-time -- never by re-deriving
            # "what changed" from a fresh sys.modules scan. This correctly
            # handles attributes that were never registered under their own
            # name in sys.modules (D5) and attributes whose sys.modules
            # entry was removed before close() ran (D6), because neither
            # case is looked up again here: the parent OBJECT and the leaf
            # NAME were captured directly at open()-time.
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
