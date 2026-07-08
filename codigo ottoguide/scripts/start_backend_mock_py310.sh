#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
BACKEND_DIR="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

PYTHON_BIN="${PYTHON_BIN:-/home/unitree/.local/ottoguide-miniforge/envs/ottoguide-py310/bin/python}"
API_PORT="${API_PORT:-8000}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: PYTHON_BIN not executable: ${PYTHON_BIN}" >&2
  exit 2
fi

unset RMW_IMPLEMENTATION
unset CYCLONEDDS_URI
unset ROBOT_NETWORK_INTERFACE

export ROBOT_MODE=mock
export NAVIGATION_BACKEND=stub
export NAVIGATION_ALLOW_STUB_TOURS=false
export QR_STATION_TRIGGER_ENABLED=false
export WEB_UI_ALLOWED_ORIGINS="${WEB_UI_ALLOWED_ORIGINS:-http://localhost:3001,http://127.0.0.1:3001,http://192.168.123.101:3001}"
export WEB_UI_ALLOW_MISSING_ORIGIN="${WEB_UI_ALLOW_MISSING_ORIGIN:-true}"
export API_PORT="${API_PORT}"

cd "${BACKEND_DIR}"

echo "[start_backend_mock_py310] PYTHON_BIN=${PYTHON_BIN}"
echo "[start_backend_mock_py310] BACKEND_DIR=${BACKEND_DIR}"
echo "[start_backend_mock_py310] ROBOT_MODE=${ROBOT_MODE}"
echo "[start_backend_mock_py310] NAVIGATION_BACKEND=${NAVIGATION_BACKEND}"
echo "[start_backend_mock_py310] API_PORT=${API_PORT}"
echo "[start_backend_mock_py310] ROS/DDS/Unitree environment variables were unset."

exec "${PYTHON_BIN}" main.py
