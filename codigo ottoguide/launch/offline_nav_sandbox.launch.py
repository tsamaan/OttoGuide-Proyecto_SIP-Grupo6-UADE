from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


CODE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_ROOT.parent
PARAMS_FILE = str(CODE_ROOT / "config" / "navigation" / "nav2_offline_sandbox_params.yaml")
RVIZ_DEFAULT = str(CODE_ROOT / "tools" / "hil" / "rviz" / "ottoguide_nav2_offline_sandbox.rviz")
MAP_DEFAULT = str(
    CODE_ROOT / "tests" / "fixtures" / "offline_navigation" / "offline_sandbox_test_map.yaml"
)


def generate_launch_description():
    # Declarar argumentos
    map_yaml_arg = DeclareLaunchArgument(
        'map_yaml',
        default_value=MAP_DEFAULT,
        description=(
            'Ruta al archivo yaml del mapa. Default: mapa sintetico versionado '
            '(SYNTHETIC_TEST_MAP, NOT_UADE_MAP, NOT_FOR_PHYSICAL_NAVIGATION).'
        )
    )

    use_rviz_arg = DeclareLaunchArgument(
        'use_rviz',
        default_value='false',
        description='Lanzar RViz'
    )

    rviz_config_arg = DeclareLaunchArgument(
        'rviz_config',
        default_value=RVIZ_DEFAULT,
        description='Configuracion de RViz'
    )

    # Nodo map_server
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[PARAMS_FILE, {'yaml_filename': LaunchConfiguration('map_yaml')}]
    )

    # Nodo lifecycle manager para arrancar el map_server
    lifecycle_manager_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        output='screen',
        parameters=[{'use_sim_time': False},
                    {'autostart': True},
                    {'node_names': ['map_server']}]
    )

    # Nodo RViz (opcional)
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', LaunchConfiguration('rviz_config')],
        condition=IfCondition(LaunchConfiguration('use_rviz')),
        output='screen'
    )

    # Sandbox offline unicamente: sin navegacion real, sin hardware fisico,
    # sin controller_server y sin /cmd_vel.
    # Requiere entorno con ROS_LOCALHOST_ONLY=1 y ROS_DOMAIN_ID explicito
    # (no el default 0) para aislar este sandbox del resto de la red ROS.

    return LaunchDescription([
        map_yaml_arg,
        use_rviz_arg,
        rviz_config_arg,
        map_server_node,
        lifecycle_manager_node,
        rviz_node
    ])
