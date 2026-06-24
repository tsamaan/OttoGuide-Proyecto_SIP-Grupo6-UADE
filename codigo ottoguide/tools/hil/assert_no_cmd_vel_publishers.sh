#!/usr/bin/env bash
# assert_no_cmd_vel_publishers.sh — Verify no node is publishing to /cmd_vel.
#
# OVERLAP_TRIVIAL_REVIEW_BRANCH: EOL-only overlap with review branch.
# This guard is read-only and produces no robot motion under any conditions.
#
# Exit 0  : no active publishers on /cmd_vel (safe for offline read-only operation)
# Exit 1  : one or more publishers detected (ABORT — cmd_vel is live)
# Exit 2  : ROS 2 environment not available or topic query failed

set -euo pipefail

TOPIC="/cmd_vel"
TIMEOUT_S="${CMD_VEL_ASSERT_TIMEOUT_S:-5}"

# --- Locate ROS 2 setup ----------------------------------------------------
ROS_SETUP=""
for candidate in \
    "/opt/ros/jazzy/setup.bash" \
    "/opt/ros/humble/setup.bash" \
    "/opt/ros/iron/setup.bash" \
    "/opt/ros/rolling/setup.bash"; do
    if [[ -f "$candidate" ]]; then
        ROS_SETUP="$candidate"
        break
    fi
done

if [[ -z "$ROS_SETUP" ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: ROS 2 not found in known prefixes." >&2
    exit 2
fi

# shellcheck disable=SC1090
source "$ROS_SETUP"

if ! command -v ros2 &>/dev/null; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: ros2 CLI not found after sourcing $ROS_SETUP." >&2
    exit 2
fi

# --- Query topic publisher count -------------------------------------------
TOPIC_INFO=""
if ! TOPIC_INFO="$(timeout "$TIMEOUT_S" ros2 topic info "$TOPIC" 2>&1)"; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic info $TOPIC' timed out or failed." >&2
    exit 2
fi

PUBLISHER_COUNT="$(echo "$TOPIC_INFO" | grep -i "Publisher count:" | awk '{print $NF}')" || true
PUBLISHER_COUNT="${PUBLISHER_COUNT:-0}"

if ! [[ "$PUBLISHER_COUNT" =~ ^[0-9]+$ ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: Could not parse publisher count from topic info." >&2
    echo "$TOPIC_INFO" >&2
    exit 2
fi

if [[ "$PUBLISHER_COUNT" -gt 0 ]]; then
    echo "[ASSERT_NO_CMD_VEL] FAIL: $PUBLISHER_COUNT active publisher(s) on $TOPIC." >&2
    echo "$TOPIC_INFO" >&2
    exit 1
fi

echo "[ASSERT_NO_CMD_VEL] OK: No publishers on $TOPIC (publisher_count=$PUBLISHER_COUNT)."
exit 0
