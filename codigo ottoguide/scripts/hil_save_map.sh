#!/bin/bash
set -eo pipefail
export AMENT_TRACE_SETUP_FILES=""
export AMENT_PYTHON_EXECUTABLE="$(which python3)"
source /opt/ros/foxy/setup.bash
source /home/unitree/livox_ws/install/setup.bash

: <<'DOC'
@TASK: Persistir mapa fisico generado por slam_toolbox mediante nav2_map_server.
@INPUT: Nodo slam_toolbox activo y topicos de mapa disponibles en ROS 2 Foxy.
@OUTPUT: Archivos YAML y PGM en ruta absoluta maps/uade_physical_map.
@CONTEXT: Script operativo para cierre de sesion de mapeo HIL.
@SECURITY: Falla de forma explicita si map_saver_cli no responde en 60 segundos.
STEP [1]: Cargar workspace local.
STEP [2]: Construir ruta absoluta destino y asegurar directorio existente.
STEP [3]: Ejecutar map_saver_cli con timeout de seguridad.
DOC

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MAP_BASENAME="${1:-${HIL_MAP_BASENAME:-${PROJECT_ROOT}/maps/uade_physical_map}}"

if [ -f "${PROJECT_ROOT}/install/setup.bash" ]; then
  source "${PROJECT_ROOT}/install/setup.bash"
fi

mkdir -p "$(dirname "${MAP_BASENAME}")"

echo "@CONTEXT: Invocando map_saver_cli en ${MAP_BASENAME}..."
if timeout 60 ros2 run nav2_map_server map_saver_cli -f "${MAP_BASENAME}"; then
  echo "@OUTPUT: Mapa guardado exitosamente en ${MAP_BASENAME}.yaml y ${MAP_BASENAME}.pgm"
else
  echo "@OUTPUT: ERROR al guardar el mapa. map_saver_cli fallo o excedio timeout." >&2
  exit 1
fi
