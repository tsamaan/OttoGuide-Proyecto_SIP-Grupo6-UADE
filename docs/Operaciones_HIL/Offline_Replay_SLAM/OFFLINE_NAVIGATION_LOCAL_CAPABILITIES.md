# Capacidades ROS Locales — Sandbox de Navegación Offline

**Fecha**: 2026-06-20
**Entorno verificado**: Windows 11 + WSL `Ubuntu-24.04`, ROS 2 `jazzy` (`/opt/ros/jazzy`), Python 3.12.

Este documento registra qué paquetes ROS 2 relevantes para el sandbox offline de Nav2 están disponibles localmente. La verificación se hizo exclusivamente con `ros2 pkg list`, `ros2 pkg executables`, `ros2 pkg prefix` y listados de `find`/`ls` sobre `/opt/ros/jazzy`. No se usó `apt`, `apt-get`, `pip`, `rosdep` ni acceso a Internet. No se inició ningún nodo ROS.

## Tabla de capacidades

| Componente | Paquete | Disponible | Ejecutable o launch detectado | Requerido en fase posterior | Observaciones |
|---|---|---|---|---|---|
| Map Server | `nav2_map_server` | SÍ | `map_server`, `map_saver_cli`, `map_saver_server`, `costmap_filter_info_server` | Ya usado en el sandbox actual | Es el único nodo Nav2 que el launch actual levanta. |
| Lifecycle Manager | `nav2_lifecycle_manager` | SÍ | `lifecycle_manager` | Ya usado en el sandbox actual | Gestiona el ciclo de vida de `map_server`. |
| Planificador global | `nav2_planner` | SÍ | `planner_server` | Sí, para fase de planificación offline | No se levanta todavía en este launch. |
| Controlador local | `nav2_controller` | SÍ | `controller_server` | Sí, pero implica `/cmd_vel` — requiere decisión explícita de aislamiento antes de habilitarlo | El plan prohíbe `/cmd_vel` en el sandbox; este nodo debe quedar fuera o con output desconectado del robot real hasta que se decida lo contrario. |
| Behaviors (recovery) | `nav2_behaviors` | SÍ | `behavior_server` | Sí, para fase de runtime completo | No usado todavía. |
| Waypoint follower | `nav2_waypoint_follower` | SÍ | `waypoint_follower` | Sí, para validar waypoints templados | No usado todavía. |
| Collision monitor | `nav2_collision_monitor` | SÍ | `collision_monitor`, `collision_detector` | Opcional en fases posteriores | No usado todavía. |
| Bringup (launch agregados) | `nav2_bringup` | SÍ (paquete presente, sin ejecutables propios) | Launch files: `bringup_launch.py`, `navigation_launch.py`, `localization_launch.py`, `slam_launch.py`, `rviz_launch.py`, `tb3_simulation_launch.py`, `tb3_loopback_simulation.launch.py`, `tb4_simulation_launch.py`, `tb4_loopback_simulation.launch.py`, `cloned_multi_tb3_simulation_launch.py`, `unique_multi_tb3_simulation_launch.py` | Referencia para componer el launch propio del sandbox | No recrear el launch actual desde estos templates sin revisión; son ejemplos orientados a TurtleBot. |
| Loopback Simulator | `nav2_loopback_sim` | **NO** | Referenciado por `tb3_loopback_simulation.launch.py` / `tb4_loopback_simulation.launch.py` de `nav2_bringup`, pero el paquete `nav2_loopback_sim` no está instalado (`ros2 pkg prefix nav2_loopback_sim` → `Package not found`) | Sí, para simular `/odom` sin robot real en fases posteriores | Estos launch de `nav2_bringup` fallarían si se ejecutan ahora porque dependen de un paquete ausente. Cualquier intento de usarlos debe instalarlo primero (fuera del alcance de esta fase). |
| Simple Commander (API Python) | `nav2_simple_commander` | SÍ | Librería Python (`nav2_simple_commander/__init__.py` en `site-packages`), no expone ejecutable propio | Sí, para scripting de waypoints en fase de runtime | Se importa desde Python (`import nav2_simple_commander`), no se lanza como nodo. |
| TF | `tf2_ros` | SÍ | `buffer_server`, `static_transform_publisher`, `tf2_echo`, `tf2_monitor` | Sí | Disponible para transforms estáticos en pruebas futuras. |
| Robot State Publisher | `robot_state_publisher` | SÍ | `robot_state_publisher` | Sí, si se publica URDF | No usado todavía en el sandbox. |
| Visualización | `rviz2` | SÍ | `rviz2`, `rviz1_to_rviz2.py` | Ya soportado como opcional (`use_rviz`) en el launch actual | — |

## Resumen

- **Disponibles localmente**: `nav2_map_server`, `nav2_lifecycle_manager`, `nav2_planner`, `nav2_controller`, `nav2_behaviors`, `nav2_waypoint_follower`, `nav2_collision_monitor`, `nav2_bringup` (paquete y launches, sin contar el loopback sim ausente), `nav2_simple_commander` (librería Python), `tf2_ros`, `robot_state_publisher`, `rviz2`.
- **No disponible**: `nav2_loopback_sim` (paquete standalone). Es una dependencia externa de los launch de loopback simulation de `nav2_bringup`; no está instalada en este entorno WSL.

## Método de verificación

```bash
source /opt/ros/jazzy/setup.bash
ros2 pkg list
ros2 pkg executables <paquete>
ros2 pkg prefix <paquete>
ls /opt/ros/jazzy/share/nav2_bringup/launch
python3 -c "import nav2_simple_commander; print(nav2_simple_commander.__file__)"
```

Ningún comando de esta verificación inició nodos, publicó tópicos, accedió a la red ni requirió privilegios de instalación.
