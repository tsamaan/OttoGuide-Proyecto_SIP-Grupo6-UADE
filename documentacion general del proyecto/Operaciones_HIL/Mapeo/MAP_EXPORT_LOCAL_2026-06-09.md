# Exportación de Mapa Local (HIL)

- **Entorno**: WSL Ubuntu-24.04 + ROS 2 Jazzy
- **Bag usado**: `artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755` (copiado localmente a `$HOME/ottoguide_bags/`)
- **Comando de replay**:
  ```bash
  ros2 bag play "$HOME/ottoguide_bags/hil_mapping_stationary_retry_20260605_070755" --clock --read-ahead-queue-size 10000
  ```
- **Comando map_saver_cli**:
  ```bash
  ros2 run nav2_map_server map_saver_cli -f artifacts/maps/ottoguide_hil_stationary_map
  ```
- **Ruta del archivo .pgm**: `artifacts/maps/ottoguide_hil_stationary_map.pgm`
- **Ruta del archivo .yaml**: `artifacts/maps/ottoguide_hil_stationary_map.yaml`
- **Detalles del mapa exportado**: 160x82, resolución 0.05.

> [!WARNING]
> Mapa exportado desde TF temporal diagnóstico, no apto todavía para navegación autónoma.
> Los archivos `.pgm` y `.yaml` están ignorados por git y **no deben ser versionados** (son evidencia local).
