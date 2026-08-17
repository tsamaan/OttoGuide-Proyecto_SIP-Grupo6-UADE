#!/usr/bin/env bash
# Trivial no-op stand-in for /opt/ros/foxy/setup.bash, used by test cases
# that need source_ros to succeed without exercising its hardening logic.
: "${COLCON_TRACE:=}"
export FAKE_ROS_FOXY_SOURCED=1
