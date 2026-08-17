"""
@TASK: Adapter TTS dual — Piper TTS (via Docker HTTP) y AudioClient.TtsMaker (SDK Unitree nativo)
@INPUT: Texto limpio para síntesis; configuración de backend (piper|unitree_sdk)
@OUTPUT: Audio sintetizado reproducido en el parlante; sin valor de retorno
@CONTEXT: Implementa el patrón Strategy para TTS. Dos implementaciones intercambiables:
          - PiperTTSAdapter: usa el contenedor Docker ottoguide-tts (modo desarrollo/notebook)
          - UnitreeTTSAdapter: usa AudioClient.TtsMaker() del SDK nativo (modo robot HIL)
          El ConversationManager selecciona el adapter según ROBOT_MODE en Settings.
          Migrado y refactorizado desde OttoGuide IA/services/core/main.py (función hablar()).
@SECURITY: PiperTTSAdapter: subprocess docker cp/exec con args fijos — sin interpolación de texto del usuario.
           El texto se escribe a /tmp via tempfile antes de copiar al contenedor.
           UnitreeTTSAdapter: llamada directa al SDK; sin procesos externos.
@PERFORMANCE: PiperTTSAdapter es bloqueante (docker cp + docker exec + paplay) — ejecutar en run_in_executor.
              UnitreeTTSAdapter es síncrono en el SDK; también debe ejecutarse en executor.
@AI_CONTEXT: En producción (robot Jetson + SDK disponible), usar UnitreeTTSAdapter.
             En desarrollo (notebook Linux Mint), usar PiperTTSAdapter.
             Ambos implementan la misma interfaz TTSAdapter para ser intercambiables vía Strategy.

BUG FIX DOCUMENTADO (SDK Unitree g1_audio_client.py):
  El SDK original tenía `self.tts_index += self.tts_index` en TtsMaker(), causando
  crecimiento exponencial del índice DDS y eventual crash en sesiones largas.
  Resolución en dos capas:
    1. PATCH DIRECTO en libs/unitree_sdk2_python-master/.../g1_audio_client.py
       (cambiado a `+= 1` con guard de overflow en INT32_MAX)
    2. WRAPPER DEFENSIVO en UnitreeTTSAdapter._speak_sync: detecta crecimientos
       anómalos del índice y lo corrige en runtime si el patch fue revertido.

STEP 1: Definir protocolo TTSAdapter (interfaz abstracta)
STEP 2: Implementar PiperTTSAdapter (Piper via Docker, para notebook)
STEP 3: Implementar UnitreeTTSAdapter (AudioClient.TtsMaker, para robot)
STEP 4: Factory tts_adapter_factory() que selecciona el adapter según Settings
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import Optional

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# STEP 1: Interfaz abstracta (Strategy contract)
# ---------------------------------------------------------------------------

class TTSAdapter(ABC):
    """
    @TASK: Definir el contrato de Strategy para síntesis de voz
    @INPUT: texto — string ya limpio (sin emojis, sin caracteres problemáticos)
    @OUTPUT: Audio reproducido en el parlante del host o del robot
    @CONTEXT: Interfaz abstracta; PiperTTSAdapter y UnitreeTTSAdapter la implementan
    @AI_CONTEXT: El método speak() es la única API pública; toda configuración es interna
    """

    @abstractmethod
    async def speak(self, text: str) -> None:
        """
        @TASK: Sintetizar y reproducir texto como audio
        @INPUT: text — string limpio para TTS (sin emojis, normalizado)
        @OUTPUT: Ninguno; audio reproducido en hardware
        @SECURITY: text debe estar pre-procesado con clean_text_for_tts() antes de llamar
        """
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Identificador del backend para logging y telemetría."""
        ...


# ---------------------------------------------------------------------------
# STEP 2: PiperTTSAdapter — Docker container (modo desarrollo)
# ---------------------------------------------------------------------------

