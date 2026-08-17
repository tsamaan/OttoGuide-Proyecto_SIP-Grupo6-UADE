"""
@TASK: Definir ABC RobotHardwareInterface y dataclass MotionCommand
@INPUT: Sin dependencias externas — cero imports de unitree_sdk2py
@OUTPUT: Contrato de interfaz para todos los adaptadores de hardware
@CONTEXT: Capa de abstraccion HIL/SITL; desacopla orquestador de SDK fisico
@SECURITY: frozen=True en MotionCommand previene mutacion post-construccion

STEP 1: Definir MotionCommand como dataclass inmutable
STEP 2: Definir ABC con metodos obligatorios para cualquier adaptador
STEP 3: stop_motion() preserva postura y delega exclusivamente en StopMove
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class MotionCommand:
    """
    @TASK: Encapsular comando cinematico inmutable para locomocion
    @INPUT: linear_x (m/s), angular_z (rad/s), duration_ms (ms)
    @OUTPUT: Objeto inmutable consumido por move()
    @CONTEXT: Unidad atomica de movimiento; validacion de rango en el adaptador
    @SECURITY: frozen=True impide modificacion post-despacho
    """
    linear_x: float
    angular_z: float
    duration_ms: int


class RobotHardwareInterface(abc.ABC):
    """
    @TASK: Contrato ABC para adaptadores de hardware del robot
    @INPUT: Sin parametros de instanciacion en el ABC
    @OUTPUT: Interfaz estable para TourOrchestrator y main.py
    @CONTEXT: Implementado por UnitreeG1Adapter (real) y MockRobotAdapter (mock)
    @SECURITY: Ningun metodo importa unitree_sdk2py; el ABC es SDK-agnostico
    """

    @abc.abstractmethod
    async def initialize(self) -> None:
        """
        @TASK: Inicializar el adaptador de hardware
        @INPUT: Sin parametros
        @OUTPUT: Hardware listo para recibir comandos
        @CONTEXT: Invocado una sola vez en el lifespan de FastAPI
        @SECURITY: Puede ser bloqueante internamente; el caller usa await
        """
        ...

    @abc.abstractmethod
    async def move(self, command: MotionCommand) -> None:
        """
        @TASK: Ejecutar comando de movimiento cinematico
        @INPUT: command — MotionCommand con linear_x, angular_z, duration_ms
        @OUTPUT: Robot en movimiento durante duration_ms
        @CONTEXT: Clamping cinematico aplicado por el adaptador concreto
        @SECURITY: Velocidad maxima operativa 0.3 m/s (clamping obligatorio)
        """
        ...

    @abc.abstractmethod
    async def stop_motion(self) -> None:
        """Detener locomocion preservando la postura.

        Debe ejecutar StopMove exactamente una vez por invocacion. No puede
        ejecutar Damp, Start, StandUp, BalanceStand ni otro cambio postural.
        """
        ...

    @abc.abstractmethod
    async def get_state(self) -> dict:
        """
        @TASK: Obtener estado actual del hardware
        @INPUT: Sin parametros
        @OUTPUT: dict con estado del adaptador (mode, position, etc.)
        @CONTEXT: Consumido por endpoints de observabilidad
        @SECURITY: Solo lectura; sin efectos secundarios
        """
        ...

__all__ = [
    "MotionCommand",
    "RobotHardwareInterface",
]
