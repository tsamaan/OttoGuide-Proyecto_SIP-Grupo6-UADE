import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _default_config_path() -> str:
    explicit = os.environ.get("OTTOGUIDE_LIVOX_CONFIG")
    if explicit:
        return explicit

    root = os.environ.get("OTTOGUIDE_ROOT")
    if root:
        return str(Path(root) / "config" / "livox" / "mid360_sdk2_bridge.json")

    source_tree_root = Path(__file__).resolve().parents[4]
    source_tree_config = source_tree_root / "config" / "livox" / "mid360_sdk2_bridge.json"
    if source_tree_config.exists():
        return str(source_tree_config)

    return "config/livox/mid360_sdk2_bridge.json"


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "config_path",
            default_value=_default_config_path(),
            description="Absolute Livox SDK2 MID360 JSON config path.",
        ),
        DeclareLaunchArgument(
            "frame_id",
            default_value="utlidar_lidar",
            description="Frame used for PointCloud2 and Imu headers.",
        ),
        DeclareLaunchArgument(
            "topic_cloud",
            default_value="/utlidar/cloud",
            description="PointCloud2 output topic consumed by the HIL mapping pipeline.",
        ),
        DeclareLaunchArgument(
            "topic_imu",
            default_value="/livox/imu",
            description="IMU output topic recorded by the HIL mapping pipeline.",
        ),
        DeclareLaunchArgument(
            "max_points_per_packet",
            default_value="96",
            description="Hard safety cap for decoded Livox points per SDK2 packet.",
        ),
        DeclareLaunchArgument(
            "debug_dry_run_no_publish",
            default_value="false",
            description="Decode and log SDK2 callbacks without publishing ROS messages.",
        ),
        DeclareLaunchArgument(
            "diagnostic_log_every_n_packets",
            default_value="250",
            description="Emit one SDK2 packet diagnostic sample every N callbacks.",
        ),
        Node(
            package="ottoguide_livox_sdk_bridge",
            executable="livox_sdk_bridge_node",
            name="livox_sdk_bridge_node",
            output="screen",
            parameters=[{
                "config_path": LaunchConfiguration("config_path"),
                "frame_id": LaunchConfiguration("frame_id"),
                "topic_cloud": LaunchConfiguration("topic_cloud"),
                "topic_imu": LaunchConfiguration("topic_imu"),
                "max_points_per_packet": ParameterValue(
                    LaunchConfiguration("max_points_per_packet"),
                    value_type=int,
                ),
                "debug_dry_run_no_publish": ParameterValue(
                    LaunchConfiguration("debug_dry_run_no_publish"),
                    value_type=bool,
                ),
                "diagnostic_log_every_n_packets": ParameterValue(
                    LaunchConfiguration("diagnostic_log_every_n_packets"),
                    value_type=int,
                ),
            }],
        ),
    ])
