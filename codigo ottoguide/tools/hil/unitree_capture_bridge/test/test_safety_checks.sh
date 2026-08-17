#!/usr/bin/env bash
# Offline unit tests for process-identity (Phase G) and ROS safety-query
# fail-closed semantics (Phase H). Spawns only dummy processes it owns
# (sleep, bash) and verifies their identity via /proc - never signals a
# real system process, never talks to a real ROS graph.
set -Eeuo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$TEST_DIR/../scripts/unitree-capture-bridge"
FIXTURES="$TEST_DIR/fixtures"

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
  if "$@" >/tmp/ottoguide_test_safety_case.$$ 2>&1; then
    check "$name" 0
  else
    check "$name" 1
    sed 's/^/    /' "/tmp/ottoguide_test_safety_case.$$"
  fi
  rm -f "/tmp/ottoguide_test_safety_case.$$"
}

REAL_SLEEP="$(readlink -f "$(command -v sleep)")"

# --- Phase G: process identity --------------------------------------------

case_tap_identity_matches_real_binary() {
  (
    source "$WRAPPER"
    TAP_BIN="$REAL_SLEEP"
    "$REAL_SLEEP" 30 &
    local pid=$!
    trap 'kill -9 "$pid" 2>/dev/null || true' RETURN
    sleep 0.2
    is_tap_process "$pid"
  )
}

case_tap_identity_rejects_mismatched_binary() {
  (
    source "$WRAPPER"
    TAP_BIN="$(readlink -f "$(command -v cat)")"
    "$REAL_SLEEP" 30 &
    local pid=$!
    trap 'kill -9 "$pid" 2>/dev/null || true' RETURN
    sleep 0.2
    if is_tap_process "$pid"; then
      return 1
    fi
    return 0
  )
}

case_bridge_identity_matches_configured_executable() {
  (
    source "$WRAPPER"
    BRIDGE_EXECUTABLE="/fake/lib/ottoguide_unitree_capture_bridge/bridge_node"
    bash -c "exec -a \"$BRIDGE_EXECUTABLE\" sleep 30" &
    local pid=$!
    trap 'kill -9 "$pid" 2>/dev/null || true' RETURN
    sleep 0.2
    is_bridge_process "$pid"
  )
}

case_bridge_identity_rejects_unrelated_argv0() {
  (
    source "$WRAPPER"
    BRIDGE_EXECUTABLE="/fake/lib/ottoguide_unitree_capture_bridge/bridge_node"
    bash -c 'exec -a "/usr/bin/some_other_tool" sleep 30' &
    local pid=$!
    trap 'kill -9 "$pid" 2>/dev/null || true' RETURN
    sleep 0.2
    if is_bridge_process "$pid"; then
      return 1
    fi
    return 0
  )
}

case_bridge_identity_requires_exact_path_not_suffix() {
  # is_bridge_process compares against the exact configured
  # BRIDGE_EXECUTABLE, not a generic path suffix - a process whose argv0
  # merely *ends with* the same components but lives under a different
  # prefix must not match.
  (
    source "$WRAPPER"
    BRIDGE_EXECUTABLE="/fake/lib/ottoguide_unitree_capture_bridge/bridge_node"
    bash -c 'exec -a "/some/other/prefix/fake/lib/ottoguide_unitree_capture_bridge/bridge_node" sleep 30' &
    local pid=$!
    trap 'kill -9 "$pid" 2>/dev/null || true' RETURN
    sleep 0.2
    if is_bridge_process "$pid"; then
      echo "matched on suffix instead of requiring an exact path" >&2
      return 1
    fi
    return 0
  )
}

case_wrapper_never_self_matches() {
  (
    source "$WRAPPER"
    TAP_BIN="$REAL_SLEEP"
    if is_tap_process "$$"; then
      echo "current shell falsely matched as tap" >&2
      return 1
    fi
    if is_bridge_process "$$"; then
      echo "current shell falsely matched as bridge" >&2
      return 1
    fi
    return 0
  )
}

case_text_argument_mentioning_names_does_not_self_match() {
  # A process that merely *mentions* the tap/bridge name as a text argument
  # (the old pgrep -f substring bug) must never be classified as foreign.
  (
    source "$WRAPPER"
    TAP_BIN="$REAL_SLEEP"
    bash -c 'exec -a "cat" cat /dev/null' &
    local pid=$!
    sleep 0.2
    bash -c "exec -a \"grep\" grep -q ottoguide_unitree_capture_tap /dev/null" >/dev/null 2>&1 &
    local pid2=$!
    sleep 0.2
    local result=0
    if is_tap_process "$pid" 2>/dev/null; then result=1; fi
    if is_bridge_process "$pid" 2>/dev/null; then result=1; fi
    kill -9 "$pid" "$pid2" 2>/dev/null || true
    wait "$pid" "$pid2" 2>/dev/null || true
    return "$result"
  )
}

