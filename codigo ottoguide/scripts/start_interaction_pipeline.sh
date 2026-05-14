#!/usr/bin/env bash
# @TASK: Script de orquestación del pipeline completo de interacción OttoGuide
# @INPUT: Variables de entorno ROBOT_MODE, WHISPER_STT_PORT, OLLAMA_OTTO_MODEL, etc.
# @OUTPUT: Stack Docker levantado + modelo otto registrado en Ollama + backend Python activo
# @CONTEXT: Punto de entrada unificado para modo desarrollo (notebook) y modo robot (HIL).
#           Reemplaza el docker-compose de OttoGuide IA/ y el script start_interaction_mvp.sh.
#           STEP 1: Verificar dependencias (docker, arecord, python3)
#           STEP 2: Levantar servicios Docker (llm + stt + tts)
#           STEP 3: Esperar que Ollama esté disponible
#           STEP 4: Registrar modelo otto si no existe
#           STEP 5: Lanzar el backend principal (python main.py)
# @SECURITY: Sin variables hardcodeadas; todo via env vars con defaults seguros.
# @AI_CONTEXT: En robot HIL (ROBOT_MODE=real) el step TTS Docker es opcional —
#              AudioClient.TtsMaker() del SDK no requiere el contenedor ottoguide-tts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ─── Configuración con defaults ───────────────────────────────────────────────
ROBOT_MODE="${ROBOT_MODE:-mock}"
OLLAMA_OTTO_MODEL="${OLLAMA_OTTO_MODEL:-otto}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
WHISPER_STT_PORT="${WHISPER_STT_PORT:-9001}"
MODELFILE_PATH="${PROJECT_ROOT}/data/llm/Modelfile"
DOCKER_COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yml"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " OttoGuide — Interaction Pipeline Startup"
echo " ROBOT_MODE     : ${ROBOT_MODE}"
echo " OLLAMA_MODEL   : ${OLLAMA_OTTO_MODEL}"
echo " WHISPER_PORT   : ${WHISPER_STT_PORT}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── STEP 1: Verificar dependencias ───────────────────────────────────────────
echo "[STEP 1] Verificando dependencias..."
for cmd in docker python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "[ERROR] '$cmd' no encontrado en PATH. Abortando."
        exit 1
    fi
done
# arecord es opcional en modo mock (no hay hardware de audio)
if [[ "$ROBOT_MODE" != "mock" ]] && ! command -v arecord &>/dev/null; then
    echo "[WARN] 'arecord' no disponible. El wake word detector no funcionará sin ALSA."
fi
echo "[STEP 1] OK"

# ─── STEP 2: Levantar servicios Docker ────────────────────────────────────────
echo "[STEP 2] Levantando stack Docker (llm + stt + tts)..."
# @SECURITY: --no-recreate previene interrupciones si los contenedores ya están corriendo
docker compose -f "$DOCKER_COMPOSE_FILE" up -d llm stt tts --no-recreate
echo "[STEP 2] OK — contenedores iniciados"

# ─── STEP 3: Esperar que Ollama esté listo ────────────────────────────────────
echo "[STEP 3] Esperando que Ollama esté disponible en ${OLLAMA_HOST}..."
MAX_RETRIES=30
RETRY=0
until curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; do
    RETRY=$((RETRY + 1))
    if [[ $RETRY -ge $MAX_RETRIES ]]; then
        echo "[ERROR] Ollama no respondió después de ${MAX_RETRIES} intentos. Abortando."
        exit 1
    fi
    echo "[STEP 3] Esperando... (intento ${RETRY}/${MAX_RETRIES})"
    sleep 2
done
echo "[STEP 3] OK — Ollama disponible"

# ─── STEP 4: Registrar modelo otto en Ollama ──────────────────────────────────
echo "[STEP 4] Verificando modelo '${OLLAMA_OTTO_MODEL}' en Ollama..."
if ! curl -sf "${OLLAMA_HOST}/api/tags" | grep -q "\"${OLLAMA_OTTO_MODEL}\""; then
    if [[ -f "$MODELFILE_PATH" ]]; then
        echo "[STEP 4] Creando modelo '${OLLAMA_OTTO_MODEL}' desde ${MODELFILE_PATH}..."
        # @SECURITY: Modelfile es un archivo local del repo; sin input de usuario
        ollama create "${OLLAMA_OTTO_MODEL}" -f "$MODELFILE_PATH"
        echo "[STEP 4] Modelo creado correctamente"
    else
        echo "[WARN] Modelfile no encontrado en ${MODELFILE_PATH}. El modelo 'otto' no estará disponible."
        echo "[WARN] Usando modelo fallback: ${OLLAMA_MODEL:-qwen2.5:3b}"
    fi
else
    echo "[STEP 4] Modelo '${OLLAMA_OTTO_MODEL}' ya existe — omitiendo creación"
fi

# ─── STEP 5: Lanzar backend principal ─────────────────────────────────────────
echo "[STEP 5] Lanzando OttoGuide backend (python main.py)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cd "$PROJECT_ROOT"
exec python3 main.py
