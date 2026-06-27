# Evidencia RViz local — OttoGuide

## Entorno

- Host: notebook Windows + WSL2 Ubuntu-24.04
- ROS 2: Jazzy
- Visualizador: RViz2
- Fuente: rosbag HIL local copiado desde robot
- Bag:
  $HOME/ottoguide_bags/hil_mapping_stationary_retry_20260605_070755

## Evidencias generadas

| Evidencia | Descripción | Estado |
|---|---|---|
| Video 1 · puntos actuales | Visualización de /utlidar/cloud instantáneo en RViz | OK |
| Video 2 · acumulación | Visualización acumulada por Decay Time en RViz | OK |
| Imagen · reconstrucción espacial acumulada | Captura de nube LiDAR acumulada sobre /map | OK |
| Mapa exportado | artifacts/maps/ottoguide_hil_stationary_map.pgm + .yaml | OK local, no versionable |

## Interpretación técnica

- /map representa un OccupancyGrid 2D generado por slam_toolbox.
- /scan representa la proyección 2D usada para SLAM.
- /utlidar/cloud representa la nube 3D del LiDAR Livox MID360.
- La nube acumulada se obtiene por Decay Time en RViz.
- Esta acumulación es visual y diagnóstica.
- No equivale a un mapa 3D métrico ni navegable.

## Limitaciones

- El rosbag actual es estacionario.
- No contiene un recorrido completo del entorno.
- No hay calibración TF real documentada para corregir el LiDAR invertido.
- No debe usarse como base de navegación autónoma.
- No se ejecutó Nav2.
- No se ejecutó /cmd_vel.
- No hubo locomoción autónoma.

## Uso recomendado en entrega

Usar las evidencias como demostración de:

1. replay local de datos HIL;
2. visualización de mapa 2D;
3. visualización de nube LiDAR;
4. acumulación diagnóstica del entorno;
5. preparación para futuras sesiones de mapeo con movimiento controlado.
