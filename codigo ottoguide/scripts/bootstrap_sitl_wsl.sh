#!/usr/bin/env bash
# @TASK: Aprovisionar un venv Linux reproducible para el panel FastAPI del runtime SITL en WSL.
# @INPUT: SITL_VENV_DIR (opcional, default ${HOME}/.venvs/ottoguide-sitl)
# @OUTPUT: Venv creado/validado en SITL_VENV_DIR con las dependencias de requirements_sitl.txt.
# @CONTEXT: Exclusivo para WSL2 x86_64. No reemplaza bootstrap_target.sh (Companion PC) ni el
#           runtime del robot fisico (Jetson Tegra, AArch64, Ubuntu 20.04, ROS 2 Foxy). Aislado
#           del .venv Windows del repo. Idempotencia: FUNCTIONALLY_IDEMPOTENT_WITH_EDITABLE_REINSTALL
#           (pip reinstala el enlace editable de unitree_sdk2py en cada corrida; el resto de
#           pip install -r resuelve a "Requirement already satisfied" sin cambios).
# @SECURITY: Sin sudo, sin apt, sin activar el venv, sin iniciar tmux/uvicorn/ROS/MuJoCo/Isaac.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements_sitl.txt"
SITL_VENV_DIR="${SITL_VENV_DIR:-${HOME}/.venvs/ottoguide-sitl}"
SITL_VENV_PYTHON="${SITL_VENV_DIR}/bin/python"
MIN_PYTHON_MINOR=10

# @CONTEXT: Biblioteca C de Eclipse CycloneDDS (releases/0.10.x), requerida
#           para compilar el binding Python cyclonedds==0.10.2 (no hay wheel
#           prebuilt para Linux/py3.12 en este indice). Se instala fuera del
#           repositorio, sin sudo, en una ruta propiedad del usuario. El
#           prerequisito reproducible se crea ejecutando primero
#           scripts/bootstrap_cyclonedds_wsl.sh (clona releases/0.10.x en el
#           commit fijado, compila con CMake e instala en
#           SITL_CYCLONEDDS_HOME) antes de ejecutar este script.
SITL_CYCLONEDDS_HOME="${SITL_CYCLONEDDS_HOME:-${HOME}/.local/opt/cyclonedds-0.10.x}"

echo "[BOOTSTRAP] Este script aprovisiona el runtime SITL de WSL."
echo "[BOOTSTRAP] No es el bootstrap del robot fisico."
echo "[BOOTSTRAP] PROJECT_ROOT=${PROJECT_ROOT}"
echo "[BOOTSTRAP] SITL_VENV_DIR=${SITL_VENV_DIR}"

# --- Guard de plataforma: WSL + x86_64 obligatorios ---
ARCH="$(uname -m)"
IS_WSL=0
if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
  IS_WSL=1
  echo "[BOOTSTRAP] Host WSL detectado: WSL_DISTRO_NAME=${WSL_DISTRO_NAME}"
elif grep -qi microsoft /proc/version 2>/dev/null; then
  IS_WSL=1
  echo "[BOOTSTRAP] Host WSL detectado via /proc/version (kernel microsoft)."
fi

if [[ "${IS_WSL}" -ne 1 ]]; then
  echo "[ERROR] NO_GO_WRONG_PLATFORM: no se detecto WSL (WSL_DISTRO_NAME ausente y /proc/version sin 'microsoft')." >&2
  echo "[ERROR] Este script aprovisiona el runtime SITL de WSL. No debe ejecutarse en el robot fisico." >&2
  exit 1
fi

case "${ARCH}" in
  x86_64) : ;;
  aarch64|arm64)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: arquitectura '${ARCH}' rechazada explicitamente." >&2
    echo "[ERROR] El venv y los pines de requirements_sitl.txt son para x86_64 (WSL SITL)." >&2
    echo "[ERROR] No es compatible con el robot fisico (Jetson Tegra, AArch64)." >&2
    exit 1
    ;;
  *)
    echo "[ERROR] NO_GO_WRONG_PLATFORM: arquitectura '${ARCH}' no reconocida ni autorizada." >&2
    exit 1
    ;;
