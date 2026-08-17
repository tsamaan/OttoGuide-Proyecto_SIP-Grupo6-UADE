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
        echo "WARN: using ROS 2 Jazzy for offline rosbag replay only; HIL target remains ROS 2 Foxy." >&2
        # shellcheck disable=SC1091
        source /opt/ros/jazzy/setup.bash
        return
    fi
}

set +u
source_ros
set -u

command -v ros2 >/dev/null 2>&1 || { echo >&2 "Error: ros2 is not installed or not in PATH."; exit 1; }

BAG="${1:-$HOME/ottoguide_bags/hil_mapping_stationary_retry_20260605_070755}"

if [ ! -d "$BAG" ]; then
    echo "Error: Bag directory $BAG does not exist."
    exit 1
fi

if [ ! -f "$BAG/metadata.yaml" ]; then
    echo "Error: Bag metadata $BAG/metadata.yaml does not exist."
    exit 1
fi

echo "Using BAG: $BAG"
ros2 bag info "$BAG"

RATE="${RATE:-0.25}"
READ_AHEAD="${READ_AHEAD:-10000}"

echo "Starting slow replay for RViz..."
echo "Use RViz with:"
echo "rviz2 -d ${CODE_ROOT}/tools/hil/rviz/ottoguide_hil_replay.rviz --ros-args -p use_sim_time:=true"

ros2 bag play "$BAG" \
  --clock \
  --read-ahead-queue-size "$READ_AHEAD" \
  --rate "$RATE"
