#!/bin/bash
set -eo pipefail
export AMENT_TRACE_SETUP_FILES=""
export AMENT_PYTHON_EXECUTABLE="$(which python3)"
source /opt/ros/foxy/setup.bash

: <<'DOC'
@TASK: Iniciar navegacion autonoma fisica HIL con mapa pre-generado y reloj real.
@INPUT: ROS 2 Foxy activo, mapa en maps/uade_physical_map.yaml y bridge Livox SDK2 disponible.
@OUTPUT: Drivers fisicos y stack Nav2/AMCL levantados con use_sim_time:=false.
@CONTEXT: Orquestador operativo para fase de navegacion autonoma fisica en Companion PC.
@SECURITY: No publica comandos manuales de locomocion; solo habilita infraestructura de navegacion.
STEP [1]: Cargar workspace local si existe.
STEP [2]: Verificar existencia del mapa fisico requerido.
STEP [3]: Levantar bridge Livox MID360 SDK2 y RealSense.
STEP [4]: Levantar Nav2 bringup con AMCL usando el mapa fisico y use_sim_time:=false.
STEP [5]: Mantener procesos en foreground con limpieza segura por senales.
DOC

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MAP_PATH="${PROJECT_ROOT}/maps/uade_physical_map.yaml"
LIVOX_SDK2_CONFIG_PATH="${LIVOX_SDK2_CONFIG_PATH:-${PROJECT_ROOT}/config/livox/mid360_sdk2_bridge.json}"
LIVOX_FRAME_ID="${LIVOX_FRAME_ID:-utlidar_lidar}"
LIVOX_TOPIC_CLOUD="${LIVOX_TOPIC_CLOUD:-/utlidar/cloud}"
LIVOX_TOPIC_IMU="${LIVOX_TOPIC_IMU:-/livox/imu}"

if [ -f "${PROJECT_ROOT}/install/setup.bash" ]; then
  source "${PROJECT_ROOT}/install/setup.bash"
fi
if [ -f "${PROJECT_ROOT}/ros2_ws/install/setup.bash" ]; then
  source "${PROJECT_ROOT}/ros2_ws/install/setup.bash"
fi

if [ ! -f "${MAP_PATH}" ]; then
  echo "@OUTPUT: ERROR mapa no encontrado en ${MAP_PATH}"
  exit 1
fi
if [ ! -f "${LIVOX_SDK2_CONFIG_PATH}" ]; then
  echo "@OUTPUT: ERROR config Livox SDK2 no encontrada en ${LIVOX_SDK2_CONFIG_PATH}"
  exit 1
fi

PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill -INT "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
}

trap cleanup EXIT INT TERM

ros2 launch ottoguide_livox_sdk_bridge mid360_sdk2_bridge.launch.py \
  config_path:="${LIVOX_SDK2_CONFIG_PATH}" \
  frame_id:="${LIVOX_FRAME_ID}" \
  topic_cloud:="${LIVOX_TOPIC_CLOUD}" \
  topic_imu:="${LIVOX_TOPIC_IMU}" &
PIDS+=("$!")

ros2 launch realsense2_camera rs_launch.py enable_depth:=true enable_color:=true pointcloud.enable:=true &
PIDS+=("$!")

ros2 launch nav2_bringup navigation_launch.py map:="${MAP_PATH}" use_sim_time:=false autostart:=true &
PIDS+=("$!")

echo "@OUTPUT: HIL navigation stack iniciado. livox=${PIDS[0]} realsense=${PIDS[1]} nav2=${PIDS[2]}"
echo "@CONTEXT: FSM puede despachar metas 2D sobre el mapa fisico cargado."

wait
