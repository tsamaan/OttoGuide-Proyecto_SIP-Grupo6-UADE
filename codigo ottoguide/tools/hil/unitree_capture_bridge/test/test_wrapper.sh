#!/usr/bin/env bash
# Offline integration tests for the unitree-capture-bridge wrapper's command
# lifecycle (plan/start/status/stop/validate). Runs entirely against fake
# ros2/ip/ldd and dummy self-owned processes under a per-case temp directory -
# never a real ROS graph, never a real signal to a process this suite did
# not itself spawn.
set -Eeuo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$TEST_DIR/../scripts/unitree-capture-bridge"
FIXTURES="$TEST_DIR/fixtures"
REAL_SLEEP="$(readlink -f "$(command -v sleep)")"
REAL_FALSE="$(readlink -f "$(command -v false)")"
# `yes` ignores its argv entirely and blocks forever writing to stdout until
# signaled - the only common coreutils binary that can stand in for the real
# tap (which is invoked as `$TAP_BIN $NET_IFACE $DDS_DOMAIN`, arguments a
# stand-in like `sleep`/`cat` cannot swallow without erroring) while still
# being a real ELF file usable for /proc/<pid>/exe identity checks.
REAL_YES="$(readlink -f "$(command -v yes)")"

PASS=0
FAIL=0

check() {
  local name="$1" rc="$2"
  if [[ "$rc" == "0" ]]; then
    PASS=$((PASS + 1))
    echo "PASS: $name"
  else
    FAIL=$((FAIL + 1))
    echo "FAIL: $name"
  fi
}

run() {
  local name="$1"
  shift
  if "$@" >/tmp/ottoguide_test_wrapper_case.$$ 2>&1; then
    check "$name" 0
  else
    check "$name" 1
    sed 's/^/    /' "/tmp/ottoguide_test_wrapper_case.$$"
  fi
  rm -f "/tmp/ottoguide_test_wrapper_case.$$"
}

# Each case gets a fresh isolated tmp dir for PID files / IPC socket, and
# sources the wrapper inside its own subshell so set -e aborts (the
# behavior under test, in several cases) never affect the test runner.
new_case_env() {
  CASE_TMP="$(mktemp -d)"
  export TAP_PID_FILE="$CASE_TMP/tap.pid"
  export BRIDGE_PID_FILE="$CASE_TMP/bridge.pid"
  export IPC_SOCK="$CASE_TMP/capture.sock"
  export TAP_LOG="$CASE_TMP/tap.log"
  export BRIDGE_LOG="$CASE_TMP/bridge.log"
  export NET_IFACE=lo
  export DDS_DOMAIN=0
  export ROS_FOXY_SETUP="$FIXTURES/ros_setup_noop.bash"
  export ROS_QUERY_TIMEOUT=2
  export PATH="$FIXTURES/bin:$PATH"
  export BRIDGE_EXECUTABLE="$FIXTURES/fake_bridge_node.py"
  # Default: the isolated-ldd gate passes, so tests targeting other gates
  # reach them. Tests of the gate itself override FAKE_LDD_MODE.
  export SDK_ROOT="$CASE_TMP/fake_sdk"
  export TAP_LD_LIBRARY_PATH="$SDK_ROOT/lib/aarch64:$SDK_ROOT/thirdparty/lib/aarch64"
  export FAKE_LDD_MODE=ok
  export FAKE_LDD_SDK_ROOT="$SDK_ROOT"
  unset FAKE_ROS2_PUB_CMD_VEL FAKE_ROS2_PUB_ODOM FAKE_ROS2_TOPIC_LIST_FAIL \
        FAKE_ROS2_TOPICS_STR FAKE_BRIDGE_CREATE_SOCKET FAKE_BRIDGE_EXIT_IMMEDIATELY || true
}

cleanup_case_env() {
  [[ -n "${CASE_TMP:-}" ]] && rm -rf "$CASE_TMP"
}

# Runs cmd_start (with TAP_BIN already exported by the caller) in an
# isolated subshell and reports whether it SUCCEEDED. A 0 return from this
# helper means cmd_start did NOT block - the opposite of what most of the
# cases below want, so callers branch on it explicitly instead of relying
# on subshell-failure-equals-test-failure.
attempt_start() {
  ( source "$WRAPPER"; cmd_start >/dev/null 2>&1 )
}

# --- plan / status never start anything ------------------------------------

