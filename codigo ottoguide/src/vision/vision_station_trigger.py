"""
@TASK: Adaptar VisionProcessor al contrato StationTriggerPort (U2)
@INPUT: Una instancia ya construida de VisionProcessor (camara compartida)
@OUTPUT: VisionStationTrigger, implementacion concreta de StationTriggerPort definido en U1
@CONTEXT: U2 — Integracion del sensor QR de estaciones. Este adaptador no abre ni cierra
          la camara: VisionProcessor conserva la propiedad exclusiva del VideoCapture.
@SECURITY: No importa hardware, navegacion, conversacion ni movimiento. Puramente
           observacional, igual que el contrato StationTriggerPort que implementa.
"""
from __future__ import annotations

from src.vision.station_trigger import (
    QRStationDetected,
    StationTriggerHealth,
    StationTriggerState,
)
from src.vision.vision_processor import QR_DETECTION_SOURCE, VisionProcessor


class StationTriggerUnavailableError(Exception):
    """El sensor de estaciones QR no esta disponible para iniciar o consultar."""


class VisionStationTrigger:
    """
    @TASK: Exponer VisionProcessor como StationTriggerPort sin tomar propiedad de la camara
    @CONTEXT: start() es idempotente; stop() nunca cierra VisionProcessor; close() es terminal.
    """

    def __init__(self, vision_processor: VisionProcessor) -> None:
        self._vision_processor: VisionProcessor = vision_processor
        self._state: StationTriggerState = StationTriggerState.NOT_STARTED
        self._last_error: str | None = None

    async def start(self) -> None:
        if self._state in (StationTriggerState.READY, StationTriggerState.STARTING):
            return
        if self._state == StationTriggerState.CLOSED:
            raise StationTriggerUnavailableError("station_trigger_closed_cannot_restart")

        self._state = StationTriggerState.STARTING

        if not self._vision_processor.qr_enabled:
            self._state = StationTriggerState.FAILED
            self._last_error = "qr_lane_not_configured"
            raise StationTriggerUnavailableError(self._last_error)

        if not self._vision_processor.is_started:
            self._state = StationTriggerState.FAILED
            self._last_error = "vision_processor_not_started"
            raise StationTriggerUnavailableError(self._last_error)

        self._state = StationTriggerState.READY
        self._last_error = None

    async def next_detection(self) -> QRStationDetected:
        if self._state != StationTriggerState.READY:
            raise StationTriggerUnavailableError(
                f"next_detection_invalid_in_state:{self._state.value}"
            )
        return await self._vision_processor.get_next_station_detection()

    async def health(self) -> StationTriggerHealth:
        return StationTriggerHealth(
            state=self._state,
            ready=self._state == StationTriggerState.READY,
            source=QR_DETECTION_SOURCE,
            last_error=self._last_error,
        )

    async def stop(self) -> None:
        if self._state == StationTriggerState.CLOSED:
            return
        self._state = StationTriggerState.NOT_STARTED

    async def close(self) -> None:
        self._state = StationTriggerState.CLOSED


__all__ = [
    "StationTriggerUnavailableError",
    "VisionStationTrigger",
]
