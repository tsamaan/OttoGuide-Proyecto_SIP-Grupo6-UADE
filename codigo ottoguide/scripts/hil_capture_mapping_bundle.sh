#!/bin/bash
set -eo pipefail
export AMENT_TRACE_SETUP_FILES=""
export AMENT_PYTHON_EXECUTABLE="$(which python3)"
source /opt/ros/foxy/setup.bash
source /home/unitree/livox_ws/install/setup.bash

: <<'DOC'
@TASK: Ejecutar captura HIL de mapeo con fases declarativas y manifiesto.
@INPUT: ROS 2 Humble, drivers Livox/RealSense, slam_toolbox, rosbag2 y nav2_map_server.
@OUTPUT: rosbag2, mapa YAML/PGM y manifest JSON de la sesion.
@CONTEXT: Orquestador para recorrer una sola vez el entorno y capturar mapa/datos brutos.
@SECURITY: No publica locomocion; solo levanta sensores, SLAM y suscripcion rosbag2.
STEP 1: Preflight de scripts, comandos y rutas.
STEP 2: Arrancar stack de mapeo y esperar topics/nodo criticos.
STEP 3: Iniciar rosbag2 con path exacto y mantener sesion hasta Ctrl+C.
STEP 4: Guardar mapa, validar artefactos y emitir manifest.
DOC

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROS_SETUP="/opt/ros/foxy/setup.bash"
HIL_MAP_BASENAME="${HIL_MAP_BASENAME:-${PROJECT_ROOT}/maps/uade_physical_map}"
HIL_BAG_OUT_DIR="${HIL_BAG_OUT_DIR:-${PROJECT_ROOT}/logs/bags}"
HIL_DRY_RUN="${HIL_DRY_RUN:-0}"
HIL_READY_TIMEOUT_S="${HIL_READY_TIMEOUT_S:-90}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BAG_PATH="${HIL_BAG_PATH:-${HIL_BAG_OUT_DIR}/hil_mapping_${STAMP}}"
MANIFEST_PATH="${HIL_MANIFEST_PATH:-${HIL_BAG_OUT_DIR}/hil_mapping_${STAMP}_manifest.json}"
SESSION_STARTED_EPOCH="$(date +%s)"

MAPPING_SCRIPT="${SCRIPT_DIR}/hil_start_mapping.sh"
RECORDER_SCRIPT="${SCRIPT_DIR}/hil_mapping_recorder.sh"
SAVE_MAP_SCRIPT="${SCRIPT_DIR}/hil_save_map.sh"

PIDS=()
RECORDER_STARTED=0
MAP_SAVE_STATUS="not-run"

log_output() {
  printf '@OUTPUT: %s\n' "$*"
}

log_context() {
  printf '@CONTEXT: %s\n' "$*"
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "${path}" ]]; then
    printf '@OUTPUT: ERROR falta %s: %s\n' "${label}" "${path}" >&2
    exit 1
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf '@OUTPUT: ERROR comando requerido no disponible: %s\n' "${command_name}" >&2
    exit 1
  fi
}

load_ros_environment() {
  if [[ -f "${ROS_SETUP}" ]]; then
    # shellcheck source=/dev/null
    source "${ROS_SETUP}"
  fi
  if [[ -f "${PROJECT_ROOT}/install/setup.bash" ]]; then
    # shellcheck source=/dev/null
    source "${PROJECT_ROOT}/install/setup.bash"
  fi
}

wait_for_process() {
  local description="$1"
  local pid="$2"
  if kill -0 "${pid}" >/dev/null 2>&1; then
    log_output "${description} listo"
    return 0
  fi
  printf '@OUTPUT: ERROR proceso no activo: %s pid=%s\n' "${description}" "${pid}" >&2
  return 1
}

wait_for_topic() {
  local topic_name="$1"
  local timeout_seconds="$2"
  local elapsed=0

  while [[ "${elapsed}" -lt "${timeout_seconds}" ]]; do
    if ros2 topic list 2>/dev/null | grep -Fxq "${topic_name}"; then
      log_output "topic ${topic_name} listo"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  printf '@OUTPUT: ERROR timeout esperando topic %s\n' "${topic_name}" >&2
  return 1
}

wait_for_node_pattern() {
  local description="$1"
  local pattern="$2"
  local timeout_seconds="$3"
  local elapsed=0

  while [[ "${elapsed}" -lt "${timeout_seconds}" ]]; do
    if ros2 node list 2>/dev/null | grep -Eq "${pattern}"; then
      log_output "${description} listo"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  printf '@OUTPUT: ERROR timeout esperando %s\n' "${description}" >&2
  return 1
}

checksum_or_empty() {
  local path="$1"
  if [[ -f "${path}" ]] && command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${path}" | awk '{print $1}'
  else
    printf ''
  fi
}

