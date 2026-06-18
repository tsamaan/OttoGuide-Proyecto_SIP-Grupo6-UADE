#!/usr/bin/env bash
set -Eeuo pipefail

set +u
source /opt/ros/jazzy/setup.bash
set -u

command -v ros2 >/dev/null 2>&1 || { echo >&2 "Error: ros2 is not installed or not in PATH."; exit 1; }

BAG="${1:-$HOME/ottoguide_bags/hil_mapping_stationary_retry_20260605_070755}"
REPO="/mnt/c/Users/lucas/Documents/OttoGuide-Proyecto_SIP-Grupo6-UADE"
MAP_BASENAME="${MAP_BASENAME:-ottoguide_hil_stationary_map}"
WAIT_SECONDS="${WAIT_SECONDS:-8}"

if [ ! -d "$BAG" ]; then
    echo "Error: Bag directory $BAG does not exist."
    exit 1
fi

if [ ! -f "$BAG/metadata.yaml" ]; then
    echo "Error: Bag metadata $BAG/metadata.yaml does not exist."
    exit 1
fi

echo "Creating map directory at $REPO/artifacts/maps"
mkdir -p "$REPO/artifacts/maps"

echo "Starting replay in background..."
ros2 bag play "$BAG" --clock --read-ahead-queue-size 10000 > /tmp/ottoguide_bag_play_map_export.log 2>&1 &
BAG_PID=$!

echo "Waiting $WAIT_SECONDS seconds for map data..."
sleep "$WAIT_SECONDS"

echo "Running map_saver_cli..."
ros2 run nav2_map_server map_saver_cli -f "$REPO/artifacts/maps/$MAP_BASENAME" || { echo "Error: map_saver_cli failed."; }

echo "Stopping replay (PID $BAG_PID)..."
kill -INT "$BAG_PID" 2>/dev/null || true
sleep 2

echo "Checking exported files:"
ls -lah "$REPO/artifacts/maps" || true
