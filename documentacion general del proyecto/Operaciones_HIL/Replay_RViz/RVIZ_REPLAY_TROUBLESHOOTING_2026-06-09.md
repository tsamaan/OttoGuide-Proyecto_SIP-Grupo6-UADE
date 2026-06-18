# Troubleshooting RViz Replay

## Problema Original
El usuario reportó que RViz abría vacío, no mostraba el mapa ni los puntos, y se registraban errores como:
- `Invalid topic name: topic name must not be empty string`
- `TF_OLD_DATA`
- `Message queue starved`

## Correcciones Aplicadas
- **Bag copiado a WSL home**: Para evitar cuellos de botella de IO al leer un archivo de 500 MB desde `/mnt/c`.
- **Read-ahead queue aumentada**: Se aumentó la cola a 10000 para evitar que el bag reproductor se quede sin datos pre-cacheados.
- **use_sim_time:=true**: Configurado para que RViz utilice `/clock` del bag en lugar de la hora actual de la computadora.
- **RViz config automática**: Se generaron configuraciones `.rviz` prearmadas para evitar tópicos vacíos por abrir RViz antes que el bag.
- **Map Update Topic corregido**: Se eliminó el string vacío `""` y se asignó `/map_updates`.
- **Protección de entorno ROS (`set +u`)**: Se ajustaron los scripts Bash que usan `set -u` temporalmente apagándolo al llamar `setup.bash` de ROS, que tiene variables sin inicializar.

## Comandos de Uso Final
Para reproducir la grabación y visualizar correctamente, usar dos terminales:
1. RViz2 auto-configurado: `"codigo ottoguide/tools/hil/open_rviz_config.sh" [2d|current|accumulated]`
2. Reproduccion de datos (lenta y estable): `"codigo ottoguide/tools/hil/replay_rosbag_rviz_slow.sh"`

## Tipos de Visualización (Limitaciones)
- **Mapa 2D (`/map`)**: Es el mapa bidimensional publicado por `slam_toolbox`.
- **Nube actual (`/utlidar/cloud`)**: Los puntos instantáneos escaneados por el LiDAR Livox MID360.
- **Acumulación visual (`Decay Time`)**: Configurar el `Decay Time` alto en RViz para ver la historia de la nube, simulando un mapeo denso. **Advertencia: El LiDAR MID360 parece estar físicamente invertido y los puntos se visualizan "girando" en RViz.**
- **Mapa 3D real**: **No disponible con bag estacionario**. La nube acumulada en RViz sirve como visualización diagnóstica, no como reconstrucción 3D métrica completa. Se requiere un recorrido real con odometría para obtener un mapeo volumétrico.
