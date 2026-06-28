#!/usr/bin/env bash
# @TASK: Provision a reproducible Linux venv for the WSL SITL FastAPI panel.
# @INPUT: SITL_VENV_DIR, SITL_CYCLONEDDS_HOME, UNITREE_SDK_DIR.
# @OUTPUT: Venv outside the repository with requirements_sitl.txt installed.
# @CONTEXT: WSL2 x86_64 only. Not the physical robot bootstrap.
# @SECURITY: No sudo, no apt, no venv activation, no tmux, no uvicorn, no ROS,
#            no DDS runtime, no MuJoCo, and no Isaac startup.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements_sitl.txt"
SITL_VENV_DIR="${SITL_VENV_DIR:-${HOME}/.venvs/ottoguide-sitl}"
SITL_VENV_PYTHON="${SITL_VENV_DIR}/bin/python"
MIN_PYTHON_MINOR=10
SITL_CYCLONEDDS_HOME="${SITL_CYCLONEDDS_HOME:-${HOME}/.local/opt/cyclonedds-0.10.x}"

echo "[BOOTSTRAP] Provisioning WSL SITL runtime."
echo "[BOOTSTRAP] This is not the physical robot bootstrap."
echo "[BOOTSTRAP] PROJECT_ROOT=${PROJECT_ROOT}"
echo "[BOOTSTRAP] SITL_VENV_DIR=${SITL_VENV_DIR}"

ARCH="$(uname -m)"
IS_WSL=0
if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
  IS_WSL=1
elif grep -qi microsoft /proc/version 2>/dev/null; then
  IS_WSL=1
fi

if [[ "${IS_WSL}" -ne 1 ]]; then
  echo "[ERROR] NO_GO_WRONG_PLATFORM: WSL was not detected." >&2
  echo "[ERROR] This script must not run on the physical robot." >&2
  exit 1
fi

case "${ARCH}" in
  x86_64) : ;;
  aarch64|arm64)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: architecture '${ARCH}' is explicitly rejected." >&2
    echo "[ERROR] requirements_sitl.txt is for x86_64 WSL, not Jetson/AArch64." >&2
    exit 1
    ;;
  *)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: architecture '${ARCH}' is not authorized." >&2
    exit 1
    ;;
esac

if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
  echo "[ERROR] NO-GO bootstrap: SITL manifest missing at ${REQUIREMENTS_FILE}." >&2
  exit 1
fi

