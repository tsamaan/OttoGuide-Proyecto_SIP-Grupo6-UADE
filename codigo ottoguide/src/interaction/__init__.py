from .audio_bridge import AudioHardwareBridge
from .conversation_manager import (
    CloudNLPPipeline,
    ConversationManager,
    ConversationRequest,
    ConversationResponse,
    LocalNLPPipeline,
    NLPStrategy,
)
from .llm_client import OllamaAsyncClient
from .wake_word_detector import (
    WakeWordDetector,
    clean_text_for_tts,
    correct_uade_transcription,
    load_uade_corrections,
    WAKE_WORDS,
    FAREWELL_WORDS,
)
from .stt_whisper_client import WhisperSTTClient
from .tts_unitree_client import (
    TTSAdapter,
    PiperTTSAdapter,
    UnitreeTTSAdapter,
    tts_adapter_factory,
)

__all__ = [
    # Audio hardware bridge
    "AudioHardwareBridge",
    # Conversation pipeline (Strategy pattern)
    "CloudNLPPipeline",
    "ConversationManager",
    "ConversationRequest",
    "ConversationResponse",
    "LocalNLPPipeline",
    "NLPStrategy",
    # LLM client
    "OllamaAsyncClient",
    # Wake word detection (migrado de OttoGuide IA/)
    "WakeWordDetector",
    "clean_text_for_tts",
    "correct_uade_transcription",
    "load_uade_corrections",
    "WAKE_WORDS",
    "FAREWELL_WORDS",
    # STT adapter async (migrado de OttoGuide IA/)
    "WhisperSTTClient",
    # TTS adapters — Strategy pattern (Piper + SDK Unitree)
    "TTSAdapter",
    "PiperTTSAdapter",
    "UnitreeTTSAdapter",
    "tts_adapter_factory",
]