write_manifest() {
  local result="$1"
  local ended_epoch
  local duration_s
  local map_yaml
  local map_pgm
  local yaml_sha
  local pgm_sha

  ended_epoch="$(date +%s)"
  duration_s=$((ended_epoch - SESSION_STARTED_EPOCH))
  map_yaml="${HIL_MAP_BASENAME}.yaml"
  map_pgm="${HIL_MAP_BASENAME}.pgm"
  yaml_sha="$(checksum_or_empty "${map_yaml}")"
  pgm_sha="$(checksum_or_empty "${map_pgm}")"

  mkdir -p "$(dirname "${MANIFEST_PATH}")"
  cat >"${MANIFEST_PATH}" <<JSON
{
  "result": "${result}",
  "started_epoch": ${SESSION_STARTED_EPOCH},
  "ended_epoch": ${ended_epoch},
  "duration_s": ${duration_s},
  "map_basename": "${HIL_MAP_BASENAME}",
  "map_yaml": "${map_yaml}",
  "map_pgm": "${map_pgm}",
  "map_save_status": "${MAP_SAVE_STATUS}",
  "map_yaml_sha256": "${yaml_sha}",
  "map_pgm_sha256": "${pgm_sha}",
  "bag_path": "${BAG_PATH}",
  "topics_required": [
    "/scan",
    "/livox/lidar",
    "/livox/imu",
    "/camera/color/image_raw",
    "/camera/depth/image_rect_raw",
    "/tf",
    "/tf_static",
    "/map",
    "/robot_state/odom"
  ]
}
JSON
  log_output "Manifest generado en ${MANIFEST_PATH}"
}

validate_artifacts() {
  local result="success"
  if [[ ! -f "${HIL_MAP_BASENAME}.yaml" ]]; then
    printf '@OUTPUT: ERROR mapa YAML no generado: %s.yaml\n' "${HIL_MAP_BASENAME}" >&2
    result="failed"
  fi
  if [[ ! -f "${HIL_MAP_BASENAME}.pgm" ]]; then
    printf '@OUTPUT: ERROR mapa PGM no generado: %s.pgm\n' "${HIL_MAP_BASENAME}" >&2
    result="failed"
  fi
  if [[ ! -d "${BAG_PATH}" ]]; then
    printf '@OUTPUT: ERROR bag no generado: %s\n' "${BAG_PATH}" >&2
    result="failed"
  fi
  [[ "${result}" == "success" ]]
}

cleanup() {
  local exit_code="${1:-0}"
  local result="success"

  trap - INT TERM EXIT

  if [[ "${RECORDER_STARTED}" -eq 1 ]] && [[ -n "${PIDS[1]:-}" ]] && kill -0 "${PIDS[1]}" >/dev/null 2>&1; then
    kill -INT "${PIDS[1]}" >/dev/null 2>&1 || true
    wait "${PIDS[1]}" >/dev/null 2>&1 || true
  fi

  log_context "Cerrando captura y guardando mapa en ${HIL_MAP_BASENAME}"
  if HIL_MAP_BASENAME="${HIL_MAP_BASENAME}" bash "${SAVE_MAP_SCRIPT}"; then
    MAP_SAVE_STATUS="success"
  else
    MAP_SAVE_STATUS="failed"
    result="failed"
  fi

  if [[ -n "${PIDS[0]:-}" ]] && kill -0 "${PIDS[0]}" >/dev/null 2>&1; then
    kill -INT "${PIDS[0]}" >/dev/null 2>&1 || true
    wait "${PIDS[0]}" >/dev/null 2>&1 || true
  fi

  if ! validate_artifacts; then
    result="failed"
  fi
  if [[ "${exit_code}" -ne 0 && "${exit_code}" -ne 130 ]]; then
    result="failed"
  fi
  write_manifest "${result}"
  exit "${exit_code}"
}

on_signal() {
  cleanup 130
}

preflight() {
  require_file "${MAPPING_SCRIPT}" "script de mapeo"
  require_file "${RECORDER_SCRIPT}" "script de rosbag"
  require_file "${SAVE_MAP_SCRIPT}" "script de guardado de mapa"
  mkdir -p "${HIL_BAG_OUT_DIR}" "$(dirname "${BAG_PATH}")" "$(dirname "${HIL_MAP_BASENAME}")"
  load_ros_environment
  require_command grep
  require_command awk
  if [[ "${HIL_DRY_RUN}" != "1" ]]; then
    require_command ros2
  fi
  log_output "Preflight OK"
}

preflight

if [[ "${HIL_DRY_RUN}" == "1" ]]; then
  log_output "Dry-run OK. No se iniciaron procesos ROS2."
  write_manifest "dry-run"
  exit 0
fi

trap on_signal INT TERM
trap 'cleanup $?' EXIT

bash "${MAPPING_SCRIPT}" &
PIDS+=("$!")

wait_for_process "mapping stack" "${PIDS[0]}"
wait_for_node_pattern "SLAM" '(^|/)slam_toolbox($|/)' "${HIL_READY_TIMEOUT_S}"
wait_for_topic "/scan" "${HIL_READY_TIMEOUT_S}"
wait_for_topic "/livox/lidar" "${HIL_READY_TIMEOUT_S}"
wait_for_topic "/livox/imu" "${HIL_READY_TIMEOUT_S}"
wait_for_topic "/camera/color/image_raw" "${HIL_READY_TIMEOUT_S}"
wait_for_topic "/camera/depth/image_rect_raw" "${HIL_READY_TIMEOUT_S}"
wait_for_topic "/map" "${HIL_READY_TIMEOUT_S}"

HIL_BAG_PATH="${BAG_PATH}" ROS_SETUP="${ROS_SETUP}" bash "${RECORDER_SCRIPT}" "${HIL_BAG_OUT_DIR}" &
PIDS+=("$!")
RECORDER_STARTED=1
wait_for_process "rosbag2" "${PIDS[1]}"

log_output "Captura unica de mapeo iniciada. mapping=${PIDS[0]} bag=${PIDS[1]}"
log_output "Bag destino ${BAG_PATH}"
log_output "Mapa destino ${HIL_MAP_BASENAME}.yaml y ${HIL_MAP_BASENAME}.pgm"
log_context "Conducir una sola vez el recorrido; al terminar, pulsar Ctrl+C para guardar todo."

wait "${PIDS[0]}"