esac
echo "[BOOTSTRAP] Plataforma validada: arch=${ARCH}"

if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
  echo "[ERROR] NO-GO bootstrap: manifiesto SITL ausente en ${REQUIREMENTS_FILE}" >&2
  exit 1
fi

# --- Proteccion anticolision con el venv Windows del repositorio ---
PROJECT_VENV_DIR="${PROJECT_ROOT}/.venv"
case "${SITL_VENV_DIR}" in
  "${PROJECT_VENV_DIR}"|"${PROJECT_VENV_DIR}"/*)
    echo "[ERROR] NO-GO bootstrap: SITL_VENV_DIR (${SITL_VENV_DIR}) cae dentro de ${PROJECT_VENV_DIR}." >&2
    echo "[ERROR] Ese directorio es el venv Windows del repositorio; no debe reutilizarse desde WSL." >&2
    exit 1
    ;;
esac
if [[ -e "${SITL_VENV_DIR}/Scripts/python.exe" ]]; then
  echo "[ERROR] NO-GO bootstrap: ${SITL_VENV_DIR} contiene un layout Windows (Scripts/python.exe)." >&2
  exit 1
fi
if [[ -e "${SITL_VENV_DIR}/pyvenv.cfg" ]] && [[ -e "${SITL_VENV_DIR}/Scripts" ]] && [[ ! -e "${SITL_VENV_DIR}/bin" ]]; then
  echo "[ERROR] NO-GO bootstrap: ${SITL_VENV_DIR} parece un venv Windows (Scripts/ sin bin/)." >&2
  exit 1
fi

# --- Validacion del interprete base ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] NO-GO bootstrap: python3 no encontrado en PATH." >&2
  exit 1
fi

PY3_VERSION="$(python3 -B -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
PY3_MAJOR="$(python3 -B -c 'import sys; print(sys.version_info[0])')"
PY3_MINOR="$(python3 -B -c 'import sys; print(sys.version_info[1])')"
echo "[BOOTSTRAP] python3 detectado: ${PY3_VERSION} ($(command -v python3))"

if [[ "${PY3_MAJOR}" -lt 3 ]] || { [[ "${PY3_MAJOR}" -eq 3 ]] && [[ "${PY3_MINOR}" -lt "${MIN_PYTHON_MINOR}" ]]; }; then
  echo "[ERROR] NO-GO bootstrap: python3 ${PY3_VERSION} no cumple el minimo requires-python>=3.${MIN_PYTHON_MINOR}." >&2
  exit 1
fi

# --- Creacion idempotente del venv ---
if [[ -x "${SITL_VENV_PYTHON}" ]]; then
  echo "[BOOTSTRAP] Venv ya existe en ${SITL_VENV_DIR}; no se recrea."
else
  echo "[BOOTSTRAP] Creando venv en ${SITL_VENV_DIR}..."
  mkdir -p "$(dirname "${SITL_VENV_DIR}")"
  if python3 -m venv "${SITL_VENV_DIR}"; then
    echo "[BOOTSTRAP] Venv creado."
  else
    VENV_CREATE_EXIT=$?
    echo "[ERROR] NO-GO bootstrap: python3 -m venv fallo (exit=${VENV_CREATE_EXIT})." >&2
    echo "[ERROR] Si el mensaje anterior menciona 'ensurepip is not available', falta el" >&2
    echo "[ERROR] paquete de sistema python3.${PY3_MINOR}-venv. Instalarlo manualmente" >&2
    echo "[ERROR] (sudo apt-get install -y python3.${PY3_MINOR}-venv) antes de reintentar." >&2
    echo "[ERROR] Este script no instala paquetes apt ni usa sudo." >&2
    exit "${VENV_CREATE_EXIT}"
  fi
fi

if [[ ! -x "${SITL_VENV_PYTHON}" ]]; then
  echo "[ERROR] NO-GO bootstrap: ${SITL_VENV_PYTHON} no existe o no es ejecutable tras la creacion." >&2
  exit 1
fi

VENV_PY_VERSION="$("${SITL_VENV_PYTHON}" -B --version 2>&1)"
echo "[BOOTSTRAP] Interprete del venv: ${VENV_PY_VERSION} (${SITL_VENV_PYTHON})"

# --- pip: no se actualiza automaticamente salvo necesidad demostrada ---
# @CONTEXT: El venv recien creado trae la version de pip empaquetada con la
#           libreria estandar de python3 -m venv (bootstrap via ensurepip).
#           No se ha demostrado ninguna incompatibilidad entre esa version y
#           los paquetes de requirements_sitl.txt, por lo que no se fuerza
#           `pip install --upgrade pip` en cada corrida (a diferencia de
#           bootstrap_target.sh, que si lo hace para el entorno productivo).
PIP_VERSION_BEFORE="$("${SITL_VENV_PYTHON}" -B -m pip --version 2>&1)"
echo "[BOOTSTRAP] pip actual: ${PIP_VERSION_BEFORE}"

# --- Validacion de la biblioteca C de CycloneDDS antes de instalar el binding Python ---
# @CONTEXT: requirements_sitl.txt declara cyclonedds==0.10.2 sin wheel
#           prebuilt para este host; el build desde fuente necesita
#           CYCLONEDDS_HOME/CMAKE_PREFIX_PATH apuntando a una instalacion
#           ya compilada de la biblioteca C. Este script no compila esa
#           biblioteca; el procedimiento reproducible es
#           scripts/bootstrap_cyclonedds_wsl.sh (ver SITL_CYCLONEDDS_HOME
#           arriba). Aqui solo se valida que ya exista.
CYCLONEDDS_LIB_FOUND=0
for _candidate in "${SITL_CYCLONEDDS_HOME}/lib/libddsc.so" "${SITL_CYCLONEDDS_HOME}/lib"/libddsc.so.*; do
  if [[ -e "${_candidate}" ]]; then
    CYCLONEDDS_LIB_FOUND=1
    break
  fi
done
if [[ "${CYCLONEDDS_LIB_FOUND}" -ne 1 ]]; then
  echo "[ERROR] NO-GO bootstrap: no se encontro libddsc.so en ${SITL_CYCLONEDDS_HOME}/lib" >&2
  echo "[ERROR] Ejecutar primero: scripts/bootstrap_cyclonedds_wsl.sh" >&2
  echo "[ERROR] Alternativamente, exportar SITL_CYCLONEDDS_HOME apuntando a una" >&2
  echo "[ERROR] instalacion existente de la biblioteca C." >&2
  exit 1
fi
echo "[BOOTSTRAP] Biblioteca C de CycloneDDS encontrada en ${SITL_CYCLONEDDS_HOME}"
export CYCLONEDDS_HOME="${SITL_CYCLONEDDS_HOME}"
export CMAKE_PREFIX_PATH="${SITL_CYCLONEDDS_HOME}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"
export LD_LIBRARY_PATH="${SITL_CYCLONEDDS_HOME}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
echo "[BOOTSTRAP] CYCLONEDDS_HOME=${CYCLONEDDS_HOME}"
echo "[BOOTSTRAP] CMAKE_PREFIX_PATH=${CMAKE_PREFIX_PATH}"
echo "[BOOTSTRAP] LD_LIBRARY_PATH=${LD_LIBRARY_PATH}"

# --- Instalacion del manifiesto SITL ---
echo "[BOOTSTRAP] Instalando dependencias desde ${REQUIREMENTS_FILE}..."
"${SITL_VENV_PYTHON}" -B -m pip install --requirement "${REQUIREMENTS_FILE}"

# --- Instalacion de unitree_sdk2py vendorizado (ruta absoluta, no soportada en requirements_sitl.txt) ---
# @CONTEXT: pip rechaza `paquete @ file:ruta-relativa`; se instala aqui con
#           la ruta absoluta de PROJECT_ROOT, ya resuelta. Mismo paquete
#           vendorizado que referencia pyproject.toml:46. Se usa --no-deps
#           porque el setup.py vendorizado declara `opencv-python` (no la
#           variante headless ya instalada por requirements_sitl.txt) y
#           `cyclonedds`/`numpy` ya quedaron satisfechos por el paso
#           anterior; instalar con resolucion automatica de dependencias
#           reinstalaria opencv-python sin headless, dejando ambas
#           variantes de OpenCV simultaneamente instaladas.
UNITREE_SDK_DIR="${PROJECT_ROOT}/libs/unitree_sdk2_python-master"
if [[ ! -f "${UNITREE_SDK_DIR}/setup.py" ]]; then
  echo "[ERROR] NO-GO bootstrap: paquete vendorizado unitree_sdk2py ausente en ${UNITREE_SDK_DIR}" >&2
  exit 1
fi
echo "[BOOTSTRAP] Instalando unitree_sdk2py vendorizado (--no-deps) desde ${UNITREE_SDK_DIR}..."
"${SITL_VENV_PYTHON}" -B -m pip install --no-deps -e "${UNITREE_SDK_DIR}"

# --- Verificacion de exclusividad OpenCV (headless vs GUI) ---
OPENCV_GUI_PRESENT="$("${SITL_VENV_PYTHON}" -B -m pip show opencv-python >/dev/null 2>&1 && echo 1 || echo 0)"
if [[ "${OPENCV_GUI_PRESENT}" -eq 1 ]]; then
  echo "[ERROR] NO-GO bootstrap: opencv-python (variante GUI) quedo instalado junto a opencv-python-headless." >&2
  echo "[ERROR] Desinstalar manualmente opencv-python del venv SITL y reintentar." >&2
  exit 1
fi
echo "[BOOTSTRAP] Verificado: solo opencv-python-headless presente (sin opencv-python)."

PIP_VERSION_AFTER="$("${SITL_VENV_PYTHON}" -B -m pip --version 2>&1)"
echo "[BOOTSTRAP] pip tras instalacion: ${PIP_VERSION_AFTER}"

# --- Validacion de modulos instalados (sin importar el proyecto) ---
# @CONTEXT: unitree_sdk2py y cyclonedds pertenecen a la capa LIFESPAN_SIM
#           (ver requirements_sitl.txt); se validan aqui porque estan
#           declarados en el manifiesto, pero su ausencia no degrada
#           silenciosamente: el bootstrap falla con NO-GO si faltan.
echo "[BOOTSTRAP] Validando modulos instalados..."
"${SITL_VENV_PYTHON}" -B -c "
import importlib.util
faltantes = []
modulos = (
    'fastapi', 'uvicorn', 'pydantic', 'pydantic_settings', 'statemachine',
    'httpx', 'cyclonedds', 'unitree_sdk2py', 'numpy', 'cv2',
)
for name in modulos:
    spec = importlib.util.find_spec(name)
    status = 'OK' if spec else 'FALTANTE'
    print(f'  {name}: {status}')
    if not spec:
        faltantes.append(name)
if faltantes:
    raise SystemExit(f'Modulos faltantes: {faltantes}')
"

echo "[BOOTSTRAP] Validando imports especificos del SDK Unitree (sin contactar hardware)..."
"${SITL_VENV_PYTHON}" -B -c "
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
print('  ChannelFactoryInitialize: OK (import)')
print('  LocoClient: OK (import)')
"

echo "[BOOTSTRAP] GO: venv SITL listo en ${SITL_VENV_DIR}."
echo "[BOOTSTRAP] Interprete: ${SITL_VENV_PYTHON}"
