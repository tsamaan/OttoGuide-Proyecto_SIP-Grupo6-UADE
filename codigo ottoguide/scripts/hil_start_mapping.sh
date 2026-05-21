#!/bin/bash
set -eo pipefail
export AMENT_TRACE_SETUP_FILES=""
export AMENT_PYTHON_EXECUTABLE="$(which python3)"
source /opt/ros/foxy/setup.bash

: <<'DOC'
@TASK: Orquestar inicio de mapeo fisico HIL en Companion PC con sensores reales del Unitree G1.
@INPUT: Entorno ROS 2 Foxy disponible con bridge Livox SDK2 y RealSense instalados.
@OUTPUT: Drivers de sensores y slam_toolbox online_async ejecutandose en paralelo para generar mapa.
@CONTEXT: Flujo de pre-configuracion para mapeo fisico teleoperado por joystick nativo del G1.
@SECURITY: No inicia teleoperacion por teclado ni publica comandos de movimiento.
STEP [1]: Cargar workspace local.
STEP [2]: Levantar bridge Livox MID360 SDK2.
STEP [3]: Levantar driver RealSense.
STEP [4]: Ejecutar preflight read-only de sensores y /scan.
STEP [5]: Levantar slam_toolbox en modo online_async con reloj real.
STEP [6]: Mantener sesion viva y cerrar procesos hijos de forma segura al terminar.
DOC

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PREFLIGHT_SCRIPT="${SCRIPT_DIR}/preflight_sensors.sh"
HIL_PREFLIGHT_ENABLED="${HIL_PREFLIGHT_ENABLED:-1}"
HIL_SENSOR_WARMUP_S="${HIL_SENSOR_WARMUP_S:-8}"
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

PIDS=()

cleanup() {
  echo "@CONTEXT: Deteniendo stack de sensores..."
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill -INT "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
}

trap cleanup EXIT INT TERM

if [ ! -f "${LIVOX_SDK2_CONFIG_PATH}" ]; then
  echo "@OUTPUT: ERROR config Livox SDK2 no encontrada en ${LIVOX_SDK2_CONFIG_PATH}"
  exit 1
fi

ros2 launch ottoguide_livox_sdk_bridge mid360_sdk2_bridge.launch.py \
  config_path:="${LIVOX_SDK2_CONFIG_PATH}" \
  frame_id:="${LIVOX_FRAME_ID}" \
  topic_cloud:="${LIVOX_TOPIC_CLOUD}" \
  topic_imu:="${LIVOX_TOPIC_IMU}" &
PIDS+=("$!")

ros2 launch realsense2_camera rs_launch.py enable_depth:=true enable_color:=true pointcloud.enable:=true &
PIDS+=("$!")

if [ "${HIL_PREFLIGHT_ENABLED}" = "1" ]; then
  if [ ! -f "${PREFLIGHT_SCRIPT}" ]; then
    echo "@OUTPUT: ERROR preflight no encontrado en ${PREFLIGHT_SCRIPT}"
    exit 1
  fi
  sleep "${HIL_SENSOR_WARMUP_S}"
  bash "${PREFLIGHT_SCRIPT}"
fi

ros2 launch slam_toolbox online_async_launch.py use_sim_time:=false scan_topic:=/scan &
PIDS+=("$!")

echo "@OUTPUT: HIL mapping stack iniciado. livox=${PIDS[0]} realsense=${PIDS[1]} slam=${PIDS[2]}"
echo "@CONTEXT: Teleoperar el G1 con joystick nativo para recorrer el entorno durante el mapeo."

wait
