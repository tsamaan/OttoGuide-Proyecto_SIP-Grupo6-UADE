#!/bin/bash
set -eo pipefail
export AMENT_TRACE_SETUP_FILES=""
export AMENT_PYTHON_EXECUTABLE=""

: <<'DOC'
@TASK: Persistir mapa fisico generado por slam_toolbox mediante nav2_map_server.
@INPUT: Nodo slam_toolbox activo y topicos de mapa disponibles en ROS 2 Humble.
@OUTPUT: Archivos YAML y PGM en ruta absoluta codigo ottoguide/maps/uade_physical_map.
@CONTEXT: Script operativo para cierre de sesion de mapeo HIL.
@SECURITY: Falla de forma explicita si el servicio de guardado no responde o la ruta no es escribible.
STEP [1]: Cargar setup ROS 2 y workspace local.
STEP [2]: Construir ruta absoluta destino y asegurar directorio existente.
STEP [3]: Ejecutar map_saver_cli con timeout de seguridad.
DOC

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# @CONTEXT: Inyeccion de middleware ROS 2 verificada para robot (header canónico)
source /opt/ros/foxy/setup.bash
source /home/unitree/livox_ws/install/setup.bash
ROS_SETUP="/opt/ros/foxy/setup.bash"
MAP_BASENAME="${1:-${HIL_MAP_BASENAME:-${PROJECT_ROOT}/maps/uade_physical_map}}"

if [ ! -f "${ROS_SETUP}" ]; then
  echo "@OUTPUT: ERROR ROS_SETUP no encontrado: ${ROS_SETUP}" >&2
  exit 1
fi

# shellcheck source=/dev/null
# source "${ROS_SETUP}"
if [ -f "${PROJECT_ROOT}/install/setup.bash" ]; then
  # shellcheck source=/dev/null
  source "${PROJECT_ROOT}/install/setup.bash"
fi

if ! command -v ros2 >/dev/null 2>&1; then
  echo "@OUTPUT: ERROR comando ros2 no disponible tras cargar ROS_SETUP" >&2
  exit 1
fi
if ! command -v timeout >/dev/null 2>&1; then
  echo "@OUTPUT: ERROR comando timeout no disponible" >&2
  exit 1
fi

mkdir -p "$(dirname "${MAP_BASENAME}")"

timeout 60 ros2 run nav2_map_server map_saver_cli -f "${MAP_BASENAME}"

echo "@OUTPUT: Mapa guardado en ${MAP_BASENAME}.yaml y ${MAP_BASENAME}.pgm"
