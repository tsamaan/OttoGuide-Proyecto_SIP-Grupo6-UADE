#!/usr/bin/env bash
# @TASK: Arrancar backend OttoGuide en modo demostracion local offline/mock.
# @INPUT: Entorno local de desarrollo con .venv y Ollama/audio del host.
# @OUTPUT: FastAPI activo en 127.0.0.1:8000 con ROBOT_MODE=mock y NAV_BRIDGE_ACTIVE=false.
# @CONTEXT: Demo local del pipeline STT/LLM/TTS sin conexion DDS ni robot fisico.
# @SECURITY: No ejecuta preflight HIL ni verify_remote_env; trap cierra proceso de backend.
# STEP 1: Resolver rutas y validar .venv.
# STEP 2: Exportar ROBOT_MODE=mock y NAV_BRIDGE_ACTIVE=false.
# STEP 3: Levantar uvicorn en 127.0.0.1:8000.
# STEP 4: Capturar SIGINT/SIGTERM y finalizar backend limpio.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_ACTIVATE="${PROJECT_ROOT}/.venv/bin/activate"
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"
API_HOST="127.0.0.1"
API_PORT="8000"

if [[ ! -f "${VENV_ACTIVATE}" ]] || [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[ERROR] Entorno virtual no disponible en ${PROJECT_ROOT}/.venv" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${VENV_ACTIVATE}"

export ROBOT_MODE="mock"
export NAV_BRIDGE_ACTIVE="false"
export API_HOST="${API_HOST}"
export API_PORT="${API_PORT}"

API_PID=""

cleanup() {
  local exit_code="${1:-0}"
  trap - INT TERM EXIT

  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" >/dev/null 2>&1; then
    kill -TERM "${API_PID}" >/dev/null 2>&1 || true
    wait "${API_PID}" >/dev/null 2>&1 || true
  fi

  exit "${exit_code}"
}

on_signal() {
  cleanup 130
}

trap on_signal INT TERM
trap 'cleanup $?' EXIT

"${VENV_PYTHON}" -m uvicorn main:create_app --factory --host "${API_HOST}" --port "${API_PORT}" &
API_PID="$!"

echo "[INFO] Demo local activo en http://${API_HOST}:${API_PORT}"
wait "${API_PID}"
EXIT_CODE="$?"
cleanup "${EXIT_CODE}"
