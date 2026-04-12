"""
@TASK: Proveer adaptador de hardware mock para demo local/offline sin DDS ni Unitree SDK.
@INPUT: MotionCommand y contratos del RobotHardwareInterface.
@OUTPUT: Implementacion asincrona de exito inmediato para initialize/stand/move/damp/emergency_stop.
@CONTEXT: Usado en ROBOT_MODE=mock|demo para demostraciones en PC comun sin robot fisico.
@SECURITY: Cero imports de unitree_sdk2py y cero llamadas de red a 192.168.123.161.

STEP 1: Mantener estado interno minimo (_state, _position) para observabilidad.
STEP 2: Devolver exito inmediato en metodos async criticos (sin sleeps bloqueantes).
STEP 3: Exponer compatibilidad retroactiva mediante MockRobotAdapter.
"""

from __future__ import annotations

import logging
import math

from .interface import MotionCommand, RobotHardwareInterface

LOGGER = logging.getLogger("otto_guide.hardware.mock_adapter")


class MockHardwareAPI(RobotHardwareInterface):
    """
    @TASK: Implementar API de hardware mock con retorno asincrono inmediato.
    @INPUT: Comandos de movimiento/seguridad del orquestador.
    @OUTPUT: Estado local actualizado sin dependencias externas.
    @CONTEXT: Entorno demo local para pipeline de interaccion RC1_LOCKED.
    @SECURITY: No invoca DDS, no abre sockets, no toca hardware fisico.
    """

    def __init__(self) -> None:
        """
        @TASK: Inicializar estado interno minimo del adaptador mock.
        @INPUT: Sin parametros.
        @OUTPUT: _state='IDLE' y posicion inicial en origen.
        @CONTEXT: Estado mutable usado por get_state() para dashboard/status.
        @SECURITY: Solo memoria local del proceso.
        """
        self._state: str = "IDLE"
        self._position: dict[str, float] = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        LOGGER.info("[MOCK] MockHardwareAPI creado.")

    async def initialize(self) -> None:
        """
        @TASK: Simular inicializacion de hardware con exito inmediato.
        @INPUT: Sin parametros.
        @OUTPUT: _state='initialized'.
        @CONTEXT: Invocado desde lifespan() en main.py.
        @SECURITY: Sin I/O externo ni dependencias del host robotico.
        """
        self._state = "initialized"
        LOGGER.info("[MOCK] initialize() -> state='%s'", self._state)

    async def stand(self) -> None:
        """
        @TASK: Simular comando de bipedestacion.
        @INPUT: Sin parametros.
        @OUTPUT: _state='standing'.
        @CONTEXT: Compatible con contrato de RobotHardwareInterface.
        @SECURITY: Sin actuacion fisica.
        """
        self._state = "standing"
        LOGGER.info("[MOCK] stand() -> state='%s'", self._state)

    async def damp(self) -> None:
        """
        @TASK: Simular parada segura amortiguada.
        @INPUT: Sin parametros.
        @OUTPUT: _state='damped'.
        @CONTEXT: Hook de seguridad invocado en shutdown y emergencia.
        @SECURITY: Failsafe local sin efectos laterales en hardware real.
        """
        self._state = "damped"
        LOGGER.info("[MOCK] damp() -> state='%s'", self._state)

    async def move(self, command: MotionCommand) -> None:
        """
        @TASK: Simular movimiento integrando posicion local.
        @INPUT: command.linear_x, command.angular_z, command.duration_ms.
        @OUTPUT: _position actualizada y _state='moving'.
        @CONTEXT: Mantiene trazabilidad visual de comandos en modo demo.

        STEP 1: Calcular dt en segundos.
        STEP 2: Integrar x/y en heading actual.
        STEP 3: Integrar yaw.
        @SECURITY: Solo aritmetica local; no publica comandos a bus externo.
        """
        dt = command.duration_ms / 1000.0
        self._position["x"] += command.linear_x * dt * math.cos(self._position["yaw"])
        self._position["y"] += command.linear_x * dt * math.sin(self._position["yaw"])
        self._position["yaw"] += command.angular_z * dt
        self._state = "moving"
        LOGGER.info(
            "[MOCK] move(vx=%.3f,wz=%.3f,dt=%.3f) -> pos=(%.3f,%.3f,yaw=%.3f)",
            command.linear_x,
            command.angular_z,
            dt,
            self._position["x"],
            self._position["y"],
            self._position["yaw"],
        )

    async def get_state(self) -> dict:
        """
        @TASK: Exponer estado del adaptador mock para observabilidad.
        @INPUT: Sin parametros.
        @OUTPUT: Dict serializable con adapter/state/position.
        @CONTEXT: Consumido por endpoints de status y debugging.
        @SECURITY: Solo lectura de memoria local.
        """
        return {
            "adapter": "MockHardwareAPI",
            "state": self._state,
            "position": dict(self._position),
        }

    async def emergency_stop(self) -> None:
        """
        @TASK: Simular parada de emergencia inmediata.
        @INPUT: Sin parametros.
        @OUTPUT: Estado final amortiguado via damp().
        @CONTEXT: Ruta de contingencia en modo demo.
        @SECURITY: No emite comandos externos.
        """
        LOGGER.critical("[MOCK] emergency_stop() invocado")
        await self.damp()


class MockRobotAdapter(MockHardwareAPI):
    """
    @TASK: Mantener compatibilidad retroactiva de nombre para importadores existentes.
    @INPUT: Sin parametros.
    @OUTPUT: Alias funcional de MockHardwareAPI.
    @CONTEXT: Evita romper imports historicos de MockRobotAdapter.
    @SECURITY: Hereda la misma politica offline segura de MockHardwareAPI.
    """


__all__ = ["MockHardwareAPI", "MockRobotAdapter"]
