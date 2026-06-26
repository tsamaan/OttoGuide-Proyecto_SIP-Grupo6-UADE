#!/usr/bin/env bash
# @TASK: Compilar e instalar la biblioteca C nativa de Eclipse CycloneDDS para el runtime SITL WSL.
# @INPUT: SITL_CYCLONEDDS_SRC_DIR, SITL_CYCLONEDDS_HOME, SITL_CYCLONEDDS_COMMIT (todos opcionales).
# @OUTPUT: libddsc.so instalada en SITL_CYCLONEDDS_HOME, lista para que el binding Python
#          cyclonedds==0.10.2 la enlace via CYCLONEDDS_HOME/CMAKE_PREFIX_PATH.
# @CONTEXT: Exclusivo para el host SITL de desarrollo (WSL2, x86_64). NO es el bootstrap del
#           robot fisico (Jetson Tegra, AArch64, Ubuntu 20.04, ROS 2 Foxy) ni lo reemplaza.
# @SECURITY: Sin sudo, sin apt, sin iniciar procesos DDS. Rechaza explicitamente ejecutarse
#            fuera de WSL o en una arquitectura distinta de x86_64.

set -euo pipefail

echo "[CYCLONEDDS-BOOTSTRAP] Este bootstrap es exclusivo para WSL SITL y no debe ejecutarse en el robot fisico."

# --- Guard de plataforma: WSL + x86_64 obligatorios ---
ARCH="$(uname -m)"
IS_WSL=0
if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
  IS_WSL=1
elif grep -qi microsoft /proc/version 2>/dev/null; then
  IS_WSL=1
fi

if [[ "${IS_WSL}" -ne 1 ]]; then
  echo "[ERROR] NO_GO_WRONG_PLATFORM: no se detecto WSL (WSL_DISTRO_NAME ausente y /proc/version sin 'microsoft')." >&2
  echo "[ERROR] Este script no debe ejecutarse en el robot fisico ni en un host Linux generico sin WSL." >&2
  exit 1
fi

case "${ARCH}" in
  x86_64) : ;;
  aarch64|arm64)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: arquitectura '${ARCH}' rechazada explicitamente." >&2
    echo "[ERROR] El build x86_64 de CycloneDDS no es compatible con AArch64 (robot fisico Jetson)." >&2
    echo "[ERROR] No reutilizar este build en el robot. Este script no tiene opcion para omitir este chequeo." >&2
    exit 1
    ;;
  *)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: arquitectura '${ARCH}' no reconocida ni autorizada." >&2
    exit 1
    ;;
esac

echo "[CYCLONEDDS-BOOTSTRAP] Plataforma validada: WSL_DISTRO_NAME=${WSL_DISTRO_NAME:-<detectado via /proc/version>} arch=${ARCH}"

SITL_CYCLONEDDS_SRC_DIR="${SITL_CYCLONEDDS_SRC_DIR:-${HOME}/.local/src/cyclonedds}"
SITL_CYCLONEDDS_HOME="${SITL_CYCLONEDDS_HOME:-${HOME}/.local/opt/cyclonedds-0.10.x}"
SITL_CYCLONEDDS_COMMIT="${SITL_CYCLONEDDS_COMMIT:-5041f3560c088c99e5088b2b8520b69169621196}"
SITL_CYCLONEDDS_REPO_URL="https://github.com/eclipse-cyclonedds/cyclonedds.git"

echo "[CYCLONEDDS-BOOTSTRAP] SITL_CYCLONEDDS_SRC_DIR=${SITL_CYCLONEDDS_SRC_DIR}"
echo "[CYCLONEDDS-BOOTSTRAP] SITL_CYCLONEDDS_HOME=${SITL_CYCLONEDDS_HOME}"
echo "[CYCLONEDDS-BOOTSTRAP] SITL_CYCLONEDDS_COMMIT=${SITL_CYCLONEDDS_COMMIT}"

# --- Preflight de herramientas de compilacion (sin apt ni sudo) ---
_require_tool() {
  local binario="$1" paquete_probable="$2"
  if ! command -v "${binario}" >/dev/null 2>&1; then
    echo "[ERROR] NO-GO: falta '${binario}' en PATH." >&2
    echo "[ERROR] Paquete de sistema probable: ${paquete_probable}" >&2
    echo "[ERROR] Este script no ejecuta apt ni sudo; instalar manualmente y reintentar." >&2
    exit 1
  fi
}
_require_tool cmake "cmake"
_require_tool gcc "build-essential / gcc"
_require_tool g++ "build-essential / g++"
_require_tool git "git"
_require_tool make "build-essential / make"

AVAILABLE_KB="$(df -Pk "${HOME}" | tail -1 | awk '{print $4}')"
echo "[CYCLONEDDS-BOOTSTRAP] Espacio disponible en ${HOME}: ${AVAILABLE_KB} KB"
if [[ "${AVAILABLE_KB}" -lt 1048576 ]]; then
  echo "[ERROR] NO-GO: menos de 1 GiB disponible en ${HOME} (${AVAILABLE_KB} KB). Build requiere mas espacio." >&2
  exit 1
fi

mkdir -p "$(dirname "${SITL_CYCLONEDDS_SRC_DIR}")"
mkdir -p "$(dirname "${SITL_CYCLONEDDS_HOME}")"

# --- Clonado o reutilizacion de la fuente (no se borra automaticamente) ---
if [[ -d "${SITL_CYCLONEDDS_SRC_DIR}/.git" ]]; then
  echo "[CYCLONEDDS-BOOTSTRAP] Fuente ya existe en ${SITL_CYCLONEDDS_SRC_DIR}; no se reclona."
  if [[ -n "$(git -C "${SITL_CYCLONEDDS_SRC_DIR}" status --porcelain 2>&1)" ]]; then
    echo "[ERROR] NO-GO: ${SITL_CYCLONEDDS_SRC_DIR} contiene cambios locales no confirmados." >&2
    echo "[ERROR] Este script no descarta ni sobrescribe cambios locales automaticamente." >&2
    exit 1
  fi
