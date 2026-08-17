#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

source_ros() {
    if [[ -n "${ROS_DISTRO:-}" ]] && [[ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]]; then
        # shellcheck disable=SC1090
        source "/opt/ros/${ROS_DISTRO}/setup.bash"
        return
    fi
    if [[ -f /opt/ros/foxy/setup.bash ]]; then
        # shellcheck disable=SC1091
        source /opt/ros/foxy/setup.bash
        return
    fi
    if [[ -f /opt/ros/jazzy/setup.bash ]]; then
        echo "WARN: using ROS 2 Jazzy for offline RViz replay only; HIL target remains ROS 2 Foxy." >&2
        # shellcheck disable=SC1091
        source /opt/ros/jazzy/setup.bash
        return
    fi
}

set +u
source_ros
set -u

command -v rviz2 >/dev/null 2>&1 || { echo >&2 "Error: rviz2 is not installed or not in PATH."; exit 1; }

CONFIG_TYPE="${1:-2d}"

case "$CONFIG_TYPE" in
  2d)
    CONFIG_FILE="$CODE_ROOT/tools/hil/rviz/ottoguide_hil_replay_2d.rviz"
    ;;
  current)
    CONFIG_FILE="$CODE_ROOT/tools/hil/rviz/ottoguide_hil_replay_cloud_current.rviz"
    ;;
  accumulated)
    CONFIG_FILE="$CODE_ROOT/tools/hil/rviz/ottoguide_hil_replay_cloud_accumulated.rviz"
    ;;
  *)
    echo "Unknown config type: $CONFIG_TYPE. Using default 2d."
    CONFIG_FILE="$CODE_ROOT/tools/hil/rviz/ottoguide_hil_replay_2d.rviz"
    ;;
esac

echo "Opening RViz2 with config: $CONFIG_FILE"
rviz2 -d "$CONFIG_FILE" --ros-args -p use_sim_time:=true
