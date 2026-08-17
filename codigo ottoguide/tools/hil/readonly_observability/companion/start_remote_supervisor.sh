#!/usr/bin/env bash
# NB-HIL-WEB-R0 FASE P — launcher remoto del supervisor (corre en el Companion).
# Desacopla la observabilidad de la sesion SSH: prefiere systemd-run --user; si no hay,
# cae a setsid+nohup con stdin=/dev/null y stdout/stderr a archivos.
# READ-ONLY: NO detiene procesos factory, NO crea writers DDS, NO ordena movimiento.
set -euo pipefail

REMOTE_RUN_ROOT="${1:?uso: start_remote_supervisor.sh <REMOTE_RUN_ROOT> <SESSION_ID> [--enable-bms]}"
SESSION_ID="${2:?falta SESSION_ID}"
ENABLE_BMS="${3:-}"

RUNTIME_DIR="$REMOTE_RUN_ROOT/remote_runtime"
mkdir -p "$REMOTE_RUN_ROOT"

# Detectar python compatible (>=3.8) sin asumir ruta historica.
PYBIN=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PYBIN="$(command -v "$c")"; break; fi
done
[ -n "$PYBIN" ] || { echo "no python found" >&2; exit 4; }

# NB-HIL-CONN-R1: override explicito del interprete via OTTOGUIDE_PYBIN (venv resuelto en
# preflight con cyclonedds/fastapi/uvicorn). Prioridad maxima si es ejecutable.
if [ -n "${OTTOGUIDE_PYBIN:-}" ] && [ -x "${OTTOGUIDE_PYBIN}" ]; then
  PYBIN="${OTTOGUIDE_PYBIN}"
else
  # venv del deployment si existe (detectar dinamicamente, sin asumir).
  for v in "$REMOTE_RUN_ROOT/venv/bin/python" /home/unitree/.venvs/*/bin/python3 /home/unitree/*/venv/bin/python; do
    [ -x "$v" ] && { PYBIN="$v"; break; }
  done
fi
echo "[remote] python=$PYBIN"

SUP="$RUNTIME_DIR/ottoguide_observability_supervisor.py"
ARGS=(--out "$REMOTE_RUN_ROOT" --session "$SESSION_ID" --python "$PYBIN")
[ "$ENABLE_BMS" = "--enable-bms" ] && ARGS+=(--enable-bms)

LOG="$REMOTE_RUN_ROOT/supervisor.boot.log"
launched=""

# NB-HIL-CONN-R1: systemd-run --user solo es DURABLE si el usuario tiene linger habilitado;
# sin linger, la unit transitoria se destruye al cerrar la ultima sesion SSH (matando
# recorder/bridge tras el deploy). Por eso SOLO se usa systemd-run cuando linger=yes;
# de lo contrario, setsid+nohup (reparentado a init, sobrevive el cierre de SSH).
linger="no"
if command -v loginctl >/dev/null 2>&1; then
  linger="$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo no)"
fi
if command -v systemd-run >/dev/null 2>&1 && [ "$linger" = "yes" ]; then
  echo "[remote] linger=yes -> intentando systemd-run --user ..."
  if systemd-run --user --unit="ottoguide-observability-$SESSION_ID" \
       --setenv=OTTOGUIDE_SDK_PATH="${OTTOGUIDE_SDK_PATH:-}" \
       --setenv=OTTOGUIDE_PYBIN="${OTTOGUIDE_PYBIN:-}" \
       "$PYBIN" "$SUP" "${ARGS[@]}" >>"$LOG" 2>&1; then
    launched="systemd-run"
    echo "[remote] lanzado via systemd-run --user (unit=ottoguide-observability-$SESSION_ID)"
  else
    echo "[remote] systemd-run --user FALLO (rc=$?); usando fallback setsid+nohup"
  fi
else
  echo "[remote] linger=$linger -> se omite systemd-run; se usa setsid+nohup durable"
fi

if [ -z "$launched" ]; then
  setsid nohup "$PYBIN" "$SUP" "${ARGS[@]}" </dev/null >>"$LOG" 2>&1 &
  echo "[remote] supervisor pid=$! (setsid+nohup, desacoplado; log: $LOG)"
  launched="nohup"
fi

echo "[remote] LISTO ($launched). La captura sobrevive al cierre de SSH."
