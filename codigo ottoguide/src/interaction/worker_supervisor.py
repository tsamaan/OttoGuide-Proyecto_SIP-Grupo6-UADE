"""
@TASK: Definir el contrato canonico del supervisor del worker de interaccion real (U1)
@INPUT: Sin dependencias externas — solo biblioteca estandar
@OUTPUT: Protocol InteractionWorkerSupervisor y dataclass WorkerTermination
@CONTEXT: U1 — Unificacion de OttoGuide. Este modulo declara el contrato del
          componente que en una etapa futura (U3) sera responsable de administrar
          el ciclo de vida de un worker dedicado de interaccion real. No crea
          procesos, hilos, sockets ni ningun transporte IPC.
@SECURITY: Modulo importable sin subprocess, multiprocessing, sockets ni el SDK
           de Unitree instalados. Cero efectos de lado.
@AI_CONTEXT: Una implementacion futura de este Protocol sera responsable de:
             crear exactamente un worker; verificar su readiness antes de
             declararlo disponible; aplicar un timeout de arranque; detectar
             salida inesperada; aplicar un timeout de apagado; detener el worker
             durante una emergencia; impedir su respawn durante EMERGENCY;
             registrar exit code y causa de terminacion; cerrar el transporte de
             forma deterministica; nunca construir comandos de shell con texto
             proveniente del usuario; y nunca degradar silenciosamente en modo
             real. Ninguna de esas responsabilidades se implementa en U1. La
             eleccion de transporte (JSONL, stdin/stdout, socket Unix, TCP, pipe
             nombrado, memoria compartida) y de tecnologia del worker (Python,
             C++) queda deliberadamente sin decidir en esta etapa.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.interaction.runtime_port import InteractionRuntimePort


@dataclass(frozen=True, slots=True)
class WorkerTermination:
    exit_code: int | None
    reason: str
    unexpected: bool
    occurred_at_monotonic_s: float

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must not be empty")
        if self.occurred_at_monotonic_s < 0:
            raise ValueError("occurred_at_monotonic_s must not be negative")


@runtime_checkable
class InteractionWorkerSupervisor(InteractionRuntimePort, Protocol):
    """
    @TASK: Declarar el contrato del supervisor de ciclo de vida del worker real
    @CONTEXT: Extiende InteractionRuntimePort agregando unicamente observabilidad
              de terminacion. No implementado en U1.
    """

    @property
    def termination(self) -> WorkerTermination | None:
        ...


__all__ = [
    "InteractionWorkerSupervisor",
    "WorkerTermination",
]
