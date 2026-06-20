#!/usr/bin/env python3
"""Synthetic odometry/scan publisher for the Nav2 offline sandbox.

This node exists exclusively for the offline sandbox. It publishes a fixed,
zero-velocity pose as nav_msgs/Odometry, the matching odom->base_link TF, and
a deterministic synthetic sensor_msgs/LaserScan. It does not subscribe to
any velocity command topic, does not import hardware/HAL modules, does not
open rosbags, and does not access the network. It does not represent or
claim to be a validated model of the real Unitree G1.
"""
from __future__ import annotations

import math

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_ros import TransformBroadcaster

ODOM_FRAME = "odom"
BASE_FRAME = "base_link"
LIDAR_FRAME = "utlidar_lidar"

DEFAULT_PUBLISH_FREQUENCY_HZ = 5.0
DEFAULT_SCAN_RANGE_COUNT = 360
DEFAULT_SCAN_RANGE_M = 3.0

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


class OfflineRuntimeSimulator(Node):
    """Publishes synthetic, stationary odometry and a synthetic LaserScan.

    Intended only for the Nav2 offline sandbox. Pose is fixed at the origin,
    velocity is always zero, and the scan is a deterministic, finite pattern.
    """

    def __init__(self) -> None:
        super().__init__("offline_runtime_simulator")

        self.declare_parameter("publish_frequency_hz", DEFAULT_PUBLISH_FREQUENCY_HZ)
        self.declare_parameter("scan_range_count", DEFAULT_SCAN_RANGE_COUNT)
        self.declare_parameter("scan_range_m", DEFAULT_SCAN_RANGE_M)

        frequency_hz = float(self.get_parameter("publish_frequency_hz").value)
        self._scan_range_count = int(self.get_parameter("scan_range_count").value)
        self._scan_range_m = float(self.get_parameter("scan_range_m").value)

        self._odom_publisher = self.create_publisher(Odometry, "odom", 10)
        self._scan_publisher = self.create_publisher(LaserScan, "scan", 10)
        self._tf_broadcaster = TransformBroadcaster(self)

        period_s = 1.0 / frequency_hz
        self._timer = self.create_timer(period_s, self._on_timer)

        self.get_logger().info(
            "offline_runtime_simulator started: SYNTHETIC_ODOMETRY, "
            "NOT_VALIDATED, NOT_REPRESENTATIVE_OF_REAL_G1"
        )

    def _on_timer(self) -> None:
        now = self.get_clock().now()
        stamp = now.to_msg()

        odom_msg = Odometry()
        odom_msg.header.stamp = stamp
        odom_msg.header.frame_id = ODOM_FRAME
        odom_msg.child_frame_id = BASE_FRAME
        odom_msg.pose.pose.position.x = 0.0
        odom_msg.pose.pose.position.y = 0.0
        odom_msg.pose.pose.position.z = 0.0
        odom_msg.pose.pose.orientation.x = 0.0
        odom_msg.pose.pose.orientation.y = 0.0
        odom_msg.pose.pose.orientation.z = 0.0
        odom_msg.pose.pose.orientation.w = 1.0
        odom_msg.pose.covariance = POSE_COVARIANCE_CONSERVATIVE
        odom_msg.twist.twist.linear.x = 0.0
        odom_msg.twist.twist.linear.y = 0.0
        odom_msg.twist.twist.angular.z = 0.0
        odom_msg.twist.covariance = TWIST_COVARIANCE_CONSERVATIVE
        self._odom_publisher.publish(odom_msg)

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = ODOM_FRAME
        transform.child_frame_id = BASE_FRAME
        transform.transform.translation.x = 0.0
        transform.transform.translation.y = 0.0
        transform.transform.translation.z = 0.0
        transform.transform.rotation.x = 0.0
        transform.transform.rotation.y = 0.0
        transform.transform.rotation.z = 0.0
        transform.transform.rotation.w = 1.0
        self._tf_broadcaster.sendTransform(transform)

        scan_msg = LaserScan()
        scan_msg.header.stamp = stamp
        scan_msg.header.frame_id = LIDAR_FRAME
        scan_msg.angle_min = -math.pi
        scan_msg.angle_max = math.pi
        scan_msg.angle_increment = (2.0 * math.pi) / self._scan_range_count
        scan_msg.time_increment = 0.0
        scan_msg.scan_time = 1.0 / max(self._scan_range_count, 1)
        scan_msg.range_min = 0.1
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
