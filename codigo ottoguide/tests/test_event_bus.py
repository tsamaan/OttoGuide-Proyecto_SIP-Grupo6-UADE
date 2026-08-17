"""
@TASK: Test de smoke para el EventBus — verifica suscripción, publicación y despacho correcto
@INPUT: Sin dependencias de hardware; usa únicamente asyncio y los módulos de src/core/
@OUTPUT: Resultado de pytest: PASSED si el bus funciona correctamente; FAILED si hay regresión
@CONTEXT: Tests locales de integración rápida (sin mocks de hardware).
          Ejecutar con: python -m pytest tests/test_event_bus.py -v
@SECURITY: Sin I/O de red ni hardware; completamente aislado.
@AI_CONTEXT: Resetea OttoEventBus._instance entre tests para aislamiento correcto.
             Los módulos ROS2 (rclpy, nav2_msgs) no están disponibles en Windows/CI;
             se stubs-ean antes de cualquier import de src.core para evitar ImportError.
             U2R2: events.py/event_bus.py se cargan via tests.support.core_module_identity,
             que garantiza una unica identidad canonica de EventType/OttoEventBus por proceso
             de pytest (nunca reemplaza una entrada ya presente en sys.modules).
"""
from __future__ import annotations

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Asegurar que el path raíz del proyecto está en sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Stub de módulos ROS2 y dependencias Linux-only ANTES de cualquier import
# ---------------------------------------------------------------------------
# @AI_CONTEXT: rclpy, nav2_msgs, etc. solo existen en el entorno Linux del robot.
#              MagicMock() actúa como módulo vacío para prevenir ImportError.
#              Se inyectan ANTES de importar cualquier módulo de src/ que dependa de ellos.
def _make_package_mock(name: str) -> MagicMock:
    """Crear un MagicMock que se comporta como un package (tiene __path__)."""
    mock = MagicMock()
    mock.__name__ = name
    mock.__path__ = []
    mock.__package__ = name
    mock.__spec__ = None
    return mock


_ROS2_STUBS = [
    "rclpy", "rclpy.node", "rclpy.action", "rclpy.action.client",
    "rclpy.executors", "rclpy.callback_groups", "rclpy.qos",
    "nav2_msgs", "nav2_msgs.action",
    "geometry_msgs", "geometry_msgs.msg",
    "tf2_ros", "tf2_ros.buffer", "tf2_ros.transform_listener",
    "action_msgs", "action_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "std_msgs", "std_msgs.msg",
]

for _mod_name in _ROS2_STUBS:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _make_package_mock(_mod_name)

# ---------------------------------------------------------------------------
# Imports de los módulos bajo prueba (post-stub)
# @AI_CONTEXT: tests.support.core_module_identity evita que src.core.__init__ cargue
#              tour_orchestrator → navigation → rclpy, y garantiza que si otro archivo
#              de test del mismo proceso de pytest ya cargo events.py/event_bus.py,
#              se reutiliza esa misma identidad de clase en vez de re-ejecutar el archivo.
# ---------------------------------------------------------------------------
from tests.support.core_module_identity import ensure_core_event_modules  # noqa: E402

_core_modules = ensure_core_event_modules()
EventType = _core_modules.EventType
OttoEventBus = _core_modules.OttoEventBus


# ---------------------------------------------------------------------------
# Fixture de aislamiento
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_event_bus():
    """Resetear el Singleton entre cada test para aislamiento."""
    OttoEventBus.reset_for_testing()
    yield
    OttoEventBus.reset_for_testing()


# ---------------------------------------------------------------------------
# Test 1: Singleton
# ---------------------------------------------------------------------------

def test_singleton_returns_same_instance():
    """get_instance() debe retornar siempre la misma instancia."""
    bus1 = OttoEventBus.get_instance()
    bus2 = OttoEventBus.get_instance()
    assert bus1 is bus2, "OttoEventBus debe ser un Singleton"


