#!/usr/bin/env bash
set -Eeuo pipefail

if [ -f "/opt/ros/jazzy/setup.bash" ]; then
    echo "ROS 2 Jazzy already installed."
    exit 0
fi

echo "=== Fase 4: Preparar repositorio apt de ROS 2 Jazzy ==="
sudo apt update
sudo apt install -y curl software-properties-common
sudo add-apt-repository universe -y
sudo apt update

export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F'"' '{print $4}')
curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb"
sudo dpkg -i /tmp/ros2-apt-source.deb
sudo apt update

echo "=== Fase 5: Instalar ROS 2 Jazzy Desktop y paquetes necesarios ==="
sudo apt install -y ros-jazzy-desktop ros-jazzy-ros2bag ros-jazzy-rosbag2-storage-sqlite3 ros-jazzy-nav2-map-server

echo "=== Fase 6: Activar entorno ROS 2 ==="
set +u
source /opt/ros/jazzy/setup.bash
set -u

ros2 --help | head -40
rviz2 --help | head -20 || true
