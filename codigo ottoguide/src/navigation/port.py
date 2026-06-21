"""
@TASK: Definir el contrato abstracto NavigationPort para implementaciones de navegacion
@INPUT: Sin dependencias externas — cero imports de rclpy, cv2 o el cliente de simple commander
@OUTPUT: Protocol runtime_checkable consumido por TourOrchestrator y sus implementaciones
@CONTEXT: Fase 2H.0 — Reconciliacion de arquitecturas de navegacion y hardware.
          Este contrato desacopla TourOrchestrator del bridge Nav2 legacy (basado en el cliente
          de simple commander), permitiendo una futura implementacion canonica via
          rclpy.action.ActionClient directo contra /offline_nav/navigate_to_pose y
          /offline_nav/follow_waypoints (Fase 2H.1).
@SECURITY: Este modulo debe permanecer importable sin ROS 2 instalado. No contiene
           implementacion ni efectos de lado; es exclusivamente un contrato de tipos.
"""
from __future__ import annotations

from typing import Protocol, Sequence, TYPE_CHECKING, runtime_checkable

from src.navigation.models import NavWaypoint

if TYPE_CHECKING:
    from src.vision import PoseEstimate


@runtime_checkable
class NavigationPort(Protocol):
    """
    @TASK: Declarar el contrato minimo que cualquier implementacion de navegacion debe cumplir
    @INPUT: Sin parametros de instanciacion en el Protocol
    @OUTPUT: Interfaz estable consumida por TourOrchestrator via inyeccion de dependencias
    @CONTEXT: Implementado actualmente por el bridge Nav2 legacy y por MockNav2Bridge (tests).
              La implementacion canonica futura (Fase 2H.1) sera un cliente ROS 2 directo
              basado en rclpy.action.ActionClient contra las acciones namespaced del sandbox
              offline validado: /offline_nav/navigate_to_pose y /offline_nav/follow_waypoints.
    @SECURITY: runtime_checkable permite isinstance() para verificacion de conformidad
               estructural sin necesidad de herencia explicita.
    """

    async def start(self) -> None:
        ...

    async def close(self) -> None:
        ...

    async def navigate_to_waypoints(
        self,
        waypoints: Sequence[NavWaypoint],
    ) -> bool:
        ...

    async def send_goal(
        self,
        waypoint: NavWaypoint,
    ) -> bool:
        ...

    async def cancel_navigation(self) -> None:
        ...

    async def inject_absolute_pose(
        self,
        pose_estimate: "PoseEstimate",
    ) -> None:
        ...

    async def is_navigation_active(self) -> bool:
        ...


__all__ = [
    "NavigationPort",
]
