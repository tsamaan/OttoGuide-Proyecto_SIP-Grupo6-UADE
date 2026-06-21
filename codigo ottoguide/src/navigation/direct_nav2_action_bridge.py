import asyncio
import threading
import time
import math
import uuid
import binascii
from typing import Optional, Sequence, Any, Dict, Tuple, List, cast

from src.navigation.port import NavigationPort
from src.navigation.models import (
    NavWaypoint,
    NavigationStatus,
    NavigationResult,
    NavigationTerminalStatus,
    MissedWaypointDetail
)

class DirectNav2ActionBridge(NavigationPort):
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
        if any(t <= 0 for t in [server_timeout_s, goal_response_timeout_s, result_timeout_s, cancel_response_timeout_s, cancel_terminal_timeout_s]):
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

    async def start(self) -> None:
        if self._started:
            return
            
        try:
            import rclpy
            import rclpy.context
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.action import ActionClient
            from nav2_msgs.action import NavigateToPose, FollowWaypoints
            from geometry_msgs.msg import PoseWithCovarianceStamped
            
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
            
            ntp_ready = self._ntp_client.wait_for_server(timeout_sec=self._server_timeout_s)
            fw_ready = self._fw_client.wait_for_server(timeout_sec=self._server_timeout_s)
            
            if not ntp_ready or not fw_ready:
                raise RuntimeError("Action servers not available")
                
            self._started = True
            
        except Exception as e:
            await self._cleanup()
            raise RuntimeError(f"Failed to start bridge: {e}")

    async def _cleanup(self) -> None:
        self._started = False
        if self._active_goal_handle:
            try:
                await self.cancel_navigation()
            except Exception:
                pass
                
        if self._executor:
            try:
                self._executor.shutdown()
            except Exception:
                pass
                
        if self._node:
            try:
                self._node.destroy_node()
            except Exception:
                pass
                
        if self._context:
            try:
                self._rclpy.shutdown(context=self._context)
            except Exception:
                pass
                
        if self._spin_thread and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)
            
        self._executor = None
        self._node = None
        self._context = None
        self._spin_thread = None
        self._ntp_client = None
        self._fw_client = None
        self._initial_pose_pub = None
        self._active_goal_handle = None

    async def close(self) -> None:
        await self._cleanup()

    def _ros_future_to_asyncio(self, ros_future: Any) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        aio_future = loop.create_future()
        
        def done_callback(f: Any) -> None:
            if not aio_future.done():
                try:
                    res = f.result()
                    loop.call_soon_threadsafe(aio_future.set_result, res)
                except Exception as e:
                    loop.call_soon_threadsafe(aio_future.set_exception, e)
                    
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
        from builtin_interfaces.msg import Time
        
        msg = PoseStamped()
        msg.header.frame_id = waypoint.frame_id
        
        now = self._node.get_clock().now().to_msg()
        msg.header.stamp = now
        
        msg.pose.position.x = float(waypoint.x)
        msg.pose.position.y = float(waypoint.y)
        msg.pose.position.z = 0.0
        
        msg.pose.orientation.x = 0.0
        msg.pose.orientation.y = 0.0
        msg.pose.orientation.z = math.sin(waypoint.yaw_rad / 2.0)
        msg.pose.orientation.w = math.cos(waypoint.yaw_rad / 2.0)
        
        return msg

    async def is_navigation_active(self) -> bool:
        with self._state_lock:
            return self._status.task_active

    async def get_status(self) -> NavigationStatus:
        with self._state_lock:
            return NavigationStatus(
                task_active=self._status.task_active,
                last_result_succeeded=self._status.last_result_succeeded,
                active_waypoint_index=self._status.active_waypoint_index,
                feedback_count=self._status.feedback_count,
                distance_remaining_m=self._status.distance_remaining_m,
                goal_uuid=self._status.goal_uuid,
                action_name=self._status.action_name,
                last_result=self._status.last_result
            )

    async def get_last_result(self) -> Optional[NavigationResult]:
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
                
            try:
                send_goal_future = client.send_goal_async(goal_msg, feedback_callback=feedback_cb)
                aio_send_future = self._ros_future_to_asyncio(send_goal_future)
                
                try:
                    goal_handle = await asyncio.wait_for(aio_send_future, timeout=self._goal_response_timeout_s)
                except asyncio.TimeoutError:
                    return self._finish_with_result(NavigationResult(
                        action_name=action_name,
                        status=NavigationTerminalStatus.TIMEOUT,
                        succeeded=False,
                        error_msg="Goal response timeout"
                    ))
                
                if not goal_handle.accepted:
                    return self._finish_with_result(NavigationResult(
                        action_name=action_name,
                        status=NavigationTerminalStatus.REJECTED,
                        succeeded=False,
                        error_msg="Goal rejected by server"
                    ))
                
                uuid_str = self._normalize_uuid(goal_handle.goal_id)
                
                with self._state_lock:
                    self._active_goal_handle = goal_handle
                    self._active_action_name = action_name
                    self._status.goal_uuid = uuid_str
                
                get_result_future = goal_handle.get_result_async()
                aio_result_future = self._ros_future_to_asyncio(get_result_future)
                
                try:
                    result_msg = await asyncio.wait_for(aio_result_future, timeout=self._result_timeout_s)
                except asyncio.TimeoutError:
                    await self.cancel_navigation()
                    with self._state_lock:
                        cancel_accepted = self._status.last_result.cancel_accepted if self._status.last_result else None
                    return self._finish_with_result(NavigationResult(
                        action_name=action_name,
                        status=NavigationTerminalStatus.TIMEOUT,
                        succeeded=False,
                        goal_uuid=uuid_str,
                        cancel_requested=True,
                        cancel_accepted=cancel_accepted,
                        error_msg="Result timeout"
                    ))
                
                term_status = self._map_goal_status(result_msg.status)
                
                error_code = getattr(result_msg.result, 'error_code', None)
                error_msg = getattr(result_msg.result, 'error_msg', "")
                
                missed = []
                if hasattr(result_msg.result, 'missed_waypoints'):
                    for mw in result_msg.result.missed_waypoints:
                        idx = getattr(mw, 'index', 0)
                        ec = getattr(mw, 'error_code', None)
                        missed.append(MissedWaypointDetail(index=idx, error_code=ec))
                
                with self._state_lock:
                    final_wp = self._status.active_waypoint_index
                    cancel_req = False
                    cancel_acc = None
                    if self._status.last_result:
                        cancel_req = self._status.last_result.cancel_requested
                        cancel_acc = self._status.last_result.cancel_accepted
                
                return self._finish_with_result(NavigationResult(
                    action_name=action_name,
                    status=term_status,
                    succeeded=(term_status == NavigationTerminalStatus.SUCCEEDED),
                    goal_uuid=uuid_str,
                    error_code=error_code,
                    error_msg=error_msg,
                    missed_waypoints=tuple(missed),
                    final_waypoint_index=final_wp,
                    cancel_requested=cancel_req,
                    cancel_accepted=cancel_acc
                ))
                
            except Exception as e:
                return self._finish_with_result(NavigationResult(
                    action_name=action_name,
                    status=NavigationTerminalStatus.ERROR,
                    succeeded=False,
                    error_msg=str(e)
                ))

    def _finish_with_result(self, result: NavigationResult) -> NavigationResult:
        with self._state_lock:
            # Preserve cancel info if we're overwriting a preliminary result from cancel
            if self._status.last_result:
                if not result.cancel_requested:
                    result = NavigationResult(
                        action_name=result.action_name,
                        status=result.status,
                        succeeded=result.succeeded,
                        goal_uuid=result.goal_uuid,
                        error_code=result.error_code,
                        error_msg=result.error_msg,
                        missed_waypoints=result.missed_waypoints,
                        final_waypoint_index=result.final_waypoint_index,
                        cancel_requested=self._status.last_result.cancel_requested,
                        cancel_accepted=self._status.last_result.cancel_accepted
                    )
            self._status.task_active = False
            self._status.last_result = result
            self._status.last_result_succeeded = result.succeeded
            self._active_goal_handle = None
            self._active_action_name = None
            
        return result

    async def send_goal(self, waypoint: NavWaypoint) -> bool:
        from nav2_msgs.action import NavigateToPose
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self._create_pose_stamped(waypoint)
        
        result = await self._execute_action(self._ntp_client, goal_msg, "NavigateToPose", self._ntp_feedback_cb)
        return result.succeeded

    async def navigate_to_waypoints(self, waypoints: Sequence[NavWaypoint]) -> bool:
        if not waypoints:
            self._finish_with_result(NavigationResult(
                action_name="FollowWaypoints",
                status=NavigationTerminalStatus.SUCCEEDED,
                succeeded=True
            ))
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
            
        result = await self._execute_action(self._fw_client, goal_msg, "FollowWaypoints", self._fw_feedback_cb)
        return result.succeeded

    async def cancel_navigation(self) -> None:
        with self._state_lock:
            goal_handle = self._active_goal_handle
            action_name = self._active_action_name
            uuid_str = self._status.goal_uuid
            
            if not goal_handle:
                return
                
            if not self._status.last_result:
                self._status.last_result = NavigationResult(
                    action_name=action_name or "",
                    status=NavigationTerminalStatus.ERROR,
                    succeeded=False,
                    cancel_requested=True
                )
            else:
                self._status.last_result = NavigationResult(
                    action_name=self._status.last_result.action_name,
                    status=self._status.last_result.status,
                    succeeded=self._status.last_result.succeeded,
                    goal_uuid=self._status.last_result.goal_uuid,
                    error_code=self._status.last_result.error_code,
                    error_msg=self._status.last_result.error_msg,
                    missed_waypoints=self._status.last_result.missed_waypoints,
                    final_waypoint_index=self._status.last_result.final_waypoint_index,
                    cancel_requested=True,
                    cancel_accepted=self._status.last_result.cancel_accepted
                )
                
        try:
            from action_msgs.srv import CancelGoal
            
            cancel_future = goal_handle.cancel_goal_async()
            aio_cancel_future = self._ros_future_to_asyncio(cancel_future)
            
            cancel_response = await asyncio.wait_for(aio_cancel_future, timeout=self._cancel_response_timeout_s)
            
            accepted = False
            if cancel_response.return_code == CancelGoal.Response.ERROR_NONE:
                for gc in cancel_response.goals_canceling:
                    if self._normalize_uuid(gc.goal_id) == uuid_str:
                        accepted = True
                        break
                        
            with self._state_lock:
                if self._status.last_result:
                    self._status.last_result = NavigationResult(
                        action_name=self._status.last_result.action_name,
                        status=self._status.last_result.status,
                        succeeded=self._status.last_result.succeeded,
                        goal_uuid=self._status.last_result.goal_uuid,
                        error_code=self._status.last_result.error_code,
                        error_msg=self._status.last_result.error_msg,
                        missed_waypoints=self._status.last_result.missed_waypoints,
                        final_waypoint_index=self._status.last_result.final_waypoint_index,
                        cancel_requested=True,
                        cancel_accepted=accepted
                    )
                    
        except Exception:
            pass

    async def inject_absolute_pose(self, pose_estimate: "PoseEstimate") -> None:
        if not self._started or not self._initial_pose_pub:
            return
            
        try:
            import cv2
            import numpy as np
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from builtin_interfaces.msg import Time
            
            msg = PoseWithCovarianceStamped()
            msg.header.frame_id = "map"
            msg.header.stamp = self._node.get_clock().now().to_msg()
            
            msg.pose.pose.position.x = float(pose_estimate.x)
            msg.pose.pose.position.y = float(pose_estimate.y)
            msg.pose.pose.position.z = 0.0
            
            msg.pose.pose.orientation.x = 0.0
            msg.pose.pose.orientation.y = 0.0
            msg.pose.pose.orientation.z = math.sin(pose_estimate.yaw / 2.0)
            msg.pose.pose.orientation.w = math.cos(pose_estimate.yaw / 2.0)
            
            # Covariance matrix 6x6
            cov = np.zeros((6, 6), dtype=np.float64)
            # Position covariance
            cov[0, 0] = pose_estimate.covariance[0, 0]
            cov[0, 1] = pose_estimate.covariance[0, 1]
            cov[1, 0] = pose_estimate.covariance[1, 0]
            cov[1, 1] = pose_estimate.covariance[1, 1]
            # Yaw covariance
            cov[5, 5] = pose_estimate.covariance[2, 2]
            
            msg.pose.covariance = cov.flatten().tolist()
            
            self._initial_pose_pub.publish(msg)
            
        except ImportError:
            pass
