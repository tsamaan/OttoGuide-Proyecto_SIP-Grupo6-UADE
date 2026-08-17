"""
@TASK: Definir el contrato canonico del sensor de estaciones por QR (U1)
@INPUT: Sin dependencias externas — solo biblioteca estandar
@OUTPUT: Protocol StationTriggerPort, modelos QRStationDetected y
         StationTriggerHealth, y enum StationTriggerState
@CONTEXT: U1 — Unificacion de OttoGuide. Este modulo declara el contrato de un
          futuro sensor de estaciones (U2) que observara codigos QR y emitira
          detecciones. El sensor es puramente observacional: no decide que
          hacer con una estacion detectada, no mueve el robot, no cambia la FSM
          y no inicia interaccion, LLM o audio. Esas decisiones permanecen en
          TourOrchestrator.
@SECURITY: Modulo importable sin cv2, numpy, pyrealsense, rclpy ni acceso a
           camara. Cero efectos de lado.
@AI_CONTEXT: Invariantes contractuales de StationTriggerPort:
             - es observacion pura;
             - no mueve el robot;
             - no publica MotionCommand;
             - no cambia la FSM;
             - no inicia interaccion;
             - no inicia el LLM;
             - no reproduce audio;
             - no finaliza el tour;
             - no abre una camara dentro de este contrato;
             - no decide que hacer con una estacion detectada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class StationTriggerState(str, Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class QRStationDetected:
    station_id: str
    qr_value: str
    detected_at: datetime
    confidence_or_stability: float
    source: str

    def __post_init__(self) -> None:
        if not self.station_id:
            raise ValueError("station_id must not be empty")
        if not self.qr_value:
            raise ValueError("qr_value must not be empty")
        if not self.source:
            raise ValueError("source must not be empty")
        if self.detected_at.tzinfo is None:
            raise ValueError("detected_at must be timezone-aware")
        if not (0.0 <= self.confidence_or_stability <= 1.0):
            raise ValueError("confidence_or_stability must be within 0.0..1.0")


@dataclass(frozen=True, slots=True)
class StationTriggerHealth:
    state: StationTriggerState
    ready: bool
    source: str
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("source must not be empty")
        if self.last_error is not None and not self.last_error:
            raise ValueError("last_error must not be empty when provided")


@runtime_checkable
class StationTriggerPort(Protocol):
    """
    @TASK: Declarar el contrato minimo de un sensor de estaciones por QR
    @CONTEXT: Implementado en el futuro (U2) por un detector real. No
              implementado en U1.
    @AI_CONTEXT: Ver invariantes contractuales en el docstring del modulo.
    """

    async def start(self) -> None:
        ...

    async def next_detection(self) -> QRStationDetected:
        ...

    async def health(self) -> StationTriggerHealth:
        ...

    async def stop(self) -> None:
        ...

    async def close(self) -> None:
        ...


__all__ = [
    "QRStationDetected",
    "StationTriggerHealth",
    "StationTriggerPort",
    "StationTriggerState",
]
