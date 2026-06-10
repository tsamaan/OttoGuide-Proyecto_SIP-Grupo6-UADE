import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.conditions import IfCondition
from launch_ros.actions import Node

def generate_launch_description():
    # Declarar argumentos
    map_yaml_arg = DeclareLaunchArgument(
        'map_yaml',
        default_value='artifacts/maps/ottoguide_hil_stationary_map.yaml',
        description='Ruta al archivo yaml del mapa. NOTA: default es un artefacto local no versionable.'
    )

    use_rviz_arg = DeclareLaunchArgument(
        'use_rviz',
        default_value='false',
        description='Lanzar RViz'
    )

    rviz_config_arg = DeclareLaunchArgument(
        'rviz_config',
        default_value='tools/hil/rviz/ottoguide_nav2_offline_sandbox.rviz',
        description='Configuracion de RViz'
    )

    params_file = 'config/navigation/nav2_offline_sandbox_params.yaml'

    # Nodo map_server
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[params_file, {'yaml_filename': LaunchConfiguration('map_yaml')}]
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

    # NOTA: No lanzamos controller_server ni navegacion real (prohibido por contexto)

    return LaunchDescription([
        map_yaml_arg,
        use_rviz_arg,
        rviz_config_arg,
        map_server_node,
        lifecycle_manager_node,
        rviz_node
    ])
