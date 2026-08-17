#!/usr/bin/env bash
set -euo pipefail

RUN_SECONDS="${RUN_SECONDS:-30}"
ALLOW_START_ROSCORE="${ALLOW_START_ROSCORE:-NO}"
ALLOW_NO_INPUT_TEST="${ALLOW_NO_INPUT_TEST:-NO}"
SVO_LAUNCH_MODE="${SVO_LAUNCH_MODE:-rs_camera}"
REQUIRED_IMAGE_TOPIC="${REQUIRED_IMAGE_TOPIC:-/camera/infra1/image_rect_raw}"

case "$RUN_SECONDS" in
  ''|*[!0-9]*) echo "RUN_SECONDS must be a positive integer" >&2; exit 2 ;;
esac
if [ "$RUN_SECONDS" -lt 1 ]; then
  echo "RUN_SECONDS must be greater than zero" >&2
  exit 2
fi
if [ "$SVO_LAUNCH_MODE" != "rs_camera" ]; then
  echo "Only SVO_LAUNCH_MODE=rs_camera is prepared" >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$CODE_DIR/logs/svo_validation_$RUN_ID"
ODOMETER_WS="/home/unitree/unitree/Odometer_service"
SVO_LAUNCH="$ODOMETER_WS/src/rpg_svo_pro_open/svo_ros/launch/rs_camera.launch"
SUMMARY="$LOG_DIR/summary.txt"
SVO_LOG="$LOG_DIR/svo_node.log"
MASTER_LOG="$LOG_DIR/ros_master.log"
PIDS=()

cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

mkdir -p "$LOG_DIR"
exec > >(tee -a "$SUMMARY") 2>&1

echo "RUN_ID=$RUN_ID"
echo "RUN_SECONDS=$RUN_SECONDS"
echo "LOG_DIR=$LOG_DIR"
echo "SVO_LAUNCH_MODE=$SVO_LAUNCH_MODE"
echo "REQUIRED_IMAGE_TOPIC=$REQUIRED_IMAGE_TOPIC"
echo "VALIDATION_MODE=supervised_pose_output_only"

if [ ! -f /opt/ros/noetic/setup.bash ] || [ ! -f "$ODOMETER_WS/devel/setup.bash" ]; then
  echo "STOP_MISSING_ROS1_OR_ODOMETER_SETUP"
  exit 10
fi
if [ ! -f "$SVO_LAUNCH" ]; then
  echo "STOP_MISSING_SVO_LAUNCH"
  exit 11
fi

set +u
source /opt/ros/noetic/setup.bash
source "$ODOMETER_WS/devel/setup.bash"
set -u

if pgrep -afi '[s]vo[_]node|[r]oslaunch.*svo_ros|[n]odelet.*[Ss]vo' > "$LOG_DIR/existing_svo_runtime.txt"; then
  echo "STOP_EXISTING_SVO_RUNTIME_ACTIVE"
  cat "$LOG_DIR/existing_svo_runtime.txt"
  exit 12
fi
UNSAFE_REGEX='[n]av2|[/]cmd[_]vel|[s]port[c]lient|[l]oco[c]lient|[g]1[_-]loco|[l]ow[c]md|[s]lam[_]toolbox|[s]can[_]gate|[m]ap[_]saver|[o]dom[_]bridge'
if pgrep -afi "$UNSAFE_REGEX" > "$LOG_DIR/unsafe_runtime.txt"; then
  echo "STOP_UNSAFE_RUNTIME_ACTIVE"
  cat "$LOG_DIR/unsafe_runtime.txt"
  exit 12
fi

if ! timeout 3 rostopic list > "$LOG_DIR/topics_before.txt" 2> "$LOG_DIR/topics_before.err"; then
  if [ "$ALLOW_START_ROSCORE" != "YES" ]; then
    echo "STOP_ROS_MASTER_UNAVAILABLE_SET_ALLOW_START_ROSCORE_YES"
    exit 20
  fi
  roscore > "$MASTER_LOG" 2>&1 &
  MASTER_PID=$!
  PIDS+=("$MASTER_PID")
  sleep 2
  timeout 3 rostopic list > "$LOG_DIR/topics_before.txt"
fi

if ! grep -Fxq "$REQUIRED_IMAGE_TOPIC" "$LOG_DIR/topics_before.txt"; then
  if [ "$ALLOW_NO_INPUT_TEST" != "YES" ]; then
    echo "STOP_REQUIRED_IMAGE_TOPIC_MISSING_SET_ALLOW_NO_INPUT_TEST_YES"
    exit 21
  fi
  echo "WARNING_REQUIRED_IMAGE_TOPIC_MISSING_STARTUP_ONLY_TEST"
fi

roslaunch svo_ros rs_camera.launch > "$SVO_LOG" 2>&1 &
SVO_PID=$!
PIDS+=("$SVO_PID")
echo "SVO_PID=$SVO_PID"
sleep 2
if ! kill -0 "$SVO_PID" 2>/dev/null; then
  echo "STOP_SVO_EXITED_DURING_STARTUP"
  tail -n 100 "$SVO_LOG" || true
  exit 30
fi

timeout 3 rosnode list > "$LOG_DIR/nodes_after_start.txt" 2>&1 || true
timeout 3 rostopic list > "$LOG_DIR/topics_after_start.txt" 2>&1 || true

DEADLINE=$((SECONDS + RUN_SECONDS))
for topic in /svo/pose_imu /svo/pose_cam/0 /svo/info /svo/pointcloud /tf; do
  safe_name="$(printf '%s' "$topic" | tr '/' '_')"
  remaining=$((DEADLINE - SECONDS))
  if [ "$remaining" -le 0 ]; then
    break
  fi
  probe_seconds=4
  if [ "$remaining" -lt "$probe_seconds" ]; then
    probe_seconds="$remaining"
  fi
  timeout "$probe_seconds" rostopic hz -w 5 "$topic" > "$LOG_DIR/hz${safe_name}.txt" 2>&1 || true
  timeout 2 rostopic echo -n 1 "$topic" > "$LOG_DIR/echo${safe_name}.txt" 2>&1 || true
done

remaining=$((DEADLINE - SECONDS))
if [ "$remaining" -gt 0 ]; then
  sleep "$remaining"
fi

echo "SVO_ALIVE_AT_END=$(kill -0 "$SVO_PID" 2>/dev/null && echo YES || echo NO)"
echo "OUTPUT_TOPIC_SUMMARY"
timeout 3 rostopic list 2>/dev/null | grep -E '^/svo/|^/tf$' || true
echo "VALIDATION_COMPLETE"
