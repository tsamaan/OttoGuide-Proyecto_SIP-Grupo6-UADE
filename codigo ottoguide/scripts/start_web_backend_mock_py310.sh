#!/usr/bin/env bash
# WEB-R6: launcher no-robot para el backend FastAPI cuando se opera junto a la UI
# canonica (ottoguide_web_app/frontend, Vite :3001) en topologia notebook local.
# No se autoejecuta desde ningun otro script; el operador lo invoca explicitamente.
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
export API_PORT="${API_PORT}"

# WEB-R6: la UI canonica es ottoguide_web_app/frontend (Vite :3001). Estas dos variables
# son la fuente de verdad para que "/" y "/dashboard" redirijan a React (WEB_UI_PUBLIC_URL)
# y para que CORS/WS acepten el origen real del frontend (WEB_UI_ALLOWED_ORIGINS).
export WEB_UI_ALLOWED_ORIGINS="${WEB_UI_ALLOWED_ORIGINS:-http://localhost:3001,http://127.0.0.1:3001}"
export WEB_UI_PUBLIC_URL="${WEB_UI_PUBLIC_URL:-http://127.0.0.1:3001}"

cd "${BACKEND_DIR}"

echo "[start_web_backend_mock_py310] PYTHON_BIN=${PYTHON_BIN}"
echo "[start_web_backend_mock_py310] BACKEND_DIR=${BACKEND_DIR}"
echo "[start_web_backend_mock_py310] ROBOT_MODE=${ROBOT_MODE}"
echo "[start_web_backend_mock_py310] API_PORT=${API_PORT}"
echo "[start_web_backend_mock_py310] WEB_UI_ALLOWED_ORIGINS=${WEB_UI_ALLOWED_ORIGINS}"
echo "[start_web_backend_mock_py310] WEB_UI_PUBLIC_URL=${WEB_UI_PUBLIC_URL}"
echo "[start_web_backend_mock_py310] ROS/DDS/Unitree environment variables were unset."
echo "[start_web_backend_mock_py310] Canonical UI: ottoguide_web_app/frontend (npm run dev, port 3001)."

exec "${PYTHON_BIN}" main.py
