"""ROS 2 receiver for validated local Unitree capture datagrams."""

import os
import time
from typing import Dict, Optional

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Imu, Joy
from std_msgs.msg import String, UInt32

from .protocol import (
    ALLOWED_TOPICS,
    SOCK_PATH,
    ParseError,
    assert_not_prohibited,
    create_ros_socket_server,
    keys_to_buttons,
    make_imu_dict,
    packet_age_seconds,
    receive_packet,
)


class UnitreeCaptureBridge(Node):
    def __init__(self) -> None:
        super().__init__("ottoguide_unitree_capture_bridge")
        sensor_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        reliable_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        for topic in ALLOWED_TOPICS:
            assert_not_prohibited(topic)

        self._pub_joy = self.create_publisher(
            Joy, "/unitree/remote_joy", sensor_qos)
        self._pub_lowstate_imu = self.create_publisher(
            Imu, "/unitree/lowstate_imu", sensor_qos)
        self._pub_secondary_imu = self.create_publisher(
            Imu, "/unitree/secondary_imu", sensor_qos)
        self._pub_fsm = self.create_publisher(
            UInt32, "/unitree/fsm_state", reliable_qos)
        self._pub_summary = self.create_publisher(
            String, "/unitree/lowstate_summary", sensor_qos)
        self._pub_health = self.create_publisher(
            DiagnosticArray, "/unitree/sdk_health", reliable_qos)

        self._socket = None
        self._socket_error = ""
        try:
            self._socket = create_ros_socket_server()
        except Exception as exc:
            self._socket_error = str(exc)
            self.get_logger().error("IPC socket unavailable: {}".format(exc))

        self._stats = {
            "rx_lowstate": 0,
            "rx_secondary_imu": 0,
            "rx_sport_state": 0,
            "rx_health": 0,
            "parse_errors": 0,
            "socket_errors": 0,
        }
        self._last_fsm: Optional[int] = None
        self._last_valid_seen: Optional[float] = None
        self._last_health_seen: Optional[float] = None
        self._last_health: Dict[str, object] = {}
        self._last_source_age = 0.0

        self.create_timer(0.005, self._poll_ipc)
        self.create_timer(1.0, self._publish_health)
        self.get_logger().info(
            "capture bridge started; topics={}".format(sorted(ALLOWED_TOPICS)))

    def _poll_ipc(self) -> None:
        if self._socket is None:
            return
        for _ in range(20):
            try:
                packet = receive_packet(self._socket)
            except ParseError as exc:
                self._stats["parse_errors"] += 1
                self.get_logger().warning("invalid datagram: {}".format(exc))
                continue
            except OSError as exc:
                self._stats["socket_errors"] += 1
                self._socket_error = str(exc)
                self.get_logger().error("IPC receive failed: {}".format(exc))
                break
            if packet is None:
                break
            self._last_valid_seen = time.monotonic()
            self._last_source_age = packet_age_seconds(packet)
            self._dispatch(packet)

    def _dispatch(self, packet: Dict[str, object]) -> None:
        try:
            kind = packet["k"]
            stamp = self.get_clock().now().to_msg()
            if kind == "lowstate":
                self._stats["rx_lowstate"] += 1
                self._handle_lowstate(packet, stamp)
            elif kind == "secondary_imu":
                self._stats["rx_secondary_imu"] += 1
                self._handle_secondary_imu(packet, stamp)
            elif kind == "sport_state":
                self._stats["rx_sport_state"] += 1
                self._handle_sport_state(packet)
            elif kind == "health":
                self._stats["rx_health"] += 1
                self._last_health_seen = time.monotonic()
                self._last_health = packet
        except (KeyError, TypeError, ValueError) as exc:
            self._stats["parse_errors"] += 1
            self.get_logger().warning("dispatch rejected: {}".format(exc))

    def _handle_lowstate(self, packet: Dict[str, object], stamp) -> None:
        axes = [float(packet[name]) for name in ("lx", "ly", "rx", "ry")]
        buttons = keys_to_buttons(int(packet["keys"]))

        joy = Joy()
        joy.header.stamp = stamp
        joy.header.frame_id = "unitree_remote"
        joy.axes = axes
        joy.buttons = buttons
        self._pub_joy.publish(joy)

        self._pub_lowstate_imu.publish(
            self._make_imu_message(packet, stamp, "unitree_lowstate_imu"))

        summary = String()
        summary.data = (
            "ch={ch} tick={tick} mm={mm} lx={lx:.3f} ly={ly:.3f} "
            "rx={rx:.3f} ry={ry:.3f} keys=0x{keys:04X}"
        ).format(
            ch=packet["ch"], tick=packet["tick"], mm=packet["mm"],
            lx=axes[0], ly=axes[1], rx=axes[2], ry=axes[3],
            keys=int(packet["keys"]),
        )
        self._pub_summary.publish(summary)

    def _handle_secondary_imu(self, packet: Dict[str, object], stamp) -> None:
        self._pub_secondary_imu.publish(
            self._make_imu_message(packet, stamp, "unitree_secondary_imu"))

    def _handle_sport_state(self, packet: Dict[str, object]) -> None:
        fsm = int(packet["fsm"])
        message = UInt32()
        message.data = fsm
        self._pub_fsm.publish(message)
        if fsm != self._last_fsm:
            self.get_logger().info(
                "FSM changed: {} -> {}".format(self._last_fsm, fsm))
            self._last_fsm = fsm

    @staticmethod
    def _make_imu_message(packet: Dict[str, object], stamp, frame_id: str) -> Imu:
        data = make_imu_dict(packet)
        message = Imu()
        message.header.stamp = stamp
        message.header.frame_id = frame_id
        message.orientation.w, message.orientation.x, \
            message.orientation.y, message.orientation.z = data["q"]
        message.angular_velocity.x, message.angular_velocity.y, \
            message.angular_velocity.z = data["g"]
        message.linear_acceleration.x, message.linear_acceleration.y, \
            message.linear_acceleration.z = data["a"]
        message.orientation_covariance[0] = -1.0
        message.angular_velocity_covariance[0] = -1.0
        message.linear_acceleration_covariance[0] = -1.0
        return message

    def _publish_health(self) -> None:
        now = time.monotonic()
        health_age = None if self._last_health_seen is None \
            else now - self._last_health_seen
        data_age = None if self._last_valid_seen is None \
            else now - self._last_valid_seen
        drops = int(self._last_health.get("n_drop", 0))

        level = DiagnosticStatus.OK
        reasons = []
        if self._socket is None or (health_age is not None and health_age > 5.0):
            level = DiagnosticStatus.ERROR
            reasons.append("socket unavailable" if self._socket is None else "tap health stale")
        elif self._last_health_seen is None:
            level = DiagnosticStatus.WARN
            reasons.append("waiting for tap health")
        if drops > 0 or self._stats["parse_errors"] > 0 or self._stats["socket_errors"] > 0:
            level = max(level, DiagnosticStatus.WARN)
            reasons.append("drops or receive errors")

        array = DiagnosticArray()
        array.header.stamp = self.get_clock().now().to_msg()
        status = DiagnosticStatus()
        status.name = "ottoguide_unitree_capture_bridge"
        status.hardware_id = "unitree_g1_edu_8"
        status.level = level
        status.message = "; ".join(reasons) if reasons else "receive-only bridge healthy"

        values = dict(self._stats)
        values.update({
            "ipc_socket": "ready" if self._socket else self._socket_error or "unavailable",
            "tap_health_age_sec": "unknown" if health_age is None else "{:.3f}".format(health_age),
            "data_age_sec": "unknown" if data_age is None else "{:.3f}".format(data_age),
            "source_age_sec": "{:.6f}".format(self._last_source_age),
        })
        for key in ("n_ls", "n_lf_ls", "n_simu", "n_sport", "n_sent", "n_drop"):
            values["tap_{}".format(key)] = self._last_health.get(key, "unknown")
        for key, value in values.items():
            item = KeyValue()
            item.key = str(key)
            item.value = str(value)
            status.values.append(item)
        array.status.append(status)
        self._pub_health.publish(array)

    def destroy_node(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if os.path.exists(SOCK_PATH):
            try:
                os.unlink(SOCK_PATH)
            except OSError:
                pass
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = UnitreeCaptureBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
