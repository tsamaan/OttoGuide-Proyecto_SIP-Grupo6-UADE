# Nav2 Offline Sandbox

**Fecha**: 2026-06-10

## 1. Objetivo
Preparar el entorno base de la pila de navegación (Nav2) en la máquina de desarrollo (WSL) aislando completamente el hardware físico del robot. Permite asegurar que los paquetes de ROS 2 necesarios estén instalados, las configuraciones yaml se parseen sin errores de sintaxis, los launch files se ejecuten de manera limpia y que las herramientas de visualización (RViz2) logren renderizar el `map_server`.

## 2. Dependencias detectadas
Al correr el diagnóstico de dependencias de Nav2 localmente, se detectó la ausencia de la mayoría de los paquetes principales para navegación:

| Paquete | Estado |
|---|---|
| nav2_bringup | MISSING |
| nav2_map_server | OK |
| nav2_lifecycle_manager | MISSING |
| nav2_planner | MISSING |
| nav2_controller | MISSING |
| nav2_bt_navigator | MISSING |
| nav2_amcl | MISSING |
| nav2_costmap_2d | MISSING |
| tf2_ros | OK |

Debido a que `nav2_lifecycle_manager` no está instalado, el Smoke Test fallará tempranamente (by design) advirtiendo la falta de dependencias sin alterar el entorno (no se instalan paquetes sin autorización).

## 3. Qué valida este sandbox
- **Configuraciones YAML**: Estructura, espacios y parámetros base de `nav2_map_server` y los costmaps.
- **Estructura de Launch**: Que las invocaciones a nodos a través de `launch_ros` (Python) resuelvan correctamente.
- **Disponibilidad de Dependencias**: Chequeo en bash duro de qué está instalado y qué falta antes de arriesgar el robot.
- **Renderizado Estático**: Que RViz2 puede abrirse con una configuración de paneles y displays pre-armada para Nav2.

## 4. Qué NO valida
- **Navegación Autónoma**: No hay locomoción, evitación de obstáculos, ni seguimiento de trayectorias.
- **Odometría Dinámica**: No existe validación alguna de que las ruedas provean `/odom` confiable al girar.
- **Transformadas en Movimiento**: No hay TF calibrado ni validado dinámicamente para la posible inversión del LiDAR.
- **Nav2 Real**: No levanta el stack completo ni corre nodos críticos como controller o amcl si no existen las dependencias y el hardware que emita `scan`.

## 5. Cómo correr smoke test
En WSL (Ubuntu-24.04), ejecutar:
```bash
./tools/hil/nav2_offline_smoke_test.sh artifacts/maps/ottoguide_hil_stationary_map.yaml
```
*Si faltan paquetes (como nav2_lifecycle_manager), el script abortará proactivamente antes de correr ROS.*

## 6. Cómo abrir RViz
En WSL o nativo con GUI support, ejecutar:
```bash
ros2 run rviz2 rviz2 -d tools/hil/rviz/ottoguide_nav2_offline_sandbox.rviz
```

## 7. Por qué el mapa actual no sirve para navegación real
- Proviene de un **bag estacionario** capturado estáticamente.
- Posee un **98.07% de espacio desconocido**. Sólo reporta 1.91% de celdas libres y 0.02% de celdas ocupadas.
- La extensión física real conocida es mínima. Nav2 (global planner) no podría trazar rutas fuera de ese mínimo espacio de centímetros y AMCL no tendría landmarks suficientes para correlacionar la pose.

## 8. Qué falta para pasar a HIL físico
- Instalar localmente y en la Raspberry Pi todo el meta-paquete de `nav2`.
- Realizar una sesión de mapeo con *movimiento real* (SLAM) guardando un rosbag completo y un mapa PGM íntegro de la ruta.
- Comprobar que el transformador TF del LiDAR publica el rayo en la orientación idéntica al entorno físico (LiDAR invertido).

## 9. Criterios mínimos antes de /cmd_vel
- [ ] Mapeo físico validado sin drifts graves en esquinas.
- [ ] Chequeo estricto de odometría al girar en el lugar (360°).
- [ ] Estructura tf (base_link -> odom -> map) contigua sin desconexiones o saltos bruscos.
- [ ] Emergency stop (E-stop) validado tanto remoto como hardware.
- [ ] Aprobación de operador para publicar de forma automatizada sobre el tópico `/cmd_vel`.

## 10. Resultado smoke test WSL
- **Paquetes instalados**: `ros-jazzy-navigation2`, `ros-jazzy-nav2-bringup`.
- **Paquetes detectados**: Se detectaron exitosamente `nav2_bringup`, `nav2_map_server`, `nav2_lifecycle_manager`, `nav2_planner`, `nav2_controller`, `nav2_bt_navigator`, `nav2_amcl`, `nav2_costmap_2d`, `tf2_ros`, `robot_state_publisher`.
- **Comando ejecutado**: `./tools/hil/nav2_offline_smoke_test.sh artifacts/maps/ottoguide_hil_stationary_map.yaml`
- **Resultado del smoke test**: PASS (map_server activado exitosamente).
- **/map publicado**: Sí, el lifecycle manager logró configurar y activar map_server (estado Active en ROS).
- **Logs locales generados**: Bajo `artifacts/logs/nav2_offline_smoke_<timestamp>/launch.log`.
- **Limitaciones**: Esto solo valida que las herramientas base de Nav2 instancian. No prueba navegadores ni controladores con transformadas reales o datos de LiDAR.
- **Recordatorio**: Esto **NO** valida navegación autónoma.
