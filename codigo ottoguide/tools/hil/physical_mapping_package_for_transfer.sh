#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID="${2:?missing run id}"; shift 2 ;;
    -h|--help) echo "Usage: physical_mapping_package_for_transfer.sh [--run-id RUN_ID]"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACTS="$BASE/artifacts"
if [[ -z "$RUN_ID" ]]; then
  RUN_ID="$(cat "$ARTIFACTS/physical_mapping_latest_run_id")"
fi

SESSION="$ARTIFACTS/physical_mapping_route_$RUN_ID"
TAR="/tmp/physical_mapping_route_$RUN_ID.tar.gz"
if [[ ! -d "$SESSION" ]]; then
  echo "FAIL: session does not exist: $SESSION" >&2
  exit 1
fi

tar -C "$ARTIFACTS" -czf "$TAR" "physical_mapping_route_$RUN_ID"
sha256sum "$TAR" > "$TAR.sha256"
ls -lh "$TAR" "$TAR.sha256"

cat <<EOF
Copy from Windows PowerShell:
scp -i "\$env:USERPROFILE\.ssh\id_ed25519_ottoguide_robot" unitree@192.168.123.164:$TAR "C:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\artifacts"
scp -i "\$env:USERPROFILE\.ssh\id_ed25519_ottoguide_robot" unitree@192.168.123.164:$TAR.sha256 "C:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\artifacts"
EOF

echo "PHYSICAL MAPPING PACKAGE PASS"
