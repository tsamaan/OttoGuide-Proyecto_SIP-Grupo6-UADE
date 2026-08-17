#!/usr/bin/env bash
# assert_no_cmd_vel_publishers.sh — Fail-closed guard: /cmd_vel must be present
# in the ROS 2 graph AND its publisher count must be deterministically zero.
#
# Returns exit 0 ONLY when both conditions are proven.  Any absence, error,
# ambiguity, timeout, empty output, or parse failure produces exit 2.
#
# Machine-readable STATUS= line is always emitted to stdout:
#   exit 0  STATUS=SAFE_ZERO_PUBLISHERS   — /cmd_vel present, 0 publishers confirmed
#   exit 1  STATUS=PUBLISHERS_PRESENT     — /cmd_vel has >= 1 active publisher(s)
#   exit 2  STATUS=TOPIC_ABSENT           — /cmd_vel absent from ros2 topic list
#   exit 2  STATUS=ROS2_UNAVAILABLE       — ros2 CLI not found / setup.bash unreadable
#   exit 2  STATUS=TIMEOUT_UNAVAILABLE    — 'timeout' or 'mktemp' binary missing
#   exit 2  STATUS=COMMAND_TIMEOUT        — ros2 subcommand exceeded time limit
#   exit 2  STATUS=COMMAND_ERROR          — ros2 returned non-zero or wrote to stderr
#   exit 2  STATUS=PARSE_ERROR            — Publisher count line missing or ambiguous
#   exit 2  STATUS=INVALID_CONFIGURATION  — CMD_VEL_ASSERT_TIMEOUT_S not a positive integer
#
# Environment variables:
#   OTTOGUIDE_ROS_SETUP       Readable ROS 2 setup.bash (overrides auto-detection;
#                             intended for non-standard installs and test stubs).
#   CMD_VEL_ASSERT_TIMEOUT_S  Per-command timeout in whole seconds (positive integer;
#                             default 5).

set -euo pipefail
export LC_ALL=C

TOPIC="/cmd_vel"
TIMEOUT_S="${CMD_VEL_ASSERT_TIMEOUT_S:-5}"

