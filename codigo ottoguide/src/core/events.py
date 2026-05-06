"""
@TASK: Definir el catálogo canónico de tipos de eventos del sistema OttoGuide
@INPUT: Sin dependencias externas
@OUTPUT: Enum EventType con todos los eventos del bus intra-proceso
@CONTEXT: Contrato compartido entre publicadores (WakeWordDetector, ConversationManager)
          y suscriptores (TourOrchestrator). Usar siempre EventType.X en lugar de strings
          para evitar errores tipográficos y habilitar análisis estático.
@SECURITY: Sin datos sensibles en el enum; solo identificadores de tipo.
@AI_CONTEXT: Agrupados por dominio (Interacción, Navegación, Sistema) para claridad.
             Nuevos eventos se agregan aquí y quedan disponibles para todo el sistema.

STEP 1: Definir eventos de dominio de Interacción (wake word, NLP, TTS)
STEP 2: Definir eventos de dominio de Navegación (waypoint, tour)
STEP 3: Definir eventos de dominio de Sistema (emergencia, health)
"""
from __future__ import annotations

from enum import Enum, unique


@unique
class EventType(Enum):
    """
    @TASK: Catálogo centralizado de tipos de eventos del bus intra-proceso OttoGuide
    @INPUT: Sin parámetros
    @OUTPUT: Enum con valores string autodocumentados para logging y serialización
    @CONTEXT: Todos los publicadores y suscriptores del OttoEventBus deben referenciar
              este enum. Nunca usar strings raw para tipos de evento.
    @AI_CONTEXT: Los valores string (e.g. "interaction.started") facilitan la serialización
                 en logs JSON y en el payload de telemetría WebSocket.
    """

    # ------------------------------------------------------------------
    # STEP 1: Dominio de Interacción (Capa 3)
    # ------------------------------------------------------------------

    # Publicado por: WakeWordDetector cuando detecta "Hola Otto"
    # Suscripto por: TourOrchestrator para pausar la navegación y cambiar a INTERACTING
    INTERACTION_STARTED = "interaction.started"

    # Publicado por: ConversationManager / TourOrchestrator al completar el pipeline TTS
    # Suscripto por: WakeWordDetector para reactivar la escucha; dashboard para métricas
    INTERACTION_COMPLETED = "interaction.completed"

    # Publicado por: WakeWordDetector ante timeout sin respuesta del usuario
    # Suscripto por: TourOrchestrator para retornar a NAVIGATING sin acción adicional
    INTERACTION_TIMEOUT = "interaction.timeout"

    # ------------------------------------------------------------------
    # STEP 2: Dominio de Navegación (Capa 4)
    # ------------------------------------------------------------------

    # Publicado por: TourOrchestrator al alcanzar un waypoint del plan
    # Suscripto por: ConversationManager para cambiar de zona activa de contenido
    WAYPOINT_REACHED = "navigation.waypoint_reached"

    # Publicado por: TourOrchestrator al completar el plan de tour completo
    # Suscripto por: Sistemas de analytics, dashboard WebSocket
    TOUR_COMPLETED = "navigation.tour_completed"

    # Publicado por: TourOrchestrator al iniciar un nuevo tour
    # Suscripto por: MissionAuditLogger, dashboard
    TOUR_STARTED = "navigation.tour_started"

    # ------------------------------------------------------------------
    # STEP 3: Dominio de Sistema (Capa 1)
    # ------------------------------------------------------------------

    # Publicado por: TourOrchestrator.emergency_stop() o API /emergency
    # Suscripto por: Todos los subsistemas para shutdown coordinado
    EMERGENCY_STOP = "system.emergency_stop"

    # Publicado por: Preflight check o factoryRestClient.con_check()
    # Suscripto por: Dashboard para alertas de conectividad
    FACTORY_UNREACHABLE = "system.factory_unreachable"

    def __str__(self) -> str:
        """Retorna el valor string para serialización en logs y telemetría."""
        return self.value


__all__ = ["EventType"]
