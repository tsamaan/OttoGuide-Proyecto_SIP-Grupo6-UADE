#!/usr/bin/env bash
# WEB-HIL-R1 — discover_companion_python.sh
# Descubre, en el Companion, un interprete Python que pueda importar REALMENTE
# fastapi, uvicorn, cyclonedds y unitree_sdk2py. No basta find_spec para
# CycloneDDS (puede resolver el paquete y fallar igual al cargar libddsc): se
# hace un import real de cada modulo.
#
# Orden de candidatos:
#   1. OTTOGUIDE_PYBIN explicito (env var), si existe y pasa la verificacion.
#   2. /home/unitree/.venvs/ottoguide-final-r1a/bin/python3 (venv conocido de
#      una validacion fisica anterior; NO se asume como autoridad permanente,
#      es solo un candidato mas en la lista).
#   3. Otros venvs bajo /home/unitree (busca pyvenv.cfg).
#   4. python3 del sistema.
#
# No instala nada. Devuelve por stdout UNICAMENTE el path del interprete que
# pasa todas las verificaciones, o sale con codigo != 0 si ninguno pasa.
#
# Uso:
#   ./discover_companion_python.sh [--sdk-path <path>]
set -uo pipefail

SDK_PATH_HINT=""
if [ "${1:-}" = "--sdk-path" ] && [ -n "${2:-}" ]; then
  SDK_PATH_HINT="$2"
fi

check_candidate() {
  local py="$1"
  [ -x "$py" ] || return 1
  # Import real (no find_spec) de fastapi/uvicorn/cyclonedds; cyclonedds debe
  # cargar su binding nativo (libddsc) para contar como disponible de verdad.
  "$py" - "$SDK_PATH_HINT" <<'PY' >/dev/null 2>&1
import sys
sdk_hint = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    import fastapi  # noqa
    import uvicorn  # noqa
    import cyclonedds  # noqa
    from cyclonedds.domain import DomainParticipant  # noqa - fuerza carga del binding nativo
except Exception:
    sys.exit(1)

# unitree_sdk2py: puede requerir resolver la ruta del SDK dinamicamente.
import importlib.util, os, glob
if importlib.util.find_spec("unitree_sdk2py") is not None:
    sys.exit(0)
cands = []
if sdk_hint:
    cands.append(sdk_hint)
cands += ["/home/unitree/unitree_sdk2_python",
          "/home/unitree/ottoguide/codigo ottoguide/libs/unitree_sdk2_python"]
cands += sorted(glob.glob("/home/unitree/ottoguide_deployments/*/codigo ottoguide/libs/unitree_sdk2_python"))
cands += sorted(glob.glob("/home/unitree/**/unitree_sdk2_python", recursive=True))
for c in cands:
    if c and os.path.isdir(os.path.join(c, "unitree_sdk2py")):
        sys.path.insert(0, c)
        try:
            import unitree_sdk2py  # noqa
            sys.exit(0)
        except Exception:
            continue
sys.exit(1)
PY
}

CANDIDATES=()
[ -n "${OTTOGUIDE_PYBIN:-}" ] && CANDIDATES+=("$OTTOGUIDE_PYBIN")
# Candidato conocido de una validacion fisica anterior (NO autoridad permanente,
# solo un item mas en la lista de candidatos; ver companion_runtime_manifest.json).
CANDIDATES+=("/home/unitree/.venvs/ottoguide-final-r1a/bin/python3")
while IFS= read -r cfg; do
  d="$(dirname "$cfg")"
  [ -x "$d/bin/python3" ] && CANDIDATES+=("$d/bin/python3")
  [ -x "$d/bin/python" ] && CANDIDATES+=("$d/bin/python")
done < <(find /home/unitree -maxdepth 6 -name pyvenv.cfg 2>/dev/null)
for c in python3 python; do
  p="$(command -v "$c" 2>/dev/null || true)"
  [ -n "$p" ] && CANDIDATES+=("$p")
done

for c in "${CANDIDATES[@]}"; do
  if check_candidate "$c"; then
    echo "$c"
    exit 0
  fi
done

echo "discover_companion_python: ningun interprete paso fastapi+uvicorn+cyclonedds(import real)+unitree_sdk2py" >&2
exit 4
