#!/usr/bin/env bash
# Fase 2H.2.4 -- P0 PHYSICAL READ-ONLY evidence collector (shell wrapper).
#
# STATUS: PREPARED_NOT_AUTHORIZED / NOT_EXECUTED.
#
# Minimal wrapper only: resolves its own directory safely, verifies a
# python3 interpreter is on PATH, and execs straight into
# collect_p0_readonly_evidence.py -- which holds every guard, every gate,
# and every line of introspection logic. This wrapper never builds a
# shell command string, never uses eval, and never branches on its
# arguments; it only forwards "$@" verbatim to the Python core.
#
# This script carries no remote-shell, no remote-copy, no hard-coded
# network address, and no remote-connection logic: it never reaches out
# to a robot, it is meant to already be running on one. It is strictly
# INTROSPECTION-ONLY by construction (see the Python core's own
# docstring), in every one of its modes (--dry-run, --execute-read-only,
# --fixture-dir).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
CORE_PY="${SCRIPT_DIR}/collect_p0_readonly_evidence.py"

if [[ ! -f "${CORE_PY}" ]]; then
  echo "P0_COLLECTOR_CORE_MISSING:${CORE_PY}" >&2
  exit 3
fi

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "PYTHON3_NOT_FOUND" >&2
  exit 3
fi

exec "${PYTHON_BIN}" "${CORE_PY}" "$@"
