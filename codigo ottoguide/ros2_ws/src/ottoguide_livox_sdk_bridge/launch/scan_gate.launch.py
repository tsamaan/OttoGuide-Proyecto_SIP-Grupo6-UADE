import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def generate_launch_description():
    pkg_dir = get_package_share_directory('ottoguide_livox_sdk_bridge')
    
    bridge_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_dir, 'launch', 'mid360_sdk2_bridge.launch.py')
        ),
        launch_arguments={
            'debug_log_lifecycle_markers': 'false',
            'diagnostic_log_every_n_packets': '1000'
        }.items()
    )

    scan_config = os.path.join(pkg_dir, 'config', 'pointcloud_to_laserscan.yaml')

    scan_node = Node(
        package='pointcloud_to_laserscan',
        executable='pointcloud_to_laserscan_node',
        name='pointcloud_to_laserscan',
        remappings=[
            ('cloud_in', '/utlidar/cloud'),
            ('scan', '/scan')
        ],
        parameters=[scan_config]
    )

    return LaunchDescription([
        bridge_launch,
        scan_node
    ])
