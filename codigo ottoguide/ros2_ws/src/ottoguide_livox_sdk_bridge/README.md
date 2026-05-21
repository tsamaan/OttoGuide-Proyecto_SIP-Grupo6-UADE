# OttoGuide Livox SDK2 bridge

Minimal ROS 2 Foxy bridge from Livox SDK2 to standard ROS sensor topics for OttoGuide HIL mapping.

This package uses the official Livox SDK2 C API (`livox_lidar_api.h`) and links
against `liblivox_lidar_sdk_shared.so`. It does not implement a custom Livox
wire protocol.

## Topics

- `/utlidar/cloud` (`sensor_msgs/msg/PointCloud2`)
- `/livox/imu` (`sensor_msgs/msg/Imu`)

`/utlidar/cloud` intentionally matches the Unitree ROS 2/LiDAR convention used
by the downstream mapping pipeline. IMU is published as `/livox/imu` to avoid
claiming compatibility with `livox_ros_driver2`'s `/utlidar/imu` behavior.

## Parameters

- `config_path`: Livox SDK2 JSON config. Default: `config/livox/mid360_sdk2_bridge.json`
- `frame_id`: ROS frame for cloud and IMU messages. Default: `utlidar_lidar`
- `topic_cloud`: point cloud topic. Default: `/utlidar/cloud`
- `topic_imu`: IMU topic. Default: `/livox/imu`
- `publish_pointcloud`: enable point cloud publisher. Default: `true`
- `publish_imu`: enable IMU publisher. Default: `true`

## Network

Default HIL config:

- Host / Companion PC: `192.168.123.164`
- Livox MID360: `192.168.123.120`
- Multicast: `224.1.1.5`
- LiDAR SDK2 ports: `56100`, `56200`, `56300`, `56400`, `56500`
- Host SDK2 ports: `56101`, `56201`, `56301`, `56401`, `56501`

If HIL proves that the MID360 is actually `192.168.123.20`, override the JSON
or `LIVOX_SDK2_CONFIG_PATH` for that session and record the result before
changing the default.

## Robot build

Build this package on the robot where ROS 2 Foxy and Livox SDK2 are installed:

```bash
cd /home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo\ ottoguide/ros2_ws
colcon build --packages-select ottoguide_livox_sdk_bridge
ldd install/ottoguide_livox_sdk_bridge/lib/ottoguide_livox_sdk_bridge/livox_sdk_bridge_node | grep livox_lidar_sdk_shared
```

The CMake configuration expects Livox SDK2 headers in `/home/unitree/Livox-SDK2/include` or `/usr/local/include`, and `liblivox_lidar_sdk_shared.so` in `/usr/local/lib`.

Do not run this bridge at the same time as `livox_ros_driver2`; both processes would compete for the same MID360 data path.

## Launch

```bash
export OTTOGUIDE_ROOT="/home/unitree/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide"
source /opt/ros/foxy/setup.bash
source "$OTTOGUIDE_ROOT/ros2_ws/install/setup.bash"
ros2 launch ottoguide_livox_sdk_bridge mid360_sdk2_bridge.launch.py
```

The launch file passes an absolute config path when `OTTOGUIDE_ROOT` or
`OTTOGUIDE_LIVOX_CONFIG` is set. Keep `frame_id=utlidar_lidar` unless the TF
tree is intentionally changed.
