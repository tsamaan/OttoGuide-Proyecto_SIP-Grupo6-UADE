#!/usr/bin/env bash
set -Eeuo pipefail

BASE_DEFAULT="/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide"
BASE="${BASE:-$BASE_DEFAULT}"
ART="$BASE/artifacts"
LATEST="$ART/office_sensor_capture_latest_run_id"

MODE=""
DURATION=""
LABEL="office_short_remote_control_raw"
BAG_NAME=""

usage() {
  cat <<USAGE
Usage:
  $0 --mode start [--route-label LABEL] [--bag-name NAME]
  $0 --mode timed --duration SECONDS [--route-label LABEL] [--bag-name NAME]
  $0 --mode status
  $0 --mode stop
  $0 --mode package

This script records a raw sensor-only rosbag.
It does not publish /cmd_vel.
It does not move the robot.
It does not require /tf.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --duration) DURATION="${2:-}"; shift 2 ;;
    --route-label) LABEL="${2:-}"; shift 2 ;;
    --bag-name) BAG_NAME="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

load_ros() {
  set +u
  source /opt/ros/foxy/setup.bash
  if [[ -f "$BASE/ros2_ws/install/setup.bash" ]]; then
    source "$BASE/ros2_ws/install/setup.bash"
  fi
  set -u
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
  if [[ -z "${CYCLONEDDS_URI:-}" && -f "$BASE/config/cyclonedds.foxy.xml" ]]; then
    export CYCLONEDDS_URI="file://$BASE/config/cyclonedds.foxy.xml"
  fi
}

new_session() {
  RUN_ID="$(date +%Y%m%d_%H%M%S)"
  SESSION="$ART/office_sensor_capture_$RUN_ID"
  mkdir -p "$SESSION/logs" "$SESSION/rosbags" "$SESSION/state" "$SESSION/manifests" "$SESSION/reports"
  echo "$RUN_ID" > "$LATEST"
  echo "$SESSION" > "$SESSION/state/session_dir.txt"
  echo "$LABEL" > "$SESSION/state/route_label.txt"
}

get_latest_session() {
  if [[ ! -f "$LATEST" ]]; then
    echo "No latest run id found: $LATEST" >&2
    exit 1
  fi
  RUN_ID="$(cat "$LATEST")"
  SESSION="$ART/office_sensor_capture_$RUN_ID"
  if [[ ! -d "$SESSION" ]]; then
    echo "Session dir not found: $SESSION" >&2
    exit 1
  fi
}

topic_exists() {
  ros2 topic list | grep -Fxq "$1"
}

build_topics_file() {
  local f="$1"
  : > "$f"

  for t in \
    /utlidar/cloud \
    /livox/imu \
    /scan \
    /tf \
    /tf_static \
    /odom \
    /map \
    /map_metadata \
    /slam_toolbox/graph_visualization \
    /slam_toolbox/scan_visualization \
    /cmd_vel
  do
    if topic_exists "$t"; then
      echo "$t" >> "$f"
    fi
  done

  ros2 topic list | grep -Ei "cmd|vel|odom|sport|low|state|joint|imu|unitree|wireless|joy|remote|controller" \
    | sort -u >> "$f" || true

  sort -u "$f" -o "$f"
}

capture_header() {
  local topic="$1"
  local output="$2"
  timeout 5s ros2 topic echo "$topic" > "$output" 2>&1 || true
}

start_recording() {
  load_ros
  new_session

  {
    date
    hostname
    whoami
    pwd
    echo "LABEL=$LABEL"
    echo "ROS_DISTRO=${ROS_DISTRO:-}"
    echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-}"
    echo "CYCLONEDDS_URI=${CYCLONEDDS_URI:-}"
    ros2 topic list
  } > "$SESSION/logs/baseline.log" 2>&1 || true

  capture_header /utlidar/cloud "$SESSION/logs/cloud_sample.log"
  capture_header /scan "$SESSION/logs/scan_sample.log"
  capture_header /livox/imu "$SESSION/logs/imu_sample.log"

  TOPICS_FILE="$SESSION/state/topics_to_record.txt"
  build_topics_file "$TOPICS_FILE"

  if ! grep -Fxq "/utlidar/cloud" "$TOPICS_FILE" && ! grep -Fxq "/scan" "$TOPICS_FILE"; then
    echo "ERROR: neither /utlidar/cloud nor /scan is available. Refusing to record." >&2
    exit 3
  fi

  BAG_DIR="$SESSION/rosbags/${BAG_NAME:-office_sensor_capture_$RUN_ID}"
  echo "$BAG_DIR" > "$SESSION/state/bag_dir.txt"

  echo "Recording topics:"
  cat "$TOPICS_FILE"

  mapfile -t TOPICS < "$TOPICS_FILE"
  ros2 bag record -o "$BAG_DIR" "${TOPICS[@]}" \
    > "$SESSION/logs/rosbag_record.log" 2>&1 &

  BAG_PID=$!
  echo "$BAG_PID" > "$SESSION/state/rosbag_pid.txt"

  echo "RUN_ID=$RUN_ID"
  echo "SESSION=$SESSION"
  echo "BAG_DIR=$BAG_DIR"
  echo "BAG_PID=$BAG_PID"
  echo "Status with: $0 --mode status"
  echo "Stop with: $0 --mode stop"
}

