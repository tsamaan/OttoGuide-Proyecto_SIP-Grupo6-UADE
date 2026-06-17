#!/usr/bin/env bash
set -Eeuo pipefail

MODE="preflight"
DURATION=""
ROUTE_LABEL="ruta_real_mvp_lima3_lima2"
BAG_NAME=""
DRY_RUN=0
PREFLIGHT_ONLY=0
TOPICS_MODE="default"

usage() {
  cat <<'USAGE'
Usage:
  physical_mapping_route.sh --preflight-only
  physical_mapping_route.sh --mode start --route-label "ruta_real_mvp_lima3_lima2"
  physical_mapping_route.sh --mode timed --duration 1800 --route-label "ruta_real_mvp_lima3_lima2"

This script records evidence only. It never publishes /cmd_vel.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:?missing mode}"; shift 2 ;;
    --duration) DURATION="${2:?missing duration}"; shift 2 ;;
    --route-label) ROUTE_LABEL="${2:?missing route label}"; shift 2 ;;
    --bag-name) BAG_NAME="${2:?missing bag name}"; shift 2 ;;
    --topics) TOPICS_MODE="${2:?missing topics mode}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --preflight-only) PREFLIGHT_ONLY=1; MODE="preflight"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$MODE" != "start" && "$MODE" != "timed" && "$MODE" != "preflight" ]]; then
  echo "FAIL: unsupported mode: $MODE" >&2
  exit 2
fi
if [[ "$MODE" == "timed" && -z "$DURATION" ]]; then
  echo "FAIL: --duration is required for timed mode" >&2
  exit 2
fi
if [[ "$TOPICS_MODE" != "default" ]]; then
  echo "FAIL: only --topics default is currently supported" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACTS="$BASE/artifacts"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
SESSION="$ARTIFACTS/physical_mapping_route_$RUN_ID"
BAG_NAME="${BAG_NAME:-route_mapping_$RUN_ID}"
BAG_DIR="$SESSION/rosbags/$BAG_NAME"

mkdir -p "$SESSION/logs" "$SESSION/rosbags" "$SESSION/maps/raw" "$SESSION/maps/cleaned" "$SESSION/manifests" "$SESSION/state" "$SESSION/reports"
printf '%s\n' "$RUN_ID" > "$ARTIFACTS/physical_mapping_latest_run_id"
printf '%s\n' "$SESSION" > "$SESSION/state/session_dir.txt"
printf '%s\n' "$ROUTE_LABEL" > "$SESSION/state/route_label.txt"
printf '%s\n' "$BAG_DIR" > "$SESSION/state/bag_dir.txt"

LOG="$SESSION/logs/preflight.log"
exec > >(tee -a "$LOG") 2>&1

echo "RUN_ID=$RUN_ID"
echo "SESSION=$SESSION"
echo "ROUTE_LABEL=$ROUTE_LABEL"
echo "MODE=$MODE"
echo "SAFETY: this script does not publish /cmd_vel"

set +u
source /opt/ros/foxy/setup.bash
set -u

echo "ROS_DISTRO=${ROS_DISTRO:-}"
if [[ "${ROS_DISTRO:-}" != "foxy" ]]; then
  echo "FAIL: ROS 2 Foxy is not active"
  exit 1
fi

{
  echo "## Baseline"
  date
  hostname || true
  whoami || true
  pwd
  git -C "$BASE" status --short --branch --untracked-files=all || true
  git -C "$BASE" rev-parse --short HEAD || true
  ip -br addr || true
  ip route || true
  env | grep -E '^(ROS_|RMW_|CYCLONEDDS_)' || true
} > "$SESSION/logs/baseline.log" 2>&1

TOPICS=(/utlidar/cloud /livox/imu /scan /tf /tf_static /odom /map /map_metadata /slam_toolbox/graph_visualization /slam_toolbox/scan_visualization /cmd_vel)

echo "ROS topic list:"
ros2 topic list | tee "$SESSION/logs/ros2_topic_list.log" || true

CRITICAL_MISSING=0
for topic in /utlidar/cloud /scan /tf /tf_static; do
  if ros2 topic list | grep -Fxq "$topic"; then
    echo "PASS: topic present $topic"
  else
    echo "FAIL: missing critical topic $topic"
    CRITICAL_MISSING=1
  fi
done
for topic in /odom /map /map_metadata /livox/imu; do
  if ros2 topic list | grep -Fxq "$topic"; then
    echo "PASS: optional topic present $topic"
  else
    echo "PARTIAL: optional topic missing $topic"
  fi
done

ros2 topic info /cmd_vel -v > "$SESSION/logs/cmd_vel_info.log" 2>&1 || true
cat "$SESSION/logs/cmd_vel_info.log"

if [[ "$CRITICAL_MISSING" -ne 0 ]]; then
  echo "PHYSICAL MAPPING PREFLIGHT FAIL"
  exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'DRY RUN: ros2 bag record -o %q %s\n' "$BAG_DIR" "${TOPICS[*]}"
  echo "PHYSICAL MAPPING DRY RUN PASS"
  exit 0
fi

if [[ "$PREFLIGHT_ONLY" -eq 1 || "$MODE" == "preflight" ]]; then
  echo "PHYSICAL MAPPING PREFLIGHT PASS"
  exit 0
fi

echo "Starting rosbag at $BAG_DIR"
ros2 bag record -o "$BAG_DIR" "${TOPICS[@]}" > "$SESSION/logs/rosbag_record.log" 2>&1 &
BAG_PID=$!
printf '%s\n' "$BAG_PID" > "$SESSION/state/rosbag_pid.txt"
echo "PASS: rosbag started PID=$BAG_PID"

if [[ "$MODE" == "start" ]]; then
  echo "PHYSICAL MAPPING START PASS"
  exit 0
fi

echo "Timed recording for $DURATION seconds"
sleep "$DURATION"
echo "Sending SIGINT to rosbag PID=$BAG_PID"
kill -INT "$BAG_PID"
set +e
wait "$BAG_PID"
BAG_RC=$?
set -e
echo "rosbag wait rc=$BAG_RC"
ros2 bag info "$BAG_DIR" > "$SESSION/logs/rosbag_info.log" 2>&1 || true
cat "$SESSION/logs/rosbag_info.log"
echo "PHYSICAL MAPPING TIMED PASS"