case_plan_starts_no_processes() {
  new_case_env
  trap cleanup_case_env RETURN
  ( source "$WRAPPER"; cmd_plan >/dev/null )
  local rc=$?
  [[ -f "$TAP_PID_FILE" ]] && return 1
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return $rc
}

case_status_starts_no_processes() {
  new_case_env
  trap cleanup_case_env RETURN
  ( source "$WRAPPER"; cmd_status >/dev/null )
  [[ -f "$TAP_PID_FILE" ]] && return 1
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

# --- start blocks on unsafe / unknown conditions ---------------------------

case_start_blocks_on_cmd_vel_publisher() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_ROS2_PUB_CMD_VEL=one
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded with an active /cmd_vel publisher" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && { echo "bridge was started despite unsafe /cmd_vel" >&2; return 1; }
  return 0
}

case_start_blocks_on_odom_publisher() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_ROS2_PUB_ODOM=one
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded with an active /odom publisher" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

case_start_blocks_on_unknown_ros_query() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_ROS2_PUB_CMD_VEL=fail
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded when the ROS query itself failed" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

case_start_blocks_on_nav2() {
  new_case_env
  trap cleanup_case_env RETURN
  export TAP_BIN="$REAL_YES"
  bash -c 'exec -a bt_navigator sleep 30' &
  local dummy=$!
  sleep 0.2
  local started_ok=0
  attempt_start && started_ok=1
  kill -9 "$dummy" 2>/dev/null || true
  wait "$dummy" 2>/dev/null || true
  if [[ "$started_ok" == "1" ]]; then
    echo "cmd_start incorrectly succeeded with a Nav2-named process running" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

case_start_blocks_on_slam() {
  new_case_env
  trap cleanup_case_env RETURN
  export TAP_BIN="$REAL_YES"
  bash -c 'exec -a slam_toolbox sleep 30' &
  local dummy=$!
  sleep 0.2
  local started_ok=0
  attempt_start && started_ok=1
  kill -9 "$dummy" 2>/dev/null || true
  wait "$dummy" 2>/dev/null || true
  if [[ "$started_ok" == "1" ]]; then
    echo "cmd_start incorrectly succeeded with a SLAM-named process running" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

# --- tap DDS library isolation gate (new) ----------------------------------

case_start_blocks_when_tap_libraries_missing() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_LDD_MODE=missing
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded although a tap DDS library was unresolved" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && { echo "bridge was started before the library gate" >&2; return 1; }
  [[ -f "$TAP_PID_FILE" ]] && return 1
  return 0
}

case_start_blocks_when_tap_libraries_resolve_outside_sdk() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_LDD_MODE=wrong_sdk
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded although tap DDS libs resolved outside the SDK" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

case_start_blocks_when_ldd_itself_fails() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_LDD_MODE=fail
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded although ldd failed" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

case_tap_env_isolation_uses_sdk_path_and_clears_ros_vars() {
  # Concrete proof that the tap's actual launch environment carries the SDK
  # LD_LIBRARY_PATH and not whatever ROS/CycloneDDS variables happen to be
  # exported in the calling shell - not just an inspection of the helper's
  # output, but the real environment `env` would hand to the child.
  new_case_env
  trap cleanup_case_env RETURN
  (
    source "$WRAPPER"
    export CYCLONEDDS_URI=/should/not/leak/into/tap
    export ROS_DOMAIN_ID=99
    export PYTHONPATH=/should/not/leak/either
    build_tap_env_args
    dumped="$(env "${TAP_ENV_ARGS[@]}" env)"
    if grep -q '^CYCLONEDDS_URI=' <<<"$dumped"; then
      echo "CYCLONEDDS_URI leaked into the tap environment" >&2
      exit 1
    fi
    if grep -q '^ROS_DOMAIN_ID=' <<<"$dumped"; then
      echo "ROS_DOMAIN_ID leaked into the tap environment" >&2
      exit 1
    fi
    if grep -q '^PYTHONPATH=' <<<"$dumped"; then
      echo "PYTHONPATH leaked into the tap environment" >&2
      exit 1
    fi
    if ! grep -qF "LD_LIBRARY_PATH=$TAP_LD_LIBRARY_PATH" <<<"$dumped"; then
      echo "tap environment is missing the expected SDK LD_LIBRARY_PATH" >&2
      exit 1
    fi
  )
}

# --- bridge / tap startup failure handling ---------------------------------

case_bridge_failing_to_create_socket_is_detected() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_BRIDGE_CREATE_SOCKET=0
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded although the bridge never created the socket" >&2
    return 1
  fi
  [[ -S "$IPC_SOCK" ]] && return 1
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

case_bridge_crashing_immediately_is_detected() {
  new_case_env
  trap cleanup_case_env RETURN
  export FAKE_BRIDGE_EXIT_IMMEDIATELY=1
  export TAP_BIN="$REAL_YES"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded although the bridge crashed immediately" >&2
    return 1
  fi
  [[ -f "$BRIDGE_PID_FILE" ]] && return 1
  return 0
}

case_tap_exiting_during_startup_is_detected() {
  new_case_env
  trap cleanup_case_env RETURN
  export TAP_BIN="$REAL_FALSE"
  if attempt_start; then
    echo "cmd_start incorrectly succeeded although the tap exited immediately" >&2
    return 1
  fi
  [[ -f "$TAP_PID_FILE" ]] && return 1
  # cmd_start must clean up the bridge it already started before the tap
  # was found dead - no PID file, no leftover process, no socket.
  [[ -f "$BRIDGE_PID_FILE" ]] && { echo "bridge PID file remained after tap startup failure" >&2; return 1; }
  [[ -S "$IPC_SOCK" ]] && { echo "IPC socket remained after tap startup failure" >&2; return 1; }
  return 0
}

# --- happy path: start succeeds and tracks the real PIDs -------------------

case_start_succeeds_and_tracks_real_pids() {
  new_case_env
  trap cleanup_case_env RETURN
  export TAP_BIN="$REAL_YES"
  if ! ( source "$WRAPPER"; cmd_start >/dev/null 2>&1 ); then
    echo "cmd_start unexpectedly failed on the happy path" >&2
    return 1
  fi

  local result=0 tap_pid bridge_pid
  tap_pid="$(cat "$TAP_PID_FILE" 2>/dev/null || true)"
  bridge_pid="$(cat "$BRIDGE_PID_FILE" 2>/dev/null || true)"

  [[ -n "$tap_pid" ]] || { echo "TAP_PID_FILE is empty after a successful start" >&2; result=1; }
  [[ -n "$bridge_pid" ]] || { echo "BRIDGE_PID_FILE is empty after a successful start" >&2; result=1; }
  [[ -S "$IPC_SOCK" ]] || { echo "IPC socket missing after a successful start" >&2; result=1; }

  if [[ -n "$tap_pid" ]]; then
    ( source "$WRAPPER"; is_tap_process "$tap_pid" ) \
      || { echo "the recorded TAP_PID does not pass is_tap_process" >&2; result=1; }
  fi
  if [[ -n "$bridge_pid" ]]; then
    ( source "$WRAPPER"; is_bridge_process "$bridge_pid" ) \
      || { echo "the recorded BRIDGE_PID does not pass is_bridge_process" >&2; result=1; }
  fi

  # Exercise stop on a genuinely healthy pair while we're here.
  if ! ( source "$WRAPPER"; cmd_stop >/dev/null 2>&1 ); then
    echo "cmd_stop failed on a healthy tap+bridge pair" >&2
    result=1
  fi
  [[ -f "$TAP_PID_FILE" ]] && { echo "TAP_PID_FILE remained after stop" >&2; result=1; }
  [[ -f "$BRIDGE_PID_FILE" ]] && { echo "BRIDGE_PID_FILE remained after stop" >&2; result=1; }
  [[ -S "$IPC_SOCK" ]] && { echo "IPC socket remained after stop" >&2; result=1; }

  return $result
}

# --- PID-file / process-identity edge cases --------------------------------

case_stale_pid_file_is_handled_gracefully() {
  new_case_env
  trap cleanup_case_env RETURN
  echo 999999 >"$TAP_PID_FILE"  # not a live PID
  ( source "$WRAPPER"; TAP_BIN="$REAL_SLEEP"; stop_owned_process "$TAP_PID_FILE" tap tap )
}

case_reused_pid_identity_mismatch_blocks_and_sends_no_signal() {
  new_case_env
  trap cleanup_case_env RETURN
  "$REAL_SLEEP" 30 &
  local other=$!
  echo "$other" >"$TAP_PID_FILE"
  local stop_ok=0
  if ( source "$WRAPPER"
       TAP_BIN="$(readlink -f "$(command -v cat)")"  # deliberately mismatched
       stop_owned_process "$TAP_PID_FILE" tap tap >/dev/null 2>&1
  ); then
    stop_ok=1
  fi
  local rc=0
  if [[ "$stop_ok" == "1" ]]; then
    echo "stop_owned_process incorrectly accepted a mismatched PID" >&2
    rc=1
  fi
  if ! kill -0 "$other" 2>/dev/null; then
    echo "the unrelated process was killed despite the identity mismatch" >&2
    rc=1
  fi
  kill -9 "$other" 2>/dev/null || true
  wait "$other" 2>/dev/null || true
  return $rc
}

case_foreign_untracked_process_is_detected() {
  new_case_env
  trap cleanup_case_env RETURN
  "$REAL_SLEEP" 30 &
  local foreign=$!
  sleep 0.2
  local detected=0
  if ! ( source "$WRAPPER"
         TAP_BIN="$REAL_SLEEP"
         # no TAP_PID_FILE written: $foreign runs the tap binary but is not
         # the one we are tracking.
         assert_no_foreign_bridge_processes >/dev/null 2>&1
  ); then
    detected=1
  fi
  kill -9 "$foreign" 2>/dev/null || true
  wait "$foreign" 2>/dev/null || true
  if [[ "$detected" == "0" ]]; then
    echo "assert_no_foreign_bridge_processes missed an untracked tap process" >&2
    return 1
  fi
  return 0
}

case_stale_ipc_socket_is_removed_by_stop() {
  new_case_env
  trap cleanup_case_env RETURN
  python3 - "$IPC_SOCK" <<'PYEOF'
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind(sys.argv[1])
s.close()
PYEOF
  ( source "$WRAPPER"; TAP_BIN="$REAL_SLEEP"; cmd_stop )
  local rc=$?
  [[ -S "$IPC_SOCK" ]] && return 1
  return $rc
}

case_stop_only_kills_own_pids() {
  new_case_env
  trap cleanup_case_env RETURN
  "$REAL_SLEEP" 30 &
  local owned=$!
  echo "$owned" >"$TAP_PID_FILE"
  "$REAL_SLEEP" 30 &
  local bystander=$!
  ( source "$WRAPPER"; TAP_BIN="$REAL_SLEEP"; stop_owned_process "$TAP_PID_FILE" tap tap )
  local rc=$?
  if kill -0 "$owned" 2>/dev/null; then
    echo "owned tap process was not stopped" >&2
    rc=1
  fi
  if ! kill -0 "$bystander" 2>/dev/null; then
    echo "an unrelated bystander process was killed" >&2
    rc=1
  fi
  kill -9 "$bystander" 2>/dev/null || true
  wait "$owned" "$bystander" 2>/dev/null || true
  return $rc
}

run "plan starts no processes" case_plan_starts_no_processes
run "status starts no processes" case_status_starts_no_processes
run "start blocks on an active /cmd_vel publisher" case_start_blocks_on_cmd_vel_publisher
run "start blocks on an active /odom publisher" case_start_blocks_on_odom_publisher
run "start blocks when the ROS publisher query itself fails (fail-closed)" case_start_blocks_on_unknown_ros_query
run "start blocks when a Nav2-named process is running" case_start_blocks_on_nav2
run "start blocks when a SLAM-named process is running" case_start_blocks_on_slam
run "start blocks when a tap DDS library is unresolved" case_start_blocks_when_tap_libraries_missing
run "start blocks when tap DDS libraries resolve outside the SDK" case_start_blocks_when_tap_libraries_resolve_outside_sdk
run "start blocks when the isolated ldd check itself fails" case_start_blocks_when_ldd_itself_fails
run "the tap launch environment uses the SDK path and clears ROS vars" case_tap_env_isolation_uses_sdk_path_and_clears_ros_vars
run "a bridge that never creates the IPC socket is detected and not left running" case_bridge_failing_to_create_socket_is_detected
run "a bridge that crashes immediately is detected" case_bridge_crashing_immediately_is_detected
run "a tap that exits during startup is detected and the bridge is cleaned up" case_tap_exiting_during_startup_is_detected
run "start succeeds end-to-end and tracks the real tap/bridge PIDs" case_start_succeeds_and_tracks_real_pids
run "a stale (dead) PID file is handled gracefully" case_stale_pid_file_is_handled_gracefully
run "a reused PID with mismatched identity blocks and receives no signal" case_reused_pid_identity_mismatch_blocks_and_sends_no_signal
run "a foreign untracked tap-identity process is detected" case_foreign_untracked_process_is_detected
run "a stale IPC socket is removed by stop" case_stale_ipc_socket_is_removed_by_stop
run "stop only terminates its own tracked PID, not bystanders" case_stop_only_kills_own_pids

echo
echo "wrapper tests: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" == "0" ]]
