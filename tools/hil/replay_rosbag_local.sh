#!/usr/bin/env bash
set -Eeuo pipefail

BAG_DIR="${1:-artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755}"

echo "BAG_DIR=$BAG_DIR"

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ERROR: ros2 no está disponible en PATH."
  echo "Ejecutar en Linux/WSL2/Ubuntu con ROS 2 Foxy o Humble."
  exit 1
fi

ros2 bag info "$BAG_DIR"
ros2 bag play "$BAG_DIR" --clock --loop
