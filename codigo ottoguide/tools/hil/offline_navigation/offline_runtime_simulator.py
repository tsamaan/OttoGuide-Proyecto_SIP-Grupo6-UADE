#!/usr/bin/env python3
"""Synthetic odometry/scan publisher and closed-loop kinematic integrator
for the Nav2 offline sandbox.

This node exists exclusively for the offline sandbox. It publishes
nav_msgs/Odometry, the matching odom->base_link TF, and a deterministic
synthetic sensor_msgs/LaserScan. It subscribes to a *relative* topic,
'cmd_vel_raw' (resolved under the sandbox namespace, e.g.
/offline_nav/cmd_vel_raw), and integrates that velocity command into a 2D
planar pose (x, y, yaw) using a simple deterministic kinematic model. It
never subscribes to any global velocity topic, never imports hardware/HAL
modules, never opens rosbags, and never accesses the network. It does not
represent or claim to be a validated model of the real Unitree G1.

OFFLINE_ONLY / SYNTHETIC / NOT_FOR_HARDWARE.
"""
from __future__ import annotations

import math

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_ros import TransformBroadcaster

ODOM_FRAME = "odom"
BASE_FRAME = "base_link"
LIDAR_FRAME = "utlidar_lidar"

DEFAULT_PUBLISH_FREQUENCY_HZ = 5.0
DEFAULT_SCAN_RANGE_COUNT = 360
DEFAULT_SCAN_RANGE_M = 3.0
DEFAULT_MAX_LINEAR_SPEED_MPS = 0.10
DEFAULT_MAX_ANGULAR_SPEED_RADPS = 0.30
DEFAULT_CMD_VEL_WATCHDOG_TIMEOUT_S = 0.5

POSE_COVARIANCE_CONSERVATIVE = [0.0] * 36
POSE_COVARIANCE_CONSERVATIVE[0] = 0.50  # x
POSE_COVARIANCE_CONSERVATIVE[7] = 0.50  # y
POSE_COVARIANCE_CONSERVATIVE[14] = 999.0  # z
POSE_COVARIANCE_CONSERVATIVE[21] = 999.0  # roll
POSE_COVARIANCE_CONSERVATIVE[28] = 999.0  # pitch
POSE_COVARIANCE_CONSERVATIVE[35] = 0.10  # yaw

TWIST_COVARIANCE_CONSERVATIVE = [0.0] * 36
TWIST_COVARIANCE_CONSERVATIVE[0] = 0.50
TWIST_COVARIANCE_CONSERVATIVE[7] = 999.0
TWIST_COVARIANCE_CONSERVATIVE[14] = 999.0
TWIST_COVARIANCE_CONSERVATIVE[21] = 999.0
TWIST_COVARIANCE_CONSERVATIVE[28] = 999.0
TWIST_COVARIANCE_CONSERVATIVE[35] = 0.10


def _yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    """Return (x, y, z, w) for a planar rotation about Z. Deterministic, no
    external dependency on tf_transformations.
    """
    half_yaw = yaw * 0.5
    return (0.0, 0.0, math.sin(half_yaw), math.cos(half_yaw))


def _clamp(value: float, limit: float) -> float:
    if limit < 0.0:
        limit = 0.0
    return max(-limit, min(limit, value))


