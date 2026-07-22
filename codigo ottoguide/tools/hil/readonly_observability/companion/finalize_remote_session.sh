#!/usr/bin/env bash
# NB-HIL-WEB-R0A FASE J — cierre limpio de la sesion remota (corre en el Companion).
# Lee PIDs exactos, valida command lines, envia SIGTERM, espera cierre, confirma chunks
# cerrados, genera manifiesto + hashes, registra faltantes y PRESERVA todo el run root.
# NO borra datos. NO detiene procesos factory (solo los PIDs registrados de esta sesion).
set -uo pipefail

REMOTE_RUN_ROOT="${1:?uso: finalize_remote_session.sh <REMOTE_RUN_ROOT> [grace_s]}"
GRACE="${2:-12}"
PIDS_JSON="$REMOTE_RUN_ROOT/pids.json"
LOG="$REMOTE_RUN_ROOT/finalize.log"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

log "finalize start (grace=${GRACE}s) run_root=$REMOTE_RUN_ROOT"

# --- 1/2: leer PIDs exactos y validar command line antes de senalar ---
term_pid() {
  local name="$1" pid="$2" match="$3"
  [ -n "$pid" ] && [ "$pid" != "null" ] || { log "$name: sin pid"; return; }
  if [ ! -e "/proc/$pid" ]; then log "$name pid=$pid ya no existe"; return; fi
  local cmd; cmd="$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null)"
  if ! echo "$cmd" | grep -q "$match"; then
    log "$name pid=$pid NO coincide ('$cmd' !~ '$match') -> NO se senala (seguridad)"
    return
  fi
  log "SIGTERM -> $name pid=$pid"
  kill -TERM "$pid" 2>/dev/null || true
}

if [ -f "$PIDS_JSON" ]; then
  SUP=$(grep -oE '"supervisor"[: ]+[0-9]+' "$PIDS_JSON" | grep -oE '[0-9]+' | head -1)
  REC=$(grep -oE '"recorder"[: ]+[0-9]+' "$PIDS_JSON" | grep -oE '[0-9]+' | head -1)
  BRG=$(grep -oE '"bridge"[: ]+[0-9]+' "$PIDS_JSON" | grep -oE '[0-9]+' | head -1)
  # 3: SIGTERM a supervisor primero (el propaga a sus hijos), luego a los hijos por si acaso.
  term_pid supervisor "$SUP" "ottoguide_observability_supervisor"
  term_pid recorder  "$REC" "ottoguide_remote_recorder"
  term_pid bridge    "$BRG" "ottoguide_readonly_bridge"
else
  log "sin pids.json; no se puede senalar por PID exacto"
fi

# --- 4: esperar cierre acotado ---
deadline=$(( $(date +%s) + GRACE ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  alive=0
  for p in "$SUP" "$REC" "$BRG"; do [ -n "${p:-}" ] && [ -e "/proc/$p" ] && alive=1; done
  [ "$alive" -eq 0 ] && break
  sleep 0.5
done

# --- 5: confirmar chunks cerrados (recorder_state final) ---
REC_STATE="$REMOTE_RUN_ROOT/recorder_data/recorder_state.json"
CLEAN_SHUTDOWN=false
if [ -f "$REC_STATE" ] && grep -q '"final": true\|"final":true' "$REC_STATE"; then
  log "recorder cerro chunks (final=true)"
  CLEAN_SHUTDOWN=true
else
  log "ADVERTENCIA: recorder_state final no confirmado (revisar $REC_STATE)"
fi

# --- FASE A3 (R0B hotfix): FINALIZATION_COMPLETE.json se crea ANTES del hashing, para
# quedar incluido en el manifiesto/SHA256SUMS.txt igual que cualquier otro archivo estable.
FINALIZATION_JSON="$REMOTE_RUN_ROOT/FINALIZATION_COMPLETE.json"
{
  echo "{"
  echo "  \"completed\": true,"
  echo "  \"clean_shutdown\": $CLEAN_SHUTDOWN,"
  echo "  \"manifest_generated\": true,"
  echo "  \"remote_data_preserved\": true,"
  echo "  \"utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
  echo "}"
} > "$FINALIZATION_JSON"
log "FINALIZATION_COMPLETE.json escrito antes del hashing (clean_shutdown=$CLEAN_SHUTDOWN)"

# --- 6/7: manifiesto + hashes de TODO el run root ---
# FASE A3 (R0B hotfix): finalize.log es un log operativo MUTABLE (log() sigue escribiendo
# en el despues de este punto) -> se excluye explicitamente del hashing/manifiesto
# autoritativo. Ningun archivo incluido en el hash se modifica despues de este bloque.
MANIFEST="$REMOTE_RUN_ROOT/REMOTE_FILE_MANIFEST.json"
SUMS="$REMOTE_RUN_ROOT/SHA256SUMS.txt"
: > "$SUMS"
{
  echo "{"
  echo "  \"run_root\": \"$REMOTE_RUN_ROOT\","
  echo "  \"utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"files\": ["
  first=1
  while IFS= read -r f; do
    rel="${f#$REMOTE_RUN_ROOT/}"
    sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
    sha=$(sha256sum "$f" | awk '{print $1}')
    echo "$sha  $rel" >> "$SUMS"
    [ $first -eq 1 ] || echo ","
    first=0
    printf '    {"path": "%s", "size_bytes": %s, "sha256": "%s"}' "$rel" "$sz" "$sha"
  done < <(find "$REMOTE_RUN_ROOT" -type f \
             ! -name 'REMOTE_FILE_MANIFEST.json' ! -name 'SHA256SUMS.txt' ! -name 'finalize.log' \
           | sort)
  echo ""
  echo "  ]"
  echo "}"
} > "$MANIFEST"
log "manifiesto: $MANIFEST ; hashes: $SUMS ($(wc -l < "$SUMS") archivos; finalize.log excluido por mutable)"

# --- 8: registrar faltantes esperados (solo finalize.log, ya excluido del hash) ---
for expect in "recorder_data/recorder_state.json" "bridge_data/ws_stream.jsonl" "pids.json"; do
  [ -e "$REMOTE_RUN_ROOT/$expect" ] || log "FALTANTE esperado: $expect"
done

# --- 9/10: preservar todo; NO borrar ---
log "finalize OK. Run root PRESERVADO (no se borro nada)."