# --- Phase H: fail-closed ROS safety queries ------------------------------

run_publisher_status() {
  local mode="$1" topic="${2:-/cmd_vel}"
  (
    source "$WRAPPER"
    export PATH="$FIXTURES/bin:$PATH"
    export ROS_QUERY_TIMEOUT=2
    export FAKE_ROS2_PUB_CMD_VEL="$mode"
    publisher_status "$topic"
  )
}

case_publisher_status_unknown_topic_is_safe_zero() {
  # Regression case: real ROS 2 Foxy reports a nonexistent topic as
  # "Unknown topic '<topic>'" on EXIT CODE 1, not 0. This is exactly the
  # condition that produced UNKNOWN_ROS_QUERY_FAILED during the physical
  # session of 2026-06-20 and blocked the bridge from starting.
  [[ "$(run_publisher_status unknown)" == "SAFE_ZERO_PUBLISHERS" ]]
}

case_publisher_status_unknown_topic_rc0_is_also_safe_zero() {
  # Compatibility: some ros2 CLI builds/distros report the same exact
  # message on exit code 0 instead of 1. Both must be treated as safe.
  [[ "$(run_publisher_status unknown-rc0)" == "SAFE_ZERO_PUBLISHERS" ]]
}

case_publisher_status_unknown_like_text_is_unsafe() {
  # Text that merely mentions "Unknown topic" but is not the exact
  # expected line must never be treated as safe - only an exact match is
  # trusted, to avoid silently absorbing some other, unrelated error.
  [[ "$(run_publisher_status unknown-like)" == "UNKNOWN_ROS_QUERY_FAILED" ]]
}

case_publisher_status_unknown_exact_message_wrong_rc_is_unsafe() {
  # The exact "Unknown topic" line is only trusted on rc 0 or 1. Any other
  # exit code with that same text must still block.
  [[ "$(run_publisher_status unknown-wrong-rc)" == "UNKNOWN_ROS_QUERY_FAILED" ]]
}

case_publisher_status_works_for_odom_topic_too() {
  (
    source "$WRAPPER"
    export PATH="$FIXTURES/bin:$PATH"
    export ROS_QUERY_TIMEOUT=2
    export FAKE_ROS2_PUB_ODOM=unknown
    [[ "$(publisher_status /odom)" == "SAFE_ZERO_PUBLISHERS" ]] || exit 1
    export FAKE_ROS2_PUB_ODOM=one
    [[ "$(publisher_status /odom)" == "UNSAFE_ACTIVE_PUBLISHERS:1" ]] || exit 1
  )
}

case_publisher_status_zero_publishers_is_safe() {
  [[ "$(run_publisher_status zero)" == "SAFE_ZERO_PUBLISHERS" ]]
}

case_publisher_status_one_publisher_is_unsafe() {
  [[ "$(run_publisher_status one)" == "UNSAFE_ACTIVE_PUBLISHERS:1" ]]
}

case_publisher_status_many_publishers_is_unsafe() {
  [[ "$(run_publisher_status many)" == "UNSAFE_ACTIVE_PUBLISHERS:3" ]]
}

case_publisher_status_ros2_nonzero_exit_is_unknown() {
  [[ "$(run_publisher_status fail)" == "UNKNOWN_ROS_QUERY_FAILED" ]]
}

case_publisher_status_empty_output_is_unknown() {
  [[ "$(run_publisher_status empty)" == "UNKNOWN_TOPIC_INFO_UNPARSEABLE" ]]
}

case_publisher_status_garbage_output_is_unknown() {
  [[ "$(run_publisher_status garbage)" == "UNKNOWN_TOPIC_INFO_UNPARSEABLE" ]]
}

case_publisher_status_timeout_is_unknown() {
  [[ "$(run_publisher_status timeout)" == "UNKNOWN_ROS_QUERY_FAILED" ]]
}

