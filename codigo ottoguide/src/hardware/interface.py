from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MotionCommand:
    # @TASK: Encapsular comando cinematico inmutable
    # @INPUT: linear_x, angular_z, duration_ms
    # @OUTPUT: Objeto de dominio consumible por adaptadores de locomocion
    # @CONTEXT: Contrato compartido entre TourOrchestrator y hardware real/mock
    # @SECURITY: frozen=True impide mutacion despues del despacho
    linear_x: float
    angular_z: float
    duration_ms: int = 0


__all__ = ["MotionCommand"]
