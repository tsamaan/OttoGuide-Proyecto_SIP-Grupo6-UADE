#!/bin/bash
set -eo pipefail

: <<'DOC'
@TASK: Levantar el sandbox Nav2 offline (map_server + lifecycle_manager +
       simulador sintetico + TF) en aislamiento local, sin robot ni red.
@INPUT: WSL con ROS 2 jazzy disponible en /opt/ros/jazzy.
@OUTPUT: Stack del sandbox offline corriendo en foreground bajo
         ROS_LOCALHOST_ONLY=1 y un ROS_DOMAIN_ID dedicado distinto de 0.
@CONTEXT: Fase 2A del sandbox de navegacion offline. No incluye planner,
          controller, waypoint follower, Collision Monitor ni Simple
          Commander. No publica comandos de velocidad de ningun tipo.
@SECURITY: No abre conexiones de red, no usa IPs fisicas, no inicia
           bridges Unitree. Aborta si el aislamiento no puede garantizarse.
STEP [1]: Verificar que se ejecuta dentro de WSL.
STEP [2]: Exportar ROS_LOCALHOST_ONLY=1.
STEP [3]: Exigir o asignar ROS_DOMAIN_ID dedicado (!= 0), default 77.
STEP [4]: Ejecutar el verificador de aislamiento en modo runtime.
STEP [5]: Sourcear /opt/ros/jazzy/setup.bash.
STEP [6]: Iniciar el launch del sandbox offline.
STEP [7]: Propagar el exit code real del launch.
STEP [8]: Cerrar procesos hijos ante SIGINT/SIGTERM.
DOC

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# STEP [1]: Exigir WSL.
if [ ! -f /proc/sys/kernel/osrelease ] || ! grep -qi "microsoft" /proc/sys/kernel/osrelease; then
  echo "@OUTPUT: ERROR este wrapper debe ejecutarse dentro de WSL (osrelease no contiene 'microsoft')."
  exit 1
fi

# STEP [2]: Aislamiento de red ROS.
export ROS_LOCALHOST_ONLY=1

# STEP [3]: Domain ID dedicado, nunca 0.
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
if [ "${ROS_DOMAIN_ID}" = "0" ]; then
  echo "@OUTPUT: ERROR ROS_DOMAIN_ID=0 no esta permitido en el sandbox offline. Use un valor dedicado (ej. 77)."
  exit 1
fi
export ROS_DOMAIN_ID

echo "@CONTEXT: ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY} ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"

# STEP [4]: Verificador de aislamiento en modo runtime.
ISOLATION_CHECKER="${CODE_ROOT}/tools/hil/offline_navigation/verify_sandbox_isolation.py"
if [ ! -f "${ISOLATION_CHECKER}" ]; then
  echo "@OUTPUT: ERROR verificador de aislamiento no encontrado en ${ISOLATION_CHECKER}"
  exit 1
fi

if ! python3 "${ISOLATION_CHECKER}" --runtime; then
  echo "@OUTPUT: ERROR el verificador de aislamiento runtime reporto FAIL. Abortando antes de iniciar ROS."
  exit 2
fi

# STEP [5]: Activar ROS 2 jazzy.
if [ ! -f /opt/ros/jazzy/setup.bash ]; then
  echo "@OUTPUT: ERROR /opt/ros/jazzy/setup.bash no encontrado."
  exit 1
fi
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash

LAUNCH_FILE="${CODE_ROOT}/launch/offline_nav_sandbox.launch.py"
if [ ! -f "${LAUNCH_FILE}" ]; then
  echo "@OUTPUT: ERROR launch file no encontrado en ${LAUNCH_FILE}"
  exit 1
fi

# STEP [8]: Limpieza de procesos hijos ante interrupcion.
LAUNCH_PID=""
cleanup() {
  if [ -n "${LAUNCH_PID}" ] && kill -0 "${LAUNCH_PID}" >/dev/null 2>&1; then
    kill -INT "${LAUNCH_PID}" >/dev/null 2>&1 || true
    wait "${LAUNCH_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

# STEP [6]: Iniciar el launch del sandbox offline.
ros2 launch "${LAUNCH_FILE}" "$@" &
LAUNCH_PID="$!"

wait "${LAUNCH_PID}"
LAUNCH_EXIT_CODE="$?"

# STEP [7]: Propagar exit code real.
exit "${LAUNCH_EXIT_CODE}"
