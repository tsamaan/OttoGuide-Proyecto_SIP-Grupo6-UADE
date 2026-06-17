#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACTS="$BASE/artifacts"
LATEST="$ARTIFACTS/physical_mapping_latest_run_id"

set +u
source /opt/ros/foxy/setup.bash
set -u

if [[ ! -f "$LATEST" ]]; then
  echo "FAIL: no latest mapping run id" >&2
  exit 1
fi

RUN_ID="$(cat "$LATEST")"
SESSION="$ARTIFACTS/physical_mapping_route_$RUN_ID"
BAG_DIR="$(cat "$SESSION/state/bag_dir.txt" 2>/dev/null || true)"
MAP_BASE="$SESSION/maps/raw/ottoguide_route_real_$RUN_ID"
LOG="$SESSION/logs/physical_mapping_finalize.log"
exec > >(tee -a "$LOG") 2>&1

echo "RUN_ID=$RUN_ID"
echo "SESSION=$SESSION"
echo "BAG_DIR=$BAG_DIR"

if [[ -n "$BAG_DIR" && -d "$BAG_DIR" && ! -f "$SESSION/logs/rosbag_info.log" ]]; then
  ros2 bag info "$BAG_DIR" > "$SESSION/logs/rosbag_info.log" 2>&1 || true
fi

if ros2 topic list | grep -Fxq /map; then
  echo "Exporting raw map to $MAP_BASE"
  ros2 run nav2_map_server map_saver_cli -f "$MAP_BASE" > "$SESSION/logs/map_saver.log" 2>&1 || true
else
  echo "PARTIAL: /map is not active; skipping map_saver"
  printf 'map_saver skipped because /map was not active at finalize time\n' > "$SESSION/logs/map_saver.log"
fi

if [[ -f "$MAP_BASE.pgm" && -f "$MAP_BASE.yaml" ]]; then
  echo "PASS: raw map exported"
  if [[ -f "$BASE/tools/hil/analyze_map_yaml.py" ]]; then
    python3 "$BASE/tools/hil/analyze_map_yaml.py" "$MAP_BASE.yaml" > "$SESSION/reports/map_qa_raw.md" 2>&1 || true
  fi
else
  echo "PARTIAL: raw map files not present"
fi

cat > "$SESSION/README.md" <<EOF
# Physical Mapping Route $RUN_ID

- Route label: $(cat "$SESSION/state/route_label.txt" 2>/dev/null || true)
- Session: $SESSION
- Bag dir: $BAG_DIR
- Raw map base: $MAP_BASE
- Safety: agent did not publish /cmd_vel and did not run autonomous navigation.
- Raw artifacts are preserved. Any cleaned/cropped map must be derived under maps/cleaned/.
EOF

find "$SESSION" -type f -printf '%s %p\n' | sort -nr > "$SESSION/manifests/FILES_SIZES.txt"
(cd "$SESSION" && find . -type f ! -path './manifests/SHA256SUMS.txt' -print0 | sort -z | xargs -0 sha256sum) > "$SESSION/manifests/SHA256SUMS.txt" || true

echo "Next: $SCRIPT_DIR/physical_mapping_package_for_transfer.sh --run-id $RUN_ID"
echo "PHYSICAL MAPPING FINALIZE PASS"
