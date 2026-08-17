#!/usr/bin/env bash
# Builds ottoguide_g1_micro_motion.cpp against a companion computer's installed
# Unitree SDK. Validated on the OttoGuide G1 EDU 8 companion (Ubuntu 20.04, aarch64,
# g++ 9.4.0, SDK installed at /opt/unitree_robotics) during ROBOT-R5F-R2.
#
# Usage: ./build_g1_micro_motion.sh [output_path]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_PATH="${1:-$SCRIPT_DIR/ottoguide_g1_micro_motion}"
SDK_ROOT="${OTTOGUIDE_UNITREE_SDK_ROOT:-/opt/unitree_robotics}"

g++ -std=c++17 -O2 -pthread \
  -I"$SDK_ROOT/include" \
  -I"$SDK_ROOT/include/ddscxx" \
  -I"$SDK_ROOT/include/ddsc" \
  "$SCRIPT_DIR/ottoguide_g1_micro_motion.cpp" \
  -L"$SDK_ROOT/lib" -lunitree_sdk2 -lddsc -lddscxx \
  -o "$OUTPUT_PATH"

echo "Built: $OUTPUT_PATH"