case_assert_no_publishers_blocks_on_unknown() {
  # fail() exits the subshell outright (see scripts/unitree-capture-bridge),
  # so the expected-to-block path never returns control to an inner
  # if/then/else - the outer `if` here tests the subshell's own exit status.
  if (
    source "$WRAPPER"
    export PATH="$FIXTURES/bin:$PATH"
    export ROS_QUERY_TIMEOUT=2
    export FAKE_ROS2_PUB_CMD_VEL=fail
    assert_no_publishers /cmd_vel
  ) 2>/dev/null; then
    echo "assert_no_publishers incorrectly passed on UNKNOWN" >&2
    return 1
  fi
  return 0
}

case_assert_no_publishers_allows_safe_zero() {
  (
    source "$WRAPPER"
    export PATH="$FIXTURES/bin:$PATH"
    export ROS_QUERY_TIMEOUT=2
    export FAKE_ROS2_PUB_CMD_VEL=zero
    assert_no_publishers /cmd_vel
  )
}

case_assert_no_publishers_allows_real_foxy_unknown_topic() {
  # The exact scenario observed on the robot: rc=1, "Unknown topic
  # '/cmd_vel'". This must NOT block start/validate.
  (
    source "$WRAPPER"
    export PATH="$FIXTURES/bin:$PATH"
    export ROS_QUERY_TIMEOUT=2
    export FAKE_ROS2_PUB_CMD_VEL=unknown
    assert_no_publishers /cmd_vel
  )
}

case_assert_no_publishers_blocks_on_active() {
  if (
    source "$WRAPPER"
    export PATH="$FIXTURES/bin:$PATH"
    export ROS_QUERY_TIMEOUT=2
    export FAKE_ROS2_PUB_CMD_VEL=one
    assert_no_publishers /cmd_vel
  ) 2>/dev/null; then
    echo "assert_no_publishers incorrectly passed with an active publisher" >&2
    return 1
  fi
  return 0
}

run "is_tap_process matches the real configured binary" case_tap_identity_matches_real_binary
run "is_tap_process rejects a process running a different binary" case_tap_identity_rejects_mismatched_binary
run "is_bridge_process matches the exact configured executable" case_bridge_identity_matches_configured_executable
run "is_bridge_process rejects unrelated argv0" case_bridge_identity_rejects_unrelated_argv0
run "is_bridge_process requires an exact path match, not a suffix" case_bridge_identity_requires_exact_path_not_suffix
run "the wrapper's own process never self-matches tap or bridge" case_wrapper_never_self_matches
run "a process merely mentioning the names as a text argument does not match" case_text_argument_mentioning_names_does_not_self_match
run "publisher_status: real Foxy 'Unknown topic' on rc=1 is SAFE_ZERO (regression)" case_publisher_status_unknown_topic_is_safe_zero
run "publisher_status: 'Unknown topic' on rc=0 is also SAFE_ZERO (compat)" case_publisher_status_unknown_topic_rc0_is_also_safe_zero
run "publisher_status: text merely resembling 'Unknown topic' is UNKNOWN" case_publisher_status_unknown_like_text_is_unsafe
run "publisher_status: exact 'Unknown topic' message on an unexpected rc is UNKNOWN" case_publisher_status_unknown_exact_message_wrong_rc_is_unsafe
run "publisher_status: works generically for /odom too" case_publisher_status_works_for_odom_topic_too
run "publisher_status: zero publishers is SAFE_ZERO" case_publisher_status_zero_publishers_is_safe
run "publisher_status: one publisher is UNSAFE" case_publisher_status_one_publisher_is_unsafe
run "publisher_status: many publishers is UNSAFE" case_publisher_status_many_publishers_is_unsafe
run "publisher_status: ros2 non-zero exit is UNKNOWN" case_publisher_status_ros2_nonzero_exit_is_unknown
run "publisher_status: empty output is UNKNOWN" case_publisher_status_empty_output_is_unknown
run "publisher_status: unparseable garbage output is UNKNOWN" case_publisher_status_garbage_output_is_unknown
run "publisher_status: ros2 timeout is UNKNOWN" case_publisher_status_timeout_is_unknown
run "assert_no_publishers blocks (fail-closed) on UNKNOWN" case_assert_no_publishers_blocks_on_unknown
run "assert_no_publishers allows SAFE_ZERO_PUBLISHERS" case_assert_no_publishers_allows_safe_zero
run "assert_no_publishers allows the real Foxy unknown-topic case (regression)" case_assert_no_publishers_allows_real_foxy_unknown_topic
run "assert_no_publishers blocks on active publishers" case_assert_no_publishers_blocks_on_active

echo
echo "safety-check tests: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" == "0" ]]
