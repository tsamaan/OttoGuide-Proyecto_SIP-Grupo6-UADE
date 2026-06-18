#!/bin/bash
set +u
source /opt/ros/jazzy/setup.bash
set -u

echo '=== ROS distro ==='
echo $ROS_DISTRO

echo '=== Nav2 packages ==='
for p in nav2_bringup nav2_map_server nav2_lifecycle_manager nav2_planner nav2_controller nav2_bt_navigator nav2_amcl nav2_costmap_2d tf2_ros robot_state_publisher; do
  if ros2 pkg prefix $p >/dev/null 2>&1; then
    echo "OK $p -> $(ros2 pkg prefix $p)"
  else
    echo "MISSING $p"
  fi
done