# ---------------------------------------------------------------------------
# Test 2: subscribe + publish básico
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscribe_and_publish():
    """Un callback suscripto debe recibir el evento publicado."""
    bus = OttoEventBus.get_instance()
    received: list[tuple] = []

    async def handler(event_type, data):
        received.append((event_type, data))

    bus.subscribe(EventType.INTERACTION_STARTED, handler)
    await bus.publish(EventType.INTERACTION_STARTED, data={"transcript": "hola otto"})

    assert len(received) == 1
    assert received[0][0] == EventType.INTERACTION_STARTED
    assert received[0][1] == {"transcript": "hola otto"}


# ---------------------------------------------------------------------------
# Test 3: Sin suscriptores — no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_without_subscribers_is_noop():
    """Publicar a un evento sin suscriptores no debe lanzar excepción."""
    bus = OttoEventBus.get_instance()
    await bus.publish(EventType.TOUR_COMPLETED, data=None)


# ---------------------------------------------------------------------------
# Test 4: Múltiples suscriptores
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_subscribers_all_called():
    """Todos los callbacks suscriptos deben recibir el evento."""
    bus = OttoEventBus.get_instance()
    results: list[str] = []

    async def handler_a(event_type, data):
        results.append("A")

    async def handler_b(event_type, data):
        results.append("B")

    bus.subscribe(EventType.INTERACTION_STARTED, handler_a)
    bus.subscribe(EventType.INTERACTION_STARTED, handler_b)
    await bus.publish(EventType.INTERACTION_STARTED, data={})

    assert "A" in results and "B" in results and len(results) == 2


# ---------------------------------------------------------------------------
# Test 5: unsubscribe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsubscribe_removes_callback():
    """Un callback desuscripto no debe recibir eventos posteriores."""
    bus = OttoEventBus.get_instance()
    received: list[bool] = []

    async def handler(event_type, data):
        received.append(True)

    bus.subscribe(EventType.INTERACTION_STARTED, handler)
    bus.unsubscribe(EventType.INTERACTION_STARTED, handler)
    await bus.publish(EventType.INTERACTION_STARTED, data={})

    assert len(received) == 0, "El handler desuscripto no debe ser llamado"


# ---------------------------------------------------------------------------
# Test 6: Excepción en callback no rompe los demás
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_faulty_callback_does_not_block_others():
    """Una excepción en un callback no debe impedir la ejecución de los demás."""
    bus = OttoEventBus.get_instance()
    results: list[str] = []

    async def faulty_handler(event_type, data):
        raise RuntimeError("Fallo intencional en test")

    async def good_handler(event_type, data):
        results.append("ok")

    bus.subscribe(EventType.INTERACTION_STARTED, faulty_handler)
    bus.subscribe(EventType.INTERACTION_STARTED, good_handler)

    await bus.publish(EventType.INTERACTION_STARTED, data={})

    assert "ok" in results, "El callback bueno debe ejecutarse aunque el primero falle"


# ---------------------------------------------------------------------------
# Test 7: Tipos de evento aislados
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_isolation():
    """Un suscriptor de INTERACTION_STARTED no debe recibir TOUR_COMPLETED."""
    bus = OttoEventBus.get_instance()
    received: list = []

    async def handler(event_type, data):
        received.append(event_type)

    bus.subscribe(EventType.INTERACTION_STARTED, handler)
    await bus.publish(EventType.TOUR_COMPLETED, data={})

    assert len(received) == 0, "TOUR_COMPLETED no debe llegar al suscriptor de INTERACTION_STARTED"


# ---------------------------------------------------------------------------
# Test 8: publish_fire_and_forget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_and_forget():
    """publish_fire_and_forget debe despachar el evento aunque sea llamado sincrónicamente."""
    bus = OttoEventBus.get_instance()
    received: list[bool] = []

    async def handler(event_type, data):
        received.append(True)

    bus.subscribe(EventType.EMERGENCY_STOP, handler)
    bus.publish_fire_and_forget(EventType.EMERGENCY_STOP, data={"reason": "test"})

    # Ceder el event loop para que la Task se ejecute
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(received) == 1, "fire_and_forget debe ejecutar el callback en el event loop"


