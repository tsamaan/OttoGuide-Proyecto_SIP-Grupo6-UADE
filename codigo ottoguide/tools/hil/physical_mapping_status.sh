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
  echo "FAIL: no latest mapping run id at $LATEST" >&2
  exit 1
fi

RUN_ID="$(cat "$LATEST")"
SESSION="$ARTIFACTS/physical_mapping_route_$RUN_ID"
PID_FILE="$SESSION/state/rosbag_pid.txt"
BAG_FILE="$SESSION/state/bag_dir.txt"
LABEL_FILE="$SESSION/state/route_label.txt"
BAG_DIR="$(cat "$BAG_FILE" 2>/dev/null || true)"
PID="$(cat "$PID_FILE" 2>/dev/null || true)"

echo "RUN_ID=$RUN_ID"
echo "SESSION=$SESSION"
echo "ROUTE_LABEL=$(cat "$LABEL_FILE" 2>/dev/null || true)"
echo "BAG_DIR=$BAG_DIR"
echo "ROS_DISTRO=${ROS_DISTRO:-}"

if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
  echo "rosbag PID $PID is alive"
else
  echo "rosbag PID ${PID:-missing} is not alive"
fi

if [[ -n "$BAG_DIR" && -d "$BAG_DIR" ]]; then
  du -sh "$BAG_DIR" || true
  find "$BAG_DIR" -maxdepth 2 -type f -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' | sort | tail -20 || true
fi

echo "Recent session files:"
find "$SESSION" -maxdepth 3 -type f -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' | sort | tail -30 || true

echo "Last rosbag log lines:"
tail -40 "$SESSION/logs/rosbag_record.log" 2>/dev/null || true

echo "ROS topics:"
ros2 topic list || true

echo "/cmd_vel info:"
ros2 topic info /cmd_vel -v || true

echo "PHYSICAL MAPPING STATUS PASS"