else
  if [[ -e "${SITL_CYCLONEDDS_SRC_DIR}" ]]; then
    echo "[ERROR] NO-GO: ${SITL_CYCLONEDDS_SRC_DIR} existe pero no es un repositorio git valido." >&2
    exit 1
  fi
  echo "[CYCLONEDDS-BOOTSTRAP] Clonando ${SITL_CYCLONEDDS_REPO_URL} (releases/0.10.x)..."
  git clone --branch releases/0.10.x --depth 50 "${SITL_CYCLONEDDS_REPO_URL}" "${SITL_CYCLONEDDS_SRC_DIR}"
fi

# --- Checkout detached del commit exacto (no depende del HEAD mutable de la rama) ---
cd "${SITL_CYCLONEDDS_SRC_DIR}"
if ! git cat-file -e "${SITL_CYCLONEDDS_COMMIT}^{commit}" 2>/dev/null; then
  echo "[CYCLONEDDS-BOOTSTRAP] Commit ${SITL_CYCLONEDDS_COMMIT} no presente localmente; haciendo fetch..."
  git fetch origin "${SITL_CYCLONEDDS_COMMIT}" --depth 50
fi
git checkout --detach "${SITL_CYCLONEDDS_COMMIT}"

ACTUAL_HEAD="$(git rev-parse HEAD)"
echo "[CYCLONEDDS-BOOTSTRAP] git rev-parse HEAD = ${ACTUAL_HEAD}"
if [[ "${ACTUAL_HEAD}" != "${SITL_CYCLONEDDS_COMMIT}" ]]; then
  echo "[ERROR] NO-GO: HEAD tras checkout (${ACTUAL_HEAD}) no coincide con SITL_CYCLONEDDS_COMMIT (${SITL_CYCLONEDDS_COMMIT})." >&2
  exit 1
fi

# --- Configuracion, compilacion e instalacion (sin borrar instalacion existente) ---
mkdir -p "${SITL_CYCLONEDDS_HOME}"
BUILD_DIR="${SITL_CYCLONEDDS_SRC_DIR}/build"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

echo "[CYCLONEDDS-BOOTSTRAP] === CMAKE CONFIGURE ==="
cmake \
  -DCMAKE_INSTALL_PREFIX="${SITL_CYCLONEDDS_HOME}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_EXAMPLES=OFF \
  -DBUILD_TESTING=OFF \
  ..

NPROC="$(nproc)"
echo "[CYCLONEDDS-BOOTSTRAP] === CMAKE BUILD (jobs=${NPROC}) ==="
cmake --build . --parallel "${NPROC}"

echo "[CYCLONEDDS-BOOTSTRAP] === CMAKE INSTALL ==="
cmake --build . --target install

# --- Validacion de la instalacion ---
LIBDDSC_SO=""
for _candidate in "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so" "${SITL_CYCLONEDDS_HOME}/lib"/libddsc.so.*; do
  if [[ -e "${_candidate}" ]]; then
    LIBDDSC_SO="${_candidate}"
    break
  fi
done
if [[ ! -e "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so" ]]; then
  echo "[ERROR] NO-GO: ${SITL_CYCLONEDDS_HOME}/lib/libddsc.so ausente tras la instalacion." >&2
  exit 1
fi
if ! compgen -G "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so.0*" >/dev/null; then
  echo "[ERROR] NO-GO: no se encontro libddsc.so.0* en ${SITL_CYCLONEDDS_HOME}/lib" >&2
  exit 1
fi
if [[ ! -d "${SITL_CYCLONEDDS_HOME}/lib/cmake" ]]; then
  echo "[ERROR] NO-GO: metadata CMake ausente en ${SITL_CYCLONEDDS_HOME}/lib/cmake" >&2
  exit 1
fi
PKGCONFIG_FOUND="NO"
if [[ -d "${SITL_CYCLONEDDS_HOME}/lib/pkgconfig" ]]; then
  PKGCONFIG_FOUND="YES"
fi
if [[ ! -x "${SITL_CYCLONEDDS_HOME}/bin/idlc" ]]; then
  echo "[ERROR] NO-GO: ejecutable bin/idlc ausente o no ejecutable en ${SITL_CYCLONEDDS_HOME}" >&2
  exit 1
fi

LIBDDSC_VERSION_FILE="$(basename "$(compgen -G "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so.0.*" | head -1)")"

echo "[CYCLONEDDS-BOOTSTRAP] === RESUMEN ==="
echo "[CYCLONEDDS-BOOTSTRAP] source_commit=${ACTUAL_HEAD}"
echo "[CYCLONEDDS-BOOTSTRAP] source_dir=${SITL_CYCLONEDDS_SRC_DIR}"
echo "[CYCLONEDDS-BOOTSTRAP] build_dir=${BUILD_DIR}"
echo "[CYCLONEDDS-BOOTSTRAP] install_prefix=${SITL_CYCLONEDDS_HOME}"
echo "[CYCLONEDDS-BOOTSTRAP] libddsc_version_file=${LIBDDSC_VERSION_FILE}"
echo "[CYCLONEDDS-BOOTSTRAP] pkgconfig_present=${PKGCONFIG_FOUND}"
echo "[CYCLONEDDS-BOOTSTRAP] idlc=${SITL_CYCLONEDDS_HOME}/bin/idlc"
echo "[CYCLONEDDS-BOOTSTRAP] GO: biblioteca nativa CycloneDDS lista en ${SITL_CYCLONEDDS_HOME}"
