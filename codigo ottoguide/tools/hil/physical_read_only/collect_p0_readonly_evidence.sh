#!/usr/bin/env bash
# Fase 2H.2.3 -- P0 PHYSICAL READ-ONLY evidence collector.
#
# STATUS: PREPARED_NOT_AUTHORIZED / NOT_EXECUTED.
#
# This script is prepared OFFLINE. It is designed to be run LOCALLY on the
# companion/robot host ONLY under a future, explicit authorization.
#
# It carries no remote-shell, no remote-copy, no hard-coded network address,
# and no remote-connection logic: it never reaches out to a robot, it is meant
# to already be running on one.
#
# It is strictly INTROSPECTION-ONLY. It MUST NOT, and does not:
#   * start any node, bring up any launch file, or run any control node
#   * change any lifecycle state or any parameter
#   * send any action goal, publish any topic, or call any control service
#   * emit any motion/velocity/mode command of any kind
#
# Real execution is double-gated: it requires BOTH the --execute-read-only flag
# AND the environment variable OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES. Without
# both, it stays in --dry-run (the default) and only prints what it *would* do.
# Every command that could block is wrapped in `timeout`.
set -euo pipefail

DRY_RUN=1
OUTPUT_DIR="./p0_readonly_evidence"
CMD_TIMEOUT="${OTTOGUIDE_P0_CMD_TIMEOUT:-10}"

usage() {
  cat <<'USAGE'
collect_p0_readonly_evidence.sh -- P0 physical READ-ONLY evidence collector.

  --dry-run             (default) print the read-only commands without running.
  --execute-read-only   run the read-only introspection (requires
                        OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES).
  --output-dir DIR      where to write p0_*.json (default ./p0_readonly_evidence).
  -h | --help           this help.

This tool never moves the robot, never sends a goal, never publishes a topic,
and never changes a parameter or lifecycle state. It is read-only by contract.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --execute-read-only) DRY_RUN=0 ;;
    --output-dir) OUTPUT_DIR="${2:?--output-dir needs a value}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "UNKNOWN_ARG:$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# Double authorization gate for real execution.
if [[ "$DRY_RUN" -eq 0 ]]; then
  if [[ "${OTTOGUIDE_P0_READ_ONLY_AUTHORIZED:-}" != "YES" ]]; then
    echo "P0_NOT_AUTHORIZED: real execution requires both --execute-read-only and" >&2
    echo "OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES. Staying safe; refusing to run." >&2
    exit 3
  fi
fi

# run_ro: execute a read-only introspection command under a hard timeout, or,
# in dry-run, just describe it. Failures/timeouts are recorded, never fatal.
run_ro() {
  local label="$1"; shift
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] ($label) would run: $*"
    return 0
  fi
  if ! timeout "$CMD_TIMEOUT" "$@"; then
    echo "RO_CMD_FAILED_OR_TIMEOUT:$label" >&2
  fi
}

mkdir -p "$OUTPUT_DIR"

# --- session meta: local git + ROS environment introspection only ----------
session_meta() {
  run_ro git_branch git branch --show-current
  run_ro git_head git rev-parse HEAD
  run_ro git_status git status --short --branch
  run_ro env_ros_distro printenv ROS_DISTRO
  run_ro env_rmw printenv RMW_IMPLEMENTATION
  run_ro env_cyclonedds_uri printenv CYCLONEDDS_URI
}

# --- ROS graph: list/info only (typed). No node is started. -----------------
ros_graph() {
  run_ro node_list ros2 node list
  run_ro action_list ros2 action list -t
  run_ro topic_list ros2 topic list -t
  run_ro service_list ros2 service list -t
}

# --- tf + localization: single-shot echoes, hard-timed -----------------------
tf_and_localization() {
  run_ro tf_static ros2 topic echo --once /tf_static
  run_ro odom_once ros2 topic echo --once /odom
}

# --- velocity chain: INSPECTION of the chain wiring, never publication ------
#   `ros2 topic info -v` reports publishers/subscribers and QoS; it does not
#   publish. Publishing to any velocity topic is forbidden and absent here.
velocity_chain_inspection() {
  run_ro cmd_vel_raw_info ros2 topic info -v /cmd_vel_raw
  run_ro cmd_vel_safe_info ros2 topic info -v /cmd_vel_safe
  run_ro cmd_vel_raw_hz ros2 topic hz /cmd_vel_raw
}

echo "P0 read-only collector: dry_run=${DRY_RUN}, output_dir=${OUTPUT_DIR}"
echo "This tool is introspection-only and never commands the robot."
session_meta
ros_graph
tf_and_localization
velocity_chain_inspection
echo "P0 read-only collection complete (dry_run=${DRY_RUN}). NOT_AUTHORIZED for movement."
