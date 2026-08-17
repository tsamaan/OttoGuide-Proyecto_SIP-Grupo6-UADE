#!/usr/bin/env bash
# Fake /opt/ros/foxy/setup.bash. Mirrors the real colcon-generated pattern of
# referencing COLCON_TRACE without a default, which raises "unbound
# variable" if nounset is active and the caller never initialized it.
if [ -n "$COLCON_TRACE" ]; then
  echo "[fake-foxy-setup] trace enabled" >&2
fi
export FAKE_ROS_FOXY_SOURCED=1
