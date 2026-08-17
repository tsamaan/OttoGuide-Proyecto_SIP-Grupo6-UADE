#!/usr/bin/env bash
# Validate a CycloneDDS XML file on the robot without launching drivers.

set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /absolute/path/to/cyclonedds.xml" >&2
  exit 2
fi

XML="$1"

if [[ ! -f "${XML}" ]]; then
  echo "CycloneDDS XML not found: ${XML}" >&2
  exit 2
fi

export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://${XML}"

set +u
source /opt/ros/foxy/setup.bash
set -u

set +e
timeout 8 ros2 topic list
rc_topic=$?
set -e

ros2 daemon stop || true

exit "${rc_topic}"