PROJECT_VENV_DIR="${PROJECT_ROOT}/.venv"
case "${SITL_VENV_DIR}" in
  "${PROJECT_VENV_DIR}"|"${PROJECT_VENV_DIR}"/*)
    echo "[ERROR] NO-GO bootstrap: SITL_VENV_DIR points inside the repository .venv." >&2
    exit 1
    ;;
esac
if [[ -e "${SITL_VENV_DIR}/Scripts/python.exe" ]]; then
  echo "[ERROR] NO-GO bootstrap: ${SITL_VENV_DIR} contains a Windows venv layout." >&2
  exit 1
fi
if [[ -e "${SITL_VENV_DIR}/pyvenv.cfg" ]] && [[ -e "${SITL_VENV_DIR}/Scripts" ]] && [[ ! -e "${SITL_VENV_DIR}/bin" ]]; then
  echo "[ERROR] NO-GO bootstrap: ${SITL_VENV_DIR} looks like a Windows venv." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] NO-GO bootstrap: python3 not found in PATH." >&2
  exit 1
fi

PY3_VERSION="$(python3 -B -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
PY3_MAJOR="$(python3 -B -c 'import sys; print(sys.version_info[0])')"
PY3_MINOR="$(python3 -B -c 'import sys; print(sys.version_info[1])')"
echo "[BOOTSTRAP] python3=${PY3_VERSION}"

if [[ "${PY3_MAJOR}" -lt 3 ]] || { [[ "${PY3_MAJOR}" -eq 3 ]] && [[ "${PY3_MINOR}" -lt "${MIN_PYTHON_MINOR}" ]]; }; then
  echo "[ERROR] NO-GO bootstrap: python3 ${PY3_VERSION} is below 3.${MIN_PYTHON_MINOR}." >&2
  exit 1
fi

if [[ -x "${SITL_VENV_PYTHON}" ]]; then
  echo "[BOOTSTRAP] Reusing venv at ${SITL_VENV_DIR}."
else
  echo "[BOOTSTRAP] Creating venv at ${SITL_VENV_DIR}."
  mkdir -p "$(dirname "${SITL_VENV_DIR}")"
  if python3 -m venv "${SITL_VENV_DIR}"; then
    echo "[BOOTSTRAP] Venv created."
  else
    VENV_CREATE_EXIT=$?
    echo "[ERROR] NO-GO bootstrap: python3 -m venv failed (exit=${VENV_CREATE_EXIT})." >&2
    echo "[ERROR] If ensurepip is unavailable, install python3.${PY3_MINOR}-venv manually." >&2
    echo "[ERROR] This script does not install apt packages or use sudo." >&2
    exit "${VENV_CREATE_EXIT}"
  fi
fi

if [[ ! -x "${SITL_VENV_PYTHON}" ]]; then
  echo "[ERROR] NO-GO bootstrap: ${SITL_VENV_PYTHON} is missing or not executable." >&2
  exit 1
fi

CYCLONEDDS_LIB_FOUND=0
for candidate in "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so" "${SITL_CYCLONEDDS_HOME}/lib"/libddsc.so.*; do
  if [[ -e "${candidate}" ]]; then
    CYCLONEDDS_LIB_FOUND=1
    break
  fi
done
if [[ "${CYCLONEDDS_LIB_FOUND}" -ne 1 ]]; then
  echo "[ERROR] NO-GO bootstrap: libddsc.so not found in ${SITL_CYCLONEDDS_HOME}/lib." >&2
  echo "[ERROR] Run scripts/bootstrap_cyclonedds_wsl.sh first, or export SITL_CYCLONEDDS_HOME." >&2
  exit 1
fi
export CYCLONEDDS_HOME="${SITL_CYCLONEDDS_HOME}"
export CMAKE_PREFIX_PATH="${SITL_CYCLONEDDS_HOME}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"
export LD_LIBRARY_PATH="${SITL_CYCLONEDDS_HOME}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

resolve_unitree_sdk_dir() {
  local primary="${PROJECT_ROOT}/libs/unitree_sdk2_python"
  local fallback="${PROJECT_ROOT}/libs/unitree_sdk2_python-master"

  if [[ -n "${UNITREE_SDK_DIR:-}" ]]; then
    local override
    override="$(cd "${UNITREE_SDK_DIR}" 2>/dev/null && pwd)"
    if [[ -z "${override}" || ! -f "${override}/setup.py" ]]; then
      echo "[ERROR] NO_GO_UNITREE_SDK_NOT_FOUND: UNITREE_SDK_DIR does not contain setup.py." >&2
      exit 1
    fi
    echo "${override}"
    return
  fi

  local primary_setup="${primary}/setup.py"
  local fallback_setup="${fallback}/setup.py"
  local primary_exists=0
  local fallback_exists=0

  [[ -f "${primary_setup}" ]] && primary_exists=1
  [[ -f "${fallback_setup}" ]] && fallback_exists=1

  if [[ "${primary_exists}" -ne 1 && "${fallback_exists}" -ne 1 ]]; then
    echo "[ERROR] NO_GO_UNITREE_SDK_NOT_FOUND: no vendored SDK setup.py found." >&2
    exit 1
  fi

  if [[ "${primary_exists}" -eq 1 && "${fallback_exists}" -eq 1 ]]; then
    local primary_hash fallback_hash
    primary_hash="$(sha256sum "${primary_setup}" | awk '{print $1}')"
    fallback_hash="$(sha256sum "${fallback_setup}" | awk '{print $1}')"
    if [[ "${primary_hash}" != "${fallback_hash}" ]]; then
      echo "[ERROR] NO_GO_DIVERGENT_UNITREE_SDK_VENDOR_COPIES: setup.py hashes differ." >&2
      exit 1
    fi
    echo "${primary}"
    return
  fi

  if [[ "${primary_exists}" -eq 1 ]]; then
    echo "${primary}"
  else
    echo "${fallback}"
  fi
}

UNITREE_SDK_RESOLVED_DIR="$(resolve_unitree_sdk_dir)"
echo "[BOOTSTRAP] UNITREE_SDK_RESOLVED_DIR=${UNITREE_SDK_RESOLVED_DIR}"

echo "[BOOTSTRAP] Installing dependencies from ${REQUIREMENTS_FILE}."
"${SITL_VENV_PYTHON}" -B -m pip install --requirement "${REQUIREMENTS_FILE}"

echo "[BOOTSTRAP] Installing vendored unitree_sdk2py with --no-deps."
"${SITL_VENV_PYTHON}" -B -m pip install --no-deps -e "${UNITREE_SDK_RESOLVED_DIR}"

OPENCV_GUI_PRESENT="$("${SITL_VENV_PYTHON}" -B -m pip show opencv-python >/dev/null 2>&1 && echo 1 || echo 0)"
if [[ "${OPENCV_GUI_PRESENT}" -eq 1 ]]; then
  echo "[ERROR] NO-GO bootstrap: opencv-python GUI package is installed alongside headless." >&2
  exit 1
fi

echo "[BOOTSTRAP] Validating installed modules without contacting hardware."
"${SITL_VENV_PYTHON}" -B -c "
import importlib.util
missing = []
for name in ('fastapi', 'uvicorn', 'pydantic', 'pydantic_settings',
             'statemachine', 'httpx', 'cyclonedds', 'unitree_sdk2py',
             'numpy', 'cv2'):
    if importlib.util.find_spec(name) is None:
        missing.append(name)
if missing:
    raise SystemExit(f'Missing modules: {missing}')
"

echo "[BOOTSTRAP] Validating Unitree SDK imports without contacting hardware."
"${SITL_VENV_PYTHON}" -B -c "
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
print('Unitree SDK imports OK')
"

echo "[BOOTSTRAP] GO: WSL SITL venv ready at ${SITL_VENV_DIR}."
