from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="ottoguide_unitree_capture_bridge",
            executable="bridge_node",
            name="ottoguide_unitree_capture_bridge",
            output="screen",
            parameters=[
                {"use_sim_time": False},
            ],
        ),
    ])