# ---------------------------------------------------------------------------
# Test 9: EventType enum tiene valores únicos
# ---------------------------------------------------------------------------

def test_event_type_values_are_unique():
    """Todos los miembros del enum deben tener valores únicos."""
    values = [e.value for e in EventType]
    assert len(values) == len(set(values)), "EventType tiene valores duplicados"


# ---------------------------------------------------------------------------
# Test 10: Integración con TourOrchestrator — verificar suscripción
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrator_subscribes_on_init():
    """
    TourOrchestrator debe suscribirse a INTERACTION_STARTED en su constructor.
    Verifica la suscripción sin instanciar hardware real (todos los subsistemas son mocks).
    ROS2 ya está mockeado en sys.modules al inicio del módulo de test.
    """
    # Importar tour_orchestrator directamente (rclpy ya está stub-eado)
    from src.core.tour_orchestrator import TourOrchestrator
    import src.core.tour_orchestrator as tour_orchestrator_module

    # U2R2: confirmar que el modulo ya cargado (events/event_bus, sea cual sea
    # el orden de coleccion) es la MISMA identidad de clase que usa este test
    # y la que tour_orchestrator efectivamente importo.
    assert sys.modules["src.core.events"].EventType is EventType
    assert sys.modules["src.core.event_bus"].OttoEventBus is OttoEventBus
    assert tour_orchestrator_module.EventType is EventType

    # Mocks mínimos para el constructor
    mock_hw = MagicMock()
    mock_hw.stop_motion = AsyncMock()
    mock_hw.move = AsyncMock()
    mock_hw.get_state = AsyncMock(return_value={"battery_level": 100.0})

    mock_nav = MagicMock()
    mock_nav.cancel_navigation = AsyncMock()
    mock_nav.navigate_to_waypoints = AsyncMock(return_value=True)

    mock_cm = MagicMock()
    mock_cm.get_waypoint_interaction_type = MagicMock(return_value="free")
    mock_cm.set_active_zone = MagicMock()
    mock_cm.process_interaction = AsyncMock()

    mock_vp = MagicMock()
    mock_vp.close = MagicMock()
    mock_vp.get_next_estimate = AsyncMock(return_value=None)

    # Bus fresco para este test (no usa el Singleton global)
    test_bus = OttoEventBus()

    orchestrator = TourOrchestrator(
        hardware_api=mock_hw,
        nav_bridge=mock_nav,
        conversation_manager=mock_cm,
        vision_processor=mock_vp,
        robot_mode="mock",
        event_bus=test_bus,
    )

    # Verificar que hay exactamente 1 suscriptor en INTERACTION_STARTED
    subs = test_bus._subscribers.get(EventType.INTERACTION_STARTED, [])
    assert len(subs) == 1, (
        f"TourOrchestrator debe registrar 1 suscriptor en INTERACTION_STARTED; "
        f"encontrados: {len(subs)}"
    )
    # Verificar nombre del método suscripto
    assert hasattr(subs[0], "__func__"), "El suscriptor debe ser un método bound"
    assert subs[0].__func__.__name__ == "_on_interaction_started", (
        f"Nombre de método inesperado: {subs[0].__func__.__name__}"
    )

    # U2R2: verificar que hay exactamente 1 suscriptor en QR_STATION_DETECTED,
    # usando el mismo enum canonico (sin copia distinta del EventType).
    qr_subs = test_bus._subscribers.get(EventType.QR_STATION_DETECTED, [])
    assert len(qr_subs) == 1, (
        f"TourOrchestrator debe registrar 1 suscriptor en QR_STATION_DETECTED; "
        f"encontrados: {len(qr_subs)}"
    )
    assert hasattr(qr_subs[0], "__func__"), "El suscriptor QR debe ser un método bound"
    assert qr_subs[0].__func__.__name__ == "_on_qr_station_detected", (
        f"Nombre de método inesperado: {qr_subs[0].__func__.__name__}"
    )
