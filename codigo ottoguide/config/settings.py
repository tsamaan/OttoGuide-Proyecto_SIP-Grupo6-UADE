from __future__ import annotations

# @TASK: Centralizar configuracion del sistema via Pydantic BaseSettings
# @INPUT: Variables de entorno (.env o shell)
# @OUTPUT: Instancia Settings singleton + factory get_hardware_adapter()
# @CONTEXT: Unico punto de configuracion; reemplaza variables dispersas
# @SECURITY: ROBOT_MODE default "mock" — nunca real sin intencion explicita
# STEP 1: Definir Settings con todas las variables del sistema
# STEP 2: Implementar factory get_hardware_adapter() con import lazy
# STEP 3: Validar ROBOT_NETWORK_INTERFACE requerida si ROBOT_MODE=real

import logging
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings

LOGGER = logging.getLogger("otto_guide.config.settings")


class Settings(BaseSettings):
    """
    @TASK: Modelo de configuracion centralizado del sistema OttoGuide
    @INPUT: Variables de entorno ROBOT_MODE, ROBOT_NETWORK_INTERFACE, etc.
    @OUTPUT: Instancia validada con valores por defecto seguros
    @CONTEXT: Pydantic BaseSettings lee automaticamente de .env y shell
    @SECURITY: ROBOT_MODE default "mock" previene inicializacion DDS accidental
    """

    # --- Hardware ---
    ROBOT_MODE: Literal["real", "sim", "mock", "demo"] = "mock"
    ROBOT_NETWORK_INTERFACE: str = ""

    # --- Navigation backend selection (Fase 2H.2) ---
    # @SECURITY: NAVIGATION_DIRECT_REAL_ENABLED default False es un interlock cerrado por
    #            defecto: selecciona el backend "direct" en ROBOT_MODE=real exige habilitarlo
    #            explicitamente. NAVIGATION_ALLOW_STUB_TOURS default False impide despachar
    #            tours autonomos contra un backend no operativo.
    NAVIGATION_BACKEND: Literal["auto", "legacy", "direct", "stub"] = "auto"
    NAVIGATION_DIRECT_REAL_ENABLED: bool = False
    NAVIGATION_ALLOW_STUB_TOURS: bool = False

    NAVIGATION_NODE_NAME: str = "direct_nav2_action_bridge"
    NAVIGATION_NAMESPACE: str = "offline_nav"

    NAVIGATION_NTP_ACTION: str = "/offline_nav/navigate_to_pose"
    NAVIGATION_FW_ACTION: str = "/offline_nav/follow_waypoints"
    NAVIGATION_INITIAL_POSE_TOPIC: str = "/initialpose"

    NAVIGATION_SERVER_TIMEOUT_S: float = 15.0
    NAVIGATION_GOAL_RESPONSE_TIMEOUT_S: float = 10.0
    NAVIGATION_RESULT_TIMEOUT_S: float = 120.0
    NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S: float = 10.0
    NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S: float = 15.0

    # --- NLP / LLM ---
    OLLAMA_HOST: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    # Nombre del modelo personalizado creado via Modelfile (ollama create otto -f Modelfile)
    OLLAMA_OTTO_MODEL: str = "otto"

    # --- API Server ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # --- Unitree factory plane diagnostics (read-only) ---
    UNITREE_FACTORY_DIAGNOSTICS_ENABLED: bool = False
    UNITREE_FACTORY_BASE_URL: str = "http://192.168.12.1:9991"
    UNITREE_FACTORY_TIMEOUT_S: float = 0.35

    # --- Whisper STT (Docker container openai-whisper-asr-webservice) ---
    # @CONTEXT: Puerto 9001 en notebook (Portainer ocupa el 9000); puerto 9000 en robot Jetson
    # @AI_CONTEXT: Configurable via WHISPER_STT_PORT env var; default notebook
    WHISPER_STT_PORT: int = 9001
    WHISPER_STT_HOST: str = "http://localhost"
    WHISPER_STT_TIMEOUT_S: float = 30.0
    WHISPER_STT_LANGUAGE: str = "es"
    WHISPER_SILENCE_THRESHOLD: int = 1000

    # --- Piper TTS (Docker container ottoguide-tts) ---
    # @CONTEXT: Solo usado en modo mock/sim/demo; modo real usa UnitreeTTSAdapter (SDK)
    PIPER_TTS_CONTAINER: str = "ottoguide-tts"
    PIPER_TTS_VOICE: str = "es_MX-gevy-high"
    PIPER_TTS_BIN: str = "/usr/src/.venv/bin/piper"
    PIPER_TTS_VOICES_DIR: str = "/data/voices"

    # --- Audio / Micrófono ---
    # @AI_CONTEXT: plughw:1,0 = notebook Linux Mint; plughw:0,0 = robot Jetson Orin NX
    AUDIO_MIC_DEVICE: str = "plughw:1,0"
    AUDIO_MIC_CHANNELS: str = "1"
    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_WAKE_CYCLE_S: int = 3

    # --- Wake Word / Corrección UADE ---
    # @CONTEXT: "levenshtein" = automático (default); "manual" = usa data/correcciones_uade.json
    UADE_CORRECTION_MODE: str = "levenshtein"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }

    def validate_navigation_config(self) -> None:
        """
        @TASK: Validar la configuracion de navegacion antes de inicializar hardware
        @INPUT: Sin parametros; opera sobre los campos NAVIGATION_* de esta instancia
        @OUTPUT: None si la configuracion es valida; ValueError("NAVIGATION_CONFIG_INVALID:<detalle>") si no
        @CONTEXT: Invocado desde el lifespan de main.py antes de get_hardware_adapter()/rclpy.init().
        @SECURITY: No valida alcanzabilidad de red ni del action server; solo forma de los valores.
        """
        timeouts = (
            ("NAVIGATION_SERVER_TIMEOUT_S", self.NAVIGATION_SERVER_TIMEOUT_S),
            ("NAVIGATION_GOAL_RESPONSE_TIMEOUT_S", self.NAVIGATION_GOAL_RESPONSE_TIMEOUT_S),
            ("NAVIGATION_RESULT_TIMEOUT_S", self.NAVIGATION_RESULT_TIMEOUT_S),
            ("NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S", self.NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S),
            ("NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S", self.NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S),
        )
        for name, value in timeouts:
            if value <= 0:
                raise ValueError(f"NAVIGATION_CONFIG_INVALID:{name}_must_be_positive")

        for name, value in (
            ("NAVIGATION_NTP_ACTION", self.NAVIGATION_NTP_ACTION),
            ("NAVIGATION_FW_ACTION", self.NAVIGATION_FW_ACTION),
        ):
            if not value:
                raise ValueError(f"NAVIGATION_CONFIG_INVALID:{name}_empty")
            if not value.startswith("/"):
                raise ValueError(f"NAVIGATION_CONFIG_INVALID:{name}_not_absolute")

        if not self.NAVIGATION_INITIAL_POSE_TOPIC:
            raise ValueError("NAVIGATION_CONFIG_INVALID:NAVIGATION_INITIAL_POSE_TOPIC_empty")
        if not self.NAVIGATION_INITIAL_POSE_TOPIC.startswith("/"):
            raise ValueError("NAVIGATION_CONFIG_INVALID:NAVIGATION_INITIAL_POSE_TOPIC_not_absolute")

        if not self.NAVIGATION_NAMESPACE:
            raise ValueError("NAVIGATION_CONFIG_INVALID:NAVIGATION_NAMESPACE_empty")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    @TASK: Obtener instancia singleton de Settings
    @INPUT: Sin parametros
    @OUTPUT: Settings cacheada
    @CONTEXT: lru_cache garantiza una sola lectura de .env por proceso
    @SECURITY: Inmutable una vez construida
    """
    return Settings()


def get_hardware_adapter():
    """
    @TASK: Factory de adaptador de hardware basada en ROBOT_MODE
    @INPUT: Settings.ROBOT_MODE y Settings.ROBOT_NETWORK_INTERFACE
    @OUTPUT: Instancia de RobotHardwareInterface (real, sim o mock)
    @CONTEXT: Import lazy — unitree_sdk2py solo se importa si mode=real|sim
    STEP 1: Si ROBOT_MODE=real y ROBOT_NETWORK_INTERFACE vacio → EnvironmentError
    STEP 2: Si ROBOT_MODE=real → importar lazy UnitreeG1Adapter, retornar instancia
    STEP 3: Si ROBOT_MODE=sim → importar lazy UnitreeG1SimAdapter, retornar instancia
              Nota: requiere unitree_mujoco corriendo en domain 1 (loopback)
    STEP 4: Si ROBOT_MODE=mock → importar MockRobotAdapter, retornar instancia
    STEP 5: Cualquier otro valor → ValueError con valores validos listados
    @SECURITY: unitree_sdk2py nunca se importa en modo mock
    """
    settings = get_settings()

    if settings.ROBOT_MODE == "real":
        # STEP 1: Validar interfaz de red
        if not settings.ROBOT_NETWORK_INTERFACE:
            raise EnvironmentError(
                "ROBOT_MODE=real requiere ROBOT_NETWORK_INTERFACE. "
                "Ejemplo: ROBOT_NETWORK_INTERFACE=eth0"
            )

        # STEP 2: Import lazy del adaptador real
        LOGGER.info(
            "[CONFIG] ROBOT_MODE=real. Cargando UnitreeG1Adapter "
            "(interface='%s').",
            settings.ROBOT_NETWORK_INTERFACE,
        )
        from hardware.real_adapter import UnitreeG1Adapter
        return UnitreeG1Adapter()

    if settings.ROBOT_MODE == "sim":
        # STEP 3: Import lazy del adaptador de simulacion
        LOGGER.info(
            "[CONFIG] ROBOT_MODE=sim. Cargando UnitreeG1SimAdapter "
            "(domain_id=1, interface=lo). "
            "Requiere unitree_mujoco corriendo en domain 1."
        )
        from hardware.sim_adapter import UnitreeG1SimAdapter
        return UnitreeG1SimAdapter()

    if settings.ROBOT_MODE in ("mock", "demo"):
        # STEP 4: Modo mock/demo (default)
        LOGGER.info(
            "[CONFIG] ROBOT_MODE=%s. Cargando MockHardwareAPI.",
            settings.ROBOT_MODE,
        )
        from hardware.mock_adapter import MockHardwareAPI
        return MockHardwareAPI()

    # STEP 5: Modo no reconocido
    raise ValueError(
        f"ROBOT_MODE='{settings.ROBOT_MODE}' no es valido. "
        "Valores validos: 'real', 'sim', 'mock', 'demo'."
    )


__all__ = [
    "Settings",
    "get_hardware_adapter",
    "get_settings",
]
