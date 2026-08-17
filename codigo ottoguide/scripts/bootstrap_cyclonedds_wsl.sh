#!/usr/bin/env bash
# @TASK: Build and install the native Eclipse CycloneDDS C library for WSL SITL.
# @INPUT: SITL_CYCLONEDDS_SRC_DIR, SITL_CYCLONEDDS_HOME, SITL_CYCLONEDDS_COMMIT.
# @OUTPUT: libddsc.so installed outside the repository for cyclonedds==0.10.2.
# @CONTEXT: WSL2 x86_64 development host only. Not for the physical Jetson robot.
# @SECURITY: No sudo, no apt, no runtime startup. Rejects non-WSL and AArch64.

set -euo pipefail

echo "[CYCLONEDDS-BOOTSTRAP] WSL SITL only; do not run on the physical robot."

ARCH="$(uname -m)"
IS_WSL=0
if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
  IS_WSL=1
elif grep -qi microsoft /proc/version 2>/dev/null; then
  IS_WSL=1
fi

if [[ "${IS_WSL}" -ne 1 ]]; then
  echo "[ERROR] NO_GO_WRONG_PLATFORM: WSL was not detected." >&2
  echo "[ERROR] This script must not run on the physical robot or a generic Linux host." >&2
  exit 1
fi

case "${ARCH}" in
  x86_64) : ;;
  aarch64|arm64)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: architecture '${ARCH}' is explicitly rejected." >&2
    echo "[ERROR] This x86_64 WSL build is not compatible with the Jetson/AArch64 robot." >&2
    exit 1
    ;;
  *)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: architecture '${ARCH}' is not authorized." >&2
    exit 1
    ;;
esac

echo "[CYCLONEDDS-BOOTSTRAP] Platform OK: WSL=${WSL_DISTRO_NAME:-detected-via-proc} arch=${ARCH}"

SITL_CYCLONEDDS_SRC_DIR="${SITL_CYCLONEDDS_SRC_DIR:-${HOME}/.local/src/cyclonedds}"
SITL_CYCLONEDDS_HOME="${SITL_CYCLONEDDS_HOME:-${HOME}/.local/opt/cyclonedds-0.10.x}"
SITL_CYCLONEDDS_COMMIT="${SITL_CYCLONEDDS_COMMIT:-5041f3560c088c99e5088b2b8520b69169621196}"
SITL_CYCLONEDDS_REPO_URL="https://github.com/eclipse-cyclonedds/cyclonedds.git"

echo "[CYCLONEDDS-BOOTSTRAP] source_dir=${SITL_CYCLONEDDS_SRC_DIR}"
echo "[CYCLONEDDS-BOOTSTRAP] install_prefix=${SITL_CYCLONEDDS_HOME}"
echo "[CYCLONEDDS-BOOTSTRAP] source_commit=${SITL_CYCLONEDDS_COMMIT}"

require_tool() {
  local binary="$1"
  local package_hint="$2"
  if ! command -v "${binary}" >/dev/null 2>&1; then
    echo "[ERROR] NO-GO: '${binary}' is missing from PATH." >&2
    echo "[ERROR] Probable system package: ${package_hint}" >&2
    echo "[ERROR] Install it manually; this script does not run sudo or apt." >&2
    exit 1
  fi
}

require_tool cmake "cmake"
require_tool gcc "build-essential / gcc"
require_tool g++ "build-essential / g++"
require_tool git "git"
require_tool make "build-essential / make"

AVAILABLE_KB="$(df -Pk "${HOME}" | tail -1 | awk '{print $4}')"
echo "[CYCLONEDDS-BOOTSTRAP] Free space in ${HOME}: ${AVAILABLE_KB} KB"
if [[ "${AVAILABLE_KB}" -lt 1048576 ]]; then
  echo "[ERROR] NO-GO: less than 1 GiB available in ${HOME}." >&2
  exit 1
fi

mkdir -p "$(dirname "${SITL_CYCLONEDDS_SRC_DIR}")"
mkdir -p "$(dirname "${SITL_CYCLONEDDS_HOME}")"

