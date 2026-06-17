#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACTS="$BASE/artifacts"
LATEST="$ARTIFACTS/physical_mapping_latest_run_id"

set +u
source /opt/ros/foxy/setup.bash
set -u

if [[ ! -f "$LATEST" ]]; then
  echo "FAIL: no latest mapping run id" >&2
  exit 1
fi

RUN_ID="$(cat "$LATEST")"
SESSION="$ARTIFACTS/physical_mapping_route_$RUN_ID"
PID_FILE="$SESSION/state/rosbag_pid.txt"
BAG_FILE="$SESSION/state/bag_dir.txt"

if [[ ! -f "$PID_FILE" ]]; then
  echo "FAIL: no rosbag PID file at $PID_FILE" >&2
  exit 1
fi

BAG_PID="$(cat "$PID_FILE")"
BAG_DIR="$(cat "$BAG_FILE" 2>/dev/null || true)"
LOG="$SESSION/logs/physical_mapping_stop.log"
exec > >(tee -a "$LOG") 2>&1

echo "RUN_ID=$RUN_ID"
echo "SESSION=$SESSION"
echo "BAG_PID=$BAG_PID"
echo "BAG_DIR=$BAG_DIR"

if kill -0 "$BAG_PID" 2>/dev/null; then
  echo "Sending SIGINT to rosbag PID=$BAG_PID"
  kill -INT "$BAG_PID"
  for _ in $(seq 1 60); do
    if ! kill -0 "$BAG_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
else
  echo "PARTIAL: rosbag PID is not alive"
fi

if kill -0 "$BAG_PID" 2>/dev/null; then
  echo "FAIL: rosbag PID still alive after SIGINT wait; not using kill -9"
  exit 1
fi

if [[ -n "$BAG_DIR" && -d "$BAG_DIR" ]]; then
  ros2 bag info "$BAG_DIR" > "$SESSION/logs/rosbag_info.log" 2>&1 || true
  cat "$SESSION/logs/rosbag_info.log"
fi

echo "PHYSICAL MAPPING STOP PASS"
