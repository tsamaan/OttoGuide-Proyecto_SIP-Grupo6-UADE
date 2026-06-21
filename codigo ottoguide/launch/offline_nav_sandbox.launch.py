import sys
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
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
SIMULATOR_SCRIPT = str(
    CODE_ROOT / "tools" / "hil" / "offline_navigation" / "offline_runtime_simulator.py"
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

    sandbox_namespace_arg = DeclareLaunchArgument(
        'sandbox_namespace',
        default_value='offline_nav',
        description=(
            'Namespace ROS real aplicado a los nodos del sandbox offline. '
            'No es solo un marcador textual: se aplica como namespace de Node.'
        )
    )

    namespace = LaunchConfiguration('sandbox_namespace')

    # Nodo map_server
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        namespace=namespace,
        output='screen',
        parameters=[PARAMS_FILE, {'yaml_filename': LaunchConfiguration('map_yaml')}]
    )

    # Nodo planner_server: planificacion global unicamente. OFFLINE_ONLY,
    # SYNTHETIC, NOT_FOR_HARDWARE. Sin controller_server, sin local_costmap,
    # sin behaviors, sin waypoint follower, sin Collision Monitor.
    planner_server_node = Node(
        package='nav2_planner',
        executable='planner_server',
        name='planner_server',
        namespace=namespace,
        output='screen',
        parameters=[PARAMS_FILE]
    )

    # Nodo lifecycle manager: activa map_server y planner_server unicamente.
    lifecycle_manager_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        namespace=namespace,
        output='screen',
        parameters=[{'use_sim_time': False},
                    {'autostart': True},
                    {'node_names': ['map_server', 'planner_server']}]
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

    # Simulador offline: odometria sintetica (nav_msgs/Odometry en 'odom'),
    # TF dinamico odom->base_link, y LaserScan sintetico en 'scan'.
    # No suscribe /cmd_vel ni /cmd_vel_nav. No importa HAL fisico.
    # Se ejecuta con ExecuteProcess (no es un ejecutable instalado de un
    # paquete ROS) pero el nodo rclpy interno aplica el namespace via
    # remapping de __ns para mantener los topicos relativos correctos.
    offline_runtime_simulator_node = ExecuteProcess(
        cmd=[
            sys.executable,
            SIMULATOR_SCRIPT,
            '--ros-args',
            '-r', ['__ns:=/', namespace],
        ],
        name='offline_runtime_simulator',
        output='screen',
        shell=False
    )

    # TF estatico map->odom: identidad sintetica, NO es una localizacion
    # validada. Solo permite que el grafo TF este completo en el sandbox.
    map_to_odom_static_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='map_to_odom_synthetic_tf',
        namespace=namespace,
        arguments=['0', '0', '0', '0', '0', '0', 'map', 'odom'],
        output='screen'
    )

    # TF estatico base_link->utlidar_lidar: identidad sintetica de
    # placeholder. NO es un extrinseco fisico medido ni validado.
    base_link_to_lidar_static_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_link_to_utlidar_lidar_synthetic_tf',
        namespace=namespace,
        arguments=['0', '0', '0', '0', '0', '0', 'base_link', 'utlidar_lidar'],
        output='screen'
    )

    # Sandbox offline unicamente: sin navegacion real, sin hardware fisico,
    # sin controller_server, sin behaviors, sin waypoint follower, sin
    # Collision Monitor y sin comandos de velocidad de ningun tipo.
    # planner_server solo planifica rutas globales; no mueve nada.
    # Requiere entorno con ROS_LOCALHOST_ONLY=1 y ROS_DOMAIN_ID explicito
    # (no el default 0) para aislar este sandbox del resto de la red ROS.
    # Las TF map->odom y base_link->utlidar_lidar publicadas aqui son
    # identidades sinteticas, no extrinsecos fisicos validados.

    return LaunchDescription([
        map_yaml_arg,
        use_rviz_arg,
        rviz_config_arg,
        sandbox_namespace_arg,
        map_server_node,
        planner_server_node,
        lifecycle_manager_node,
        rviz_node,
        offline_runtime_simulator_node,
        map_to_odom_static_tf,
        base_link_to_lidar_static_tf
    ])
