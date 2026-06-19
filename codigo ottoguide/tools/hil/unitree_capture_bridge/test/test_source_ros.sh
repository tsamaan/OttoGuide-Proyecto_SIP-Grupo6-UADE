#!/usr/bin/env bash
# Offline tests for the wrapper's source_ros() hardening (nounset
# save/restore, COLCON_TRACE handling, no error swallowing). Never sources a
# real /opt/ros/foxy/setup.bash and never touches a real ROS install.
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

# Each case runs in an isolated subshell: the wrapper's own `set -Eeuo
# pipefail` takes effect on the sourcing shell, so a case that is *expected*
# to abort (errexit firing) must not take the whole test runner down with it.

case_ok_setup_with_nounset_initially_on() {
  (
    source "$WRAPPER"
    ROS_FOXY_SETUP="$FIXTURES/ros_setup_ok.bash"
    source_ros
    case "$-" in
      *u*) exit 0 ;;
      *) echo "nounset not re-enabled" >&2; exit 1 ;;
    esac
  )
}

case_ok_setup_with_nounset_initially_off() {
  (
    source "$WRAPPER"
    set +u
    ROS_FOXY_SETUP="$FIXTURES/ros_setup_ok.bash"
    source_ros
    case "$-" in
      *u*) echo "nounset incorrectly re-enabled" >&2; exit 1 ;;
      *) exit 0 ;;
    esac
  )
}

case_colcon_trace_never_unbound() {
  (
    source "$WRAPPER"
    unset COLCON_TRACE || true
    ROS_FOXY_SETUP="$FIXTURES/ros_setup_ok.bash"
    source_ros
  ) 2>/tmp/ottoguide_test_source_ros_stderr.$$
  local rc=$?
  if grep -qi "unbound variable" "/tmp/ottoguide_test_source_ros_stderr.$$"; then
    rc=1
  fi
  rm -f "/tmp/ottoguide_test_source_ros_stderr.$$"
  return $rc
}

case_failure_is_not_swallowed() {
  (
    source "$WRAPPER"
    ROS_FOXY_SETUP="$FIXTURES/ros_setup_fail.bash"
    source_ros
    echo "should never print: source_ros did not abort" >&2
    exit 0
  ) >/tmp/ottoguide_test_source_ros_stdout.$$ 2>&1
  local rc=$?
  local swallowed=0
  grep -q "should never print" "/tmp/ottoguide_test_source_ros_stdout.$$" && swallowed=1
  rm -f "/tmp/ottoguide_test_source_ros_stdout.$$"
  # Expect non-zero exit (errexit fired) AND the line after source_ros must
  # never have run.
  if [[ "$rc" != "0" && "$swallowed" == "0" ]]; then
    return 0
  fi
  return 1
}

case_rmw_and_domain_defaults_applied() {
  (
    source "$WRAPPER"
    unset RMW_IMPLEMENTATION ROS_DOMAIN_ID || true
    ROS_FOXY_SETUP="$FIXTURES/ros_setup_noop.bash"
    source_ros
    [[ "$RMW_IMPLEMENTATION" == "rmw_cyclonedds_cpp" ]] || exit 1
    [[ "$ROS_DOMAIN_ID" == "0" ]] || exit 1
  )
}

run() {
  local name="$1"
  shift
  if "$@" >/tmp/ottoguide_test_source_ros_case.$$ 2>&1; then
    check "$name" 0
  else
    check "$name" 1
    sed 's/^/    /' "/tmp/ottoguide_test_source_ros_case.$$"
  fi
  rm -f "/tmp/ottoguide_test_source_ros_case.$$"
}

run "nounset initially ON is restored to ON after source_ros" case_ok_setup_with_nounset_initially_on
run "nounset initially OFF is restored to OFF after source_ros" case_ok_setup_with_nounset_initially_off
run "COLCON_TRACE never raises unbound variable" case_colcon_trace_never_unbound
run "a genuinely failing setup.bash is not swallowed" case_failure_is_not_swallowed
run "RMW_IMPLEMENTATION and ROS_DOMAIN_ID defaults applied" case_rmw_and_domain_defaults_applied

echo
echo "source_ros tests: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" == "0" ]]
