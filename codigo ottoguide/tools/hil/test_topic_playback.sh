#!/usr/bin/env bash
set -Eeuo pipefail

set +u
source /opt/ros/jazzy/setup.bash
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

echo "Starting replay for topic testing..."
ros2 bag play "$BAG" \
  --clock \
  --read-ahead-queue-size 10000 \
  --rate 0.25 \
  > /tmp/ottoguide_replay_topic_test.log 2>&1 &

BAG_PID=$!
echo "BAG_PID=$BAG_PID"

sleep 5

echo "--- /clock ---"
timeout 5 ros2 topic echo /clock --once > /dev/null && echo "PASS: /clock" || echo "FAIL: /clock"

echo "--- /map ---"
timeout 8 ros2 topic echo /map --once > /dev/null && echo "PASS: /map" || echo "FAIL: /map"

echo "--- /scan ---"
timeout 8 ros2 topic echo /scan --once > /dev/null && echo "PASS: /scan" || echo "FAIL: /scan"

echo "--- /utlidar/cloud ---"
timeout 8 ros2 topic echo /utlidar/cloud --once --field header > /dev/null && echo "PASS: /utlidar/cloud" || echo "FAIL: /utlidar/cloud"

echo "Stopping replay (PID $BAG_PID)..."
kill -INT "$BAG_PID" 2>/dev/null || true
sleep 2

echo "Done."
