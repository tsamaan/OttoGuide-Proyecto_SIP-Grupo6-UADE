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

    async def test_15_close_reports_degraded_remote_state_and_is_then_idempotent(self):
        loop = asyncio.get_running_loop()
        res_future = loop.create_future()  # never resolves: result task never completes
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_handle = MagicMock()
        self.bridge._active_goal_handle.cancel_goal_async.side_effect = Exception("err")
        self.bridge._active_result_task = res_future

        with self.assertRaisesRegex(RuntimeError, "DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN"):
            await self.bridge.close()
        self.assertFalse(self.bridge._started)
        self.assertFalse(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)

        # Second close: nothing left to cancel/wait on (idempotent in
        # effects -- no resources to repeat), but the historical
        # degradation is preserved and may be reported again.
        with self.assertRaisesRegex(RuntimeError, "DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN"):
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

class TestDirectNav2ActionBridgeOwnershipAndTerminalSafety(unittest.IsolatedAsyncioTestCase):
    """2H.1.2: ownership of terminal state, cancellation, timeouts and pose injection.

    Reproduces and then verifies the fix for each defect confirmed in the
    49a998c audit (see section 8 of the 2H.1.2 spec): self-await on timeout,
    inferred cleanup from the local ERROR/TIMEOUT enum, missing CANCELED
    enforcement on cancel, unsafe exception-after-acceptance handling,
    unsafe goal-response timeout, and the silent ImportError on pose
    injection.
    """

    def setUp(self):
        self.bridge = DirectNav2ActionBridge(
            server_timeout_s=0.1,
            goal_response_timeout_s=0.1,
            result_timeout_s=0.1,
            cancel_response_timeout_s=0.1,
            cancel_terminal_timeout_s=0.1
        )

    @staticmethod
    def _accepted_cancel_response(uuid_str):
        class MockGoalCancel:
            goal_id = uuid_str
        class MockCancelResponse:
            return_code = 0
            goals_canceling = [MockGoalCancel()]
        return MockCancelResponse()

    @staticmethod
    def _cancel_goal_srv_module():
        mock_srv = MagicMock()
        mock_srv.CancelGoal.Response.ERROR_NONE = 0
        return mock_srv

    async def test_33_monitor_timeout_never_calls_public_cancel_navigation_and_is_bounded(self):
        """1+2: the monitor's timeout path must not self-await via the
        public cancel_navigation() (which would wait on this same task);
        it must use the internal helper and stay bounded in time."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidm"
        self.bridge._active_goal_handle = MagicMock()

        loop = asyncio.get_running_loop()
        never_resolves = loop.create_future()
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response("uuidm"))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future
        self.bridge.cancel_navigation = AsyncMock()

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            start = loop.time()
            res = await asyncio.wait_for(
                self.bridge._result_monitor_task(MagicMock(), never_resolves, "test", "uuidm"),
                timeout=2.0
            )
            elapsed = loop.time() - start

        self.bridge.cancel_navigation.assert_not_called()
        self.assertLess(elapsed, 2.0)
        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)

    async def test_34_cancel_terminal_not_canceled_raises(self):
        """4: a confirmed terminal that is not CANCELED after an accepted
        cancel must raise, never just warn."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidx"
        self.bridge._active_goal_handle = MagicMock()

        loop = asyncio.get_running_loop()
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response("uuidx"))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future

        res_future = loop.create_future()
        res_future.set_result(NavigationResult("test", NavigationTerminalStatus.ABORTED, False))
        self.bridge._active_result_task = res_future

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            with self.assertRaisesRegex(RuntimeError, "CANCEL_TERMINAL_NOT_CANCELED"):
                await self.bridge.cancel_navigation()

    async def test_35_result_timeout_with_confirmed_cancel_yields_timeout_and_cleans_up(self):
        """6: result timeout + accepted cancel + confirmed CANCELED terminal
        produces a local TIMEOUT result and fully cleans up state."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidt"
        self.bridge._active_goal_handle = MagicMock()

        loop = asyncio.get_running_loop()
        result_future = loop.create_future()
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response("uuidt"))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future
        self.bridge._map_goal_status = MagicMock(return_value=NavigationTerminalStatus.CANCELED)

        async def resolve_later():
            await asyncio.sleep(0.15)
            if not result_future.done():
                result_future.set_result(MagicMock())
        asyncio.create_task(resolve_later())

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            res = await asyncio.wait_for(
                self.bridge._result_monitor_task(MagicMock(), result_future, "test", "uuidt"),
                timeout=2.0
            )

        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)
        self.assertFalse(self.bridge._status.task_active)
        self.assertIsNone(self.bridge._active_goal_handle)
        self.assertFalse(self.bridge._status.remote_state_unknown)

    async def test_36_result_timeout_without_confirmed_cancel_keeps_task_active(self):
        """7: result timeout with no confirmed terminal must keep the goal
        marked active and the remote state explicitly unknown."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidn"
        self.bridge._active_goal_handle = MagicMock()

        loop = asyncio.get_running_loop()
        result_future = loop.create_future()  # never resolves, even on the secondary wait
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response("uuidn"))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            res = await asyncio.wait_for(
                self.bridge._result_monitor_task(MagicMock(), result_future, "test", "uuidn"),
                timeout=2.0
            )

        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)
        self.assertTrue(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)
        self.assertIsNotNone(self.bridge._active_goal_handle)

    async def test_37_exception_after_acceptance_requests_cancel_and_keeps_active_without_terminal(self):
        """8+9: an exception raised strictly after goal_handle.accepted=True
        must request cancellation via the internal helper and, absent a
        confirmed terminal, must keep the goal marked active (never cleaned
        up by _execute_action's except block as a plain ERROR)."""
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()

        accepted_handle = MagicMock()
        accepted_handle.accepted = True
        accepted_handle.goal_id = MagicMock(uuid=b'1234567890123456')
        accepted_handle.get_result_async.side_effect = RuntimeError("get_result_async boom")

        accept_future = loop.create_future()
        accept_future.set_result(accepted_handle)

        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response(self.bridge._normalize_uuid(accepted_handle.goal_id)))

        sentinel_cancel_raw = object()
        accepted_handle.cancel_goal_async.return_value = sentinel_cancel_raw

        def mock_ros_to_async(f):
            return cancel_future if f is sentinel_cancel_raw else accept_future
        self.bridge._ros_future_to_asyncio = mock_ros_to_async

        with patch.dict('sys.modules', {
            'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock(),
            'action_msgs.srv': self._cancel_goal_srv_module()
        }):
            res = await self.bridge._execute_action(client, MagicMock(), "test", None)

        self.assertEqual(res.status, NavigationTerminalStatus.ERROR)
        accepted_handle.cancel_goal_async.assert_called_once()
        self.assertTrue(self.bridge._status.task_active)
        self.assertIsNotNone(self.bridge._active_goal_handle)
        self.assertTrue(self.bridge._status.remote_state_unknown)

    def test_38_finalize_result_error_without_terminal_confirmed_preserves_active_goal(self):
        """10: _finalize_result must never infer a confirmed terminal from
        the local ERROR/TIMEOUT enum value; only the explicit
        terminal_confirmed flag governs cleanup."""
        self.bridge._status.task_active = True
        self.bridge._active_goal_handle = MagicMock()
        self.bridge._active_goal_uuid = "uuid-keep"

        self.bridge._finalize_result(
            NavigationResult("test", NavigationTerminalStatus.ERROR, False),
            terminal_confirmed=False
        )

        self.assertTrue(self.bridge._status.task_active)
        self.assertIsNotNone(self.bridge._active_goal_handle)
        self.assertEqual(self.bridge._active_goal_uuid, "uuid-keep")
        self.assertTrue(self.bridge._status.remote_state_unknown)

    async def test_39_goal_response_timeout_preserves_uuid_and_blocks_second_goal(self):
        """11+12: goal-response timeout must preserve the locally generated
        UUID for diagnostics and must block a second goal until close()."""
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.bridge._ros_future_to_asyncio = lambda f: future
        client.send_goal_async.return_value = future

        with patch.dict('sys.modules', {'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock()}):
            res = await self.bridge._execute_action(client, MagicMock(), "test", None)

        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)
        self.assertTrue(res.goal_uuid)
        self.assertTrue(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)

        with self.assertRaisesRegex(RuntimeError, "NAVIGATION_GOAL_ALREADY_ACTIVE"):
            await self.bridge._execute_action(client, MagicMock(), "test2", None)

    async def test_40_inject_absolute_pose_propagates_missing_dependency(self):
        """13: a missing pose dependency must propagate explicitly, never
        report silent success without publishing /initialpose."""
        self.bridge._started = True
        self.bridge._initial_pose_pub = MagicMock()
        with patch.dict('sys.modules', {'cv2': None}):
            with self.assertRaisesRegex(RuntimeError, "INITIAL_POSE_DEPENDENCY_UNAVAILABLE"):
                await self.bridge.inject_absolute_pose(MagicMock())
        self.bridge._initial_pose_pub.publish.assert_not_called()

    async def test_41_late_callback_on_cancelled_future_does_not_raise(self):
        """14: a ROS-thread callback firing after the asyncio future was
        already cancelled must not raise asyncio.InvalidStateError."""
        class MockRosFuture:
            def __init__(self):
                self.callbacks = []
            def add_done_callback(self, cb):
                self.callbacks.append(cb)
            def result(self):
                return "late result"

        ros_f = MockRosFuture()
        aio_f = self.bridge._ros_future_to_asyncio(ros_f)
        aio_f.cancel()

        loop = asyncio.get_running_loop()
        captured = []
        loop.set_exception_handler(lambda l, ctx: captured.append(ctx))
        try:
            for cb in ros_f.callbacks:
                cb(ros_f)
            await asyncio.sleep(0.01)
        finally:
            loop.set_exception_handler(None)

        self.assertEqual(captured, [])
        self.assertTrue(aio_f.cancelled())

    async def test_42_callback_with_closed_loop_does_not_schedule_or_raise(self):
        """15: a done_callback firing from the ROS spin thread after the
        asyncio loop reports closed must not attempt to schedule on it."""
        class MockRosFuture:
            def __init__(self):
                self.callbacks = []
            def add_done_callback(self, cb):
                self.callbacks.append(cb)
            def result(self):
                return "result"

        ros_f = MockRosFuture()
        aio_f = self.bridge._ros_future_to_asyncio(ros_f)

        loop = asyncio.get_running_loop()
        with patch.object(loop, 'is_closed', return_value=True):
            with patch.object(loop, 'call_soon_threadsafe') as mock_schedule:
                for cb in ros_f.callbacks:
                    cb(ros_f)
                mock_schedule.assert_not_called()

        self.assertFalse(aio_f.done())

    async def test_43_get_status_does_not_share_internal_status_instance(self):
        """19: get_status() must never expose the live internal object;
        mutating the returned copy must not affect bridge state."""
        self.bridge._status.task_active = True
        self.bridge._status.last_result = NavigationResult("test", NavigationTerminalStatus.SUCCEEDED, True)

        st1 = await self.bridge.get_status()
        st2 = await self.bridge.get_status()

        self.assertIsNot(st1, st2)
        self.assertIsNot(st1, self.bridge._status)
        st1.task_active = False
        st1.feedback_count = 999
        self.assertTrue(self.bridge._status.task_active)
        self.assertEqual(self.bridge._status.feedback_count, 0)

    async def test_44_cancel_navigation_actually_awaits_monitor_completion(self):
        """3: the public cancel_navigation() must genuinely await the
        monitor task's completion, not return as soon as cancel is
        accepted."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidw"
        self.bridge._active_goal_handle = MagicMock()

        loop = asyncio.get_running_loop()
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response("uuidw"))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future

        res_future = loop.create_future()
        self.bridge._active_result_task = res_future

        async def resolve_later():
            await asyncio.sleep(0.05)
            res_future.set_result(NavigationResult("test", NavigationTerminalStatus.CANCELED, False))
        asyncio.create_task(resolve_later())

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            start = loop.time()
            await self.bridge.cancel_navigation()
            elapsed = loop.time() - start

        self.assertGreaterEqual(elapsed, 0.04)

    async def test_45_close_detects_preexisting_remote_state_unknown_with_done_result_task(self):
        """2H.1.3 #1: degraded state must be detected from what is already
        true at entry (remote_state_unknown=True), even when there is no
        goal handle to cancel and the result task already completed."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._status.remote_state_unknown = True
        self.bridge._active_goal_handle = None

        loop = asyncio.get_running_loop()
        done_future = loop.create_future()
        done_future.set_result(NavigationResult("test", NavigationTerminalStatus.TIMEOUT, False))
        self.bridge._active_result_task = done_future

        with self.assertRaisesRegex(RuntimeError, "DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN"):
            await self.bridge.close()

        self.assertFalse(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)

    async def test_46_close_after_goal_response_timeout_raises_remote_state_unknown(self):
        """2H.1.3 #2: a goal-response timeout never creates a goal handle
        or a result task, so close() must still detect the degradation
        from task_active=True with no handle, not from a reactive
        cancel/wait failure (there is nothing to react to)."""
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()
        future = loop.create_future()  # never resolves -> goal response timeout
        self.bridge._ros_future_to_asyncio = lambda f: future
        client.send_goal_async.return_value = future

        with patch.dict('sys.modules', {
            'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock()
        }):
            res = await self.bridge._execute_action(client, MagicMock(), "test", None)
        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)

        self.assertIsNone(self.bridge._active_goal_handle)
        self.assertIsNone(self.bridge._active_result_task)
        self.assertTrue(self.bridge._status.task_active)

        with self.assertRaisesRegex(RuntimeError, "DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN"):
            await self.bridge.close()

    async def test_47_close_clean_called_twice_does_not_raise(self):
        """2H.1.3 #3: a clean close (no active goal, no remote state
        unknown) must remain idempotent across repeated calls."""
        self.bridge._started = True
        await self.bridge.close()
        self.assertFalse(self.bridge._status.task_active)
        self.assertFalse(self.bridge._status.remote_state_unknown)
        await self.bridge.close()
        self.assertFalse(self.bridge._status.remote_state_unknown)

    def _arm_accepted_cancel_without_result_task(self, uuid_str="uuidz"):
        """Shared precondition for 2H.1.4 #1-#3: a goal accepted by the
        server (handle + UUID present) for which get_result_async()/the
        monitor task creation failed before ever producing a result task --
        the exact state described in section 7 of the 2H.1.4 spec."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = uuid_str
        self.bridge._active_goal_handle = MagicMock()
        self.bridge._active_result_task = None

        loop = asyncio.get_running_loop()
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response(uuid_str))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future

    async def test_48_cancel_accepted_without_result_monitor_raises_unobservable(self):
        """2H.1.4 #1: CancelGoal acceptance is evidence the server *received*
        the request, never evidence the goal actually terminated CANCELED.
        Without a result task to observe the real GoalStatus, the bridge
        must not return normally (that would assert an unobserved
        cancellation); it must raise CANCEL_TERMINAL_UNOBSERVABLE and leave
        every piece of state exactly as the spec requires."""
        self._arm_accepted_cancel_without_result_task("uuidz")

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            with self.assertRaisesRegex(RuntimeError, "CANCEL_TERMINAL_UNOBSERVABLE"):
                await self.bridge.cancel_navigation()

        self.assertTrue(self.bridge._cancel_requested)
        self.assertTrue(self.bridge._cancel_accepted)
        self.assertTrue(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)
        self.assertIsNotNone(self.bridge._active_goal_handle)
        self.assertEqual(self.bridge._active_goal_uuid, "uuidz")

    async def test_49_second_goal_blocked_after_unobservable_cancel(self):
        """2H.1.4 #2: the degraded, unconfirmed-cancel state must keep
        blocking new goals, exactly like every other unconfirmed-terminal
        path already covered for 2H.1.2/2H.1.3."""
        self._arm_accepted_cancel_without_result_task("uuidz")

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            with self.assertRaisesRegex(RuntimeError, "CANCEL_TERMINAL_UNOBSERVABLE"):
                await self.bridge.cancel_navigation()

        with self.assertRaisesRegex(RuntimeError, "NAVIGATION_GOAL_ALREADY_ACTIVE"):
            await self.bridge._execute_action(None, None, "test2", None)

    async def test_50_close_after_unobservable_cancel_tears_down_and_raises(self):
        """2H.1.4 #3: close() must still perform the full local teardown
        and report the historical degradation, without inventing a
        terminal for the goal it could never observe."""
        self._arm_accepted_cancel_without_result_task("uuidz")

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            with self.assertRaisesRegex(RuntimeError, "CANCEL_TERMINAL_UNOBSERVABLE"):
                await self.bridge.cancel_navigation()

            with self.assertRaisesRegex(RuntimeError, "DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN"):
                await self.bridge.close()

        self.assertFalse(self.bridge._started)
        self.assertFalse(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)
        self.assertIsNone(self.bridge._active_goal_handle)
        self.assertIsNone(self.bridge._active_result_task)

    async def test_51_cancel_with_result_monitor_present_does_not_raise_unobservable(self):
        """2H.1.4 regression: when a result task IS observable and resolves
        to CANCELED, cancel_navigation() must keep returning normally --
        the new guard must trigger only on a missing monitor, never on a
        present one."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidp"
        self.bridge._active_goal_handle = MagicMock()

        loop = asyncio.get_running_loop()
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response("uuidp"))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future

        res_task = loop.create_future()
        res_task.set_result(NavigationResult("test", NavigationTerminalStatus.CANCELED, False))
        self.bridge._active_result_task = res_task

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            await self.bridge.cancel_navigation()  # must not raise

        self.assertTrue(self.bridge._cancel_accepted)

    async def test_52_cancel_with_result_monitor_wrong_terminal_raises_not_canceled(self):
        """2H.1.4 regression: a present, resolved result task that did NOT
        confirm CANCELED must still raise CANCEL_TERMINAL_NOT_CANCELED
        (the 2H.1.2 contract), not the new CANCEL_TERMINAL_UNOBSERVABLE --
        these are deliberately distinct failure modes."""
        self.bridge._started = True
        self.bridge._status.task_active = True
        self.bridge._active_goal_uuid = "uuidq"
        self.bridge._active_goal_handle = MagicMock()

        loop = asyncio.get_running_loop()
        cancel_future = loop.create_future()
        cancel_future.set_result(self._accepted_cancel_response("uuidq"))
        self.bridge._ros_future_to_asyncio = lambda f: cancel_future

        res_task = loop.create_future()
        res_task.set_result(NavigationResult("test", NavigationTerminalStatus.SUCCEEDED, True))
        self.bridge._active_result_task = res_task

        with patch.dict('sys.modules', {'action_msgs.srv': self._cancel_goal_srv_module()}):
            with self.assertRaisesRegex(RuntimeError, "CANCEL_TERMINAL_NOT_CANCELED"):
                await self.bridge.cancel_navigation()

    async def test_53_cancel_inactive_is_noop_and_never_requests_cancel(self):
        """2H.1.5 #1: with no navigation active (task_active=False), cancel_navigation()
        must keep returning normally without ever attempting a CancelGoal request,
        regardless of whatever stale goal_handle/result_task values remain."""
        self.bridge._status.task_active = False
        self.bridge._active_goal_handle = None
        self.bridge._active_result_task = None
        self.bridge._request_cancel_only = AsyncMock()

        await self.bridge.cancel_navigation()  # must not raise

        self.bridge._request_cancel_only.assert_not_called()
        self.assertFalse(self.bridge._status.remote_state_unknown)

    async def test_54_single_waypoint_delegates_to_send_goal_not_follow_waypoints(self):
        """Commit 4: navigate_to_waypoints([wp]) must call send_goal(), never
        touch FollowWaypoints or require _fw_available."""
        self.bridge._fw_available = False  # FW server absent — single-wp must still work
        wp = NavWaypoint(1.0, 2.0, 0.0, "map")
        self.bridge.send_goal = AsyncMock(return_value=True)

        result = await self.bridge.navigate_to_waypoints([wp])

        self.assertTrue(result)
        self.bridge.send_goal.assert_awaited_once_with(wp)

    async def test_55_multi_waypoint_fw_unavailable_returns_false(self):
        """Commit 4: navigate_to_waypoints([wp1, wp2]) must return False and
        record an ERROR result when _fw_available is False."""
        self.bridge._fw_available = False
        wp1 = NavWaypoint(1.0, 2.0, 0.0, "map")
        wp2 = NavWaypoint(3.0, 4.0, 0.0, "map")

        result = await self.bridge.navigate_to_waypoints([wp1, wp2])

        self.assertFalse(result)
        self.assertIsNotNone(self.bridge._status.last_result)
        self.assertEqual(self.bridge._status.last_result.status, NavigationTerminalStatus.ERROR)
        self.assertFalse(self.bridge._status.last_result_succeeded)

    async def test_56_start_sets_fw_available_false_when_fw_server_absent(self):
        """Commit 4: when NTP is ready but FW is not, start() must succeed,
        set _ntp_available=True, and set _fw_available=False.

        Tested via run_in_executor simulation: we bypass the real rclpy init
        by making run_in_executor return (True, False) for the two wait calls.
        """
        ntp_client = MagicMock()
        ntp_client.wait_for_server.return_value = True
        fw_client = MagicMock()
        fw_client.wait_for_server.return_value = False

        call_index = [0]
        executor_results = [True, False]

        original_run = asyncio.get_event_loop().run_in_executor

        async def fake_run_in_executor(pool, fn, *args):
            idx = call_index[0]
            call_index[0] += 1
            return executor_results[idx] if idx < len(executor_results) else True

        mock_rclpy = MagicMock()
        mock_rclpy.context.Context.return_value = MagicMock()
        mock_rclpy.create_node.return_value = MagicMock()

        mock_spin_thread = MagicMock()
        mock_spin_thread.is_alive.return_value = False

        with patch.dict('sys.modules', {
            'rclpy': mock_rclpy,
            'rclpy.context': mock_rclpy.context,
            'geometry_msgs.msg': MagicMock(),
            'nav2_msgs.action': MagicMock(),
            'rclpy.action': MagicMock(),
            'rclpy.executors': MagicMock(),
        }):
            with patch('threading.Thread', return_value=mock_spin_thread):
                loop = asyncio.get_running_loop()
                with patch.object(loop, 'run_in_executor', side_effect=fake_run_in_executor):
                    await self.bridge.start()

        self.assertTrue(self.bridge._started)
        self.assertTrue(self.bridge._ntp_available)
        self.assertFalse(self.bridge._fw_available)

    async def test_54_goal_response_timeout_then_cancel_raises_handle_unavailable(self):
        """2H.1.5 #2: reproduces the exact defect of section 7 -- a real
        goal-response timeout leaves task_active=True, remote_state_unknown=True,
        a generated goal_uuid, but no goal handle and no result task. Calling
        the public cancel_navigation() in that state must never return
        normally (that would silently assert an unobservable cancellation
        request never even sent); it must raise CANCEL_GOAL_HANDLE_UNAVAILABLE
        and preserve every diagnostic field."""
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()
        never_resolves = loop.create_future()
        self.bridge._ros_future_to_asyncio = lambda f: never_resolves
        client.send_goal_async.return_value = never_resolves

        with patch.dict('sys.modules', {
            'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock()
        }):
            res = await self.bridge._execute_action(client, MagicMock(), "test", None)

        self.assertEqual(res.status, NavigationTerminalStatus.TIMEOUT)
        self.assertTrue(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)
        self.assertIsNone(self.bridge._active_goal_handle)
        self.assertIsNone(self.bridge._active_result_task)
        self.assertIsNone(self.bridge._active_goal_uuid)
        preserved_uuid = self.bridge._status.goal_uuid
        self.assertTrue(preserved_uuid)

        with self.assertRaisesRegex(RuntimeError, "CANCEL_GOAL_HANDLE_UNAVAILABLE"):
            await self.bridge.cancel_navigation()

        self.assertTrue(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)
        self.assertEqual(self.bridge._status.goal_uuid, preserved_uuid)

    async def test_55_second_goal_blocked_after_handle_unavailable_cancel(self):
        """2H.1.5 #3: the CANCEL_GOAL_HANDLE_UNAVAILABLE degraded state must
        keep blocking a second goal, exactly like every other unconfirmed
        path already covered for 2H.1.2/2H.1.3/2H.1.4."""
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()
        never_resolves = loop.create_future()
        self.bridge._ros_future_to_asyncio = lambda f: never_resolves
        client.send_goal_async.return_value = never_resolves

        with patch.dict('sys.modules', {
            'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock()
        }):
            await self.bridge._execute_action(client, MagicMock(), "test", None)

        with self.assertRaisesRegex(RuntimeError, "CANCEL_GOAL_HANDLE_UNAVAILABLE"):
            await self.bridge.cancel_navigation()

        with self.assertRaisesRegex(RuntimeError, "NAVIGATION_GOAL_ALREADY_ACTIVE"):
            await self.bridge._execute_action(client, MagicMock(), "test2", None)

    async def test_56_close_after_handle_unavailable_tears_down_and_raises(self):
        """2H.1.5 #4: close() after a CANCEL_GOAL_HANDLE_UNAVAILABLE cancel
        attempt must still complete the full local teardown and report the
        historical degradation, never inventing a terminal for a goal it
        could never reach."""
        self.bridge._started = True
        client = MagicMock()
        loop = asyncio.get_running_loop()
        never_resolves = loop.create_future()
        self.bridge._ros_future_to_asyncio = lambda f: never_resolves
        client.send_goal_async.return_value = never_resolves

        with patch.dict('sys.modules', {
            'uuid': MagicMock(), 'unique_identifier_msgs': MagicMock(), 'unique_identifier_msgs.msg': MagicMock()
        }):
            await self.bridge._execute_action(client, MagicMock(), "test", None)

        with self.assertRaisesRegex(RuntimeError, "CANCEL_GOAL_HANDLE_UNAVAILABLE"):
            await self.bridge.cancel_navigation()

        with self.assertRaisesRegex(RuntimeError, "DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN"):
            await self.bridge.close()

        self.assertFalse(self.bridge._started)
        self.assertFalse(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)
        self.assertIsNone(self.bridge._active_goal_handle)
        self.assertIsNone(self.bridge._active_result_task)

    async def test_57_active_without_handle_but_with_stale_result_task_still_guards(self):
        """2H.1.5 #5: an inconsistent state with task_active=True, no goal
        handle, but a (stale/leftover) result_task present must still raise
        CANCEL_GOAL_HANDLE_UNAVAILABLE -- a result task is never a substitute
        for actually being able to send CancelGoal, and must not be awaited
        as if it were one."""
        self.bridge._status.task_active = True
        self.bridge._active_goal_handle = None

        loop = asyncio.get_running_loop()
        stale_result_task = loop.create_future()
        self.bridge._active_result_task = stale_result_task
        self.bridge._request_cancel_only = AsyncMock()

        with self.assertRaisesRegex(RuntimeError, "CANCEL_GOAL_HANDLE_UNAVAILABLE"):
            await self.bridge.cancel_navigation()

        self.bridge._request_cancel_only.assert_not_called()
        self.assertFalse(stale_result_task.done())
        self.assertTrue(self.bridge._status.task_active)
        self.assertTrue(self.bridge._status.remote_state_unknown)


if __name__ == '__main__':
    unittest.main()
