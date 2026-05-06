"""
@TASK: Detectar el wake word "Hola Otto" en ciclos de audio via STT remoto
@INPUT: Audio PCM capturado por arecord o SpeechRecognition; texto transcripto via WhisperSTTClient
@OUTPUT: Booleano is_detected; texto transcripto crudo para auditoría
@CONTEXT: Capa de wake-word detection del pipeline HIL. Primer eslabón de la cadena
          AudioInput -> WakeWordDetector -> ConversationManager -> TTS.
          Migrado desde OttoGuide IA/services/core/main.py (prototipo procedural).
          Integra corrección fonética de UADE via Levenshtein (distancia ≤ 2) y lista
          de variaciones manual como fallback (correcciones_uade.json).
@SECURITY: No persiste audio en disco en el path primario; archivos /tmp limpiados post-uso.
@PERFORMANCE: Ciclos de detección de 3s (configurable). Filter de silencio previene llamadas
              innecesarias al servicio Whisper.
@AI_CONTEXT: Todos los métodos bloqueantes (arecord, requests) se aíslan en run_in_executor
             para no bloquear el event loop de FastAPI/uvicorn.

STEP 1: Definir constantes de wake word y filtros de falsos positivos
STEP 2: Implementar corrección fonética de UADE (Levenshtein + fallback JSON)
STEP 3: Implementar WakeWordDetector con detección async y limpieza de /tmp
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# STEP 1: Constantes de detección
# ---------------------------------------------------------------------------

# @TASK: Definir variaciones fonéticas toleradas del wake word
# @INPUT: Ninguno
# @OUTPUT: Lista de strings aceptados como "Hola Otto"
# @CONTEXT: Whisper ES puede transcribir "Otto" como "Oto", "Auto", etc.
# @AI_CONTEXT: Lista empírica obtenida de pruebas en notebook Linux Mint
WAKE_WORDS: list[str] = [
    "hola otto", "hola oto",
    "ola otto",  "ola oto",
    "hola auto", "hola a otto",
    "hola a oto", "oto", "otto",
]

# @TASK: Definir palabras de despedida que finalizan la sesión de conversación
# @INPUT: Ninguno
# @OUTPUT: Lista de strings que activan el modo hibernación
FAREWELL_WORDS: list[str] = [
    "chau", "adios", "hasta luego",
    "listo", "eso es todo",
    "no tengo mas preguntas",
    "no tengo otra pregunta", "chao",
]

# @TASK: Definir alucinaciones conocidas de Whisper para filtrado
# @INPUT: Ninguno
# @OUTPUT: Lista de substrings que indican alucinación (no voz real)
# @CONTEXT: Whisper genera estos textos cuando recibe silencio o ruido de fondo
FALSE_POSITIVES: list[str] = [
    "subtitulos", "amara", "suscribite", "suscribete", "suscríbete",
    "youtube", "comunidad", "gracias por ver", "nos valemos",
    "se prevenden", "la edicion", "edicion", "por favor",
    "musica", "música", "like", "me gusta", "compartir", "comentarios",
]

# @TASK: Umbral de amplitud mínima para considerar voz real
# @SECURITY: Previene enviar silencio a Whisper, ahorrando recursos
SILENCE_THRESHOLD: int = 1_000

# @TASK: Patrón regex para remover emojis antes de enviar texto a TTS
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F9FF"
    "\U00002700-\U000027BF"
    "\U0001FA00-\U0001FA6F"
    "]+",
    flags=re.UNICODE,
)

# ---------------------------------------------------------------------------
# STEP 2: Corrección fonética de UADE
# ---------------------------------------------------------------------------

def _levenshtein_distance(a: str, b: str) -> int:
    """
    @TASK: Calcular distancia de Levenshtein entre dos strings
    @INPUT: a, b — strings a comparar
    @OUTPUT: Número entero de operaciones mínimas (inserción/eliminación/sustitución)
    @CONTEXT: Usado para detectar variaciones fonéticas de "uade" con tolerancia ≤ 2
    @PERFORMANCE: O(m*n) en tiempo y espacio; aceptable para palabras cortas (≤ 10 chars)
    """
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]


def _is_similar_to_uade(word: str) -> bool:
    """
    @TASK: Detectar si una palabra es fonéticamente similar a "UADE"
    @INPUT: word — string a evaluar (normalizado a minúsculas)
    @OUTPUT: True si Levenshtein("uade", word) ≤ 2
    @CONTEXT: Cubre variaciones como "guadi", "huade", "wady", "uadee", etc.
    @AI_CONTEXT: Umbral 2 elegido empíricamente; 3 genera falsos positivos frecuentes
    """
    target = "uade"
    p = word.lower()
    if p == target:
        return True
    if len(p) < 3 or len(p) > 7:
        return False
    return _levenshtein_distance(target, p) <= 2


def correct_uade_transcription(text: str, *, fallback_map: Optional[dict[str, str]] = None) -> str:
    """
    @TASK: Corregir variaciones fonéticas de "UADE" en el texto transcripto
    @INPUT: text — string crudo de Whisper; fallback_map — dict de correcciones manuales (opcional)
    @OUTPUT: Texto con variaciones de UADE reemplazadas por la sigla correcta
    @CONTEXT: Método primario: Levenshtein. Método alternativo: fallback_map (correcciones_uade.json)
    @AI_CONTEXT: El fallback_map se activa si el módulo detecta que Levenshtein genera falsos positivos
    """
    words = text.split()
    corrected: list[str] = []
    for word in words:
        clean = re.sub(r"[^\w]", "", word.lower())
        if fallback_map and clean in fallback_map:
            corrected.append(fallback_map[clean])
        elif _is_similar_to_uade(clean):
            corrected.append("UADE")
        else:
            corrected.append(word)
    return " ".join(corrected)


def clean_text_for_tts(text: str) -> str:
    """
    @TASK: Limpiar texto para síntesis de voz: remover emojis, normalizar puntuación
    @INPUT: text — string crudo del LLM
    @OUTPUT: Texto limpio, sin emojis, con pausas naturales para Piper/TtsMaker
    @CONTEXT: Piper y AudioClient.TtsMaker fallan o leen mal emojis y caracteres especiales
    @SECURITY: Sin side effects; operación pura en memoria
    """
    text = EMOJI_PATTERN.sub("", text)
    text = text.replace('"', "'").replace("`", "'")
    text = text.replace("\n", " ").replace("\r", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\. ([A-Z])", r". \1", text)
    text = text.replace("...", ",")
    words = text.split()
    if len(words) > 15:
        mid = len(words) // 2
        words.insert(mid, ",")
        text = " ".join(words)
    return text


# ---------------------------------------------------------------------------
# STEP 3: WakeWordDetector
# ---------------------------------------------------------------------------

class WakeWordDetector:
    """
    @TASK: Detectar el wake word "Hola Otto" en ciclos de audio via STT Whisper
    @INPUT: Configuración de micrófono (device, channels, sample_rate) y URL de Whisper STT
    @OUTPUT: Método detect_cycle() retorna (is_wake_word: bool, transcript: str)
    @CONTEXT: Consumido por el pipeline de interacción en modo hibernación.
              Reemplaza el while-True procedural de OttoGuide IA/services/core/main.py.
              Toda I/O bloqueante (subprocess.run) se ejecuta en run_in_executor.
    @SECURITY: Archivos /tmp con nombres únicos (tempfile) para evitar colisiones.
               arecord es un proceso externo; no se interpola input del usuario.
    @PERFORMANCE: Ciclos de 3s por defecto. Filtro de silencio previene llamadas HTTP a Whisper.
    @AI_CONTEXT: Diseñado para operar en Jetson Orin NX con array de 4 micrófonos (plughw:0,0)
                 y en notebook de desarrollo (plughw:1,0). Configurable via Settings.
    """

    def __init__(
        self,
        *,
        stt_url: str = "http://localhost:9001/asr",
        mic_device: str = "plughw:1,0",
        mic_channels: str = "1",
        sample_rate: int = 16_000,
        cycle_duration_s: int = 3,
        silence_threshold: int = SILENCE_THRESHOLD,
        wake_words: Optional[list[str]] = None,
        false_positives: Optional[list[str]] = None,
        uade_fallback_map: Optional[dict[str, str]] = None,
    ) -> None:
        # STEP 3.1: Guardar configuración
        self._stt_url = stt_url
        self._mic_device = mic_device
        self._mic_channels = mic_channels
        self._sample_rate = sample_rate
        self._cycle_duration_s = cycle_duration_s
        self._silence_threshold = silence_threshold
        self._wake_words: list[str] = wake_words or WAKE_WORDS
        self._false_positives: list[str] = false_positives or FALSE_POSITIVES
        self._uade_fallback_map: Optional[dict[str, str]] = uade_fallback_map

        LOGGER.info(
            "[WakeWordDetector] Inicializado. stt_url=%s mic=%s cycle=%ds",
            stt_url, mic_device, cycle_duration_s,
        )

    # ------------------------------------------------------------------
    # API pública async
    # ------------------------------------------------------------------

    async def detect_cycle(self) -> tuple[bool, str]:
        """
        @TASK: Ejecutar un ciclo completo de detección: grabar → transcribir → evaluar
        @INPUT: Sin parámetros (usa configuración de la instancia)
        @OUTPUT: Tuple (is_wake_word: bool, transcript: str)
        @CONTEXT: Llamar en loop desde el pipeline de hibernación
        @SECURITY: Archivo temporal con nombre único (mkstemp); eliminado en finally
        @PERFORMANCE: Toda I/O en run_in_executor para no bloquear el event loop
        """
        loop = asyncio.get_running_loop()

        # STEP 3.2: Crear archivo temporal único
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="otto_wake_")
        os.close(fd)

        try:
            # STEP 3.3: Grabar audio en executor
            await loop.run_in_executor(
                None,
                self._record_audio,
                self._cycle_duration_s,
                tmp_path,
            )

            # STEP 3.4: Transcribir en executor
            transcript = await loop.run_in_executor(
                None,
                self._transcribe,
                tmp_path,
            )

            if not transcript:
                return False, ""

            # STEP 3.5: Descartar frases largas (wake word es siempre corto)
            if len(transcript.split()) > 4:
                LOGGER.debug("[WakeWordDetector] Descartado por longitud: '%s'", transcript)
                return False, transcript

            is_wake = self._is_wake_word(transcript)
            LOGGER.debug("[WakeWordDetector] transcript='%s' is_wake=%s", transcript, is_wake)
            return is_wake, transcript

        finally:
            # STEP 3.6: Limpiar archivo temporal
            # @SECURITY: Cleanup garantizado independientemente del resultado
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    async def is_farewell(self, text: str) -> bool:
        """
        @TASK: Verificar si el texto contiene palabra de despedida
        @INPUT: text — transcripción del usuario
        @OUTPUT: True si se detecta despedida
        @CONTEXT: Llamar después de cada respuesta del LLM para saber si continuar
        """
        text_lower = text.lower()
        return any(d in text_lower for d in FAREWELL_WORDS)

    # ------------------------------------------------------------------
    # Métodos síncronos (ejecutados en executor)
    # ------------------------------------------------------------------

    def _record_audio(self, duration_s: int, path: str) -> None:
        """
        @TASK: Grabar audio del micrófono via arecord y guardar en path
        @INPUT: duration_s — duración en segundos; path — ruta del archivo WAV de salida
        @OUTPUT: Archivo WAV creado en path
        @CONTEXT: arecord es parte del stack ALSA de Linux; disponible en Jetson Orin y notebook
        @SECURITY: path proviene de tempfile.mkstemp — sin interpolación de input de usuario
        @PERFORMANCE: Bloqueante; debe ejecutarse en run_in_executor
        """
        subprocess.run(
            [
                "arecord",
                "-d", str(duration_s),
                "-D", self._mic_device,
                "-f", "S16_LE",
                "-c", self._mic_channels,
                "-r", str(self._sample_rate),
                path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,  # No lanzar excepción si arecord no está disponible
        )

    def _transcribe(self, path: str) -> str:
        """
        @TASK: Verificar que hay voz real y transcribir via Whisper HTTP
        @INPUT: path — ruta del archivo WAV grabado
        @OUTPUT: Texto transcripto limpio y corregido; string vacío si silencio o error
        @CONTEXT: Pipeline: amplitud → Whisper → filtro falsos positivos → corrección UADE
        @SECURITY: Archivo WAV nunca enviado a servicios externos; Whisper es local (Docker)
        @PERFORMANCE: Timeout de 30s al servicio Whisper; bloqueante → ejecutar en executor
        """
        import requests  # lazy import — no disponible en CI sin la dependencia

        # STEP 3.a: Verificar amplitud (filtro de silencio)
        try:
            with wave.open(path, "rb") as wf:
                frames = wf.readframes(wf.getnframes())
                if not frames:
                    return ""
                samples = struct.unpack(f"{len(frames) // 2}h", frames)
                amplitude = max(abs(s) for s in samples)
                if amplitude < self._silence_threshold:
                    LOGGER.debug("[WakeWordDetector] Silencio detectado (amp=%d)", amplitude)
                    return ""
        except Exception as exc:
            LOGGER.warning("[WakeWordDetector] Error leyendo WAV: %s", exc)
            return ""

        # STEP 3.b: Enviar a Whisper STT
        try:
            with open(path, "rb") as f:
                response = requests.post(
                    f"{self._stt_url}?language=es&task=transcribe",
                    files={"audio_file": f},
                    timeout=30,
                )
            text = response.text.lower().strip()
            text = re.sub(r"[^\w\s]", "", text)
        except Exception as exc:
            LOGGER.warning("[WakeWordDetector] Error en STT HTTP: %s", exc)
            return ""

        # STEP 3.c: Filtrar alucinaciones de Whisper
        if any(fp in text for fp in self._false_positives):
            LOGGER.debug("[WakeWordDetector] Falso positivo filtrado: '%s'", text[:50])
            return ""

        # STEP 3.d: Corregir variaciones fonéticas de UADE
        text = correct_uade_transcription(text, fallback_map=self._uade_fallback_map)
        return text

    def _is_wake_word(self, text: str) -> bool:
        """
        @TASK: Verificar si el texto contiene el wake word
        @INPUT: text — string transcripto (ya normalizado a minúsculas)
        @OUTPUT: True si alguna variación de "Hola Otto" está presente
        """
        return any(w in text for w in self._wake_words)


def load_uade_corrections(json_path: Optional[Path] = None) -> dict[str, str]:
    """
    @TASK: Cargar diccionario de correcciones fonéticas de UADE desde JSON
    @INPUT: json_path — ruta al archivo correcciones_uade.json (default: data/correcciones_uade.json)
    @OUTPUT: Dict {variacion: "UADE"} para uso como fallback_map en WakeWordDetector
    @CONTEXT: Usado cuando UADE_CORRECTION_MODE=manual en Settings
    @SECURITY: Archivo local; sin llamadas de red
    """
    if json_path is None:
        json_path = Path(__file__).resolve().parent.parent.parent / "data" / "correcciones_uade.json"

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("correcciones", {})
    except Exception as exc:
        LOGGER.warning("[WakeWordDetector] No se pudo cargar correcciones_uade.json: %s", exc)
        return {}


__all__ = [
    "WakeWordDetector",
    "clean_text_for_tts",
    "correct_uade_transcription",
    "load_uade_corrections",
    "WAKE_WORDS",
    "FAREWELL_WORDS",
    "FALSE_POSITIVES",
]
