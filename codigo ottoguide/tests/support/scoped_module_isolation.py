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
         el scope: los modulos originales se restauran por identidad, los
         atributos originales de los paquetes padre se restauran o se
         eliminan segun corresponda, y cualquier nombre/atributo NUEVO que
         haya aparecido durante el scope (p.ej. un submodulo que un reimport
         intermedio cargo por primera vez) se elimina, no se conserva.
@CONTEXT: Los purges previos eliminaban src.*/config.* de forma indefinida
          (nunca se restauraban). Una primera version de este helper (R1)
          solo restauraba los nombres que ya existian al abrir el scope,
          dejando fugar cualquier modulo/atributo nuevo creado DURANTE el
          scope (TEST-INFRA-R1A defectos D1/D2), y no era exception-safe en
          open() (defecto D3: una falla a mitad de open() dejaba el guard de
          hilo activo para siempre). Esta version (R1A) corrige ambos huecos:
          el conjunto de nombres coincidentes se re-calcula al cerrar y se
          compara contra el conjunto original, y open() es transaccional.
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


class ModuleIsolationScope:
    """Retira temporalmente de sys.modules los nombres que matchean
    `prefixes` (nombres exactos, o prefijos que terminan en '.') y no estan
    en `preserve`. Al cerrarse, restaura el conjunto EXACTO de nombres
    coincidentes que existia antes de abrir -- no solo los que se llegaron a
    capturar -- incluyendo la eliminacion de cualquier nombre/atributo nuevo
    introducido durante el scope. `open()` es transaccional: si cualquier
    paso falla, revierte lo ya retirado antes de propagar la excepcion.

    Rechaza explicitamente scopes anidados en el mismo hilo: no hay ningun
    caller actual que necesite componer dos scopes, y apilar snapshots sin un
    caso de uso real que lo valide es mas riesgo que beneficio.
    """

    def __init__(self, prefixes: frozenset[str], *, preserve: frozenset[str] = frozenset()):
        self._prefixes = prefixes
        self._preserve = preserve
        self._original_matching_names: set[str] = set()
        self._captured_modules: dict[str, ModuleType] = {}
        self._captured_parent_attrs: dict[str, object] = {}
        self._is_open = False

    def _current_matching_names(self) -> set[str]:
        return {
            name
            for name in list(sys.modules)
            if name not in self._preserve and _matches(name, self._prefixes)
        }

    def _affected_parents(self, names: set[str]) -> set[str]:
        parents = set()
        for name in names:
            parent_info = _parent_and_leaf(name)
            if parent_info is not None:
                parents.add(parent_info[0])
        return parents

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

            for name in self._original_matching_names:
                parent_info = _parent_and_leaf(name)
                if parent_info is None:
                    continue
                parent_name, leaf = parent_info
                parent_module = sys.modules.get(parent_name)
                if parent_module is None:
                    continue
                self._captured_parent_attrs[name] = getattr(parent_module, leaf, _SENTINEL)

            for name in self._original_matching_names:
                del sys.modules[name]

            self._is_open = True
        except BaseException:
            # Transactional: undo anything already captured/removed before
            # re-raising, so a failure mid-open() never leaves the thread
            # guard engaged or modules permanently missing (D3).
            self._restore_and_reset()
            raise

    def _restore_and_reset(self) -> None:
        """Restores sys.modules and parent attributes to the exact
        pre-open() state, then clears all internal snapshots and releases
        the thread guard. Used by both close() and open()'s failure path."""
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

            # D2: reset every parent package touched by the ORIGINAL matching
            # set (not just the ones still present in _captured_parent_attrs)
            # so that any new attribute a reimport introduced is cleared, and
            # every original attribute (present or absent) is restored.
            affected_parents = self._affected_parents(
                self._original_matching_names | leaked_names
            )
            for parent_name in affected_parents:
                parent_module = sys.modules.get(parent_name)
                if parent_module is None:
                    continue
                for name, original_attr in self._captured_parent_attrs.items():
                    parent_info = _parent_and_leaf(name)
                    if parent_info is None or parent_info[0] != parent_name:
                        continue
                    leaf = parent_info[1]
                    if original_attr is _SENTINEL:
                        if hasattr(parent_module, leaf):
                            delattr(parent_module, leaf)
                    else:
                        setattr(parent_module, leaf, original_attr)
                # Also strip any leaf attribute introduced during the scope
                # for a leaked name whose parent is this one, even though it
                # was never in _captured_parent_attrs (it didn't exist
                # originally, so there is no captured entry for it at all).
                for name in leaked_names:
                    parent_info = _parent_and_leaf(name)
                    if parent_info is None or parent_info[0] != parent_name:
                        continue
                    leaf = parent_info[1]
                    if name not in self._captured_parent_attrs and hasattr(parent_module, leaf):
                        delattr(parent_module, leaf)
        finally:
            self._original_matching_names = set()
            self._captured_modules.clear()
            self._captured_parent_attrs.clear()
            self._is_open = False
            _active.engaged = False

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
