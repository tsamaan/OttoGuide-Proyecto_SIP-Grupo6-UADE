"""
@TASK: Proveer un aislamiento de sys.modules acotado y reversible, para
       reemplazar los purges globales/allowlist de src.* usados por
       test_navigation_runtime_selection.py y test_u2_qr_lifespan_wiring.py.
@INPUT: Un conjunto cerrado de nombres exactos y/o prefijos ("pkg.") a
        retirar temporalmente de sys.modules.
@OUTPUT: Mientras el scope esta abierto, los nombres retirados estan ausentes
         de sys.modules (permitiendo un import fresco, p.ej. `import main`).
         Al cerrarse el scope -- incluso si algo lanzo mientras estaba
         abierto -- se restauran EXACTAMENTE los objetos de modulo originales
         (no se reimporta nada durante la restauracion), y se restauran
         tambien los atributos de los paquetes padres que un reimport
         intermedio pudo haber sobrescrito.
@CONTEXT: Los purges previos eliminaban src.*/config.* de forma indefinida
          (nunca se restauraban), dejando que main.py y el resto del arbol de
          paquetes se reimportaran frescos para el resto del proceso de
          pytest. Esta utilidad acota esa mutacion a la ventana
          open()/close() (o al bloque `with`) y la revierte simetricamente,
          evitando que un test posterior en el mismo proceso reciba objetos
          de modulo/clase incompatibles con los que alguna closure ya
          capturo antes de esa ventana.
@AI_CONTEXT: No reemplaza tests.support.core_module_identity -- las claves en
             `preserve` deben incluir PRESERVED_CORE_IDENTITY_MODULES cuando
             el llamador purga src.*, exactamente como antes. Soporta dos
             estilos de uso: `with fresh_reimport_scope(...): import main`
             (purga+restaura dentro del mismo bloque) o
             `scope = ModuleIsolationScope(...); scope.open(); ...;
             scope.close()` (abrir en setUp, cerrar en tearDown -- el patron
             que necesitan los 15+ TestCase de los dos archivos objetivo,
             donde el modulo debe permanecer fresco durante todo el cuerpo
             del test, no solo durante el import).
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
    en `preserve`. Restaura exactamente los objetos originales -- de
    sys.modules y de los atributos de sus paquetes padre -- al cerrarse,
    incluso si algo lanzo mientras el scope estaba abierto.

    Rechaza explicitamente scopes anidados en el mismo hilo: no hay ningun
    caller actual que necesite componer dos scopes, y apilar snapshots sin un
    caso de uso real que lo valide es mas riesgo que beneficio.
    """

    def __init__(self, prefixes: frozenset[str], *, preserve: frozenset[str] = frozenset()):
        self._prefixes = prefixes
        self._preserve = preserve
        self._captured_modules: dict[str, ModuleType] = {}
        self._captured_parent_attrs: dict[str, object] = {}
        self._is_open = False

    def open(self) -> None:
        if self._is_open:
            raise RuntimeError("ModuleIsolationScope.open() called while already open")
        if getattr(_active, "engaged", False):
            raise RuntimeError(
                "fresh_reimport_scope/ModuleIsolationScope called while already "
                "active in this thread — nested scopes are not supported"
            )
        _active.engaged = True

        for name in list(sys.modules):
            if name in self._preserve:
                continue
            if not _matches(name, self._prefixes):
                continue
            self._captured_modules[name] = sys.modules[name]

        for name in self._captured_modules:
            parent_info = _parent_and_leaf(name)
            if parent_info is None:
                continue
            parent_name, leaf = parent_info
            parent_module = sys.modules.get(parent_name)
            if parent_module is None:
                continue
            self._captured_parent_attrs[name] = getattr(parent_module, leaf, _SENTINEL)

        for name in self._captured_modules:
            del sys.modules[name]

        self._is_open = True

    def close(self) -> None:
        if not self._is_open:
            return
        try:
            for name, module in self._captured_modules.items():
                sys.modules[name] = module

            for name, original_attr in self._captured_parent_attrs.items():
                parent_name, leaf = _parent_and_leaf(name)  # type: ignore[misc]
                parent_module = sys.modules.get(parent_name)
                if parent_module is None:
                    continue
                if original_attr is _SENTINEL:
                    if hasattr(parent_module, leaf):
                        delattr(parent_module, leaf)
                else:
                    setattr(parent_module, leaf, original_attr)
        finally:
            self._captured_modules.clear()
            self._captured_parent_attrs.clear()
            self._is_open = False
            _active.engaged = False


@contextmanager
def fresh_reimport_scope(
    prefixes: frozenset[str],
    *,
    preserve: frozenset[str] = frozenset(),
) -> Iterator[None]:
    """Context-manager form of ModuleIsolationScope: purges on enter,
    restores on exit (even if the block raised)."""
    scope = ModuleIsolationScope(prefixes, preserve=preserve)
    scope.open()
    try:
        yield
    finally:
        scope.close()


__all__ = ["ModuleIsolationScope", "fresh_reimport_scope"]