# ---------------------------------------------------------------------------
# Validate configuration
# ---------------------------------------------------------------------------
if ! [[ "$TIMEOUT_S" =~ ^[1-9][0-9]*$ ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: CMD_VEL_ASSERT_TIMEOUT_S must be a positive integer; got '$TIMEOUT_S'." >&2
    echo "STATUS=INVALID_CONFIGURATION"
    exit 2
fi

# ---------------------------------------------------------------------------
# Verify required external tools
# ---------------------------------------------------------------------------
if ! command -v mktemp > /dev/null 2>&1; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'mktemp' not found in PATH." >&2
    echo "STATUS=TIMEOUT_UNAVAILABLE"
    exit 2
fi
if ! command -v timeout > /dev/null 2>&1; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'timeout' not found in PATH." >&2
    echo "STATUS=TIMEOUT_UNAVAILABLE"
    exit 2
fi

# ---------------------------------------------------------------------------
# Temporary directory — cleaned on any exit
# ---------------------------------------------------------------------------
_tmpdir="$(mktemp -d)"
trap 'rm -rf "$_tmpdir"' EXIT

# ---------------------------------------------------------------------------
# Initialize ROS 2 environment
# Priority: OTTOGUIDE_ROS_SETUP > pre-sourced env (ros2 already in PATH) >
#           auto-detection of known Foxy/Humble/Iron/Jazzy/Rolling prefixes.
# ---------------------------------------------------------------------------
if [[ -n "${OTTOGUIDE_ROS_SETUP:-}" ]]; then
    if [[ ! -r "$OTTOGUIDE_ROS_SETUP" ]]; then
        echo "[ASSERT_NO_CMD_VEL] ERROR: OTTOGUIDE_ROS_SETUP='$OTTOGUIDE_ROS_SETUP' is not a readable file." >&2
        echo "STATUS=ROS2_UNAVAILABLE"
        exit 2
    fi
    # shellcheck disable=SC1090
    source "$OTTOGUIDE_ROS_SETUP"
elif ! command -v ros2 > /dev/null 2>&1; then
    _ros_setup=""
    for _candidate in \
        "/opt/ros/foxy/setup.bash" \
        "/opt/ros/humble/setup.bash" \
        "/opt/ros/iron/setup.bash" \
        "/opt/ros/jazzy/setup.bash" \
        "/opt/ros/rolling/setup.bash"; do
        if [[ -f "$_candidate" ]]; then
            _ros_setup="$_candidate"
            break
        fi
    done
    if [[ -z "$_ros_setup" ]]; then
        echo "[ASSERT_NO_CMD_VEL] ERROR: ros2 not in PATH and no ROS 2 setup.bash found." >&2
        echo "[ASSERT_NO_CMD_VEL] Tip: set OTTOGUIDE_ROS_SETUP to a readable setup.bash." >&2
        echo "STATUS=ROS2_UNAVAILABLE"
        exit 2
    fi
    # shellcheck disable=SC1090
    source "$_ros_setup"
fi

if ! command -v ros2 > /dev/null 2>&1; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: ros2 not found after environment initialization." >&2
    echo "STATUS=ROS2_UNAVAILABLE"
    exit 2
fi

# ---------------------------------------------------------------------------
# Step 1 — ros2 topic list: verify /cmd_vel exists in the active graph.
# stdout and stderr are captured to separate files; 2>&1 is never used for
# building the buffer that will be parsed.
# ---------------------------------------------------------------------------
_list_out="$_tmpdir/topic_list.stdout"
_list_err="$_tmpdir/topic_list.stderr"
_list_rc=0
timeout "$TIMEOUT_S" ros2 topic list > "$_list_out" 2> "$_list_err" || _list_rc=$?

if [[ "$_list_rc" -eq 124 ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic list' timed out after ${TIMEOUT_S}s." >&2
    echo "STATUS=COMMAND_TIMEOUT"
    exit 2
fi
if [[ "$_list_rc" -ne 0 ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic list' failed with exit code $_list_rc." >&2
    cat "$_list_err" >&2
    echo "STATUS=COMMAND_ERROR"
    exit 2
fi
if [[ -s "$_list_err" ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic list' exited 0 but produced stderr output." >&2
    cat "$_list_err" >&2
    echo "STATUS=COMMAND_ERROR"
    exit 2
fi

# Count exact line matches for /cmd_vel — no grep/awk/sed/cut/head/tail
_topic_match_count=0
while IFS= read -r _line || [[ -n "$_line" ]]; do
    if [[ "$_line" == "/cmd_vel" ]]; then
        _topic_match_count=$(( _topic_match_count + 1 ))
    fi
done < "$_list_out"

if [[ "$_topic_match_count" -eq 0 ]]; then
    echo "[ASSERT_NO_CMD_VEL] INFO: /cmd_vel not present in active topic list." >&2
    echo "STATUS=TOPIC_ABSENT"
    exit 2
fi
if [[ "$_topic_match_count" -gt 1 ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: /cmd_vel appeared $_topic_match_count times in topic list (ambiguous)." >&2
    echo "STATUS=PARSE_ERROR"
    exit 2
fi

# ---------------------------------------------------------------------------
# Step 2 — ros2 topic info: query publisher count for /cmd_vel.
# ---------------------------------------------------------------------------
_info_out="$_tmpdir/topic_info.stdout"
_info_err="$_tmpdir/topic_info.stderr"
_info_rc=0
timeout "$TIMEOUT_S" ros2 topic info "$TOPIC" > "$_info_out" 2> "$_info_err" || _info_rc=$?

if [[ "$_info_rc" -eq 124 ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic info $TOPIC' timed out after ${TIMEOUT_S}s." >&2
    echo "STATUS=COMMAND_TIMEOUT"
    exit 2
fi
if [[ "$_info_rc" -ne 0 ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic info $TOPIC' failed with exit code $_info_rc." >&2
    cat "$_info_err" >&2
    echo "STATUS=COMMAND_ERROR"
    exit 2
fi
if [[ -s "$_info_err" ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic info $TOPIC' exited 0 but produced stderr output." >&2
    cat "$_info_err" >&2
    echo "STATUS=COMMAND_ERROR"
    exit 2
fi
if [[ ! -s "$_info_out" ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: 'ros2 topic info $TOPIC' produced empty stdout." >&2
    echo "STATUS=PARSE_ERROR"
    exit 2
fi

# ---------------------------------------------------------------------------
# Step 3 — Parse publisher count line-by-line without external text tools.
# Regex: optional leading spaces, "Publisher count:", optional spaces, digits.
# ---------------------------------------------------------------------------
_publisher_match_count=0
_publisher_count=""
while IFS= read -r _line || [[ -n "$_line" ]]; do
    if [[ "$_line" =~ ^[[:space:]]*Publisher[[:space:]]+count:[[:space:]]*([0-9]+)[[:space:]]*$ ]]; then
        _publisher_match_count=$(( _publisher_match_count + 1 ))
        _publisher_count="${BASH_REMATCH[1]}"
    fi
done < "$_info_out"

if [[ "$_publisher_match_count" -ne 1 ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: Expected exactly 1 'Publisher count:' line; found $_publisher_match_count." >&2
    cat "$_info_out" >&2
    echo "STATUS=PARSE_ERROR"
    exit 2
fi
if ! [[ "$_publisher_count" =~ ^[0-9]+$ ]]; then
    echo "[ASSERT_NO_CMD_VEL] ERROR: Parsed publisher count '$_publisher_count' is not numeric." >&2
    echo "STATUS=PARSE_ERROR"
    exit 2
fi

# ---------------------------------------------------------------------------
# Final decision
# ---------------------------------------------------------------------------
if [[ "$_publisher_count" -gt 0 ]]; then
    echo "[ASSERT_NO_CMD_VEL] FAIL: $_publisher_count active publisher(s) on $TOPIC." >&2
    cat "$_info_out" >&2
    echo "STATUS=PUBLISHERS_PRESENT"
    exit 1
fi

echo "[ASSERT_NO_CMD_VEL] OK: $TOPIC present, publisher_count=0."
echo "STATUS=SAFE_ZERO_PUBLISHERS"
exit 0