stop_recording() {
  load_ros
  get_latest_session

  BAG_PID="$(cat "$SESSION/state/rosbag_pid.txt" 2>/dev/null || true)"
  BAG_DIR="$(cat "$SESSION/state/bag_dir.txt" 2>/dev/null || true)"

  if [[ -n "$BAG_PID" ]] && ps -p "$BAG_PID" >/dev/null 2>&1; then
    kill -INT "$BAG_PID"
    while ps -p "$BAG_PID" >/dev/null 2>&1; do
      sleep 1
    done
    sleep 3
  fi

  if [[ -n "$BAG_DIR" && -d "$BAG_DIR" ]]; then
    ros2 bag info "$BAG_DIR" > "$SESSION/logs/rosbag_info.log" 2>&1 || true
  fi

  find "$SESSION" -type f -printf "%p %s bytes\n" | sort > "$SESSION/manifests/FILES_SIZES.txt" || true
  (cd "$SESSION" && find . -type f ! -path './manifests/SHA256SUMS.txt' -print0 | sort -z | xargs -0 sha256sum) > "$SESSION/manifests/SHA256SUMS.txt" 2>/dev/null || true

  cat > "$SESSION/README.md" <<README
# Office sensor capture - OttoGuide

RUN_ID: $RUN_ID
Label: $(cat "$SESSION/state/route_label.txt" 2>/dev/null || true)

Purpose:
Raw sensor-only office capture.

Notes:
- This capture does not require /tf.
- It does not validate autonomous navigation.
- It does not imply map export will work immediately.
- Use offline replay to reconstruct TF/SLAM/map if needed.
README

  echo "Stopped."
  echo "SESSION=$SESSION"
  echo "BAG_DIR=$BAG_DIR"
}

status_run() {
  load_ros
  get_latest_session

  echo "RUN_ID=$RUN_ID"
  echo "SESSION=$SESSION"
  cat "$SESSION/state/route_label.txt" 2>/dev/null || true

  if [[ -f "$SESSION/state/rosbag_pid.txt" ]]; then
    BAG_PID="$(cat "$SESSION/state/rosbag_pid.txt")"
    echo "BAG_PID=$BAG_PID"
    ps -p "$BAG_PID" -o pid,ppid,cmd || true
  fi

  if [[ -f "$SESSION/state/bag_dir.txt" ]]; then
    BAG_DIR="$(cat "$SESSION/state/bag_dir.txt")"
    echo "BAG_DIR=$BAG_DIR"
    du -sh "$BAG_DIR" 2>/dev/null || true
  fi

  echo "Topics currently available:"
  ros2 topic list | sort

  echo "Recent rosbag log:"
  tail -40 "$SESSION/logs/rosbag_record.log" 2>/dev/null || true
}

package_run() {
  get_latest_session
  TAR="/tmp/office_sensor_capture_${RUN_ID}.tar.gz"
  tar -czf "$TAR" -C "$ART" "office_sensor_capture_$RUN_ID"
  sha256sum "$TAR" > "${TAR}.sha256"
  echo "TAR=$TAR"
  echo "SHA256=${TAR}.sha256"
  echo "PowerShell copy command:"
  echo "scp -i \"\$env:USERPROFILE\\.ssh\\id_ed25519_ottoguide_robot\" unitree@192.168.123.164:$TAR \"C:\\Users\\lucas\\Documents\\OttoGuide-Proyecto_SIP-Grupo6-UADE\\artifacts\\\""
}

case "$MODE" in
  start)
    start_recording
    ;;
  timed)
    if [[ -z "$DURATION" ]]; then
      echo "--duration required for timed mode" >&2
      exit 2
    fi
    start_recording
    sleep "$DURATION"
    stop_recording
    ;;
  stop)
    stop_recording
    ;;
  status)
    status_run
    ;;
  package)
    package_run
    ;;
  *)
    usage
    exit 2
    ;;
esac