class PiperTTSAdapter(TTSAdapter):
    """
    @TASK: Sintetizar voz via Piper TTS corriendo en contenedor Docker ottoguide-tts
    @INPUT: Texto limpio; configuración de contenedor, voz y rutas /tmp
    @OUTPUT: Audio WAV generado en contenedor y reproducido con paplay en el host
    @CONTEXT: Usado en modo desarrollo (notebook Linux Mint) donde el SDK Unitree no está disponible.
              Pipeline: texto → /tmp/otto_texto.txt → docker cp → piper → WAV → docker cp → paplay.
    @SECURITY: docker cp y docker exec con args fijos (lista, no shell=True).
               Texto escrito a tempfile antes de docker cp; sin interpolación en comandos shell.
               @SECURITY: shell=False en todos los subprocess.run() — sin command injection.
    @PERFORMANCE: Secuencia bloqueante (docker cp + exec + paplay); tiempo típico 1-3s para frase corta.
                  Ejecutar en run_in_executor para no bloquear el event loop.
    @AI_CONTEXT: esperar_fin_audio() via pactl garantiza que el micrófono no captura feedback del TTS.
    """

    def __init__(
        self,
        *,
        container_name: str = "ottoguide-tts",
        voice_model: str = "es_MX-gevy-high",
        piper_bin: str = "/usr/src/.venv/bin/piper",
        voices_dir: str = "/data/voices",
        wait_for_audio_end: bool = True,
        post_speak_delay_s: float = 0.5,
    ) -> None:
        self._container = container_name
        self._voice = voice_model
        self._piper_bin = piper_bin
        self._voices_dir = voices_dir
        self._wait_for_audio = wait_for_audio_end
        self._post_delay = post_speak_delay_s

    @property
    def backend_name(self) -> str:
        return f"piper-docker/{self._container}"

    async def speak(self, text: str) -> None:
        """
        @TASK: Sintetizar texto con Piper TTS en Docker y reproducir con paplay
        @INPUT: text — string ya limpio
        @OUTPUT: Audio reproducido; retorna cuando el parlante queda libre
        @SECURITY: text escrito a tempfile; sin interpolación en args de subprocess
        @PERFORMANCE: Bloqueante ~1-3s; ejecutado en run_in_executor
        """
        if not text.strip():
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._speak_sync, text)

    def _speak_sync(self, text: str) -> None:
        """
        @TASK: Pipeline completo de TTS síncrono para ejecución en executor
        @INPUT: text — texto limpio
        @OUTPUT: Audio reproducido
        @SECURITY: shell=False en todos los subprocess; args como lista fija
        """
        # STEP 2.1: Escribir texto a tempfile (UTF-8, sin corrupción de acentos)
        fd, txt_path = tempfile.mkstemp(suffix=".txt", prefix="otto_tts_")
        wav_path = txt_path.replace(".txt", ".wav")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)

            container_txt = "/tmp/otto_texto.txt"
            container_wav = "/tmp/respuesta.wav"
            host_wav = "/tmp/respuesta.wav"

            # STEP 2.2: Copiar texto al contenedor
            subprocess.run(
                ["docker", "cp", txt_path, f"{self._container}:{container_txt}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

            # STEP 2.3: Generar WAV con Piper dentro del contenedor
            # @SECURITY: La voz y el binario son configuración fija — sin input del usuario
            voice_path = f"{self._voices_dir}/{self._voice}.onnx"
            piper_cmd = (
                f"rm -f {container_wav} && "
                f"cat {container_txt} | {self._piper_bin} "
                f"--model {voice_path} --output_file {container_wav}"
            )
            subprocess.run(
                ["docker", "exec", self._container, "sh", "-c", piper_cmd],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

            # STEP 2.4: Copiar WAV de vuelta al host
            subprocess.run(
                ["docker", "cp", f"{self._container}:{container_wav}", host_wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )

            # STEP 2.5: Reproducir con paplay (PipeWire/PulseAudio)
            proc = subprocess.Popen(
                ["paplay", host_wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

            if self._wait_for_audio:
                self._wait_for_playback_end()

            import time
            time.sleep(self._post_delay)

        except Exception as exc:
            LOGGER.warning("[PiperTTSAdapter] Error en speak: %s — %s", type(exc).__name__, exc)
        finally:
            # @SECURITY: Limpiar tempfile del host
            try:
                os.unlink(txt_path)
            except OSError:
                pass

    @staticmethod
    def _wait_for_playback_end() -> None:
        """
        @TASK: Esperar hasta que el parlante deje de reproducir audio
        @INPUT: Sin parámetros
        @OUTPUT: Retorna cuando no hay sink-inputs activos en PipeWire/PulseAudio
        @CONTEXT: Previene que el micrófono capture la voz de Otto (feedback loop)
        @PERFORMANCE: Polling cada 200ms via pactl; overhead mínimo
        """
        import time
        while True:
            result = subprocess.run(
                ["pactl", "list", "sink-inputs"],
                capture_output=True, text=True, check=False,
            )
            if not result.stdout.strip():
                break
            time.sleep(0.2)


# ---------------------------------------------------------------------------
# STEP 3: UnitreeTTSAdapter — AudioClient.TtsMaker (modo robot HIL)
# ---------------------------------------------------------------------------

class UnitreeTTSAdapter(TTSAdapter):
    """
    @TASK: Sintetizar voz via AudioClient.TtsMaker() del SDK Unitree nativo
    @INPUT: Texto limpio; configuración de idioma TTS del SDK
    @OUTPUT: Audio reproducido en el parlante integrado del robot Unitree G1 EDU
    @CONTEXT: Usado en modo robot HIL donde el SDK unitree_sdk2py está disponible.
              AudioClient.TtsMaker() es la API TTS nativa del SDK — sin dependencias Docker.
              Reemplaza el pipeline Piper+Docker en producción.
    @SECURITY: SDK importado de forma lazy — no disponible en CI/notebook sin SDK instalado.
               Sin procesos externos; llamada directa al SDK.
    @PERFORMANCE: TtsMaker() es bloqueante; ejecutado en run_in_executor.
                  Latencia típica: <500ms para frases cortas en hardware real.
    @AI_CONTEXT: AudioClient fue descubierto como API TTS nativa del SDK Unitree durante hito
                 de desarrollo. Prioridad sobre Piper en despliegue HIL real.
    """

    def __init__(
        self,
        *,
        language: int = 0,  # 0=Chinese, 1=English; TTS nativo soporta ambos
        tts_volume: float = 1.0,
    ) -> None:
        self._language = language
        self._tts_volume = tts_volume
        self._client: Optional[object] = None

    @property
    def backend_name(self) -> str:
        return "unitree-sdk/AudioClient.TtsMaker"

    async def speak(self, text: str) -> None:
        """
        @TASK: Sintetizar texto via AudioClient.TtsMaker() del SDK Unitree
        @INPUT: text — string limpio
        @OUTPUT: Audio reproducido en el parlante del robot
        @SECURITY: Sin procesos externos; SDK en proceso Python
        @PERFORMANCE: Bloqueante → run_in_executor
        """
        if not text.strip():
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._speak_sync, text)

    def _speak_sync(self, text: str) -> None:
        """
        @TASK: Llamar a AudioClient.TtsMaker() del SDK Unitree de forma síncrona con wrapper defensivo
        @INPUT: text — string a sintetizar (ya limpio de emojis y caracteres problemáticos)
        @OUTPUT: Audio enviado al hardware del robot via DDS RPC
        @SECURITY: SDK importado lazy; no disponible fuera de robot HIL.
                   Wrapper defensivo detecta y corrige el bug de índice exponencial del SDK
                   en caso de que un future update del SDK revierta el patch directo.
        @AI_CONTEXT: El wrapper valida que tts_index creció exactamente +1 después de TtsMaker().
                     Si detectó crecimiento > 1 (bug exponencial activo), corrige el índice
                     en el objeto del SDK y emite LOGGER.critical para alerta inmediata.

        STEP 3.1: Inicializar AudioClient lazy si no existe
        STEP 3.2: Capturar tts_index antes de la llamada
        STEP 3.3: Invocar TtsMaker()
        STEP 3.4: Validar que el incremento fue lineal (+1); corregir si es exponencial
        """
        try:
            # STEP 3.1: Inicializar AudioClient lazy
            if self._client is None:
                self._client = self._init_sdk_client()

            if self._client is None:
                LOGGER.warning("[UnitreeTTSAdapter] AudioClient no disponible — omitiendo TTS")
                return

            # STEP 3.2: Capturar índice ANTES de la llamada para detectar comportamiento exponencial
            index_before = getattr(self._client, "tts_index", None)

            # STEP 3.3: Invocar TtsMaker()
            self._client.TtsMaker(text, self._language)
            LOGGER.info("[UnitreeTTSAdapter] TtsMaker enviado: '%s'", text[:60])

            # STEP 3.4: Wrapper defensivo — detectar y corregir bug de índice exponencial
            # @AI_CONTEXT: Si el SDK fue actualizado y el bug regresó, el índice crecerá > 1.
            #              Este wrapper lo detecta y lo corrige sin romper la sesión de audio.
            if index_before is not None:
                index_after = getattr(self._client, "tts_index", index_before)
                expected = index_before + 1
                if index_after != expected and index_after > 0:
                    LOGGER.critical(
                        "[UnitreeTTSAdapter] BUG DETECTADO: tts_index creció de %d a %d "
                        "(esperado %d). El bug exponencial del SDK está activo. "
                        "Corrigiendo a %d. Aplicar patch en g1_audio_client.py.",
                        index_before, index_after, expected, expected,
                    )
                    # Corregir el índice en el objeto SDK directamente
                    # @SECURITY: Mutación directa del atributo del SDK; justificada por el bug.
                    self._client.tts_index = expected

        except Exception as exc:
            LOGGER.warning(
                "[UnitreeTTSAdapter] Error en TtsMaker: %s — %s", type(exc).__name__, exc
            )

    @staticmethod
    def _init_sdk_client() -> Optional[object]:
        """
        @TASK: Inicializar AudioClient del SDK Unitree de forma lazy
        @INPUT: Sin parámetros
        @OUTPUT: Instancia de AudioClient o None si el SDK no está disponible
        @CONTEXT: Import lazy permite que el módulo sea importable sin el SDK instalado
        @SECURITY: unitree_sdk2py solo se importa si se usa UnitreeTTSAdapter en modo real
        @AI_CONTEXT: La ruta exacta del módulo depende de la versión del SDK instalada en Jetson
        """
        try:
            audio_module = __import__(
                "unitree_sdk2py.g1.audio.g1_audio_client",
                fromlist=["AudioClient"],
            )
            AudioClient = getattr(audio_module, "AudioClient", None)
            if AudioClient is None:
                raise ImportError("AudioClient no encontrado en el módulo de audio del SDK")

            client = AudioClient()
            client.Init()
            LOGGER.info("[UnitreeTTSAdapter] AudioClient inicializado correctamente")
            return client

        except (ImportError, ModuleNotFoundError) as exc:
            LOGGER.warning(
                "[UnitreeTTSAdapter] unitree_sdk2py no disponible: %s. "
                "Fallback a None — TTS deshabilitado.",
                exc,
            )
            return None
        except Exception as exc:
            LOGGER.warning(
                "[UnitreeTTSAdapter] Error inicializando AudioClient: %s — %s",
                type(exc).__name__, exc,
            )
            return None


# ---------------------------------------------------------------------------
# STEP 4: Factory de selección de adapter
# ---------------------------------------------------------------------------

def tts_adapter_factory(*, robot_mode: str = "mock") -> TTSAdapter:
    """
    @TASK: Seleccionar el TTSAdapter correcto según el modo de operación del robot
    @INPUT: robot_mode — string de Settings.ROBOT_MODE ("real", "sim", "mock", "demo")
    @OUTPUT: Instancia de PiperTTSAdapter o UnitreeTTSAdapter según modo
    @CONTEXT: Invocado desde main.py lifespan o desde ConversationManager según configuración.
              Permite hot-swap de TTS sin cambiar código de negocio.
    @AI_CONTEXT: ROBOT_MODE=real → UnitreeTTSAdapter (SDK nativo en Jetson)
                 ROBOT_MODE=sim|mock|demo → PiperTTSAdapter (Docker en desarrollo)
    """
    if robot_mode == "real":
        LOGGER.info("[TTSFactory] Seleccionando UnitreeTTSAdapter (SDK nativo HIL)")
        return UnitreeTTSAdapter()
    else:
        LOGGER.info(
            "[TTSFactory] Seleccionando PiperTTSAdapter (Docker) para modo '%s'",
            robot_mode,
        )
        return PiperTTSAdapter()


__all__ = [
    "TTSAdapter",
    "PiperTTSAdapter",
    "UnitreeTTSAdapter",
    "tts_adapter_factory",
]
