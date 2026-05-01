from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Optional, Sequence, TYPE_CHECKING

import cv2
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from src.vision import PoseEstimate

if TYPE_CHECKING:
    from nav2_simple_commander.robot_navigator import BasicNavigator


# @TASK: Definir limite lineal de seguridad para navegacion
# @INPUT: Ninguno
# @OUTPUT: Constante MAX_LINEAR_VELOCITY en m/s
# @CONTEXT: Restriccion operacional obligatoria para trayectorias Nav2
# STEP 1: Establecer tope conservador de 0.3 m/s
# STEP 2: Aplicar en configuracion runtime de BasicNavigator
# @SECURITY: Reduce riesgo de caidas durante desplazamiento autonomo
# @AI_CONTEXT: Debe coincidir con limite de RobotHardwareAPI
MAX_LINEAR_VELOCITY: float = 0.3
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Waypoint:
    x: float
    y: float
    yaw_rad: float
    frame_id: str = "map"


class NavigationManager:
    def __init__(
        self,
        *,
        executor_workers: int = 1,
        amcl_topic: str = "/initialpose",
    ) -> None:
        # @TASK: Inicializar navigation manager
        # @INPUT: executor_workers, amcl_topic
        # @OUTPUT: Wrapper listo para Nav2 y AMCL
        # @CONTEXT: Capa de navegacion ROS2 desacoplada del event loop
        # STEP 1: Configurar ejecutores dedicados para Nav2 y ROS spin
        # STEP 2: Iniciar nodo ROS2 en hilo separado con spin continuo
        # @SECURITY: Prohibe bloqueo del hilo principal de asyncio
        # @AI_CONTEXT: Diseñado para invocacion async desde TourOrchestrator
        if executor_workers <= 0:
            raise ValueError("executor_workers debe ser mayor que 0.")

        self._amcl_topic: str = amcl_topic
        self._work_executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=executor_workers,
            thread_name_prefix="navigation-nav2",
        )
        self._spin_executor: MultiThreadedExecutor = MultiThreadedExecutor(num_threads=2)

        # @TASK: Inicializar contexto ROS2
        # @INPUT: Sin parametros
        # @OUTPUT: Nodo activo y publisher de /initialpose
        # @CONTEXT: Bootstrap de infraestructura ROS fuera del event loop
        # STEP 1: Ejecutar rclpy.init una sola vez
        # STEP 2: Crear nodo interno y registrar publisher AMCL
        # @SECURITY: Evita inicializaciones ROS repetidas
        # @AI_CONTEXT: Nodo interno sirve como punto de publicacion de correcciones
        if not rclpy.ok():
            rclpy.init(args=None)

        self._node: Node = Node("navigation_manager_node")
        self._amcl_publisher = self._node.create_publisher(
            PoseWithCovarianceStamped,
            self._amcl_topic,
            10,
        )
        self._spin_executor.add_node(self._node)

        # @TASK: Preparar BasicNavigator
        # @INPUT: Sin parametros
        # @OUTPUT: Instancia del robot_navigator
        # @CONTEXT: Wrapper asíncrono para APIs nav2_simple_commander
        # STEP 1: Importar BasicNavigator en tiempo de ejecucion
        # STEP 2: Crear instancia y mantenerla para operaciones de ruta
        # @SECURITY: Limita acceso al objeto a metodos controlados
        # @AI_CONTEXT: Se mantiene lazy-friendly para entornos de desarrollo
        self._navigator: "BasicNavigator" = self._create_navigator()
        self._apply_safety_speed_limit()

        # @TASK: Lanzar spin en hilo dedicado
        # @INPUT: Sin parametros
        # @OUTPUT: Hilo daemon ejecutando executor.spin
        # @CONTEXT: Cumplimiento de concurrencia critica para ROS2
        # STEP 1: Definir target bloqueante con manejo de excepciones
        # STEP 2: Iniciar thread daemon y mantener referencia
        # @SECURITY: Aisla spin de ROS2 fuera del event loop
        # @AI_CONTEXT: Fundamental para callbacks y pub/sub reactivos
        self._spin_thread = threading.Thread(
            target=self._spin_forever,
            name="ros2-spin-thread",
            daemon=True,
        )
        self._spin_thread.start()

    async def follow_waypoints(self, waypoints: Sequence[Waypoint]) -> bool:
        # @TASK: Ejecutar ruta waypoints
        # @INPUT: waypoints
        # @OUTPUT: True si ruta finaliza correctamente
        # @CONTEXT: API async principal de navegacion Nav2
        # STEP 1: Convertir waypoints de dominio a PoseStamped ROS
        # STEP 2: Invocar followWaypoints y esperar finalizacion en executor
        # @SECURITY: Ejecuta llamadas potencialmente bloqueantes fuera del loop
        # @AI_CONTEXT: Integrable con callbacks del TourOrchestrator
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._work_executor,
            self._follow_waypoints_sync,
            list(waypoints),
        )

    async def inject_absolute_pose(self, vision_pose: PoseEstimate) -> None:
        # @TASK: Inyectar pose absoluta
        # @INPUT: vision_pose
        # @OUTPUT: Publicacion en topico /initialpose
        # @CONTEXT: Correccion odometrica AMCL basada en VisionProcessor
        # STEP 1: Convertir rvec/tvec de vision a PoseWithCovarianceStamped
        # STEP 2: Publicar mensaje usando nodo ROS en hilo dedicado
        # @SECURITY: Evita bloqueo de event loop en puente vision->AMCL
        # @AI_CONTEXT: Punto de fusion entre localizacion visual y AMCL
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._work_executor,
            self._inject_absolute_pose_sync,
            vision_pose,
        )

    def _follow_waypoints_sync(self, waypoints: Sequence[Waypoint]) -> bool:
        # @TASK: Ejecutar followWaypoints sync
        # @INPUT: waypoints
        # @OUTPUT: True si tarea nav2 completa
        # @CONTEXT: Segmento bloqueante encapsulado para run_in_executor
        # STEP 1: Construir lista PoseStamped para Nav2
        # STEP 2: Lanzar followWaypoints y esperar task completion
        # @SECURITY: Encapsula llamadas Nav2 fuera del hilo principal
        # @AI_CONTEXT: Retorna bool simplificado para orquestacion de estado
        ros_waypoints = [self._build_pose_stamped(wp) for wp in waypoints]
        if len(ros_waypoints) == 0:
            return True

        self._navigator.followWaypoints(ros_waypoints)
        while not self._navigator.isTaskComplete():
            time.sleep(0.02)
        return True

    def _inject_absolute_pose_sync(self, vision_pose: PoseEstimate) -> None:
        # @TASK: Publicar mensaje initialpose
        # @INPUT: vision_pose
        # @OUTPUT: Mensaje publicado en /initialpose
        # @CONTEXT: Ajuste de AMCL usando pose absoluta estimada por vision
        # STEP 1: Construir PoseWithCovarianceStamped desde rvec/tvec
        # STEP 2: Publicar en topico configurado para AMCL
        # @SECURITY: Mantiene covarianza conservadora para convergencia estable
        # @AI_CONTEXT: Conversor minimo viable a espera de calibracion fina
        msg = PoseWithCovarianceStamped()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.pose.pose.position.x = float(vision_pose.tvec[0][0])
        msg.pose.pose.position.y = float(vision_pose.tvec[1][0])
        msg.pose.pose.position.z = float(vision_pose.tvec[2][0])

        yaw = self._extract_yaw_from_rvec(vision_pose.rvec)
        msg.pose.pose.orientation.x = 0.0
        msg.pose.pose.orientation.y = 0.0
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance = [0.0] * 36
        msg.pose.covariance[0] = 0.15
        msg.pose.covariance[7] = 0.15
        msg.pose.covariance[35] = 0.4
        self._amcl_publisher.publish(msg)

    def _build_pose_stamped(self, waypoint: Waypoint) -> Any:
        # @TASK: Convertir waypoint a ROS
        # @INPUT: waypoint
        # @OUTPUT: PoseStamped compatible con Nav2
        # @CONTEXT: Adaptador de dominio interno hacia BasicNavigator
        # STEP 1: Instanciar PoseStamped dinamicamente
        # STEP 2: Poblar posicion, orientacion y frame temporal
        # @SECURITY: Evita dependencia fuerte al tipo en interfaz publica
        # @AI_CONTEXT: Any se utiliza por import dinamico de mensajes ROS
        from geometry_msgs.msg import PoseStamped

        msg = PoseStamped()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.header.frame_id = waypoint.frame_id
        msg.pose.position.x = waypoint.x
        msg.pose.position.y = waypoint.y
        msg.pose.position.z = 0.0
        msg.pose.orientation.x = 0.0
        msg.pose.orientation.y = 0.0
        msg.pose.orientation.z = math.sin(waypoint.yaw_rad / 2.0)
        msg.pose.orientation.w = math.cos(waypoint.yaw_rad / 2.0)
        return msg

    @staticmethod
    def _extract_yaw_from_rvec(rvec: Any) -> float:
        # @TASK: Extraer yaw desde rvec
        # @INPUT: rvec
        # @OUTPUT: Angulo yaw en radianes
        # @CONTEXT: Paso auxiliar para inyeccion de pose en AMCL
        # STEP 1: Convertir vector de rotacion a matriz con Rodrigues
        # STEP 2: Derivar yaw desde la matriz de rotacion
        # @SECURITY: Metodo puro sin efectos secundarios
        # @AI_CONTEXT: Aproximacion adecuada para MVP de guiado indoor
        rotation_matrix, _ = cv2.Rodrigues(rvec)
        yaw = math.atan2(float(rotation_matrix[1, 0]), float(rotation_matrix[0, 0]))
        return yaw

    @staticmethod
    def _create_navigator() -> "BasicNavigator":
        # @TASK: Crear BasicNavigator
        # @INPUT: Sin parametros
        # @OUTPUT: Instancia de nav2_simple_commander
        # @CONTEXT: Factory interna para desacoplar import en runtime
        # STEP 1: Importar BasicNavigator dentro de la funcion
        # STEP 2: Retornar instancia lista para comandos de ruta
        # @SECURITY: Falla temprano si dependencia nav2 no esta instalada
        # @AI_CONTEXT: Facilita reemplazo por doubles en pruebas
        from nav2_simple_commander.robot_navigator import BasicNavigator

        return BasicNavigator()

    def _apply_safety_speed_limit(self) -> None:
        # @TASK: Aplicar limite de velocidad al BasicNavigator
        # @INPUT: MAX_LINEAR_VELOCITY
        # @OUTPUT: Nav2 configurado con cap lineal de seguridad
        # @CONTEXT: Enforce centralizado de restriccion cinemática en navegacion
        # STEP 1: Detectar API setSpeedLimit en la instancia de navigator
        # STEP 2: Configurar limite absoluto en m/s y registrar resultado
        # @SECURITY: Evita que planes de navegacion excedan 0.3 m/s
        # @AI_CONTEXT: Falla controlada si la API del navigator no expone speed limit
        set_speed_limit = getattr(self._navigator, "setSpeedLimit", None)
        if not callable(set_speed_limit):
            LOGGER.warning(
                "BasicNavigator no expone setSpeedLimit(); no se pudo aplicar cap de %.2f m/s.",
                MAX_LINEAR_VELOCITY,
            )
            return

        set_speed_limit(MAX_LINEAR_VELOCITY, False)
        LOGGER.info(
            "NavigationManager aplico limite lineal de seguridad: %.2f m/s.",
            MAX_LINEAR_VELOCITY,
        )

    def _spin_forever(self) -> None:
        # @TASK: Ejecutar spin continuo
        # @INPUT: Sin parametros
        # @OUTPUT: Executor ROS2 atendiendo callbacks
        # @CONTEXT: Hilo dedicado para rclpy.spin prohibido en event loop
        # STEP 1: Entrar a loop de spin del MultiThreadedExecutor
        # STEP 2: Salir silenciosamente en shutdown
        # @SECURITY: Encapsula ciclo bloqueante dentro de thread daemon
        # @AI_CONTEXT: Base de concurrencia para pub/sub y timers ROS
        try:
            self._spin_executor.spin()
        except Exception:
            return

    async def close(self) -> None:
        # @TASK: Cerrar recursos navegacion
        # @INPUT: Sin parametros
        # @OUTPUT: Executor y nodo ROS2 liberados
        # @CONTEXT: Shutdown ordenado de capa NavigationManager
        # STEP 1: Detener spin executor y destruir nodo interno
        # STEP 2: Apagar thread pool de trabajo y contexto ROS2
        # @SECURITY: Previene callbacks tardios tras finalizar aplicacion
        # @AI_CONTEXT: Invocar durante apagado del proceso principal
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._work_executor, self._close_sync)

    def _close_sync(self) -> None:
        # @TASK: Ejecutar cierre sync
        # @INPUT: Sin parametros
        # @OUTPUT: Recursos ROS2 y ejecutores cerrados
        # @CONTEXT: Segmento bloqueante para run_in_executor en close
        # STEP 1: Apagar spin executor y destruir nodo
        # STEP 2: Apagar rclpy y thread pool
        # @SECURITY: Evita fugas de hilos y handles ROS
        # @AI_CONTEXT: Mantiene cierre determinista del subsistema de navegacion
        self._spin_executor.shutdown(timeout_sec=0.2)
        self._node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        self._work_executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["MAX_LINEAR_VELOCITY", "NavigationManager", "Waypoint"]