"""
@TASK: Implementar puente de navegacion offline mediante ActionClient directo.
@INPUT: Llamadas de TourOrchestrator para navegacion.
@OUTPUT: Ejecucion de NavigateToPose y FollowWaypoints mediante ROS 2 actions.
@CONTEXT: Reemplaza a AsyncNav2Bridge para entorno sin Simple Commander.
@SECURITY: Isolation completo de I/O bloqueante.
"""
from __future__ import annotations

import asyncio
import binascii
import logging
import math
import threading
from typing import Any, Optional, Sequence

from src.navigation.models import (
    MissedWaypointDetail,
    NavigationResult,
    NavigationStatus,
    NavigationTerminalStatus,
    NavWaypoint,
)
from src.navigation.port import NavigationPort

LOGGER = logging.getLogger("direct_nav2_action_bridge")


class DirectNav2ActionBridge(NavigationPort):
    """
    @TASK: Bridge directo para interactuar con Nav2 actions sin BasicNavigator.
    @CONTEXT: Mantiene total control sobre el event loop local de asyncio.
    """

    def __init__(
        self,
        node_name: str = "direct_nav2_action_bridge",
        namespace: str = "offline_nav",
        navigate_to_pose_action: str = "/offline_nav/navigate_to_pose",
        follow_waypoints_action: str = "/offline_nav/follow_waypoints",
        initial_pose_topic: str = "/initialpose",
        server_timeout_s: float = 15.0,
        goal_response_timeout_s: float = 10.0,
        result_timeout_s: float = 120.0,
        cancel_response_timeout_s: float = 10.0,
        cancel_terminal_timeout_s: float = 15.0,
    ):
        if any(t <= 0 for t in [
            server_timeout_s, goal_response_timeout_s, result_timeout_s,
            cancel_response_timeout_s, cancel_terminal_timeout_s
        ]):
            raise ValueError("Timeouts must be positive")

        self._node_name = node_name
        self._namespace = namespace
        self._ntp_action = navigate_to_pose_action
        self._fw_action = follow_waypoints_action
        self._initial_pose_topic = initial_pose_topic
        self._server_timeout_s = server_timeout_s
        self._goal_response_timeout_s = goal_response_timeout_s
        self._result_timeout_s = result_timeout_s
        self._cancel_response_timeout_s = cancel_response_timeout_s
        self._cancel_terminal_timeout_s = cancel_terminal_timeout_s

        self._started = False

        self._rclpy: Any = None
        self._context: Any = None
        self._node: Any = None
        self._executor: Any = None
        self._spin_thread: Optional[threading.Thread] = None

        self._ntp_client: Any = None
        self._fw_client: Any = None
        self._initial_pose_pub: Any = None

        self._dispatch_lock = asyncio.Lock()
        self._state_lock = threading.RLock()

        self._status = NavigationStatus()
        self._active_goal_handle: Any = None
        self._active_action_name: Optional[str] = None
        self._active_goal_uuid: Optional[str] = None
        self._active_result_task: Optional[asyncio.Task[Any]] = None
        self._cancel_requested: bool = False
        self._cancel_accepted: Optional[bool] = None

    async def start(self) -> None:
        """Inicializa el bridge y los action clients."""
        if self._started:
            return

        try:
            import rclpy
            import rclpy.context
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from nav2_msgs.action import FollowWaypoints, NavigateToPose
            from rclpy.action import ActionClient
            from rclpy.executors import MultiThreadedExecutor

            self._rclpy = rclpy
            self._context = rclpy.context.Context()
            rclpy.init(context=self._context)

            self._node = rclpy.create_node(
                self._node_name,
                namespace=self._namespace,
                context=self._context
            )

            self._executor = MultiThreadedExecutor(context=self._context)
            self._executor.add_node(self._node)

            self._spin_thread = threading.Thread(target=self._executor.spin, daemon=True)
            self._spin_thread.start()

            self._ntp_client = ActionClient(self._node, NavigateToPose, self._ntp_action)
            self._fw_client = ActionClient(self._node, FollowWaypoints, self._fw_action)
            self._initial_pose_pub = self._node.create_publisher(
                PoseWithCovarianceStamped,
                self._initial_pose_topic,
                10
            )

            loop = asyncio.get_running_loop()

            def wait_ntp() -> bool:
                return self._ntp_client.wait_for_server(timeout_sec=self._server_timeout_s)

            def wait_fw() -> bool:
                return self._fw_client.wait_for_server(timeout_sec=self._server_timeout_s)

            ntp_ready = await loop.run_in_executor(None, wait_ntp)
            fw_ready = await loop.run_in_executor(None, wait_fw)

            if not ntp_ready or not fw_ready:
                raise RuntimeError("Action servers not available")

            self._started = True
            LOGGER.info("DirectNav2ActionBridge started successfully.")

        except Exception as exc:
            await self._cleanup()
            raise RuntimeError(f"Failed to start bridge: {exc}") from exc

    async def _cleanup(self) -> None:
        """Limpieza interna idempotente.

        El estado degradado se detecta primero a partir del estado YA
        existente al entrar (remote_state_unknown ya en True, o
        task_active=True sin un goal handle -- p.ej. tras un goal-response
        timeout, donde nunca hubo result task que pudiera reportar el
        fallo por su cuenta), y luego se amplia si la cancelacion o la
        espera de su terminal fallan durante este mismo cierre. Siempre
        completa el teardown local (executor/nodo/contexto/thread)
        independientemente del resultado de la cancelacion, pero nunca
        silencia la degradacion: se levanta
        DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN despues de liberar los
        recursos locales si corresponde.
        """
        self._started = False

        with self._state_lock:
            had_handle = self._active_goal_handle is not None
            result_task = self._active_result_task
            degraded = bool(
                self._status.remote_state_unknown
                or (self._status.task_active and self._active_goal_handle is None)
            )

        if had_handle:
            try:
                await self.cancel_navigation()
            except Exception as exc:
                LOGGER.error("Cleanup cancel failed, remote state unknown: %s", exc)
                degraded = True

        if result_task and not result_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(result_task), timeout=self._cancel_terminal_timeout_s)
            except Exception as exc:
                LOGGER.error("Cleanup waiting for result task failed, remote state unknown: %s", exc)
                degraded = True

        if self._executor:
            try:
                self._executor.shutdown(timeout_sec=1.0)
            except Exception as exc:
                LOGGER.warning("Executor shutdown failed: %s", exc)

        if self._node:
            try:
                self._node.destroy_node()
            except Exception as exc:
                LOGGER.warning("Node destroy failed: %s", exc)

        if self._context:
            try:
                if self._rclpy and self._rclpy.ok(context=self._context):
                    self._rclpy.shutdown(context=self._context)
            except Exception as exc:
                LOGGER.warning("Context shutdown failed: %s", exc)

        if self._spin_thread and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)
            if self._spin_thread.is_alive():
                raise RuntimeError("DIRECT_BRIDGE_SPIN_THREAD_STILL_ALIVE")

        self._executor = None
        self._node = None
        self._context = None
        self._spin_thread = None
        self._ntp_client = None
        self._fw_client = None
        self._initial_pose_pub = None
        self._active_goal_handle = None
        self._active_result_task = None
        self._active_action_name = None
        self._active_goal_uuid = None

        with self._state_lock:
            # El bridge local esta cerrado: no hay event loop ROS propio
            # que pueda seguir resolviendo este goal, sin importar si su
            # estado remoto fue confirmado.
            self._status.task_active = False
            # Si hubo degradacion (previa o detectada durante este cierre),
            # remote_state_unknown se conserva en True como evidencia
            # historica; un cierre limpio lo deja en False.
            self._status.remote_state_unknown = degraded

        if degraded:
            raise RuntimeError("DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN")

    async def close(self) -> None:
        """Cierra el bridge y libera recursos."""
        await self._cleanup()

    def _ros_future_to_asyncio(self, ros_future: Any) -> asyncio.Future[Any]:
        loop = asyncio.get_running_loop()
        aio_future = loop.create_future()

        def done_callback(f: Any) -> None:
            def transfer() -> None:
                if aio_future.done():
                    return
                try:
                    res = f.result()
                    aio_future.set_result(res)
                except Exception as exc:
                    aio_future.set_exception(exc)

            if not loop.is_closed():
                loop.call_soon_threadsafe(transfer)

        ros_future.add_done_callback(done_callback)
        return aio_future

    def _normalize_uuid(self, uuid_msg: Any) -> str:
        if hasattr(uuid_msg, 'uuid'):
            return binascii.hexlify(bytes(uuid_msg.uuid)).decode('utf-8')
        return str(uuid_msg)

    def _map_goal_status(self, status: int) -> NavigationTerminalStatus:
        from action_msgs.msg import GoalStatus
        mapping = {
            GoalStatus.STATUS_SUCCEEDED: NavigationTerminalStatus.SUCCEEDED,
            GoalStatus.STATUS_CANCELED: NavigationTerminalStatus.CANCELED,
            GoalStatus.STATUS_ABORTED: NavigationTerminalStatus.ABORTED,
        }
        return mapping.get(status, NavigationTerminalStatus.ERROR)

    def _create_pose_stamped(self, waypoint: NavWaypoint) -> Any:
        from geometry_msgs.msg import PoseStamped

        msg = PoseStamped()
        msg.header.frame_id = waypoint.frame_id
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.position.x = float(waypoint.x)
        msg.pose.position.y = float(waypoint.y)
        msg.pose.position.z = 0.0
        msg.pose.orientation.x = 0.0
        msg.pose.orientation.y = 0.0
        msg.pose.orientation.z = math.sin(waypoint.yaw_rad / 2.0)
        msg.pose.orientation.w = math.cos(waypoint.yaw_rad / 2.0)
        return msg

    async def is_navigation_active(self) -> bool:
        """Consulta actividad."""
        with self._state_lock:
            return self._status.task_active

    async def get_status(self) -> NavigationStatus:
        """Consulta estado general."""
        with self._state_lock:
            return NavigationStatus(
                task_active=self._status.task_active,
                last_result_succeeded=self._status.last_result_succeeded,
                active_waypoint_index=self._status.active_waypoint_index,
                feedback_count=self._status.feedback_count,
                distance_remaining_m=self._status.distance_remaining_m,
                goal_uuid=self._status.goal_uuid,
                action_name=self._status.action_name,
                last_result=self._status.last_result,
                remote_state_unknown=self._status.remote_state_unknown
            )

    async def get_last_result(self) -> Optional[NavigationResult]:
        """Consulta el ultimo resultado."""
        with self._state_lock:
            return self._status.last_result

    def _ntp_feedback_cb(self, feedback_msg: Any) -> None:
        with self._state_lock:
            self._status.feedback_count += 1
            if hasattr(feedback_msg.feedback, 'distance_remaining'):
                self._status.distance_remaining_m = feedback_msg.feedback.distance_remaining

    def _fw_feedback_cb(self, feedback_msg: Any) -> None:
        with self._state_lock:
            self._status.feedback_count += 1
            if hasattr(feedback_msg.feedback, 'current_waypoint'):
                self._status.active_waypoint_index = feedback_msg.feedback.current_waypoint

    async def _result_monitor_task(self, goal_handle: Any, aio_result_future: asyncio.Future[Any], action_name: str, uuid_str: str) -> NavigationResult:
        """Monitor unico de resultado.

        Unico propietario de la transicion terminal normal. En las ramas de
        timeout/excepcion nunca llama al metodo publico cancel_navigation()
        (eso causaria que esta misma tarea se espere a si misma a traves de
        _active_result_task); usa el helper interno _request_cancel_only()
        y espera directamente el result future subyacente.
        """
        try:
            result_msg = await asyncio.wait_for(asyncio.shield(aio_result_future), timeout=self._result_timeout_s)
        except asyncio.TimeoutError:
            LOGGER.warning("Result timeout for goal %s", uuid_str)
            terminal_confirmed = False

            with self._state_lock:
                had_active_goal = self._active_goal_handle is not None

            if had_active_goal:
                try:
                    await self._request_cancel_only()
                    try:
                        result_msg2 = await asyncio.wait_for(asyncio.shield(aio_result_future), timeout=self._cancel_terminal_timeout_s)
                        if self._map_goal_status(result_msg2.status) == NavigationTerminalStatus.CANCELED:
                            terminal_confirmed = True
                    except asyncio.TimeoutError:
                        terminal_confirmed = False
                except Exception as exc:
                    LOGGER.warning("Cancel after result timeout failed: %s", exc)

            with self._state_lock:
                req = self._cancel_requested
                acc = self._cancel_accepted

            return self._finalize_result(NavigationResult(
                action_name=action_name,
                status=NavigationTerminalStatus.TIMEOUT,
                succeeded=False,
                goal_uuid=uuid_str,
                cancel_requested=req,
                cancel_accepted=acc,
                error_msg="Result timeout"
            ), terminal_confirmed=terminal_confirmed)

        except Exception as exc:
            LOGGER.warning("Exception during result monitoring: %s", exc)
            try:
                await self._request_cancel_only()
            except Exception as e:
                LOGGER.warning("Cancel after exception failed: %s", e)

            with self._state_lock:
                req = self._cancel_requested
                acc = self._cancel_accepted

            return self._finalize_result(NavigationResult(
                action_name=action_name,
                status=NavigationTerminalStatus.ERROR,
                succeeded=False,
                goal_uuid=uuid_str,
                cancel_requested=req,
                cancel_accepted=acc,
                error_msg=str(exc)
            ), terminal_confirmed=False)

        # Llegada normal de un GoalStatus terminal real del servidor: es
        # evidencia comprobada (SUCCEEDED/CANCELED/ABORTED, o ERROR si el
        # status no esta mapeado), nunca inferida.
        term_status = self._map_goal_status(result_msg.status)
        error_code = getattr(result_msg.result, 'error_code', None)
        error_msg = getattr(result_msg.result, 'error_msg', "")

        missed: list[MissedWaypointDetail] = []
        if hasattr(result_msg.result, 'missed_waypoints'):
            for mw in result_msg.result.missed_waypoints:
                idx = getattr(mw, 'index', 0)
                ec = getattr(mw, 'error_code', None)
                missed.append(MissedWaypointDetail(index=idx, error_code=ec))

        with self._state_lock:
            final_wp = self._status.active_waypoint_index
            req = self._cancel_requested
            acc = self._cancel_accepted

        res = NavigationResult(
            action_name=action_name,
            status=term_status,
            succeeded=(term_status == NavigationTerminalStatus.SUCCEEDED),
            goal_uuid=uuid_str,
            error_code=error_code,
            error_msg=error_msg,
            missed_waypoints=tuple(missed),
            final_waypoint_index=final_wp,
            cancel_requested=req,
            cancel_accepted=acc
        )
        return self._finalize_result(res, terminal_confirmed=True)

    def _finalize_result(self, result: NavigationResult, terminal_confirmed: bool) -> NavigationResult:
        """Unico punto de limpieza de estado terminal.

        Nunca infiere terminacion remota a partir del enum NavigationTerminalStatus
        local (p.ej. ERROR/TIMEOUT): solo limpia active_goal_handle/uuid y libera
        task_active cuando el llamador aporta evidencia terminal comprobada
        (terminal_confirmed=True). En caso contrario el goal permanece activo y
        remote_state_unknown queda en True, bloqueando nuevos goals hasta close().
        """
        with self._state_lock:
            if terminal_confirmed:
                self._status.task_active = False
                self._active_goal_handle = None
                self._active_action_name = None
                self._active_goal_uuid = None
                self._status.remote_state_unknown = False
            else:
                self._status.remote_state_unknown = True

            self._status.last_result = result
            self._status.last_result_succeeded = result.succeeded
        return result

    async def _execute_action(self, client: Any, goal_msg: Any, action_name: str, feedback_cb: Any) -> NavigationResult:
        if not self._started:
            raise RuntimeError("Bridge not started")

        async with self._dispatch_lock:
            with self._state_lock:
                if self._status.task_active:
                    raise RuntimeError("NAVIGATION_GOAL_ALREADY_ACTIVE")

                self._status = NavigationStatus()
                self._status.task_active = True
                self._status.action_name = action_name
                self._cancel_requested = False
                self._cancel_accepted = None

            goal_accepted = False
            aio_result_future: Optional[asyncio.Future[Any]] = None
            try:
                import uuid as uuid_lib
                generated_uuid = uuid_lib.uuid4()
                generated_uuid_hex = str(generated_uuid)
                import unique_identifier_msgs.msg
                uuid_msg = unique_identifier_msgs.msg.UUID(uuid=list(generated_uuid.bytes))

                send_goal_future = client.send_goal_async(goal_msg, feedback_callback=feedback_cb, goal_uuid=uuid_msg)
                aio_send_future = self._ros_future_to_asyncio(send_goal_future)

                try:
                    goal_handle = await asyncio.wait_for(asyncio.shield(aio_send_future), timeout=self._goal_response_timeout_s)
                except asyncio.TimeoutError:
                    try:
                        aio_send_future.cancel()
                        send_goal_future.cancel()
                    except Exception:
                        pass
                    # Aceptacion remota desconocida: no podemos afirmar
                    # rechazo ni exito. Conservamos el UUID generado para
                    # diagnostico, dejamos el bridge bloqueado
                    # (task_active permanece True) y exigimos close().
                    with self._state_lock:
                        self._status.goal_uuid = generated_uuid_hex
                    return self._finalize_result(NavigationResult(
                        action_name=action_name,
                        status=NavigationTerminalStatus.TIMEOUT,
                        succeeded=False,
                        goal_uuid=generated_uuid_hex,
                        error_msg="Goal response timeout: remote acceptance unknown"
                    ), terminal_confirmed=False)

                if not goal_handle.accepted:
                    return self._finalize_result(NavigationResult(
                        action_name=action_name,
                        status=NavigationTerminalStatus.REJECTED,
                        succeeded=False,
                        goal_uuid=generated_uuid_hex,
                        error_msg="Goal rejected by server"
                    ), terminal_confirmed=True)

                goal_accepted = True
                uuid_str = self._normalize_uuid(goal_handle.goal_id)

                with self._state_lock:
                    self._active_goal_handle = goal_handle
                    self._active_action_name = action_name
                    self._active_goal_uuid = uuid_str
                    self._status.goal_uuid = uuid_str

                get_result_future = goal_handle.get_result_async()
                aio_result_future = self._ros_future_to_asyncio(get_result_future)

                loop = asyncio.get_running_loop()
                self._active_result_task = loop.create_task(
                    self._result_monitor_task(goal_handle, aio_result_future, action_name, uuid_str)
                )

            except Exception as exc:
                LOGGER.warning("Exception during action execution start: %s", exc)

                if goal_accepted:
                    # El goal fue aceptado por el servidor antes de que la
                    # excepcion ocurriera (p.ej. fallo de get_result_async()
                    # o de creacion de la tarea monitor, que nunca llego a
                    # iniciarse). Conservamos handle/UUID, solicitamos
                    # cancelacion mediante el helper interno (nunca el
                    # monitor, que no existe en esta rama) y solo limpiamos
                    # si se confirma terminal CANCELED.
                    terminal_confirmed = False
                    try:
                        await self._request_cancel_only()
                        if aio_result_future is not None:
                            try:
                                result_msg = await asyncio.wait_for(
                                    asyncio.shield(aio_result_future), timeout=self._cancel_terminal_timeout_s
                                )
                                if self._map_goal_status(result_msg.status) == NavigationTerminalStatus.CANCELED:
                                    terminal_confirmed = True
                            except asyncio.TimeoutError:
                                terminal_confirmed = False
                    except Exception as cancel_exc:
                        LOGGER.warning("Cancel after post-acceptance exception failed: %s", cancel_exc)

                    with self._state_lock:
                        req = self._cancel_requested
                        acc = self._cancel_accepted
                        uuid_for_result = self._active_goal_uuid

                    return self._finalize_result(NavigationResult(
                        action_name=action_name,
                        status=NavigationTerminalStatus.ERROR,
                        succeeded=False,
                        goal_uuid=uuid_for_result,
                        cancel_requested=req,
                        cancel_accepted=acc,
                        error_msg=str(exc)
                    ), terminal_confirmed=terminal_confirmed)

                return self._finalize_result(NavigationResult(
                    action_name=action_name,
                    status=NavigationTerminalStatus.ERROR,
                    succeeded=False,
                    error_msg=str(exc)
                ), terminal_confirmed=True)

        return await asyncio.shield(self._active_result_task)

    async def send_goal(self, waypoint: NavWaypoint) -> bool:
        """Envia un unico waypoint de navegacion."""
        from nav2_msgs.action import NavigateToPose
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self._create_pose_stamped(waypoint)

        result = await self._execute_action(self._ntp_client, goal_msg, self._ntp_action, self._ntp_feedback_cb)
        return result.succeeded

    async def navigate_to_waypoints(self, waypoints: Sequence[NavWaypoint]) -> bool:
        """Envia una lista de waypoints."""
        if not waypoints:
            res = NavigationResult(
                action_name=self._fw_action,
                status=NavigationTerminalStatus.SUCCEEDED,
                succeeded=True
            )
            with self._state_lock:
                self._status.last_result = res
                self._status.last_result_succeeded = True
            return True

        from nav2_msgs.action import FollowWaypoints
        goal_msg = FollowWaypoints.Goal()

        if hasattr(goal_msg, 'number_of_loops'):
            goal_msg.number_of_loops = 0
        if hasattr(goal_msg, 'goal_index'):
            goal_msg.goal_index = 0

        poses = [self._create_pose_stamped(wp) for wp in waypoints]
        if hasattr(goal_msg, 'poses'):
            goal_msg.poses = poses

        result = await self._execute_action(self._fw_client, goal_msg, self._fw_action, self._fw_feedback_cb)
        return result.succeeded

    async def _request_cancel_only(self) -> None:
        """Solicita CancelGoal y valida su aceptacion remota.

        Helper interno de bajo nivel: nunca espera _active_result_task. Es
        seguro llamarlo desde el monitor de resultado (en sus ramas de
        timeout/excepcion) o desde _execute_action (tras una excepcion
        posterior a la aceptacion), porque nunca se espera a si mismo a
        traves de la tarea que esos llamadores pueden ser.
        """
        with self._state_lock:
            goal_handle = self._active_goal_handle
            uuid_str = self._active_goal_uuid
            if not goal_handle:
                return
            self._cancel_requested = True

        from action_msgs.srv import CancelGoal

        try:
            cancel_future = goal_handle.cancel_goal_async()
            aio_cancel_future = self._ros_future_to_asyncio(cancel_future)

            cancel_response = await asyncio.wait_for(asyncio.shield(aio_cancel_future), timeout=self._cancel_response_timeout_s)

            accepted = False
            if cancel_response.return_code == CancelGoal.Response.ERROR_NONE:
                for gc in cancel_response.goals_canceling:
                    if self._normalize_uuid(gc.goal_id) == uuid_str:
                        accepted = True
                        break

            with self._state_lock:
                self._cancel_accepted = accepted

            if not accepted:
                raise RuntimeError("CANCEL_REQUEST_NOT_ACCEPTED")

        except asyncio.TimeoutError as exc:
            raise RuntimeError("Cancel response timeout") from exc
        except Exception as exc:
            if str(exc) == "CANCEL_REQUEST_NOT_ACCEPTED":
                raise
            LOGGER.warning("Cancel request failed: %s", exc)
            raise RuntimeError(f"Cancel request failed: {exc}") from exc

    async def cancel_navigation(self) -> None:
        """Cancela el goal activo y exige confirmacion terminal CANCELED.

        Unico metodo publico de cancelacion: solicita la cancelacion via el
        helper interno y luego espera al monitor de resultado (propietario
        unico de la transicion terminal normal). Nunca debe ser llamado por
        el propio monitor (eso causaria que una tarea se espere a si misma).

        Si no existe un result task observable (p.ej. el goal fue aceptado
        pero get_result_async()/la creacion del monitor fallo antes de
        producir uno), una respuesta CancelGoal aceptada NUNCA se traduce
        en CANCELED: aceptacion del servicio de cancelacion es evidencia de
        que el servidor *recibio* la solicitud, no de que el goal terminara.
        Sin un monitor que observe el GoalStatus real, ese terminal sigue
        sin confirmar, por lo que el goal permanece activo y el estado
        remoto queda explicitamente desconocido hasta close().
        """
        with self._state_lock:
            goal_handle = self._active_goal_handle
            res_task = self._active_result_task
            if not goal_handle or not self._status.task_active:
                return

        await self._request_cancel_only()

        if res_task is None:
            with self._state_lock:
                self._status.remote_state_unknown = True
            raise RuntimeError("CANCEL_TERMINAL_UNOBSERVABLE")

        try:
            res = await asyncio.wait_for(asyncio.shield(res_task), timeout=self._cancel_terminal_timeout_s)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("CANCEL_TERMINAL_TIMEOUT") from exc
        if res.status != NavigationTerminalStatus.CANCELED:
            raise RuntimeError(f"CANCEL_TERMINAL_NOT_CANCELED:{res.status}")

    async def inject_absolute_pose(self, pose_estimate: "PoseEstimate") -> None:
        """Inyecta una pose absoluta inicial."""
        if not self._started:
            raise RuntimeError("DIRECT_NAV2_BRIDGE_NOT_STARTED")
        if not self._initial_pose_pub:
            return

        try:
            import cv2
            from geometry_msgs.msg import PoseWithCovarianceStamped
        except ImportError as exc:
            # Una dependencia faltante nunca debe reportarse como exito
            # silencioso: /initialpose no se publica y el llamador debe
            # saberlo de forma explicita.
            raise RuntimeError(f"INITIAL_POSE_DEPENDENCY_UNAVAILABLE:{exc}") from exc

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self._node.get_clock().now().to_msg()

        msg.pose.pose.position.x = float(pose_estimate.tvec[0][0])
        msg.pose.pose.position.y = float(pose_estimate.tvec[1][0])
        msg.pose.pose.position.z = 0.0

        rotation_matrix, _ = cv2.Rodrigues(pose_estimate.rvec)
        yaw = math.atan2(rotation_matrix[1, 0], rotation_matrix[0, 0])

        msg.pose.pose.orientation.x = 0.0
        msg.pose.pose.orientation.y = 0.0
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        cov = [0.0] * 36
        cov[0] = 0.15
        cov[7] = 0.15
        cov[35] = 0.40
        msg.pose.covariance = cov

        self._initial_pose_pub.publish(msg)
