#!/usr/bin/env bash
set -Eeuo pipefail

SDK_ROOT="${SDK_ROOT:-/home/unitree/unitree_sdk2}"
SDK_STATIC="$SDK_ROOT/lib/aarch64/libunitree_sdk2.a"
SRC="$(cd "$(dirname "$0")" && pwd)/unitree_capture_tap.cpp"
OUT="${OUT:-/tmp/ottoguide_unitree_capture_tap}"
LINK_LOG="${LINK_LOG:-/tmp/ottoguide_unitree_capture_tap_link.log}"

echo "SDK_ROOT=$SDK_ROOT"
echo "SDK_STATIC=$SDK_STATIC"
echo "SRC=$SRC"
echo "OUT=$OUT"

if [[ ! -f "$SDK_STATIC" ]]; then
  echo "STATIC_ARCHIVE_INVALID" >&2
  exit 30
fi
file "$SDK_STATIC"
ar t "$SDK_STATIC" | head -30

if grep -nE \
  'ChannelPublisher|CreateSendChannel|LocoClient|SportClient|LowCmd|ClientStub|SetVelocity|SetFsmId|rt/api/|cmd_vel|/odom' \
  "$SRC"; then
  echo "NATIVE_SAFETY_AUDIT_FAILED" >&2
  exit 31
fi
if grep -nE -- \
  '-include cstring|thirdparty/include/dds|#define[[:space:]]+(memcpy|memset|strlen|memmove)' \
  "$SRC"; then
  echo "NATIVE_INCLUDE_AUDIT_FAILED" >&2
  exit 32
fi

set +e
g++ -std=c++17 -O3 -DNDEBUG \
  -isystem "$SDK_ROOT/include" \
  -isystem "$SDK_ROOT/thirdparty/include" \
  -isystem "$SDK_ROOT/thirdparty/include/ddscxx" \
  "$SRC" \
  "$SDK_STATIC" \
  -L"$SDK_ROOT/thirdparty/lib/aarch64" \
  -lddscxx \
  -lddsc \
  -lpthread \
  -Wl,-rpath,"$SDK_ROOT/lib/aarch64" \
  -Wl,-rpath,"$SDK_ROOT/thirdparty/lib/aarch64" \
  -Wl,-t \
  -o "$OUT" \
  2>&1 | tee "$LINK_LOG"
compile_rc=${PIPESTATUS[0]}
set -e
echo "COMPILE_RC=$compile_rc"
if [[ "$compile_rc" -ne 0 ]]; then
  echo "STATIC_LINK_FAILED" >&2
  exit 33
fi

file "$OUT"
readelf -d "$OUT" | grep -E 'NEEDED|RPATH|RUNPATH' || true
ldd "$OUT"
if readelf -d "$OUT" | grep -q 'libunitree_sdk2\.so'; then
  echo "UNEXPECTED_DYNAMIC_UNITREE_DEPENDENCY" >&2
  exit 34
fi
if ldd "$OUT" | grep -q 'not found'; then
  echo "UNRESOLVED_DYNAMIC_DEPENDENCY" >&2
  exit 35
fi

echo "STATIC_BUILD_OK=$OUT"
