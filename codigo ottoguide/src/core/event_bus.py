"""
@TASK: Implementar bus de mensajería asíncrono (patrón Observer) como Singleton del proceso
@INPUT: Suscripciones de callbacks async via subscribe(); publicaciones via publish()
@OUTPUT: Despacho concurrente de todos los callbacks registrados para un tipo de evento dado
@CONTEXT: Capa de mensajería interna entre subsistemas desacoplados (Interacción ↔ Orquestación).
          Permite que WakeWordDetector notifique a TourOrchestrator sin acoplamiento directo.
          No usa broker externo (Redis, RabbitMQ) — está diseñado para comunicación intra-proceso
          en un único asyncio event loop (uvicorn con un solo worker).
@SECURITY: Los callbacks son funciones internas del proceso; sin serialización ni red.
           Los callbacks que lanzan excepciones se aíslan con logging.error sin propagar al publicador.
@PERFORMANCE: publish() crea un asyncio.Task por callback (gather concurrente sin bloquear al publicador).
              Para eventos de alta frecuencia con muchos suscriptores, considerar un canal dedicado.
@AI_CONTEXT: Singleton implementado con _instance de clase + asyncio.Lock para thread-safety
             en entornos donde múltiples coroutines pudieran intentar get_instance() concurrentemente.
             El lock se crea lazily para evitar problemas de event loop en import time.

STEP 1: Definir OttoEventBus con registro interno de suscriptores por EventType
STEP 2: Implementar subscribe() — registra un callable async por tipo de evento
STEP 3: Implementar unsubscribe() — elimina un callable del registro
STEP 4: Implementar publish() — despacha el evento a todos los suscriptores con gather()
STEP 5: Implementar get_instance() como factory de Singleton thread-safe
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine, Optional

from .events import EventType

LOGGER = logging.getLogger(__name__)

# Tipo alias para callbacks asincrónicos de eventos
AsyncEventCallback = Callable[[EventType, Any], Coroutine[Any, Any, None]]


class OttoEventBus:
    """
    @TASK: Bus de mensajería intra-proceso async para desacoplar subsistemas de OttoGuide
    @INPUT: Callbacks async registrados via subscribe(); datos de eventos via publish()
    @OUTPUT: Todos los callbacks del tipo correspondiente invocados concurrentemente ante publish()
    @CONTEXT: Singleton; una sola instancia por proceso. Acceder via OttoEventBus.get_instance().
              Diseñado para el event loop único de uvicorn (single-worker FastAPI).
              Reemplaza el acoplamiento directo entre WakeWordDetector y TourOrchestrator.
    @SECURITY: Los callbacks se ejecutan en el event loop del proceso; sin I/O externo ni red.
               Excepciones en callbacks se loguean y absorben; no propagan al publicador.
    @PERFORMANCE: asyncio.gather() ejecuta todos los callbacks del evento concurrentemente.
                  Callbacks lentos no bloquean el loop principal (son Tasks separadas).
    @AI_CONTEXT: Pattern: Observer con canal tipado (EventType enum). Los suscriptores son
                 coroutines; callbacks síncronos no están soportados (forzar async para consistencia).
    """

    _instance: Optional["OttoEventBus"] = None
    _instance_lock: Optional[asyncio.Lock] = None

    def __init__(self) -> None:
        # STEP 1: Mapa evento → lista de callbacks suscriptos
        # @AI_CONTEXT: defaultdict evita KeyError en publish() para eventos sin suscriptores
        self._subscribers: dict[EventType, list[AsyncEventCallback]] = defaultdict(list)
        LOGGER.info("[OttoEventBus] Instancia inicializada.")

    # ------------------------------------------------------------------
    # STEP 2: Suscripción
    # ------------------------------------------------------------------

    def subscribe(self, event_type: EventType, callback: AsyncEventCallback) -> None:
        """
        @TASK: Registrar un callback async para ser notificado ante un tipo de evento
        @INPUT: event_type — miembro del enum EventType que identifica el evento de interés
                callback — coroutine function con firma (event_type: EventType, data: Any) -> None
        @OUTPUT: callback agregado a la lista de suscriptores del event_type dado
        @CONTEXT: Llamar durante la inicialización de cada suscriptor (p. ej. en __init__ del orchestrator).
                  Un mismo callback puede suscribirse a múltiples EventType con llamadas separadas.
        @SECURITY: No valida contenido del callback; el caller es responsable de proveer una coroutine.
        @AI_CONTEXT: No se verifican duplicados; si se llama subscribe() dos veces con el mismo callback,
                     el callback se ejecutará dos veces por publish(). Usar unsubscribe() para limpiar.
        """
        self._subscribers[event_type].append(callback)
        LOGGER.debug(
            "[OttoEventBus] Suscriptor registrado. event=%s total=%d",
            event_type.name,
            len(self._subscribers[event_type]),
        )

    # ------------------------------------------------------------------
    # STEP 3: Desuscripción
    # ------------------------------------------------------------------

    def unsubscribe(self, event_type: EventType, callback: AsyncEventCallback) -> None:
        """
        @TASK: Eliminar un callback previamente registrado para un tipo de evento
        @INPUT: event_type — tipo de evento del que desuscribirse
                callback — referencia exacta al mismo objeto callback registrado en subscribe()
        @OUTPUT: callback removido de la lista; no-op si el callback no está registrado
        @CONTEXT: Llamar durante el shutdown del suscriptor para evitar memory leaks o callbacks
                  a objetos destruidos en entornos con lifecycle dinámico.
        """
        try:
            self._subscribers[event_type].remove(callback)
            LOGGER.debug(
                "[OttoEventBus] Suscriptor removido. event=%s", event_type.name
            )
        except ValueError:
            LOGGER.debug(
                "[OttoEventBus] unsubscribe: callback no encontrado para event=%s",
                event_type.name,
            )

    # ------------------------------------------------------------------
    # STEP 4: Publicación
    # ------------------------------------------------------------------

    async def publish(self, event_type: EventType, data: Any = None) -> None:
        """
        @TASK: Publicar un evento a todos los suscriptores registrados para ese tipo
        @INPUT: event_type — tipo de evento a publicar
                data — payload opcional con datos del evento (dict, dataclass, None)
        @OUTPUT: Todos los callbacks suscriptos invocados concurrentemente via asyncio.gather()
        @CONTEXT: Fire-and-forget por diseño; el publicador no espera el resultado de los callbacks.
                  La invocación es concurrente (gather) pero dentro del mismo event loop.
        @SECURITY: Excepciones en callbacks individuales se capturan con logging.error
                   y no propagan al publicador. Garantiza que un callback roto no rompe los demás.
        @PERFORMANCE: asyncio.gather() con return_exceptions=True ejecuta todos los callbacks
                      concurrentemente. Para eventos críticos (EMERGENCY_STOP), considerar
                      await individual con timeout estricto.
        @AI_CONTEXT: data=None es válido; los callbacks deben manejar data=None gracefully.
        """
        callbacks = list(self._subscribers.get(event_type, []))
        if not callbacks:
            LOGGER.debug("[OttoEventBus] Evento '%s' publicado sin suscriptores.", event_type.name)
            return

        LOGGER.info(
            "[OttoEventBus] Publicando evento '%s' a %d suscriptor(es).",
            event_type.name,
            len(callbacks),
        )

        # STEP 4.1: Ejecutar todos los callbacks concurrentemente
        # @PERFORMANCE: return_exceptions=True garantiza que un callback que falla
        #               no cancela los restantes.
        results = await asyncio.gather(
            *(cb(event_type, data) for cb in callbacks),
            return_exceptions=True,
        )

        # STEP 4.2: Loguear excepciones individuales sin propagar
        # @SECURITY: Absorción de excepciones es intencional; el publicador no debe manejar
        #            errores de los suscriptores (SRP).
        for cb, result in zip(callbacks, results):
            if isinstance(result, BaseException):
                LOGGER.error(
                    "[OttoEventBus] Callback '%s' falló en evento '%s': %s — %s",
                    getattr(cb, "__qualname__", repr(cb)),
                    event_type.name,
                    type(result).__name__,
                    result,
                )

    def publish_fire_and_forget(self, event_type: EventType, data: Any = None) -> None:
        """
        @TASK: Publicar un evento desde contexto síncrono sin awaitar (fire-and-forget)
        @INPUT: event_type — tipo de evento; data — payload opcional
        @OUTPUT: asyncio.Task creada en el event loop activo; retorno inmediato
        @CONTEXT: Usar cuando el publicador es síncrono y no puede hacer await.
                  Equivale a asyncio.create_task(publish(event_type, data)).
        @SECURITY: Requiere que exista un event loop activo; falla silenciosamente si no hay loop.
        @AI_CONTEXT: Preferir publish() (async) cuando es posible. Este método es el fallback
                     para code paths síncronos que necesitan emitir eventos.
        """
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(
                self.publish(event_type, data),
                name=f"eventbus-publish-{event_type.name.lower()}",
            )
            task.add_done_callback(self._handle_publish_result)
        except RuntimeError:
            LOGGER.warning(
                "[OttoEventBus] publish_fire_and_forget: no hay event loop activo. "
                "Evento '%s' no despachado.",
                event_type.name,
            )

    @staticmethod
    def _handle_publish_result(task: asyncio.Task[None]) -> None:
        """
        @TASK: Absorber silenciosamente excepciones de la Task de publish_fire_and_forget
        @INPUT: task — asyncio.Task completada
        @OUTPUT: LOGGER.error si la tarea falló; sin re-propagación
        @CONTEXT: done_callback registrado en publish_fire_and_forget
        """
        try:
            task.result()
        except Exception as exc:
            LOGGER.error("[OttoEventBus] Fallo en publish Task: %s", exc)

    # ------------------------------------------------------------------
    # STEP 5: Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "OttoEventBus":
        """
        @TASK: Obtener la instancia Singleton del EventBus del proceso
        @INPUT: Sin parámetros
        @OUTPUT: Única instancia de OttoEventBus por proceso; creada lazily en la primera llamada
        @CONTEXT: Usar en todos los puntos de acceso al bus en lugar de instanciar directamente.
                  No requiere await; la instancia se crea sincrónicamente (sin I/O en __init__).
        @SECURITY: Sin locks pesados; la creación inicial en Python (GIL) es suficientemente segura
                   para el patrón de uso del event loop único de uvicorn.
        @AI_CONTEXT: En tests unitarios, resetear _instance = None entre tests para aislamiento.
        """
        if cls._instance is None:
            cls._instance = cls()
            LOGGER.debug("[OttoEventBus] Singleton creado.")
        return cls._instance

    @classmethod
    def reset_for_testing(cls) -> None:
        """
        @TASK: Resetear el Singleton para aislamiento en tests unitarios
        @INPUT: Sin parámetros
        @OUTPUT: _instance = None; próxima llamada a get_instance() crea instancia fresca
        @CONTEXT: SOLO usar en fixtures de tests (pytest). Nunca en código de producción.
        @SECURITY: Destruye todos los suscriptores registrados; operación irreversible.
        """
        cls._instance = None
        LOGGER.debug("[OttoEventBus] Singleton reseteado para testing.")


__all__ = ["OttoEventBus", "AsyncEventCallback"]
