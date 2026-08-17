"""
@TASK: Coordinar el consumo de StationTriggerPort y su publicacion en OttoEventBus (U2)
@INPUT: Una instancia de StationTriggerPort ya construida y una instancia de OttoEventBus
@OUTPUT: StationTriggerCoordinator — crea una unica task consumidora que traduce
         QRStationDetected en EventType.QR_STATION_DETECTED
@CONTEXT: U2 — Integracion del sensor QR de estaciones. Este coordinador es la unica
          frontera entre el sensor observacional y el bus de eventos; no decide que
          hacer con la deteccion, eso es responsabilidad de TourOrchestrator.
@SECURITY: No crea threads ni procesos; no abre camara; no mueve el robot; no cambia
           la FSM; no inicia interaccion ni reproduce audio.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.core.event_bus import OttoEventBus
from src.core.events import EventType
from src.vision.station_trigger import StationTriggerPort

LOGGER = logging.getLogger(__name__)


class StationTriggerCoordinator:
    """
    @TASK: Consumir StationTriggerPort.next_detection() y publicar QR_STATION_DETECTED
    @CONTEXT: start()/stop()/close() son idempotentes. Un fallo no cancelatorio del
              provider detiene el loop sin reiniciarlo silenciosamente.
    """

    def __init__(
        self,
        station_trigger: StationTriggerPort,
        event_bus: OttoEventBus,
    ) -> None:
        self._station_trigger: StationTriggerPort = station_trigger
        self._event_bus: OttoEventBus = event_bus
        self._task: Optional[asyncio.Task[None]] = None
        self._last_error: Optional[str] = None
        self._closed: bool = False

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("station_trigger_coordinator_closed_cannot_restart")
        if self._task is not None and not self._task.done():
            return

        await self._station_trigger.start()
        self._task = asyncio.create_task(
            self._consume_loop(),
            name="station-trigger-coordinator-consume-loop",
        )

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def close(self) -> None:
        if self._closed:
            return
        await self.stop()
        try:
            await self._station_trigger.close()
        except Exception as exc:
            LOGGER.warning(
                "[StationTriggerCoordinator] Fallo al cerrar StationTriggerPort: %s", exc
            )
        self._closed = True

    async def _consume_loop(self) -> None:
        LOGGER.info("[StationTriggerCoordinator] Loop de consumo iniciado.")
        try:
            while True:
                try:
                    detection = await self._station_trigger.next_detection()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    LOGGER.error(
                        "[StationTriggerCoordinator] next_detection() fallo; "
                        "deteniendo el loop sin fallback. error=%s",
                        self._last_error,
                    )
                    return

                await self._event_bus.publish(EventType.QR_STATION_DETECTED, detection)
        except asyncio.CancelledError:
            LOGGER.info("[StationTriggerCoordinator] Loop de consumo cancelado.")
            raise


__all__ = ["StationTriggerCoordinator"]
