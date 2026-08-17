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


def _node_env() -> dict:
    """Return environment variables needed for the node process.

    Under ROS2 Foxy on the Unitree robot, the node subprocess does not
    automatically inherit LD_LIBRARY_PATH when launched from a non-interactive
    SSH session.  Without /opt/ros/foxy/lib in LD_LIBRARY_PATH the dynamic
    linker cannot resolve rclcpp / rmw symbols and the process crashes with
    SIGSEGV (exit code -11) before MARK_010.

    Strategy: start from the current environment value if set, then append
    the mandatory Foxy and Livox SDK2 paths if not already present.  This
    makes the launch work both from an interactive shell (where ROS is already
    sourced) and from non-interactive SSH invocations (where it is not).

    The mandatory paths below are the exact paths set by sourcing
    /opt/ros/foxy/setup.bash on the Unitree G1 (aarch64-linux-gnu), plus
    /usr/local/lib which is required by liblivox_lidar_sdk_shared.so.
    """
    mandatory = [
        "/opt/ros/foxy/opt/yaml_cpp_vendor/lib",
        "/opt/ros/foxy/opt/rviz_ogre_vendor/lib",
        "/opt/ros/foxy/lib/aarch64-linux-gnu",
        "/opt/ros/foxy/lib",
        "/usr/local/lib",
    ]

    current = os.environ.get("LD_LIBRARY_PATH", "")
    parts = [p for p in current.split(":") if p] if current else []
    for path in mandatory:
        if path not in parts:
            parts.append(path)
    return {"LD_LIBRARY_PATH": ":".join(parts)}



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
        DeclareLaunchArgument("debug_stage_stop_after_node_init", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_after_params", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_after_publishers", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_after_timer", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_before_sdk_init", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_after_sdk_init", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_after_callbacks_registered", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_before_sdk_start", default_value="false"),
        DeclareLaunchArgument("debug_stage_stop_after_sdk_start", default_value="false"),
        DeclareLaunchArgument("debug_disable_livox_sdk", default_value="false"),
        DeclareLaunchArgument("debug_disable_callbacks", default_value="false"),
        DeclareLaunchArgument("debug_disable_timers", default_value="false"),
        DeclareLaunchArgument("debug_disable_publishers", default_value="false"),
        DeclareLaunchArgument("debug_log_lifecycle_markers", default_value="true"),
        Node(
            package="ottoguide_livox_sdk_bridge",
            executable="livox_sdk_bridge_node",
            name="livox_sdk_bridge_node",
            output="screen",
            additional_env=_node_env(),
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
                "debug_stage_stop_after_node_init": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_after_node_init"), value_type=bool),
                "debug_stage_stop_after_params": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_after_params"), value_type=bool),
                "debug_stage_stop_after_publishers": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_after_publishers"), value_type=bool),
                "debug_stage_stop_after_timer": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_after_timer"), value_type=bool),
                "debug_stage_stop_before_sdk_init": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_before_sdk_init"), value_type=bool),
                "debug_stage_stop_after_sdk_init": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_after_sdk_init"), value_type=bool),
                "debug_stage_stop_after_callbacks_registered": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_after_callbacks_registered"), value_type=bool),
                "debug_stage_stop_before_sdk_start": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_before_sdk_start"), value_type=bool),
                "debug_stage_stop_after_sdk_start": ParameterValue(
                    LaunchConfiguration("debug_stage_stop_after_sdk_start"), value_type=bool),
                "debug_disable_livox_sdk": ParameterValue(
                    LaunchConfiguration("debug_disable_livox_sdk"), value_type=bool),
                "debug_disable_callbacks": ParameterValue(
                    LaunchConfiguration("debug_disable_callbacks"), value_type=bool),
                "debug_disable_timers": ParameterValue(
                    LaunchConfiguration("debug_disable_timers"), value_type=bool),
                "debug_disable_publishers": ParameterValue(
                    LaunchConfiguration("debug_disable_publishers"), value_type=bool),
                "debug_log_lifecycle_markers": ParameterValue(
                    LaunchConfiguration("debug_log_lifecycle_markers"), value_type=bool),
            }],
        ),
    ])
