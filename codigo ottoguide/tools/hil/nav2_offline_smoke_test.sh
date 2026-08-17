#!/bin/bash
set -Eeuo pipefail

echo "=== Nav2 Offline Sandbox Smoke Test ==="
echo "Offline sandbox only: no real robot, no controller_server, no /cmd_vel."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${CODE_ROOT}/.." && pwd)"

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
        echo "WARN: using ROS 2 Jazzy for offline sandbox only; HIL target remains ROS 2 Foxy." >&2
        # shellcheck disable=SC1091
        source /opt/ros/jazzy/setup.bash
        return
    fi
}

# Load ROS 2
set +u
source_ros
set -u

# Validate ROS 2
if ! command -v ros2 &> /dev/null; then
    echo "FAIL: ros2 command not found. Source ROS_DISTRO, install ROS 2 Foxy, or provide Jazzy for offline sandbox only."
    exit 1
fi

# Validate map_server and lifecycle_manager
if ! ros2 pkg prefix nav2_map_server >/dev/null 2>&1; then
    echo "FAIL: nav2_map_server package missing. Cannot run smoke test."
    exit 1
fi

if ! ros2 pkg prefix nav2_lifecycle_manager >/dev/null 2>&1; then
    echo "FAIL: nav2_lifecycle_manager package missing. Cannot run smoke test."
    exit 1
fi

# Validate map yaml existence
MAP_YAML=${1:-"${REPO_ROOT}/artifacts/maps/ottoguide_hil_stationary_map.yaml"}
if [ ! -f "$MAP_YAML" ]; then
    echo "FAIL: Map YAML not found at $MAP_YAML"
    exit 1
fi

# Prepare logs directory
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_DIR="${REPO_ROOT}/artifacts/logs/nav2_offline_smoke_${TIMESTAMP}"
mkdir -p "$LOG_DIR"

echo "Running ros2 launch with timeout 10s..."
timeout 10 ros2 launch "${CODE_ROOT}/launch/offline_nav_sandbox.launch.py" map_yaml:="$MAP_YAML" > "${LOG_DIR}/launch.log" 2>&1 || true

# Check if processes are left hanging
pkill -f map_server || true
pkill -f lifecycle_manager || true

# Check log for success indicators
if grep -q "Activating map_server" "${LOG_DIR}/launch.log" || grep -q "Managed nodes are active" "${LOG_DIR}/launch.log"; then
    echo "PASS: map_server activated successfully."
    exit 0
else
    echo "FAIL: map_server failed to launch. Check logs at ${LOG_DIR}/launch.log"
    exit 1
fi
