# OttoGuide Livox SDK2 bridge

Minimal ROS 2 Foxy bridge from Livox SDK2 to standard ROS sensor topics for OttoGuide HIL mapping.

## Topics

- `/utlidar/cloud` (`sensor_msgs/msg/PointCloud2`)
- `/livox/imu` (`sensor_msgs/msg/Imu`)

## Parameters

- `config_path`: Livox SDK2 JSON config. Default: `config/livox/mid360_sdk2_bridge.json`
- `frame_id`: ROS frame for cloud and IMU messages. Default: `livox_frame`
- `topic_cloud`: point cloud topic. Default: `/utlidar/cloud`
- `topic_imu`: IMU topic. Default: `/livox/imu`
- `publish_pointcloud`: enable point cloud publisher. Default: `true`
- `publish_imu`: enable IMU publisher. Default: `true`

## Robot build

Build this package on the robot where ROS 2 Foxy and Livox SDK2 are installed:

```bash
cd /home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo\ ottoguide/ros2_ws
colcon build --packages-select ottoguide_livox_sdk_bridge
```

The CMake configuration expects Livox SDK2 headers in `/home/unitree/Livox-SDK2/include` or `/usr/local/include`, and `liblivox_lidar_sdk_shared.so` in `/usr/local/lib`.

Do not run this bridge at the same time as `livox_ros_driver2`; both processes would compete for the same MID360 data path.
