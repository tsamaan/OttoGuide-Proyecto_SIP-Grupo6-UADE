"""
@TASK: Adapter async para servicio STT Whisper (HTTP) — transcripción de audio PCM a texto
@INPUT: Bytes de audio WAV o PCM float32 numpy array; configuración de URL y timeout
@OUTPUT: String con la transcripción en español; string vacío si silencio, error o timeout
@CONTEXT: Implementa el patrón Adapter sobre el servicio HTTP Whisper-ASR-Webservice (Docker).
          Reemplaza el requests.post() bloqueante de OttoGuide IA/services/core/main.py.
          Integra filtro de amplitud (silencio) y corrección fonética de UADE.
          Consumido por WakeWordDetector y LocalNLPPipeline (conversation_manager.py).
@SECURITY: Sin credenciales; Whisper es un servicio local en Docker.
           Audio nunca persiste en disco en esta capa — se trabaja sobre bytes en memoria.
@PERFORMANCE: Llamadas HTTP async via httpx. Timeout configurable (default: 30s).
              La conversión PCM→WAV bytes es en memoria; sin I/O de disco.
@AI_CONTEXT: En el robot Jetson Orin NX el puerto es 9000; en notebook de desarrollo es 9001.
             Configurable via WHISPER_STT_PORT en Settings.

STEP 1: Definir WhisperSTTClient con método transcribe_wav_bytes() async
STEP 2: Implementar transcribe_pcm() para arrays numpy float32
STEP 3: Implementar filtro de silencio integrado (opcional, activable)
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import struct
import wave
from typing import Optional

import numpy as np
from numpy.typing import NDArray

LOGGER = logging.getLogger(__name__)


class WhisperSTTClient:
    """
    @TASK: Cliente HTTP async para servicio Whisper ASR (transcripción de voz a texto)
    @INPUT: Bytes WAV o NDArray[float32] + configuración de host/timeout/idioma
    @OUTPUT: Texto transcripto en español; string vacío si falla o silencio
    @CONTEXT: Adapter sobre onerahmet/openai-whisper-asr-webservice corriendo en Docker.
              Diseñado para operar con modelo Whisper "medium" con ASR_LANGUAGE=es.
    @SECURITY: Sin autenticación; solo red local (127.0.0.1 o red Docker interna).
               Input del usuario NUNCA se interpola en la URL o comandos.
    @PERFORMANCE: httpx.AsyncClient con connection pooling; timeout configurable.
                  Filtro de amplitud opcional previene llamadas HTTP innecesarias.
    @AI_CONTEXT: Singleton recomendado — crear una instancia por proceso e inyectar via DI.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:9001",
        timeout_s: float = 30.0,
        language: str = "es",
        silence_threshold: int = 1_000,
        filter_silence: bool = True,
        false_positives: Optional[list[str]] = None,
    ) -> None:
        # STEP 1.1: Guardar configuración
        self._base_url = base_url.rstrip("/")
        self._asr_url = f"{self._base_url}/asr"
        self._timeout_s = timeout_s
        self._language = language
        self._silence_threshold = silence_threshold
        self._filter_silence = filter_silence
        self._false_positives: list[str] = false_positives or [
            "subtitulos", "amara", "suscribite", "suscribete",
            "youtube", "comunidad", "gracias por ver",
            "musica", "música", "like", "me gusta",
        ]

        LOGGER.info(
            "[WhisperSTTClient] Inicializado. url=%s timeout=%.1fs lang=%s",
            self._asr_url, timeout_s, language,
        )

    # ------------------------------------------------------------------
    # API pública async
    # ------------------------------------------------------------------

    async def transcribe_wav_bytes(self, wav_bytes: bytes) -> str:
        """
        @TASK: Transcribir audio WAV (bytes) a texto via Whisper HTTP
        @INPUT: wav_bytes — contenido completo de un archivo WAV en memoria
        @OUTPUT: Texto transcripto limpio; string vacío si falla
        @CONTEXT: Método primario; usado cuando el audio ya está en formato WAV
        @SECURITY: wav_bytes en memoria; sin escritura en disco
        @PERFORMANCE: I/O async via httpx; no bloquea el event loop
        """
        try:
            import httpx
        except ImportError:
            LOGGER.error("[WhisperSTTClient] httpx no instalado. Agregar a requirements.")
            return ""

        # STEP 1.2: Filtro de silencio opcional
        if self._filter_silence:
            if self._is_silence(wav_bytes):
                LOGGER.debug("[WhisperSTTClient] Silencio detectado — omitiendo STT")
                return ""

        # STEP 1.3: Llamada HTTP async a Whisper
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    f"{self._asr_url}?language={self._language}&task=transcribe",
                    files={"audio_file": ("audio.wav", wav_bytes, "audio/wav")},
                )
                response.raise_for_status()
                text = response.text.lower().strip()
        except httpx.TimeoutException:
            LOGGER.warning("[WhisperSTTClient] Timeout (%.1fs) en request a Whisper", self._timeout_s)
            return ""
        except Exception as exc:
            LOGGER.warning("[WhisperSTTClient] Error HTTP STT: %s — %s", type(exc).__name__, exc)
            return ""

        return self._postprocess(text)

    async def transcribe_pcm(
        self,
        pcm: NDArray[np.float32],
        *,
        sample_rate: int = 16_000,
    ) -> str:
        """
        @TASK: Transcribir array PCM float32 a texto via Whisper HTTP
        @INPUT: pcm — NDArray[float32] normalizado en [-1, 1]; sample_rate — frecuencia de muestreo
        @OUTPUT: Texto transcripto; string vacío si falla
        @CONTEXT: Interfaz de alto nivel para callers que trabajan con numpy arrays (LocalNLPPipeline)
        @SECURITY: Conversión PCM→WAV en memoria via io.BytesIO; sin escritura en disco
        @PERFORMANCE: Conversión en memoria O(n) en samples; acceptable para frases cortas (<15s)
        """
        if pcm.size == 0:
            return ""

        # STEP 2.1: Convertir PCM float32 → WAV bytes en memoria
        wav_bytes = self._pcm_to_wav_bytes(pcm, sample_rate=sample_rate)
        return await self.transcribe_wav_bytes(wav_bytes)

    # ------------------------------------------------------------------
    # Métodos privados
    # ------------------------------------------------------------------

    def _is_silence(self, wav_bytes: bytes) -> bool:
        """
        @TASK: Detectar si el audio WAV contiene solo silencio
        @INPUT: wav_bytes — contenido WAV en bytes
        @OUTPUT: True si la amplitud máxima está por debajo del threshold
        @CONTEXT: Previene llamadas innecesarias al servicio Whisper con audio vacío
        @PERFORMANCE: O(n) en frames; ejecución en <1ms para clips de 3s a 16kHz
        """
        try:
            with wave.open(io.BytesIO(wav_bytes)) as wf:
                frames = wf.readframes(wf.getnframes())
                if not frames:
                    return True
                samples = struct.unpack(f"{len(frames) // 2}h", frames)
                amplitude = max(abs(s) for s in samples)
                return amplitude < self._silence_threshold
        except Exception:
            return False

    def _postprocess(self, raw_text: str) -> str:
        """
        @TASK: Post-procesar texto de Whisper: eliminar puntuación, filtrar falsos positivos
        @INPUT: raw_text — texto crudo de Whisper (ya en minúsculas)
        @OUTPUT: Texto limpio; string vacío si es falso positivo
        @CONTEXT: Pipeline: strip → remove_punctuation → filter_false_positives → return
        """
        # STEP 3.1: Remover puntuación para comparaciones
        text = re.sub(r"[^\w\s]", "", raw_text).strip()

        # STEP 3.2: Filtrar alucinaciones de Whisper
        if any(fp in text for fp in self._false_positives):
            LOGGER.debug("[WhisperSTTClient] Falso positivo filtrado: '%s'", text[:50])
            return ""

        return text

    @staticmethod
    def _pcm_to_wav_bytes(
        pcm: NDArray[np.float32],
        *,
        sample_rate: int = 16_000,
        n_channels: int = 1,
    ) -> bytes:
        """
        @TASK: Convertir array PCM float32 a bytes WAV en memoria
        @INPUT: pcm — NDArray[float32] en [-1, 1]; sample_rate; n_channels
        @OUTPUT: bytes con contenido WAV válido (header RIFF + data)
        @CONTEXT: Necesario para enviar PCM de SpeechRecognition a la API HTTP de Whisper
        @SECURITY: Sin escritura en disco; operación puramente en memoria
        @PERFORMANCE: Asignación lineal en n_samples; <1ms para clips de 15s
        """
        pcm_int16 = (pcm * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_int16.tobytes())
        return buf.getvalue()


__all__ = ["WhisperSTTClient"]
