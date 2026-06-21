"""
@TASK: Definir modelos puros de dominio de navegacion, sin dependencias de ROS 2
@INPUT: Sin dependencias externas — cero imports de rclpy, cv2 o el cliente de simple commander
@OUTPUT: NavWaypoint y NavigationStatus, consumidos por NavigationPort y el bridge Nav2 legacy
@CONTEXT: Extraido de src/navigation/nav2_bridge.py en Fase 2H.0 para permitir que
          NavigationPort (contrato abstracto) y TourOrchestrator dependan de tipos de
          dominio sin importar transitivamente rclpy/cv2/el SDK de simple commander.
@SECURITY: Este modulo debe permanecer importable sin ROS 2 instalado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class NavWaypoint:
    """
    @TASK: Representar un waypoint de navegacion en el frame del mapa de forma inmutable
    @INPUT: Coordenadas x, y en metros y yaw en radianes relativas al origen del mapa; frame opcional
    @OUTPUT: Estructura inmutable consumible por AsyncNav2Bridge.navigate_to_waypoints y send_goal
    @CONTEXT: Tipo de dominio interno del bridge; independiente de PoseStamped de ROS 2.
              Equivalente a Waypoint en NavigationManager; separado por clean architecture.
    @SECURITY: frozen=True evita mutacion accidental de coordenadas durante la ejecucion del plan.

    STEP 1: Capturar posicion 2D y orientacion yaw del plan de ruta del TourOrchestrator
    STEP 2: Permitir override del frame_id para casos multi-mapa o frames de odometria
    """

    x: float
    y: float
    yaw_rad: float
    frame_id: str = "map"


@dataclass(slots=True)
class NavigationStatus:
    """
    @TASK: Encapsular el estado observable de la tarea de navegacion activa en el bridge
    @INPUT: Indicadores de tarea activa, resultado del ultimo plan y waypoint activo actual
    @OUTPUT: Snapshot del estado compartido entre el hilo ROS 2 y las corrutinas async
    @CONTEXT: Estado mutable compartido; acceso protegido por asyncio.Lock en el bridge.
              No usar directamente; consultado via propiedades y metodos protegidos del bridge.
    @SECURITY: Acceso siempre protegido por _status_lock (asyncio.Lock) para evitar race conditions
               entre el hilo de spin ROS 2 y las corrutinas de asyncio.

    STEP 1: Registrar si hay una tarea Nav2 activa y resultado del ultimo plan ejecutado
    STEP 2: Mantener indice del waypoint activo para observabilidad y telemetria
    """

    task_active: bool = False
    last_result_succeeded: Optional[bool] = None
    active_waypoint_index: int = 0


__all__ = [
    "NavWaypoint",
    "NavigationStatus",
]
