# Scan Gate Configuration

## Objetivo del Gate
Proveer una configuración reproducible para arrancar el bridge de Livox SDK2 junto con `pointcloud_to_laserscan`, de manera estable y probada en HIL, garantizando la conversión de nubes de puntos 3D a escaneos 2D requeridos por Nav2/SLAM, sin activar la navegación completa.

## Historial de Tuning
- Commit base: `d2ae8fa`
- Problema detectado: La configuración inicial producía `finite ranges = 0` en ciertas pruebas debido a filtros de altura muy restrictivos o dinámicas del entorno.
- Combinación elegida: **Case F** (`min_height: -3.00`, `max_height: 3.00`, sin `target_frame` explícito). Esto permite capturar el volumen completo de la nube y retener el frame `utlidar_lidar` original, maximizando la detección de obstáculos cercanos.
- Aclaración: SLAM y Nav2 no fueron ejecutados durante esta validación.

## Entorno Requerido
```bash
source /opt/ros/foxy/setup.bash
source ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=0
export CYCLONEDDS_URI="file://$PWD/cyclonedds.xml"
```

## Comando de Ejecución
```bash
ros2 launch ottoguide_livox_sdk_bridge scan_gate.launch.py
```

## Criterio de Éxito
- `/scan` es visible vía `ros2 topic info`.
- Scan subscriber count > 0.
- Finite ranges > 0 en el escaneo procesado.
- Sin errores TF ni crasheos por load DDS.
- Sin activación de SLAM o Nav2.
