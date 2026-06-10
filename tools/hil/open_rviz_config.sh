#!/usr/bin/env bash
set -Eeuo pipefail

set +u
source /opt/ros/jazzy/setup.bash
set -u

command -v rviz2 >/dev/null 2>&1 || { echo >&2 "Error: rviz2 is not installed or not in PATH."; exit 1; }

CONFIG_TYPE="${1:-2d}"
REPO="/mnt/c/Users/lucas/Documents/OttoGuide-Proyecto_SIP-Grupo6-UADE"

case "$CONFIG_TYPE" in
  2d)
    CONFIG_FILE="$REPO/tools/hil/rviz/ottoguide_hil_replay_2d.rviz"
    ;;
  current)
    CONFIG_FILE="$REPO/tools/hil/rviz/ottoguide_hil_replay_cloud_current.rviz"
    ;;
  accumulated)
    CONFIG_FILE="$REPO/tools/hil/rviz/ottoguide_hil_replay_cloud_accumulated.rviz"
    ;;
  *)
    echo "Unknown config type: $CONFIG_TYPE. Using default 2d."
    CONFIG_FILE="$REPO/tools/hil/rviz/ottoguide_hil_replay_2d.rviz"
    ;;
esac

echo "Opening RViz2 with config: $CONFIG_FILE"
rviz2 -d "$CONFIG_FILE" --ros-args -p use_sim_time:=true
