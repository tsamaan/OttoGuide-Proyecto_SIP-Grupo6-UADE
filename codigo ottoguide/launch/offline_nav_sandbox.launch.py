import sys
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml


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
BT_XML_FILE = str(
    CODE_ROOT / "config" / "navigation" / "bt" / "offline_navigate_to_pose.xml"
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

    # Parametros reescritos con el namespace real del sandbox como root_key,
    # de forma que los nodos namespaced (map_server, planner_server,
    # controller_server) reciban sus claves de plugin anidadas
    # (GridBased.*, FollowPath.*) correctamente resueltas bajo
    # /<sandbox_namespace>/<nodo>. Sin esta reescritura, ROS 2 Jazzy en este
    # entorno carga el archivo con las claves raiz tal como estan escritas
    # (sin namespace), y los nodos namespaced ignoran silenciosamente esos
    # valores, cayendo a los defaults de stock Nav2.
    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=PARAMS_FILE,
            root_key=namespace,
            param_rewrites={},
            convert_types=True,
        ),
        allow_substs=True,
    )

    # Parametros de bt_navigator: identicos a configured_params salvo
    # default_nav_to_pose_bt_xml, reescrito aqui con la ruta absoluta del XML
    # versionado del repositorio (BT_XML_FILE), derivada de CODE_ROOT y por
    # lo tanto independiente del directorio actual de ejecucion. El valor
    # placeholder en el YAML nunca se usa realmente.
    bt_navigator_params = ParameterFile(
        RewrittenYaml(
            source_file=PARAMS_FILE,
            root_key=namespace,
            param_rewrites={'default_nav_to_pose_bt_xml': BT_XML_FILE},
            convert_types=True,
        ),
        allow_substs=True,
    )

    # Nodo map_server
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        namespace=namespace,
        output='screen',
        parameters=[configured_params, {'yaml_filename': LaunchConfiguration('map_yaml')}]
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
        parameters=[configured_params]
    )

    # Nodo controller_server: control local closed-loop unicamente simulado.
    # OFFLINE_ONLY, SYNTHETIC, NOT_FOR_HARDWARE. Su salida relativa 'cmd_vel'
    # se remapea a 'cmd_vel_raw' (resuelve a <namespace>/cmd_vel_raw), el
    # unico topico de velocidad permitido en el sandbox. Nunca publica
    # /cmd_vel ni /cmd_vel_nav globales y nunca llega a un bridge fisico.
    controller_server_node = Node(
        package='nav2_controller',
        executable='controller_server',
        name='controller_server',
        namespace=namespace,
        output='screen',
        parameters=[configured_params],
        remappings=[('cmd_vel', 'cmd_vel_raw')]
    )

    # Nodo lifecycle manager principal: activa unicamente map_server y
    # planner_server. Aislado deliberadamente del lifecycle de
    # controller_server para que una falla de activacion del controller
    # (ver lifecycle_manager_controller mas abajo) nunca bloquee ni
    # regresione map_server/planner_server, que ya estaban validados antes
    # de intentar agregar control local.
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

    lifecycle_manager_controller_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_controller',
        namespace=namespace,
        output='screen',
        parameters=[{'use_sim_time': False},
                    {'autostart': True},
                    {'node_names': ['controller_server']}]
    )

    # Nodo collision_monitor: monitoreo de colisiones aislado. OFFLINE_ONLY,
    # SYNTHETIC, NOT_FOR_HARDWARE. Recibe cmd_vel_raw y publica cmd_vel_safe.
    collision_monitor_node = Node(
        package='nav2_collision_monitor',
        executable='collision_monitor',
        name='collision_monitor',
        namespace=namespace,
        output='screen',
        parameters=[configured_params]
    )

    # Nodo lifecycle manager dedicado, exclusivamente para collision_monitor.
    # Separado del resto de los managers: si collision_monitor falla al iniciar
    # o activar, queda aislado sin degradar Map, Planner o Controller.
    lifecycle_manager_collision_monitor_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_collision_monitor',
        namespace=namespace,
        output='screen',
        parameters=[{'use_sim_time': False},
                    {'autostart': True},
                    {'node_names': ['collision_monitor']}]
    )

    # Nodo behavior_server: solo plugins Wait y Spin en esta fase. OFFLINE_ONLY,
    # SYNTHETIC, NOT_FOR_HARDWARE. Su salida relativa 'cmd_vel' se remapea a
    # 'cmd_vel_raw' (resuelve a <namespace>/cmd_vel_raw), exactamente igual que
    # controller_server, de forma que ambos publishers pasan obligatoriamente
    # por collision_monitor antes de llegar al simulador. Nunca se remapea a
    # 'cmd_vel_safe' directamente: eso bypassearia Collision Monitor. Sin
    # Waypoint Follower, sin Simple Commander, sin BackUp, DriveOnHeading ni
    # AssistedTeleop en esta fase.
    behavior_server_node = Node(
        package='nav2_behaviors',
        executable='behavior_server',
        name='behavior_server',
        namespace=namespace,
        output='screen',
        parameters=[configured_params],
        remappings=[('cmd_vel', 'cmd_vel_raw')]
    )

    # Nodo lifecycle manager dedicado, exclusivamente para behavior_server.
    # Aislado del resto de los managers: si behavior_server falla al iniciar
    # o activar, queda aislado sin degradar Map, Planner, Controller o
    # Collision Monitor, que ya estaban validados antes de agregar behaviors.
    lifecycle_manager_behavior_server_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_behavior_server',
        namespace=namespace,
        output='screen',
        parameters=[{'use_sim_time': False},
                    {'autostart': True},
                    {'node_names': ['behavior_server']}]
    )

    # Nodo bt_navigator: orquesta unicamente NavigateToPose mediante el arbol
    # minimo versionado offline_navigate_to_pose.xml (ComputePathToPose ->
    # FollowPath, sin recoveries). OFFLINE_ONLY, SYNTHETIC, NOT_FOR_HARDWARE.
    # No remapea cmd_vel/cmd_vel_raw/cmd_vel_safe: nunca publica velocidad
    # directamente. El movimiento real de NavigateToPose proviene exclusiva-
    # mente de controller_server, igual que cualquier otro goal de FollowPath.
    # NavigateThroughPoses no esta configurado. Sin Waypoint Follower, sin
    # Simple Commander.
    bt_navigator_node = Node(
        package='nav2_bt_navigator',
        executable='bt_navigator',
        name='bt_navigator',
        namespace=namespace,
        output='screen',
        parameters=[bt_navigator_params]
    )

    # Nodo lifecycle manager dedicado, exclusivamente para bt_navigator.
    # Aislado del resto de los managers: si bt_navigator falla al iniciar o
    # activar, queda aislado sin degradar Map, Planner, Controller, Collision
    # Monitor o Behavior Server, que ya estaban validados antes de agregar
    # BT Navigator.
    lifecycle_manager_bt_navigator_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_bt_navigator',
        namespace=namespace,
        output='screen',
        parameters=[{'use_sim_time': False},
                    {'autostart': True},
                    {'node_names': ['bt_navigator']}]
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
    # Suscribe unicamente el topico relativo 'cmd_vel_safe' (resuelve a
    # <namespace>/cmd_vel_safe) e integra esa velocidad en una pose 2D
    # determinista. No suscribe ningun topico global de velocidad. No
    # importa HAL fisico. Se ejecuta con ExecuteProcess (no es un ejecutable
    # instalado de un paquete ROS) pero el nodo rclpy interno aplica el
    # namespace via remapping de __ns para mantener los topicos relativos
    # correctos.
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

    # Sandbox offline unicamente: sin navegacion fisica real, sin hardware,
    # sin waypoint follower, sin Simple Commander. Incluye planner_server,
    # controller_server, Collision Monitor, Behavior Server (Wait, Spin) y
    # BT Navigator (NavigateToPose unicamente, agregado en Fase 2F), sin
    # comandos de velocidad fuera de los topicos relativos 'cmd_vel_raw' y
    # 'cmd_vel_safe'. planner_server planifica rutas globales y
    # controller_server las sigue en simulacion; bt_navigator solo orquesta
    # esas acciones, nunca publica velocidad directamente. Requiere entorno
    # con ROS_LOCALHOST_ONLY=1 y ROS_DOMAIN_ID explicito (no el default 0)
    # para aislar este sandbox del resto de la red ROS. Las TF map->odom y
    # base_link->utlidar_lidar publicadas aqui son identidades sinteticas,
    # no extrinsecos fisicos validados.

    return LaunchDescription([
        map_yaml_arg,
        use_rviz_arg,
        rviz_config_arg,
        sandbox_namespace_arg,
        map_server_node,
        planner_server_node,
        controller_server_node,
        collision_monitor_node,
        behavior_server_node,
        bt_navigator_node,
        lifecycle_manager_node,
        lifecycle_manager_controller_node,
        lifecycle_manager_collision_monitor_node,
        lifecycle_manager_behavior_server_node,
        lifecycle_manager_bt_navigator_node,
        rviz_node,
        offline_runtime_simulator_node,
        map_to_odom_static_tf,
        base_link_to_lidar_static_tf
    ])