class OfflineRuntimeSimulator(Node):
    """Publishes synthetic odometry/scan and integrates cmd_vel_raw into a
    deterministic planar pose. Intended only for the Nav2 offline sandbox.
    """

    def __init__(self) -> None:
        super().__init__("offline_runtime_simulator")

        self.declare_parameter("publish_frequency_hz", DEFAULT_PUBLISH_FREQUENCY_HZ)
        self.declare_parameter("scan_range_count", DEFAULT_SCAN_RANGE_COUNT)
        self.declare_parameter("scan_range_m", DEFAULT_SCAN_RANGE_M)
        self.declare_parameter("max_linear_speed_mps", DEFAULT_MAX_LINEAR_SPEED_MPS)
        self.declare_parameter("max_angular_speed_radps", DEFAULT_MAX_ANGULAR_SPEED_RADPS)
        self.declare_parameter(
            "cmd_vel_watchdog_timeout_s", DEFAULT_CMD_VEL_WATCHDOG_TIMEOUT_S
        )

        frequency_hz = float(self.get_parameter("publish_frequency_hz").value)
        self._scan_range_count = int(self.get_parameter("scan_range_count").value)
        self._scan_range_m = float(self.get_parameter("scan_range_m").value)
        self._scan_range_min_m = 0.1
        self._max_linear_speed_mps = float(
            self.get_parameter("max_linear_speed_mps").value
        )
        self._max_angular_speed_radps = float(
            self.get_parameter("max_angular_speed_radps").value
        )
        self._cmd_vel_watchdog_timeout_s = float(
            self.get_parameter("cmd_vel_watchdog_timeout_s").value
        )

        if frequency_hz <= 0.0:
            raise ValueError(
                f"publish_frequency_hz must be > 0, got {frequency_hz}"
            )
        if self._scan_range_count < 2:
            raise ValueError(
                f"scan_range_count must be >= 2, got {self._scan_range_count}"
            )
        if self._scan_range_m <= self._scan_range_min_m:
            raise ValueError(
                f"scan_range_m must be > range_min ({self._scan_range_min_m}), "
                f"got {self._scan_range_m}"
            )
        if self._max_linear_speed_mps <= 0.0:
            raise ValueError(
                f"max_linear_speed_mps must be > 0, got {self._max_linear_speed_mps}"
            )
        if self._max_angular_speed_radps <= 0.0:
            raise ValueError(
                "max_angular_speed_radps must be > 0, got "
                f"{self._max_angular_speed_radps}"
            )
        if self._cmd_vel_watchdog_timeout_s <= 0.0:
            raise ValueError(
                "cmd_vel_watchdog_timeout_s must be > 0, got "
                f"{self._cmd_vel_watchdog_timeout_s}"
            )

        # Planar kinematic state. Starts at the origin; only this node's own
        # deterministic integration of cmd_vel_raw ever changes it.
        self._x = 0.0
        self._y = 0.0
        self._yaw = 0.0
        self._commanded_linear_x = 0.0
        self._commanded_angular_z = 0.0
        self._last_cmd_vel_time = None

        self._odom_publisher = self.create_publisher(Odometry, "odom", 10)
        self._scan_publisher = self.create_publisher(LaserScan, "scan", 10)
        self._tf_broadcaster = TransformBroadcaster(self)

        # Relative subscription: resolves to <namespace>/cmd_vel_raw. Never a
        # global topic, never /cmd_vel, never /cmd_vel_nav.
        self._cmd_vel_subscription = self.create_subscription(
            Twist, "cmd_vel_raw", self._on_cmd_vel_raw, 10
        )

        self._scan_time_s = 1.0 / frequency_hz
        self._period_s = 1.0 / frequency_hz
        self._timer = self.create_timer(self._period_s, self._on_timer)

        self.get_logger().info(
            "offline_runtime_simulator started: SYNTHETIC_ODOMETRY, "
            "NOT_VALIDATED, NOT_REPRESENTATIVE_OF_REAL_G1, "
            "OFFLINE_ONLY, SYNTHETIC, NOT_FOR_HARDWARE"
        )

    def _on_cmd_vel_raw(self, msg: Twist) -> None:
        self._commanded_linear_x = _clamp(
            float(msg.linear.x), self._max_linear_speed_mps
        )
        self._commanded_angular_z = _clamp(
            float(msg.angular.z), self._max_angular_speed_radps
        )
        self._last_cmd_vel_time = self.get_clock().now()

    def _watchdog_expired(self) -> bool:
        if self._last_cmd_vel_time is None:
            return True
        elapsed_s = (self.get_clock().now() - self._last_cmd_vel_time).nanoseconds / 1e9
        return elapsed_s > self._cmd_vel_watchdog_timeout_s

    def _integrate_pose(self, linear_x: float, angular_z: float, dt: float) -> None:
        # Deterministic planar kinematic integration (differential-drive
        # style). No noise, no randomness, no hardware feedback.
        self._x += linear_x * math.cos(self._yaw) * dt
        self._y += linear_x * math.sin(self._yaw) * dt
        self._yaw += angular_z * dt
        self._yaw = math.atan2(math.sin(self._yaw), math.cos(self._yaw))

    def _on_timer(self) -> None:
        now = self.get_clock().now()
        stamp = now.to_msg()

        if self._watchdog_expired():
            effective_linear_x = 0.0
            effective_angular_z = 0.0
        else:
            effective_linear_x = self._commanded_linear_x
            effective_angular_z = self._commanded_angular_z

        self._integrate_pose(effective_linear_x, effective_angular_z, self._period_s)

        qx, qy, qz, qw = _yaw_to_quaternion(self._yaw)

        odom_msg = Odometry()
        odom_msg.header.stamp = stamp
        odom_msg.header.frame_id = ODOM_FRAME
        odom_msg.child_frame_id = BASE_FRAME
        odom_msg.pose.pose.position.x = self._x
        odom_msg.pose.pose.position.y = self._y
        odom_msg.pose.pose.position.z = 0.0
        odom_msg.pose.pose.orientation.x = qx
        odom_msg.pose.pose.orientation.y = qy
        odom_msg.pose.pose.orientation.z = qz
        odom_msg.pose.pose.orientation.w = qw
        odom_msg.pose.covariance = POSE_COVARIANCE_CONSERVATIVE
        odom_msg.twist.twist.linear.x = effective_linear_x
        odom_msg.twist.twist.linear.y = 0.0
        odom_msg.twist.twist.angular.z = effective_angular_z
        odom_msg.twist.covariance = TWIST_COVARIANCE_CONSERVATIVE
        self._odom_publisher.publish(odom_msg)

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = ODOM_FRAME
        transform.child_frame_id = BASE_FRAME
        transform.transform.translation.x = self._x
        transform.transform.translation.y = self._y
        transform.transform.translation.z = 0.0
        transform.transform.rotation.x = qx
        transform.transform.rotation.y = qy
        transform.transform.rotation.z = qz
        transform.transform.rotation.w = qw
        self._tf_broadcaster.sendTransform(transform)

        scan_msg = LaserScan()
        scan_msg.header.stamp = stamp
        scan_msg.header.frame_id = LIDAR_FRAME
        scan_msg.angle_min = -math.pi
        scan_msg.angle_max = math.pi
        scan_msg.angle_increment = (2.0 * math.pi) / self._scan_range_count
        scan_msg.time_increment = 0.0
        scan_msg.scan_time = self._scan_time_s
        scan_msg.range_min = self._scan_range_min_m
        scan_msg.range_max = self._scan_range_m
        scan_msg.ranges = [self._scan_range_m for _ in range(self._scan_range_count)]
        scan_msg.intensities = []
        self._scan_publisher.publish(scan_msg)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = OfflineRuntimeSimulator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
