import asyncio
import sys
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any

from src.navigation.models import (
    NavWaypoint,
    NavigationResult,
    NavigationStatus,
    NavigationTerminalStatus,
)
from src.navigation.direct_nav2_action_bridge import DirectNav2ActionBridge

class TestDirectNav2ActionBridge(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = DirectNav2ActionBridge(
            server_timeout_s=0.1,
            goal_response_timeout_s=0.1,
            result_timeout_s=0.1,
            cancel_response_timeout_s=0.1,
            cancel_terminal_timeout_s=0.1
        )
        
    def test_01_init_invalid_timeouts(self):
        with self.assertRaises(ValueError):
            DirectNav2ActionBridge(server_timeout_s=-1.0)
            
    def test_02_imports_without_ros(self):
        self.assertFalse(self.bridge._started)
        
    def test_03_normalize_uuid(self):
        class UuidMsg:
            def __init__(self, uuid_bytes):
                self.uuid = uuid_bytes
        msg = UuidMsg(b'1234567890123456')
        norm = self.bridge._normalize_uuid(msg)
        self.assertEqual(norm, '31323334353637383930313233343536')
        
    def test_04_normalize_uuid_fallback(self):
        norm = self.bridge._normalize_uuid("abc")
        self.assertEqual(norm, "abc")
        
    def test_05_map_goal_status(self):
        class GoalStatusMock:
            STATUS_SUCCEEDED = 4
            STATUS_CANCELED = 5
            STATUS_ABORTED = 6
        
        mock_action_msgs = MagicMock()
        mock_action_msgs.msg.GoalStatus = GoalStatusMock
        with patch.dict('sys.modules', {'action_msgs': mock_action_msgs, 'action_msgs.msg': mock_action_msgs.msg}):
            self.assertEqual(self.bridge._map_goal_status(4), NavigationTerminalStatus.SUCCEEDED)
            self.assertEqual(self.bridge._map_goal_status(5), NavigationTerminalStatus.CANCELED)
            self.assertEqual(self.bridge._map_goal_status(6), NavigationTerminalStatus.ABORTED)
            self.assertEqual(self.bridge._map_goal_status(99), NavigationTerminalStatus.ERROR)

    async def test_06_inject_absolute_pose(self):
        self.bridge._started = True
        self.bridge._initial_pose_pub = MagicMock()
        
        mock_cv2 = MagicMock()
        
        class MockPoseEstimate:
            tvec = [[1.0], [2.0], [0.0]]
            rvec = [[0.0], [0.0], [0.1]]
            covariance = MagicMock()
            
            def __init__(self):
                self.covariance.__getitem__.side_effect = lambda idx: 0.1
        
        class MockMatrix:
            def __getitem__(self, idx):
                if idx == (1, 0): return 0.0
                if idx == (0, 0): return 1.0
                return 0.0
        mock_cv2.Rodrigues.return_value = (MockMatrix(), None)
        
        with patch.dict('sys.modules', {
            'geometry_msgs.msg': MagicMock(),
            'builtin_interfaces.msg': MagicMock(),
            'cv2': mock_cv2
        }):
            self.bridge._node = MagicMock()
            await self.bridge.inject_absolute_pose(MockPoseEstimate())
            
        self.bridge._initial_pose_pub.publish.assert_called_once()
        msg = self.bridge._initial_pose_pub.publish.call_args[0][0]
        self.assertEqual(msg.pose.pose.position.x, 1.0)
        self.assertEqual(msg.pose.covariance[0], 0.15)
        self.assertEqual(msg.pose.covariance[7], 0.15)
        self.assertEqual(msg.pose.covariance[35], 0.40)
        
    async def test_07_inject_not_started(self):
        with self.assertRaisesRegex(RuntimeError, "DIRECT_NAV2_BRIDGE_NOT_STARTED"):
            await self.bridge.inject_absolute_pose(MagicMock())

    async def test_08_inject_no_pub(self):
        self.bridge._started = True
        self.bridge._initial_pose_pub = None
        await self.bridge.inject_absolute_pose(MagicMock()) # Should not raise

    async def test_09_future_adapter(self):
        loop = asyncio.get_running_loop()
        class MockRosFuture:
            def __init__(self):
                self.callbacks = []
            def add_done_callback(self, cb):
                self.callbacks.append(cb)
            def result(self):
                return "res"
        
        ros_f = MockRosFuture()
        aio_f = self.bridge._ros_future_to_asyncio(ros_f)
        
        for cb in ros_f.callbacks:
            cb(ros_f)
            
        await asyncio.sleep(0.01)
        self.assertEqual(aio_f.result(), "res")
        
    async def test_10_future_adapter_exception(self):
        loop = asyncio.get_running_loop()
        class MockRosFuture:
            def __init__(self):
                self.callbacks = []
            def add_done_callback(self, cb):
                self.callbacks.append(cb)
            def result(self):
                raise ValueError("err")
        
        ros_f = MockRosFuture()
        aio_f = self.bridge._ros_future_to_asyncio(ros_f)
        
        for cb in ros_f.callbacks:
            cb(ros_f)
            
        await asyncio.sleep(0.01)
        with self.assertRaises(ValueError):
            aio_f.result()

    async def test_11_second_goal_fails_immediately(self):
        self.bridge._started = True
        self.bridge._status.task_active = True
        
        with self.assertRaisesRegex(RuntimeError, "NAVIGATION_GOAL_ALREADY_ACTIVE"):
            await self.bridge._execute_action(None, None, "test", None)
            
    async def test_12_execute_not_started(self):
        with self.assertRaisesRegex(RuntimeError, "Bridge not started"):
            await self.bridge._execute_action(None, None, "test", None)
        
    async def test_13_navigate_empty_list(self):
        res = await self.bridge.navigate_to_waypoints([])
        self.assertTrue(res)
        
    async def test_14_cancel_no_active(self):
        self.bridge._status.task_active = False
        await self.bridge.cancel_navigation()
        self.assertFalse(self.bridge._cancel_requested)

    async def test_15_close_idempotent(self):
        self.bridge._started = True
        self.bridge._active_goal_handle = MagicMock()
        self.bridge._active_goal_handle.cancel_goal_async.side_effect = Exception("err")
        await self.bridge.close()
        self.assertFalse(self.bridge._started)
        await self.bridge.close()

    def test_16_create_pose_stamped(self):
        with patch.dict('sys.modules', {'geometry_msgs.msg': MagicMock()}):
            self.bridge._node = MagicMock()
            wp = NavWaypoint(1.0, 2.0, 3.14, "map")
            msg = self.bridge._create_pose_stamped(wp)
            self.assertEqual(msg.header.frame_id, "map")
            self.assertEqual(msg.pose.position.x, 1.0)
            self.assertEqual(msg.pose.position.y, 2.0)

    async def test_17_is_navigation_active(self):
        self.assertFalse(await self.bridge.is_navigation_active())
        self.bridge._status.task_active = True
        self.assertTrue(await self.bridge.is_navigation_active())

    async def test_18_get_status_copy(self):
        self.bridge._status.task_active = True
        st = await self.bridge.get_status()
        self.assertTrue(st.task_active)
        st.task_active = False
        self.assertTrue(self.bridge._status.task_active)

    async def test_19_get_last_result(self):
        res = NavigationResult("test", NavigationTerminalStatus.SUCCEEDED, True)
        self.bridge._status.last_result = res
        self.assertEqual(await self.bridge.get_last_result(), res)

    def test_20_ntp_feedback_cb(self):
        cb = MagicMock()
        cb.feedback.distance_remaining = 5.0
        self.bridge._ntp_feedback_cb(cb)
        self.assertEqual(self.bridge._status.distance_remaining_m, 5.0)
        self.assertEqual(self.bridge._status.feedback_count, 1)

    def test_21_fw_feedback_cb(self):
        cb = MagicMock()
        cb.feedback.current_waypoint = 2
        self.bridge._fw_feedback_cb(cb)
        self.assertEqual(self.bridge._status.active_waypoint_index, 2)
        self.assertEqual(self.bridge._status.feedback_count, 1)

    async def test_22_result_monitor_timeout(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        res = await self.bridge._result_monitor_task(MagicMock(), future, "test", "uuid1")
        self.assertFalse(res.succeeded)
        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)

    async def test_23_result_monitor_exception(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_exception(ValueError("error in future"))
        res = await self.bridge._result_monitor_task(MagicMock(), future, "test", "uuid2")
        self.assertFalse(res.succeeded)
        self.assertEqual(res.status, NavigationTerminalStatus.ERROR)

    async def test_24_result_monitor_success(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        class MockResult:
            status = 4 # SUCCEEDED in map_goal_status mock below
            result = MagicMock()
            
        future.set_result(MockResult())
        
        self.bridge._map_goal_status = MagicMock(return_value=NavigationTerminalStatus.SUCCEEDED)
        res = await self.bridge._result_monitor_task(MagicMock(), future, "test", "uuid3")
        self.assertTrue(res.succeeded)
        self.assertEqual(res.status, NavigationTerminalStatus.SUCCEEDED)

    async def test_25_execute_goal_rejected(self):
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_result(MagicMock(accepted=False))
        
        def mock_ros_to_async(f):
            return future
            
        self.bridge._ros_future_to_asyncio = mock_ros_to_async
        client.send_goal_async.return_value = MagicMock()
        
        with patch.dict('sys.modules', {'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock()}):
            res = await self.bridge._execute_action(client, MagicMock(), "test", None)
            
        self.assertFalse(res.succeeded)
        self.assertEqual(res.status, NavigationTerminalStatus.REJECTED)

    async def test_26_execute_goal_response_timeout(self):
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        def mock_ros_to_async(f):
            return future
            
        self.bridge._ros_future_to_asyncio = mock_ros_to_async
        client.send_goal_async.return_value = future
        
        with patch.dict('sys.modules', {'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock()}):
            res = await self.bridge._execute_action(client, MagicMock(), "test", None)
            
        self.assertFalse(res.succeeded)
        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)

    async def test_27_cancel_response_timeout(self):
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_handle = MagicMock()
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        def mock_ros_to_async(f):
            return future
            
        self.bridge._ros_future_to_asyncio = mock_ros_to_async
        
        with patch.dict('sys.modules', {'action_msgs.srv': MagicMock()}):
            with self.assertRaisesRegex(RuntimeError, "Cancel response timeout"):
                await self.bridge.cancel_navigation()

    async def test_28_cancel_not_accepted(self):
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_handle = MagicMock()
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        class MockCancelResponse:
            return_code = 99 # ERROR
            
        future.set_result(MockCancelResponse())
        
        def mock_ros_to_async(f):
            return future
            
        self.bridge._ros_future_to_asyncio = mock_ros_to_async
        
        mock_srv = MagicMock()
        mock_srv.CancelGoal.Response.ERROR_NONE = 0
        with patch.dict('sys.modules', {'action_msgs.srv': mock_srv}):
            with self.assertRaisesRegex(RuntimeError, "CANCEL_REQUEST_NOT_ACCEPTED"):
                await self.bridge.cancel_navigation()

    async def test_29_cancel_uuid_absent(self):
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidx"
        self.bridge._active_goal_handle = MagicMock()
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        class MockGoalCancel:
            goal_id = "uuidy"
            
        class MockCancelResponse:
            return_code = 0
            goals_canceling = [MockGoalCancel()]
            
        future.set_result(MockCancelResponse())
        
        def mock_ros_to_async(f):
            return future
            
        self.bridge._ros_future_to_asyncio = mock_ros_to_async
        
        mock_srv = MagicMock()
        mock_srv.CancelGoal.Response.ERROR_NONE = 0
        with patch.dict('sys.modules', {'action_msgs.srv': mock_srv}):
            with self.assertRaisesRegex(RuntimeError, "CANCEL_REQUEST_NOT_ACCEPTED"):
                await self.bridge.cancel_navigation()

    async def test_30_cancel_accepted_and_terminal_timeout(self):
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidx"
        self.bridge._active_goal_handle = MagicMock()
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        res_future = loop.create_future()
        self.bridge._active_result_task = res_future # Will timeout
        
        class MockGoalCancel:
            goal_id = "uuidx"
            
        class MockCancelResponse:
            return_code = 0
            goals_canceling = [MockGoalCancel()]
            
        future.set_result(MockCancelResponse())
        
        def mock_ros_to_async(f):
            return future
            
        self.bridge._ros_future_to_asyncio = mock_ros_to_async
        
        mock_srv = MagicMock()
        mock_srv.CancelGoal.Response.ERROR_NONE = 0
        with patch.dict('sys.modules', {'action_msgs.srv': mock_srv}):
            with self.assertRaisesRegex(TimeoutError, "CANCEL_TERMINAL_TIMEOUT"):
                await self.bridge.cancel_navigation()
                
    async def test_31_cancel_accepted_and_terminal_success(self):
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidx"
        self.bridge._active_goal_handle = MagicMock()
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        res_future = loop.create_future()
        res_future.set_result(NavigationResult("test", NavigationTerminalStatus.CANCELED, False))
        self.bridge._active_result_task = res_future
        
        class MockGoalCancel:
            goal_id = "uuidx"
            
        class MockCancelResponse:
            return_code = 0
            goals_canceling = [MockGoalCancel()]
            
        future.set_result(MockCancelResponse())
        
        def mock_ros_to_async(f):
            return future
            
        self.bridge._ros_future_to_asyncio = mock_ros_to_async
        
        mock_srv = MagicMock()
        mock_srv.CancelGoal.Response.ERROR_NONE = 0
        with patch.dict('sys.modules', {'action_msgs.srv': mock_srv}):
            await self.bridge.cancel_navigation()
            self.assertTrue(self.bridge._cancel_accepted)

    async def test_32_spin_thread_alive(self):
        self.bridge._started = True
        self.bridge._spin_thread = MagicMock()
        self.bridge._spin_thread.is_alive.return_value = True
        with self.assertRaisesRegex(RuntimeError, "DIRECT_BRIDGE_SPIN_THREAD_STILL_ALIVE"):
            await self.bridge.close()

if __name__ == '__main__':
    unittest.main()
