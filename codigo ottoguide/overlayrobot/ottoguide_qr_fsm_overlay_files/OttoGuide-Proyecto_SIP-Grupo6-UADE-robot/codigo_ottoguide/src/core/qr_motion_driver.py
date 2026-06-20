from __future__ import annotations

import asyncio
import math
from typing import Optional

from src.hardware.interface import MotionCommand


class QRMotionDriver:
    """
    @TASK: Mantener movimiento del robot para la FSM QR sin bloquear el event loop.
    @CONTEXT: Usa RobotHardwareAPI.move(); si el runtime usa ROS2 cmd_vel, reemplazar esta clase por publisher Twist.
    @SECURITY: stop_loop() siempre envía velocidad cero al finalizar.
    """

    def __init__(
        self,
        *,
        hardware,
        forward_speed_mps: float = 0.12,
        approach_speed_mps: float = 0.06,
        turn_angular_z: float = 0.35,
        move_tick_ms: int = 250,
    ) -> None:
        if move_tick_ms < 50:
            raise ValueError("move_tick_ms debe ser >= 50 ms.")

        self._hardware = hardware
        self._forward_speed_mps = forward_speed_mps
        self._approach_speed_mps = approach_speed_mps
        self._turn_angular_z = abs(turn_angular_z)
        self._move_tick_ms = move_tick_ms
        self._linear_x = 0.0
        self._angular_z = 0.0
        self._enabled = False
        self._task: Optional[asyncio.Task[None]] = None

    async def start_loop(self) -> None:
        """@TASK: Iniciar publicación periódica de movimiento."""
        if self._task is not None and not self._task.done():
            return

        self._task = asyncio.create_task(self._move_loop(), name="qr-motion-loop")

    async def stop_loop(self) -> None:
        """@TASK: Cancelar loop de movimiento y dejar velocidad cero."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        await self.stop_motion()

    async def drive_forward(self) -> None:
        """@TASK: Reanudar marcha normal hacia el frente."""
        self._enabled = True
        self._linear_x = self._forward_speed_mps
        self._angular_z = 0.0

    async def drive_approach(self) -> None:
        """@TASK: Avanzar suavemente durante el delay posterior a QR."""
        self._enabled = True
        self._linear_x = self._approach_speed_mps
        self._angular_z = 0.0

    async def stop_motion(self) -> None:
        """@TASK: Frenar completamente el robot."""
        self._enabled = False
        self._linear_x = 0.0
        self._angular_z = 0.0
        await self._hardware.move(MotionCommand(linear_x=0.0, angular_z=0.0, duration_ms=0))

    async def turn_degrees(self, degrees: float, *, max_duration_s: float = 8.0) -> None:
        """
        @TASK: Girar en el lugar por tiempo estimado.
        @CONTEXT: Ajustar turn_angular_z/max_duration_s en pruebas HIL.
        """
        if abs(degrees) < 1.0:
            return

        await self.stop_motion()

        sign = 1.0 if degrees > 0 else -1.0
        radians = math.radians(abs(degrees))
        duration_s = min(max_duration_s, radians / max(self._turn_angular_z, 0.05))

        await self._hardware.move(
            MotionCommand(
                linear_x=0.0,
                angular_z=sign * self._turn_angular_z,
                duration_ms=int(duration_s * 1000),
            )
        )
        await asyncio.sleep(duration_s)
        await self.stop_motion()

    async def _move_loop(self) -> None:
        """@TASK: Enviar comando de movimiento periódico mientras la marcha está habilitada."""
        tick_s = self._move_tick_ms / 1000.0
        try:
            while True:
                if self._enabled:
                    await self._hardware.move(
                        MotionCommand(
                            linear_x=self._linear_x,
                            angular_z=self._angular_z,
                            duration_ms=self._move_tick_ms,
                        )
                    )
                await asyncio.sleep(tick_s)
        except asyncio.CancelledError:
            raise
