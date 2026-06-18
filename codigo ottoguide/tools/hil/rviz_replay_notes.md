# RViz2 replay notes — OttoGuide HIL bag

Fixed Frame:

- `map`

Displays:

- Map: `/map`
- LaserScan: `/scan`
- PointCloud2: `/utlidar/cloud`
- TF
- MarkerArray: `/slam_toolbox/graph_visualization`

Uso:

1. Terminal A: `codigo ottoguide/tools/hil/replay_rosbag_local.sh`
2. Terminal B: `rviz2`
3. Configurar displays.
4. Capturar video o screenshots.

Advertencia: TF temporal diagnóstico, no calibrado para navegación.
