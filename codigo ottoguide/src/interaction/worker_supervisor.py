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

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.interaction.runtime_port import InteractionRuntimePort


@dataclass(frozen=True, slots=True)
class WorkerTermination:
    exit_code: int | None
    reason: str
    unexpected: bool
    occurred_at_monotonic_s: float
    protocol_error_code: str | None = None
    stderr_tail: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise ValueError("exit_code must be int or None")
        if type(self.unexpected) is not bool:
            raise ValueError("unexpected must be bool")
        if type(self.reason) is not str or not self.reason:
            raise ValueError("reason must not be empty")
        if len(self.reason) > 512:
            raise ValueError("reason is too long")
        if (
            type(self.occurred_at_monotonic_s) not in (int, float)
            or not math.isfinite(float(self.occurred_at_monotonic_s))
            or self.occurred_at_monotonic_s < 0
        ):
            raise ValueError("occurred_at_monotonic_s must not be negative")
        if self.protocol_error_code is not None and (
            type(self.protocol_error_code) is not str or not self.protocol_error_code
        ):
            raise ValueError("protocol_error_code must be a non-empty string when provided")
        if type(self.stderr_tail) is not tuple:
            object.__setattr__(self, "stderr_tail", tuple(self.stderr_tail))
        if len(self.stderr_tail) > 50:
            raise ValueError("stderr_tail has too many lines")
        for line in self.stderr_tail:
            if type(line) is not str:
                raise ValueError("stderr_tail lines must be strings")
            if len(line) > 4096:
                raise ValueError("stderr_tail line is too long")


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
