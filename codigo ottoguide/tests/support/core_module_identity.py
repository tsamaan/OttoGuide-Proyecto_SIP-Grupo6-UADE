"""
@TASK: Garantizar una unica identidad canonica de src.core.events/event_bus por proceso de pytest
@INPUT: Sin parametros (opera sobre sys.modules del proceso actual)
@OUTPUT: Las clases EventType y OttoEventBus, cargadas como maximo una vez por proceso
@CONTEXT: src/core/__init__.py importa tour_orchistrator -> src.navigation -> rclpy a nivel de
          modulo, lo cual no esta disponible en este workstation. Por eso varios archivos de test
          cargaban events.py/event_bus.py directamente desde archivo via importlib, evitando pasar
          por el paquete src.core. El defecto que este modulo corrige no es esa tecnica en si, sino
          que multiples archivos repetian la carga SIN verificar si sys.modules ya tenia una copia,
          lo cual podia producir dos clases EventType incompatibles dentro del mismo proceso segun
          el orden de coleccion de tests. Esta utilidad centraliza la carga bajo una unica guarda
          idempotente: si "src.core.events"/"src.core.event_bus" ya existen en sys.modules, se
          reutilizan tal cual; si no existen, se cargan una sola vez por archivo y se fijan bajo
          su nombre canonico. Nunca reemplaza una entrada ya presente en sys.modules.
@AI_CONTEXT: Llamar a ensure_core_event_modules() es seguro desde cualquier archivo de test, en
             cualquier orden de coleccion, y cualquier numero de veces -- el resultado siempre
             apunta a la misma identidad de clase dentro de un mismo proceso.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType
from typing import NamedTuple

_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_EVENTS_MODULE_NAME = "src.core.events"
_EVENT_BUS_MODULE_NAME = "src.core.event_bus"


class CoreEventModules(NamedTuple):
    events_module: ModuleType
    event_bus_module: ModuleType
    EventType: type
    OttoEventBus: type


def _load_module_from_file_once(module_name: str, relative_path: str) -> ModuleType:
    """Carga module_name desde relative_path SOLO si no esta ya en sys.modules.

    Si ya existe, retorna la entrada existente sin volver a ejecutar el archivo
    (evita la doble-ejecucion que produce clases EventType/OttoEventBus
    incompatibles entre si)."""
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    file_path = os.path.join(_CODE_ROOT, *relative_path.split("/"))
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def ensure_core_event_modules() -> CoreEventModules:
    """Punto de entrada unico: garantiza que src.core.events y src.core.event_bus
    esten cargados exactamente una vez por proceso, y retorna sus clases.

    Idempotente: llamar repetidas veces, desde cualquier archivo de test y en
    cualquier orden de coleccion, siempre retorna la misma identidad de clase."""
    events_module = _load_module_from_file_once(_EVENTS_MODULE_NAME, "src/core/events.py")
    event_bus_module = _load_module_from_file_once(_EVENT_BUS_MODULE_NAME, "src/core/event_bus.py")
    return CoreEventModules(
        events_module=events_module,
        event_bus_module=event_bus_module,
        EventType=events_module.EventType,
        OttoEventBus=event_bus_module.OttoEventBus,
    )


# Modulos productivos que jamas deben eliminarse de sys.modules durante una
# purga de aislamiento de tests: hacerlo rompe la identidad canonica de
# EventType/OttoEventBus para el resto del proceso de pytest.
#
# "src" y "src.core" (los PAQUETES contenedores, no sus demas submodulos) se
# incluyen aqui por una razon estructural: si se elimina sys.modules["src"] o
# sys.modules["src.core"] mientras se preservan sys.modules["src.core.events"]
# y sys.modules["src.core.event_bus"], el siguiente "import src.core.algo"
# vuelve a ejecutar src/core/__init__.py desde cero (porque el paquete padre
# ya no esta cacheado), lo cual reimporta tour_orchestrator.py y, con el, una
# copia nueva de "from .events import EventType" -- exactamente el defecto
# que esta utilidad existe para prevenir. Preservar los paquetes contenedores
# no impide que main.py ni el resto de src.* se reimporten frescos: solo fija
# el nodo del arbol de paquetes por el que ya pasa la identidad canonica.
PRESERVED_CORE_IDENTITY_MODULES = frozenset(
    {
        "src",
        "src.core",
        _EVENTS_MODULE_NAME,
        _EVENT_BUS_MODULE_NAME,
        "src.core.tour_orchestrator",
    }
)


__all__ = [
    "CoreEventModules",
    "ensure_core_event_modules",
    "PRESERVED_CORE_IDENTITY_MODULES",
]