if [[ -d "${SITL_CYCLONEDDS_SRC_DIR}/.git" ]]; then
  echo "[CYCLONEDDS-BOOTSTRAP] Reusing source repo at ${SITL_CYCLONEDDS_SRC_DIR}."
  if [[ -n "$(git -C "${SITL_CYCLONEDDS_SRC_DIR}" status --porcelain 2>&1)" ]]; then
    echo "[ERROR] NO-GO: source repo has local changes; not overwriting." >&2
    exit 1
  fi
else
  if [[ -e "${SITL_CYCLONEDDS_SRC_DIR}" ]]; then
    echo "[ERROR] NO-GO: source path exists but is not a git repository." >&2
    exit 1
  fi
  echo "[CYCLONEDDS-BOOTSTRAP] Cloning ${SITL_CYCLONEDDS_REPO_URL}."
  git clone --branch releases/0.10.x --depth 50 "${SITL_CYCLONEDDS_REPO_URL}" "${SITL_CYCLONEDDS_SRC_DIR}"
fi

cd "${SITL_CYCLONEDDS_SRC_DIR}"
if ! git cat-file -e "${SITL_CYCLONEDDS_COMMIT}^{commit}" 2>/dev/null; then
  echo "[CYCLONEDDS-BOOTSTRAP] Fetching pinned commit ${SITL_CYCLONEDDS_COMMIT}."
  git fetch origin "${SITL_CYCLONEDDS_COMMIT}" --depth 50
fi
git checkout --detach "${SITL_CYCLONEDDS_COMMIT}"

ACTUAL_HEAD="$(git rev-parse HEAD)"
if [[ "${ACTUAL_HEAD}" != "${SITL_CYCLONEDDS_COMMIT}" ]]; then
  echo "[ERROR] NO-GO: checked out ${ACTUAL_HEAD}, expected ${SITL_CYCLONEDDS_COMMIT}." >&2
  exit 1
fi

mkdir -p "${SITL_CYCLONEDDS_HOME}"
BUILD_DIR="${SITL_CYCLONEDDS_SRC_DIR}/build"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

cmake \
  -DCMAKE_INSTALL_PREFIX="${SITL_CYCLONEDDS_HOME}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_EXAMPLES=OFF \
  -DBUILD_TESTING=OFF \
  ..

cmake --build . --parallel "$(nproc)"
cmake --build . --target install

if [[ ! -e "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so" ]]; then
  echo "[ERROR] NO-GO: libddsc.so missing after install." >&2
  exit 1
fi
if ! compgen -G "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so.0*" >/dev/null; then
  echo "[ERROR] NO-GO: versioned libddsc.so.0* missing after install." >&2
  exit 1
fi
if [[ ! -d "${SITL_CYCLONEDDS_HOME}/lib/cmake" ]]; then
  echo "[ERROR] NO-GO: CMake metadata missing after install." >&2
  exit 1
fi
if [[ ! -x "${SITL_CYCLONEDDS_HOME}/bin/idlc" ]]; then
  echo "[ERROR] NO-GO: idlc missing or not executable after install." >&2
  exit 1
fi

LIBDDSC_VERSION_FILE="$(basename "$(compgen -G "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so.0.*" | head -1)")"

echo "[CYCLONEDDS-BOOTSTRAP] GO"
echo "[CYCLONEDDS-BOOTSTRAP] source_commit=${ACTUAL_HEAD}"
echo "[CYCLONEDDS-BOOTSTRAP] source_dir=${SITL_CYCLONEDDS_SRC_DIR}"
echo "[CYCLONEDDS-BOOTSTRAP] build_dir=${BUILD_DIR}"
echo "[CYCLONEDDS-BOOTSTRAP] install_prefix=${SITL_CYCLONEDDS_HOME}"
echo "[CYCLONEDDS-BOOTSTRAP] libddsc_version_file=${LIBDDSC_VERSION_FILE}"
